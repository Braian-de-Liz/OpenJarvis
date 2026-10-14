import { create } from 'zustand';
import { approveAction, denyAction, fetchPendingApprovals } from './api';
import type { PendingApproval } from './api';

interface ApprovalsState {
  items: PendingApproval[];
  /** ids with an approve/deny request in flight */
  processing: Record<string, boolean>;
  /**
   * Refresh the pending list. Resolves to the approvals that were not in the
   * previous list, so callers can announce new ones (toast, HUD log).
   * The first load never reports anything as new.
   */
  load: () => Promise<PendingApproval[]>;
  /** Approve or deny; resolves false (item kept) when the request fails. */
  decide: (id: string, approve: boolean) => Promise<boolean>;
}

let loadedOnce = false;

export const useApprovalsStore = create<ApprovalsState>((set, get) => ({
  items: [],
  processing: {},

  load: async () => {
    let next: PendingApproval[];
    try {
      next = await fetchPendingApprovals();
    } catch {
      return []; // backend down: keep showing what we had
    }
    const known = new Set(get().items.map((a) => a.id));
    const fresh = loadedOnce ? next.filter((a) => !known.has(a.id)) : [];
    loadedOnce = true;
    set({ items: next });
    return fresh;
  },

  decide: async (id, approve) => {
    set((s) => ({ processing: { ...s.processing, [id]: true } }));
    try {
      await (approve ? approveAction(id) : denyAction(id));
      set((s) => ({ items: s.items.filter((a) => a.id !== id) }));
      return true;
    } catch {
      return false;
    } finally {
      set((s) => {
        const processing = { ...s.processing };
        delete processing[id];
        return { processing };
      });
    }
  },
}));

/** Test helper: forget the first-load guard. */
export function __resetApprovalsForTests(): void {
  loadedOnce = false;
  useApprovalsStore.setState({ items: [], processing: {} });
}
