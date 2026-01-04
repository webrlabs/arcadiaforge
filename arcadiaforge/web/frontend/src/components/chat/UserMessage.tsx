import React from 'react';
import { Box, Typography, Avatar } from '@mui/material';
import { User } from 'lucide-react';

interface UserMessageProps {
  content: string;
  timestamp: string;
  isResponse?: boolean;
}

const UserMessage: React.FC<UserMessageProps> = ({ content, timestamp, isResponse }) => {
  return (
    <Box
      sx={{
        display: 'flex',
        gap: 1.5,
        mb: 2,
        alignItems: 'flex-start',
        flexDirection: 'row-reverse',
      }}
    >
      {/* User Avatar */}
      <Avatar
        sx={{
          width: 32,
          height: 32,
          bgcolor: 'rgba(139, 92, 246, 0.15)',
          border: '1px solid rgba(139, 92, 246, 0.3)',
        }}
      >
        <User size={18} color="#8B5CF6" />
      </Avatar>

      {/* Message Bubble */}
      <Box
        sx={{
          maxWidth: 'calc(100% - 48px)',
        }}
      >
        <Box
          sx={{
            bgcolor: 'rgba(139, 92, 246, 0.12)',
            borderRadius: 2,
            borderTopRightRadius: 0,
            border: '1px solid rgba(139, 92, 246, 0.25)',
            p: 2,
          }}
        >
          {isResponse && (
            <Typography
              variant="caption"
              sx={{
                color: '#8B5CF6',
                fontWeight: 'bold',
                display: 'block',
                mb: 0.5,
                fontSize: '0.65rem',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Response
            </Typography>
          )}
          <Typography
            variant="body2"
            sx={{
              color: 'text.primary',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              lineHeight: 1.6,
            }}
          >
            {content}
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
            textAlign: 'right',
            opacity: 0.7,
          }}
        >
          {new Date(timestamp).toLocaleTimeString()}
        </Typography>
      </Box>
    </Box>
  );
};

export default UserMessage;
