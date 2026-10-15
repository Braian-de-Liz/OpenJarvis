import { memo, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { Check, ChevronDown, ChevronUp, Loader2, X } from 'lucide-react';
import { stripThinkTags } from '../../lib/message-text';
import type { ChatMessage, ToolCallInfo } from '../../types';
import type { VoiceLogEntry } from '../../lib/useVoiceEvents';

export interface HudStream {
  isStreaming: boolean;
  conversationId: string | null;
  content: string;
  phase: string;
}

type Entry = {
  id: string;
  role: string;
  text: string;
  timestamp: number;
  message?: ChatMessage;
  live?: boolean;
};

const REHYPE = [[rehypeHighlight, { detect: true, ignoreMissing: true }]] as never[];
const REMARK = [remarkGfm];

/** Assistant text with Markdown (lists, code, tables), safe for streaming partials. */
export const HudMarkdown = memo(function HudMarkdown({ text }: { text: string }) {
  return (
    <div className="jarvis-md">
      <ReactMarkdown
        remarkPlugins={REMARK}
        rehypePlugins={REHYPE}
        components={{
          a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer noopener" />,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
});

function truncate(text: string | undefined, max = 600): string {
  if (!text) return '';
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export function ToolChip({ call }: { call: ToolCallInfo }) {
  const [open, setOpen] = useState(false);
  const icon =
    call.status === 'running' ? <Loader2 size={10} className="animate-spin" />
    : call.status === 'success' ? <Check size={10} />
    : <X size={10} />;
  return (
    <div className={`jarvis-tool-chip is-${call.status}`}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex items-center gap-1.5 w-full">
        {icon}
        <span className="truncate">{call.tool}</span>
        {typeof call.latency === 'number' && (
          // latency is in milliseconds (same as ToolCallCard)
          <span className="text-zinc-500 tabular-nums">{call.latency < 1000 ? `${Math.round(call.latency)}ms` : `${(call.latency / 1000).toFixed(1)}s`}</span>
        )}
        {open ? <ChevronUp size={10} className="ml-auto" /> : <ChevronDown size={10} className="ml-auto" />}
      </button>
      {open && (
        <div className="jarvis-tool-detail">
          {call.arguments && <pre><span className="text-zinc-500">args </span>{truncate(call.arguments)}</pre>}
          {call.result && <pre><span className="text-zinc-500">result </span>{truncate(call.result)}</pre>}
        </div>
      )}
    </div>
  );
}

export function TelemetryLine({ message }: { message: ChatMessage }) {
  const t = message.telemetry;
  if (!t) return null;
  const parts: string[] = [];
  if (typeof t.total_ms === 'number') parts.push(t.total_ms >= 1000 ? `${(t.total_ms / 1000).toFixed(1)}s` : `${Math.round(t.total_ms)}ms`);
  if (typeof t.tokens_per_sec === 'number' && t.tokens_per_sec > 0) parts.push(`${t.tokens_per_sec.toFixed(1)} tok/s`);
  if (t.model_id) parts.push(t.model_id);
  if (parts.length === 0) return null;
  return <div className="text-[9px] tracking-wider text-zinc-600 mt-1">{parts.join(' · ')}</div>;
}

export const USER_TEXT_FOLD = 400;

/** User text; long messages (e.g. a screen reading) fold after the first line. */
export function UserText({ text }: { text: string }) {
  const cls = 'whitespace-pre-wrap break-words text-amber-100/90';
  if (text.length <= USER_TEXT_FOLD) return <p className={cls}>{text}</p>;
  const firstLine = text.split('\n', 1)[0].slice(0, USER_TEXT_FOLD);
  return (
    <div>
      <p className={cls}>{firstLine}</p>
      <details className="mt-1">
        <summary className="cursor-pointer text-[10px] text-zinc-500 hover:text-zinc-300">
          ver texto completo ({text.length.toLocaleString('pt-BR')} caracteres)
        </summary>
        <p className={`${cls} mt-1 max-h-48 overflow-y-auto text-[11px] text-amber-100/70`}>{text}</p>
      </details>
    </div>
  );
}

/** Merge typed chat (store) and hands-free voice turns in time order. */
export function buildEntries(
  messages: ChatMessage[],
  voiceLog: VoiceLogEntry[],
  stream: HudStream,
  activeId: string | null,
): Entry[] {
  const streamingHere = stream.isStreaming && stream.conversationId === activeId;
  const lastIdx = messages.length - 1;
  const entries: Entry[] = messages.map((m, i) => {
    const live = streamingHere && i === lastIdx && m.role === 'assistant';
    const text = live && stream.content.length > m.content.length ? stream.content : m.content;
    return {
      id: m.id,
      role: m.role,
      text: m.role === 'assistant' ? stripThinkTags(text) : text,
      timestamp: m.timestamp || 0,
      message: m,
      live,
    };
  });
  for (const v of voiceLog) {
    entries.push({ id: v.id, role: v.role, text: v.text, timestamp: v.timestamp });
  }
  return entries.sort((a, b) => a.timestamp - b.timestamp);
}

export function HudLog({ messages, voiceLog, stream, activeId, userName, emptyHints }: {
  messages: ChatMessage[];
  voiceLog: VoiceLogEntry[];
  stream: HudStream;
  activeId: string | null;
  userName: string;
  emptyHints?: string[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const entries = buildEntries(messages, voiceLog, stream, activeId);

  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [entries.length, stream.content, autoScroll]);

  const formatTime = (ts: number) => new Date(ts).toLocaleTimeString('pt-BR', { hour12: false });

  return (
    <div
      ref={containerRef}
      onScroll={(e) => {
        const { scrollTop, scrollHeight, clientHeight } = e.currentTarget;
        setAutoScroll(scrollHeight - scrollTop - clientHeight < 50);
      }}
      className="jarvis-terminal jarvis-font-hud"
      aria-live="polite"
      aria-relevant="additions"
    >
      {entries.length === 0 ? (
        <div className="h-full flex flex-col items-center justify-center text-center gap-2 py-6">
          <p className="jarvis-font-display text-cyan-400/70 text-sm tracking-[0.3em]">JARVIS ONLINE</p>
          <p className="text-[11px] text-zinc-500">Aguardando comando, {userName}.</p>
          {emptyHints && emptyHints.length > 0 && (
            <div className="mt-2 flex flex-wrap justify-center gap-1.5">
              {emptyHints.map((s) => <kbd key={s} className="jarvis-chip">{s}</kbd>)}
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-2.5">
          {entries.map((e) => e.role === 'system' ? (
            <div key={e.id} className="terminal-message text-zinc-500 italic">
              <span className="text-zinc-600">{formatTime(e.timestamp)}</span>
              <span className="mx-1.5 text-cyan-500/40">◆</span>
              {e.text}
            </div>
          ) : (
            <div key={e.id} className={`terminal-message ${e.role === 'user' ? 'is-user' : 'is-jarvis'}`}>
              <div className="flex items-baseline gap-2 text-[10px] tracking-wider">
                <span className={e.role === 'user' ? 'text-amber-400' : 'text-cyan-400'}>
                  {e.role === 'user' ? userName.toUpperCase() : 'JARVIS'}
                </span>
                <span className="text-zinc-600">{formatTime(e.timestamp)}</span>
                {e.live && stream.phase && <span className="text-purple-300/80 truncate">{stream.phase}</span>}
              </div>
              {e.message?.toolCalls && e.message.toolCalls.length > 0 && (
                <div className="flex flex-col gap-1 my-1">
                  {e.message.toolCalls.map((tc) => <ToolChip key={tc.id} call={tc} />)}
                </div>
              )}
              {e.role === 'user' ? (
                <UserText text={e.text} />
              ) : e.text ? (
                <div className="text-cyan-100/90">
                  <HudMarkdown text={e.text} />
                  {e.live && <span className="text-cyan-400 animate-blink">█</span>}
                </div>
              ) : e.live ? (
                <span className="text-cyan-400 animate-blink">█</span>
              ) : null}
              {!e.live && e.message && <TelemetryLine message={e.message} />}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
