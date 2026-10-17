/**
 * OpenJarvis Claude Agent SDK runner.
 *
 * Reads one JSON request from stdin and writes one sentinel-delimited JSON
 * response to stdout.
 */

import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const OUTPUT_START = "---OPENJARVIS_OUTPUT_START---";
const OUTPUT_END = "---OPENJARVIS_OUTPUT_END---";
// One JSON event per line, emitted while the query runs so the host can show
// text and tool progress live. The final sentinel block below is unchanged.
const EVENT_PREFIX = "---OJ_EVENT--- ";

function emitEvent(event) {
  console.log(EVENT_PREFIX + JSON.stringify(event));
}

// Credential sources other than the Claude Code login. All are removed so the
// SDK cannot silently fall back to token billing (API key, third-party cloud
// providers, custom endpoints, helper scripts).
const BLOCKED_ENV = new Set([
  "CLAUDE_CODE_OAUTH_TOKEN",
  "CLAUDE_CODE_API_KEY_HELPER_TTL_MS",
  "AWS_BEARER_TOKEN_BEDROCK",
]);

// Variables of the Claude Code session that happened to launch the server
// (e.g. started from a terminal inside Claude Code). The runner is its own
// independent session; inheriting these could tie it to that parent session.
const PARENT_SESSION_ENV = new Set(["CLAUDECODE", "AI_AGENT", "CLAUDE_PID"]);
const PARENT_SESSION_PREFIXES = [
  "CLAUDE_CODE_SESSION_",
  "CLAUDE_CODE_CHILD_SESSION",
  "CLAUDE_CODE_MESSAGING_",
  "CLAUDE_CODE_ENTRYPOINT",
  "CLAUDE_CODE_SSE_PORT",
];

export function scrubbedEnv(source) {
  const env = {};
  for (const [key, value] of Object.entries(source)) {
    if (key.startsWith("ANTHROPIC_")) continue;
    if (key.startsWith("CLAUDE_CODE_USE_")) continue;
    if (BLOCKED_ENV.has(key)) continue;
    if (PARENT_SESSION_ENV.has(key)) continue;
    if (PARENT_SESSION_PREFIXES.some((p) => key.startsWith(p))) continue;
    env[key] = value;
  }
  return env;
}

// `apiKeySource` reported by the SDK's init message. "none" means the Claude
// Code login (claude.ai) is the credential; anything else is a key source.
const ALLOWED_KEY_SOURCES = new Set(["none", "oauth"]);

function emitResult(response) {
  console.log(OUTPUT_START);
  console.log(JSON.stringify(response));
  console.log(OUTPUT_END);
}

function emitError(message) {
  emitResult({ content: message, tool_results: [], metadata: { error: true } });
  console.error(message);
}

// stdin protocol: the first line is the JSON request; later lines are the
// host's answers to permission questions ({"type":"permission_decision",
// "id":..., "allow":true|false}). A request sent without a trailing newline and
// followed by EOF (the non-interactive path) works too.
function openStdin() {
  process.stdin.setEncoding("utf-8");
  let buf = "";
  let gotRequest = false;
  let ended = false;
  let resolveRequest;
  let rejectRequest;
  const request = new Promise((resolve, reject) => {
    resolveRequest = resolve;
    rejectRequest = reject;
  });
  const waiting = new Map();

  const handleLine = (line) => {
    if (!line.trim()) return;
    if (!gotRequest) {
      gotRequest = true;
      resolveRequest(line);
      return;
    }
    try {
      const message = JSON.parse(line);
      if (message.type === "permission_decision" && waiting.has(message.id)) {
        waiting.get(message.id)(message.allow === true);
        waiting.delete(message.id);
      }
    } catch {
      // not a decision: ignore
    }
  };

  process.stdin.on("data", (chunk) => {
    buf += chunk;
    let newline;
    while ((newline = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, newline);
      buf = buf.slice(newline + 1);
      handleLine(line);
    }
  });
  process.stdin.on("end", () => {
    ended = true;
    if (buf.trim()) handleLine(buf);
    buf = "";
    if (!gotRequest) rejectRequest(new Error("empty stdin"));
    // The host went away: nobody can approve anything any more.
    for (const resolve of waiting.values()) resolve(false);
    waiting.clear();
  });

  return {
    request,
    // Resolves true only on an explicit approval; timeout/EOF mean "no".
    decision(id, timeoutMs) {
      if (ended) return Promise.resolve(false);
      return new Promise((resolve) => {
        const timer = setTimeout(() => {
          waiting.delete(id);
          resolve(false);
        }, timeoutMs);
        waiting.set(id, (allow) => {
          clearTimeout(timer);
          resolve(allow);
        });
      });
    },
    close() {
      process.stdin.destroy();
    },
  };
}

// Long strings (file contents) are cut before they travel to the HUD.
function trimInput(input) {
  const out = {};
  for (const [key, value] of Object.entries(input || {})) {
    out[key] =
      typeof value === "string" && value.length > 2000
        ? `${value.slice(0, 2000)}… [${value.length} caracteres]`
        : value;
  }
  return out;
}

function makeCanUseTool(request, channel) {
  return async (toolName, input, context) => {
    if (permissionPolicy(request.permission, toolName, input, request.workspace) === "allow") {
      return { behavior: "allow", updatedInput: input };
    }
    if (!request.interactive) {
      return {
        behavior: "deny",
        message: "Sem canal de aprovação nesta execução; a ação foi negada.",
      };
    }
    const id = randomUUID().replace(/-/g, "").slice(0, 12);
    emitEvent({
      type: "permission_request",
      id,
      tool: toolName,
      input: trimInput(input),
      reason: context?.decisionReason || "",
      blocked_path: context?.blockedPath || "",
    });
    const allowed = await channel.decision(id, PERMISSION_WAIT_MS);
    return allowed
      ? { behavior: "allow", updatedInput: input }
      : { behavior: "deny", message: "O usuário negou esta ação (ou não respondeu a tempo)." };
  };
}

function serializeContent(content) {
  return typeof content === "string" ? content : JSON.stringify(content ?? "");
}

// Tool policy. `allowedTools` in the SDK only PRE-APPROVES tools; it does not
// limit which ones exist. Availability is set with `tools` / `disallowedTools`.
//
// Three agent permission modes (request.permission):
//   read - read, search and browse only; nothing else exists. (default)
//   ask  - may also edit files and run commands, but EVERY such action is sent
//          to the user for approval first.
//   free - edits and commands inside the project folder run without asking,
//          unless risky; anything outside it, or risky, still asks.
// In all modes reading/searching is pre-approved and the host (HUD) is the
// only one who can answer a question, so without a channel "ask" means "deny".
const READ_ONLY_TOOLS = ["Read", "Glob", "Grep", "WebSearch", "WebFetch"];
const WRITE_TOOLS = ["Edit", "Write", "NotebookEdit", "Bash"];
const BLOCKED_TOOLS = [
  "Bash",
  "BashOutput",
  "KillShell",
  "Edit",
  "Write",
  "NotebookEdit",
  "Task",
];
// How long to wait for the user before denying (the host denies a bit earlier).
const PERMISSION_WAIT_MS = 200000;
const FILE_TOOLS = new Set(["Edit", "Write", "NotebookEdit"]);

export function toolOptions(request) {
  const base = { permissionMode: "dontAsk" };
  if (request.mode === "chat") return { ...base, tools: [] };
  const explicit = (request.allowed_tools || []).filter(Boolean);
  if (explicit.length) {
    return { ...base, tools: explicit, allowedTools: explicit };
  }
  const permission = request.permission || "read";
  if (permission === "ask" || permission === "free") {
    // Reads are pre-approved; everything else reaches canUseTool.
    return {
      permissionMode: "default",
      tools: [...READ_ONLY_TOOLS, ...WRITE_TOOLS],
      allowedTools: READ_ONLY_TOOLS,
      disallowedTools: ["BashOutput", "KillShell", "Task"],
    };
  }
  return {
    ...base,
    tools: READ_ONLY_TOOLS,
    allowedTools: READ_ONLY_TOOLS,
    disallowedTools: BLOCKED_TOOLS,
  };
}

function isInside(workspace, target) {
  if (!workspace || !target) return false;
  const win = process.platform === "win32";
  const norm = (value) => {
    const resolved = path.resolve(workspace, value);
    return win ? resolved.toLowerCase() : resolved;
  };
  const rel = path.relative(norm(workspace), norm(target));
  return rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel));
}

// Files that deserve a question even inside the project.
const SENSITIVE_PATH =
  /(^|[\/])(\.git|\.claude|\.ssh|\.aws|\.gnupg)([\/]|$)|(^|[\/])(\.env[^\/]*|\.npmrc|\.pypirc|id_rsa[^\/]*|credentials[^\/]*|[^\/]*\.(pem|key|pfx))$/i;

// Shell commands that always ask in "free" mode: deleting, installing,
// publishing, networking, privilege/process/registry control, inline code and
// anything that pipes into a shell. Best effort, NOT a sandbox.
const RISKY_SHELL = [
  /\b(rm|rmdir|del|erase|rd|mv|move|ren|rename|cp -r|xcopy|robocopy)\b/i,
  /\b(format|mkfs|dd|diskpart|fdisk)\b/i,
  /\bRemove-Item\b|\bSet-Content\b|\bOut-File\b|\bNew-Item\b|\bMove-Item\b/i,
  /\bgit\s+(push|reset|clean|rebase|checkout\s+--|branch\s+-D|stash\s+(drop|clear)|remote|config|filter-branch|update-ref)\b/i,
  /\b(npm|pnpm|yarn|bun|pip|pip3|pipx|uv|poetry|cargo|go|gem|composer|winget|choco|scoop|apt|apt-get|brew|dotnet)\s+(install|add|remove|uninstall|publish|upgrade|update|tool|sync|pip|exec|dlx|x|i)\b/i,
  /\b(npx|bunx|pnpx|uvx)\b/i,
  /\b(curl|wget|iwr|irm|Invoke-WebRequest|Invoke-RestMethod|nc|ncat|ssh|scp|ftp|telnet)\b/i,
  /\b(sudo|su|runas|shutdown|reboot|restart-computer|taskkill|kill|pkill|killall|reg|regedit|schtasks|sc|net|netsh|setx|chmod|chown|icacls|takeown|attrib)\b/i,
  /\b(eval|exec|source|start-process|invoke-expression|iex)\b/i,
  /\b(python[0-9.]*|py|node|deno|perl|ruby|php|powershell|pwsh|cmd|bash|sh|zsh)\b\s+(-c|-e|-command|-encodedcommand|\/c)\b/i,
  /\|\s*(sh|bash|zsh|pwsh|powershell|cmd|python[0-9.]*|node)\b/i,
  /\$\(|`/,
  />>?\s*(?!\/dev\/null|nul\b|\$null|&)\S/i,
  /(^|[\s"'=])\.\.([\/]|$)/,
];

function absolutePathTokens(command) {
  const tokens = command.split(/[\s"'`|&;<>()]+/).filter(Boolean);
  const found = [];
  for (let token of tokens) {
    token = token.replace(/^--?[\w-]+=/, "");
    if (!token || /^[a-z][a-z0-9+.-]*:\/\//i.test(token)) continue; // URLs
    if (token === "/dev/null" || /^nul$/i.test(token)) continue;
    const drive = /^\/([a-zA-Z])\/(.*)$/.exec(token); // git-bash: /c/Users/...
    if (drive) token = `${drive[1].toUpperCase()}:/${drive[2]}`;
    if (/^([a-zA-Z]:[\/]|\\|\/|~[\/]?|%[A-Za-z_]+%|\$[A-Za-z_{]|\$HOME|\$env:)/.test(token)) {
      found.push(token);
    }
  }
  return found;
}

// "allow" runs without asking; "ask" needs the user's approval.
function permissionPolicy(permission, toolName, input, workspace) {
  if (permission !== "free") return "ask";
  if (FILE_TOOLS.has(toolName)) {
    const target = input?.file_path || input?.notebook_path || "";
    if (!target || !isInside(workspace, target)) return "ask";
    return SENSITIVE_PATH.test(target) ? "ask" : "allow";
  }
  if (toolName === "Bash") {
    const command = String(input?.command || "");
    if (!command.trim() || RISKY_SHELL.some((re) => re.test(command))) return "ask";
    for (const token of absolutePathTokens(command)) {
      if (/^(~|%|\$)/.test(token) || !isInside(workspace, token)) return "ask";
    }
    return SENSITIVE_PATH.test(command) ? "ask" : "allow";
  }
  return "ask";
}

// Conversation mode runs from a dedicated, empty folder next to the runner
// (``~/.openjarvis/claude_chat_workspace``) so no project files, CLAUDE.md or
// per-folder auto-memory can be picked up from wherever the server started.
export function defaultChatWorkspace() {
  const here = path.dirname(fileURLToPath(import.meta.url));
  return path.resolve(here, "..", "claude_chat_workspace");
}

// Everything `settingSources: []` and `tools: []` do NOT switch off. Per the
// Agent SDK docs, the Claude Code process still reads ~/.claude.json (user
// MCP servers), loads the claude.ai MCP connectors of the logged-in account
// and injects auto-memory into the system prompt. Each of those adds its own
// tokens to every conversation message, so chat mode turns them all off:
//   strictMcpConfig            only use the servers in `mcpServers` ({}), ignoring
//                              user settings, plugin MCPs and claude.ai connectors
//                              (`mcpServers: {}` alone does NOT do this)
//   ENABLE_CLAUDEAI_MCP_SERVERS=false   belt and braces for the connectors
//   CLAUDE_CODE_DISABLE_AUTO_MEMORY=1   no MEMORY.md in the system prompt
export const CHAT_ISOLATION_ENV = {
  ENABLE_CLAUDEAI_MCP_SERVERS: "false",
  CLAUDE_CODE_DISABLE_AUTO_MEMORY: "1",
};

// Pure: builds the `query()` options for a request. ``sourceEnv`` is the raw
// process environment; credentials are scrubbed here so every path goes
// through the same filter. ``canUseTool`` is attached by the caller.
export function buildQueryOptions(request, sourceEnv, { chatWorkspace } = {}) {
  const env = scrubbedEnv(sourceEnv);
  const options = {
    maxTurns: 30,
    includePartialMessages: true,
    env,
    // Do not load project/local settings: their `env` block or apiKeyHelper
    // could inject an API key behind our back.
    settingSources: ["user"],
  };
  if (request.workspace) {
    options.cwd = request.workspace;
  }
  if (request.system_prompt) {
    options.systemPrompt = request.system_prompt;
  }
  Object.assign(options, toolOptions(request));
  if (request.session_id) {
    options.sessionId = request.session_id;
  }
  if (request.model) {
    // Claude model chosen in the HUD ("sonnet", "opus", "haiku" or a full id).
    options.model = request.model;
  }
  if (options.permissionMode === "default") {
    // A user-level `allow` rule would let tools run without ever reaching
    // canUseTool, so the questions could be skipped. Ignore user settings here.
    options.settingSources = [];
  }
  if (request.mode === "chat") {
    // Conversation mode: no tools, no user settings, no MCP servers (own or
    // claude.ai connectors), no auto-memory, a neutral folder and a short
    // system prompt. Only the system prompt and the message reach the model.
    options.settingSources = [];
    options.maxTurns = 2;
    options.strictMcpConfig = true;
    options.mcpServers = {};
    options.env = { ...env, ...CHAT_ISOLATION_ENV };
    options.cwd = chatWorkspace || defaultChatWorkspace();
    if (!options.systemPrompt) {
      options.systemPrompt = "Responda de forma curta e direta.";
    }
  }
  return options;
}

// Opt-in diagnostics (OPENJARVIS_CLAUDE_DEBUG_CONTEXT=1): what the SDK's init
// message says was loaded for this session. Names and counts only; paths,
// env, args and URLs of MCP servers or plugins are never copied.
const DEBUG_LIST_LIMIT = 50;

function names(list, pick) {
  if (!Array.isArray(list)) return [];
  return list
    .map((item) => String(typeof item === "string" ? item : (item && pick(item)) || ""))
    .filter(Boolean)
    .slice(0, DEBUG_LIST_LIMIT);
}

export function summarizeInit(message) {
  const mcp = Array.isArray(message.mcp_servers) ? message.mcp_servers : [];
  return {
    type: "context_debug",
    model: String(message.model || ""),
    tools: names(message.tools, (t) => t.name),
    mcp_servers: mcp.slice(0, DEBUG_LIST_LIMIT).map((s) => ({
      name: String((s && s.name) || ""),
      status: String((s && s.status) || ""),
    })),
    plugins: names(message.plugins, (p) => p.name),
    skills: Array.isArray(message.skills) ? message.skills.length : 0,
    slash_commands: Array.isArray(message.slash_commands)
      ? message.slash_commands.length
      : 0,
  };
}

async function main() {
  const channel = openStdin();
  let request;
  try {
    request = JSON.parse(await channel.request);
  } catch (error) {
    emitError(`Failed to parse input: ${error}`);
    process.exitCode = 1;
    channel.close();
    return;
  }

  // Subscription only: never bill an API key. The SDK then authenticates with
  // the local Claude Code login (claude.ai account), so usage counts against
  // the Claude Code plan limit. request.api_key is intentionally ignored.
  const debugContext = process.env.OPENJARVIS_CLAUDE_DEBUG_CONTEXT === "1";
  const options = buildQueryOptions(request, process.env);
  for (const key of Object.keys(process.env)) {
    if (!(key in options.env)) delete process.env[key];
  }
  if (options.permissionMode === "default") {
    options.canUseTool = makeCanUseTool(request, channel);
  }
  if (request.mode === "chat") {
    try {
      fs.mkdirSync(options.cwd, { recursive: true });
    } catch {
      // the SDK reports a missing folder itself
    }
  }

  // Loaded here, not at the top, so the pure helpers above can be imported
  // (and unit-tested) without the SDK being installed.
  const { query } = await import("@anthropic-ai/claude-agent-sdk");

  let content = "";
  let messageCount = 0;
  let streamedText = false;
  let usage;
  let modelInUse;
  let resultInfo;
  const toolResults = [];
  const toolUseIndexes = new Map();

  try {
    for await (const message of query({ prompt: request.prompt, options })) {
      messageCount += 1;

      if (message.type === "system" && message.subtype === "init") {
        if (!ALLOWED_KEY_SOURCES.has(message.apiKeySource)) {
          throw new Error(
            `Refusing to run: credential source is "${message.apiKeySource}", ` +
              "not the Claude Code login. API keys are never used by OpenJarvis.",
          );
        }
        if (message.model) {
          modelInUse = message.model;
          emitEvent({ type: "model", model: message.model });
        }
        if (debugContext) emitEvent(summarizeInit(message));
      } else if (message.type === "stream_event" && !message.parent_tool_use_id) {
        const delta = message.event?.delta;
        if (
          message.event?.type === "content_block_start" &&
          message.event.content_block?.type === "text"
        ) {
          // Separate text blocks from different turns (text, tool, more text).
          if (streamedText) emitEvent({ type: "text_delta", text: "\n\n" });
        } else if (
          message.event?.type === "content_block_delta" &&
          delta?.type === "text_delta" &&
          delta.text
        ) {
          streamedText = true;
          emitEvent({ type: "text_delta", text: delta.text });
        }
      } else if (message.type === "assistant") {
        const blocks = Array.isArray(message.message?.content)
          ? message.message.content
          : [];
        for (const block of blocks) {
          if (block.type === "text") {
            content = block.text;
          } else if (block.type === "tool_use") {
            emitEvent({
              type: "tool_start",
              id: block.id,
              tool: block.name,
              input: block.input,
            });
            toolUseIndexes.set(block.id, toolResults.length);
            toolResults.push({
              tool_name: block.name,
              content: serializeContent(block.input),
              success: true,
            });
          }
        }
      } else if (message.type === "user") {
        const blocks = Array.isArray(message.message?.content)
          ? message.message.content
          : [];
        for (const block of blocks) {
          if (block.type !== "tool_result") {
            continue;
          }
          emitEvent({
            type: "tool_end",
            id: block.tool_use_id,
            success: !block.is_error,
            content: serializeContent(block.content).slice(0, 2000),
          });
          const index = toolUseIndexes.get(block.tool_use_id);
          if (index !== undefined) {
            toolResults[index].content = serializeContent(block.content);
            toolResults[index].success = !block.is_error;
          }
        }
      } else if (message.type === "result") {
        if (message.is_error || message.subtype !== "success") {
          const errorMessage =
            message.subtype === "success"
              ? message.result
              : message.errors?.join("\n");
          throw new Error(errorMessage || "Claude query failed");
        }
        content = message.result || content;
        usage = message.usage;
        // Cost breakdown: lets the host see turns and per-model usage.
        resultInfo = {
          num_turns: message.num_turns,
          total_cost_usd: message.total_cost_usd,
          model_usage: message.modelUsage,
        };
      }
    }

    emitResult({
      content,
      tool_results: toolResults,
      metadata: {
        message_count: messageCount,
        session_id: request.session_id || undefined,
        usage,
        model: modelInUse,
        ...(resultInfo || {}),
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    emitError(`Claude Agent SDK error: ${message}`);
    process.exitCode = 1;
  } finally {
    channel.close();
  }
}

// Tests import this file for the pure helpers and set this to skip the run.
if (process.env.OPENJARVIS_RUNNER_NO_MAIN !== "1") {
  await main();
}
