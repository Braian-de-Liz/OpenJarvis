import { useEffect, useState, type ReactNode } from 'react';

export interface HudModule {
  id: string;
  label: string;
  icon: ReactNode;
  /** Small counter shown on the tab (e.g. pending reminders). */
  badge?: number;
  render: () => ReactNode;
}

const TAB_KEY = 'openjarvis-hud-module-tab';
export const OPEN_MODULE_EVENT = 'hud:open-module';

function loadTab(fallback: string): string {
  try {
    return localStorage.getItem(TAB_KEY) || fallback;
  } catch {
    return fallback;
  }
}

/** Tabbed body for the HUD "Módulos" panel; only the active module renders. */
export function HudModules({ modules }: { modules: HudModule[] }) {
  const [active, setActive] = useState(() => loadTab(modules[0]?.id ?? ''));
  const current = modules.find((m) => m.id === active) ?? modules[0];
  if (!current) return null;

  const select = (id: string) => {
    setActive(id);
    try {
      localStorage.setItem(TAB_KEY, id);
    } catch {}
  };

  // Lets other HUD parts (e.g. the CTX pill) jump to a tab.
  useEffect(() => {
    const open = (e: Event) => {
      const id = (e as CustomEvent<string>).detail;
      if (modules.some((m) => m.id === id)) select(id);
    };
    window.addEventListener(OPEN_MODULE_EVENT, open);
    return () => window.removeEventListener(OPEN_MODULE_EVENT, open);
  });

  return (
    <div className="jarvis-font-hud text-[11px]">
      <div className="jarvis-tabs" role="tablist" aria-label="Módulos">
        {modules.map((m) => (
          <button
            key={m.id}
            type="button"
            role="tab"
            aria-selected={m.id === current.id}
            className={`jarvis-tab ${m.id === current.id ? 'is-active' : ''}`}
            onClick={() => select(m.id)}
            title={m.label}
          >
            {m.icon}
            {/* Only the active tab spells its name, so several tabs fit the column. */}
            {m.id === current.id && <span className="truncate">{m.label}</span>}
            {!!m.badge && <span className="jarvis-tab-badge">{m.badge}</span>}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="pt-3">{current.render()}</div>
    </div>
  );
}
