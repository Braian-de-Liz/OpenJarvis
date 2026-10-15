import { apiFetch } from './api';
import type { ChatMessage } from '../types';

export interface ContextWindowInfo {
  model: string;
  /** Effective window in tokens, or null when unknown. */
  window: number | null;
  model_max: number | null;
  source: string;
  /** Claude Code "conversa" only sends the last N messages / chars. */
  history_limit: { messages: number; chars: number } | null;
}

export async function fetchContextWindow(model: string): Promise<ContextWindowInfo> {
  const res = await apiFetch(`/api/context-window?model=${encodeURIComponent(model)}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** ~4 characters per token plus a little per-message overhead (like the server). */
export function estimateTokens(text: string): number {
  return Math.max(1, Math.ceil(text.length / 4)) + 4;
}

export interface ContextItem {
  id: string;
  role: 'user' | 'assistant';
  preview: string;
  tokens: number;
  /** True when this message is no longer sent to the model. */
  outside: boolean;
}

export interface ContextSnapshot {
  /** Tokens the next request will carry (last reply's prompt + completion). */
  used: number;
  /** True when `used` is an estimate (no server-reported usage yet). */
  estimated: boolean;
  window: number | null;
  /** 0..1, or null without a known window. */
  fraction: number | null;
  promptTotal: number;
  completionTotal: number;
  replies: number;
  items: ContextItem[];
  outsideCount: number;
}

function preview(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length > 90 ? `${flat.slice(0, 90)}…` : flat;
}

/**
 * Which messages are out of the model's reach.
 * - Claude Code "conversa": only the last `messages` messages and `chars`
 *   characters of "who: text" lines are sent (mirrors `_with_history`).
 * - Otherwise: newest-first until the estimated tokens exceed the window.
 */
export function markOutside(
  messages: ChatMessage[],
  tokens: number[],
  info: ContextWindowInfo | null,
): boolean[] {
  const outside = messages.map(() => false);
  if (!info) return outside;
  if (info.history_limit) {
    const { messages: maxMessages, chars: maxChars } = info.history_limit;
    // For the *next* request every message so far is history. The server cuts
    // the joined string, so a message straddling the limit is partly kept;
    // count it as inside and mark only those fully cut.
    let kept = 0;
    let charBudget = maxChars;
    for (let i = messages.length - 1; i >= 0; i--) {
      const text = messages[i].content.trim();
      if (!text) continue;
      const cost = text.length + (messages[i].role === 'user' ? 9 : 8) + 1;
      if (kept >= maxMessages || charBudget <= 0) outside[i] = true;
      else {
        kept += 1;
        charBudget -= cost;
      }
    }
    return outside;
  }
  if (info.window) {
    let budget = info.window;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (budget <= 0) outside[i] = true;
      budget -= tokens[i];
    }
  }
  return outside;
}

export function computeContext(
  messages: ChatMessage[],
  info: ContextWindowInfo | null,
): ContextSnapshot {
  const tokens = messages.map((m) => estimateTokens(m.content));
  let promptTotal = 0;
  let completionTotal = 0;
  let replies = 0;
  let lastUsage: ChatMessage['usage'];
  for (const m of messages) {
    if (m.role === 'assistant' && m.usage) {
      promptTotal += m.usage.prompt_tokens || 0;
      completionTotal += m.usage.completion_tokens || 0;
      replies += 1;
      lastUsage = m.usage;
    }
  }
  const reported = lastUsage ? (lastUsage.prompt_tokens || 0) + (lastUsage.completion_tokens || 0) : 0;
  const used = reported > 0 ? reported : tokens.reduce((a, b) => a + b, 0);
  const window = info?.window ?? null;
  const outside = markOutside(messages, tokens, info);
  const items: ContextItem[] = messages
    .map((m, i) => ({
      id: m.id,
      role: m.role,
      preview: preview(m.content) || '(vazio)',
      tokens: tokens[i],
      outside: outside[i],
    }))
    .filter((it) => it.preview !== '(vazio)' || it.role === 'user');
  return {
    used,
    estimated: reported <= 0,
    window,
    fraction: window ? Math.min(1, used / window) : null,
    promptTotal,
    completionTotal,
    replies,
    items,
    outsideCount: items.filter((i) => i.outside).length,
  };
}

/** Compact "3,2k" style count. */
export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace('.', ',')}M`;
  if (n >= 10_000) return `${Math.round(n / 1000)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace('.', ',')}k`;
  return String(n);
}

export type ContextLevel = 'ok' | 'warn' | 'high';
export function contextLevel(fraction: number | null): ContextLevel {
  if (fraction === null) return 'ok';
  return fraction >= 0.9 ? 'high' : fraction >= 0.7 ? 'warn' : 'ok';
}
