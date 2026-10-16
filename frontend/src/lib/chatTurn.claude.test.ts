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

const sent: { model: string }[] = [];
let events: SSEEvent[] = [];

vi.mock('./sse', () => ({
  streamChat: async function* (req: { model: string }) {
    sent.push(req);
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
  sent.length = 0;
  events = [];
});

afterEach(() => {
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage = undefined;
});

async function setup(model: string, claudeModel = '') {
  const { useAppStore } = await import('./store');
  const { useHudSettings } = await import('./hudSettings');
  const { sendChatTurn } = await import('./chatTurn');
  useAppStore.getState().setSelectedModel(model);
  useHudSettings.getState().updateHud({ claudeModel });
  return { useAppStore, useHudSettings, sendChatTurn };
}

describe('Claude model choice', () => {
  it('sends the chosen Claude model as a suffix', async () => {
    const { sendChatTurn } = await setup('claude-code', 'opus');
    events = [chunk('oi', 'stop')];
    await sendChatTurn('oi');
    expect(sent[0].model).toBe('claude-code:opus');
  });

  it('keeps the plan default model, and the agent asks before acting by default', async () => {
    const { sendChatTurn } = await setup('claude-code-agent');
    events = [chunk('oi', 'stop')];
    await sendChatTurn('oi');
    expect(sent[0].model).toBe('claude-code-agent@ask');
  });

  it('sends the chosen agent permission mode', async () => {
    const { sendChatTurn, useHudSettings } = await setup('claude-code-agent', 'haiku');
    events = [chunk('oi', 'stop')];
    for (const mode of ['read', 'free'] as const) {
      useHudSettings.getState().updateHud({ claudeAgentMode: mode });
      await sendChatTurn('oi');
    }
    expect(sent.map((s) => s.model)).toEqual([
      'claude-code-agent:haiku@read',
      'claude-code-agent:haiku@free',
    ]);
  });

  it('never adds a permission mode to conversation mode or local models', async () => {
    const { sendChatTurn } = await setup('claude-code');
    events = [chunk('oi', 'stop')];
    await sendChatTurn('oi');
    expect(sent[0].model).toBe('claude-code');
  });

  it('never suffixes local models', async () => {
    const { sendChatTurn } = await setup('llama3.2:1b', 'opus');
    events = [chunk('oi', 'stop')];
    await sendChatTurn('oi');
    expect(sent[0].model).toBe('llama3.2:1b');
  });

  it('records the model Claude Code reports and shows it in telemetry', async () => {
    const { sendChatTurn, useHudSettings, useAppStore } = await setup('claude-code', 'sonnet');
    events = [
      { event: 'model_info', data: JSON.stringify({ model: 'claude-sonnet-4-5' }) },
      chunk('Olá', 'stop'),
    ];
    await sendChatTurn('oi');
    expect(useHudSettings.getState().hud.claudeModelInUse).toBe('claude-sonnet-4-5');
    expect(useAppStore.getState().messages[1].telemetry?.model_id).toBe('claude-code · claude-sonnet-4-5');
  });
});

describe('aiSource helpers', () => {
  it('builds request ids and labels', async () => {
    const { requestModel, claudeModelLabel } = await import('./aiSource');
    expect(requestModel('claude-code', 'haiku')).toBe('claude-code:haiku');
    expect(requestModel('claude-code', '')).toBe('claude-code');
    expect(requestModel('qwen2.5:7b', 'opus')).toBe('qwen2.5:7b');
    expect(requestModel('claude-code-agent', 'opus', 'free')).toBe('claude-code-agent:opus@free');
    expect(requestModel('claude-code-agent', '')).toBe('claude-code-agent@ask');
    expect(claudeModelLabel('claude-opus-4-1', 'opus')).toBe('claude-opus-4-1');
    expect(claudeModelLabel('', 'opus')).toBe('Opus');
    expect(claudeModelLabel('', '')).toBe('Padrão do plano');
  });
});

describe('unusualClaudeUsage', () => {
  it('flags a conversation-mode reply that costs far more than ~400 tokens', async () => {
    const { unusualClaudeUsage } = await import('./aiSource');
    expect(unusualClaudeUsage('claude-code', { prompt_tokens: 75626 })).toContain('75.626');
    expect(unusualClaudeUsage('claude-code', { prompt_tokens: 520 })).toBeNull();
  });

  it('stays quiet for agent mode, local models and missing usage', async () => {
    const { unusualClaudeUsage } = await import('./aiSource');
    expect(unusualClaudeUsage('claude-code-agent', { prompt_tokens: 80000 })).toBeNull();
    expect(unusualClaudeUsage('llama3.2:1b', { prompt_tokens: 80000 })).toBeNull();
    expect(unusualClaudeUsage('claude-code', undefined)).toBeNull();
  });
});
