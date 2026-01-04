import React, { useState } from 'react';
import {
  Container, Typography, Box, Button, Grid, Card, CardContent,
  CardActionArea, Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, CircularProgress, Alert
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type Project } from '../services/api';
import { PlusCircle, Folder, Database, Upload, X } from 'lucide-react';
import ThemeToggle from '../components/ThemeToggle';

const LandingPage: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [isModalOpen, setModalOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [appSpec, setAppSpec] = useState('');
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) readFile(file);
  };

  const readFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      if (e.target?.result) {
        setAppSpec(e.target.result as string);
      }
    };
    reader.readAsText(file);
  };

  const { data: projects, isLoading, error } = useQuery({
    queryKey: ['projects'],
    queryFn: api.getProjects
  });

  const createMutation = useMutation({
    mutationFn: () => api.createProject(newProjectName, appSpec),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      setModalOpen(false);
      navigate(`/project/${data.id}`);
    },
    onError: (err) => {
      alert("Failed to create project: " + err);
    }
  });

  const handleCreate = () => {
    if (newProjectName && appSpec) {
      createMutation.mutate();
    }
  };

  return (
    <Box sx={{ width: '100%', height: '100%', overflowY: 'auto' }}>
      <Container maxWidth="lg" sx={{ py: 8 }}>
        {/* Theme toggle in top-right */}
        <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2 }}>
          <ThemeToggle />
        </Box>

        <Box sx={{ mb: 6, textAlign: 'center' }}>
        <Typography variant="h2" component="h1" gutterBottom color="primary" sx={{ fontWeight: 800, letterSpacing: -1 }}>
          ArcadiaForge
        </Typography>
        <Typography variant="h5" color="text.secondary" gutterBottom sx={{ mb: 4 }}>
          Autonomous Coding Framework
        </Typography>
        <Button 
          variant="contained" 
          size="large" 
          startIcon={<PlusCircle size={20} />}
          onClick={() => setModalOpen(true)}
          sx={{ px: 4, py: 1.5, fontSize: '1.1rem' }}
        >
          New Project
        </Button>
      </Box>

      {isLoading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
          <CircularProgress color="primary" />
        </Box>
      ) : error ? (
        <Alert severity="error">Error loading projects. Ensure the backend is running.</Alert>
      ) : (
        <Grid container spacing={3}>
          {projects?.map((project: Project) => (
            <Grid key={project.id} size={{ xs: 12, sm: 6, md: 4 }}>
              <Card sx={{ height: '100%', border: '1px solid', borderColor: 'divider', background: 'background.paper' }}>
                <CardActionArea onClick={() => navigate(`/project/${project.id}`)} sx={{ height: '100%' }}>
                  <CardContent sx={{ p: 3 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
                      <Folder color="#22D3EE" style={{ marginRight: '12px' }} />
                      <Typography variant="h6" component="div" sx={{ fontWeight: 'bold' }}>
                        {project.name}
                      </Typography>
                    </Box>
                    <Box sx={{ display: 'flex', alignItems: 'center', color: 'text.secondary', fontSize: '0.875rem' }}>
                      <Database size={14} style={{ marginRight: '6px' }} />
                      {project.has_db ? 'Active Database' : 'No History'}
                    </Box>
                  </CardContent>
                </CardActionArea>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      {/* New Project Modal */}
      <Dialog open={isModalOpen} onClose={() => setModalOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ fontWeight: 'bold' }}>Create New Project</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="Project Name"
            fullWidth
            variant="outlined"
            value={newProjectName}
            onChange={(e) => setNewProjectName(e.target.value)}
            sx={{ mb: 3, mt: 1 }}
          />
          {!appSpec ? (
            <Box
              sx={{
                border: '2px dashed',
                borderColor: isDragging ? 'primary.main' : 'divider',
                borderRadius: 2,
                p: 4,
                textAlign: 'center',
                bgcolor: isDragging ? 'rgba(34, 211, 238, 0.08)' : 'background.paper',
                cursor: 'pointer',
                transition: 'all 0.2s',
                '&:hover': {
                  borderColor: 'primary.main',
                  bgcolor: 'rgba(34, 211, 238, 0.04)'
                }
              }}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                type="file"
                hidden
                ref={fileInputRef}
                accept=".txt,.md,.json,.py,.js,.ts"
                onChange={(e) => {
                  if (e.target.files?.[0]) readFile(e.target.files[0]);
                }}
              />
              <Upload size={48} color={isDragging ? '#22D3EE' : '#666'} style={{ marginBottom: 16 }} />
              <Typography variant="h6" color="text.primary" gutterBottom>
                Upload App Specification
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Drag & drop your <code>app_spec.txt</code> here, or click to browse
              </Typography>
            </Box>
          ) : (
            <Box sx={{ position: 'relative' }}>
              <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1 }}>
                <Button 
                  size="small" 
                  startIcon={<X size={16} />} 
                  onClick={() => setAppSpec('')}
                  color="error"
                  sx={{ minWidth: 'auto', px: 2 }}
                >
                  Clear File
                </Button>
              </Box>
              <TextField
                label="Application Specification"
                fullWidth
                multiline
                rows={10}
                variant="outlined"
                value={appSpec}
                onChange={(e) => setAppSpec(e.target.value)}
                InputProps={{
                  sx: { fontFamily: 'monospace' }
                }}
              />
            </Box>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 3 }}>
          <Button onClick={() => setModalOpen(false)} color="inherit">Cancel</Button>
          <Button 
            onClick={handleCreate} 
            variant="contained" 
            disabled={!newProjectName || !appSpec || createMutation.isPending}
          >
            {createMutation.isPending ? 'Generating...' : 'Generate'}
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
    </Box>
  );
};

export default LandingPage;