import type { ThemeMode } from './store';

const THEME_CLASSES = ['dark', 'light', 'jarvis'] as const;

/** Classes on <html> for a theme. JARVIS builds on dark (Tailwind `dark:`, shadcn). */
export function themeClasses(theme: ThemeMode | undefined): string[] {
  switch (theme) {
    case 'dark':
      return ['dark'];
    case 'light':
      return ['light'];
    case 'jarvis':
      return ['dark', 'jarvis'];
    default:
      return []; // system: follow prefers-color-scheme
  }
}

export function applyTheme(theme: ThemeMode | undefined, root: HTMLElement = document.documentElement): void {
  root.classList.remove(...THEME_CLASSES);
  root.classList.add(...themeClasses(theme));
}
