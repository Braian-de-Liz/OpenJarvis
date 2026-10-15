import { beforeEach, describe, expect, it } from 'vitest';
import {
  CLAUDE_CODE_AGENT_MODEL,
  CLAUDE_CODE_MODEL,
  claudeModeOf,
  claudeModelFor,
  localModels,
  pickLocalModel,
  rememberLocalModel,
  sourceOf,
} from './aiSource';

class MemoryStorage {
  private store = new Map<string, string>();
  getItem(key: string) {
    return this.store.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.store.set(key, String(value));
  }
}

const models = [
  { id: 'nomic-embed-text' },
  { id: 'llama3' },
  { id: 'qwen3' },
  { id: CLAUDE_CODE_MODEL },
  { id: CLAUDE_CODE_AGENT_MODEL },
];

describe('aiSource', () => {
  beforeEach(() => {
    (globalThis as unknown as { localStorage: MemoryStorage }).localStorage = new MemoryStorage();
  });

  it('classifies the source from the model id', () => {
    expect(sourceOf(CLAUDE_CODE_MODEL)).toBe('claude-code');
    expect(sourceOf(CLAUDE_CODE_AGENT_MODEL)).toBe('claude-code');
    expect(sourceOf('llama3')).toBe('ollama');
  });

  it('local models exclude Claude Code and embedders', () => {
    expect(localModels(models).map((m) => m.id)).toEqual(['llama3', 'qwen3']);
  });

  it('goes back to the remembered local model, else the first', () => {
    expect(pickLocalModel(models)).toBe('llama3');
    rememberLocalModel('qwen3');
    expect(pickLocalModel(models)).toBe('qwen3');
    rememberLocalModel('uninstalled');
    expect(pickLocalModel(models)).toBe('llama3');
  });

  it('never remembers Claude Code as the local model', () => {
    rememberLocalModel(CLAUDE_CODE_MODEL);
    expect(pickLocalModel(models)).toBe('llama3');
  });

  it('returns empty when no local model exists', () => {
    expect(pickLocalModel([{ id: CLAUDE_CODE_MODEL }])).toBe('');
  });

  it('maps between Claude Code modes and model ids', () => {
    expect(claudeModelFor('chat')).toBe(CLAUDE_CODE_MODEL);
    expect(claudeModelFor('agent')).toBe(CLAUDE_CODE_AGENT_MODEL);
    expect(claudeModeOf(CLAUDE_CODE_AGENT_MODEL)).toBe('agent');
    expect(claudeModeOf(CLAUDE_CODE_MODEL)).toBe('chat');
  });

  it('never remembers the agent model as the local model', () => {
    rememberLocalModel(CLAUDE_CODE_AGENT_MODEL);
    expect(pickLocalModel(models)).toBe('llama3');
  });
});
