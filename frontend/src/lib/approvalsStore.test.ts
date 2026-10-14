import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PendingApproval } from './api';

const api = vi.hoisted(() => ({
  fetchPendingApprovals: vi.fn(),
  approveAction: vi.fn(),
  denyAction: vi.fn(),
}));
vi.mock('./api', () => api);

import { __resetApprovalsForTests, useApprovalsStore } from './approvalsStore';

const approval = (id: string): PendingApproval => ({
  id,
  action_type: 'shell_exec',
  description: `ação ${id}`,
  payload: {},
  permission_key: 'shell',
  tier: 'high',
  status: 'pending',
  created_at: new Date().toISOString(),
  expires_at: new Date().toISOString(),
});

beforeEach(() => {
  __resetApprovalsForTests();
  vi.clearAllMocks();
});

describe('approvals store', () => {
  it('loads pending items and only reports genuinely new ones', async () => {
    api.fetchPendingApprovals.mockResolvedValueOnce([approval('a')]);
    expect(await useApprovalsStore.getState().load()).toEqual([]); // first load is silent
    expect(useApprovalsStore.getState().items.map((a) => a.id)).toEqual(['a']);

    api.fetchPendingApprovals.mockResolvedValueOnce([approval('a'), approval('b')]);
    const fresh = await useApprovalsStore.getState().load();
    expect(fresh.map((a) => a.id)).toEqual(['b']);
  });

  it('keeps the current list when the backend is unreachable', async () => {
    api.fetchPendingApprovals.mockResolvedValueOnce([approval('a')]);
    await useApprovalsStore.getState().load();
    api.fetchPendingApprovals.mockRejectedValueOnce(new Error('offline'));
    expect(await useApprovalsStore.getState().load()).toEqual([]);
    expect(useApprovalsStore.getState().items).toHaveLength(1);
  });

  it('approve and deny remove the item and call the right endpoint', async () => {
    api.fetchPendingApprovals.mockResolvedValueOnce([approval('a'), approval('b')]);
    await useApprovalsStore.getState().load();
    api.approveAction.mockResolvedValueOnce(undefined);
    api.denyAction.mockResolvedValueOnce(undefined);

    expect(await useApprovalsStore.getState().decide('a', true)).toBe(true);
    expect(await useApprovalsStore.getState().decide('b', false)).toBe(true);

    expect(api.approveAction).toHaveBeenCalledWith('a');
    expect(api.denyAction).toHaveBeenCalledWith('b');
    expect(useApprovalsStore.getState().items).toEqual([]);
    expect(useApprovalsStore.getState().processing).toEqual({});
  });

  it('keeps the item when the decision fails', async () => {
    api.fetchPendingApprovals.mockResolvedValueOnce([approval('a')]);
    await useApprovalsStore.getState().load();
    api.approveAction.mockRejectedValueOnce(new Error('500'));

    expect(await useApprovalsStore.getState().decide('a', true)).toBe(false);
    expect(useApprovalsStore.getState().items).toHaveLength(1);
    expect(useApprovalsStore.getState().processing).toEqual({});
  });
});
