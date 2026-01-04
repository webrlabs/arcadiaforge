import { useState, useCallback, useRef, useEffect } from 'react';
import type { ChatEvent, ChatMessage, ToolCallData, ToolResultData, UserQuestionData } from './types';

interface ToolCallState {
  toolId: string;
  name: string;
  summary: string;
  status: 'running' | 'completed' | 'failed';
  input?: Record<string, unknown>;
  result?: string;
  duration?: number;
  imageUrl?: string;
  timestamp: string;
}

interface ChatState {
  messages: ChatMessage[];
  toolCalls: Map<string, ToolCallState>;
  pendingQuestions: Map<string, UserQuestionData>;
  answeredQuestions: Set<string>;
  isThinking: boolean;
  isConnected: boolean;
}

export function useChatState() {
  const [state, setState] = useState<ChatState>({
    messages: [],
    toolCalls: new Map(),
    pendingQuestions: new Map(),
    answeredQuestions: new Set(),
    isThinking: false,
    isConnected: false,
  });

  const scrollRef = useRef<HTMLDivElement>(null);
  const shouldAutoScroll = useRef(true);

  // Auto-scroll to bottom when new messages arrive
  const scrollToBottom = useCallback(() => {
    if (scrollRef.current && shouldAutoScroll.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [state.messages, scrollToBottom]);

  const setConnected = useCallback((connected: boolean) => {
    setState((prev) => ({ ...prev, isConnected: connected }));
  }, []);

  const clearMessages = useCallback(() => {
    setState((prev) => ({
      ...prev,
      messages: [],
      toolCalls: new Map(),
      pendingQuestions: new Map(),
      answeredQuestions: new Set(),
      isThinking: false,
    }));
  }, []);

  const processEvent = useCallback((event: ChatEvent) => {
    setState((prev) => {
      const newState = { ...prev };
      const timestamp = event.timestamp;
      const id = event.id;

      switch (event.type) {
        case 'agent_message': {
          const data = event.data as { content: string; isStreaming?: boolean };
          const message: ChatMessage = {
            id,
            timestamp,
            type: 'agent',
            data: { kind: 'agent', content: data.content, isStreaming: data.isStreaming },
          };
          newState.messages = [...prev.messages, message];
          newState.isThinking = false;
          break;
        }

        case 'tool_call': {
          const data = event.data as ToolCallData;
          const toolState: ToolCallState = {
            toolId: data.toolId,
            name: data.name,
            summary: data.summary,
            status: 'running',
            input: data.input,
            timestamp,
          };
          const newToolCalls = new Map(prev.toolCalls);
          newToolCalls.set(data.toolId, toolState);
          newState.toolCalls = newToolCalls;

          // Add tool call message
          const message: ChatMessage = {
            id,
            timestamp,
            type: 'tool',
            data: {
              kind: 'tool',
              toolId: data.toolId,
              name: data.name,
              summary: data.summary,
              status: 'running',
              input: data.input,
            },
          };
          newState.messages = [...prev.messages, message];
          break;
        }

        case 'tool_result': {
          const data = event.data as ToolResultData;
          const newToolCalls = new Map(prev.toolCalls);
          const existing = newToolCalls.get(data.toolId);
          if (existing) {
            newToolCalls.set(data.toolId, {
              ...existing,
              status: data.status,
              result: data.result,
              duration: data.duration,
              imageUrl: data.imageUrl,
            });
          }
          newState.toolCalls = newToolCalls;

          // Update tool message status
          newState.messages = prev.messages.map((msg) => {
            if (msg.type === 'tool' && msg.data.kind === 'tool' && msg.data.toolId === data.toolId) {
              return {
                ...msg,
                data: {
                  ...msg.data,
                  status: data.status,
                  result: data.result,
                  duration: data.duration,
                  imageUrl: data.imageUrl,
                },
              };
            }
            return msg;
          });
          break;
        }

        case 'user_question': {
          const data = event.data as UserQuestionData;
          const newQuestions = new Map(prev.pendingQuestions);
          newQuestions.set(data.questionId, data);
          newState.pendingQuestions = newQuestions;

          const message: ChatMessage = {
            id,
            timestamp,
            type: 'agent',
            data: {
              kind: 'question',
              questionId: data.questionId,
              question: data.question,
              options: data.options,
              inputType: data.inputType,
              isAnswered: false,
            },
          };
          newState.messages = [...prev.messages, message];
          newState.isThinking = false;
          break;
        }

        case 'user_response': {
          const data = event.data as { questionId: string; response: string };
          const newQuestions = new Map(prev.pendingQuestions);
          newQuestions.delete(data.questionId);
          newState.pendingQuestions = newQuestions;

          const newAnswered = new Set(prev.answeredQuestions);
          newAnswered.add(data.questionId);
          newState.answeredQuestions = newAnswered;

          // Mark question as answered and add user response
          newState.messages = prev.messages.map((msg) => {
            if (
              msg.data.kind === 'question' &&
              msg.data.questionId === data.questionId
            ) {
              return {
                ...msg,
                data: { ...msg.data, isAnswered: true },
              };
            }
            return msg;
          });

          // Add user response message
          const responseMessage: ChatMessage = {
            id: `${id}-response`,
            timestamp,
            type: 'user',
            data: {
              kind: 'user',
              content: data.response,
              isResponse: true,
              questionId: data.questionId,
            },
          };
          newState.messages = [...newState.messages, responseMessage];
          break;
        }

        case 'thinking': {
          const data = event.data as { isThinking: boolean };
          newState.isThinking = data.isThinking;
          break;
        }

        case 'system': {
          const data = event.data as { message: string; level?: string };
          const message: ChatMessage = {
            id,
            timestamp,
            type: 'system',
            data: {
              kind: 'system',
              message: data.message,
              level: (data.level as 'info' | 'warning' | 'error' | 'success') || 'info',
            },
          };
          newState.messages = [...prev.messages, message];
          break;
        }

        case 'error': {
          const data = event.data as { message: string; details?: string };
          const message: ChatMessage = {
            id,
            timestamp,
            type: 'system',
            data: {
              kind: 'system',
              message: data.details ? `${data.message}: ${data.details}` : data.message,
              level: 'error',
            },
          };
          newState.messages = [...prev.messages, message];
          break;
        }

        // Legacy event types for backwards compatibility
        case 'log': {
          const data = event.data as { message: string; style?: string };
          // Convert legacy logs to agent messages
          const message: ChatMessage = {
            id,
            timestamp,
            type: 'agent',
            data: { kind: 'agent', content: data.message },
          };
          newState.messages = [...prev.messages, message];
          break;
        }

        case 'tool': {
          // Legacy tool event
          const data = event.data as { name: string; summary: string; result: string };
          const toolId = `legacy-${id}`;
          const message: ChatMessage = {
            id,
            timestamp,
            type: 'tool',
            data: {
              kind: 'tool',
              toolId,
              name: data.name,
              summary: data.summary,
              status: data.result === 'error' ? 'failed' : 'completed',
              result: data.result,
            },
          };
          newState.messages = [...prev.messages, message];
          break;
        }

        case 'feedback_ack': {
          const data = event.data as { message: string; type: string };
          // User sent feedback, add as user message
          const message: ChatMessage = {
            id,
            timestamp,
            type: 'user',
            data: { kind: 'user', content: data.message },
          };
          newState.messages = [...prev.messages, message];
          break;
        }
      }

      return newState;
    });
  }, []);

  const respondToQuestion = useCallback((questionId: string, response: string) => {
    setState((prev) => {
      const newQuestions = new Map(prev.pendingQuestions);
      newQuestions.delete(questionId);

      const newAnswered = new Set(prev.answeredQuestions);
      newAnswered.add(questionId);

      // Mark question as answered
      const newMessages = prev.messages.map((msg) => {
        if (
          msg.data.kind === 'question' &&
          msg.data.questionId === questionId
        ) {
          return {
            ...msg,
            data: { ...msg.data, isAnswered: true },
          };
        }
        return msg;
      });

      // Add user response message
      const responseMessage: ChatMessage = {
        id: `response-${questionId}`,
        timestamp: new Date().toISOString(),
        type: 'user',
        data: {
          kind: 'user',
          content: response,
          isResponse: true,
          questionId,
        },
      };

      return {
        ...prev,
        messages: [...newMessages, responseMessage],
        pendingQuestions: newQuestions,
        answeredQuestions: newAnswered,
      };
    });
  }, []);

  return {
    messages: state.messages,
    isThinking: state.isThinking,
    isConnected: state.isConnected,
    answeredQuestions: state.answeredQuestions,
    scrollRef,
    setConnected,
    processEvent,
    clearMessages,
    respondToQuestion,
  };
}
