export interface Product {
  id: number;
  name: string;
  category: string;
  price: number;
  description: string;
  target_users: string;
  brand_name: string;
  ingredients: string;
  usage_method: string;
  specifications: string;
  image_urls: string[];
  detail_image_urls: string[];
  created_at: string;
  updated_at: string;
  generation_count: number;
  learned_profile_enabled: boolean;
}

export interface ProductCreate {
  name: string;
  category: string;
  price: number;
  description: string;
  target_users: string;
  brand_name: string;
  ingredients: string;
  usage_method: string;
  specifications: string;
  image_urls: string[];
  detail_image_urls: string[];
  learned_profile_enabled?: boolean;
}

export interface Generation {
  id: number;
  product_id: number;
  status: 'pending' | 'running' | 'completed' | 'failed' | string;
  agent_results: Record<string, unknown> | null;
  detail_page_markdown: string | null;
  detail_page_sections: Record<string, string | string[]> | null;
  marketing_copy: string | null;
  main_image_copy: string | null;
  error_message: string | null;
  attempt_count: number;
  max_attempts: number;
  created_at: string;
  updated_at: string;
}

export interface GenerationListItem {
  id: number;
  product_id: number;
  product_name: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface EditRequest {
  action: 'regenerate_section' | 'optimize_tone' | 'change_audience';
  section?: string;
  instruction?: string;
  target_audience?: string;
}

export interface EditHistory {
  id: number;
  generation_id: number;
  action: string;
  section: string | null;
  instruction: string | null;
  before_content: string | null;
  after_content: string | null;
  created_at: string;
}

export interface KnowledgeDoc {
  id: number;
  product_id: number | null;
  brand_name: string;
  title: string;
  doc_type: string;
  filename: string | null;
  content: string;
  chunk_count: number;
  created_at: string;
}

export interface DesignSkill {
  id: number;
  name: string;
  scope: 'general' | 'category' | 'brand' | 'product';
  category: string;
  brand_name: string;
  product_id: number | null;
  description: string;
  design_principles: string;
  module_guidance: string;
  visual_rules: string;
  copy_rules: string;
  negative_rules: string;
  primary_color: string;
  accent_color: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export type DesignSkillCreate = Omit<DesignSkill, 'id' | 'created_at' | 'updated_at'>;

export interface ImageReview {
  id: number;
  generation_id: number;
  product_id: number;
  module_key: string;
  module_title: string;
  image_url: string;
  status: 'usable' | 'needs_edit' | 'rejected' | 'final';
  reasons: string[];
  note: string;
  weight: number;
  visual_analysis: Record<string, unknown> | null;
  learning_status: 'pending' | 'analyzing' | 'completed' | 'failed';
  created_at: string;
  updated_at: string;
}

export interface LearnedDesignProfile {
  id: number;
  brand_name: string;
  category: string;
  sample_count: number;
  positive_count: number;
  negative_count: number;
  confidence: number;
  learned_rules: Record<string, Array<{ value: string; count: number }> | string>;
  status: 'observing' | 'stable';
  updated_at: string;
}

export interface CreativeProject {
  id: number;
  product_id: number;
  name: string;
  brief: string;
  platform: string;
  output_width: number;
  output_height: number;
  status: string;
  viewport: { x?: number; y?: number; zoom?: number };
  created_at: string;
  updated_at: string;
}

export interface CanvasNodeRecord {
  id: string;
  project_id: number;
  node_type: string;
  parent_node_id: string | null;
  position_x: number;
  position_y: number;
  width: number;
  height: number;
  data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CreativeFeedback {
  id: number;
  project_id: number;
  product_id: number;
  node_id: string;
  image_url: string;
  status: string;
  reasons: string[];
  weight: number;
  learning_status: string;
}

export interface ProductAsset {
  id: number;
  product_id: number | null;
  name: string;
  asset_type: string;
  file_url: string;
  mime_type: string;
  description: string;
  tags: string[];
  created_at: string;
}

export interface DashboardStats {
  product_count: number;
  generation_count: number;
  knowledge_doc_count: number;
  recent_tasks: GenerationListItem[];
}

export const SECTION_LABELS: Record<string, string> = {
  title: '商品标题',
  selling_points: '核心卖点',
  advantages: '产品优势',
  scenarios: '使用场景',
  pain_solutions: '痛点解决方案',
  purchase_reasons: '购买理由',
  faq: 'FAQ',
  after_sales: '售后说明',
};
