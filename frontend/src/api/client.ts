import axios from 'axios';
import type {
  DashboardStats,
  DesignSkill,
  DesignSkillCreate,
  ImageReview,
  LearnedDesignProfile,
  CreativeProject,
  CanvasNodeRecord,
  CreativeFeedback,
  EditHistory,
  EditRequest,
  Generation,
  GenerationListItem,
  KnowledgeDoc,
  Product,
  ProductAsset,
  ProductCreate,
} from '../types';

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(undefined, (error) => {
  if (error.response?.status === 401 && !window.location.pathname.startsWith('/login')) {
    localStorage.removeItem('access_token');
    window.location.href = '/login';
  }
  return Promise.reject(error);
});

export const authApi = {
  login: (email: string, password: string) => api.post('/auth/login', { email, password }).then((r) => r.data),
  register: (payload: { tenant_name: string; tenant_code: string; name: string; email: string; password: string }) =>
    api.post('/auth/register', payload).then((r) => r.data),
};

export function mediaUrl(path: string): string {
  if (!path) return '';
  if (path.startsWith('http://') || path.startsWith('https://') || path.startsWith('data:')) {
    return path;
  }
  return path;
}

export function apiUrl(path: string): string {
  return `/api${path}`;
}

export const productApi = {
  list: () => api.get<Product[]>('/products').then((r) => r.data),
  get: (id: number) => api.get<Product>(`/products/${id}`).then((r) => r.data),
  create: (data: ProductCreate) => api.post<Product>('/products', data).then((r) => r.data),
  update: (id: number, data: Partial<ProductCreate>) =>
    api.put<Product>(`/products/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/products/${id}`).then((r) => r.data),
  uploadImage: async (file: File) => {
    const form = new FormData();
    form.append('file', file);
    const { data } = await api.post<{ url: string }>('/products/upload-image', form);
    return data.url;
  },
  uploadProductImages: async (productId: number, files: File[], imageType: 'product' | 'detail') => {
    const form = new FormData();
    form.append('image_type', imageType);
    files.forEach((f) => form.append('files', f));
    const { data } = await api.post<Product>(`/products/${productId}/images`, form);
    return data;
  },
  listAssets: (productId: number) =>
    api.get<ProductAsset[]>(`/products/${productId}/assets`).then((r) => r.data),
  uploadAssets: async (
    productId: number,
    files: File[],
    meta: { asset_type: string; description?: string; tags?: string },
  ) => {
    const form = new FormData();
    form.append('asset_type', meta.asset_type);
    form.append('description', meta.description || '');
    form.append('tags', meta.tags || '');
    files.forEach((file) => form.append('files', file));
    const { data } = await api.post<ProductAsset[]>(`/products/${productId}/assets`, form);
    return data;
  },
  removeAsset: (productId: number, assetId: number) =>
    api.delete(`/products/${productId}/assets/${assetId}`).then((r) => r.data),
};

export const generationApi = {
  start: (productId: number) =>
    api.post<Generation>(`/products/${productId}/generate`).then((r) => r.data),
  list: (productId?: number) =>
    api
      .get<GenerationListItem[]>('/generations', {
        params: productId != null ? { product_id: productId } : undefined,
      })
      .then((r) => r.data),
  get: (id: number) => api.get<Generation>(`/generations/${id}`).then((r) => r.data),
  remove: (id: number) => api.delete(`/generations/${id}`).then((r) => r.data),
  retry: (id: number) => api.post<Generation>(`/generations/${id}/retry`).then((r) => r.data),
  edit: (id: number, payload: EditRequest) =>
    api.post<Generation>(`/generations/${id}/edit`, payload).then((r) => r.data),
  edits: (id: number) =>
    api.get<EditHistory[]>(`/generations/${id}/edits`).then((r) => r.data),
  updateModules: (id: number, sections: Record<string, string>, moduleOrder: string[]) =>
    api
      .put<Generation>(`/generations/${id}/modules`, {
        sections,
        module_order: moduleOrder,
      })
      .then((r) => r.data),
  imageReviews: (id: number) => api.get<ImageReview[]>(`/generations/${id}/image-reviews`).then((r) => r.data),
  reviewImage: (id: number, moduleKey: string, payload: { status: ImageReview['status']; reasons: string[]; note?: string }) =>
    api.put<ImageReview>(`/generations/${id}/visual-modules/${moduleKey}/review`, payload).then((r) => r.data),
  learnedProfile: (productId: number) => api.get<LearnedDesignProfile | null>(`/products/${productId}/learned-design-profile`).then((r) => r.data),
};

export const knowledgeApi = {
  list: (productId?: number) =>
    api
      .get<KnowledgeDoc[]>('/knowledge', {
        params: productId != null ? { product_id: productId } : undefined,
      })
      .then((r) => r.data),
  create: (data: {
    title: string;
    doc_type: string;
    content: string;
    product_id?: number | null;
    brand_name?: string;
  }) => api.post<KnowledgeDoc>('/knowledge', data).then((r) => r.data),
  upload: async (file: File, meta: { title?: string; doc_type: string; product_id?: number; brand_name?: string }) => {
    const form = new FormData();
    form.append('file', file);
    form.append('doc_type', meta.doc_type);
    if (meta.title) form.append('title', meta.title);
    if (meta.product_id != null) form.append('product_id', String(meta.product_id));
    if (meta.brand_name) form.append('brand_name', meta.brand_name);
    const { data } = await api.post<KnowledgeDoc>('/knowledge/upload', form);
    return data;
  },
  remove: (id: number) => api.delete(`/knowledge/${id}`).then((r) => r.data),
};

export const designSkillApi = {
  list: () => api.get<DesignSkill[]>('/design-skills').then((r) => r.data),
  create: (data: DesignSkillCreate) => api.post<DesignSkill>('/design-skills', data).then((r) => r.data),
  update: (id: number, data: DesignSkillCreate) => api.put<DesignSkill>(`/design-skills/${id}`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/design-skills/${id}`).then((r) => r.data),
};

export const creativeApi = {
  list: () => api.get<CreativeProject[]>('/creative-projects').then((r) => r.data),
  get: (id: number) => api.get<CreativeProject>(`/creative-projects/${id}`).then((r) => r.data),
  create: (data: { product_id: number; name: string; brief: string; platform: string; output_width: number; output_height: number }) => api.post<CreativeProject>('/creative-projects', data).then((r) => r.data),
  nodes: (id: number) => api.get<CanvasNodeRecord[]>(`/creative-projects/${id}/nodes`).then((r) => r.data),
  saveCanvas: (id: number, nodes: Array<Partial<CanvasNodeRecord> & { id: string; node_type: string; position_x: number; position_y: number; data: Record<string, unknown> }>, viewport: Record<string, number>) => api.put<CanvasNodeRecord[]>(`/creative-projects/${id}/canvas`, { nodes, viewport }).then((r) => r.data),
  generate: (id: number, data: { prompt: string; action: string; selected_node_ids: string[]; parent_node_id?: string | null; auto_select_materials: boolean; count: number }) => api.post<{ generation: { context_snapshot?: Record<string, unknown> }; nodes: CanvasNodeRecord[] }>(`/creative-projects/${id}/generate`, data, { timeout: 600000 }).then((r) => r.data),
  uploadRefined: async (id: number, file: File, parentNodeId?: string) => {
    const form = new FormData(); form.append('file', file); form.append('parent_node_id', parentNodeId || '');
    return api.post<CanvasNodeRecord>(`/creative-projects/${id}/refined-output`, form).then((r) => r.data);
  },
  submitDeliverable: async (id: number, file: File, parentNodeId?: string, note = '') => {
    const form = new FormData();
    form.append('file', file);
    form.append('parent_node_id', parentNodeId || '');
    form.append('note', note);
    return api.post<CanvasNodeRecord>(`/creative-projects/${id}/deliverable`, form).then((r) => r.data);
  },
  markFinal: (id: number, nodeId: string) => api.put<CanvasNodeRecord>(`/creative-projects/${id}/nodes/${nodeId}/final`).then((r) => r.data),
  feedback: (id: number) => api.get<CreativeFeedback[]>(`/creative-projects/${id}/feedback`).then((r) => r.data),
  reviewNode: (id: number, nodeId: string, status: string, reasons: string[] = []) => api.put<CreativeFeedback>(`/creative-projects/${id}/nodes/${nodeId}/feedback`, { status, reasons }).then((r) => r.data),
  learnedProfile: (productId: number) => api.get<LearnedDesignProfile | null>(`/products/${productId}/learned-design-profile`).then((r) => r.data),
};

export const dashboardApi = {
  stats: () => api.get<DashboardStats>('/dashboard/stats').then((r) => r.data),
};

export default api;
