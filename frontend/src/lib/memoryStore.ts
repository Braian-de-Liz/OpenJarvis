import { create } from 'zustand';
import { getMemoryConfig, getMemoryStats, searchMemory, storeMemory } from './api';
import type { MemorySearchResult } from './api';

export type MemoryStatus = 'loading' | 'ready' | 'unavailable' | 'offline';

interface MemoryState {
  status: MemoryStatus;
  /** Server-provided reason when memory can't be used (e.g. missing Rust extension). */
  detail: string | null;
  entries: number;
  backend: string;
  results: MemorySearchResult[];
  searching: boolean;
  refresh: () => Promise<void>;
  search: (query: string) => Promise<void>;
  /** Store a fact; resolves to an error message, or null on success. */
  remember: (text: string) => Promise<string | null>;
}

export const useMemoryStore = create<MemoryState>((set, get) => ({
  status: 'loading',
  detail: null,
  entries: 0,
  backend: '',
  results: [],
  searching: false,

  refresh: async () => {
    try {
      const config = await getMemoryConfig();
      if (config.available === false) {
        set({ status: 'unavailable', detail: config.detail ?? 'Memória indisponível no servidor.' });
        return;
      }
      const stats = await getMemoryStats();
      if (stats.status === 'not_configured') {
        set({ status: 'unavailable', detail: 'Memória não configurada no servidor.', entries: 0 });
        return;
      }
      set({ status: 'ready', detail: null, entries: stats.entries, backend: stats.backend });
    } catch (err) {
      set({ status: 'offline', detail: err instanceof Error ? err.message : String(err) });
    }
  },

  search: async (query) => {
    const q = query.trim();
    if (!q || get().status !== 'ready') {
      set({ results: [] });
      return;
    }
    set({ searching: true });
    try {
      set({ results: await searchMemory(q, 8) });
    } catch {
      set({ results: [] });
    } finally {
      set({ searching: false });
    }
  },

  remember: async (text) => {
    const content = text.trim();
    if (!content) return 'Nada para lembrar.';
    try {
      await storeMemory(content, { source: 'jarvis-hud' });
      await get().refresh();
      return null;
    } catch (err) {
      return err instanceof Error ? err.message : String(err);
    }
  },
}));
