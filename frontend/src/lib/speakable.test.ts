import { describe, expect, it } from 'vitest';
import { toSpeakable } from './speakable';

describe('toSpeakable', () => {
  it('drops Markdown symbols, code, links and think tags', () => {
    const md = [
      '<think>planejando</think># Resultado',
      '',
      'O volume está em **80%**. Veja [o guia](https://example.com).',
      '',
      '- item um',
      '1. item dois',
      '',
      '```bash',
      'amixer set Master 80%',
      '```',
      'Fonte: https://example.com/x',
    ].join('\n');
    expect(toSpeakable(md)).toBe('Resultado O volume está em 80%. Veja o guia. item um item dois Fonte:');
  });

  it('returns an empty string for code-only replies', () => {
    expect(toSpeakable('```\nls -la\n```')).toBe('');
  });
});
