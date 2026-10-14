import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SSEEvent } from '../types';

class MemoryStorage {
  private store = new Map<string, string>();
  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
}

let events: SSEEvent[] = [];
let failWith: Error | null = null;

vi.mock('./sse', () => ({
  streamChat: async function* () {
    if (failWith) throw failWith;
    for (const ev of events) yield ev;
  },
}));
vi.mock('./api', async (orig) => ({
  ...(await orig<typeof import('./api')>()),
  fetchSavings: () => Promise.reject(new Error('offline')),
}));

const chunk = (content: string, finish?: string): SSEEvent => ({
  event: 'message',
  data: JSON.stringify({ choices: [{ delta: { content }, finish_reason: finish ?? null }] }),
});

beforeEach(() => {
  vi.resetModules();
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage = new MemoryStorage();
  events = [];
  failWith = null;
});

afterEach(() => {
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage = undefined;
});

async function setup(model = 'qwen2.5:7b') {
  const { useAppStore } = await import('./store');
  const { sendChatTurn } = await import('./chatTurn');
  useAppStore.getState().setSelectedModel(model);
  return { useAppStore, sendChatTurn };
}

describe('sendChatTurn', () => {
  it('streams the reply into a new conversation and resets the stream', async () => {
    const { useAppStore, sendChatTurn } = await setup();
    events = [chunk('Olá, '), chunk('Sir.', 'stop')];

    const result = await sendChatTurn('  oi jarvis  ');

    expect(result?.content).toBe('Olá, Sir.');
    expect(result?.aborted).toBe(false);
    const { messages, streamState, activeId } = useAppStore.getState();
    expect(activeId).toBe(result?.conversationId);
    expect(messages.map((m) => [m.role, m.content])).toEqual([
      ['user', 'oi jarvis'],
      ['assistant', 'Olá, Sir.'],
    ]);
    expect(messages[1].telemetry?.model_id).toBe('qwen2.5:7b');
    expect(streamState.isStreaming).toBe(false);
  });

  it('records tool calls from the stream', async () => {
    const { useAppStore, sendChatTurn } = await setup();
    events = [
      { event: 'tool_call_start', data: JSON.stringify({ tool: 'audio_control', arguments: { level: 80 } }) },
      { event: 'tool_call_end', data: JSON.stringify({ tool: 'audio_control', success: true, latency: 12 }) },
      chunk('Volume em 80%.', 'stop'),
    ];

    await sendChatTurn('aumente o volume');

    const calls = useAppStore.getState().messages[1].toolCalls;
    expect(calls).toHaveLength(1);
    expect(calls?.[0]).toMatchObject({ tool: 'audio_control', status: 'success' });
  });

  it('does nothing without a model or with empty input', async () => {
    const { useAppStore, sendChatTurn } = await setup('');
    expect(await sendChatTurn('oi')).toBeNull();
    useAppStore.getState().setSelectedModel('m');
    expect(await sendChatTurn('   ')).toBeNull();
    expect(useAppStore.getState().messages).toHaveLength(0);
  });

  it('reports aborts and keeps the conversation consistent', async () => {
    const { useAppStore, sendChatTurn } = await setup();
    failWith = Object.assign(new Error('aborted'), { name: 'AbortError' });

    const result = await sendChatTurn('conte uma história');

    expect(result?.aborted).toBe(true);
    expect(useAppStore.getState().messages[1].content).toBe('(Generation stopped)');
    expect(useAppStore.getState().streamState.isStreaming).toBe(false);
  });

  it('surfaces stream errors as the assistant message', async () => {
    const { useAppStore, sendChatTurn } = await setup();
    failWith = new Error('Chat request failed: 500');

    const result = await sendChatTurn('oi');

    expect(result?.content).toBe('Error: Chat request failed: 500');
    expect(useAppStore.getState().messages[1].content).toBe('Error: Chat request failed: 500');
  });
});
