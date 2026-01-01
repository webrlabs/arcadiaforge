import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { ThemeProvider, CssBaseline, Box } from '@mui/material';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { theme } from './theme';
import LandingPage from './pages/LandingPage';
import ProjectDashboard from './pages/ProjectDashboard';

const queryClient = new QueryClient();

const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <Box sx={{ width: '100vw', height: '100vh', display: 'flex', flexDirection: 'column', bgcolor: 'background.default' }}>
          <Router>
            <Routes>
              <Route path="/" element={<LandingPage />} />
              <Route path="/project/:projectId" element={<ProjectDashboard />} />
            </Routes>
          </Router>
        </Box>
      </ThemeProvider>
    </QueryClientProvider>
  );
};

export default App;
