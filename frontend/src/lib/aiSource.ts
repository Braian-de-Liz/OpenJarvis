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

/** Claude models offered in the HUD ("" keeps the Claude Code plan default). */
export const CLAUDE_MODEL_OPTIONS: { value: string; label: string; hint: string }[] = [
  { value: '', label: 'Padrão do plano', hint: 'o que o seu Claude Code usa por padrão' },
  { value: 'sonnet', label: 'Sonnet', hint: 'equilibrado' },
  { value: 'opus', label: 'Opus', hint: 'mais capaz, gasta mais do limite' },
  { value: 'haiku', label: 'Haiku', hint: 'mais rápido e econômico' },
];

/** Model id sent to the server: "claude-code:opus" when a Claude model is chosen. */
export function requestModel(
  model: string,
  claudeModel: string,
  agentMode: AgentPermission = 'ask',
): string {
  if (!isClaudeCode(model)) return model;
  const withModel = claudeModel ? `${model}:${claudeModel}` : model;
  // The permission mode only applies to the agent ("claude-code-agent@ask").
  return model === CLAUDE_CODE_AGENT_MODEL ? `${withModel}@${agentMode}` : withModel;
}

/** What the Claude agent may do. read: only look; ask: every edit/command needs
 * your approval in the HUD; free: edits and commands inside the project run
 * without asking (risky or outside-the-project ones still ask). */
export type AgentPermission = 'read' | 'ask' | 'free';

export const AGENT_PERMISSION_OPTIONS: { value: AgentPermission; label: string; hint: string }[] = [
  {
    value: 'read',
    label: 'LEITURA',
    hint: 'Só lê arquivos, busca no projeto e na web. Não edita nem roda comandos.',
  },
  {
    value: 'ask',
    label: 'PERGUNTAR',
    hint: 'Lê livremente; toda edição de arquivo ou comando pede a sua aprovação aqui no HUD.',
  },
  {
    value: 'free',
    label: 'LIVRE',
    hint:
      'Edita arquivos e roda comandos comuns dentro da pasta do projeto sem perguntar. '
      + 'Fora da pasta, ou comandos arriscados (apagar, instalar, git push, internet, shell inline), ainda pedem aprovação. '
      + 'Não é uma sandbox: confira o que aprova.',
  },
];

export function agentPermissionLabel(permission: AgentPermission): string {
  return AGENT_PERMISSION_OPTIONS.find((o) => o.value === permission)?.label ?? permission.toUpperCase();
}

/** Short label for the Claude model in use, e.g. "claude-opus-4-1" or "Opus". */
export function claudeModelLabel(inUse: string, chosen: string): string {
  if (inUse) return inUse;
  return CLAUDE_MODEL_OPTIONS.find((o) => o.value === chosen)?.label ?? chosen;
}

/** Claude Code "conversa" normally uses ~400 input tokens; far more is a red flag. */
export const CLAUDE_CHAT_USAGE_WARN = 5000;

/**
 * Message to show when a Claude Code conversation-mode reply cost far more
 * than that mode should (the plan limit is what pays for it), else null.
 */
export function unusualClaudeUsage(
  model: string,
  usage: { prompt_tokens: number } | undefined,
): string | null {
  if (!usage || !isClaudeCode(model) || claudeModeOf(model) !== 'chat') return null;
  if (usage.prompt_tokens <= CLAUDE_CHAT_USAGE_WARN) return null;
  const n = usage.prompt_tokens.toLocaleString('pt-BR');
  return `Esta resposta do Claude (modo Conversa) gastou ${n} tokens de entrada — o normal é ~400. Confira o consumo do seu plano.`;
}
