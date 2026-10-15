import { useEffect, useState } from 'react';
import { Brain, Loader2, Plus, Search } from 'lucide-react';
import { toast } from 'sonner';
import { useMemoryStore } from '../../lib/memoryStore';
import type { MemorySearchResult } from '../../lib/api';

export function MemoryView({ status, detail, entries, results, searching, onSearch, onRemember }: {
  status: ReturnType<typeof useMemoryStore.getState>['status'];
  detail: string | null;
  entries: number;
  results: MemorySearchResult[];
  searching: boolean;
  onSearch: (q: string) => void;
  onRemember: (text: string) => void;
}) {
  const [query, setQuery] = useState('');
  const [fact, setFact] = useState('');

  if (status === 'loading') {
    return <p className="text-zinc-500 flex items-center gap-2"><Loader2 size={12} className="animate-spin" /> Verificando memória…</p>;
  }
  if (status !== 'ready') {
    return (
      <div className="space-y-2">
        <p className="text-amber-300 flex items-center gap-2">
          <Brain size={13} /> {status === 'offline' ? 'Servidor sem resposta' : 'Memória indisponível'}
        </p>
        {detail && <p className="text-zinc-500 text-[10px] leading-relaxed break-words">{detail}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="jarvis-row">
        <span className="text-zinc-400 tracking-wider">LEMBRANÇAS</span>
        <span className="text-cyan-200 tabular-nums">{entries}</span>
      </div>

      <form
        className="flex gap-1.5"
        onSubmit={(e) => {
          e.preventDefault();
          if (fact.trim()) {
            onRemember(fact);
            setFact('');
          }
        }}
      >
        <input
          className="jarvis-field-input"
          placeholder="Lembre que… (ex.: prefiro café sem açúcar)"
          value={fact}
          onChange={(e) => setFact(e.target.value)}
          aria-label="Novo fato para lembrar"
        />
        <button type="submit" className="jarvis-icon-btn shrink-0" disabled={!fact.trim()} title="Lembrar" aria-label="Lembrar">
          <Plus size={14} />
        </button>
      </form>

      <form
        className="flex gap-1.5"
        onSubmit={(e) => {
          e.preventDefault();
          onSearch(query);
        }}
      >
        <input
          className="jarvis-field-input"
          placeholder="O que você sabe sobre…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Buscar na memória"
        />
        <button type="submit" className="jarvis-icon-btn shrink-0" disabled={!query.trim() || searching} title="Buscar" aria-label="Buscar">
          {searching ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
        </button>
      </form>

      {results.length > 0 && (
        <ul className="space-y-1.5 max-h-48 overflow-y-auto">
          {results.map((r, i) => (
            <li key={i} className="jarvis-row items-start gap-2">
              <span className="text-zinc-200 break-words min-w-0">{r.content}</span>
              <span className="text-zinc-600 tabular-nums shrink-0">{r.score.toFixed(2)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Store-connected memory tab for the HUD modules panel. */
export function HudMemory() {
  const s = useMemoryStore();
  const refresh = s.refresh;
  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <MemoryView
      status={s.status}
      detail={s.detail}
      entries={s.entries}
      results={s.results}
      searching={s.searching}
      onSearch={(q) => void s.search(q)}
      onRemember={async (text) => {
        const err = await s.remember(text);
        if (err) toast.error(`Não consegui lembrar: ${err}`);
        else toast.success('Anotado.');
      }}
    />
  );
}
