import React, { useState, useEffect } from 'react';
import { 
  Dialog, DialogTitle, DialogContent, DialogActions, 
  Button, TextField, CircularProgress, Alert, Box 
} from '@mui/material';
import { Save } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';

interface AppSpecEditorProps {
  projectId: string;
  open: boolean;
  onClose: () => void;
}

const AppSpecEditor: React.FC<AppSpecEditorProps> = ({ projectId, open, onClose }) => {
  const [content, setContent] = useState('');
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ['spec', projectId],
    queryFn: () => api.getProjectSpec(projectId),
    enabled: open // Only fetch when open
  });

  useEffect(() => {
    if (data) {
      setContent(data.content);
    }
  }, [data]);

  const saveMutation = useMutation({
    mutationFn: () => api.saveProjectSpec(projectId, content),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['spec', projectId] });
      onClose();
    }
  });

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth scroll="paper">
      <DialogTitle sx={{ fontWeight: 'bold' }}>Application Specification</DialogTitle>
      <DialogContent dividers>
        {isLoading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
            <CircularProgress />
          </Box>
        ) : error ? (
          <Alert severity="error">Failed to load app_spec.txt</Alert>
        ) : (
          <TextField
            multiline
            fullWidth
            minRows={15}
            maxRows={25}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            InputProps={{
              sx: { fontFamily: 'monospace', fontSize: '0.875rem' }
            }}
            placeholder="Enter application requirements..."
          />
        )}
      </DialogContent>
      <DialogActions sx={{ p: 2 }}>
        <Button onClick={onClose} color="inherit">Cancel</Button>
        <Button 
          onClick={() => saveMutation.mutate()} 
          variant="contained" 
          startIcon={<Save size={16} />}
          disabled={saveMutation.isPending || isLoading}
        >
          {saveMutation.isPending ? 'Saving...' : 'Save Changes'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default AppSpecEditor;