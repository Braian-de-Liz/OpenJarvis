import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';

const api = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock('./api', () => api);

import { DEFAULT_SCREEN_QUESTION, buildScreenPrompt, readScreen } from './screenRead';
import type { ScreenText } from './screenRead';
import { USER_TEXT_FOLD, UserText } from '../components/Jarvis/HudLog';

const screen = (over: Partial<ScreenText> = {}): ScreenText => ({
  text: 'Fatura vence 20/10\nTotal R$ 120,00',
  truncated: false,
  chars: 33,
  language: 'pt-BR',
  width: 1600,
  height: 900,
  engine: 'windows-ocr',
  ...over,
});

beforeEach(() => vi.clearAllMocks());

describe('readScreen', () => {
  it('posts to the vision endpoint and returns the OCR result', async () => {
    api.apiFetch.mockResolvedValue(new Response(JSON.stringify(screen())));
    expect((await readScreen()).language).toBe('pt-BR');
    expect(api.apiFetch).toHaveBeenCalledWith('/api/vision/screen', { method: 'POST' });
  });

  it('surfaces the server detail on errors', async () => {
    api.apiFetch.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Instale com: uv sync --extra screen' }), { status: 501 }),
    );
    await expect(readScreen()).rejects.toThrow('uv sync --extra screen');
  });
});

describe('buildScreenPrompt', () => {
  it('puts the question first and quotes the screen text', () => {
    const prompt = buildScreenPrompt(screen(), 'quando vence?');
    expect(prompt.split('\n')[0]).toBe('Analise minha tela: quando vence?');
    expect(prompt).toContain('"""\nFatura vence 20/10\nTotal R$ 120,00\n"""');
    expect(prompt).toContain('1600×900');
  });

  it('uses a default question and flags truncation', () => {
    const prompt = buildScreenPrompt(screen({ truncated: true, chars: 20000 }));
    expect(prompt).toContain(DEFAULT_SCREEN_QUESTION);
    expect(prompt).toContain('de 20000');
  });
});

describe('UserText', () => {
  it('keeps short messages as-is', () => {
    expect(renderToStaticMarkup(createElement(UserText, { text: 'oi' }))).not.toContain('<details');
  });

  it('folds long messages behind their first line', () => {
    const long = `Analise minha tela: resumo\n${'x'.repeat(USER_TEXT_FOLD + 10)}`;
    const html = renderToStaticMarkup(createElement(UserText, { text: long }));
    expect(html).toContain('<details');
    expect(html).toContain('Analise minha tela: resumo');
    expect(html).toContain('ver texto completo');
  });
});
