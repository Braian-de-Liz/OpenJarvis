import { AlertTriangle, MessageSquarePlus } from 'lucide-react';
import { useContextStore } from '../../lib/contextStore';
import { contextLevel, formatTokens } from '../../lib/contextWindow';
import type { ContextSnapshot, ContextWindowInfo } from '../../lib/contextWindow';

const BAR: Record<ReturnType<typeof contextLevel>, string> = {
  ok: 'linear-gradient(90deg, #22d3ee, #a855f7)',
  warn: 'linear-gradient(90deg, #fbbf24, #f59e0b)',
  high: 'linear-gradient(90deg, #fb7185, #e11d48)',
};

export function sourceLabel(info: ContextWindowInfo | null): string {
  if (!info?.window) return 'janela desconhecida';
  const n = info.window.toLocaleString('pt-BR');
  if (info.source === 'claude') return `${n} tokens · Claude`;
  if (info.source === 'ollama num_ctx') return `${n} tokens · num_ctx do Ollama`;
  return `${n} tokens · num_ctx configurado`;
}

export function ContextView({ snapshot, info, onNewConversation }: {
  snapshot: ContextSnapshot;
  info: ContextWindowInfo | null;
  onNewConversation?: () => void;
}) {
  const level = contextLevel(snapshot.fraction);
  const pct = snapshot.fraction === null ? null : Math.round(snapshot.fraction * 100);
  const free = snapshot.window ? Math.max(0, snapshot.window - snapshot.used) : null;

  return (
    <div className="space-y-3">
      <div>
        <div className="flex items-baseline justify-between mb-1">
          <span className="text-zinc-400 tracking-wider">JANELA DE CONTEXTO</span>
          <span className="text-cyan-200 tabular-nums">
            {formatTokens(snapshot.used)}
            {snapshot.window ? ` / ${formatTokens(snapshot.window)}` : ''}
            {pct !== null && ` · ${pct}%`}
          </span>
        </div>
        <div
          className="h-2 rounded-full overflow-hidden bg-cyan-400/10"
          role="progressbar"
          aria-valuenow={pct ?? undefined}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Uso da janela de contexto"
        >
          <div
            className="h-full rounded-full transition-[width] duration-500"
            style={{ width: `${pct ?? 0}%`, background: BAR[level] }}
          />
        </div>
        <p className="text-[10px] text-zinc-500 mt-1">
          {sourceLabel(info)}
          {snapshot.estimated && snapshot.used > 0 && ' · estimativa até a 1ª resposta'}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="jarvis-tile">
          <span className="text-zinc-500 text-[10px] tracking-wider">LIVRE</span>
          <span className="text-cyan-200 text-xs tabular-nums">{free === null ? '—' : formatTokens(free)}</span>
        </div>
        <div className="jarvis-tile">
          <span className="text-zinc-500 text-[10px] tracking-wider">RESPOSTAS</span>
          <span className="text-cyan-200 text-xs tabular-nums">{snapshot.replies}</span>
        </div>
        <div className="jarvis-tile">
          <span className="text-zinc-500 text-[10px] tracking-wider">↑ ENTRADA TOTAL</span>
          <span className="text-cyan-200 text-xs tabular-nums">{formatTokens(snapshot.promptTotal)}</span>
        </div>
        <div className="jarvis-tile">
          <span className="text-zinc-500 text-[10px] tracking-wider">↓ SAÍDA TOTAL</span>
          <span className="text-cyan-200 text-xs tabular-nums">{formatTokens(snapshot.completionTotal)}</span>
        </div>
      </div>

      {level !== 'ok' && (
        <div className="jarvis-approval is-high flex items-start gap-2 text-zinc-200">
          <AlertTriangle size={13} className="text-amber-300 shrink-0 mt-0.5" />
          <div className="space-y-1.5">
            <p>
              {level === 'high' ? 'A janela está quase cheia' : 'A janela está enchendo'} — o modelo vai
              esquecer o início da conversa.
            </p>
            {onNewConversation && (
              <button type="button" className="jarvis-chip" onClick={onNewConversation}>
                <MessageSquarePlus size={11} className="inline mr-1" />
                Nova conversa
              </button>
            )}
          </div>
        </div>
      )}

      {info?.history_limit && (
        <p className="text-[10px] text-zinc-500 leading-relaxed">
          No modo Conversa o Claude recebe só as últimas {info.history_limit.messages} mensagens
          (até {info.history_limit.chars.toLocaleString('pt-BR')} caracteres). O modo Agente não corta.
        </p>
      )}

      <div>
        <p className="text-zinc-400 tracking-wider mb-1.5">
          MENSAGENS
          {snapshot.outsideCount > 0 && (
            <span className="text-amber-300 ml-2">{snapshot.outsideCount} fora da janela</span>
          )}
        </p>
        {snapshot.items.length === 0 ? (
          <p className="text-zinc-500">A conversa está vazia.</p>
        ) : (
          <ul className="space-y-1 max-h-52 overflow-y-auto" aria-label="Mensagens na janela de contexto">
            {snapshot.items.map((it) => (
              <li
                key={it.id}
                className={`jarvis-row gap-2 ${it.outside ? 'opacity-40' : ''}`}
                title={it.outside ? 'Fora da janela: o modelo não vê esta mensagem' : undefined}
              >
                <span className={`shrink-0 text-[9px] tracking-widest ${it.role === 'user' ? 'text-amber-400' : 'text-cyan-400'}`}>
                  {it.role === 'user' ? 'VOCÊ' : 'JARVIS'}
                </span>
                <span className={`truncate min-w-0 flex-1 text-zinc-300 ${it.outside ? 'line-through' : ''}`}>{it.preview}</span>
                <span className="shrink-0 text-zinc-500 tabular-nums">~{formatTokens(it.tokens)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** Store-connected tab (the HUD page keeps the store in sync with chat + model). */
export function HudContext({ onNewConversation }: { onNewConversation?: () => void }) {
  const { info, snapshot } = useContextStore();
  return <ContextView snapshot={snapshot} info={info} onNewConversation={onNewConversation} />;
}
