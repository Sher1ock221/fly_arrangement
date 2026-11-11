/**
 * 客户类型（与后端 CustomerRead / CustomerDetailRead / CustomerInteraction 对齐）
 */
import type { CustomerBrief } from "@/types/project";

/** 客户详情中的项目简要 */
export interface ProjectBrief {
  id: number;
  project_no: string | null;
  name: string;
  status: string | null;
  deadline: string | null;
  owner: string | null;
  owner_user_id?: number | null;
  access_role?: "owner" | "collaborator";
  /** 关联客户（多对多，客户详情接口返回） */
  related_customers?: CustomerBrief[];
}

/** 客户列表项：基础信息 + 可选统计 */
export interface Customer {
  id: number;
  name: string;
  origin: string | null;
  company: string | null;
  profile: string | null;
  contact: string | null;
  future_direction: string | null;
  position: string | null;
  business_direction: string | null;
  notes: string | null;
  acquaintance_source: string | null;
  created_at: string | null;
  updated_at: string | null;
  project_count?: number | null;
  last_contact_at?: string | null;
  owner_user_id?: number | null;
  access_role?: "owner" | "collaborator";
}

/** 客户详情：基础信息 + 关联项目 + 沟通记录 */
export interface CustomerDetail extends Customer {
  projects: ProjectBrief[];
  interactions: CustomerInteraction[];
}

/** 客户跟进/沟通记录 */
export interface CustomerInteraction {
  id: number;
  customer_id: number;
  meeting_time: string | null;
  talk_summary: string | null;
  cooperation_direction: string | null;
  cooperation_intent: string | null;
  next_cooperation_plan: string | null;
  specific_needs: string | null;
  importance: number | null;
  source: string | null;
  raw_input: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CustomerCreate {
  name: string;
  origin?: string | null;
  company?: string | null;
  profile?: string | null;
  contact?: string | null;
  future_direction?: string | null;
  position?: string | null;
  business_direction?: string | null;
  notes?: string | null;
  acquaintance_source?: string | null;
}

export interface CustomerUpdate {
  name?: string | null;
  origin?: string | null;
  company?: string | null;
  profile?: string | null;
  contact?: string | null;
  future_direction?: string | null;
  position?: string | null;
  business_direction?: string | null;
  notes?: string | null;
  acquaintance_source?: string | null;
}

/** 创建客户跟进记录 */
export interface CustomerInteractionCreate {
  meeting_time?: string | null;
  talk_summary?: string | null;
  cooperation_direction?: string | null;
  cooperation_intent?: string | null;
  next_cooperation_plan?: string | null;
  specific_needs?: string | null;
  importance?: number | null;
  source?: string | null;
  raw_input?: string | null;
}

/** 更新客户跟进记录 */
export interface CustomerInteractionUpdate {
  meeting_time?: string | null;
  talk_summary?: string | null;
  cooperation_direction?: string | null;
  cooperation_intent?: string | null;
  next_cooperation_plan?: string | null;
  specific_needs?: string | null;
  importance?: number | null;
  source?: string | null;
  raw_input?: string | null;
}
