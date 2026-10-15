import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, Play, RefreshCw, Square } from 'lucide-react';
import { toast } from 'sonner';
import { apiFetch, getBase } from '../../lib/api';
import { HudMarkdown } from './HudLog';

export interface Digest {
  text: string;
  generated_at: string;
  model_used?: string;
  audio_available: boolean;
}

type Status = 'loading' | 'ready' | 'empty' | 'error';

export function BriefingView({ status, digest, error, generating, playing, onGenerate, onPlay }: {
  status: Status;
  digest: Digest | null;
  error: string | null;
  generating: boolean;
  playing: boolean;
  onGenerate: () => void;
  onPlay: () => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex gap-1.5">
        <button type="button" className="jarvis-quick-btn flex-1 justify-center disabled:opacity-40" disabled={generating} onClick={onGenerate}>
          {generating ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          {generating ? 'Gerando…' : status === 'ready' ? 'Atualizar briefing' : 'Gerar briefing'}
        </button>
        {digest?.audio_available && (
          <button type="button" className="jarvis-quick-btn" onClick={onPlay} aria-label={playing ? 'Parar áudio' : 'Ouvir briefing'}>
            {playing ? <Square size={12} /> : <Play size={12} />}
          </button>
        )}
      </div>
      {status === 'loading' && <p className="text-zinc-500">Carregando…</p>}
      {status === 'empty' && (
        <p className="text-zinc-500 leading-relaxed">
          Nenhum briefing hoje. "Gerar" junta agenda, e-mails, clima e notícias das fontes conectadas
          (Data Sources) e resume com o modelo atual.
        </p>
      )}
      {status === 'error' && error && <p className="text-amber-300 text-[10px] break-words">{error}</p>}
      {digest && status === 'ready' && (
        <div>
          <p className="text-[10px] text-zinc-500 mb-1">
            {new Date(digest.generated_at).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })}
            {digest.model_used && ` · ${digest.model_used}`}
          </p>
          <div className="max-h-64 overflow-y-auto text-cyan-100/90">
            <HudMarkdown text={digest.text} />
          </div>
        </div>
      )}
    </div>
  );
}

/** Morning briefing tab over /api/digest (generate, read, play audio). */
export function HudBriefing({ onSpeak }: { onSpeak?: (text: string) => void }) {
  const [status, setStatus] = useState<Status>('loading');
  const [digest, setDigest] = useState<Digest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch('/api/digest');
      if (res.status === 404) {
        setDigest(null);
        setStatus('empty');
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setDigest(await res.json());
      setStatus('ready');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    void load();
    return () => audioRef.current?.pause();
  }, [load]);

  const generate = async () => {
    setGenerating(true);
    try {
      const res = await apiFetch('/api/digest/generate', { method: 'POST' });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`);
      }
      await load();
      toast.success('Briefing pronto.');
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      toast.error(`Briefing: ${msg}`);
    } finally {
      setGenerating(false);
    }
  };

  const play = () => {
    if (playing) {
      audioRef.current?.pause();
      setPlaying(false);
      return;
    }
    if (digest?.audio_available) {
      const audio = new Audio(`${getBase()}/api/digest/audio`);
      audioRef.current = audio;
      audio.onended = () => setPlaying(false);
      audio.onerror = () => {
        setPlaying(false);
        if (digest) onSpeak?.(digest.text);
      };
      void audio.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
    } else if (digest) {
      onSpeak?.(digest.text);
    }
  };

  return (
    <BriefingView
      status={status}
      digest={digest}
      error={error}
      generating={generating}
      playing={playing}
      onGenerate={() => void generate()}
      onPlay={play}
    />
  );
}
