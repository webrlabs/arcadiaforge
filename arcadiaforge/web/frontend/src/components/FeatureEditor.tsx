import React, { useState, useEffect } from 'react';
import {
  Box, TextField, Button, IconButton, Typography,
  Select, MenuItem, FormControl, InputLabel
} from '@mui/material';
import { Trash2, Plus, Save, CheckCircle2, CircleDashed, AlertOctagon, ChevronLeft, ChevronRight } from 'lucide-react';
import { type FeatureUpdate } from '../services/api';

interface FeatureEditorProps {
  feature: any;
  onSave: (update: FeatureUpdate) => void;
  onCancel: () => void;
  onNext?: () => void;
  onPrevious?: () => void;
  hasNext?: boolean;
  hasPrevious?: boolean;
}

const FeatureEditor: React.FC<FeatureEditorProps> = ({ 
  feature, onSave, onCancel, 
  onNext, onPrevious, hasNext, hasPrevious 
}) => {
  const [description, setDescription] = useState(feature.description || '');
  const [steps, setSteps] = useState<string[]>([]);
  const [priority, setPriority] = useState(feature.priority || 3);

  useEffect(() => {
    try {
      if (typeof feature.steps === 'string') {
        setSteps(JSON.parse(feature.steps));
      } else if (Array.isArray(feature.steps)) {
        setSteps(feature.steps);
      }
    } catch (e) {
      setSteps([]);
    }
    
    // Also reset form state when feature changes (navigation)
    setDescription(feature.description || '');
    setPriority(feature.priority || 3);
  }, [feature]);

  const handleStepChange = (index: number, value: string) => {
    const newSteps = [...steps];
    newSteps[index] = value;
    setSteps(newSteps);
  };

  const addStep = () => {
    setSteps([...steps, '']);
  };

  const removeStep = (index: number) => {
    setSteps(steps.filter((_, i) => i !== index));
  };

  const handleSave = () => {
    onSave({
      description,
      steps,
      priority
    });
  };

  // Status Logic
  const isImplemented = feature.passes > 0;
  const isFailed = feature.failure_count > 0 && !isImplemented;
  
  let statusColor = '#9AA4B2'; // Grey (Pending)
  let statusBg = 'rgba(255, 255, 255, 0.05)';
  let statusText = 'Pending Implementation';
  let StatusIcon = CircleDashed;

  if (isImplemented) {
    statusColor = '#22C55E'; // Green
    statusBg = 'rgba(34, 197, 94, 0.1)';
    statusText = 'Implemented & Verified';
    StatusIcon = CheckCircle2;
  } else if (isFailed) {
    statusColor = '#EF4444'; // Red
    statusBg = 'rgba(239, 68, 68, 0.1)';
    statusText = 'Implementation Failed';
    StatusIcon = AlertOctagon;
  }

  return (
    <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 3 }}>
      
      {/* Header & Status Widget */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Box sx={{ display: 'flex', bgcolor: 'background.paper', borderRadius: 1, border: '1px solid', borderColor: 'divider' }}>
                <IconButton onClick={onPrevious} disabled={!hasPrevious} size="small" title="Previous Feature">
                    <ChevronLeft size={20} />
                </IconButton>
                <IconButton onClick={onNext} disabled={!hasNext} size="small" title="Next Feature">
                    <ChevronRight size={20} />
                </IconButton>
            </Box>
            <Typography variant="h6" color="primary" sx={{ ml: 1 }}>Feature #{feature.id}</Typography>
        </Box>
        
        <Box sx={{ 
          display: 'flex', 
          alignItems: 'center', 
          gap: 1.5, 
          px: 2, 
          py: 1, 
          borderRadius: 2, 
          bgcolor: statusBg,
          border: `1px solid ${statusColor}`
        }}>
           <StatusIcon size={20} color={statusColor} />
           <Typography variant="subtitle2" sx={{ color: statusColor, fontWeight: 'bold' }}>
              {statusText}
           </Typography>
        </Box>
      </Box>

      <TextField
        label="Description"
        fullWidth
        multiline
        rows={2}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />

      <FormControl fullWidth size="small">
        <InputLabel>Priority</InputLabel>
        <Select
          value={priority}
          label="Priority"
          onChange={(e) => setPriority(Number(e.target.value))}
        >
          <MenuItem value={1}>1 - Critical</MenuItem>
          <MenuItem value={2}>2 - High</MenuItem>
          <MenuItem value={3}>3 - Medium</MenuItem>
          <MenuItem value={4}>4 - Low</MenuItem>
        </Select>
      </FormControl>

      <Box>
        <Typography variant="subtitle2" gutterBottom>Steps</Typography>
        {steps.map((step, index) => (
          <Box key={index} sx={{ display: 'flex', gap: 1, mb: 1 }}>
            <TextField
              fullWidth
              size="small"
              value={step}
              onChange={(e) => handleStepChange(index, e.target.value)}
              placeholder={`Step ${index + 1}`}
            />
            <IconButton onClick={() => removeStep(index)} color="error" size="small">
              <Trash2 size={18} />
            </IconButton>
          </Box>
        ))}
        <Button 
          startIcon={<Plus size={16} />} 
          onClick={addStep} 
          size="small" 
          sx={{ mt: 1 }}
        >
          Add Step
        </Button>
      </Box>

      <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end', mt: 2 }}>
        <Button onClick={onCancel} color="inherit">Close</Button>
        <Button 
          onClick={handleSave} 
          variant="contained" 
          startIcon={<Save size={16} />}
        >
          Save Changes
        </Button>
      </Box>
    </Box>
  );
};

export default FeatureEditor;
