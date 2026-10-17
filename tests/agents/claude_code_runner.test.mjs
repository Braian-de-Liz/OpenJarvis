// Unit tests for the pure helpers of the Claude Code runner.
// Run with: node --test tests/agents/claude_code_runner.test.mjs
// They never start the Claude Agent SDK, so no plan quota is used.

import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

// Importing the runner must not start it (it would wait on stdin).
process.env.OPENJARVIS_RUNNER_NO_MAIN = "1";
const here = path.dirname(fileURLToPath(import.meta.url));
const runnerUrl = pathToFileURL(
  path.resolve(here, "..", "..", "src", "openjarvis", "agents", "claude_code_runner", "index.mjs"),
).href;
const {
  buildQueryOptions,
  CHAT_ISOLATION_ENV,
  defaultChatWorkspace,
  scrubbedEnv,
  summarizeInit,
} = await import(runnerUrl);

const SOURCE_ENV = {
  PATH: "/usr/bin",
  HOME: "/home/user",
  ANTHROPIC_API_KEY: "sk-secret",
  ANTHROPIC_AUTH_TOKEN: "tok",
  CLAUDE_CODE_OAUTH_TOKEN: "oauth",
  CLAUDE_CODE_USE_BEDROCK: "1",
  AWS_BEARER_TOKEN_BEDROCK: "aws",
  CLAUDECODE: "1",
};

const CHAT = { mode: "chat", prompt: "oi", workspace: "/projeto" };
const NEUTRAL = path.resolve("/neutro/claude_chat_workspace");

test("chat mode isolates MCP servers, connectors and auto-memory", () => {
  const o = buildQueryOptions(CHAT, SOURCE_ENV, { chatWorkspace: NEUTRAL });

  // strictMcpConfig is what actually isolates; `mcpServers: {}` alone does not.
  assert.equal(o.strictMcpConfig, true);
  assert.deepEqual(o.mcpServers, {});
  assert.equal(o.env.ENABLE_CLAUDEAI_MCP_SERVERS, "false");
  assert.equal(o.env.CLAUDE_CODE_DISABLE_AUTO_MEMORY, "1");
  assert.deepEqual(o.settingSources, []);
  assert.deepEqual(o.tools, []);
  assert.equal(o.maxTurns, 2);
  assert.equal(o.permissionMode, "dontAsk");
  assert.equal(o.systemPrompt, "Responda de forma curta e direta.");
});

test("chat mode runs from the neutral folder, not the project", () => {
  const o = buildQueryOptions(CHAT, SOURCE_ENV, { chatWorkspace: NEUTRAL });
  assert.equal(o.cwd, NEUTRAL);
  assert.notEqual(o.cwd, CHAT.workspace);
});

test("chat mode falls back to the default neutral folder", () => {
  const o = buildQueryOptions(CHAT, SOURCE_ENV);
  assert.equal(o.cwd, defaultChatWorkspace());
  assert.equal(path.basename(o.cwd), "claude_chat_workspace");
});

test("chat mode keeps a custom system prompt", () => {
  const request = { ...CHAT, system_prompt: "Você é o JARVIS." };
  const o = buildQueryOptions(request, SOURCE_ENV, { chatWorkspace: NEUTRAL });
  assert.equal(o.systemPrompt, "Você é o JARVIS.");
});

test("credentials stay blocked in every mode", () => {
  for (const request of [CHAT, { mode: "agent", prompt: "x", workspace: "/p" }]) {
    const o = buildQueryOptions(request, SOURCE_ENV, { chatWorkspace: NEUTRAL });
    for (const key of [
      "ANTHROPIC_API_KEY",
      "ANTHROPIC_AUTH_TOKEN",
      "CLAUDE_CODE_OAUTH_TOKEN",
      "CLAUDE_CODE_USE_BEDROCK",
      "AWS_BEARER_TOKEN_BEDROCK",
      "CLAUDECODE",
    ]) {
      assert.ok(!(key in o.env), `${key} must not reach the SDK (${request.mode})`);
    }
    assert.equal(o.env.PATH, "/usr/bin");
  }
});

test("scrubbedEnv itself does not add the isolation variables", () => {
  const env = scrubbedEnv(SOURCE_ENV);
  assert.ok(!("ENABLE_CLAUDEAI_MCP_SERVERS" in env));
  assert.deepEqual(CHAT_ISOLATION_ENV, {
    ENABLE_CLAUDEAI_MCP_SERVERS: "false",
    CLAUDE_CODE_DISABLE_AUTO_MEMORY: "1",
  });
});

test("agent mode is untouched (read-only default)", () => {
  const request = { mode: "agent", prompt: "x", workspace: "/proj", permission: "read" };
  const o = buildQueryOptions(request, SOURCE_ENV, { chatWorkspace: NEUTRAL });

  assert.equal(o.strictMcpConfig, undefined);
  assert.equal(o.mcpServers, undefined);
  assert.ok(!("ENABLE_CLAUDEAI_MCP_SERVERS" in o.env));
  assert.ok(!("CLAUDE_CODE_DISABLE_AUTO_MEMORY" in o.env));
  assert.equal(o.cwd, "/proj");
  assert.equal(o.maxTurns, 30);
  assert.deepEqual(o.settingSources, ["user"]);
  assert.deepEqual(o.tools, ["Read", "Glob", "Grep", "WebSearch", "WebFetch"]);
  assert.equal(o.permissionMode, "dontAsk");
});

test("agent mode ask/free still ignores user settings and asks", () => {
  for (const permission of ["ask", "free"]) {
    const request = { mode: "agent", prompt: "x", workspace: "/proj", permission };
    const o = buildQueryOptions(request, SOURCE_ENV, { chatWorkspace: NEUTRAL });
    assert.equal(o.permissionMode, "default");
    assert.deepEqual(o.settingSources, []);
    assert.equal(o.strictMcpConfig, undefined);
    assert.equal(o.cwd, "/proj");
  }
});

test("model and session id are forwarded in chat mode", () => {
  const request = { ...CHAT, model: "haiku", session_id: "abc" };
  const o = buildQueryOptions(request, SOURCE_ENV, { chatWorkspace: NEUTRAL });
  assert.equal(o.model, "haiku");
  assert.equal(o.sessionId, "abc");
});

test("summarizeInit reports names and counts only", () => {
  const out = summarizeInit({
    model: "claude-sonnet",
    tools: ["Read", { name: "mcp__x__do" }],
    mcp_servers: [
      { name: "meu-mcp", status: "connected", command: "npx", env: { TOKEN: "secret" } },
    ],
    plugins: [{ name: "plug", path: "C:/Users/me/.claude/plugins/plug" }],
    skills: ["a", "b"],
    slash_commands: ["/x", "/y", "/z"],
    apiKeySource: "none",
  });
  assert.deepEqual(out, {
    type: "context_debug",
    model: "claude-sonnet",
    tools: ["Read", "mcp__x__do"],
    mcp_servers: [{ name: "meu-mcp", status: "connected" }],
    plugins: ["plug"],
    skills: 2,
    slash_commands: 3,
  });
  const text = JSON.stringify(out);
  assert.ok(!text.includes("secret"));
  assert.ok(!text.includes("C:/Users"));
});

test("summarizeInit tolerates a bare init message", () => {
  const out = summarizeInit({});
  assert.deepEqual(out.tools, []);
  assert.deepEqual(out.mcp_servers, []);
  assert.deepEqual(out.plugins, []);
  assert.equal(out.skills, 0);
  assert.equal(out.slash_commands, 0);
});
