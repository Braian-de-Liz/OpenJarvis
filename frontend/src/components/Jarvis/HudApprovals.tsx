import { useState } from 'react';
import { CheckCircle, ChevronDown, ChevronUp, Clock, XCircle } from 'lucide-react';
import type { PendingApproval } from '../../lib/api';

const TIER_LABEL: Record<PendingApproval['tier'], string> = {
  trivial: 'TRIVIAL',
  low: 'BAIXO',
  medium: 'MÉDIO',
  high: 'ALTO',
};

const TIER_CLASS: Record<PendingApproval['tier'], string> = {
  trivial: 'text-zinc-400 border-zinc-500/30',
  low: 'text-sky-300 border-sky-400/30',
  medium: 'text-amber-300 border-amber-400/40',
  high: 'text-rose-300 border-rose-400/50',
};

export function timeAgoPt(iso: string, now = Date.now()): string {
  const m = Math.floor((now - new Date(iso).getTime()) / 60000);
  if (!Number.isFinite(m) || m < 1) return 'agora';
  if (m < 60) return `há ${m} min`;
  const h = Math.floor(m / 60);
  return h < 24 ? `há ${h} h` : `há ${Math.floor(h / 24)} d`;
}

/** Pending agent actions waiting for the user's approval, HUD-styled. */
export function HudApprovals({ items, processing, onDecide }: {
  items: PendingApproval[];
  processing: Record<string, boolean>;
  onDecide: (id: string, approve: boolean) => void;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  if (items.length === 0) return null;

  return (
    <div className="space-y-2 jarvis-font-hud text-[11px]" role="list" aria-label="Aprovações pendentes">
      {items.map((a) => {
        const tier = TIER_LABEL[a.tier] ? a.tier : 'medium';
        const busy = !!processing[a.id];
        const open = !!expanded[a.id];
        const hasPayload = Object.keys(a.payload ?? {}).length > 0;
        return (
          <div key={a.id} role="listitem" className={`jarvis-approval ${tier === 'high' ? 'is-high' : ''}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-cyan-300 truncate">{a.action_type}</span>
              <span className="flex items-center gap-2 shrink-0">
                <span className={`px-1.5 rounded border text-[9px] tracking-widest ${TIER_CLASS[tier]}`}>
                  RISCO {TIER_LABEL[tier]}
                </span>
                <span className="flex items-center gap-0.5 text-zinc-500 text-[10px]">
                  <Clock size={9} /> {timeAgoPt(a.created_at)}
                </span>
              </span>
            </div>
            <p className="text-zinc-200 leading-snug mt-1.5">{a.description}</p>
            {hasPayload && (
              <button
                type="button"
                className="flex items-center gap-1 mt-1.5 text-zinc-500 hover:text-zinc-300"
                aria-expanded={open}
                onClick={() => setExpanded((e) => ({ ...e, [a.id]: !e[a.id] }))}
              >
                {open ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                {open ? 'Ocultar detalhes' : 'Ver detalhes'}
              </button>
            )}
            {open && (
              <pre className="jarvis-approval-payload">{JSON.stringify(a.payload, null, 2)}</pre>
            )}
            <div className="flex gap-2 mt-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => onDecide(a.id, true)}
                className="jarvis-approval-btn is-approve"
              >
                <CheckCircle size={12} /> Aprovar
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => onDecide(a.id, false)}
                className="jarvis-approval-btn is-deny"
              >
                <XCircle size={12} /> Negar
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
