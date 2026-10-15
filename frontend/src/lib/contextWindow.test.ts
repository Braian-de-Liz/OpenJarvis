import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import type { ChatMessage } from '../types';

const api = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock('./api', () => api);

import {
  computeContext,
  contextLevel,
  estimateTokens,
  formatTokens,
  markOutside,
} from './contextWindow';
import type { ContextWindowInfo } from './contextWindow';
import { __resetContextForTests, useContextStore } from './contextStore';
import { ContextView } from '../components/Jarvis/HudContext';

let n = 0;
const msg = (role: 'user' | 'assistant', content: string, usage?: ChatMessage['usage']): ChatMessage => ({
  id: `m${++n}`,
  role,
  content,
  timestamp: n,
  usage,
});

const ollama = (window: number): ContextWindowInfo => ({
  model: 'llama3.2:1b',
  window,
  model_max: 131072,
  source: 'ollama num_ctx',
  history_limit: null,
});
const claudeChat: ContextWindowInfo = {
  model: 'claude-code',
  window: 200000,
  model_max: 200000,
  source: 'claude',
  history_limit: { messages: 12, chars: 6000 },
};

beforeEach(() => {
  n = 0;
  vi.clearAllMocks();
  __resetContextForTests();
});

describe('formatting', () => {
  it('formats counts compactly in pt-BR', () => {
    expect(formatTokens(950)).toBe('950');
    expect(formatTokens(3200)).toBe('3,2k');
    expect(formatTokens(16384)).toBe('16k');
    expect(formatTokens(2_500_000)).toBe('2,5M');
  });

  it('levels the window usage', () => {
    expect(contextLevel(null)).toBe('ok');
    expect(contextLevel(0.5)).toBe('ok');
    expect(contextLevel(0.7)).toBe('warn');
    expect(contextLevel(0.95)).toBe('high');
  });
});

describe('computeContext', () => {
  it('uses the last reply usage as what the next request carries', () => {
    const s = computeContext(
      [
        msg('user', 'oi'),
        msg('assistant', 'olá', { prompt_tokens: 100, completion_tokens: 20, total_tokens: 120 }),
        msg('user', 'e agora?'),
        msg('assistant', 'ok', { prompt_tokens: 160, completion_tokens: 30, total_tokens: 190 }),
      ],
      ollama(1000),
    );
    expect(s.used).toBe(190);
    expect(s.estimated).toBe(false);
    expect(s.fraction).toBeCloseTo(0.19);
    expect(s.promptTotal).toBe(260);
    expect(s.completionTotal).toBe(50);
    expect(s.replies).toBe(2);
  });

  it('estimates before the first reply and without a known window', () => {
    const s = computeContext([msg('user', 'a'.repeat(400))], null);
    expect(s.estimated).toBe(true);
    expect(s.used).toBe(estimateTokens('a'.repeat(400)));
    expect(s.window).toBeNull();
    expect(s.fraction).toBeNull();
  });

  it('caps the fraction at 100%', () => {
    const s = computeContext(
      [msg('assistant', 'x', { prompt_tokens: 5000, completion_tokens: 0, total_tokens: 5000 })],
      ollama(1000),
    );
    expect(s.fraction).toBe(1);
  });
});

describe('markOutside', () => {
  it('Ollama: drops the oldest messages once the window is exceeded', () => {
    const messages = [msg('user', 'a'), msg('assistant', 'b'), msg('user', 'c'), msg('assistant', 'd')];
    const tokens = [400, 400, 400, 400];
    expect(markOutside(messages, tokens, ollama(1000))).toEqual([true, false, false, false]);
    expect(markOutside(messages, tokens, ollama(10_000))).toEqual([false, false, false, false]);
  });

  it('Claude conversa: only the last 12 messages are sent', () => {
    const messages = Array.from({ length: 15 }, (_, i) => msg(i % 2 ? 'assistant' : 'user', `m${i}`));
    const out = markOutside(messages, messages.map(() => 5), claudeChat);
    expect(out.slice(0, 3)).toEqual([true, true, true]);
    expect(out.slice(3).every((v) => !v)).toBe(true);
  });

  it('Claude conversa: the character limit cuts older messages too', () => {
    const big = 'x'.repeat(3000);
    const messages = [msg('user', big), msg('assistant', big), msg('user', big), msg('assistant', 'fim')];
    const out = markOutside(messages, messages.map(() => 5), claudeChat);
    expect(out).toEqual([true, false, false, false]);
  });

  it('Claude agente / unknown model: nothing is dropped', () => {
    const messages = [msg('user', 'a'), msg('assistant', 'b')];
    expect(markOutside(messages, [5, 5], { ...claudeChat, history_limit: null, window: null })).toEqual([false, false]);
    expect(markOutside(messages, [5, 5], null)).toEqual([false, false]);
  });
});

describe('context store', () => {
  it('loads the window once per model and recomputes with the messages', async () => {
    api.apiFetch.mockResolvedValue(new Response(JSON.stringify(ollama(16384))));
    const store = useContextStore.getState();
    store.setMessages([msg('user', 'oi')]);
    await store.loadWindow('llama3.2:1b');
    await store.loadWindow('llama3.2:1b');
    expect(api.apiFetch).toHaveBeenCalledTimes(1);
    expect(api.apiFetch.mock.calls[0][0]).toBe('/api/context-window?model=llama3.2%3A1b');
    expect(useContextStore.getState().snapshot.window).toBe(16384);
  });

  it('degrades to "window unknown" when the endpoint fails and retries later', async () => {
    api.apiFetch.mockResolvedValueOnce(new Response('x', { status: 500 }));
    await useContextStore.getState().loadWindow('m');
    expect(useContextStore.getState().snapshot.window).toBeNull();
    api.apiFetch.mockResolvedValueOnce(new Response(JSON.stringify(ollama(4096))));
    await useContextStore.getState().loadWindow('m');
    expect(useContextStore.getState().snapshot.window).toBe(4096);
  });
});

describe('ContextView', () => {
  const render = (messages: ChatMessage[], info: ContextWindowInfo | null) =>
    renderToStaticMarkup(createElement(ContextView, { snapshot: computeContext(messages, info), info, onNewConversation: () => {} }));

  it('shows the bar, totals, messages and the window source', () => {
    const html = render(
      [
        msg('user', 'qual a capital da França?'),
        msg('assistant', 'Paris.', { prompt_tokens: 3200, completion_tokens: 10, total_tokens: 3210 }),
      ],
      ollama(16384),
    );
    expect(html).toContain('3,2k / 16k · 20%');
    expect(html).toContain('16.384 tokens · num_ctx do Ollama');
    expect(html).toContain('qual a capital da França?');
    expect(html).toContain('role="progressbar"');
    expect(html).not.toContain('Nova conversa');
  });

  it('warns near the limit and offers a new conversation', () => {
    const html = render(
      [msg('assistant', 'x', { prompt_tokens: 950, completion_tokens: 0, total_tokens: 950 })],
      ollama(1000),
    );
    expect(html).toContain('quase cheia');
    expect(html).toContain('Nova conversa');
  });

  it('flags messages that fall outside the window and explains Claude limits', () => {
    const messages = Array.from({ length: 14 }, (_, i) => msg(i % 2 ? 'assistant' : 'user', `mensagem ${i}`));
    const html = render(messages, claudeChat);
    expect(html).toContain('2 fora da janela');
    expect(html).toContain('line-through');
    expect(html).toContain('últimas 12 mensagens');
  });

  it('copes with an unknown window', () => {
    const html = render([msg('user', 'oi')], null);
    expect(html).toContain('janela desconhecida');
    expect(html).toContain('estimativa até a 1ª resposta');
  });
});
