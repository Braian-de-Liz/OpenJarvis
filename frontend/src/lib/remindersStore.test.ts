import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';

const api = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock('./api', () => ({ ...api, getBase: () => '' }));

import { formatNextRun, localInputToIso, useRemindersStore } from './remindersStore';
import { RemindersList } from '../components/Jarvis/HudReminders';
import { BriefingView } from '../components/Jarvis/HudBriefing';

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

beforeEach(() => {
  vi.clearAllMocks();
  useRemindersStore.setState({ items: [], error: null });
});

describe('formatNextRun', () => {
  const now = new Date(2026, 9, 14, 10, 0, 0);
  it('uses minutes, then today/tomorrow/date', () => {
    expect(formatNextRun(null, now)).toBe('—');
    expect(formatNextRun(new Date(2026, 9, 14, 9, 0).toISOString(), now)).toBe('agora');
    expect(formatNextRun(new Date(2026, 9, 14, 10, 15).toISOString(), now)).toBe('em 15 min');
    expect(formatNextRun(new Date(2026, 9, 14, 15, 30).toISOString(), now)).toBe('hoje 15:30');
    expect(formatNextRun(new Date(2026, 9, 15, 9, 0).toISOString(), now)).toBe('amanhã 09:00');
    expect(formatNextRun(new Date(2026, 9, 20, 9, 0).toISOString(), now)).toBe('20/10 09:00');
  });
});

describe('localInputToIso', () => {
  it('converts a datetime-local value to an absolute ISO time', () => {
    expect(localInputToIso('2026-10-14T15:30')).toBe(new Date(2026, 9, 14, 15, 30).toISOString());
    expect(localInputToIso('')).toBeNull();
    expect(localInputToIso('not a date')).toBeNull();
  });
});

describe('reminders store', () => {
  it('creates a reminder with the API field names and reloads', async () => {
    api.apiFetch
      .mockResolvedValueOnce(json({ id: 'r1' }, 201))
      .mockResolvedValueOnce(json([{ id: 'r1', text: 'Água', status: 'active', next_run: null, last_run: null, every_minutes: null }]));

    expect(await useRemindersStore.getState().add({ text: 'Água', inMinutes: 15 })).toBeNull();

    const [path, init] = api.apiFetch.mock.calls[0];
    expect(path).toBe('/v1/reminders');
    expect(JSON.parse(init.body)).toEqual({ text: 'Água', at: null, in_minutes: 15, every_minutes: null });
    expect(useRemindersStore.getState().items).toHaveLength(1);
  });

  it('surfaces the server validation message', async () => {
    api.apiFetch.mockResolvedValueOnce(json({ detail: "'at' must be in the future" }, 422));
    expect(await useRemindersStore.getState().add({ text: 'x', at: '2000-01-01T00:00:00Z' })).toBe("'at' must be in the future");
  });

  it('routes pause and delete to the right endpoints', async () => {
    api.apiFetch.mockResolvedValue(json([]));
    await useRemindersStore.getState().update('a b', 'pause');
    await useRemindersStore.getState().update('a b', 'delete');
    const calls = api.apiFetch.mock.calls.map(([p, i]) => `${i?.method ?? 'GET'} ${p}`);
    expect(calls).toContain('POST /v1/reminders/a%20b/pause');
    expect(calls).toContain('DELETE /v1/reminders/a%20b');
  });
});

describe('RemindersList', () => {
  it('shows text, countdown, repeat and paused state', () => {
    const now = new Date(2026, 9, 14, 10, 0);
    const html = renderToStaticMarkup(
      createElement(RemindersList, {
        now,
        onAction: () => {},
        items: [
          { id: 'a', text: 'Beber água', status: 'active', next_run: new Date(2026, 9, 14, 10, 5).toISOString(), last_run: null, every_minutes: 60 },
          { id: 'b', text: 'Ligar pro João', status: 'paused', next_run: null, last_run: null, every_minutes: null },
        ],
      }),
    );
    expect(html).toContain('Beber água');
    expect(html).toContain('em 5 min');
    expect(html).toContain('a cada 1 h');
    expect(html).toContain('pausado');
    expect(html).toContain('Retomar');
  });

  it('explains how to start when empty', () => {
    expect(renderToStaticMarkup(createElement(RemindersList, { items: [], onAction: () => {} }))).toContain('Nenhum lembrete');
  });
});

describe('BriefingView', () => {
  const base = { error: null, generating: false, playing: false, onGenerate: () => {}, onPlay: () => {} };
  it('invites to generate when there is no digest today', () => {
    const html = renderToStaticMarkup(createElement(BriefingView, { ...base, status: 'empty', digest: null }));
    expect(html).toContain('Gerar briefing');
    expect(html).toContain('Nenhum briefing hoje');
  });

  it('renders the digest Markdown and the audio button when available', () => {
    const html = renderToStaticMarkup(
      createElement(BriefingView, {
        ...base,
        status: 'ready',
        digest: { text: '## Agenda\n\n- Reunião 10h', generated_at: '2026-10-14T09:00:00Z', model_used: 'qwen', audio_available: true },
      }),
    );
    expect(html).toContain('<li>Reunião 10h</li>');
    expect(html).toContain('Atualizar briefing');
    expect(html).toContain('Ouvir briefing');
  });
});
