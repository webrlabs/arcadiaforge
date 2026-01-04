import React, { useState } from 'react';
import { Box, Typography, Collapse, IconButton, useTheme } from '@mui/material';
import {
  Wrench,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  XCircle,
  Loader2,
  FileText,
  Terminal,
  Edit3,
  Search,
  Globe
} from 'lucide-react';
import { API_BASE } from '../../services/api';

interface ToolCallCardProps {
  toolId: string;
  name: string;
  summary: string;
  status: 'running' | 'completed' | 'failed';
  input?: Record<string, unknown>;
  result?: string;
  duration?: number;
  imageUrl?: string;
  defaultExpanded?: boolean;
}

const getToolIcon = (name: string) => {
  const lowerName = name.toLowerCase();
  if (lowerName.includes('read') || lowerName.includes('file')) return FileText;
  if (lowerName.includes('bash') || lowerName.includes('terminal') || lowerName.includes('exec')) return Terminal;
  if (lowerName.includes('edit') || lowerName.includes('write')) return Edit3;
  if (lowerName.includes('search') || lowerName.includes('grep') || lowerName.includes('glob')) return Search;
  if (lowerName.includes('web') || lowerName.includes('fetch')) return Globe;
  return Wrench;
};

const ToolCallCard: React.FC<ToolCallCardProps> = ({
  name,
  summary,
  status,
  input,
  result,
  duration,
  imageUrl,
  defaultExpanded = false,
}) => {
  const theme = useTheme();
  const isDark = theme.palette.mode === 'dark';
  const [expanded, setExpanded] = useState(defaultExpanded);

  const statusConfig = {
    running: {
      color: '#F59E0B',
      bg: 'rgba(245, 158, 11, 0.1)',
      border: 'rgba(245, 158, 11, 0.3)',
      Icon: Loader2,
      iconProps: { className: 'spin' },
    },
    completed: {
      color: '#22C55E',
      bg: 'rgba(34, 197, 94, 0.08)',
      border: 'rgba(34, 197, 94, 0.25)',
      Icon: CheckCircle2,
      iconProps: {},
    },
    failed: {
      color: '#EF4444',
      bg: 'rgba(239, 68, 68, 0.1)',
      border: 'rgba(239, 68, 68, 0.3)',
      Icon: XCircle,
      iconProps: {},
    },
  };

  const config = statusConfig[status];
  const ToolIcon = getToolIcon(name);
  const StatusIcon = config.Icon;
  const hasDetails = input || result || imageUrl;
  const resolvedImageUrl = imageUrl
    ? (imageUrl.startsWith('http') || imageUrl.startsWith('data:') ? imageUrl : `${API_BASE}/${imageUrl}`)
    : '';

  return (
    <Box
      sx={{
        mb: 1.5,
        ml: 5,
        mr: 2,
        '@keyframes spin': {
          from: { transform: 'rotate(0deg)' },
          to: { transform: 'rotate(360deg)' },
        },
        '& .spin': {
          animation: 'spin 1s linear infinite',
        },
      }}
    >
      <Box
        onClick={() => hasDetails && setExpanded(!expanded)}
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          p: 1,
          pl: 1.5,
          bgcolor: config.bg,
          border: '1px solid',
          borderColor: config.border,
          borderRadius: 1.5,
          cursor: hasDetails ? 'pointer' : 'default',
          transition: 'all 0.2s ease',
          '&:hover': hasDetails ? {
            borderColor: config.color,
          } : {},
        }}
      >
        {/* Tool Icon */}
        <Box
          sx={{
            width: 24,
            height: 24,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            bgcolor: isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)',
            borderRadius: 0.75,
          }}
        >
          <ToolIcon size={14} color={config.color} />
        </Box>

        {/* Tool Name and Summary */}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography
            variant="body2"
            sx={{
              color: config.color,
              fontWeight: 600,
              fontSize: '0.8rem',
              display: 'inline',
            }}
          >
            {name}
          </Typography>
          <Typography
            variant="body2"
            sx={{
              color: 'text.secondary',
              fontSize: '0.75rem',
              ml: 1,
              display: 'inline',
              opacity: 0.8,
            }}
          >
            {summary}
          </Typography>
        </Box>

        {/* Duration */}
        {duration !== undefined && (
          <Typography
            variant="caption"
            sx={{
              color: 'text.secondary',
              fontSize: '0.65rem',
              opacity: 0.7,
            }}
          >
            {duration}ms
          </Typography>
        )}

        {/* Status Icon */}
        <StatusIcon size={16} color={config.color} {...config.iconProps} />

        {/* Expand Button */}
        {hasDetails && (
          <IconButton
            size="small"
            sx={{
              p: 0.25,
              color: 'text.secondary',
            }}
          >
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </IconButton>
        )}
      </Box>

      {/* Expanded Details */}
      <Collapse in={expanded}>
        <Box
          sx={{
            mt: 0.5,
            ml: 2,
            p: 1.5,
            bgcolor: isDark ? 'rgba(0, 0, 0, 0.2)' : 'rgba(0, 0, 0, 0.03)',
            borderRadius: 1,
            border: '1px solid',
            borderColor: isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.08)',
          }}
        >
          {input && (
            <Box sx={{ mb: result ? 1.5 : 0 }}>
              <Typography
                variant="caption"
                sx={{
                  color: 'text.secondary',
                  fontWeight: 'bold',
                  display: 'block',
                  mb: 0.5,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  fontSize: '0.6rem',
                }}
              >
                Input
              </Typography>
              <Typography
                variant="body2"
                component="pre"
                sx={{
                  color: 'text.primary',
                  fontFamily: 'monospace',
                  fontSize: '0.7rem',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                  m: 0,
                  maxHeight: 150,
                  overflow: 'auto',
                }}
              >
                {JSON.stringify(input, null, 2)}
              </Typography>
            </Box>
          )}

          {result && (
            <Box>
              <Typography
                variant="caption"
                sx={{
                  color: 'text.secondary',
                  fontWeight: 'bold',
                  display: 'block',
                  mb: 0.5,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  fontSize: '0.6rem',
                }}
              >
                Result
              </Typography>
              <Typography
                variant="body2"
                component="pre"
                sx={{
                  color: status === 'failed' ? '#EF4444' : 'text.primary',
                  fontFamily: 'monospace',
                  fontSize: '0.7rem',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                  m: 0,
                  maxHeight: 200,
                  overflow: 'auto',
                }}
              >
                {result}
              </Typography>
            </Box>
          )}

          {resolvedImageUrl && (
            <Box sx={{ mt: result ? 1.5 : 0 }}>
              <Typography
                variant="caption"
                sx={{
                  color: 'text.secondary',
                  fontWeight: 'bold',
                  display: 'block',
                  mb: 0.5,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  fontSize: '0.6rem',
                }}
              >
                Screenshot
              </Typography>
              <Box
                component="img"
                src={resolvedImageUrl}
                alt="Puppeteer screenshot"
                sx={{
                  width: '100%',
                  maxHeight: 280,
                  objectFit: 'contain',
                  borderRadius: 1,
                  border: '1px solid',
                  borderColor: isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.1)',
                  bgcolor: isDark ? 'rgba(0, 0, 0, 0.2)' : 'rgba(0, 0, 0, 0.03)',
                }}
              />
            </Box>
          )}
        </Box>
      </Collapse>
    </Box>
  );
};

export default ToolCallCard;
