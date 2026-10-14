import { create } from 'zustand';

/** Per-browser preferences for the JARVIS HUD (look & feel only). */
export interface HudSettings {
  /** How JARVIS addresses the user in the HUD ("Sir", a name, ...). */
  userName: string;
  /** Floating particle network behind the panels. */
  particles: boolean;
  /** CRT scanline overlay. */
  scanlines: boolean;
  /** Slow the reactor and skip decorative motion. */
  reducedMotion: boolean;
  /** Show the telemetry panel (CPU/GPU/RAM/network). */
  showTelemetry: boolean;
  /** Hold Ctrl+Space to record from the browser mic; release to send. */
  pushToTalk: boolean;
}

export const HUD_SETTINGS_KEY = 'openjarvis-hud-settings';

export const HUD_DEFAULTS: HudSettings = {
  userName: 'Sir',
  particles: true,
  scanlines: true,
  reducedMotion: false,
  showTelemetry: true,
  pushToTalk: true,
};

export function loadHudSettings(): HudSettings {
  const prefersReduced =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const defaults = { ...HUD_DEFAULTS, reducedMotion: !!prefersReduced };
  try {
    const raw = localStorage.getItem(HUD_SETTINGS_KEY);
    if (!raw) return defaults;
    const parsed = JSON.parse(raw) as Partial<HudSettings>;
    const merged = { ...defaults, ...parsed };
    if (typeof merged.userName !== 'string' || !merged.userName.trim()) {
      merged.userName = HUD_DEFAULTS.userName;
    }
    return merged;
  } catch {
    return defaults;
  }
}

interface HudSettingsStore {
  hud: HudSettings;
  updateHud: (partial: Partial<HudSettings>) => void;
  resetHud: () => void;
}

export const useHudSettings = create<HudSettingsStore>((set, get) => ({
  hud: loadHudSettings(),
  updateHud: (partial) => {
    const hud = { ...get().hud, ...partial };
    try {
      localStorage.setItem(HUD_SETTINGS_KEY, JSON.stringify(hud));
    } catch {
      // Storage blocked (private window): keep the change for this session.
    }
    set({ hud });
  },
  resetHud: () => {
    try {
      localStorage.removeItem(HUD_SETTINGS_KEY);
    } catch {}
    set({ hud: { ...HUD_DEFAULTS } });
  },
}));
