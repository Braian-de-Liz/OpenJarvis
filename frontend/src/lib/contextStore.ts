import { create } from 'zustand';
import { computeContext, fetchContextWindow } from './contextWindow';
import type { ContextSnapshot, ContextWindowInfo } from './contextWindow';
import type { ChatMessage } from '../types';

interface ContextState {
  info: ContextWindowInfo | null;
  messages: ChatMessage[];
  snapshot: ContextSnapshot;
  setMessages: (messages: ChatMessage[]) => void;
  loadWindow: (model: string) => Promise<void>;
}

let loadedModel = '';
let loadToken = 0;

export const useContextStore = create<ContextState>((set, get) => ({
  info: null,
  messages: [],
  snapshot: computeContext([], null),
  setMessages: (messages) => set({ messages, snapshot: computeContext(messages, get().info) }),
  loadWindow: async (model) => {
    if (!model || model === loadedModel) return;
    loadedModel = model;
    const token = ++loadToken;
    try {
      const info = await fetchContextWindow(model);
      if (token !== loadToken) return; // a newer model was selected meanwhile
      set({ info, snapshot: computeContext(get().messages, info) });
    } catch {
      if (token !== loadToken) return;
      loadedModel = ''; // retry on the next call
      set({ info: null, snapshot: computeContext(get().messages, null) });
    }
  },
}));

/** Test helper. */
export function __resetContextForTests(): void {
  loadedModel = '';
  loadToken = 0;
  useContextStore.setState({ info: null, messages: [], snapshot: computeContext([], null) });
}
