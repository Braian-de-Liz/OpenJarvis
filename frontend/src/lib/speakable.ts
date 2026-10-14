import { stripThinkTags } from './message-text';

/**
 * Turn a Markdown reply into text worth reading aloud: drop code blocks, URLs
 * and formatting symbols so TTS doesn't say "asterisco". Mirrors
 * `openjarvis.cli._hands_free._speakable` used by the CLI voice loop.
 */
export function toSpeakable(markdown: string): string {
  let text = stripThinkTags(markdown);
  text = text.replace(/```[\s\S]*?```/g, ' ');
  text = text.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1'); // [label](url) -> label
  text = text.replace(/https?:\/\/\S+/g, '');
  text = text.replace(/^\s*(?:[-+*]|\d+[.)])\s+/gm, ''); // list markers
  text = text.replace(/[*_`#>|~]+/g, '');
  return text.replace(/\s+/g, ' ').trim();
}
