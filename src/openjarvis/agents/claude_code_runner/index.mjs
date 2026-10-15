/**
 * OpenJarvis Claude Agent SDK runner.
 *
 * Reads one JSON request from stdin and writes one sentinel-delimited JSON
 * response to stdout.
 */

import { query } from "@anthropic-ai/claude-agent-sdk";

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

function scrubbedEnv(source) {
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

async function readStdin() {
  let data = "";
  process.stdin.setEncoding("utf-8");
  for await (const chunk of process.stdin) {
    data += chunk;
  }
  return data;
}

function serializeContent(content) {
  return typeof content === "string" ? content : JSON.stringify(content ?? "");
}

async function main() {
  let request;
  try {
    request = JSON.parse(await readStdin());
  } catch (error) {
    emitError(`Failed to parse input: ${error}`);
    process.exitCode = 1;
    return;
  }

  // Subscription only: never bill an API key. The SDK then authenticates with
  // the local Claude Code login (claude.ai account), so usage counts against
  // the Claude Code plan limit. request.api_key is intentionally ignored.
  const env = scrubbedEnv(process.env);
  for (const key of Object.keys(process.env)) {
    if (!(key in env)) delete process.env[key];
  }

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
  if (request.allowed_tools?.length) {
    options.allowedTools = request.allowed_tools;
  }
  if (request.session_id) {
    options.sessionId = request.session_id;
  }
  if (request.model) {
    // Claude model chosen in the HUD ("sonnet", "opus", "haiku" or a full id).
    options.model = request.model;
  }
  if (request.mode === "chat") {
    // Conversation mode: no tools, no user settings and a short system prompt.
    // This cuts the fixed per-message context from ~22k tokens to a few hundred.
    options.tools = [];
    options.settingSources = [];
    options.maxTurns = 2;
    delete options.allowedTools;
    if (!options.systemPrompt) {
      options.systemPrompt = "Responda de forma curta e direta.";
    }
  }

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
  }
}

await main();
