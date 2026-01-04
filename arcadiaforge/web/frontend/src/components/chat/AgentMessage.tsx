import React from 'react';
import { Box, Typography, Avatar, useTheme } from '@mui/material';
import { Bot } from 'lucide-react';

interface AgentMessageProps {
  content: string;
  timestamp: string;
  isStreaming?: boolean;
}

const AgentMessage: React.FC<AgentMessageProps> = ({ content, timestamp, isStreaming }) => {
  const theme = useTheme();
  const isDark = theme.palette.mode === 'dark';
  return (
    <Box
      sx={{
        display: 'flex',
        gap: 1.5,
        mb: 2,
        alignItems: 'flex-start',
      }}
    >
      {/* Agent Avatar */}
      <Avatar
        sx={{
          width: 32,
          height: 32,
          bgcolor: 'rgba(34, 211, 238, 0.15)',
          border: '1px solid rgba(34, 211, 238, 0.3)',
        }}
      >
        <Bot size={18} color="#22D3EE" />
      </Avatar>

      {/* Message Bubble */}
      <Box
        sx={{
          flex: 1,
          maxWidth: 'calc(100% - 48px)',
        }}
      >
        <Box
          sx={{
            bgcolor: 'rgba(34, 211, 238, 0.08)',
            borderRadius: 2,
            borderTopLeftRadius: 0,
            border: '1px solid rgba(34, 211, 238, 0.2)',
            p: 2,
            position: 'relative',
          }}
        >
          <Typography
            variant="body2"
            sx={{
              color: 'text.primary',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontFamily: 'inherit',
              lineHeight: 1.6,
              '& code': {
                bgcolor: isDark ? 'rgba(0, 0, 0, 0.3)' : 'rgba(0, 0, 0, 0.06)',
                px: 0.5,
                py: 0.25,
                borderRadius: 0.5,
                fontFamily: 'monospace',
                fontSize: '0.85em',
              },
            }}
          >
            {content}
            {isStreaming && (
              <Box
                component="span"
                sx={{
                  display: 'inline-block',
                  width: 8,
                  height: 16,
                  bgcolor: '#22D3EE',
                  ml: 0.5,
                  animation: 'blink 1s infinite',
                  '@keyframes blink': {
                    '0%, 50%': { opacity: 1 },
                    '51%, 100%': { opacity: 0 },
                  },
                }}
              />
            )}
          </Typography>
        </Box>

        {/* Timestamp */}
        <Typography
          variant="caption"
          sx={{
            color: 'text.secondary',
            fontSize: '0.65rem',
            mt: 0.5,
            display: 'block',
            opacity: 0.7,
          }}
        >
          {new Date(timestamp).toLocaleTimeString()}
        </Typography>
      </Box>
    </Box>
  );
};

export default AgentMessage;
