import React from 'react';
import { Box, Typography, Chip, IconButton, Tooltip } from '@mui/material';
import { CheckCircle2, CircleDashed, AlertOctagon, Edit2, ListChecks } from 'lucide-react';

interface Feature {
  id: number;
  index: number;
  category: string;
  description: string;
  steps: string | string[];
  passes: number;
  failure_count: number;
  priority?: number;
  blocked_by?: string;
}

interface FeatureCardProps {
  feature: Feature;
  onEdit: (feature: Feature) => void;
}

const FeatureCard: React.FC<FeatureCardProps> = ({ feature, onEdit }) => {
  // Parse steps if needed
  let stepsArray: string[] = [];
  try {
    if (typeof feature.steps === 'string') {
      stepsArray = JSON.parse(feature.steps);
    } else if (Array.isArray(feature.steps)) {
      stepsArray = feature.steps;
    }
  } catch (e) {
    stepsArray = [];
  }

  // Status Logic
  const isImplemented = feature.passes > 0;
  const isFailed = feature.failure_count > 0 && !isImplemented;
  const isBlocked = !!feature.blocked_by;

  let statusColor = '#9AA4B2'; // Grey (Pending)
  let statusBg = 'rgba(255, 255, 255, 0.03)';
  let statusText = 'Pending';
  let StatusIcon = CircleDashed;
  let borderColor = 'rgba(255, 255, 255, 0.08)';

  if (isImplemented) {
    statusColor = '#22C55E'; // Green
    statusBg = 'rgba(34, 197, 94, 0.08)';
    statusText = 'Implemented';
    StatusIcon = CheckCircle2;
    borderColor = 'rgba(34, 197, 94, 0.3)';
  } else if (isFailed) {
    statusColor = '#EF4444'; // Red
    statusBg = 'rgba(239, 68, 68, 0.08)';
    statusText = 'Failed';
    StatusIcon = AlertOctagon;
    borderColor = 'rgba(239, 68, 68, 0.3)';
  } else if (isBlocked) {
    statusColor = '#FBBF24'; // Yellow/Warning
    statusBg = 'rgba(251, 191, 36, 0.08)';
    statusText = 'Blocked';
    borderColor = 'rgba(251, 191, 36, 0.3)';
  }

  // Category colors
  const categoryColor = feature.category === 'functional' ? '#22D3EE' : '#F59E0B';
  const categoryBg = feature.category === 'functional'
    ? 'rgba(34, 211, 238, 0.15)'
    : 'rgba(245, 158, 11, 0.15)';

  // Priority badge
  const getPriorityLabel = (priority?: number) => {
    switch (priority) {
      case 1: return { label: 'P1', color: '#EF4444' };
      case 2: return { label: 'P2', color: '#F59E0B' };
      case 3: return { label: 'P3', color: '#22D3EE' };
      case 4: return { label: 'P4', color: '#9AA4B2' };
      default: return { label: 'P3', color: '#22D3EE' };
    }
  };

  const priority = getPriorityLabel(feature.priority);

  return (
    <Box
      sx={{
        bgcolor: statusBg,
        border: '1px solid',
        borderColor: borderColor,
        borderRadius: 2,
        p: 2,
        display: 'flex',
        flexDirection: 'column',
        gap: 1.5,
        transition: 'all 0.2s ease',
        cursor: 'pointer',
        position: 'relative',
        '&:hover': {
          borderColor: statusColor,
          transform: 'translateY(-2px)',
          boxShadow: `0 4px 20px ${statusBg}`,
        },
      }}
      onClick={() => onEdit(feature)}
    >
      {/* Header Row: ID, Category, Priority, Status */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          {/* Feature ID */}
          <Typography
            variant="caption"
            sx={{
              fontWeight: 'bold',
              color: 'text.secondary',
              bgcolor: 'rgba(255,255,255,0.05)',
              px: 1,
              py: 0.25,
              borderRadius: 1,
              fontFamily: 'monospace',
            }}
          >
            #{feature.id}
          </Typography>

          {/* Category Chip */}
          <Chip
            label={feature.category}
            size="small"
            sx={{
              height: 20,
              fontSize: '0.65rem',
              fontWeight: 'bold',
              textTransform: 'uppercase',
              bgcolor: categoryBg,
              color: categoryColor,
              border: 'none',
              '& .MuiChip-label': { px: 1 },
            }}
          />

          {/* Priority Badge */}
          <Typography
            variant="caption"
            sx={{
              fontWeight: 'bold',
              color: priority.color,
              fontSize: '0.65rem',
            }}
          >
            {priority.label}
          </Typography>
        </Box>

        {/* Status Icon */}
        <Tooltip title={statusText} placement="top">
          <Box sx={{ display: 'flex', alignItems: 'center' }}>
            <StatusIcon size={18} color={statusColor} />
          </Box>
        </Tooltip>
      </Box>

      {/* Description */}
      <Tooltip title={feature.description} placement="top" enterDelay={500}>
        <Typography
          variant="body2"
          sx={{
            color: 'text.primary',
            fontSize: '0.85rem',
            lineHeight: 1.4,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            minHeight: '2.8em',
          }}
        >
          {feature.description}
        </Typography>
      </Tooltip>

      {/* Footer: Steps count and Edit button */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mt: 'auto' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, color: 'text.secondary' }}>
          <ListChecks size={14} />
          <Typography variant="caption" sx={{ fontSize: '0.7rem' }}>
            {stepsArray.length} step{stepsArray.length !== 1 ? 's' : ''}
          </Typography>
        </Box>

        <IconButton
          size="small"
          onClick={(e) => {
            e.stopPropagation();
            onEdit(feature);
          }}
          sx={{
            color: 'text.secondary',
            bgcolor: 'rgba(255,255,255,0.05)',
            '&:hover': {
              bgcolor: 'rgba(34, 211, 238, 0.2)',
              color: 'primary.main',
            },
          }}
        >
          <Edit2 size={14} />
        </IconButton>
      </Box>
    </Box>
  );
};

export default FeatureCard;
