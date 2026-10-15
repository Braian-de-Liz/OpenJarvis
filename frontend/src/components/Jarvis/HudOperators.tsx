import { useEffect } from 'react';
import { Loader2, Pause, Play, RotateCw } from 'lucide-react';
import { toast } from 'sonner';
import { useOperatorsStore } from '../../lib/operatorsStore';
import type { OperatorAction } from '../../lib/operatorsStore';
import type { ManagedAgent } from '../../lib/api';

const STATUS: Record<ManagedAgent['status'], { label: string; dot: string }> = {
  idle: { label: 'OCIOSO', dot: 'bg-zinc-500' },
  running: { label: 'RODANDO', dot: 'bg-cyan-400 animate-pulse' },
  paused: { label: 'PAUSADO', dot: 'bg-zinc-600' },
  error: { label: 'ERRO', dot: 'bg-rose-400' },
  archived: { label: 'ARQUIVADO', dot: 'bg-zinc-700' },
  needs_attention: { label: 'ATENÇÃO', dot: 'bg-amber-400' },
  budget_exceeded: { label: 'SEM ORÇAMENTO', dot: 'bg-amber-400' },
  stalled: { label: 'TRAVADO', dot: 'bg-amber-400' },
};

export function OperatorsList({ agents, busy, onAction }: {
  agents: ManagedAgent[];
  busy: Record<string, boolean>;
  onAction: (id: string, action: OperatorAction) => void;
}) {
  if (agents.length === 0) {
    return (
      <p className="text-zinc-500 leading-relaxed">
        Nenhum agente contínuo. Crie em Agents (interface clássica) — por exemplo, um que monitora
        notícias toda manhã.
      </p>
    );
  }
  return (
    <ul className="space-y-1.5 max-h-56 overflow-y-auto" aria-label="Agentes contínuos">
      {agents.map((a) => {
        const st = STATUS[a.status] ?? STATUS.idle;
        const paused = a.status === 'paused';
        const running = a.status === 'running';
        return (
          <li key={a.id} className="jarvis-row gap-2">
            <div className="min-w-0">
              <p className="text-zinc-200 truncate" title={a.name}>{a.name}</p>
              <p className="text-[10px] text-zinc-500 flex items-center gap-1.5 truncate">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${st.dot}`} />
                {st.label}
                {a.current_activity && running && <span className="truncate text-cyan-400/70">· {a.current_activity}</span>}
                {typeof a.total_runs === 'number' && !running && <span>· {a.total_runs} exec.</span>}
              </p>
            </div>
            <div className="flex shrink-0">
              {busy[a.id] ? (
                <Loader2 size={13} className="animate-spin text-cyan-400 m-1.5" />
              ) : (
                <>
                  <button
                    type="button"
                    className="jarvis-icon-btn disabled:opacity-30"
                    disabled={running || paused}
                    onClick={() => onAction(a.id, 'run')}
                    title="Executar agora"
                    aria-label={`Executar ${a.name} agora`}
                  >
                    <RotateCw size={12} />
                  </button>
                  <button
                    type="button"
                    className="jarvis-icon-btn"
                    onClick={() => onAction(a.id, paused ? 'resume' : 'pause')}
                    title={paused ? 'Retomar' : 'Pausar'}
                    aria-label={`${paused ? 'Retomar' : 'Pausar'} ${a.name}`}
                  >
                    {paused ? <Play size={12} /> : <Pause size={12} />}
                  </button>
                </>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** Operators tab: continuous agents with run / pause / resume. */
export function HudOperators() {
  const { agents, busy, error, load, act } = useOperatorsStore();
  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 15000);
    return () => clearInterval(id);
  }, [load]);

  if (error) return <p className="text-amber-300 text-[10px] break-words">{error}</p>;
  return (
    <OperatorsList
      agents={agents}
      busy={busy}
      onAction={async (id, action) => {
        const err = await act(id, action);
        if (err) toast.error(`Agente: ${err}`);
      }}
    />
  );
}
