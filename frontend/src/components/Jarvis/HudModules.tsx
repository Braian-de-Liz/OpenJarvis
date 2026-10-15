import { useState, type ReactNode } from 'react';

export interface HudModule {
  id: string;
  label: string;
  icon: ReactNode;
  /** Small counter shown on the tab (e.g. pending reminders). */
  badge?: number;
  render: () => ReactNode;
}

const TAB_KEY = 'openjarvis-hud-module-tab';

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
            <span className="hidden xl:inline">{m.label}</span>
            {!!m.badge && <span className="jarvis-tab-badge">{m.badge}</span>}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="pt-3">{current.render()}</div>
    </div>
  );
}
