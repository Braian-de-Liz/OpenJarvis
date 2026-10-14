import { useNavigate } from 'react-router';
import { Sparkles } from 'lucide-react';
import { useAppStore } from '../../lib/store';

/** HUD-style status pills for the chat header (JARVIS theme only). */
export function ChatHudBar() {
  const navigate = useNavigate();
  const selectedModel = useAppStore((s) => s.selectedModel);
  const streamState = useAppStore((s) => s.streamState);
  const activeId = useAppStore((s) => s.activeId);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const busy = streamState.isStreaming && streamState.conversationId === activeId;

  return (
    <div className="flex items-center gap-2 min-w-0 overflow-hidden">
      <button
        type="button"
        onClick={() => navigate('/')}
        className="jarvis-pill hover:border-cyan-400/40"
        title="Voltar ao HUD"
      >
        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
        <span className="jarvis-font-display text-cyan-200 tracking-[0.25em]">J.A.R.V.I.S.</span>
        <span className="text-zinc-500">CHAT</span>
      </button>
      <div className="jarvis-pill hidden sm:flex">
        <span className="text-zinc-500">STATUS</span>
        <span className={busy ? 'text-purple-300' : 'text-cyan-300'}>{busy ? 'PROCESSANDO' : 'PRONTO'}</span>
      </div>
      <button
        type="button"
        onClick={() => setCommandPaletteOpen(true)}
        className="jarvis-pill hidden md:flex hover:border-cyan-400/40"
        title="Trocar modelo (Ctrl+K)"
      >
        <span className="text-zinc-500">MODELO</span>
        <span className={`truncate max-w-[14rem] ${selectedModel ? 'text-cyan-200' : 'text-amber-300'}`}>
          {selectedModel || 'NENHUM'}
        </span>
      </button>
      <button
        type="button"
        onClick={() => navigate('/')}
        className="jarvis-pill hidden lg:flex hover:border-cyan-400/40 text-cyan-300"
        title="Abrir o HUD"
      >
        <Sparkles size={12} />
        HUD
      </button>
    </div>
  );
}
