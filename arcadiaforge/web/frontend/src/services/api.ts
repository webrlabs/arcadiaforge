import axios from 'axios';

export const API_BASE = 'http://localhost:8000/api';
export const WS_BASE = 'ws://localhost:8000/ws';

export interface Project {
  id: string;
  name: string;
  path: string;
  has_db: boolean;
}

export interface FeatureUpdate {
  description?: string;
  steps?: string[];
  priority?: number;
}

export const api = {
  getProjects: async (): Promise<Project[]> => {
    const res = await axios.get(`${API_BASE}/projects`);
    return res.data;
  },

  createProject: async (name: string, appSpec: string) => {
    const res = await axios.post(`${API_BASE}/projects`, { name, app_spec: appSpec });
    return res.data;
  },

  getTableData: async (projectId: string, table: string, limit = 100, offset = 0, order: 'asc' | 'desc' = 'asc') => {
    const res = await axios.get(`${API_BASE}/projects/${projectId}/db/${table}`, {
      params: { limit, offset, order }
    });
    return res.data;
  },

  updateFeature: async (projectId: string, featureId: number, update: FeatureUpdate) => {
    const res = await axios.patch(`${API_BASE}/projects/${projectId}/features/${featureId}`, update);
    return res.data;
  },

  getProjectSpec: async (projectId: string) => {
    const res = await axios.get(`${API_BASE}/projects/${projectId}/spec`);
    return res.data;
  },

  saveProjectSpec: async (projectId: string, content: string) => {
    const res = await axios.post(`${API_BASE}/projects/${projectId}/spec`, { content });
    return res.data;
  }
};
