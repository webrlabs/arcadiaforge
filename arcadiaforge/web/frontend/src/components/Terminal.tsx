import React, { useEffect, useState, useRef } from 'react';
import { Box, Typography, TextField, IconButton, Paper, Divider } from '@mui/material';
import { Send, Terminal as TerminalIcon, CheckCircle2, AlertCircle, Zap, Info } from 'lucide-react';
import { WS_BASE } from '../services/api';
import ControlPanel from './ControlPanel';

interface LogEvent {
  timestamp: string;
  type: 'log' | 'tool' | 'feedback_ack' | 'system';
  data: any;
}

interface TerminalProps {
  projectId: string;
}

const Terminal: React.FC<TerminalProps> = ({ projectId }) => {
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [connected, setConnected] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    // Initialize WebSocket
    const socket = new WebSocket(`${WS_BASE}/run/${projectId}`);
    ws.current = socket;

    socket.onopen = () => {
      setConnected(true);
    };

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setEvents((prev) => [...prev, data]);
    };

    socket.onclose = () => {
      setConnected(false);
    };

    return () => {
      socket.close();
    };
  }, [projectId]);

  useEffect(() => {
    // Scroll to bottom when events change
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events]);

  const sendCommand = (cmd: string) => {
    if (ws.current && connected) {
      ws.current.send(cmd);
    }
  };

  const handleSend = () => {
    if (inputValue.trim()) {
      sendCommand(inputValue);
      setInputValue('');
    }
  };

  const renderEvent = (event: LogEvent, index: number) => {
    const { type, data } = event;
    const timestamp = new Date(event.timestamp).toLocaleTimeString([], { hour12: false });

    switch (type) {
      case 'tool':
        return (
          <Box key={index} sx={{ mb: 1, display: 'flex', alignItems: 'flex-start' }}>
            <Zap size={14} color="#F59E0B" style={{ marginTop: '4px', marginRight: '8px', flexShrink: 0 }} />
            <Box>
              <Typography variant="body2" sx={{ color: 'secondary.main', fontWeight: 'bold', display: 'inline' }}>
                {data.name}
              </Typography>
              <Typography variant="body2" sx={{ color: 'text.secondary', display: 'inline', ml: 1 }}>
                ({data.summary})
              </Typography>
              {data.result === 'done' ? (
                <CheckCircle2 size={12} color="#22C55E" style={{ marginLeft: '6px', display: 'inline' }} />
              ) : data.result === 'error' ? (
                <AlertCircle size={12} color="#EF4444" style={{ marginLeft: '6px', display: 'inline' }} />
              ) : null}
            </Box>
          </Box>
        );

      case 'log':
        const color = data.style === 'success' ? '#22C55E' : 
                      data.style === 'error' ? '#EF4444' : 
                      data.style === 'warning' ? '#FBBF24' : 
                      data.style === 'info' ? '#22D3EE' : 'inherit';
        return (
          <Typography key={index} variant="body2" sx={{ color, mb: 0.5, fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
            {data.message}
          </Typography>
        );
      
      case 'feedback_ack':
        return (
          <Box key={index} sx={{ mb: 1, py: 0.5, px: 1, bgcolor: 'rgba(34, 211, 238, 0.1)', borderRadius: 1, borderLeft: '3px solid #22D3EE' }}>
            <Typography variant="caption" sx={{ color: 'primary.main', fontWeight: 'bold', display: 'block' }}>
              Feedback Received [{data.type}]
            </Typography>
            <Typography variant="body2">{data.message}</Typography>
          </Box>
        );

      default:
        return null;
    }
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', bgcolor: '#121212' }}>
      {/* Control Panel Header */}
      <ControlPanel 
        isConnected={connected}
        onStop={() => sendCommand('/stop')}
        onPause={() => sendCommand('/pause')}
        onSkip={() => sendCommand('/skip')}
        onClear={() => setEvents([])}
      />

      <Box 
        ref={scrollRef}
        sx={{ 
          flexGrow: 1, 
          p: 2, 
          overflowY: 'auto', 
          fontFamily: 'monospace',
          display: 'flex',
          flexDirection: 'column'
        }}
      >
        {events.map((ev, i) => renderEvent(ev, i))}
      </Box>

      <Box sx={{ p: 2, borderTop: '1px solid', borderColor: 'divider' }}>
        <TextField
          fullWidth
          size="small"
          placeholder="Type feedback or /help..."
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && handleSend()}
          InputProps={{
            endAdornment: (
              <IconButton size="small" onClick={handleSend} color="primary">
                <Send size={18} />
              </IconButton>
            ),
            sx: { fontFamily: 'monospace', bgcolor: 'background.paper' }
          }}
        />
      </Box>
    </Box>
  );
};

export default Terminal;