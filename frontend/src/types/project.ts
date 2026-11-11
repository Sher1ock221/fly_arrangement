/**
 * 项目类型
 */

/** 项目关联客户简要（与后端 CustomerBrief 对齐） */
export interface CustomerBrief {
  id: number;
  name: string;
  company?: string | null;
  position?: string | null;
  owner_user_id?: number | null;
  access_role?: "owner" | "collaborator";
}

/** 项目实体 */
export interface Project {
  id: number;
  project_no: string | null;
  name: string;
  deadline: string | null;
  deadline_at?: string | null;
  start_date?: string | null;
  start_time?: string | null;
  goal: string | null;
  owner: string | null;
  update_date: string | null;
  requirements: string | null;
  progress_text?: string | null;
  customer_name: string | null;
  /** 关联客户列表（多对多，列表/详情接口返回） */
  related_customers?: CustomerBrief[];
  owner_user_id?: number | null;
  initiator_user_id?: number | null;
  initiator_display_name?: string | null;
  /** 当前用户对此项目的角色 */
  access_role?: "owner" | "collaborator";
  is_initiator?: boolean;
  is_owner?: boolean;
}

/** 创建项目 payload */
export interface ProjectCreate {
  project_no?: string | null;
  name: string;
  deadline?: string | null;
  deadline_at?: string | null;
  start_date?: string | null;
  start_time?: string | null;
  goal?: string | null;
  owner?: string | null;
  owner_user_id?: number | null;
  requirements?: string | null;
  progress_text?: string | null;
  customer_name?: string | null;
  /** 关联客户 id 列表（多对多） */
  customer_ids?: number[];
}

/** 更新项目 payload（全部可选） */
export interface ProjectUpdate {
  project_no?: string | null;
  name?: string | null;
  deadline?: string | null;
  deadline_at?: string | null;
  start_date?: string | null;
  start_time?: string | null;
  goal?: string | null;
  owner?: string | null;
  owner_user_id?: number | null;
  requirements?: string | null;
  progress_text?: string | null;
  customer_name?: string | null;
  /** 关联客户 id 列表（多对多） */
  customer_ids?: number[];
}
