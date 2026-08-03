import { create } from 'zustand';
import type { ChatMessage } from '@/types/api';
import { useSessionStore } from './useSessionStore';

interface ChatState {
  messages: ChatMessage[];
  addMessage: (msg: ChatMessage) => void;
  updateMessage: (id: string, updates: Partial<ChatMessage>) => void;
  appendStreamToken: (id: string, contentDelta: string, thinkingDelta: string) => void;
  prependMessages: (msgs: ChatMessage[]) => void;
  clearMessages: () => void;
  flushSyncNow: () => void;
}

interface TokenBuffer {
  id: string;
  contentDelta: string;
  thinkingDelta: string;
}

let tokenBuffer: TokenBuffer | null = null;
let flushRafId: number | null = null;
let syncDebounceTimer: ReturnType<typeof setTimeout> | null = null;
const SYNC_DEBOUNCE_MS = 500;

const safeRAF: (cb: () => void) => number =
  typeof requestAnimationFrame !== 'undefined'
    ? (cb) => requestAnimationFrame(cb)
    : (cb) => setTimeout(cb, 16) as unknown as number;

const safeCancelRAF = (id: number): void => {
  if (typeof cancelAnimationFrame !== 'undefined') {
    cancelAnimationFrame(id);
  } else {
    clearTimeout(id as unknown as NodeJS.Timeout);
  }
};

let _isSyncingFromChatStore = false;

function debouncedSyncActive(messages: ChatMessage[]) {
  if (syncDebounceTimer) clearTimeout(syncDebounceTimer);
  syncDebounceTimer = setTimeout(() => {
    _isSyncingFromChatStore = true;
    useSessionStore.getState().syncActive({ messages });
    _isSyncingFromChatStore = false;
    syncDebounceTimer = null;
  }, SYNC_DEBOUNCE_MS);
}

function flushSyncNowInternal(messages?: ChatMessage[]) {
  if (syncDebounceTimer) {
    clearTimeout(syncDebounceTimer);
    syncDebounceTimer = null;
  }
  if (messages) {
    _isSyncingFromChatStore = true;
    useSessionStore.getState().syncActive({ messages });
    _isSyncingFromChatStore = false;
  }
}

function flushTokenBuffer() {
  if (!tokenBuffer) return;
  const { id, contentDelta, thinkingDelta } = tokenBuffer;
  tokenBuffer = null;
  flushRafId = null;

  const messages = useChatStore.getState().messages.map((m: ChatMessage) => {
    if (m.id !== id) return m;
    return {
      ...m,
      ...(contentDelta ? { content: m.content + contentDelta } : {}),
      ...(thinkingDelta ? { thinkingContent: (m.thinkingContent || '') + thinkingDelta } : {}),
    };
  });
  useChatStore.setState({ messages });
  debouncedSyncActive(messages);
}

function filterHeartbeats(msgs: ChatMessage[]): ChatMessage[] {
  const hasHeartbeat = msgs.some((m: any) => m.role === 'agent' && (m.agent?.action === 'heartbeat' || m.action === 'heartbeat'));
  if (!hasHeartbeat) return msgs;
  return msgs.filter((m: any) => !(m.role === 'agent' && (m.agent?.action === 'heartbeat' || m.action === 'heartbeat')));
}

let _sessionSubUnsub: (() => void) | null = null;
let _prevActiveId: string | null | undefined = undefined;
let _prevSessionMessagesRef: ChatMessage[] | undefined = undefined;

export const useChatStore = create<ChatState>()((set, get) => {
  if (!_sessionSubUnsub) {
    _sessionSubUnsub = useSessionStore.subscribe((state) => {
      if (_prevActiveId === undefined) {
        _prevActiveId = state.activeId;
      }

      const active = state.activeId ? state.sessions[state.activeId] : undefined;
      const raw = active?.messages || [];

      if (state.activeId !== _prevActiveId) {
        _prevActiveId = state.activeId;
        _prevSessionMessagesRef = raw;
        set({ messages: filterHeartbeats(raw) });
        return;
      }

      if (!_isSyncingFromChatStore && raw !== _prevSessionMessagesRef) {
        _prevSessionMessagesRef = raw;
        set({ messages: filterHeartbeats(raw) });
      } else {
        _prevSessionMessagesRef = raw;
      }
    });
  }

  return {
    messages: [],

    addMessage: (msg) => {
      const current = get().messages;
      const isDuplicate = current.some(m =>
        m.role === msg.role
        && m.content === msg.content
        && m.timestamp === msg.timestamp
      );
      if (isDuplicate) return;
      const messages = [...current, msg];
      set({ messages });
      flushSyncNowInternal(messages);
    },

    updateMessage: (id, updates) => {
      if (tokenBuffer) flushTokenBuffer();
      const messages = get().messages.map(m => {
        if (m.id !== id) return m;
        const merged = updates.metadata && m.metadata
          ? { ...m, ...updates, metadata: { ...m.metadata, ...updates.metadata } }
          : { ...m, ...updates };
        return merged;
      });
      set({ messages });
      flushSyncNowInternal(messages);
    },

    appendStreamToken: (id, contentDelta, thinkingDelta) => {
      if (tokenBuffer && tokenBuffer.id === id) {
        tokenBuffer.contentDelta += contentDelta || '';
        tokenBuffer.thinkingDelta += thinkingDelta || '';
      } else {
        if (tokenBuffer) flushTokenBuffer();
        tokenBuffer = { id, contentDelta: contentDelta || '', thinkingDelta: thinkingDelta || '' };
      }
      if (!flushRafId) {
        flushRafId = safeRAF(() => flushTokenBuffer());
      }
    },

    prependMessages: (msgs) => {
      if (tokenBuffer) flushTokenBuffer();
      const messages = [...msgs, ...get().messages];
      const seen = new Set<string>();
      const deduped = messages.filter(m => {
        if (seen.has(m.id)) return false;
        seen.add(m.id);
        return true;
      });
      set({ messages: deduped });
      flushSyncNowInternal(deduped);
    },

    clearMessages: () => {
      if (tokenBuffer) { tokenBuffer = null; }
      if (flushRafId) { safeCancelRAF(flushRafId); flushRafId = null; }
      set({ messages: [] });
      flushSyncNowInternal([]);
    },

    flushSyncNow: () => {
      if (tokenBuffer) flushTokenBuffer();
      flushSyncNowInternal(get().messages);
    },
  };
});
