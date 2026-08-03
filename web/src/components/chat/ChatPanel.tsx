// components/chat/ChatPanel.tsx

'use client';

import { useRef, useEffect, useState, useCallback } from 'react';
import type { AgentMessageData, ChatMessage as ChatMessageType, ChatTokenData, ChatThinkingData, SelectOption } from '@/types/api';
import { nanoid } from 'nanoid';
import { useChatStore } from '@/store/useChatStore';
import { useResearchStore } from '@/store/useResearchStore';
import { useSessionStore } from '@/store/useSessionStore';
import { useResearch } from '@/hooks/useResearch';
import { useProgress, useSessionStream } from '@/hooks/useProgress';
import type { ChatResponseData } from '@/types/api';
import { ChatInput } from './ChatInput';
import { OptionSelector } from './OptionSelector';
import { SectionSelector } from './SectionSelector';
import { DynamicParameterForm } from './DynamicParameterForm';
// ProgressPanel removed — agent progress shown via inline agent_message events
import { SearchIndicator } from './SearchIndicator';
import { ResearchStatusBar } from './ResearchStatusBar';
import { VirtualMessageList } from './VirtualMessageList';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';
import { ArrowDown, Brain } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { parseTemplateCommand, RESEARCH_TEMPLATES, formatTemplateMessage, formatTemplateList, formatTemplateNotFound, extractTemplateKeyword } from '@/lib/templates';

export function ChatPanel() {
  const { messages, addMessage, updateMessage, appendStreamToken } = useChatStore();
  const {
    currentStep,
    stepOptions,
    parameterConfig,
    taskId,
    status,
    summary,
    framework,
    reset,
    clearResearch,
    phases,
    progress,
  } = useResearchStore();
  const {
    sessionId,
    startResearch,
    quickStartResearch,
    sendMessage,
    handleOptionSelect,
    selectSections,
    setParameters,
    confirmResearch,
    isProcessing,
    isNetworkBusy,
    isWaitingForReply,
    setIsWaitingForReply,
  } = useResearch();

  // Research progress stream (closes on task complete)
  const sseId = sessionId || taskId;
  const { isConnected } = useProgress(sseId);

  // Tracks the currently streaming message ID for token-by-token updates
  const streamingMsgIdRef = useRef<string | null>(null);
  const streamingDoneRef = useRef(false);
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  const searchStateTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const waitingTimeoutRef = useRef<ReturnType<typeof setTimeout>>();

  // Persistent session stream (stays alive, unaffected by task complete)
  // Receives chat_response + chat_token + agent_message events
  useSessionStream(sessionId, {
    onChatToken: (data: ChatTokenData) => {
      const storeSessionId = useSessionStore.getState().activeId;
      const matches = data.session_id === sessionIdRef.current
        || data.session_id === taskId
        || data.session_id === storeSessionId;
      if (!matches) return;
      if (streamingDoneRef.current) return;

      if (!streamingMsgIdRef.current) {
        streamingMsgIdRef.current = nanoid();
        addMessage({
          id: streamingMsgIdRef.current,
          role: 'assistant',
          content: data.token,
          timestamp: new Date().toISOString(),
          metadata: { status: 'streaming' },
        });
      } else {
        const currentMsg = useChatStore.getState().messages.find(m => m.id === streamingMsgIdRef.current);
        if (currentMsg?.metadata?.status === 'thinking') {
          updateMessage(streamingMsgIdRef.current, { metadata: { status: 'streaming' } });
        }
        appendStreamToken(streamingMsgIdRef.current, data.token, '');
      }
    },
    onChatThinking: (data: ChatThinkingData) => {
      const storeSessionId = useSessionStore.getState().activeId;
      const matches = data.session_id === sessionIdRef.current
        || data.session_id === taskId
        || data.session_id === storeSessionId;
      if (!matches) return;
      if (streamingDoneRef.current) return;

      if (!streamingMsgIdRef.current) {
        streamingMsgIdRef.current = nanoid();
        addMessage({
          id: streamingMsgIdRef.current,
          role: 'assistant',
          content: '',
          thinkingContent: data.token,
          timestamp: new Date().toISOString(),
          metadata: { status: 'thinking' },
        });
      } else {
        const currentMsg = useChatStore.getState().messages.find(m => m.id === streamingMsgIdRef.current);
        if (currentMsg?.metadata?.status === 'streaming') {
          updateMessage(streamingMsgIdRef.current, { metadata: { status: 'thinking' } });
        }
        appendStreamToken(streamingMsgIdRef.current, '', data.token);
      }
    },
    onChatResponse: (data) => {
      const storeSessionId = useSessionStore.getState().activeId;
      const matches = data.session_id === sessionIdRef.current
        || data.session_id === taskId
        || data.session_id === storeSessionId;
      if (!matches) return;

      if (streamingDoneRef.current) return;

      const existingAssistantMsg = useChatStore.getState().messages.find(
        m => m.role === 'assistant' && m.timestamp === data.timestamp
      );
      if (existingAssistantMsg) return;

      let finalContent = data.message;
      let finalThinking: string | undefined = data.thinking_content;

      const trimmed = finalContent.trim();
      if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
        try {
          const parsed = JSON.parse(trimmed);
          if (parsed.message && typeof parsed.message === 'string') {
            finalContent = parsed.message;
          }
        } catch {}
      }

      if (streamingMsgIdRef.current) {
        updateMessage(streamingMsgIdRef.current, {
          content: finalContent,
          ...(finalThinking !== undefined ? { thinkingContent: finalThinking } : {}),
          metadata: { status: 'done' },
        });
        streamingMsgIdRef.current = null;
        streamingDoneRef.current = true;
      } else {
        addMessage({
          id: nanoid(),
          role: 'assistant',
          content: finalContent,
          ...(finalThinking !== undefined ? { thinkingContent: finalThinking } : {}),
          timestamp: data.timestamp || new Date().toISOString(),
        });
        streamingDoneRef.current = true;
      }

      setIsWaitingForReply(false);

      const mode = (data as any).mode || 'chat';
      const action = data.action || 'continue_chat';

      if (mode === 'framework') {
        useResearchStore.getState().setStatus('idle');
        useResearchStore.getState().setStep(0, data.suggestions || []);
        if ((data as any).framework) {
          useResearchStore.getState().setFramework((data as any).framework);
        } else {
          api.getResearchDetail(data.session_id).then((detail) => {
            if (detail.framework) {
              useResearchStore.getState().setFramework(detail.framework);
            }
          }).catch(() => {});
        }
      } else if (mode === 'research' && (data as any).step === 6) {
        useResearchStore.getState().setTaskId(data.session_id);
        useResearchStore.getState().setStatus('running');
        useResearchStore.getState().setStep(6, undefined);
      } else if (action === 'enter_framework') {
        useResearchStore.getState().setStatus('idle');
        useResearchStore.getState().setStep(0, data.suggestions || []);
        if ((data as any).framework) {
          useResearchStore.getState().setFramework((data as any).framework);
        } else {
          api.getResearchDetail(data.session_id).then((detail) => {
            if (detail.framework) {
              useResearchStore.getState().setFramework(detail.framework);
            }
          }).catch(() => {});
        }
      } else if (action === 'start_execution' || action === 'start_research') {
        useResearchStore.getState().setStatus('running');
        useResearchStore.getState().setStep(6, undefined);
      } else {
        if (data.suggestions && data.suggestions.length > 0) {
          useResearchStore.getState().setStep(0, data.suggestions);
        }
      }

      useResearchStore.getState().setSearchState('completed');
      const rs = useResearchStore.getState();
      if (rs.status !== 'running') {
        setIsWaitingForReply(false);
        clearTimeout(waitingTimeoutRef.current);
      }
      clearTimeout(searchStateTimerRef.current);
      searchStateTimerRef.current = setTimeout(() => {
        useResearchStore.getState().setSearchState('idle');
      }, 2000);
    },
    onAgentMessage: (data: AgentMessageData) => {
      const storeSessionId = useSessionStore.getState().activeId;
      if (data.session_id === sessionId || data.session_id === storeSessionId) {
        if (data.action === 'heartbeat') {
          const progressMatch = data.content.match(/\((\d+)%\s*complete\)/);
          if (progressMatch) {
            const pct = parseInt(progressMatch[1], 10) / 100;
            const rs = useResearchStore.getState();
            if (rs.status === 'running' && pct > rs.progress) {
              rs.setProgress(pct);
            }
          }
          return;
        }
        const MERGEABLE_IDS = ['web_search', 'news_search', 'scrape_url'];
        if (MERGEABLE_IDS.includes(data.agent_id) && data.action !== 'error') {
          const msgs = useChatStore.getState().messages;
          const existing = [...msgs].reverse().find(
            m => m.role === 'agent' && m.agent?.id === data.agent_id && m.agent?.action !== 'heartbeat' && m.agent?.action !== 'error'
          );
          if (existing) {
            const prevCompleted = existing.agent?.completedCount || 0;
            const prevTotal = existing.agent?.totalCount || 0;
            const isCompleted = data.action === 'completed';
            const newCompleted = isCompleted ? prevCompleted + 1 : prevCompleted;
            const newTotal = isCompleted ? Math.max(prevTotal, newCompleted) : prevTotal;
            const displayAction = (isCompleted && newCompleted < newTotal) ? existing.agent!.action : data.action;
            updateMessage(existing.id, {
              content: data.content,
              timestamp: data.timestamp,
              agent: {
                ...existing.agent!,
                action: displayAction,
                completedCount: newCompleted,
                totalCount: newTotal,
              },
            });
            return;
          }
          const isCompleted = data.action === 'completed';
          addMessage({
            id: nanoid(),
            role: 'agent',
            content: data.content,
            timestamp: data.timestamp,
            agent: {
              id: data.agent_id,
              name: data.agent_name,
              action: data.action,
              completedCount: isCompleted ? 1 : 0,
              totalCount: isCompleted ? 1 : 0,
            },
          });
          return;
        }
        const updatableActions = ['searching', 'writing'] as const;
        if (updatableActions.includes(data.action as any)) {
          const msgs = useChatStore.getState().messages;
          const lastSame = [...msgs].reverse().find(
            m => m.role === 'agent' && m.agent?.id === data.agent_id && m.agent?.action === data.action
          );
          if (lastSame) {
            updateMessage(lastSame.id, { content: data.content, timestamp: data.timestamp });
            return;
          }
        }
        addMessage({
          id: nanoid(),
          role: 'agent',
          content: data.content,
          timestamp: data.timestamp,
          agent: { id: data.agent_id, name: data.agent_name, action: data.action },
        });
      }
    },
  });

  // Cleanup timer on unmount (Oracle MAJOR)
  useEffect(() => {
    return () => {
      clearTimeout(searchStateTimerRef.current);
      clearTimeout(waitingTimeoutRef.current);
    };
  }, []);

  // Infinite scroll: load older messages on scroll-to-top
  const [hasMoreMessages, setHasMoreMessages] = useState(true);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const serverOffsetRef = useRef(0);

  const loadOlderMessages = useCallback(async () => {
    if (isLoadingMessages || !hasMoreMessages) return;
    const store = useSessionStore.getState();
    const activeId = store.activeId;
    if (!activeId) return;

    setIsLoadingMessages(true);
    try {
      const result = await api.getMessages(activeId, serverOffsetRef.current, 50);
      if (result.messages.length === 0) {
        setHasMoreMessages(false);
      } else {
        const currentIds = new Set(useChatStore.getState().messages.map(m => m.id));
          const olderMsgs: ChatMessageType[] = result.messages
            .filter((m: any) => !currentIds.has(m.id))
            .filter((m: any) => !(m.role === 'agent' && m.action === 'heartbeat'))
            .map((m: any) => ({
            id: m.id || nanoid(),
            role: (m.role === 'user' || m.role === 'assistant' || m.role === 'agent'
              ? m.role
              : 'system') as ChatMessageType['role'],
            content: m.content,
            timestamp: m.timestamp || new Date().toISOString(),
            ...(m.agent_id || m.agent_name || m.action ? {
              agent: {
                id: m.agent_id || '',
                name: m.agent_name || '',
                action: m.action || '',
                completedCount: m.completedCount,
                totalCount: m.totalCount,
              },
            } : {}),
          }));
        if (olderMsgs.length > 0) {
          useChatStore.getState().prependMessages(olderMsgs);
        }
        serverOffsetRef.current = result.offset + result.messages.length;
        if (!result.has_more) {
          setHasMoreMessages(false);
        }
      }
    } catch (e) {
      console.error('Failed to load older messages:', e);
    } finally {
      setIsLoadingMessages(false);
    }
  }, [isLoadingMessages, hasMoreMessages]);

  const activeSessionId = useSessionStore((s) => s.activeId);

  useEffect(() => {
    streamingMsgIdRef.current = null;
    streamingDoneRef.current = false;
  }, [activeSessionId]);

  useEffect(() => {
    const hasHeartbeat = messages.some(m => m.role === 'agent' && (m.agent?.action === 'heartbeat' || (m as any).action === 'heartbeat'));
    if (hasHeartbeat) {
      const cleaned = messages.filter(m => !(m.role === 'agent' && (m.agent?.action === 'heartbeat' || (m as any).action === 'heartbeat')));
      useChatStore.setState({ messages: cleaned });
      useSessionStore.getState().syncActive({ messages: cleaned });
    }
  }, [messages.length]);

  useEffect(() => {
    if (status === 'running' && !streamingMsgIdRef.current) {
      const hasAssistant = messages.some(m => m.role === 'assistant' && m.metadata?.status !== 'streaming' && m.metadata?.status !== 'thinking');
      if (!hasAssistant) {
        setIsWaitingForReply(true);
      }
    } else if (status !== 'running') {
      setIsWaitingForReply(false);
    }
  }, [status, activeSessionId, messages.length]);

  useEffect(() => {
    const sessionMessages = useSessionStore.getState().sessions[activeSessionId ?? '']?.messages;
    if (sessionMessages) {
      serverOffsetRef.current = sessionMessages.length;
      setHasMoreMessages(sessionMessages.length > 0);
    } else {
      serverOffsetRef.current = 0;
      setHasMoreMessages(true);
    }
  }, [activeSessionId]);

  const scrollToBottomRef = useRef<(() => void) | null>(null);

  const [showScrollBtn, setShowScrollBtn] = useState(false);

  const handleAtBottomChange = useCallback((showButton: boolean) => {
    setShowScrollBtn(showButton);
  }, []);

  const scrollToBottom = useCallback(() => {
    scrollToBottomRef.current?.();
  }, []);

  useEffect(() => {
    const handleBeforeUnload = () => { useChatStore.getState().flushSyncNow(); };
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') useChatStore.getState().flushSyncNow();
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    window.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
      window.removeEventListener('visibilitychange', handleVisibilityChange);
      useChatStore.getState().flushSyncNow();
    };
  }, []);

  // hasActiveResearch removed — ProgressPanel replaced by inline agent messages
  const isChatMode = currentStep === null || currentStep === 0;

  const handleSend = async (text: string, attachments?: File[], selectedModel?: string) => {
    // Reset streaming state for new user message
    streamingMsgIdRef.current = null;
    streamingDoneRef.current = false;
    addMessage({
      id: nanoid(),
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    });

    // Parse /template command
    const { isTemplateCommand, templateId, remainingText } = parseTemplateCommand(text);

    if (isTemplateCommand) {
      // C6: template state cleanup inside the branch
      useResearchStore.getState().setActiveTemplate(null);
      useResearchStore.getState().setResearchTopic(null);

      if (!templateId) {
        // Bare /template — show available template list
        addMessage({
          id: nanoid(),
          role: 'assistant',
          content: formatTemplateList(),
          timestamp: new Date().toISOString(),
        });
        return;
      }

      const template = RESEARCH_TEMPLATES.find(t => t.id === templateId);
      if (template) {
        useResearchStore.getState().setActiveTemplate(template);

        if (remainingText) {
          useResearchStore.getState().setResearchTopic(remainingText);
          const msg = `我选择了 ${template.name} 模板研究：${remainingText}。模板章节包括：${template.sections.join('、')}。默认参数：${Object.entries(template.parameters).map(([k,v]) => `${k}=${v}`).join('，')}。请基于这个模板框架，用中文给出研究计划建议。`;
          const hasSession = !!(sessionId && useSessionStore.getState().sessions[sessionId]);
          try {
            if (hasSession) await sendMessage(msg);
            else await startResearch(msg);
          } catch (error) {
            console.error('Failed to start template chat:', error);
            useResearchStore.getState().setStep(0, []);
          }
        } else {
          addMessage({
            id: nanoid(), role: 'assistant',
            content: formatTemplateMessage(template),
            timestamp: new Date().toISOString(),
          });
          useResearchStore.getState().setStep(0, []);
        }
        return;
      }

      // Template not found
      const keyword = extractTemplateKeyword(text);
      addMessage({
        id: nanoid(),
        role: 'assistant',
        content: formatTemplateNotFound(keyword),
        timestamp: new Date().toISOString(),
      });
      return;
    }

    try {
      if (sessionId) {
        const data = await sendMessage(text);
        if (data && (data as any).status === 'processing') {
          const thinkingContent = (data as any).thinking_content;
          const processingMsg = (data as any).message;
          if (thinkingContent || processingMsg) {
            const msgId = nanoid();
            streamingMsgIdRef.current = msgId;
            addMessage({
              id: msgId,
              role: 'assistant',
              content: processingMsg || '',
              ...(thinkingContent ? { thinkingContent } : {}),
              timestamp: new Date().toISOString(),
              metadata: { status: thinkingContent ? 'thinking' : 'streaming' },
            });
          }
          useResearchStore.getState().setSearchState('searching');
          clearTimeout(waitingTimeoutRef.current);
          waitingTimeoutRef.current = setTimeout(() => {
            setIsWaitingForReply(false);
            useResearchStore.getState().setSearchState('idle');
            if (streamingMsgIdRef.current) {
              updateMessage(streamingMsgIdRef.current, {
                metadata: { status: 'done' },
              });
              streamingMsgIdRef.current = null;
              streamingDoneRef.current = true;
            }
          }, 300000);
          return;
        }
      } else {
        const data = await startResearch(text, attachments, selectedModel);
        if (data && (data as any).status === 'processing') {
          const thinkingContent = (data as any).thinking_content;
          const processingMsg = (data as any).message;
          if (thinkingContent || processingMsg) {
            const msgId = nanoid();
            streamingMsgIdRef.current = msgId;
            addMessage({
              id: msgId,
              role: 'assistant',
              content: processingMsg || '',
              ...(thinkingContent ? { thinkingContent } : {}),
              timestamp: new Date().toISOString(),
              metadata: { status: thinkingContent ? 'thinking' : 'streaming' },
            });
          }
          useResearchStore.getState().setSearchState('searching');
          clearTimeout(waitingTimeoutRef.current);
          waitingTimeoutRef.current = setTimeout(() => {
            setIsWaitingForReply(false);
            useResearchStore.getState().setSearchState('idle');
            if (streamingMsgIdRef.current) {
              updateMessage(streamingMsgIdRef.current, {
                metadata: { status: 'done' },
              });
              streamingMsgIdRef.current = null;
              streamingDoneRef.current = true;
            }
          }, 300000);
          return;
        }
      }
    } catch (error) {
      console.error('Failed to send message:', error);
      setIsWaitingForReply(false);
      clearTimeout(waitingTimeoutRef.current);
      addMessage({
        id: nanoid(),
        role: 'assistant',
        content: 'Sorry, failed to send message. Please check if the backend service is running properly.',
        timestamp: new Date().toISOString(),
      });
    }
  };

  const handleResume = async () => {
    if (!taskId) return;
    try {
      const result = await api.resumeResearch(taskId);
      if (result.status === 'resumed') {
        useResearchStore.getState().setStatus('running');
        if (!sessionId) {
          useResearchStore.getState().setSessionId(taskId);
        }
      } else if (result.status === 'paused' || result.status === 'failed') {
        useResearchStore.getState().setStatus('idle');
        addMessage({
          id: nanoid(),
          role: 'assistant',
          content: result.message || 'Research engine has stopped. You can start a new task or continue chatting.',
          timestamp: new Date().toISOString(),
        });
      } else if (result.status === 'cancelled') {
        useResearchStore.getState().clearResearch();
        addMessage({
          id: nanoid(),
          role: 'assistant',
          content: result.message || 'Research was cancelled.',
          timestamp: new Date().toISOString(),
        });
      }
    } catch (e) {
      console.error('Failed to resume research:', e);
    }
  };

  const handleCancel = async () => {
    if (taskId && status === 'running') {
      try { await api.pauseResearch(taskId); } catch {}
      useResearchStore.getState().setStatus('paused');
      setIsWaitingForReply(false);
      clearTimeout(waitingTimeoutRef.current);
      addMessage({
        id: nanoid(),
        role: 'assistant',
        content: 'Research paused. Progress has been saved. You can resume later or continue chatting.',
        timestamp: new Date().toISOString(),
      });
      return;
    }
    if (sessionId && isWaitingForReply) {
      try { await api.cancelResearch(sessionId); } catch {}
      setIsWaitingForReply(false);
      clearTimeout(waitingTimeoutRef.current);
      useResearchStore.getState().setSearchState('idle');
      addMessage({
        id: nanoid(),
        role: 'assistant',
        content: 'Search cancelled.',
        timestamp: new Date().toISOString(),
      });
      return;
    }
    if (taskId) {
      try { await api.cancelResearch(taskId); } catch {}
      clearResearch();
    }
    setIsWaitingForReply(false);
    clearTimeout(waitingTimeoutRef.current);
    addMessage({
      id: nanoid(),
      role: 'assistant',
      content: 'Task cancelled. You can continue with new requests.',
      timestamp: new Date().toISOString(),
    });
  };

  // Render step content (framework interaction steps 1-5)
  const renderStepContent = () => {
    if (isProcessing && !currentStep) {
      return (
        <div className="flex items-center justify-center py-8">
          <div className="flex items-center gap-3">
            <Brain className="h-5 w-5 animate-pulse text-purple-600" />
            <span className="text-sm text-purple-700">AI 正在思考...</span>
          </div>
        </div>
      );
    }

    if (isChatMode) {
      const tpl = useResearchStore.getState().activeTemplate;
      const topic = useResearchStore.getState().researchTopic;
      const baseOptions = stepOptions || [];
      const isZh = (topic || framework?.topic) ? /[\u4e00-\u9fff]/.test(topic || framework?.topic || '') : false;

      if (framework && framework.sections && framework.sections.length > 0 && status === 'idle') {
        const frameworkOptions: SelectOption[] = framework.sections.map((s, i) => ({
          id: `section-${i}`,
          label: s,
          description: '',
          selected: true,
        }));

        return (
          <div className="space-y-3">
            <SectionSelector
              title={isZh ? '研究框架章节' : 'Research Framework Sections'}
              description={isZh
                ? `研究主题: ${framework.topic} — 选择要包含的章节`
                : `Topic: ${framework.topic} — Select sections to include`}
              sections={frameworkOptions}
              frameworkTree={framework.sections_tree}
              onConfirm={handleFrameworkSectionConfirm}
              disabled={isProcessing}
            />
            {baseOptions.length > 0 && (
              <div className="grid grid-cols-2 gap-2">
                {baseOptions.map((option) => (
                  <button
                    key={option.id}
                    onClick={() => handleOptionSelect(option.id, option.example)}
                    disabled={isProcessing}
                    className="bg-card border rounded-xl shadow-sm p-3 text-left hover:border-primary/50 transition-colors disabled:opacity-50"
                  >
                    <div className="font-medium text-sm text-foreground">{option.label}</div>
                    {option.example && (
                      <div className="text-xs text-muted-foreground mt-1">{option.example}</div>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        );
      }

      const enhancedOptions = (tpl && topic)
        ? [...baseOptions, {
            id: 'start_research',
            label: isZh ? '开始研究' : 'Start Research',
            example: isZh
              ? `使用定制后的 ${tpl.name} 开始研究`
              : `Start research with customized ${tpl.name}`,
            description: isZh ? '使用定制框架开始研究' : 'Use customized framework to start research',
          }]
        : baseOptions;

      if (enhancedOptions.length > 0) {
        return (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground px-1">{isZh ? '你可以选择：' : 'You can choose:'}</p>
            <div className="grid grid-cols-2 gap-2">
                {enhancedOptions.map((option) => (
                  <button
                    key={option.id}
                    onClick={() => handleOptionSelect(option.id, option.example)}
                    disabled={isProcessing}
                    className="bg-card border rounded-xl shadow-sm p-3 text-left hover:border-primary/50 transition-colors disabled:opacity-50"
                  >
                    <div className="font-medium text-sm text-foreground">{option.label}</div>
                    {option.example && (
                      <div className="text-xs text-muted-foreground mt-1">{option.example}</div>
                    )}
                  </button>
                ))}
            </div>
          </div>
        );
      }
    }

    // ProgressPanel removed — agent progress shown via inline agent_message events

    if (stepOptions && !stepOptions.some((o) => o.required !== undefined) && currentStep !== 3 && currentStep !== 4) {
      if (currentStep === 5) {
        return (
          <OptionSelector
            title="Confirm Research Plan"
            description="Please confirm whether to start the research task"
            options={stepOptions}
            onSelect={(id) => handleConfirm(id === 'confirm')}
            disabled={isProcessing}
          />
        );
      }
      return (
        <OptionSelector
          title={currentStep === 1 ? 'Select Output Type' : 'Select Template'}
          options={stepOptions}
          onSelect={handleOptionSelect}
          disabled={isProcessing}
        />
      );
    }

    if (currentStep === 3 && stepOptions) {
      return (
        <SectionSelector
          sections={stepOptions}
          onConfirm={handleSectionConfirm}
          disabled={isProcessing}
        />
      );
    }

    if (currentStep === 4 && parameterConfig) {
      const params = Array.isArray(parameterConfig)
        ? parameterConfig
        : (parameterConfig as any)?.parameters || [];
      return (
        <DynamicParameterForm
          parameters={params}
          onSubmit={handleParameterSubmit}
          disabled={isProcessing}
        />
      );
    }

    return null;
  };

  const handleSectionConfirm = async (selectedIds: string[]) => {
    try { await selectSections(selectedIds); } catch (error) { console.error('Failed to select sections:', error); }
  };

  const handleFrameworkSectionConfirm = async (selectedIds: string[], outputFormat?: string) => {
    if (!framework) return;
    const sectionMap = new Map(framework.sections.map((s, i) => [`section-${i}`, s]));
    const selectedLabels = selectedIds
      .map(id => sectionMap.get(id))
      .filter((label): label is string => label !== undefined);
    if (selectedLabels.length === 0) return;
    const isZh = /[\u4e00-\u9fff]/.test(framework.topic || '');
    const fmt = outputFormat || 'docx';
    const fmtLabel = fmt === 'pptx' ? 'PPT' : fmt === 'html' ? 'HTML' : 'Word';
    const sectionsJson = JSON.stringify(selectedLabels);
    const exampleText = isZh
      ? `确认开始研究，包含章节：${selectedLabels.join('、')}\n__SELECTED_SECTIONS__:${sectionsJson}\n__OUTPUT_FORMAT__:${fmt}`
      : `Confirm and start research with sections: ${selectedLabels.join(', ')}\n__SELECTED_SECTIONS__:${sectionsJson}\n__OUTPUT_FORMAT__:${fmt}`;
    try {
      await handleOptionSelect('confirm_start', exampleText);
      const confirmContent = isZh
        ? `✅ 已确认研究框架\n\n**文档格式**：${fmtLabel}\n\n**研究章节**：\n${selectedLabels.map((s, i) => `${i + 1}. ${s}`).join('\n')}`
        : `✅ Research Framework Confirmed\n\n**Format**: ${fmtLabel}\n\n**Sections**:\n${selectedLabels.map((s, i) => `${i + 1}. ${s}`).join('\n')}`;
      addMessage({
        id: nanoid(),
        role: 'assistant',
        content: confirmContent,
        timestamp: new Date().toISOString(),
      });
    } catch (error) { console.error('Failed to confirm framework:', error); }
  };

  const handleParameterSubmit = async (params: Record<string, any>) => {
    try { await setParameters(params); } catch (error) { console.error('Failed to set parameters:', error); }
  };

  const handleConfirm = async (confirmed: boolean) => {
    try { await confirmResearch(confirmed); } catch (error) { console.error('Failed to confirm research:', error); }
  };

  const pendingInputData = useSessionStore((s) => {
    const sid = s.activeId;
    return sid ? s.sessions[sid]?.pendingInput : null;
  });
  const pendingInputText = pendingInputData?.text || undefined;

  const pendingInputConsumedRef = useRef<string | null>(null);
  const pendingInputTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (pendingInputData && pendingInputConsumedRef.current !== pendingInputData.text) {
      pendingInputConsumedRef.current = pendingInputData.text;
      if (pendingInputTimerRef.current) clearTimeout(pendingInputTimerRef.current);
      pendingInputTimerRef.current = setTimeout(() => {
        useSessionStore.getState().syncActive({ pendingInput: null });
        pendingInputConsumedRef.current = null;
        pendingInputTimerRef.current = null;
      }, 100);
    }
    return () => {
      if (pendingInputTimerRef.current) clearTimeout(pendingInputTimerRef.current);
    };
  }, [pendingInputData]);

  return (
    <div className="relative flex h-full flex-col bg-background">
      {/* Message list — status bars are sticky headers inside the scroll container */}
      <VirtualMessageList
        messages={messages}
        loadOlderMessages={loadOlderMessages}
        hasMoreMessages={hasMoreMessages}
        isLoadingMessages={isLoadingMessages}
        onAtBottomChange={handleAtBottomChange}
        scrollToBottomRef={scrollToBottomRef}
        stickyHeader={
          <>
            <SearchIndicator isWaitingForReply={isWaitingForReply} />
            <ResearchStatusBar />
          </>
        }
      />

      {/* Step content and paused status rendered below virtual list */}
      {(() => {
        const stepContent = currentStep !== null ? renderStepContent() : null;
        return stepContent ? (
          <div className="px-4 pb-2">
            <div className="mt-2">
              {stepContent}
            </div>
          </div>
        ) : null;
      })()}

      {status === 'paused' && taskId && (
        <div className="px-4 pb-2">
          <div className="space-y-3 p-4 bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 rounded-xl mt-2">
            <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
              研究已暂停
            </p>
            <p className="text-xs text-amber-600 dark:text-amber-400">
              研究任务已暂停，已采集的数据已缓存。您可以恢复研究或取消。
            </p>
            <div className="flex gap-2">
              <button
                onClick={handleResume}
                className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90"
              >
                恢复研究
              </button>
              <button
                onClick={handleCancel}
                className="px-4 py-2 bg-secondary text-secondary-foreground rounded-lg text-sm font-medium hover:bg-secondary/90"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Scroll to bottom */}
      {showScrollBtn && (
        <div className="absolute bottom-24 left-1/2 -translate-x-1/2 z-10">
          <button
            onClick={scrollToBottom}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-card/95 backdrop-blur-sm shadow-lg border border-border/50 text-xs text-foreground hover:bg-secondary transition-all duration-200"
          >
            <ArrowDown className="h-3 w-3" />
            <span>New messages</span>
          </button>
        </div>
      )}

      {/* Input area */}
      <div className="border-t border-border/50 p-3 pb-5 bg-background">
        <ChatInput
          onSend={handleSend}
          onCancel={handleCancel}
          disabled={false}
          isLoading={isProcessing}
          isNetworkBusy={isNetworkBusy}
          isWaitingForReply={isWaitingForReply}
          isRunning={status === 'running'}
          isPaused={status === 'paused'}
          pendingInput={pendingInputText}
          placeholder="Describe research needs or /template &lt;name&gt;"
        />
      </div>
    </div>
  );
}
