import { Keyboard, X } from 'lucide-react';

export const HUD_SHORTCUTS: { keys: string[]; label: string }[] = [
  { keys: ['Ctrl', 'Espaço'], label: 'Segurar para falar (push-to-talk); soltar envia' },
  { keys: ['Enter'], label: 'Enviar comando digitado' },
  { keys: ['Esc'], label: 'Fechar painéis' },
  { keys: ['?'], label: 'Mostrar/ocultar esta ajuda' },
];

export function ShortcutsOverlay({ onClose, pushToTalk }: { onClose: () => void; pushToTalk: boolean }) {
  return (
    <>
      <div className="jarvis-drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <div className="jarvis-shortcuts" role="dialog" aria-modal="true" aria-label="Atalhos de teclado">
        <header className="jarvis-hud-panel-head">
          <div className="flex items-center gap-2">
            <Keyboard size={14} className="text-cyan-400" />
            <h3>Atalhos</h3>
          </div>
          <button onClick={onClose} className="jarvis-icon-btn" aria-label="Fechar atalhos">
            <X size={14} />
          </button>
        </header>
        <ul className="p-4 space-y-2.5 jarvis-font-hud text-[11px]">
          {HUD_SHORTCUTS.map((s) => {
            const disabled = s.keys.includes('Espaço') && !pushToTalk;
            return (
              <li key={s.label} className={`flex items-center justify-between gap-4 ${disabled ? 'opacity-40' : ''}`}>
                <span className="text-zinc-300">
                  {s.label}
                  {disabled && ' (desativado nas configurações)'}
                </span>
                <span className="flex gap-1 shrink-0">
                  {s.keys.map((k) => <kbd key={k} className="jarvis-chip">{k}</kbd>)}
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </>
  );
}
