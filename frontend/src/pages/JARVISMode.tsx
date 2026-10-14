import { useRef, useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import { useAppStore } from '../lib/store';
import { useVoiceEvents, type VoiceLogEntry } from '../lib/useVoiceEvents';
import { apiFetch, checkHealth } from '../lib/api';
import { sendChatTurn } from '../lib/chatTurn';
import { useHudSettings } from '../lib/hudSettings';
import { useSpeech } from '../hooks/useSpeech';
import { useTts } from '../hooks/useTts';
// Bundled locally so the HUD typography also works offline (Tauri).
import '@fontsource/chakra-petch/500.css';
import '@fontsource/chakra-petch/600.css';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import {
  Mic, MicOff, Volume2, Headphones, Cpu, HardDrive, Wifi, Activity, Terminal, X,
  ChevronUp, ChevronDown, Settings, Sparkles, Camera, Thermometer, Send, Square,
  MessageSquare, Server, SlidersHorizontal, RotateCcw, Loader2,
} from 'lucide-react';

/**
 * JARVIS Mode - Cinematic HUD Interface
 * Arc Reactor centerpiece, holographic panels, voice waveforms, system telemetry
 *
 * Layout: header / three-column grid (panels | core | panels) / input footer.
 * Nothing is absolutely positioned over anything else, so panels can never
 * cover the reactor, the status bar or the input.
 */

// Shared colour language: cyan = idle/listening, purple = speaking/processing.
const HUE_IDLE = 188;
const HUE_LISTEN = 192;
const HUE_SPEAK = 272;

function stateHue(isListening: boolean, isSpeaking: boolean) {
  return isListening ? HUE_LISTEN : isSpeaking ? HUE_SPEAK : HUE_IDLE;
}

/** Keeps a canvas sized to its CSS box (with DPR) and returns the logical size. */
function useCanvasSize(canvasRef: React.RefObject<HTMLCanvasElement | null>) {
  const sizeRef = useRef({ w: 0, h: 0 });
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const apply = () => {
      const dpr = window.devicePixelRatio || 1;
      const { width, height } = canvas.getBoundingClientRect();
      sizeRef.current = { w: width, h: height };
      canvas.width = Math.max(1, Math.round(width * dpr));
      canvas.height = Math.max(1, Math.round(height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [canvasRef]);
  return sizeRef;
}

/** Latest props in a ref, so animation loops don't restart on every level tick. */
function useLatest<T>(value: T) {
  const ref = useRef(value);
  ref.current = value;
  return ref;
}

// ─── Arc Reactor Canvas Component ───
function ArcReactor(props: {
  isActive: boolean;
  isListening: boolean;
  isSpeaking: boolean;
  audioLevel: number;
  /** "Reduzir animações": slow spin, no particles. */
  calm?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const sizeRef = useCanvasSize(canvasRef);
  const propsRef = useLatest(props);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;

    let raf = 0;
    let last = 0;
    let phase = 0;

    const draw = (timestamp: number) => {
      const { isActive, isListening, isSpeaking, audioLevel, calm } = propsRef.current;
      const dt = last ? (timestamp - last) / 1000 : 0;
      last = timestamp;
      phase += dt * (isSpeaking ? 3 : isListening ? 2 : 0.8) * (calm ? 0.25 : 1);

      const { w, h } = sizeRef.current;
      ctx.clearRect(0, 0, w, h);
      if (!w || !h) {
        raf = requestAnimationFrame(draw);
        return;
      }
      // Outer band is reserved for the SVG tick ring (ReactorHUD).
      const maxRadius = Math.min(w, h) / 2 / 1.3;
      const hue = stateHue(isListening, isSpeaking);

      ctx.save();
      ctx.translate(w / 2, h / 2);

      // Outer glow rings
      for (let i = 0; i < 5; i++) {
        const progress = (phase * 0.15 + i * 0.2) % 1;
        const radius = maxRadius * (0.45 + progress * 0.55);
        const opacity = (1 - progress) * (isActive ? 0.6 : 0.25) * (0.3 + audioLevel * 0.7);
        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.strokeStyle = `hsla(${hue}, 100%, 55%, ${opacity})`;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      // Core rings - segmented arc reactor style
      const segments = 12;
      const segmentAngle = (Math.PI * 2) / segments;
      ctx.lineCap = 'round';
      ctx.shadowColor = `hsla(${hue}, 100%, 60%, 0.8)`;
      ctx.shadowBlur = 8;
      for (let ring = 0; ring < 4; ring++) {
        const ringRadius = maxRadius * (0.2 + ring * 0.21);
        const direction = ring % 2 === 0 ? 1 : -1;
        const angleOffset = direction * phase * (0.3 + ring * 0.1);
        for (let seg = 0; seg < segments; seg++) {
          const lit = (seg + Math.floor(phase * 2)) % 3 === 0;
          const startAngle = seg * segmentAngle + angleOffset;
          ctx.beginPath();
          ctx.arc(0, 0, ringRadius, startAngle, startAngle + segmentAngle * 0.7);
          const brightness = lit ? 75 : 35 + audioLevel * 35;
          ctx.strokeStyle = `hsla(${hue}, 100%, ${brightness}%, ${isActive ? 0.9 : 0.5})`;
          ctx.lineWidth = 2 + ring;
          ctx.stroke();
        }
      }
      ctx.shadowBlur = 0;

      // Inner core
      const coreRadius = maxRadius * 0.12;
      const coreGradient = ctx.createRadialGradient(0, 0, 0, 0, 0, coreRadius);
      coreGradient.addColorStop(0, `hsla(${hue}, 100%, 85%, 1)`);
      coreGradient.addColorStop(0.5, `hsla(${hue}, 100%, 60%, 0.9)`);
      coreGradient.addColorStop(1, `hsla(${hue}, 100%, 30%, 0.6)`);
      ctx.beginPath();
      ctx.arc(0, 0, coreRadius, 0, Math.PI * 2);
      ctx.fillStyle = coreGradient;
      ctx.fill();

      // Core pulse
      const pulseScale = 1 + Math.sin(phase * 4) * 0.08 * (isSpeaking ? 2 : isListening ? 1.5 : 1);
      ctx.beginPath();
      ctx.arc(0, 0, coreRadius * pulseScale * 1.3, 0, Math.PI * 2);
      ctx.strokeStyle = `hsla(${hue}, 100%, 70%, ${0.4 + audioLevel * 0.5})`;
      ctx.lineWidth = 1.5;
      ctx.shadowColor = `hsla(${hue}, 100%, 70%, 0.6)`;
      ctx.shadowBlur = 15;
      ctx.stroke();
      ctx.shadowBlur = 0;

      // Rotating outer triangle markers
      const marker = Math.max(5, maxRadius * 0.05);
      for (let t = 0; t < 3; t++) {
        ctx.save();
        ctx.rotate(phase * 0.5 + t * (Math.PI * 2 / 3));
        const r = maxRadius * 1.08;
        ctx.beginPath();
        ctx.moveTo(0, -r);
        ctx.lineTo(-marker, -r + marker * 2.2);
        ctx.lineTo(marker, -r + marker * 2.2);
        ctx.closePath();
        ctx.fillStyle = `hsla(${hue}, 100%, 55%, ${0.35 + audioLevel * 0.4})`;
        ctx.fill();
        ctx.restore();
      }

      // Energy particles
      if (isActive && !calm) {
        for (let p = 0; p < 20; p++) {
          const a = (phase * 0.5 + p * 0.3) % (Math.PI * 2);
          const pr = maxRadius * (0.3 + Math.sin(p) * 0.2);
          const size = 1.2 + Math.sin(phase * 3 + p) * 0.8;
          ctx.beginPath();
          ctx.arc(Math.cos(a) * pr, Math.sin(a) * pr, Math.max(0.3, size), 0, Math.PI * 2);
          ctx.fillStyle = `hsla(${hue}, 100%, 75%, ${0.35 + Math.sin(phase * 5 + p) * 0.2})`;
          ctx.fill();
        }
      }

      ctx.restore();
      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [propsRef, sizeRef]);

  return <canvas ref={canvasRef} className="jarvis-arc-reactor" aria-label="JARVIS Core" role="img" />;
}

// ─── Reactor HUD Ring (SVG overlay) ───
function arcPath(r: number, startDeg: number, endDeg: number) {
  const pt = (deg: number) => {
    const a = (deg * Math.PI) / 180;
    return `${(100 + r * Math.sin(a)).toFixed(2)} ${(100 - r * Math.cos(a)).toFixed(2)}`;
  };
  return `M ${pt(startDeg)} A ${r} ${r} 0 0 1 ${pt(endDeg)}`;
}

const HUD_TICKS = Array.from({ length: 72 }, (_, i) => {
  const major = i % 6 === 0;
  const a = (i * 5 * Math.PI) / 180;
  const r1 = 97;
  const r2 = major ? 91 : 94.5;
  return {
    major,
    x1: 100 + r1 * Math.sin(a), y1: 100 - r1 * Math.cos(a),
    x2: 100 + r2 * Math.sin(a), y2: 100 - r2 * Math.cos(a),
  };
});

function ReactorHUD() {
  return (
    <svg className="jarvis-reactor-hud" viewBox="0 0 200 200" aria-hidden="true">
      <g className="jarvis-hud-spin-slow" stroke="currentColor">
        {HUD_TICKS.map((t, i) => (
          <line key={i} x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2}
            strokeWidth={t.major ? 0.9 : 0.4} opacity={t.major ? 0.85 : 0.35} />
        ))}
      </g>
      <g className="jarvis-hud-spin-rev" fill="none" stroke="currentColor">
        <circle cx="100" cy="100" r="88" strokeWidth="0.4" strokeDasharray="1.5 3.5" opacity="0.45" />
        {[0, 120, 240].map((d) => (
          <path key={d} d={arcPath(85, d + 10, d + 50)} strokeWidth="1.4" opacity="0.7" strokeLinecap="round" />
        ))}
      </g>
      <g fill="currentColor" opacity="0.8">
        {[0, 90, 180, 270].map((d) => (
          <rect key={d} x="98.6" y="0.5" width="2.8" height="2.8" transform={`rotate(${d} 100 100) rotate(45 100 1.9)`} />
        ))}
      </g>
    </svg>
  );
}

// ─── Voice Waveform Component ───
function VoiceWaveform(props: { isListening: boolean; isSpeaking: boolean; audioLevel: number }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const sizeRef = useCanvasSize(canvasRef);
  const propsRef = useLatest(props);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;

    const barCount = 48;
    const bars = new Array(barCount).fill(0);
    let raf = 0;

    const draw = (timestamp: number) => {
      const { isListening, isSpeaking, audioLevel } = propsRef.current;
      const { w, h } = sizeRef.current;
      ctx.clearRect(0, 0, w, h);

      const active = isListening || isSpeaking;
      // Speaking without a level feed still animates gently.
      const level = active ? Math.max(audioLevel, isSpeaking ? 0.35 : 0) : 0;
      for (let i = 0; i < barCount; i++) {
        const target = level * h * 0.9 * (0.3 + Math.abs(Math.sin(timestamp / 200 + i * 0.3)) * 0.7);
        bars[i] += active ? (target - bars[i]) * 0.15 : -bars[i] * 0.08;
      }

      const slot = w / barCount;
      const barWidth = slot * 0.6;
      const centerY = h / 2;
      const hue = stateHue(isListening, isSpeaking);
      ctx.shadowColor = `hsla(${hue}, 100%, 60%, 0.5)`;
      ctx.shadowBlur = 6;
      for (let i = 0; i < barCount; i++) {
        const height = Math.max(2, bars[i]);
        // Fade towards both edges so the bar reads as centred under the reactor.
        const edge = 1 - Math.abs(i / (barCount - 1) - 0.5) * 2;
        ctx.fillStyle = `hsla(${hue}, 100%, 60%, ${0.25 + edge * 0.65})`;
        const x = i * slot + (slot - barWidth) / 2;
        ctx.beginPath();
        ctx.roundRect(x, centerY - height / 2, barWidth, height, barWidth / 2);
        ctx.fill();
      }
      ctx.shadowBlur = 0;

      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [propsRef, sizeRef]);

  return <canvas ref={canvasRef} className="jarvis-waveform" aria-hidden="true" />;
}

// ─── HUD Panel Component ───
function HUDPanel({
  title,
  children,
  icon,
  badge,
  code,
  collapsible = false,
  grow = false,
  className = '',
}: {
  title: string;
  children: React.ReactNode;
  icon?: React.ReactNode;
  badge?: string;
  /** Small panel designation shown in the header, e.g. SYS·01. */
  code?: string;
  collapsible?: boolean;
  /** Fill the remaining column height (body scrolls internally). */
  grow?: boolean;
  className?: string;
}) {
  const [expanded, setExpanded] = useState(true);

  return (
    <section
      className={`jarvis-hud-panel ${grow && expanded ? 'lg:flex-1 lg:min-h-0' : 'shrink-0'} ${className}`}
    >
      <header className="jarvis-hud-panel-head">
        <div className="flex items-center gap-2 min-w-0">
          {icon && <span className="text-cyan-400 shrink-0">{icon}</span>}
          <h3 className="truncate">{title}</h3>
          {badge && <span className="jarvis-badge">{badge}</span>}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {code && <span className="jarvis-panel-code">{code}</span>}
          {collapsible && (
          <button
            onClick={() => setExpanded((e) => !e)}
            className="jarvis-icon-btn"
            aria-label={expanded ? 'Recolher' : 'Expandir'}
            aria-expanded={expanded}
          >
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          )}
        </div>
      </header>
      {expanded && (
        <div className={grow ? 'flex flex-col min-h-0 flex-1' : 'p-3'}>{children}</div>
      )}

      {/* Corner brackets */}
      <span className="jarvis-corner top-0 left-0 border-t-2 border-l-2 rounded-tl-xl" />
      <span className="jarvis-corner top-0 right-0 border-t-2 border-r-2 rounded-tr-xl" />
      <span className="jarvis-corner bottom-0 left-0 border-b-2 border-l-2 rounded-bl-xl" />
      <span className="jarvis-corner bottom-0 right-0 border-b-2 border-r-2 rounded-br-xl" />
    </section>
  );
}

// ─── System Metrics Panel ───
// gpu/temp are null when the host has no NVIDIA GPU (NVML unavailable).
type Metrics = { cpu: number; gpu: number | null; ram: number; netUp: number; netDown: number; temp: number | null };

/** Polls host telemetry; `metrics` is null while the server can't provide it. */
function useSystemMetrics(enabled: boolean) {
  const [metrics, setMetrics] = useState<Metrics | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    const update = async () => {
      try {
        // apiFetch adds the base URL and the API key, like every other panel.
        const res = await apiFetch('/api/system/metrics');
        if (res.ok && res.headers.get('content-type')?.includes('json')) {
          const data = (await res.json()) as Metrics;
          if (alive) setMetrics(data);
          return;
        }
      } catch {}
      if (alive) setMetrics(null);
    };
    update();
    const interval = setInterval(update, 2000);
    return () => {
      alive = false;
      clearInterval(interval);
    };
  }, [enabled]);

  return metrics;
}

type ServerStatus = 'checking' | 'online' | 'offline';

function useServerStatus(): ServerStatus {
  const [status, setStatus] = useState<ServerStatus>('checking');
  useEffect(() => {
    let alive = true;
    const probe = () =>
      checkHealth()
        .then((ok) => alive && setStatus(ok ? 'online' : 'offline'))
        .catch(() => alive && setStatus('offline'));
    probe();
    const id = setInterval(probe, 10000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);
  return status;
}

function MetricBar({ label, value, unit, max = 100, icon: Icon, color }: {
  label: string;
  value: number | null;
  unit: string;
  max?: number;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  color: string;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-[11px]">
        <span className="flex items-center gap-1.5 text-zinc-400 tracking-wider">
          <Icon size={12} className="text-cyan-400/70" />
          {label}
        </span>
        <span className="text-cyan-200 tabular-nums">
          {value === null ? <span className="text-zinc-500">—</span> : <>{value.toFixed(1)}<span className="text-zinc-500 ml-0.5">{unit}</span></>}
        </span>
      </div>
      <div className="h-1 rounded-full overflow-hidden bg-cyan-400/10">
        <div
          className="h-full rounded-full transition-[width] duration-500 ease-out"
          style={{ width: `${value === null ? 0 : Math.min(100, (value / max) * 100)}%`, background: color, boxShadow: `0 0 8px ${color}80` }}
        />
      </div>
    </div>
  );
}

function SystemMetrics({ metrics }: { metrics: Metrics | null }) {
  const m = metrics;
  return (
    <div className="space-y-3 jarvis-font-hud">
      <MetricBar label="CPU" value={m ? m.cpu : null} unit="%" icon={Cpu} color="#22d3ee" />
      <MetricBar label="GPU" value={m ? m.gpu : null} unit="%" icon={Activity} color="#a855f7" />
      <MetricBar label="RAM" value={m ? m.ram : null} unit="%" icon={HardDrive} color="#f59e0b" />
      <MetricBar label="TEMP GPU" value={m ? m.temp : null} unit="°C" icon={Thermometer} color="#f43f5e" />
      <div className="grid grid-cols-2 gap-2 pt-1">
        {[
          { label: 'UP', value: m ? m.netUp : null },
          { label: 'DOWN', value: m ? m.netDown : null },
        ].map((n) => (
          <div key={n.label} className="jarvis-tile">
            <span className="flex items-center gap-1 text-zinc-500 text-[10px] tracking-wider">
              <Wifi size={11} /> {n.label}
            </span>
            <span className="text-cyan-200 text-xs tabular-nums">
              {n.value === null ? <span className="text-zinc-500">—</span> : n.value.toFixed(1)}{' '}
              <span className="text-zinc-500">Mb/s</span>
            </span>
          </div>
        ))}
      </div>
      {m && m.gpu === null && (
        <p className="text-[10px] text-zinc-500">GPU NVIDIA não detectada — GPU e temperatura indisponíveis.</p>
      )}
    </div>
  );
}

// ─── Terminal Chat Log ───
function TerminalChat({ voiceLog = [], userName }: { voiceLog?: VoiceLogEntry[]; userName: string }) {
  const messages = useAppStore(s => s.messages);
  const streamState = useAppStore(s => s.streamState);
  const isStreaming = streamState.isStreaming;
  const streamContent = streamState.content;
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages, streamContent, isStreaming, autoScroll, voiceLog]);

  const formatTime = (ts: number) => new Date(ts).toLocaleTimeString('pt-BR', { hour12: false });

  // Typed chat (store) + hands-free voice turns, in time order.
  const entries = [
    ...messages.map((m) => ({
      id: m.id,
      role: m.role as string,
      text: m.content,
      timestamp: m.timestamp || Date.now(),
    })),
    ...voiceLog.map((v) => ({ id: v.id, role: v.role as string, text: v.text, timestamp: v.timestamp })),
  ].sort((a, b) => a.timestamp - b.timestamp);

  return (
    <div
      ref={containerRef}
      onScroll={(e) => {
        const { scrollTop, scrollHeight, clientHeight } = e.currentTarget;
        setAutoScroll(scrollHeight - scrollTop - clientHeight < 50);
      }}
      className="jarvis-terminal jarvis-font-hud"
    >
      {entries.length === 0 && !isStreaming ? (
        <div className="h-full flex flex-col items-center justify-center text-center gap-2 py-6">
          <p className="jarvis-font-display text-cyan-400/70 text-sm tracking-[0.3em]">JARVIS ONLINE</p>
          <p className="text-[11px] text-zinc-500">Aguardando comando, {userName}.</p>
          <div className="mt-2 flex flex-wrap justify-center gap-1.5">
            {['"Aumente o volume"', '"Feche o Chrome"', '"Print da tela"'].map((s) => (
              <kbd key={s} className="jarvis-chip">{s}</kbd>
            ))}
          </div>
        </div>
      ) : (
        <div className="space-y-2.5">
          {entries.map((msg) => msg.role === 'system' ? (
            <div key={msg.id} className="terminal-message text-zinc-500 italic">
              <span className="text-zinc-600">{formatTime(msg.timestamp)}</span>
              <span className="mx-1.5 text-cyan-500/40">◆</span>
              {msg.text}
            </div>
          ) : (
            <div key={msg.id} className={`terminal-message ${msg.role === 'user' ? 'is-user' : 'is-jarvis'}`}>
              <div className="flex items-baseline gap-2 text-[10px] tracking-wider">
                <span className={msg.role === 'user' ? 'text-amber-400' : 'text-cyan-400'}>
                  {msg.role === 'user' ? userName.toUpperCase() : 'JARVIS'}
                </span>
                <span className="text-zinc-600">{formatTime(msg.timestamp)}</span>
              </div>
              <p className={`whitespace-pre-wrap break-words ${msg.role === 'user' ? 'text-amber-100/90' : 'text-cyan-100/90'}`}>
                {msg.text}
              </p>
            </div>
          ))}

          {isStreaming && streamContent && (
            <div className="terminal-message is-jarvis">
              <div className="text-[10px] tracking-wider text-cyan-400">JARVIS</div>
              <p className="whitespace-pre-wrap break-words text-cyan-100/90">
                {streamContent}
                <span className="ml-0.5 text-cyan-400 animate-blink">█</span>
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

// ─── Main JARVIS Mode Page ───
export function JARVISMode() {
  const navigate = useNavigate();
  const hud = useHudSettings((s) => s.hud);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const voice = useVoiceEvents();
  const speech = useSpeech();
  const tts = useTts();
  const settings = useAppStore((s) => s.settings);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const serverInfo = useAppStore((s) => s.serverInfo);
  const streamState = useAppStore((s) => s.streamState);
  const activeId = useAppStore((s) => s.activeId);
  const serverStatus = useServerStatus();
  const metrics = useSystemMetrics(hud.showTelemetry);
  const now = useClock();

  // Two voice sources: the hands-free CLI loop (relayed over WebSocket) and
  // the browser mic/speaker driven from this page.
  const voiceListening = voice.state === 'listening';
  const voiceSpeaking = voice.state === 'speaking';
  const voiceThinking = voice.state === 'thinking' || voice.state === 'transcribing';
  const voiceSessionActive = !['idle', 'ended'].includes(voice.state);
  const browserRecording = speech.state === 'recording';
  const browserTranscribing = speech.state === 'transcribing';

  const isListening = voiceListening || browserRecording;
  const isSpeaking = voiceSpeaking || tts.isSpeaking;
  const chatStreaming = streamState.isStreaming;
  const isStreaming = chatStreaming || voiceThinking || browserTranscribing || tts.isLoading;
  const isActive = activeId !== null || voiceSessionActive;
  // The browser paths have no level meter; a steady mid level keeps the
  // waveform alive (it already modulates per bar).
  const audioLevel = voiceListening || voiceSpeaking
    ? voice.level
    : browserRecording || tts.isSpeaking ? 0.55 : 0;

  const micEnabled = settings.speechEnabled && speech.available;
  const ttsEnabled = settings.voiceOutputEnabled && tts.available;

  useEffect(() => {
    if (speech.error) toast.error(speech.error, { duration: 6000 });
  }, [speech.error]);
  useEffect(() => {
    if (tts.error) toast.error(`Voz: ${tts.error}`, { duration: 6000 });
  }, [tts.error]);

  // Esc closes the settings drawer (the HUD is the home screen; no "exit").
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSettingsOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const handleSendMessage = useCallback(async (text: string) => {
    if (!text.trim()) return;
    if (!useAppStore.getState().selectedModel) {
      toast.error('Nenhum modelo selecionado — escolha um nas configurações do HUD.');
      setSettingsOpen(true);
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    const result = await sendChatTurn(text, controller.signal);
    abortRef.current = null;
    if (!result || result.aborted || result.content.startsWith('Error:')) return;

    const { voiceOutputEnabled, voiceAutoplay } = useAppStore.getState().settings;
    if (voiceOutputEnabled && voiceAutoplay) {
      const msgs = useAppStore.getState().messages;
      const last = msgs[msgs.length - 1];
      void tts.speak(last?.id ?? `hud-${Date.now()}`, result.content);
    }
  }, [tts]);

  const handleStop = () => {
    abortRef.current?.abort();
    tts.stop();
  };

  const handleMic = async () => {
    if (browserRecording) {
      try {
        const text = await speech.stopRecording();
        if (text.trim()) await handleSendMessage(text);
      } catch {
        // useSpeech surfaces the error (toast above)
      }
      return;
    }
    tts.stop();
    await speech.startRecording();
  };

  const handleSpeakTest = () => {
    if (tts.isSpeaking || tts.isLoading) {
      tts.stop();
      return;
    }
    void tts.speak('hud-voice-test', `Olá, ${hud.userName}. Todos os sistemas operacionais.`);
  };

  const statusLabel = isListening
    ? 'ESCUTANDO'
    : isSpeaking
      ? 'FALANDO'
      : isStreaming
        ? 'PROCESSANDO'
        : voice.state === 'activated'
          ? 'ATIVANDO'
          : serverStatus === 'offline'
            ? 'SERVIDOR OFFLINE'
            : 'PRONTO';

  const activeTool = voice.activeTool || (chatStreaming ? streamState.activeToolCalls.find((t) => t.status === 'running')?.tool : null);
  const coreLabel = isListening
    ? 'MICROFONE ATIVO'
    : isSpeaking
      ? 'SÍNTESE DE VOZ'
      : activeTool
        ? `EXECUTANDO: ${activeTool}`
        : browserTranscribing
          ? 'TRANSCREVENDO'
          : isStreaming
            ? 'PROCESSANDO REQUISIÇÃO'
            : 'SISTEMA OPERACIONAL';

  const coreHint = browserRecording
    ? 'Fale agora — clique em "Enviar fala" quando terminar'
    : voiceListening
      ? 'Diga seu comando… ("Jarvis, desligar" encerra)'
      : voiceSessionActive
        ? 'Sessão de voz ativa'
        : micEnabled
          ? 'Bata duas palmas, use o microfone ou digite um comando'
          : 'Bata duas palmas ou digite um comando';

  const micTitle = !settings.speechEnabled
    ? 'Entrada por voz desativada nas configurações'
    : !speech.available
      ? 'Sem backend de transcrição no servidor (uv sync --extra speech)'
      : browserRecording
        ? 'Parar e enviar'
        : 'Falar com o JARVIS pelo microfone do navegador';

  return (
    <div className={`jarvis-mode fixed inset-0 z-50 flex flex-col overflow-hidden text-zinc-300 ${hud.reducedMotion ? 'is-reduced-motion' : ''}`}>
      {/* Background layers */}
      <div className="jarvis-bg absolute inset-0 pointer-events-none" aria-hidden="true" />
      <div className="jarvis-grid-bg absolute inset-0 pointer-events-none" aria-hidden="true" />
      {hud.particles && !hud.reducedMotion && <ParticleField count={30} />}
      {hud.scanlines && <div className="jarvis-scanlines absolute inset-0 pointer-events-none" aria-hidden="true" />}
      <div className="jarvis-vignette absolute inset-0 pointer-events-none" aria-hidden="true" />

      {/* Top Status Bar */}
      <header className="jarvis-topbar relative z-10 shrink-0">
        <div className="flex items-center gap-2 sm:gap-3 min-w-0">
          <div className="jarvis-pill">
            <span className={`w-2 h-2 rounded-full ${serverStatus === 'offline' ? 'bg-rose-500' : 'bg-emerald-400 animate-pulse'}`} />
            <span className="jarvis-font-display text-cyan-200 tracking-[0.25em]">J.A.R.V.I.S.</span>
          </div>
          <div className="jarvis-pill">
            <span className="text-zinc-500">STATUS</span>
            <span className={serverStatus === 'offline' && !isStreaming ? 'text-rose-300' : isSpeaking || isStreaming ? 'text-purple-300' : 'text-cyan-300'}>{statusLabel}</span>
          </div>
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            className="jarvis-pill hidden md:flex hover:border-cyan-400/40"
            title="Trocar modelo"
          >
            <span className="text-zinc-500">MODELO</span>
            <span className={`truncate max-w-[14rem] ${selectedModel ? 'text-cyan-200' : 'text-amber-300'}`}>
              {selectedModel || 'NENHUM'}
            </span>
          </button>
          <div
            className="jarvis-pill hidden lg:flex"
            title={voice.connected ? 'Conectado ao relay de voz (/v1/voice/ws)' : 'Sem conexão com jarvis serve'}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${voice.connected ? 'bg-cyan-400' : 'bg-rose-500'}`} />
            <span className={voice.connected ? 'text-cyan-300' : 'text-rose-300'}>
              {voice.connected ? 'VOZ LINK' : 'VOZ OFFLINE'}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2 sm:gap-3 shrink-0">
          <div className="jarvis-pill hidden md:flex" title={now.toLocaleDateString('pt-BR')}>
            <span className="text-zinc-500">{now.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' }).toUpperCase().replace('.', '')}</span>
            <span className="text-cyan-200 tabular-nums">{now.toLocaleTimeString('pt-BR', { hour12: false })}</span>
          </div>
          <div className="jarvis-pill hidden xl:flex">
            <span className="text-zinc-500">USUÁRIO</span>
            <span className="text-cyan-200 truncate max-w-[10rem]">{hud.userName}</span>
          </div>
          <div className="hidden sm:block w-24 h-1.5 rounded-full bg-zinc-900/60 border border-cyan-500/15 overflow-hidden" title="Nível de áudio">
            <div
              className="h-full rounded-full transition-[width] duration-100"
              style={{ width: `${audioLevel * 100}%`, background: 'linear-gradient(90deg, #22d3ee, #a855f7)' }}
            />
          </div>
          <button onClick={() => navigate('/chat')} className="jarvis-icon-btn" title="Interface clássica (chat, agentes, dashboard)" aria-label="Abrir interface clássica">
            <MessageSquare size={15} />
          </button>
          <button onClick={() => setSettingsOpen(true)} className="jarvis-icon-btn" title="Configurações do HUD" aria-label="Configurações do HUD">
            <Settings size={15} />
          </button>
        </div>
      </header>

      {/* Main grid: side panels never overlap the core */}
      <main className="jarvis-grid relative z-10 flex-1 min-h-0">
        {/* Left column */}
        <div className="jarvis-col order-2 lg:order-1">
          {hud.showTelemetry && (
            <HUDPanel
              title="Telemetria"
              icon={<Cpu size={14} />}
              badge={metrics ? undefined : 'OFFLINE'}
              code="SYS·01"
              collapsible
            >
              <SystemMetrics metrics={metrics} />
            </HUDPanel>
          )}
          <HUDPanel title="Log de Comunicação" icon={<Terminal size={14} />} code="COM·02" collapsible grow className="h-80 lg:h-auto">
            <TerminalChat voiceLog={voice.log} userName={hud.userName} />
          </HUDPanel>
        </div>

        {/* Center - Arc Reactor + Voice Waveform */}
        <section className="jarvis-core order-1 lg:order-2">
          <div className={`jarvis-reactor-wrap ${isSpeaking || isStreaming ? 'is-speaking' : ''}`}>
            <ReactorHUD />
            <ArcReactor
              isActive={isActive}
              isListening={isListening}
              isSpeaking={isSpeaking || isStreaming}
              audioLevel={audioLevel}
              calm={hud.reducedMotion}
            />
          </div>

          <div className="text-center jarvis-font-hud px-2">
            <p className={`jarvis-font-display text-sm tracking-[0.3em] uppercase ${isSpeaking || isStreaming ? 'text-purple-300/90' : 'text-cyan-300/80'}`}>
              {coreLabel}
            </p>
            <p className="text-[11px] tracking-wider text-zinc-500 mt-1.5">{coreHint}</p>
          </div>

          <VoiceWaveform
            isListening={isListening}
            isSpeaking={isSpeaking || isStreaming}
            audioLevel={audioLevel}
          />

          <div className="flex flex-wrap items-center justify-center gap-3">
            <button
              onClick={handleMic}
              disabled={!micEnabled || browserTranscribing || chatStreaming}
              className={`jarvis-voice-btn ${browserRecording ? 'is-on-cyan' : ''} disabled:opacity-40 disabled:cursor-not-allowed`}
              aria-pressed={browserRecording}
              title={micTitle}
            >
              {browserTranscribing ? <Loader2 size={14} className="animate-spin" /> : browserRecording ? <Send size={14} /> : <Mic size={14} />}
              {browserTranscribing ? 'Transcrevendo…' : browserRecording ? 'Enviar fala' : 'Falar'}
            </button>
            {chatStreaming || tts.isSpeaking || tts.isLoading ? (
              <button onClick={handleStop} className="jarvis-voice-btn is-on-purple">
                <Square size={13} />
                Interromper
              </button>
            ) : (
              <button
                onClick={handleSpeakTest}
                disabled={!ttsEnabled}
                className="jarvis-voice-btn disabled:opacity-40 disabled:cursor-not-allowed"
                title={ttsEnabled ? 'Ouvir a voz do JARVIS' : 'Saída de voz desativada ou sem backend de TTS'}
              >
                <Volume2 size={14} />
                Testar voz
              </button>
            )}
          </div>
        </section>

        {/* Right column */}
        <div className="jarvis-col order-3">
          <HUDPanel title="Status" icon={<Server size={14} />} code="CTL·03" collapsible>
            <div className="space-y-1.5 jarvis-font-hud text-[11px]">
              <SystemControlRow
                label="SERVIDOR"
                value={serverStatus === 'checking' ? '…' : serverStatus === 'online' ? 'ONLINE' : 'OFFLINE'}
                icon={Server}
                status={serverStatus === 'online' ? 'online' : serverStatus === 'offline' ? 'offline' : undefined}
              />
              <SystemControlRow label="ENGINE" value={(serverInfo?.engine || '—').toUpperCase()} icon={Cpu} />
              <SystemControlRow
                label="TRANSCRIÇÃO"
                value={!settings.speechEnabled ? 'DESLIGADA' : speech.available ? 'PRONTA' : 'INDISPONÍVEL'}
                icon={Mic}
                status={!settings.speechEnabled ? undefined : speech.available ? 'online' : 'warning'}
              />
              <SystemControlRow
                label="VOZ (TTS)"
                value={!settings.voiceOutputEnabled ? 'DESLIGADA' : tts.available ? 'PRONTA' : 'INDISPONÍVEL'}
                icon={Volume2}
                status={!settings.voiceOutputEnabled ? undefined : tts.available ? 'online' : 'warning'}
              />
              <SystemControlRow
                label="RELAY DE VOZ"
                value={voice.connected ? 'CONECTADO' : 'DESCONECTADO'}
                icon={Wifi}
                status={voice.connected ? 'online' : 'offline'}
              />
            </div>
          </HUDPanel>
          <HUDPanel title="Ações Rápidas" icon={<Sparkles size={14} />} code="ACT·04" collapsible>
            <QuickActions onAction={handleSendMessage} disabled={chatStreaming} />
          </HUDPanel>
        </div>
      </main>

      {/* Bottom Input Bar */}
      <footer className="relative z-10 shrink-0 px-4 pb-4 pt-2 sm:px-6">
        <div className="max-w-3xl mx-auto">
          <JARVISInputBar
            onSend={handleSendMessage}
            onStop={handleStop}
            streaming={chatStreaming}
            placeholder={chatStreaming ? 'Processando…' : isListening ? 'Escutando…' : `Comando de voz ou texto, ${hud.userName}…`}
          />
        </div>
      </footer>

      {settingsOpen && <HUDSettingsDrawer onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}

// ─── Settings Drawer ───

function Toggle({ label, hint, checked, onChange, disabled = false }: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-disabled={disabled}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="jarvis-toggle w-full"
    >
      <span className="text-left">
        <span className="block">{label}</span>
        {hint && <span className="jarvis-field-hint">{hint}</span>}
      </span>
      <span className={`jarvis-switch ${checked ? 'is-on' : ''}`} aria-hidden="true" />
    </button>
  );
}

function HUDSettingsDrawer({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const { hud, updateHud, resetHud } = useHudSettings();
  const settings = useAppStore((s) => s.settings);
  const updateSettings = useAppStore((s) => s.updateSettings);
  const models = useAppStore((s) => s.models);
  const modelsLoading = useAppStore((s) => s.modelsLoading);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const setSelectedModel = useAppStore((s) => s.setSelectedModel);
  const isStreaming = useAppStore((s) => s.streamState.isStreaming);
  const [name, setName] = useState(hud.userName);

  const commitName = () => {
    const trimmed = name.trim();
    updateHud({ userName: trimmed || 'Sir' });
    if (!trimmed) setName('Sir');
  };

  return (
    <>
      <div className="jarvis-drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="jarvis-drawer" role="dialog" aria-modal="true" aria-label="Configurações do HUD">
        <header className="jarvis-hud-panel-head">
          <div className="flex items-center gap-2">
            <SlidersHorizontal size={14} className="text-cyan-400" />
            <h3>Configurações</h3>
          </div>
          <button onClick={onClose} className="jarvis-icon-btn" aria-label="Fechar configurações" title="Fechar (Esc)">
            <X size={14} />
          </button>
        </header>

        <div className="jarvis-drawer-body">
          <section className="jarvis-drawer-section">
            <h4>Identidade</h4>
            <label className="jarvis-field">
              Como o JARVIS deve te chamar
              <input
                className="jarvis-field-input"
                value={name}
                maxLength={40}
                onChange={(e) => setName(e.target.value)}
                onBlur={commitName}
                onKeyDown={(e) => e.key === 'Enter' && commitName()}
                placeholder="Sir"
              />
            </label>
          </section>

          <section className="jarvis-drawer-section">
            <h4>Modelo</h4>
            <label className="jarvis-field">
              Modelo de linguagem
              <select
                className="jarvis-field-input"
                value={selectedModel}
                disabled={isStreaming || modelsLoading || models.length === 0}
                onChange={(e) => {
                  setSelectedModel(e.target.value);
                  updateSettings({ defaultModel: e.target.value });
                }}
              >
                {!selectedModel && <option value="">— selecione —</option>}
                {models.map((m) => (
                  <option key={m.id} value={m.id}>{m.id}</option>
                ))}
              </select>
              <span className="jarvis-field-hint">
                {modelsLoading
                  ? 'Carregando modelos…'
                  : models.length === 0
                    ? 'Nenhum modelo disponível — verifique o servidor/engine.'
                    : 'Fica salvo como padrão.'}
              </span>
            </label>
            <label className="jarvis-field">
              Criatividade (temperatura): {settings.temperature.toFixed(1)}
              <input
                type="range"
                min={0}
                max={2}
                step={0.1}
                value={settings.temperature}
                onChange={(e) => updateSettings({ temperature: Number(e.target.value) })}
                className="accent-cyan-400"
              />
            </label>
            <label className="jarvis-field">
              Tamanho máximo da resposta (tokens)
              <input
                type="number"
                min={64}
                max={131072}
                step={64}
                className="jarvis-field-input"
                value={settings.maxTokens}
                onChange={(e) => {
                  const v = Math.round(Number(e.target.value));
                  if (Number.isFinite(v) && v >= 64) updateSettings({ maxTokens: v });
                }}
              />
            </label>
          </section>

          <section className="jarvis-drawer-section">
            <h4>Voz</h4>
            <Toggle
              label="Entrada por voz (microfone do navegador)"
              checked={settings.speechEnabled}
              onChange={(v) => updateSettings({ speechEnabled: v })}
            />
            <Toggle
              label="Saída de voz (TTS)"
              checked={settings.voiceOutputEnabled}
              onChange={(v) => updateSettings({ voiceOutputEnabled: v })}
            />
            <Toggle
              label="Ler respostas em voz alta automaticamente"
              hint="Respostas a comandos digitados ou falados no HUD"
              checked={settings.voiceOutputEnabled && settings.voiceAutoplay}
              disabled={!settings.voiceOutputEnabled}
              onChange={(v) => updateSettings({ voiceAutoplay: v })}
            />
            <p className="jarvis-field-hint mt-2">
              Ativação por palmas e sessão mãos-livres: rode <code className="text-cyan-300">jarvis show</code> no terminal.
            </p>
          </section>

          <section className="jarvis-drawer-section">
            <h4>Visual</h4>
            <Toggle label="Painel de telemetria" checked={hud.showTelemetry} onChange={(v) => updateHud({ showTelemetry: v })} />
            <Toggle label="Partículas de fundo" checked={hud.particles} disabled={hud.reducedMotion} onChange={(v) => updateHud({ particles: v })} />
            <Toggle label="Scanlines" checked={hud.scanlines} onChange={(v) => updateHud({ scanlines: v })} />
            <Toggle
              label="Reduzir animações"
              hint="Mais leve em máquinas modestas"
              checked={hud.reducedMotion}
              onChange={(v) => updateHud({ reducedMotion: v })}
            />
          </section>

          <section className="jarvis-drawer-section">
            <h4>Mais</h4>
            <button className="jarvis-link-btn" onClick={() => navigate('/chat')}>
              <MessageSquare size={13} /> Interface clássica (chat)
            </button>
            <button className="jarvis-link-btn" onClick={() => navigate('/settings')}>
              <Settings size={13} /> Configurações avançadas (servidor, API key, tema)
            </button>
            <button
              className="jarvis-link-btn"
              onClick={() => {
                resetHud();
                setName('Sir');
              }}
            >
              <RotateCcw size={13} /> Restaurar padrões do HUD
            </button>
          </section>
        </div>
      </aside>
    </>
  );
}

// ─── Helper Components ───

function SystemControlRow({ label, value, icon: Icon, status }: {
  label: string;
  value: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  status?: 'online' | 'offline' | 'warning';
}) {
  const statusColors = {
    online: 'bg-emerald-400',
    offline: 'bg-rose-400',
    warning: 'bg-amber-400',
  };
  return (
    <div className="jarvis-row">
      <div className="flex items-center gap-2 text-zinc-400 tracking-wider">
        <Icon size={12} className="text-cyan-400/70" />
        {label}
      </div>
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-cyan-200 tabular-nums truncate">{value}</span>
        {status && <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusColors[status]}`} />}
      </div>
    </div>
  );
}

function QuickActions({ onAction, disabled }: { onAction: (text: string) => void; disabled: boolean }) {
  const actions = [
    { label: 'Volume 80%', cmd: 'Aumente o volume para 80%', icon: Volume2 },
    { label: 'Fechar Chrome', cmd: 'Feche o Google Chrome', icon: X },
    { label: 'Print Screen', cmd: 'Tire um print da tela e leia o texto', icon: Camera },
    { label: 'Processos CPU', cmd: 'Liste processos com alto uso de CPU', icon: Cpu },
    { label: 'Mutar Mic', cmd: 'Mute o microfone', icon: MicOff },
    { label: 'Headset', cmd: 'Mude o áudio para o headset', icon: Headphones },
  ];

  return (
    <div className="grid grid-cols-2 gap-2">
      {actions.map((a) => (
        <button
          key={a.label}
          onClick={() => onAction(a.cmd)}
          disabled={disabled}
          className="jarvis-quick-btn group disabled:opacity-40 disabled:cursor-not-allowed"
          title={a.cmd}
        >
          <a.icon size={13} className="shrink-0 text-cyan-400/80 group-hover:text-cyan-300 transition-colors" />
          <span className="truncate">{a.label}</span>
        </button>
      ))}
    </div>
  );
}

function JARVISInputBar({ onSend, onStop, streaming, placeholder }: {
  onSend: (text: string) => void;
  onStop: () => void;
  streaming: boolean;
  placeholder: string;
}) {
  const [text, setText] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const canSend = !!text.trim() && !streaming;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (canSend) {
      onSend(text);
      setText('');
      inputRef.current?.focus();
    }
  };

  return (
    <form onSubmit={handleSubmit} className="relative">
      <span className="absolute left-5 top-1/2 -translate-y-1/2 text-cyan-400/60 jarvis-font-hud text-xs pointer-events-none">▸</span>
      <input
        ref={inputRef}
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
        className="jarvis-input"
        aria-label="Comando para o JARVIS"
        autoFocus
      />
      {streaming ? (
        <button type="button" onClick={onStop} className="jarvis-send-btn" aria-label="Interromper resposta" title="Interromper">
          <Square size={13} />
        </button>
      ) : (
        <button type="submit" disabled={!canSend} className="jarvis-send-btn" aria-label="Enviar comando">
          <Send size={14} />
        </button>
      )}
    </form>
  );
}

// ─── Particle Field Background ───
function ParticleField({ count = 30 }: { count?: number }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const sizeRef = useCanvasSize(canvasRef);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;

    const particles = Array.from({ length: count }, () => ({
      x: Math.random() * window.innerWidth,
      y: Math.random() * window.innerHeight,
      vx: (Math.random() - 0.5) * 0.3,
      vy: (Math.random() - 0.5) * 0.3,
      size: 0.5 + Math.random() * 1.5,
      opacity: 0.1 + Math.random() * 0.3,
      hue: 180 + Math.random() * 60,
    }));
    let raf = 0;
    let last = 0;

    const draw = (timestamp: number) => {
      const dt = last ? (timestamp - last) / 1000 : 0;
      last = timestamp;
      const { w, h } = sizeRef.current;
      ctx.clearRect(0, 0, w, h);

      for (const p of particles) {
        p.x += p.vx * dt * 60;
        p.y += p.vy * dt * 60;
        // Wrap around
        if (p.x < 0) p.x = w;
        if (p.x > w) p.x = 0;
        if (p.y < 0) p.y = h;
        if (p.y > h) p.y = 0;

        const pulse = 0.5 + Math.sin(timestamp / 1000 + p.x * 0.01) * 0.3;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = `hsla(${p.hue}, 100%, 60%, ${p.opacity * pulse})`;
        ctx.fill();
      }

      // Draw connections
      ctx.lineWidth = 0.5;
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x;
          const dy = particles[i].y - particles[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 120) {
            ctx.beginPath();
            ctx.moveTo(particles[i].x, particles[i].y);
            ctx.lineTo(particles[j].x, particles[j].y);
            ctx.strokeStyle = `rgba(34, 211, 238, ${(1 - dist / 120) * 0.15})`;
            ctx.stroke();
          }
        }
      }

      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [count, sizeRef]);

  return <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none opacity-60" aria-hidden="true" />;
}

export default JARVISMode;
