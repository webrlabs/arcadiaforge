import React, { useState } from 'react';
import { 
  Container, Typography, Box, Button, Grid, Card, CardContent, 
  CardActionArea, Dialog, DialogTitle, DialogContent, DialogActions, 
  TextField, CircularProgress, Alert 
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type Project } from '../services/api';
import { PlusCircle, Folder, Database } from 'lucide-react';

const LandingPage: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [isModalOpen, setModalOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [appSpec, setAppSpec] = useState('');

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
            <Grid item xs={12} sm={6} md={4} key={project.id}>
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
          <TextField
            label="Application Specification (app_spec.txt)"
            fullWidth
            multiline
            rows={10}
            variant="outlined"
            placeholder="Describe what you want to build..."
            value={appSpec}
            onChange={(e) => setAppSpec(e.target.value)}
            InputProps={{
              sx: { fontFamily: 'monospace' }
            }}
          />
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