import React from 'react';
import { Box, Typography } from '@mui/material';
import { Info, AlertTriangle, XCircle, CheckCircle2 } from 'lucide-react';

interface SystemMessageProps {
  message: string;
  level: 'info' | 'warning' | 'error' | 'success';
  timestamp: string;
}

const SystemMessage: React.FC<SystemMessageProps> = ({ message, level, timestamp }) => {
  const config = {
    info: {
      color: '#22D3EE',
      bg: 'rgba(34, 211, 238, 0.08)',
      border: 'rgba(34, 211, 238, 0.2)',
      Icon: Info,
    },
    warning: {
      color: '#FBBF24',
      bg: 'rgba(251, 191, 36, 0.08)',
      border: 'rgba(251, 191, 36, 0.2)',
      Icon: AlertTriangle,
    },
    error: {
      color: '#EF4444',
      bg: 'rgba(239, 68, 68, 0.08)',
      border: 'rgba(239, 68, 68, 0.2)',
      Icon: XCircle,
    },
    success: {
      color: '#22C55E',
      bg: 'rgba(34, 197, 94, 0.08)',
      border: 'rgba(34, 197, 94, 0.2)',
      Icon: CheckCircle2,
    },
  };

  const { color, bg, border, Icon } = config[level];

  return (
    <Box
      sx={{
        display: 'flex',
        justifyContent: 'center',
        mb: 2,
        px: 2,
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          py: 0.75,
          px: 2,
          bgcolor: bg,
          border: '1px solid',
          borderColor: border,
          borderRadius: 4,
          maxWidth: '80%',
        }}
      >
        <Icon size={14} color={color} />
        <Typography
          variant="caption"
          sx={{
            color: color,
            fontSize: '0.75rem',
          }}
        >
          {message}
        </Typography>
        <Typography
          variant="caption"
          sx={{
            color: 'text.secondary',
            fontSize: '0.6rem',
            opacity: 0.7,
            ml: 1,
          }}
        >
          {new Date(timestamp).toLocaleTimeString()}
        </Typography>
      </Box>
    </Box>
  );
};

export default SystemMessage;
