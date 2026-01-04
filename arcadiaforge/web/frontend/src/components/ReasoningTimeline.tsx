import React, { useMemo } from 'react';
import { useQueries } from '@tanstack/react-query';
import { Box, Typography, Paper, Chip, CircularProgress, Alert } from '@mui/material';
import { GitMerge, Lightbulb, Flag, CheckCircle2, HelpCircle } from 'lucide-react';
import { api } from '../services/api';

interface TimelineEvent {
  type: 'decision' | 'hypothesis' | 'checkpoint';
  timestamp: string;
  data: any;
}

interface ReasoningTimelineProps {
  projectId: string;
}

const ReasoningTimeline: React.FC<ReasoningTimelineProps> = ({ projectId }) => {
  const results = useQueries({
    queries: [
      { queryKey: ['table', projectId, 'decisions'], queryFn: () => api.getTableData(projectId, 'decisions', 100) },
      { queryKey: ['table', projectId, 'hypotheses'], queryFn: () => api.getTableData(projectId, 'hypotheses', 100) },
      { queryKey: ['table', projectId, 'checkpoints'], queryFn: () => api.getTableData(projectId, 'checkpoints', 100) }
    ]
  });

  const isLoading = results.some(r => r.isLoading);
  const isError = results.some(r => r.isError);

  const events = useMemo(() => {
    if (isLoading || isError) return [];

    const decisions = (results[0].data || []).map((d: any) => ({ type: 'decision', timestamp: d.timestamp, data: d }));
    const hypotheses = (results[1].data || []).map((h: any) => ({ type: 'hypothesis', timestamp: h.created_at || h.timestamp, data: h }));
    const checkpoints = (results[2].data || []).map((c: any) => ({ type: 'checkpoint', timestamp: c.timestamp, data: c }));

    const allEvents: TimelineEvent[] = [...decisions, ...hypotheses, ...checkpoints];
    
    // Sort descending (newest first)
    return allEvents.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  }, [results, isLoading, isError]);

  if (isLoading) return <Box sx={{ p: 4, display: 'flex', justifyContent: 'center' }}><CircularProgress /></Box>;
  if (isError) return <Alert severity="error">Failed to load reasoning data</Alert>;
  if (events.length === 0) return <Typography color="text.secondary" sx={{ p: 4, textAlign: 'center' }}>No reasoning events recorded yet.</Typography>;

  return (
    <Box sx={{ p: 2, maxWidth: 800, mx: 'auto' }}>
      {events.map((event, index) => (
        <Box key={index} sx={{ display: 'flex', mb: 3 }}>
          {/* Timeline Line & Icon */}
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', mr: 2 }}>
            <Box sx={{ 
              width: 36, height: 36, borderRadius: '50%', 
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              bgcolor: getEventColor(event.type, true),
              color: getEventColor(event.type),
              border: `2px solid ${getEventColor(event.type)}`,
              zIndex: 1
            }}>
              {getEventIcon(event.type)}
            </Box>
            {index < events.length - 1 && (
              <Box sx={{ width: 2, flexGrow: 1, bgcolor: 'divider', my: 1 }} />
            )}
          </Box>

          {/* Content Card */}
          <Paper sx={{ flexGrow: 1, p: 2, border: '1px solid', borderColor: 'divider' }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Chip 
                  label={event.type.toUpperCase()} 
                  size="small" 
                  sx={{ 
                    bgcolor: getEventColor(event.type, true), 
                    color: getEventColor(event.type),
                    fontWeight: 'bold',
                    fontSize: '0.7rem',
                    height: 20
                  }} 
                />
                <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                  {new Date(event.timestamp).toLocaleString()}
                </Typography>
              </Box>
              <Typography variant="caption" color="text.secondary">
                Session #{event.data.session_id}
              </Typography>
            </Box>

            {renderEventContent(event)}
          </Paper>
        </Box>
      ))}
    </Box>
  );
};

// Helper Functions

function getEventColor(type: string, bg = false) {
  const colors = {
    decision: '#22D3EE',   // Cyan
    hypothesis: '#F59E0B', // Orange
    checkpoint: '#22C55E'  // Green
  };
  const color = colors[type as keyof typeof colors] || '#9AA4B2';
  return bg ? `${color}20` : color; // Add transparency for bg
}

function getEventIcon(type: string) {
  switch (type) {
    case 'decision': return <GitMerge size={18} />;
    case 'hypothesis': return <Lightbulb size={18} />;
    case 'checkpoint': return <Flag size={18} />;
    default: return <HelpCircle size={18} />;
  }
}

function renderEventContent(event: TimelineEvent) {
  const { data } = event;

  if (event.type === 'decision') {
    return (
      <>
        <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 0.5 }}>
          {data.decision_type.replace(/_/g, ' ')}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {data.context}
        </Typography>
        <Box sx={{ p: 1.5, bgcolor: 'background.default', borderRadius: 1, borderLeft: '3px solid #22D3EE' }}>
          <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'primary.main' }}>
            Selected: {data.choice}
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
            Rationale: {data.rationale}
          </Typography>
        </Box>
      </>
    );
  }

  if (event.type === 'hypothesis') {
    return (
      <>
        <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 0.5 }}>
          {data.hypothesis_type}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Observed: {data.observation}
        </Typography>
        <Box sx={{ p: 1.5, bgcolor: 'background.default', borderRadius: 1, borderLeft: '3px solid #F59E0B' }}>
          <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'secondary.main' }}>
            Hypothesis: {data.hypothesis}
          </Typography>
          <Box sx={{ mt: 1, display: 'flex', gap: 1 }}>
             <Chip label={data.status} size="small" variant="outlined" sx={{ height: 20, fontSize: '0.7rem' }} />
             <Chip label={`Conf: ${(data.confidence * 100).toFixed(0)}%`} size="small" variant="outlined" sx={{ height: 20, fontSize: '0.7rem' }} />
          </Box>
        </Box>
      </>
    );
  }

  if (event.type === 'checkpoint') {
    return (
      <>
        <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 0.5 }}>
          {data.trigger}
        </Typography>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', color: 'success.main' }}>
            <CheckCircle2 size={16} style={{ marginRight: 6 }} />
            <Typography variant="body2" fontWeight="bold">
              {data.features_passing} / {data.features_total} Passing
            </Typography>
          </Box>
          <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
            Git: {data.git_commit?.substring(0, 7) || 'N/A'}
          </Typography>
        </Box>
        {data.human_note && (
           <Typography variant="body2" sx={{ mt: 1, fontStyle: 'italic', color: 'text.secondary' }}>
             "{data.human_note}"
           </Typography>
        )}
      </>
    );
  }
}

export default ReasoningTimeline;
