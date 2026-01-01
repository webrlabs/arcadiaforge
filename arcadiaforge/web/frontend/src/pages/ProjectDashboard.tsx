import React, { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { 
  Box, Typography, AppBar, Toolbar, IconButton, Tabs, Tab, 
  Button, Select, MenuItem, FormControl
} from '@mui/material';
import { ArrowLeft, Play } from 'lucide-react';
import Terminal from '../components/Terminal';
import DatabaseTable from '../components/DatabaseTable';
import ReasoningTimeline from '../components/ReasoningTimeline';
import StatusHeader from '../components/StatusHeader';

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;
  return (
    <div role="tabpanel" hidden={value !== index} {...other} style={{ height: '100%', overflow: 'hidden' }}>
      {value === index && <Box sx={{ p: 2, height: '100%', overflow: 'auto' }}>{children}</Box>}
    </div>
  );
}

const ProjectDashboard: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const [tabValue, setTabValue] = useState(0);
  const [subTab, setSubTab] = useState('features'); // For tabs with multiple tables

  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setTabValue(newValue);
    // Reset sub-selection when main tab changes
    if (newValue === 0) setSubTab('features');
    if (newValue === 1) setSubTab('hot_memory');
    if (newValue === 2) setSubTab('events');
    if (newValue === 3) setSubTab('timeline'); // Default to timeline for Reasoning
  };

  if (!projectId) return null;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
      {/* Top Bar */}
      <AppBar position="static" color="inherit" elevation={0} sx={{ borderBottom: '1px solid', borderColor: 'divider' }}>
        <Toolbar variant="dense" sx={{ minHeight: 48 }}>
          <IconButton edge="start" component={Link} to="/" sx={{ mr: 2 }}>
            <ArrowLeft size={20} />
          </IconButton>
          <Typography variant="subtitle1" sx={{ fontWeight: 'bold', flexGrow: 1 }}>
            {projectId?.replace(/_/g, ' ').toUpperCase()}
          </Typography>
          
          {/* Real-time Status Header */}
          <StatusHeader projectId={projectId} />

          <Button variant="contained" color="primary" size="small" startIcon={<Play size={14} />}>
            Generate
          </Button>
        </Toolbar>
      </AppBar>

      {/* Main Content Area */}
      <Box sx={{ flexGrow: 1, display: 'flex', overflow: 'hidden' }}>
        
        {/* Left Side: Data Views */}
        <Box sx={{ width: '50%', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <Box sx={{ borderBottom: '1px solid', borderColor: 'divider', display: 'flex', alignItems: 'center', px: 2 }}>
             <Tabs 
              value={tabValue} 
              onChange={handleTabChange} 
              indicatorColor="primary"
              textColor="primary"
            >
              <Tab label="Features" sx={{ fontSize: '0.75rem', minHeight: 48 }} />
              <Tab label="Memory" sx={{ fontSize: '0.75rem', minHeight: 48 }} />
              <Tab label="History" sx={{ fontSize: '0.75rem', minHeight: 48 }} />
              <Tab label="Reasoning" sx={{ fontSize: '0.75rem', minHeight: 48 }} />
            </Tabs>
            
            {/* Sub-table selector */}
            <FormControl size="small" sx={{ ml: 'auto', minWidth: 150, my: 0.5 }}>
               <Select
                  value={subTab}
                  onChange={(e) => setSubTab(e.target.value)}
                  variant="standard"
                  disableUnderline
                  sx={{ fontSize: '0.8rem', color: 'text.secondary' }}
               >
                 {tabValue === 0 && <MenuItem value="features">Feature List</MenuItem>}
                 
                 {tabValue === 1 && [
                   <MenuItem key="hot" value="hot_memory">Hot Memory</MenuItem>,
                   <MenuItem key="warm" value="warm_memory">Warm Memory</MenuItem>,
                   <MenuItem key="cold" value="cold_memory">Cold Memory</MenuItem>
                 ]}

                 {tabValue === 2 && [
                   <MenuItem key="sessions" value="sessions">Sessions</MenuItem>,
                   <MenuItem key="events" value="events">Events</MenuItem>,
                   <MenuItem key="artifacts" value="artifacts">Artifacts</MenuItem>
                 ]}

                 {tabValue === 3 && [
                   <MenuItem key="timeline" value="timeline">Timeline View</MenuItem>,
                   <MenuItem key="decisions" value="decisions">Decisions Table</MenuItem>,
                   <MenuItem key="hypotheses" value="hypotheses">Hypotheses Table</MenuItem>,
                   <MenuItem key="checkpoints" value="checkpoints">Checkpoints Table</MenuItem>
                 ]}
               </Select>
            </FormControl>
          </Box>

          <Box sx={{ flexGrow: 1, overflow: 'hidden', bgcolor: 'background.default' }}>
            <TabPanel value={tabValue} index={0}>
              <DatabaseTable projectId={projectId} table="features" />
            </TabPanel>
            
            <TabPanel value={tabValue} index={1}>
              <DatabaseTable projectId={projectId} table={subTab} />
            </TabPanel>
            
            <TabPanel value={tabValue} index={2}>
              <DatabaseTable projectId={projectId} table={subTab} />
            </TabPanel>
            
            <TabPanel value={tabValue} index={3}>
              {subTab === 'timeline' ? (
                 <ReasoningTimeline projectId={projectId} />
              ) : (
                 <DatabaseTable projectId={projectId} table={subTab} />
              )}
            </TabPanel>
          </Box>
        </Box>

        {/* Right Side: Terminal Sidebar */}
        <Box sx={{ width: '50%', borderLeft: '1px solid', borderColor: 'divider', display: 'flex', flexDirection: 'column' }}>
          <Terminal projectId={projectId || ''} />
        </Box>
      </Box>
    </Box>
  );
};

export default ProjectDashboard;
