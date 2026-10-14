import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { ChatMessage } from '../../types';
import type { PendingApproval } from '../../lib/api';
import { HudApprovals, timeAgoPt } from './HudApprovals';
import { HudLog, buildEntries, type HudStream } from './HudLog';
import { levelFromSamples } from './useMicLevel';

const idle: HudStream = { isStreaming: false, conversationId: null, content: '', phase: '' };

const msg = (over: Partial<ChatMessage>): ChatMessage => ({
  id: Math.random().toString(36).slice(2),
  role: 'assistant',
  content: '',
  timestamp: 1,
  ...over,
});

describe('HudLog', () => {
  it('renders assistant Markdown and strips think tags', () => {
    const html = renderToStaticMarkup(
      <HudLog
        messages={[
          msg({ role: 'user', content: '**não** é markdown', timestamp: 1 }),
          msg({ content: '<think>raciocínio</think>Itens:\n\n- um\n- `dois`', timestamp: 2 }),
        ]}
        voiceLog={[]}
        stream={idle}
        activeId="c1"
        userName="Braian"
      />,
    );
    expect(html).toContain('<li>um</li>');
    expect(html).toContain('<code>dois</code>');
    expect(html).not.toContain('raciocínio');
    expect(html).toContain('**não** é markdown'); // user text stays literal
    expect(html).toContain('BRAIAN');
  });

  it('shows tool calls and response telemetry', () => {
    const html = renderToStaticMarkup(
      <HudLog
        messages={[
          msg({
            content: 'Feito.',
            toolCalls: [{ id: 't1', tool: 'audio_control', arguments: '{}', status: 'success', latency: 1500 }],
            telemetry: { total_ms: 2300, tokens_per_sec: 12.34, model_id: 'qwen2.5:7b' },
          }),
        ]}
        voiceLog={[]}
        stream={idle}
        activeId="c1"
        userName="Sir"
      />,
    );
    expect(html).toContain('audio_control');
    expect(html).toContain('is-success');
    expect(html).toContain('1.5s');
    expect(html).toContain('2.3s · 12.3 tok/s · qwen2.5:7b');
  });

  it('marks the streaming reply live with the current phase', () => {
    const stream: HudStream = { isStreaming: true, conversationId: 'c1', content: 'Proces', phase: 'Calling web_search...' };
    const entries = buildEntries([msg({ role: 'user', content: 'oi' }), msg({ content: 'Pro', timestamp: 2 })], [], stream, 'c1');
    expect(entries[1]).toMatchObject({ live: true, text: 'Proces' });

    const html = renderToStaticMarkup(
      <HudLog messages={[msg({ content: 'Pro', timestamp: 2 })]} voiceLog={[]} stream={stream} activeId="c1" userName="Sir" />,
    );
    expect(html).toContain('Calling web_search...');
    expect(html).not.toContain('tok/s');
  });

  it('interleaves voice transcripts by time', () => {
    const entries = buildEntries(
      [msg({ role: 'user', content: 'digitado', timestamp: 20 })],
      [{ id: 'v1', role: 'user', text: 'falado', timestamp: 10 }],
      idle,
      null,
    );
    expect(entries.map((e) => e.text)).toEqual(['falado', 'digitado']);
  });
});

describe('HudApprovals', () => {
  const approval: PendingApproval = {
    id: 'a1',
    action_type: 'shell_exec',
    description: 'Executar rm -rf build/',
    payload: { command: 'rm -rf build/' },
    permission_key: 'shell',
    tier: 'high',
    status: 'pending',
    created_at: new Date().toISOString(),
    expires_at: new Date().toISOString(),
  };

  it('renders nothing without pending items', () => {
    expect(renderToStaticMarkup(<HudApprovals items={[]} processing={{}} onDecide={() => {}} />)).toBe('');
  });

  it('shows the action, its risk and both decisions', () => {
    const html = renderToStaticMarkup(<HudApprovals items={[approval]} processing={{}} onDecide={() => {}} />);
    expect(html).toContain('shell_exec');
    expect(html).toContain('RISCO ALTO');
    expect(html).toContain('Executar rm -rf build/');
    expect(html).toContain('Aprovar');
    expect(html).toContain('Negar');
    expect(html).toContain('Ver detalhes');
  });

  it('disables the buttons while a decision is in flight', () => {
    const html = renderToStaticMarkup(<HudApprovals items={[approval]} processing={{ a1: true }} onDecide={() => {}} />);
    expect(html.match(/disabled=""/g)).toHaveLength(2);
  });

  it('formats relative time in Portuguese', () => {
    const now = Date.parse('2026-10-14T12:00:00Z');
    expect(timeAgoPt('2026-10-14T11:59:40Z', now)).toBe('agora');
    expect(timeAgoPt('2026-10-14T11:45:00Z', now)).toBe('há 15 min');
    expect(timeAgoPt('2026-10-14T09:00:00Z', now)).toBe('há 3 h');
  });
});

describe('levelFromSamples', () => {
  it('is 0 for silence and grows with amplitude, capped at 1', () => {
    expect(levelFromSamples(new Uint8Array(64).fill(128))).toBe(0);
    const quiet = levelFromSamples(Uint8Array.from({ length: 64 }, (_, i) => (i % 2 ? 133 : 123)));
    const loud = levelFromSamples(Uint8Array.from({ length: 64 }, (_, i) => (i % 2 ? 200 : 56)));
    expect(quiet).toBeGreaterThan(0);
    expect(loud).toBeGreaterThan(quiet);
    expect(levelFromSamples(Uint8Array.from({ length: 64 }, (_, i) => (i % 2 ? 255 : 0)))).toBe(1);
  });
});
