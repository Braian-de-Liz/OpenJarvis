import { useEffect, useState } from 'react';
import { Pause, Play, Plus, Repeat, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { formatNextRun, localInputToIso, useRemindersStore } from '../../lib/remindersStore';
import type { NewReminder, Reminder } from '../../lib/remindersStore';

const QUICK = [
  { label: '5 min', minutes: 5 },
  { label: '15 min', minutes: 15 },
  { label: '1 h', minutes: 60 },
];

export function RemindersList({ items, onAction, now }: {
  items: Reminder[];
  onAction: (id: string, action: 'pause' | 'resume' | 'delete') => void;
  now?: Date;
}) {
  if (items.length === 0) {
    return <p className="text-zinc-500">Nenhum lembrete. Ex.: "beber água" em 15 min.</p>;
  }
  return (
    <ul className="space-y-1.5 max-h-56 overflow-y-auto" aria-label="Lembretes">
      {items.map((r) => (
        <li key={r.id} className={`jarvis-row gap-2 ${r.status === 'paused' ? 'opacity-50' : ''}`}>
          <div className="min-w-0">
            <p className="text-zinc-200 truncate" title={r.text}>{r.text}</p>
            <p className="text-[10px] text-zinc-500 flex items-center gap-1">
              {r.status === 'paused' ? 'pausado' : formatNextRun(r.next_run, now)}
              {r.every_minutes && (
                <span className="flex items-center gap-0.5 text-cyan-400/70">
                  <Repeat size={9} /> a cada {r.every_minutes >= 60 ? `${r.every_minutes / 60} h` : `${r.every_minutes} min`}
                </span>
              )}
            </p>
          </div>
          <div className="flex shrink-0">
            <button
              type="button"
              className="jarvis-icon-btn"
              onClick={() => onAction(r.id, r.status === 'paused' ? 'resume' : 'pause')}
              aria-label={r.status === 'paused' ? 'Retomar' : 'Pausar'}
              title={r.status === 'paused' ? 'Retomar' : 'Pausar'}
            >
              {r.status === 'paused' ? <Play size={12} /> : <Pause size={12} />}
            </button>
            <button type="button" className="jarvis-icon-btn" onClick={() => onAction(r.id, 'delete')} aria-label="Apagar" title="Apagar">
              <Trash2 size={12} />
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Reminders tab: create (quick or at a time, optionally repeating) and manage. */
export function HudReminders() {
  const { items, error, load, add, update } = useRemindersStore();
  const [text, setText] = useState('');
  const [at, setAt] = useState('');
  const [repeat, setRepeat] = useState(false);
  const [, setTick] = useState(0);

  useEffect(() => {
    void load();
    // Refresh countdowns and pick up rings (once-reminders leave the list).
    const id = setInterval(() => {
      setTick((t) => t + 1);
      void load();
    }, 30000);
    return () => clearInterval(id);
  }, [load]);

  const submit = async (r: Omit<NewReminder, 'text'>) => {
    const err = await add({ text: text.trim(), everyMinutes: repeat ? 60 : undefined, ...r });
    if (err) {
      toast.error(`Lembrete: ${err}`);
      return;
    }
    setText('');
    setAt('');
    toast.success('Lembrete criado.');
  };

  const canAdd = text.trim().length > 0;

  return (
    <div className="space-y-3">
      <input
        className="jarvis-field-input"
        placeholder="Me lembre de…"
        value={text}
        maxLength={300}
        onChange={(e) => setText(e.target.value)}
        aria-label="Texto do lembrete"
      />
      <div className="flex flex-wrap gap-1.5">
        {QUICK.map((q) => (
          <button
            key={q.label}
            type="button"
            className="jarvis-chip disabled:opacity-40"
            disabled={!canAdd}
            onClick={() => void submit({ inMinutes: q.minutes })}
          >
            em {q.label}
          </button>
        ))}
      </div>
      <div className="flex gap-1.5">
        <input
          type="datetime-local"
          className="jarvis-field-input"
          value={at}
          onChange={(e) => setAt(e.target.value)}
          aria-label="Data e hora do lembrete"
        />
        <button
          type="button"
          className="jarvis-icon-btn shrink-0"
          disabled={!canAdd || !at}
          onClick={() => {
            const iso = localInputToIso(at);
            if (iso) void submit({ at: iso });
          }}
          title="Criar para esta data/hora"
          aria-label="Criar lembrete na data e hora"
        >
          <Plus size={14} />
        </button>
      </div>
      <label className="flex items-center gap-2 text-zinc-400 cursor-pointer">
        <input type="checkbox" checked={repeat} onChange={(e) => setRepeat(e.target.checked)} className="accent-cyan-400" />
        Repetir a cada hora
      </label>
      {error ? <p className="text-amber-300 text-[10px]">{error}</p> : <RemindersList items={items} onAction={async (id, action) => {
        const err = await update(id, action);
        if (err) toast.error(err);
      }} />}
    </div>
  );
}
