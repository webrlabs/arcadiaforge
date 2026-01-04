import React from 'react';
import { Box, IconButton, Tooltip, Divider } from '@mui/material';
import { Pause, Square, Trash2, SkipForward } from 'lucide-react';

interface ControlPanelProps {
  onStop: () => void;
  onPause: () => void;
  onClear: () => void;
  onSkip: () => void;
  isConnected: boolean;
  isRunning?: boolean;
}

const ControlPanel: React.FC<ControlPanelProps> = ({ 
  onStop, onPause, onClear, onSkip, isConnected 
}) => {
  return (
    <Box sx={{ 
      p: 1, 
      display: 'flex', 
      alignItems: 'center', 
      gap: 1,
      borderBottom: '1px solid', 
      borderColor: 'divider',
      bgcolor: 'background.paper'
    }}>
      <Tooltip title="Pause Agent">
        <span>
          <IconButton onClick={onPause} disabled={!isConnected} color="warning" size="small">
            <Pause size={18} />
          </IconButton>
        </span>
      </Tooltip>

      <Tooltip title="Stop Session">
        <span>
          <IconButton onClick={onStop} disabled={!isConnected} color="error" size="small">
            <Square size={18} fill="currentColor" />
          </IconButton>
        </span>
      </Tooltip>

      <Tooltip title="Skip Current Feature">
        <span>
          <IconButton onClick={onSkip} disabled={!isConnected} size="small">
            <SkipForward size={18} />
          </IconButton>
        </span>
      </Tooltip>

      <Divider orientation="vertical" flexItem variant="middle" sx={{ mx: 1 }} />

      <Tooltip title="Clear Terminal">
        <IconButton onClick={onClear} size="small">
          <Trash2 size={18} />
        </IconButton>
      </Tooltip>
      
      <Box sx={{ flexGrow: 1 }} />
      
      {/* Connection Status Indicator */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1 }}>
        <Box sx={{ 
          width: 8, height: 8, borderRadius: '50%', 
          bgcolor: isConnected ? 'success.main' : 'error.main',
          boxShadow: isConnected ? '0 0 8px #22C55E' : 'none'
        }} />
      </Box>
    </Box>
  );
};

export default ControlPanel;
