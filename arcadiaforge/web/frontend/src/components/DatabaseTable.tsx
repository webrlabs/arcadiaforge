import React, { useMemo, useState } from 'react';
import { DataGrid, GridToolbar, type GridColDef } from '@mui/x-data-grid';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { 
  Box, LinearProgress, Typography, Alert, Dialog, 
  DialogTitle, DialogContent, IconButton, Button, DialogActions
} from '@mui/material';
import { X, Copy } from 'lucide-react';
import { api, type FeatureUpdate } from '../services/api';
import FeatureEditor from './FeatureEditor';

interface DatabaseTableProps {
  projectId: string;
  table: string;
  refreshInterval?: number;
}

const DatabaseTable: React.FC<DatabaseTableProps> = ({ projectId, table, refreshInterval = 5000 }) => {
  const [selectedRow, setSelectedRow] = useState<any>(null);
  const [isEditing, setIsEditing] = useState(false);
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ['table', projectId, table],
    queryFn: () => api.getTableData(projectId, table),
    refetchInterval: refreshInterval
  });

  const updateMutation = useMutation({
    mutationFn: (update: FeatureUpdate) => api.updateFeature(projectId, selectedRow.id, update),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['table', projectId, table] });
      // Keep dialog open but exit edit mode? Or maybe just keep editing?
      // Let's exit edit mode for now, or just refresh data.
      // Actually, if we stay in edit mode, we should fetch fresh data for the row.
      // For simplicity, we close the editor on save.
      setIsEditing(false);
      setSelectedRow(null);
    }
  });

  const columns = useMemo(() => {
    if (!data || data.length === 0) return [];
    
    // Create columns from the first row's keys
    return Object.keys(data[0]).map((key): GridColDef => ({
      field: key,
      headerName: key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, ' '),
      flex: 1,
      minWidth: 150,
      renderCell: (params) => {
        const value = params.value;
        
        // Handle JSON objects/arrays
        if (typeof value === 'object' && value !== null) {
          return (
             <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.75rem', overflow: 'hidden', textOverflow: 'ellipsis' }} title={JSON.stringify(value, null, 2)}>
               {Array.isArray(value) ? `[Array(${value.length})]` : '{Object}'}
             </Typography>
          );
        }
        
        // Handle Booleans
        if (typeof value === 'boolean') {
           return (
             <Box 
               sx={{ 
                 width: 10, height: 10, borderRadius: '50%', 
                 bgcolor: value ? 'success.main' : 'error.main' 
               }} 
             />
           );
        }
        
        return value;
      }
    }));
  }, [data]);

  const handleCopy = () => {
    if (selectedRow) {
      navigator.clipboard.writeText(JSON.stringify(selectedRow, null, 2));
    }
  };

  const handleRowClick = (params: any) => {
    setSelectedRow(params.row);
    // If it's the features table, default to edit mode immediately
    if (table === 'features') {
      setIsEditing(true);
    } else {
      setIsEditing(false);
    }
  };

  // Navigation Logic
  const selectedIndex = data?.findIndex((row: any) => 
    (row.id && selectedRow?.id && row.id === selectedRow.id) || row === selectedRow
  ) ?? -1;
  
  const hasPrevious = selectedIndex > 0;
  const hasNext = data && selectedIndex < data.length - 1;

  const handlePrevious = () => {
    if (hasPrevious && data) {
        setSelectedRow(data[selectedIndex - 1]);
    }
  };

  const handleNext = () => {
    if (hasNext && data) {
        setSelectedRow(data[selectedIndex + 1]);
    }
  };

  if (isLoading) return <LinearProgress />;
  if (error) return <Alert severity="error">Failed to load table: {table}</Alert>;
  if (!data || data.length === 0) return <Typography color="text.secondary" sx={{ p: 2 }}>No records found in {table}</Typography>;

  return (
    <>
      <Box sx={{ height: '100%', width: '100%', minHeight: 400 }}>
        <DataGrid
          rows={data}
          columns={columns}
          getRowId={(row) => row.id || row.session_id || row.index || Math.random()}
          slots={{ toolbar: GridToolbar }}
          onRowClick={handleRowClick}
          initialState={{
            pagination: { paginationModel: { pageSize: 25 } },
            density: 'compact'
          }}
          pageSizeOptions={[25, 50, 100]}
          sx={{
            border: 'none',
            cursor: 'pointer',
            '& .MuiDataGrid-row:hover': {
              bgcolor: 'action.hover',
              cursor: 'pointer'
            },
            '& .MuiDataGrid-cell': {
               fontFamily: 'monospace',
               fontSize: '0.8rem',
               color: 'text.secondary'
            },
            '& .MuiDataGrid-columnHeaders': {
               bgcolor: 'background.paper',
               color: 'primary.main',
               textTransform: 'uppercase',
               fontSize: '0.75rem',
               fontWeight: 'bold'
            }
          }}
        />
      </Box>

      {/* Detail/Edit Dialog */}
      <Dialog 
        open={!!selectedRow} 
        onClose={() => setSelectedRow(null)}
        maxWidth="md"
        fullWidth
        scroll="paper"
      >
        {/* If editing 'features', show editor immediately */}
        {table === 'features' && isEditing && selectedRow ? (
          <FeatureEditor 
            feature={selectedRow}
            onSave={(update) => updateMutation.mutate(update)}
            onCancel={() => setSelectedRow(null)}
            onNext={handleNext}
            onPrevious={handlePrevious}
            hasNext={hasNext}
            hasPrevious={hasPrevious}
          />
        ) : (
          <>
            <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid', borderColor: 'divider' }}>
              <Typography variant="h6" component="div" sx={{ fontFamily: 'monospace' }}>
                Row Details
              </Typography>
              <Box>
                <IconButton onClick={handleCopy} size="small" title="Copy JSON" sx={{ mr: 1 }}>
                  <Copy size={20} />
                </IconButton>
                <IconButton onClick={() => setSelectedRow(null)} size="small">
                  <X size={20} />
                </IconButton>
              </Box>
            </DialogTitle>
            <DialogContent dividers sx={{ bgcolor: '#0D0D0D', p: 0 }}>
               <Box 
                 component="pre" 
                 sx={{ 
                   p: 2, 
                   m: 0, 
                   overflow: 'auto', 
                   fontFamily: 'monospace', 
                   fontSize: '0.875rem',
                   color: 'text.secondary'
                 }}
               >
                 {selectedRow && JSON.stringify(selectedRow, null, 2)}
               </Box>
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setSelectedRow(null)}>Close</Button>
            </DialogActions>
          </>
        )}
      </Dialog>
    </>
  );
};

export default DatabaseTable;
