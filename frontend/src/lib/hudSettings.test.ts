import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

class MemoryStorage {
  private store = new Map<string, string>();
  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
}

let storage: MemoryStorage;

beforeEach(() => {
  vi.resetModules();
  storage = new MemoryStorage();
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage = storage;
});

afterEach(() => {
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage = undefined;
});

describe('HUD settings', () => {
  it('starts from defaults', async () => {
    const { useHudSettings, HUD_DEFAULTS } = await import('./hudSettings');
    expect(useHudSettings.getState().hud.userName).toBe(HUD_DEFAULTS.userName);
    expect(useHudSettings.getState().hud.particles).toBe(true);
    expect(useHudSettings.getState().hud.pushToTalk).toBe(true);
  });

  it('adds pushToTalk to settings saved before it existed', async () => {
    storage.setItem('openjarvis-hud-settings', JSON.stringify({ userName: 'Braian' }));
    const { loadHudSettings } = await import('./hudSettings');
    expect(loadHudSettings()).toMatchObject({ userName: 'Braian', pushToTalk: true });
  });

  it('persists updates and reloads them', async () => {
    const first = await import('./hudSettings');
    first.useHudSettings.getState().updateHud({ userName: 'Braian', scanlines: false });

    vi.resetModules();
    const second = await import('./hudSettings');
    expect(second.useHudSettings.getState().hud).toMatchObject({ userName: 'Braian', scanlines: false });
  });

  it('ignores corrupt or blank stored values', async () => {
    storage.setItem('openjarvis-hud-settings', JSON.stringify({ userName: '   ' }));
    const { loadHudSettings } = await import('./hudSettings');
    expect(loadHudSettings().userName).toBe('Sir');

    storage.setItem('openjarvis-hud-settings', '{not json');
    expect(loadHudSettings().userName).toBe('Sir');
  });

  it('reset restores defaults and clears storage', async () => {
    const { useHudSettings } = await import('./hudSettings');
    useHudSettings.getState().updateHud({ userName: 'Braian' });
    useHudSettings.getState().resetHud();
    expect(useHudSettings.getState().hud.userName).toBe('Sir');
    expect(storage.getItem('openjarvis-hud-settings')).toBeNull();
  });
});
