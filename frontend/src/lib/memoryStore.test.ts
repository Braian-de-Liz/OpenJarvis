import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';

const api = vi.hoisted(() => ({
  getMemoryConfig: vi.fn(),
  getMemoryStats: vi.fn(),
  searchMemory: vi.fn(),
  storeMemory: vi.fn(),
}));
vi.mock('./api', () => api);

import { useMemoryStore } from './memoryStore';
import { MemoryView } from '../components/Jarvis/HudMemory';

beforeEach(() => {
  vi.clearAllMocks();
  useMemoryStore.setState({ status: 'loading', detail: null, entries: 0, backend: '', results: [], searching: false });
});

describe('memory store', () => {
  it('reports the server reason when the backend is unavailable', async () => {
    api.getMemoryConfig.mockResolvedValue({ available: false, detail: 'openjarvis_rust is not installed' });
    await useMemoryStore.getState().refresh();
    expect(useMemoryStore.getState()).toMatchObject({ status: 'unavailable', detail: 'openjarvis_rust is not installed' });
    expect(api.getMemoryStats).not.toHaveBeenCalled();
  });

  it('loads stats when available', async () => {
    api.getMemoryConfig.mockResolvedValue({ available: true });
    api.getMemoryStats.mockResolvedValue({ entries: 3, backend: 'sqlite' });
    await useMemoryStore.getState().refresh();
    expect(useMemoryStore.getState()).toMatchObject({ status: 'ready', entries: 3, backend: 'sqlite' });
  });

  it('marks the server offline on network errors', async () => {
    api.getMemoryConfig.mockRejectedValue(new Error('Failed to fetch'));
    await useMemoryStore.getState().refresh();
    expect(useMemoryStore.getState().status).toBe('offline');
  });

  it('remembers a fact, tagging the source, and refreshes the count', async () => {
    api.getMemoryConfig.mockResolvedValue({ available: true });
    api.getMemoryStats.mockResolvedValue({ entries: 1, backend: 'sqlite' });
    api.storeMemory.mockResolvedValue(undefined);
    expect(await useMemoryStore.getState().remember('  prefiro café sem açúcar ')).toBeNull();
    expect(api.storeMemory).toHaveBeenCalledWith('prefiro café sem açúcar', { source: 'jarvis-hud' });
    expect(useMemoryStore.getState().entries).toBe(1);
  });

  it('returns the error message when storing fails', async () => {
    api.storeMemory.mockRejectedValue(new Error('Memory is not configured'));
    expect(await useMemoryStore.getState().remember('x')).toBe('Memory is not configured');
  });

  it('does not search while unavailable', async () => {
    useMemoryStore.setState({ status: 'unavailable' });
    await useMemoryStore.getState().search('café');
    expect(api.searchMemory).not.toHaveBeenCalled();
  });
});

describe('MemoryView', () => {
  const noop = () => {};
  it('shows the fix instructions when unavailable', () => {
    const html = renderToStaticMarkup(
      createElement(MemoryView, {
        status: 'unavailable', detail: 'Build it with maturin develop', entries: 0, results: [], searching: false,
        onSearch: noop, onRemember: noop,
      }),
    );
    expect(html).toContain('Memória indisponível');
    expect(html).toContain('Build it with maturin develop');
  });

  it('lists search results with scores when ready', () => {
    const html = renderToStaticMarkup(
      createElement(MemoryView, {
        status: 'ready', detail: null, entries: 2, searching: false,
        results: [{ content: 'Prefere café sem açúcar', score: 0.91, metadata: {} }],
        onSearch: noop, onRemember: noop,
      }),
    );
    expect(html).toContain('Prefere café sem açúcar');
    expect(html).toContain('0.91');
    expect(html).toContain('LEMBRANÇAS');
  });
});
