import React, { useEffect, useRef, useState } from 'react';
import { Box, TextField, IconButton, Typography, useTheme as useMuiTheme, alpha } from '@mui/material';
import { Send, ArrowDown } from 'lucide-react';
import { WS_BASE } from '../../services/api';
import { useChatState } from './useChatState';
import type { ChatEvent } from './types';
import ControlPanel from '../ControlPanel';
import AgentMessage from './AgentMessage';
import UserMessage from './UserMessage';
import ToolCallCard from './ToolCallCard';
import UserQuestion from './UserQuestion';
import ThinkingIndicator from './ThinkingIndicator';
import SystemMessage from './SystemMessage';

interface ChatContainerProps {
  projectId: string;
}

const ChatContainer: React.FC<ChatContainerProps> = ({ projectId }) => {
  const muiTheme = useMuiTheme();
  const isDark = muiTheme.palette.mode === 'dark';
  const [inputValue, setInputValue] = useState('');
  const [showScrollButton, setShowScrollButton] = useState(false);
  const ws = useRef<WebSocket | null>(null);

  const {
    messages,
    isThinking,
    isConnected,
    answeredQuestions,
    scrollRef,
    setConnected,
    processEvent,
    clearMessages,
    respondToQuestion,
  } = useChatState();

  useEffect(() => {
    // Initialize WebSocket
    const socket = new WebSocket(`${WS_BASE}/run/${projectId}`);
    ws.current = socket;

    socket.onopen = () => {
      setConnected(true);
    };

    socket.onmessage = (event) => {
      const data: ChatEvent = JSON.parse(event.data);
      processEvent(data);
    };

    socket.onclose = () => {
      setConnected(false);
    };

    return () => {
      socket.close();
    };
  }, [projectId, setConnected, processEvent]);

  // Handle scroll position for showing scroll-to-bottom button
  const handleScroll = () => {
    if (scrollRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
      const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
      setShowScrollButton(!isNearBottom);
    }
  };

  const scrollToBottom = () => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  };

  const sendCommand = (cmd: string) => {
    if (ws.current && isConnected) {
      ws.current.send(cmd);
    }
  };

  const handleSend = () => {
    if (inputValue.trim()) {
      sendCommand(inputValue);
      setInputValue('');
    }
  };

  const handleQuestionResponse = (questionId: string, response: string) => {
    respondToQuestion(questionId, response);
    sendCommand(response);
  };

  const renderMessage = (message: (typeof messages)[0]) => {
    const { id, timestamp, data } = message;

    switch (data.kind) {
      case 'agent':
        return (
          <AgentMessage
            key={id}
            content={data.content}
            timestamp={timestamp}
            isStreaming={data.isStreaming}
          />
        );

      case 'user':
        return (
          <UserMessage
            key={id}
            content={data.content}
            timestamp={timestamp}
            isResponse={data.isResponse}
          />
        );

      case 'tool':
        return (
          <ToolCallCard
            key={id}
            toolId={data.toolId}
            name={data.name}
            summary={data.summary}
            status={data.status}
            input={data.input}
            result={data.result}
            duration={data.duration}
            imageUrl={data.imageUrl}
          />
        );

      case 'question':
        return (
          <UserQuestion
            key={id}
            questionId={data.questionId}
            question={data.question}
            options={data.options}
            inputType={data.inputType}
            onRespond={handleQuestionResponse}
            isAnswered={data.isAnswered || answeredQuestions.has(data.questionId)}
            timestamp={timestamp}
          />
        );

      case 'system':
        return (
          <SystemMessage
            key={id}
            message={data.message}
            level={data.level}
            timestamp={timestamp}
          />
        );

      default:
        return null;
    }
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', bgcolor: isDark ? '#0A0A0A' : 'background.default' }}>
      {/* Control Panel Header */}
      <ControlPanel
        isConnected={isConnected}
        onStop={() => sendCommand('/stop')}
        onPause={() => sendCommand('/pause')}
        onSkip={() => sendCommand('/skip')}
        onClear={clearMessages}
      />

      {/* Chat Messages Area */}
      <Box
        ref={scrollRef}
        onScroll={handleScroll}
        sx={{
          flexGrow: 1,
          p: 2,
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          position: 'relative',
          '&::-webkit-scrollbar': {
            width: 8,
          },
          '&::-webkit-scrollbar-track': {
            bgcolor: 'transparent',
          },
          '&::-webkit-scrollbar-thumb': {
            bgcolor: alpha(muiTheme.palette.text.primary, 0.1),
            borderRadius: 4,
            '&:hover': {
              bgcolor: alpha(muiTheme.palette.text.primary, 0.2),
            },
          },
        }}
      >
        {messages.length === 0 && !isThinking && (
          <Box
            sx={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              flex: 1,
              color: 'text.secondary',
              textAlign: 'center',
              gap: 1,
            }}
          >
            <Typography variant="h6" sx={{ opacity: 0.5 }}>
              Ready to start
            </Typography>
            <Typography variant="body2" sx={{ opacity: 0.4 }}>
              The agent session will appear here
            </Typography>
          </Box>
        )}

        {messages.map(renderMessage)}

        {isThinking && <ThinkingIndicator />}
      </Box>

      {/* Scroll to Bottom Button */}
      {showScrollButton && (
        <IconButton
          onClick={scrollToBottom}
          sx={{
            position: 'absolute',
            bottom: 80,
            right: 24,
            bgcolor: alpha(muiTheme.palette.primary.main, 0.2),
            border: `1px solid ${alpha(muiTheme.palette.primary.main, 0.3)}`,
            color: 'primary.main',
            zIndex: 10,
            '&:hover': {
              bgcolor: alpha(muiTheme.palette.primary.main, 0.3),
            },
          }}
        >
          <ArrowDown size={20} />
        </IconButton>
      )}

      {/* Input Area */}
      <Box
        sx={{
          p: 2,
          borderTop: '1px solid',
          borderColor: 'divider',
          bgcolor: isDark ? 'rgba(0, 0, 0, 0.3)' : 'rgba(255, 255, 255, 0.8)',
        }}
      >
        <Box
          sx={{
            display: 'flex',
            gap: 1,
            alignItems: 'center',
          }}
        >
          <TextField
            fullWidth
            size="small"
            placeholder="Type a message or /command..."
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleSend()}
            disabled={!isConnected}
            sx={{
              '& .MuiOutlinedInput-root': {
                bgcolor: isDark ? 'rgba(255, 255, 255, 0.03)' : 'rgba(0, 0, 0, 0.02)',
                borderRadius: 3,
                '& fieldset': {
                  borderColor: isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)',
                },
                '&:hover fieldset': {
                  borderColor: isDark ? 'rgba(255, 255, 255, 0.2)' : 'rgba(0, 0, 0, 0.2)',
                },
                '&.Mui-focused fieldset': {
                  borderColor: 'primary.main',
                },
              },
              '& .MuiInputBase-input': {
                fontSize: '0.9rem',
                py: 1.5,
              },
            }}
          />
          <IconButton
            onClick={handleSend}
            disabled={!isConnected || !inputValue.trim()}
            sx={{
              bgcolor: 'primary.main',
              color: isDark ? '#000' : '#fff',
              width: 44,
              height: 44,
              '&:hover': {
                bgcolor: 'primary.dark',
              },
              '&:disabled': {
                bgcolor: 'rgba(34, 211, 238, 0.2)',
                color: isDark ? 'rgba(0, 0, 0, 0.5)' : 'rgba(255, 255, 255, 0.5)',
              },
            }}
          >
            <Send size={20} />
          </IconButton>
        </Box>

        {/* Helper Text */}
        <Typography
          variant="caption"
          sx={{
            color: 'text.secondary',
            fontSize: '0.65rem',
            mt: 1,
            display: 'block',
            opacity: 0.6,
          }}
        >
          Commands: /stop, /pause, /skip, /hint, /redirect
        </Typography>
      </Box>
    </Box>
  );
};

export default ChatContainer;
