import React from 'react';
import { Box, Typography, Avatar } from '@mui/material';
import { Bot } from 'lucide-react';

const ThinkingIndicator: React.FC = () => {
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

      {/* Thinking Bubble */}
      <Box
        sx={{
          bgcolor: 'rgba(34, 211, 238, 0.05)',
          borderRadius: 2,
          borderTopLeftRadius: 0,
          border: '1px solid rgba(34, 211, 238, 0.15)',
          py: 1.5,
          px: 2,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
        }}
      >
        <Typography
          variant="body2"
          sx={{
            color: 'text.secondary',
            fontStyle: 'italic',
            fontSize: '0.85rem',
          }}
        >
          Thinking
        </Typography>

        {/* Animated Dots */}
        <Box
          sx={{
            display: 'flex',
            gap: 0.5,
            alignItems: 'center',
          }}
        >
          {[0, 1, 2].map((i) => (
            <Box
              key={i}
              sx={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                bgcolor: '#22D3EE',
                animation: 'bounce 1.4s ease-in-out infinite',
                animationDelay: `${i * 0.16}s`,
                '@keyframes bounce': {
                  '0%, 80%, 100%': {
                    transform: 'scale(0.6)',
                    opacity: 0.4,
                  },
                  '40%': {
                    transform: 'scale(1)',
                    opacity: 1,
                  },
                },
              }}
            />
          ))}
        </Box>
      </Box>
    </Box>
  );
};

export default ThinkingIndicator;
