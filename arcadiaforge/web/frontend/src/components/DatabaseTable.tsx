import React, { useMemo, useState } from 'react';
import { DataGrid, GridToolbar, type GridColDef } from '@mui/x-data-grid';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Box, LinearProgress, Typography, Alert, Dialog,
  DialogTitle, DialogContent, IconButton, Button, DialogActions,
  TextField, InputAdornment, ToggleButtonGroup, ToggleButton,
  Pagination, MenuItem, Select, FormControl
} from '@mui/material';
import { X, Copy, Search, LayoutGrid, List, Filter, ArrowUpDown } from 'lucide-react';
import { api, type FeatureUpdate } from '../services/api';
import FeatureEditor from './FeatureEditor';
import FeatureCard from './FeatureCard';

interface DatabaseTableProps {
  projectId: string;
  table: string;
  refreshInterval?: number;
}

type SortOption = 'id' | 'priority' | 'status' | 'category';

const DatabaseTable: React.FC<DatabaseTableProps> = ({ projectId, table, refreshInterval = 5000 }) => {
  const [selectedRow, setSelectedRow] = useState<any>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [viewMode, setViewMode] = useState<'cards' | 'table'>('cards');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'pending' | 'implemented' | 'failed'>('all');
  const [categoryFilter, setCategoryFilter] = useState<'all' | 'functional' | 'style'>('all');
  const [sortBy, setSortBy] = useState<SortOption>('id');
  const [page, setPage] = useState(1);
  const cardsPerPage = 12;

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
      setIsEditing(false);
      setSelectedRow(null);
    }
  });

  // Helper to get feature status for sorting
  const getFeatureStatus = (feature: any): number => {
    const isImplemented = feature.passes > 0;
    const isFailed = feature.failure_count > 0 && !isImplemented;
    if (isImplemented) return 2; // Implemented last
    if (isFailed) return 1; // Failed in middle
    return 0; // Pending first
  };

  // Filter, search, and sort features
  const filteredData = useMemo(() => {
    if (!data || table !== 'features') return data;

    let result = data.filter((feature: any) => {
      // Search filter
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        const matchesSearch =
          feature.description?.toLowerCase().includes(query) ||
          feature.id?.toString().includes(query) ||
          feature.category?.toLowerCase().includes(query);
        if (!matchesSearch) return false;
      }

      // Status filter
      if (statusFilter !== 'all') {
        const isImplemented = feature.passes > 0;
        const isFailed = feature.failure_count > 0 && !isImplemented;

        if (statusFilter === 'implemented' && !isImplemented) return false;
        if (statusFilter === 'failed' && !isFailed) return false;
        if (statusFilter === 'pending' && (isImplemented || isFailed)) return false;
      }

      // Category filter
      if (categoryFilter !== 'all' && feature.category !== categoryFilter) return false;

      return true;
    });

    // Sort
    result = [...result].sort((a, b) => {
      switch (sortBy) {
        case 'priority':
          return (a.priority || 3) - (b.priority || 3); // Lower priority number = higher priority
        case 'status':
          return getFeatureStatus(a) - getFeatureStatus(b); // Pending first, then failed, then implemented
        case 'category':
          return (a.category || '').localeCompare(b.category || '');
        case 'id':
        default:
          return a.id - b.id;
      }
    });

    return result;
  }, [data, searchQuery, statusFilter, categoryFilter, sortBy, table]);

  // Pagination for cards
  const paginatedData = useMemo(() => {
    if (!filteredData || table !== 'features') return filteredData;
    const startIndex = (page - 1) * cardsPerPage;
    return filteredData.slice(startIndex, startIndex + cardsPerPage);
  }, [filteredData, page, table]);

  const totalPages = filteredData ? Math.ceil(filteredData.length / cardsPerPage) : 1;

  // Count stats for features
  const featureStats = useMemo(() => {
    if (!data || table !== 'features') return null;
    const implemented = data.filter((f: any) => f.passes > 0).length;
    const failed = data.filter((f: any) => f.failure_count > 0 && f.passes === 0).length;
    const pending = data.length - implemented - failed;
    return { total: data.length, implemented, failed, pending };
  }, [data, table]);

  const columns = useMemo(() => {
    if (!data || data.length === 0) return [];

    return Object.keys(data[0]).map((key): GridColDef => ({
      field: key,
      headerName: key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, ' '),
      flex: 1,
      minWidth: 150,
      renderCell: (params) => {
        const value = params.value;

        if (typeof value === 'object' && value !== null) {
          return (
             <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.75rem', overflow: 'hidden', textOverflow: 'ellipsis' }} title={JSON.stringify(value, null, 2)}>
               {Array.isArray(value) ? `[Array(${value.length})]` : '{Object}'}
             </Typography>
          );
        }

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
    if (table === 'features') {
      setIsEditing(true);
    } else {
      setIsEditing(false);
    }
  };

  const handleCardEdit = (feature: any) => {
    setSelectedRow(feature);
    setIsEditing(true);
  };

  // Navigation Logic
  const selectedIndex = filteredData?.findIndex((row: any) =>
    (row.id && selectedRow?.id && row.id === selectedRow.id) || row === selectedRow
  ) ?? -1;

  const hasPrevious = selectedIndex > 0;
  const hasNext = filteredData && selectedIndex < filteredData.length - 1;

  const handlePrevious = () => {
    if (hasPrevious && filteredData) {
        setSelectedRow(filteredData[selectedIndex - 1]);
    }
  };

  const handleNext = () => {
    if (hasNext && filteredData) {
        setSelectedRow(filteredData[selectedIndex + 1]);
    }
  };

  if (isLoading) return <LinearProgress />;
  if (error) return <Alert severity="error">Failed to load table: {table}</Alert>;
  if (!data || data.length === 0) return <Typography color="text.secondary" sx={{ p: 2 }}>No records found in {table}</Typography>;

  // Calculate progress percentage
  const progressPercent = featureStats ? Math.round((featureStats.implemented / featureStats.total) * 100) : 0;

  // Features get card view with filters
  if (table === 'features') {
    return (
      <>
        <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          {/* Progress Bar Section */}
          {featureStats && (
            <Box sx={{ px: 2, pt: 2, pb: 1 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 'bold' }}>
                  PROGRESS
                </Typography>
                <Typography variant="caption" sx={{ color: 'primary.main', fontWeight: 'bold' }}>
                  {progressPercent}% Complete
                </Typography>
              </Box>
              <Box sx={{ position: 'relative', height: 8, bgcolor: 'rgba(255,255,255,0.05)', borderRadius: 1, overflow: 'hidden' }}>
                {/* Implemented (green) */}
                <Box
                  sx={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    height: '100%',
                    width: `${(featureStats.implemented / featureStats.total) * 100}%`,
                    bgcolor: '#22C55E',
                    transition: 'width 0.3s ease',
                  }}
                />
                {/* Failed (red) - stacked after implemented */}
                {featureStats.failed > 0 && (
                  <Box
                    sx={{
                      position: 'absolute',
                      left: `${(featureStats.implemented / featureStats.total) * 100}%`,
                      top: 0,
                      height: '100%',
                      width: `${(featureStats.failed / featureStats.total) * 100}%`,
                      bgcolor: '#EF4444',
                      transition: 'width 0.3s ease',
                    }}
                  />
                )}
              </Box>
              <Box sx={{ display: 'flex', gap: 2, mt: 1 }}>
                <Typography variant="caption" sx={{ color: '#22C55E', display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: '#22C55E' }} />
                  {featureStats.implemented} implemented
                </Typography>
                {featureStats.failed > 0 && (
                  <Typography variant="caption" sx={{ color: '#EF4444', display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: '#EF4444' }} />
                    {featureStats.failed} failed
                  </Typography>
                )}
                <Typography variant="caption" sx={{ color: '#9AA4B2', display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: 'rgba(255,255,255,0.2)' }} />
                  {featureStats.pending} pending
                </Typography>
              </Box>
            </Box>
          )}

          {/* Toolbar */}
          <Box sx={{ borderBottom: '1px solid', borderColor: 'divider' }}>
            {/* Row 1: Search */}
            <Box sx={{ px: 2, pt: 2, pb: 1 }}>
              <TextField
                size="small"
                placeholder="Search features..."
                value={searchQuery}
                onChange={(e) => { setSearchQuery(e.target.value); setPage(1); }}
                fullWidth
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <Search size={16} color="#9AA4B2" />
                    </InputAdornment>
                  ),
                }}
              />
            </Box>

            {/* Row 2: Filters and View Toggle */}
            <Box sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1.5,
              px: 2,
              pb: 2,
              flexWrap: 'wrap'
            }}>
              {/* Status Filter */}
              <FormControl size="small" sx={{ minWidth: 130 }}>
                <Select
                  value={statusFilter}
                  onChange={(e) => { setStatusFilter(e.target.value as any); setPage(1); }}
                  displayEmpty
                  startAdornment={<Filter size={14} style={{ marginRight: 6, color: '#9AA4B2' }} />}
                >
                  <MenuItem value="all">All Status</MenuItem>
                  <MenuItem value="pending">Pending</MenuItem>
                  <MenuItem value="implemented">Implemented</MenuItem>
                  <MenuItem value="failed">Failed</MenuItem>
                </Select>
              </FormControl>

              {/* Category Filter */}
              <FormControl size="small" sx={{ minWidth: 130 }}>
                <Select
                  value={categoryFilter}
                  onChange={(e) => { setCategoryFilter(e.target.value as any); setPage(1); }}
                  displayEmpty
                >
                  <MenuItem value="all">All Categories</MenuItem>
                  <MenuItem value="functional">Functional</MenuItem>
                  <MenuItem value="style">Style</MenuItem>
                </Select>
              </FormControl>

              {/* Sort Dropdown */}
              <FormControl size="small" sx={{ minWidth: 130 }}>
                <Select
                  value={sortBy}
                  onChange={(e) => { setSortBy(e.target.value as SortOption); setPage(1); }}
                  displayEmpty
                  startAdornment={<ArrowUpDown size={14} style={{ marginRight: 6, color: '#9AA4B2' }} />}
                >
                  <MenuItem value="id">Sort by ID</MenuItem>
                  <MenuItem value="priority">Sort by Priority</MenuItem>
                  <MenuItem value="status">Sort by Status</MenuItem>
                  <MenuItem value="category">Sort by Category</MenuItem>
                </Select>
              </FormControl>

              {/* Spacer */}
              <Box sx={{ flex: 1 }} />

              {/* View Toggle */}
              <ToggleButtonGroup
                value={viewMode}
                exclusive
                onChange={(_, value) => value && setViewMode(value)}
                size="small"
              >
                <ToggleButton value="cards" title="Card View">
                  <LayoutGrid size={16} />
                </ToggleButton>
                <ToggleButton value="table" title="Table View">
                  <List size={16} />
                </ToggleButton>
              </ToggleButtonGroup>
            </Box>
          </Box>

          {/* Content */}
          {viewMode === 'cards' ? (
            <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
              {/* Cards Grid */}
              <Box
                sx={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                  gap: 2,
                }}
              >
                {paginatedData?.map((feature: any) => (
                  <FeatureCard
                    key={feature.id}
                    feature={feature}
                    onEdit={handleCardEdit}
                  />
                ))}
              </Box>

              {/* Empty State */}
              {(!paginatedData || paginatedData.length === 0) && (
                <Box sx={{ textAlign: 'center', py: 8, color: 'text.secondary' }}>
                  <Typography>No features match your filters</Typography>
                </Box>
              )}

              {/* Pagination */}
              {totalPages > 1 && (
                <Box sx={{ display: 'flex', justifyContent: 'center', mt: 3, pb: 2 }}>
                  <Pagination
                    count={totalPages}
                    page={page}
                    onChange={(_, value) => setPage(value)}
                    color="primary"
                    size="small"
                  />
                </Box>
              )}
            </Box>
          ) : (
            // Table View
            <Box sx={{ flex: 1, minHeight: 400 }}>
              <DataGrid
                rows={filteredData || []}
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
          )}
        </Box>

        {/* Feature Editor Dialog */}
        <Dialog
          open={!!selectedRow && isEditing}
          onClose={() => setSelectedRow(null)}
          maxWidth="md"
          fullWidth
          scroll="paper"
        >
          {selectedRow && (
            <FeatureEditor
              feature={selectedRow}
              onSave={(update) => updateMutation.mutate(update)}
              onCancel={() => setSelectedRow(null)}
              onNext={handleNext}
              onPrevious={handlePrevious}
              hasNext={hasNext}
              hasPrevious={hasPrevious}
            />
          )}
        </Dialog>
      </>
    );
  }

  // Non-features tables use the original DataGrid view
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

      {/* Detail Dialog for non-feature tables */}
      <Dialog
        open={!!selectedRow}
        onClose={() => setSelectedRow(null)}
        maxWidth="md"
        fullWidth
        scroll="paper"
      >
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
      </Dialog>
    </>
  );
};

export default DatabaseTable;
