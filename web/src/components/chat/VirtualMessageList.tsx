'use client';

import React, { useRef, useCallback, useEffect, useMemo, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { ChatMessage } from './ChatMessage';
import type { ChatMessage as ChatMessageType } from '@/types/api';

interface VirtualMessageListProps {
  messages: ChatMessageType[];
  loadOlderMessages?: () => Promise<void>;
  hasMoreMessages?: boolean;
  isLoadingMessages?: boolean;
  onAtBottomChange?: (atBottom: boolean) => void;
  scrollToBottomRef?: React.MutableRefObject<(() => void) | null>;
  stickyHeader?: React.ReactNode;
}

const ESTIMATED_ITEM_SIZE = 120;
const OVERSCAN = 5;
const AT_BOTTOM_THRESHOLD = 60;
const AT_TOP_THRESHOLD = 60;

export function VirtualMessageList({
  messages,
  loadOlderMessages,
  hasMoreMessages = true,
  isLoadingMessages = false,
  onAtBottomChange,
  scrollToBottomRef,
  stickyHeader,
}: VirtualMessageListProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  const stickyHeaderRef = useRef<HTMLDivElement>(null);
  const isUserScrollingRef = useRef(false);
  const prevScrollTopRef = useRef(0);
  const isLoadingOlderRef = useRef(false);
  const lastAtBottomRef = useRef(true);
  const prevMsgCountRef = useRef(0);
  const [stickyHeaderHeight, setStickyHeaderHeight] = useState(0);

  const visibleMessages = useMemo(
    () => messages.filter(m => !(m.role === 'agent' && (m.agent?.action === 'heartbeat' || (m as any).action === 'heartbeat'))),
    [messages]
  );

  const virtualizer = useVirtualizer({
    count: visibleMessages.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => {
      const msg = visibleMessages[index];
      if (!msg) return ESTIMATED_ITEM_SIZE;
      if (msg.role === 'agent') return 48;
      if (msg.content.length > 500) return 200;
      if (msg.content.length > 200) return 150;
      return ESTIMATED_ITEM_SIZE;
    },
    overscan: OVERSCAN,
    measureElement: (el) => el?.getBoundingClientRect().height ?? ESTIMATED_ITEM_SIZE,
  });

  useEffect(() => {
    if (!stickyHeader) {
      setStickyHeaderHeight(0);
      return;
    }
    const el = stickyHeaderRef.current;
    if (!el) return;
    setStickyHeaderHeight(el.getBoundingClientRect().height);
    const ro = new ResizeObserver(([entry]) => {
      setStickyHeaderHeight(entry.contentRect.height);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [stickyHeader]);

  const checkAtBottom = useCallback(() => {
    const el = parentRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < AT_BOTTOM_THRESHOLD;
  }, []);

  const checkAtTop = useCallback(() => {
    const el = parentRef.current;
    if (!el) return false;
    return el.scrollTop < AT_TOP_THRESHOLD;
  }, []);

  const handleScroll = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;

    const atBottom = checkAtBottom();
    const atTop = checkAtTop();
    const { scrollTop } = el;

    if (scrollTop < prevScrollTopRef.current - 5) {
      isUserScrollingRef.current = true;
    }

    if (atBottom) {
      isUserScrollingRef.current = false;
    }

    if (atBottom !== lastAtBottomRef.current) {
      lastAtBottomRef.current = atBottom;
      onAtBottomChange?.(!atBottom);
    }

    if (atTop && loadOlderMessages && hasMoreMessages && !isLoadingOlderRef.current) {
      isLoadingOlderRef.current = true;
      const prevTotalSize = virtualizer.getTotalSize();
      loadOlderMessages().finally(() => {
        requestAnimationFrame(() => {
          const newTotalSize = virtualizer.getTotalSize();
          const diff = newTotalSize - prevTotalSize;
          if (diff > 0 && el) {
            el.scrollTop = el.scrollTop + diff;
          }
          isLoadingOlderRef.current = false;
        });
      });
    }

    prevScrollTopRef.current = scrollTop;
  }, [checkAtBottom, checkAtTop, loadOlderMessages, hasMoreMessages, virtualizer, onAtBottomChange]);

  const scrollToBottom = useCallback(() => {
    const el = parentRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
      isUserScrollingRef.current = false;
    }
  }, []);

  useEffect(() => {
    if (scrollToBottomRef) {
      scrollToBottomRef.current = scrollToBottom;
    }
  }, [scrollToBottom, scrollToBottomRef]);

  useEffect(() => {
    if (isUserScrollingRef.current) return;
    if (visibleMessages.length === 0) return;
    if (visibleMessages.length <= prevMsgCountRef.current) return;

    requestAnimationFrame(() => {
      const el = parentRef.current;
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
    });
  }, [visibleMessages.length]);

  useEffect(() => {
    prevMsgCountRef.current = visibleMessages.length;
  }, [visibleMessages.length]);

  useEffect(() => {
    if (visibleMessages.length === 0) return;
    virtualizer.measure();
  }, [visibleMessages.length, virtualizer]);

  if (visibleMessages.length === 0) {
    return (
      <div className="relative flex-1 min-h-0">
        {stickyHeader && (
          <div ref={stickyHeaderRef} className="absolute top-0 inset-x-0 z-10">{stickyHeader}</div>
        )}
        <div ref={parentRef} className="h-full overflow-y-auto preview-scrollbar" />
      </div>
    );
  }

  const virtualItems = virtualizer.getVirtualItems();

  return (
    <div className="relative flex-1 min-h-0">
      {stickyHeader && (
        <div ref={stickyHeaderRef} className="absolute top-0 inset-x-0 z-10">{stickyHeader}</div>
      )}
      <div
        ref={parentRef}
        onScroll={handleScroll}
        className="h-full overflow-y-auto preview-scrollbar"
      >
        <div style={{ height: stickyHeaderHeight }} />
        <div className="px-4 py-4">
          {isLoadingMessages && (
            <div className="flex justify-center py-2">
              <span className="text-xs text-muted-foreground animate-pulse">Loading earlier messages...</span>
            </div>
          )}

          <div
            style={{
              height: virtualizer.getTotalSize(),
              width: '100%',
              position: 'relative',
            }}
          >
            {virtualItems.map((virtualItem) => {
              const msg = visibleMessages[virtualItem.index];
              return (
                <div
                  key={msg.id}
                  data-index={virtualItem.index}
                  ref={virtualizer.measureElement}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    transform: `translateY(${virtualItem.start}px)`,
                  }}
                >
                  <div className="py-1.5">
                    <ChatMessage message={msg} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
