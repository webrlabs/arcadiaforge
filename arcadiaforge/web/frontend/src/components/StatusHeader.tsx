import React, { useEffect, useState } from 'react';
import { Box, Typography } from '@mui/material';
import { Clock, CheckCircle2 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';

interface StatusHeaderProps {
  projectId: string;
}

const StatusHeader: React.FC<StatusHeaderProps> = ({ projectId }) => {
  // We can use the 'sessions' table to get the latest session status
  const { data: sessions } = useQuery({
    queryKey: ['table', projectId, 'sessions'],
    queryFn: () => api.getTableData(projectId, 'sessions', 1, 0, 'desc'),
    refetchInterval: 2000
  });

  // We can use the 'features' table to count progress
  const { data: features } = useQuery({
    queryKey: ['table', projectId, 'features'],
    queryFn: () => api.getTableData(projectId, 'features', 1000), // Get all features
    refetchInterval: 5000
  });

  const [elapsedTime, setElapsedTime] = useState('00:00:00');
  
  const activeSession = sessions && sessions.length > 0 ? sessions[0] : null;
  const sessionStatus = (activeSession?.status || '').toString().toLowerCase();
  const isRunning = sessionStatus === 'running' || (!activeSession?.end_time && !!activeSession?.start_time);

  let statusLabel = 'IDLE';
  let statusColor = '#9AA4B2';
  if (activeSession) {
    if (isRunning) {
      statusLabel = 'RUNNING';
      statusColor = '#22C55E';
    } else if (sessionStatus) {
      statusLabel = sessionStatus.replace(/_/g, ' ').toUpperCase();
      statusColor = ['failed', 'error', 'intervention', 'cyclic', 'no_progress'].includes(sessionStatus) ? '#EF4444' : '#F59E0B';
    }
  }

  // Calculate stats
  const totalFeatures = features ? features.length : 0;
  const completedFeatures = features ? features.filter((f: any) => f.passes).length : 0;
  
  useEffect(() => {
    let interval: any;
    
    if (isRunning && activeSession?.start_time) {
      interval = setInterval(() => {
        const start = new Date(activeSession.start_time).getTime();
        const now = new Date().getTime();
        const diff = Math.max(0, now - start);
        
        const hours = Math.floor(diff / 3600000).toString().padStart(2, '0');
        const minutes = Math.floor((diff % 3600000) / 60000).toString().padStart(2, '0');
        const seconds = Math.floor((diff % 60000) / 1000).toString().padStart(2, '0');
        
        setElapsedTime(`${hours}:${minutes}:${seconds}`);
      }, 1000);
    } else {
      setElapsedTime('00:00:00');
    }

    return () => clearInterval(interval);
  }, [isRunning, activeSession?.start_time]);

  return (
    <Box sx={{ display: 'flex', gap: 3, mr: 4 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Clock size={14} color={isRunning ? "#22D3EE" : "#9AA4B2"} />
        <Typography variant="caption" sx={{ color: isRunning ? "primary.main" : "text.secondary", fontFamily: 'monospace' }}>
          {elapsedTime}
        </Typography>
      </Box>
      
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Box
          sx={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            bgcolor: statusColor,
            boxShadow: isRunning ? `0 0 6px ${statusColor}` : 'none',
          }}
        />
        <Typography variant="caption" sx={{ color: statusColor, fontWeight: 'bold' }}>
          {statusLabel}
        </Typography>
      </Box>
      
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <CheckCircle2 size={14} color={completedFeatures === totalFeatures && totalFeatures > 0 ? "#22C55E" : "#9AA4B2"} />
        <Typography variant="caption" color="text.secondary">
          {completedFeatures} / {totalFeatures} Features
        </Typography>
      </Box>
    </Box>
  );
};

export default StatusHeader;
