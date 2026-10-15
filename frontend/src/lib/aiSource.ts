import { isEmbedOnlyModel } from './model-capabilities';

/** Claude Code, conversation mode: light, no tools (plan login only). */
export const CLAUDE_CODE_MODEL = 'claude-code';
/** Claude Code, agent mode: full Claude Code with its tools (heavier). */
export const CLAUDE_CODE_AGENT_MODEL = 'claude-code-agent';

export type ClaudeMode = 'chat' | 'agent';

export function isClaudeCode(model: string): boolean {
  return model === CLAUDE_CODE_MODEL || model === CLAUDE_CODE_AGENT_MODEL;
}

export function claudeModelFor(mode: ClaudeMode): string {
  return mode === 'agent' ? CLAUDE_CODE_AGENT_MODEL : CLAUDE_CODE_MODEL;
}

export function claudeModeOf(model: string): ClaudeMode {
  return model === CLAUDE_CODE_AGENT_MODEL ? 'agent' : 'chat';
}

const LOCAL_MODEL_KEY = 'openjarvis-hud-local-model';

export type AiSource = 'ollama' | 'claude-code';

export function sourceOf(model: string): AiSource {
  return isClaudeCode(model) ? 'claude-code' : 'ollama';
}

/** Chat models served by the local engine (everything except Claude Code). */
export function localModels(models: { id: string }[]): { id: string }[] {
  return models.filter((m) => !isClaudeCode(m.id) && !isEmbedOnlyModel(m.id));
}

export function rememberLocalModel(model: string): void {
  try {
    if (model && !isClaudeCode(model)) localStorage.setItem(LOCAL_MODEL_KEY, model);
  } catch {
    // storage may be unavailable (private mode); the switch still works
  }
}

/** Local model to go back to: the remembered one if still installed, else the first. */
export function pickLocalModel(models: { id: string }[]): string {
  const local = localModels(models);
  let remembered = '';
  try {
    remembered = localStorage.getItem(LOCAL_MODEL_KEY) ?? '';
  } catch {
    remembered = '';
  }
  return local.find((m) => m.id === remembered)?.id ?? local[0]?.id ?? '';
}
