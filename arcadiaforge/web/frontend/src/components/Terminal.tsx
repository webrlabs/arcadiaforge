import React from 'react';
import { ChatContainer } from './chat';

interface TerminalProps {
  projectId: string;
  runId?: number;
}

/**
 * Terminal component - now uses the modern ChatContainer interface
 * This replaces the old CLI-style output with a chat-like experience
 */
const Terminal: React.FC<TerminalProps> = ({ projectId, runId = 0 }) => {
  return <ChatContainer key={`${projectId}-${runId}`} projectId={projectId} />;
};

export default Terminal;
