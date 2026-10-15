import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import type { ManagedAgent } from './api';

const api = vi.hoisted(() => ({
  fetchManagedAgents: vi.fn(),
  runManagedAgent: vi.fn(),
  pauseManagedAgent: vi.fn(),
  resumeManagedAgent: vi.fn(),
  apiFetch: vi.fn(),
}));
vi.mock('./api', () => api);

import { describeAgentEvent, useOperatorsStore } from './operatorsStore';
import { OperatorsList } from '../components/Jarvis/HudOperators';
import { ChannelsView, fetchChannelsInfo } from '../components/Jarvis/HudChannels';

const agent = (over: Partial<ManagedAgent>): ManagedAgent => ({
  id: 'a1',
  name: 'Notícias da manhã',
  agent_type: 'operative',
  config: {},
  status: 'idle',
  summary_memory: '',
  created_at: 0,
  updated_at: 0,
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  useOperatorsStore.setState({ agents: [], error: null, busy: {} });
});

describe('describeAgentEvent', () => {
  const agents = [agent({})];
  it('names the agent and phrases each outcome', () => {
    expect(describeAgentEvent({ type: 'agent_tick_end', timestamp: 0, data: { agent_id: 'a1' } }, agents))
      .toEqual({ level: 'success', text: 'Notícias da manhã concluiu uma execução.' });
    expect(describeAgentEvent({ type: 'agent_tick_error', timestamp: 0, data: { agent_id: 'a1', error: 'timeout' } }, agents))
      .toEqual({ level: 'error', text: 'Notícias da manhã falhou: timeout' });
    expect(describeAgentEvent({ type: 'agent_budget_exceeded', timestamp: 0, data: { agent_id: 'zz' } }, agents)?.text)
      .toBe('zz estourou o orçamento e foi pausado.');
  });

  it('ignores events it does not announce', () => {
    expect(describeAgentEvent({ type: 'tool_call_start', timestamp: 0, data: {} }, agents)).toBeNull();
  });
});

describe('operators store', () => {
  it('hides archived agents', async () => {
    api.fetchManagedAgents.mockResolvedValue([agent({}), agent({ id: 'old', status: 'archived' })]);
    await useOperatorsStore.getState().load();
    expect(useOperatorsStore.getState().agents.map((a) => a.id)).toEqual(['a1']);
  });

  it('dispatches actions and reports failures', async () => {
    api.fetchManagedAgents.mockResolvedValue([]);
    api.runManagedAgent.mockResolvedValue(undefined);
    api.pauseManagedAgent.mockRejectedValue(new Error('locked'));
    expect(await useOperatorsStore.getState().act('a1', 'run')).toBeNull();
    expect(api.runManagedAgent).toHaveBeenCalledWith('a1');
    expect(await useOperatorsStore.getState().act('a1', 'pause')).toBe('locked');
    expect(useOperatorsStore.getState().busy).toEqual({});
  });
});

describe('OperatorsList', () => {
  it('shows status, live activity and the right controls', () => {
    const html = renderToStaticMarkup(
      createElement(OperatorsList, {
        busy: {},
        onAction: () => {},
        agents: [
          agent({ status: 'running', current_activity: 'lendo feeds' }),
          agent({ id: 'a2', name: 'Backup', status: 'paused' }),
        ],
      }),
    );
    expect(html).toContain('RODANDO');
    expect(html).toContain('lendo feeds');
    expect(html).toContain('PAUSADO');
    expect(html).toContain('Retomar Backup');
  });

  it('points to Agents when there are none', () => {
    expect(renderToStaticMarkup(createElement(OperatorsList, { agents: [], busy: {}, onAction: () => {} })))
      .toContain('Nenhum agente contínuo');
  });
});

describe('channels', () => {
  it('parses the bridge response, including "not configured"', async () => {
    api.apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({ channels: [], message: 'Channel bridge not configured' })));
    expect(await fetchChannelsInfo()).toEqual({ status: 'not_configured', channels: [] });
    api.apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({ channels: ['telegram'], status: 'connected' })));
    expect(await fetchChannelsInfo()).toEqual({ status: 'connected', channels: ['telegram'] });
  });

  it('shows the Telegram guide with the real config keys when nothing is connected', () => {
    const html = renderToStaticMarkup(createElement(ChannelsView, { info: { status: 'not_configured', channels: [] }, error: null }));
    expect(html).toContain('NENHUM');
    expect(html).toContain('default_channel = &quot;telegram&quot;');
    expect(html).toContain('allowed_chat_ids');
  });

  it('lists connected channels and hides the guide', () => {
    const html = renderToStaticMarkup(createElement(ChannelsView, { info: { status: 'connected', channels: ['telegram'] }, error: null }));
    expect(html).toContain('telegram');
    expect(html).not.toContain('BotFather');
  });
});
