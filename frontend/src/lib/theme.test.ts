import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { themeClasses } from './theme';

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

async function loadTheme() {
  const { useAppStore } = await import('./store');
  return useAppStore.getState().settings.theme;
}

describe('themeClasses', () => {
  it('builds JARVIS on top of dark', () => {
    expect(themeClasses('jarvis')).toEqual(['dark', 'jarvis']);
    expect(themeClasses('dark')).toEqual(['dark']);
    expect(themeClasses('light')).toEqual(['light']);
    expect(themeClasses('system')).toEqual([]);
  });
});

describe('JARVIS default theme', () => {
  it('is the default for fresh installs', async () => {
    expect(await loadTheme()).toBe('jarvis');
  });

  it('moves untouched "system" installs to JARVIS once', async () => {
    storage.setItem('openjarvis-settings', JSON.stringify({ theme: 'system' }));
    expect(await loadTheme()).toBe('jarvis');
    expect(JSON.parse(storage.getItem('openjarvis-settings')!).theme).toBe('jarvis');

    // Choosing "system" again afterwards is respected.
    storage.setItem('openjarvis-settings', JSON.stringify({ theme: 'system' }));
    vi.resetModules();
    expect(await loadTheme()).toBe('system');
  });

  it('keeps an explicit light or dark choice', async () => {
    storage.setItem('openjarvis-settings', JSON.stringify({ theme: 'light' }));
    expect(await loadTheme()).toBe('light');
  });
});
