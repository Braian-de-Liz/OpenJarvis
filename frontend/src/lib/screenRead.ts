import { apiFetch } from './api';

export interface ScreenText {
  text: string;
  truncated: boolean;
  chars: number;
  language: string;
  width: number;
  height: number;
  engine: string;
}

/** OCR of the screen of the machine running `jarvis serve` (Windows). */
export async function readScreen(): Promise<ScreenText> {
  const res = await apiFetch('/api/vision/screen', { method: 'POST' });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      if (typeof data?.detail === 'string') detail = data.detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export const DEFAULT_SCREEN_QUESTION = 'Resuma o que está na minha tela e destaque o que for importante.';

/**
 * Chat prompt for a screen reading. The question comes first so the HUD log
 * (which folds long user messages) shows what was asked; the OCR text follows
 * and stays in the conversation for follow-up questions.
 */
export function buildScreenPrompt(screen: ScreenText, question?: string): string {
  const q = question?.trim() || DEFAULT_SCREEN_QUESTION;
  const note = screen.truncated ? ` (mostrando ${screen.text.length} de ${screen.chars})` : '';
  return [
    `Analise minha tela: ${q}`,
    '',
    `[Texto lido da tela por OCR, ${screen.width}×${screen.height}${note}. Pode haver erros de leitura.]`,
    '"""',
    screen.text,
    '"""',
  ].join('\n');
}
