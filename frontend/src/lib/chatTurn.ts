import { useAppStore, generateId } from './store';
import { streamChat } from './sse';
import { fetchSavings } from './api';
import { serializeToolCallArguments } from './tool-call';
import { engineFromCompletionChunk, resolveChatEngine } from './chat-telemetry';
import type { ChatMessage, MessageTelemetry, TokenUsage, ToolCallInfo } from '../types';
import { useHudSettings } from './hudSettings';
import { isClaudeCode, requestModel } from './aiSource';

export interface ChatTurnResult {
  conversationId: string;
  content: string;
  aborted: boolean;
}

/**
 * Send one chat turn through `/v1/chat/completions` and stream the reply into
 * the shared store (same conversation, stream state and logs as the Chat page).
 *
 * This is the non-research path of `InputArea.sendMessage`, as a plain
 * function so surfaces without the chat composer (the JARVIS HUD) can drive a
 * real turn. Returns `null` when nothing was sent (empty input, no model, or
 * another stream in flight).
 */
export async function sendChatTurn(
  text: string,
  signal?: AbortSignal,
): Promise<ChatTurnResult | null> {
  const content = text.trim();
  const store = useAppStore.getState();
  const model = store.selectedModel;
  if (!content || !model || store.streamState.isStreaming) return null;

  const convId = store.activeId ?? store.createConversation(model);
  const { temperature, maxTokens } = store.settings;
  // Claude Code: the HUD's Claude model choice rides on the model id.
  const hudSettings = useHudSettings.getState().hud;
  const sentModel = requestModel(model, hudSettings.claudeModel, hudSettings.claudeAgentMode);

  const userMsg: ChatMessage = { id: generateId(), role: 'user', content, timestamp: Date.now() };
  store.addMessage(convId, userMsg);
  const apiMessages = useAppStore.getState().messages.map((m) => ({ role: m.role, content: m.content }));
  store.addMessage(convId, { id: generateId(), role: 'assistant', content: '', timestamp: Date.now() });

  const startTime = Date.now();
  const timer = setInterval(() => store.setStreamState({ elapsedMs: Date.now() - startTime }), 100);
  store.setStreamState({
    conversationId: convId,
    isStreaming: true,
    phase: 'Generating...',
    elapsedMs: 0,
    activeToolCalls: [],
    content: '',
  });
  store.addLogEntry({
    timestamp: Date.now(),
    level: 'info',
    category: 'chat',
    message: `Request (JARVIS): "${content.slice(0, 80)}${content.length > 80 ? '...' : ''}" → ${model}`,
  });

  let accumulated = '';
  let usage: TokenUsage | undefined;
  let routedEngine: string | undefined;
  let ttftMs: number | undefined;
  let modelInUse: string | undefined;
  let aborted = false;
  let lastFlush = 0;
  const toolCalls: ToolCallInfo[] = [];
  const update = (calls?: ToolCallInfo[]) =>
    useAppStore.getState().updateLastAssistant(convId, accumulated, calls);

  try {
    for await (const ev of streamChat(
      { model: sentModel, messages: apiMessages, stream: true, temperature, max_tokens: maxTokens },
      signal,
    )) {
      if (ev.event === 'agent_turn_start') {
        store.setStreamState({ phase: 'Agent thinking...' });
      } else if (ev.event === 'inference_start') {
        store.setStreamState({ phase: 'Generating...' });
      } else if (ev.event === 'tool_call_start') {
        try {
          const data = JSON.parse(ev.data);
          toolCalls.push({
            id: generateId(),
            tool: data.tool,
            arguments: serializeToolCallArguments(data.arguments),
            status: 'running',
          });
          store.setStreamState({ phase: `Calling ${data.tool}...`, activeToolCalls: [...toolCalls] });
          update([...toolCalls]);
        } catch {}
      } else if (ev.event === 'model_info') {
        // Claude Code reports which Claude model actually answered.
        try {
          modelInUse = String(JSON.parse(ev.data).model || '') || undefined;
          if (modelInUse && isClaudeCode(model)) {
            useHudSettings.getState().updateHud({ claudeModelInUse: modelInUse });
          }
        } catch {}
      } else if (ev.event === 'tool_call_end') {
        try {
          const data = JSON.parse(ev.data);
          const tc = toolCalls.find((t) => t.tool === data.tool && t.status === 'running');
          if (tc) {
            tc.status = data.success ? 'success' : 'error';
            tc.latency = data.latency;
            tc.result = data.result;
          }
          store.setStreamState({ phase: 'Generating...', activeToolCalls: [...toolCalls] });
          update([...toolCalls]);
        } catch {}
      } else {
        try {
          const data = JSON.parse(ev.data);
          if (data.usage) usage = data.usage;
          routedEngine = engineFromCompletionChunk(data) ?? routedEngine;
          const delta = data.choices?.[0]?.delta;
          if (delta?.content) {
            if (!ttftMs) ttftMs = Date.now() - startTime;
            accumulated += delta.content;
            store.setStreamState({ content: accumulated, phase: '' });
            if (Date.now() - lastFlush >= 80) {
              update(toolCalls.length ? [...toolCalls] : undefined);
              lastFlush = Date.now();
            }
          }
          if (data.choices?.[0]?.finish_reason === 'stop') break;
        } catch {}
      }
    }
  } catch (err: unknown) {
    if (err instanceof Error && err.name === 'AbortError') {
      aborted = true;
      if (!accumulated) accumulated = '(Generation stopped)';
    } else {
      const msg = err instanceof Error ? err.message : String(err);
      accumulated = accumulated || `Error: ${msg}`;
      store.addLogEntry({ timestamp: Date.now(), level: 'error', category: 'chat', message: `Stream error: ${msg}` });
    }
  } finally {
    clearInterval(timer);
    if (!accumulated) accumulated = 'No response was generated. Please try again.';
    const totalMs = Date.now() - startTime;
    const appState = useAppStore.getState();
    const telemetry: MessageTelemetry = {
      engine: resolveChatEngine({
        routedEngine,
        serverEngine: appState.serverInfo?.engine,
        selectedModel: model,
        selectedOwner: appState.models.find((m) => m.id === model)?.owned_by,
      }),
      model_id: modelInUse ? `${model} · ${modelInUse}` : model,
      total_ms: totalMs,
      ttft_ms: ttftMs,
      tokens_per_sec: usage?.completion_tokens ? usage.completion_tokens / (totalMs / 1000) : undefined,
    };
    appState.updateLastAssistant(convId, accumulated, toolCalls.length ? toolCalls : undefined, usage, telemetry);
    appState.resetStream();
    fetchSavings().then((d) => useAppStore.getState().setSavings(d)).catch(() => {});
  }

  return { conversationId: convId, content: accumulated, aborted };
}
