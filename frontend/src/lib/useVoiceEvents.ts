import { useCallback, useEffect, useRef, useState } from 'react';
import { getBase } from './api';
import { buildWsProtocols } from './useAgentEvents';

/** States published by the hands-free CLI voice loop (server/voice_events.py). */
export type VoiceState =
  | 'idle'
  | 'activated'
  | 'listening'
  | 'transcribing'
  | 'thinking'
  | 'speaking'
  | 'ended';

export interface VoiceLogEntry {
  id: string;
  role: 'user' | 'assistant' | 'system';
  text: string;
  timestamp: number; // ms
}

interface VoiceEventPayload {
  type: 'state' | 'transcript' | 'response' | 'level' | 'tool' | 'session';
  timestamp: number; // seconds (server clock)
  data: Record<string, unknown>;
}

export interface VoiceEventsSnapshot {
  connected: boolean;
  state: VoiceState;
  /** 0..1, decays to 0 when no level events arrive. */
  level: number;
  levelSource: 'listening' | 'speaking';
  log: VoiceLogEntry[];
  activeTool: string | null;
  engine: string;
  model: string;
  /** Forget the voice transcript shown in the HUD (live state is untouched). */
  clearLog: () => void;
}

const MAX_LOG = 100;
const LEVEL_DECAY_MS = 250;

export function buildVoiceWsUrl(): string {
  const base = getBase();
  const url = new URL('/v1/voice/ws', base || window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}

const END_REASONS: Record<string, string> = {
  idle_timeout: 'Sessão encerrada por inatividade. Bata palmas para reativar.',
  exit_phrase: 'Sessão encerrada por comando de voz.',
  interrupted: 'Sessão interrompida.',
  mic_error: 'Erro no microfone — sessão encerrada.',
  no_stt: 'Sem backend de transcrição — sessão encerrada.',
};

/**
 * Live voice-session state from the CLI voice loop, relayed by `jarvis serve`.
 * Reconnects with backoff; the server replays the last state on connect.
 */
export function useVoiceEvents(): VoiceEventsSnapshot {
  const [connected, setConnected] = useState(false);
  const [state, setState] = useState<VoiceState>('idle');
  const [level, setLevel] = useState(0);
  const [levelSource, setLevelSource] = useState<'listening' | 'speaking'>('listening');
  const [log, setLog] = useState<VoiceLogEntry[]>([]);
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const [session, setSession] = useState({ engine: '', model: '' });
  const decayTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const append = (role: VoiceLogEntry['role'], text: string) => {
      if (!text) return;
      seq.current += 1;
      const entry = { id: `voice-${Date.now()}-${seq.current}`, role, text, timestamp: Date.now() };
      setLog((prev) => [...prev.slice(-(MAX_LOG - 1)), entry]);
    };

    const handle = (ev: VoiceEventPayload) => {
      const d = ev.data || {};
      switch (ev.type) {
        case 'state': {
          const next = String(d.state || 'idle') as VoiceState;
          setState(next);
          if (next !== 'listening' && next !== 'speaking') setLevel(0);
          if (next === 'activated') append('system', 'Palmas detectadas — sessão de voz ativa.');
          if (next === 'ended') {
            setActiveTool(null);
            const reason = END_REASONS[String(d.reason || '')];
            if (reason) append('system', reason);
          }
          break;
        }
        case 'transcript':
          append('user', String(d.text || ''));
          break;
        case 'response':
          append('assistant', String(d.text || ''));
          break;
        case 'level': {
          setLevel(Math.max(0, Math.min(1, Number(d.level) || 0)));
          setLevelSource(d.source === 'speaking' ? 'speaking' : 'listening');
          if (decayTimer.current) clearTimeout(decayTimer.current);
          decayTimer.current = setTimeout(() => setLevel(0), LEVEL_DECAY_MS);
          break;
        }
        case 'tool':
          setActiveTool(d.phase === 'end' ? null : String(d.name || ''));
          if (d.phase !== 'end' && d.name) append('system', `Executando ferramenta: ${String(d.name)}`);
          break;
        case 'session':
          setSession({ engine: String(d.engine || ''), model: String(d.model || '') });
          break;
      }
    };

    const schedule = () => {
      if (closed) return;
      const delay = Math.min(15000, 1000 * 2 ** Math.min(retry, 4));
      retry += 1;
      reconnectTimer = setTimeout(connect, delay);
    };

    const connect = () => {
      if (closed) return;
      try {
        ws = new WebSocket(buildVoiceWsUrl(), buildWsProtocols());
      } catch {
        schedule();
        return;
      }
      ws.onopen = () => {
        retry = 0;
        setConnected(true);
      };
      ws.onmessage = (msg) => {
        try {
          handle(JSON.parse(msg.data) as VoiceEventPayload);
        } catch {
          // ignore malformed payload
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) schedule();
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (decayTimer.current) clearTimeout(decayTimer.current);
      ws?.close();
    };
  }, []);

  const clearLog = useCallback(() => setLog([]), []);

  return { connected, state, level, levelSource, log, activeTool, ...session, clearLog };
}
