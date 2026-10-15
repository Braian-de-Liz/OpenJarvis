import { create } from 'zustand';
import { apiFetch } from './api';

export interface Reminder {
  id: string;
  text: string;
  status: 'active' | 'paused';
  next_run: string | null;
  last_run: string | null;
  every_minutes: number | null;
}

export interface NewReminder {
  text: string;
  /** ISO datetime with offset; or use inMinutes. */
  at?: string;
  inMinutes?: number;
  everyMinutes?: number;
}

async function detail(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === 'string') return data.detail;
    if (Array.isArray(data?.detail) && data.detail[0]?.msg) return data.detail[0].msg;
  } catch {}
  return `${fallback} (HTTP ${res.status})`;
}

export async function fetchReminders(): Promise<Reminder[]> {
  const res = await apiFetch('/v1/reminders');
  if (!res.ok) throw new Error(await detail(res, 'Falha ao listar lembretes'));
  return res.json();
}

export async function createReminder(r: NewReminder): Promise<Reminder> {
  const res = await apiFetch('/v1/reminders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text: r.text,
      at: r.at ?? null,
      in_minutes: r.inMinutes ?? null,
      every_minutes: r.everyMinutes ?? null,
    }),
  });
  if (!res.ok) throw new Error(await detail(res, 'Falha ao criar lembrete'));
  return res.json();
}

async function act(id: string, action: 'pause' | 'resume' | 'delete'): Promise<void> {
  const res = action === 'delete'
    ? await apiFetch(`/v1/reminders/${encodeURIComponent(id)}`, { method: 'DELETE' })
    : await apiFetch(`/v1/reminders/${encodeURIComponent(id)}/${action}`, { method: 'POST' });
  if (!res.ok) throw new Error(await detail(res, 'Falha ao atualizar lembrete'));
}

/** "<datetime-local>" value (local wall time) → ISO with offset. */
export function localInputToIso(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

/** Human "em 5 min" / "amanhã 09:00" label for the next ring. */
export function formatNextRun(iso: string | null, now = new Date()): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const mins = Math.round((d.getTime() - now.getTime()) / 60000);
  if (mins <= 0) return 'agora';
  if (mins < 60) return `em ${mins} min`;
  const time = d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) return `hoje ${time}`;
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  if (d.toDateString() === tomorrow.toDateString()) return `amanhã ${time}`;
  return `${d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })} ${time}`;
}

interface RemindersState {
  items: Reminder[];
  error: string | null;
  load: () => Promise<void>;
  add: (r: NewReminder) => Promise<string | null>;
  update: (id: string, action: 'pause' | 'resume' | 'delete') => Promise<string | null>;
}

export const useRemindersStore = create<RemindersState>((set, get) => ({
  items: [],
  error: null,
  load: async () => {
    try {
      set({ items: await fetchReminders(), error: null });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },
  add: async (r) => {
    try {
      await createReminder(r);
      await get().load();
      return null;
    } catch (err) {
      return err instanceof Error ? err.message : String(err);
    }
  },
  update: async (id, action) => {
    try {
      await act(id, action);
      await get().load();
      return null;
    } catch (err) {
      return err instanceof Error ? err.message : String(err);
    }
  },
}));
