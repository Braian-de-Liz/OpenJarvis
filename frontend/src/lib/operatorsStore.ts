import { create } from 'zustand';
import { fetchManagedAgents, pauseManagedAgent, resumeManagedAgent, runManagedAgent } from './api';
import type { ManagedAgent } from './api';
import type { AgentEvent } from './useAgentEvents';

export type OperatorAction = 'run' | 'pause' | 'resume';

interface OperatorsState {
  agents: ManagedAgent[];
  error: string | null;
  busy: Record<string, boolean>;
  load: () => Promise<void>;
  act: (id: string, action: OperatorAction) => Promise<string | null>;
}

export const useOperatorsStore = create<OperatorsState>((set, get) => ({
  agents: [],
  error: null,
  busy: {},
  load: async () => {
    try {
      const agents = await fetchManagedAgents();
      set({ agents: agents.filter((a) => a.status !== 'archived'), error: null });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },
  act: async (id, action) => {
    set((s) => ({ busy: { ...s.busy, [id]: true } }));
    try {
      if (action === 'run') await runManagedAgent(id);
      else if (action === 'pause') await pauseManagedAgent(id);
      else await resumeManagedAgent(id);
      await get().load();
      return null;
    } catch (err) {
      return err instanceof Error ? err.message : String(err);
    } finally {
      set((s) => {
        const busy = { ...s.busy };
        delete busy[id];
        return { busy };
      });
    }
  },
}));

/** Agent events the HUD announces. */
export const NOTIFY_AGENT_EVENTS = [
  'agent_tick_end',
  'agent_tick_error',
  'agent_budget_exceeded',
  'agent_stall_detected',
] as const;

export interface AgentNotice {
  level: 'success' | 'error' | 'warning';
  text: string;
}

/** Turn an agent event into a short Portuguese notice (null = stay quiet). */
export function describeAgentEvent(ev: AgentEvent, agents: ManagedAgent[]): AgentNotice | null {
  const id = String(ev.data.agent_id ?? ev.data.agent ?? '');
  const name = agents.find((a) => a.id === id)?.name || id || 'Agente';
  switch (ev.type) {
    case 'agent_tick_end':
      return { level: 'success', text: `${name} concluiu uma execução.` };
    case 'agent_tick_error': {
      const error = String(ev.data.error ?? '').slice(0, 160);
      return { level: 'error', text: `${name} falhou${error ? `: ${error}` : '.'}` };
    }
    case 'agent_budget_exceeded':
      return { level: 'warning', text: `${name} estourou o orçamento e foi pausado.` };
    case 'agent_stall_detected':
      return { level: 'warning', text: `${name} parece travado.` };
    default:
      return null;
  }
}
