// Chat interface type definitions

export interface ChatEvent {
  id: string;
  timestamp: string;
  type: EventType;
  data: EventData;
}

export type EventType =
  | 'agent_message'
  | 'tool_call'
  | 'tool_result'
  | 'user_question'
  | 'user_response'
  | 'system'
  | 'thinking'
  | 'error'
  | 'log'
  | 'tool'
  | 'feedback_ack';

export type EventData =
  | AgentMessageData
  | ToolCallData
  | ToolResultData
  | UserQuestionData
  | UserResponseData
  | SystemData
  | ThinkingData
  | ErrorData
  | LogData
  | LegacyToolData
  | FeedbackAckData;

export interface AgentMessageData {
  content: string;
  isStreaming?: boolean;
}

export interface ToolCallData {
  toolId: string;
  name: string;
  summary: string;
  input?: Record<string, unknown>;
  status: 'running' | 'completed' | 'failed';
}

export interface ToolResultData {
  toolId: string;
  status: 'completed' | 'failed';
  result?: string;
  duration?: number;
  imageUrl?: string;
}

export interface UserQuestionData {
  questionId: string;
  question: string;
  options?: string[];
  inputType: 'text' | 'choice' | 'confirm';
}

export interface UserResponseData {
  questionId: string;
  response: string;
}

export interface SystemData {
  message: string;
  level: 'info' | 'warning' | 'error' | 'success';
}

export interface ThinkingData {
  isThinking: boolean;
}

export interface ErrorData {
  message: string;
  details?: string;
}

// Legacy event types (for backwards compatibility)
export interface LogData {
  message: string;
  style?: string;
  category?: string;
}

export interface LegacyToolData {
  name: string;
  summary: string;
  result: string;
}

export interface FeedbackAckData {
  message: string;
  type: string;
}

// Merged message type for display
export interface ChatMessage {
  id: string;
  timestamp: string;
  type: 'agent' | 'user' | 'tool' | 'system' | 'thinking';
  data: ChatMessageData;
}

export type ChatMessageData =
  | { kind: 'agent'; content: string; isStreaming?: boolean }
  | { kind: 'user'; content: string; isResponse?: boolean; questionId?: string }
  | { kind: 'tool'; toolId: string; name: string; summary: string; status: 'running' | 'completed' | 'failed'; result?: string; duration?: number; input?: Record<string, unknown>; imageUrl?: string }
  | { kind: 'system'; message: string; level: 'info' | 'warning' | 'error' | 'success' }
  | { kind: 'question'; questionId: string; question: string; options?: string[]; inputType: 'text' | 'choice' | 'confirm'; isAnswered: boolean }
  | { kind: 'thinking' };
