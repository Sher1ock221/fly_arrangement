/**
 * 日历日程类型
 */

/** 创建日程 payload */
export interface CalendarEventCreate {
  title: string;
  description?: string | null;
  start_time: string;
  end_time: string;
  type?: string;
  project_id?: number | null;
  status?: "scheduled" | "confirmed" | "completed" | "cancelled";
  candidate_group_id?: string | null;
  candidate_policy?: string | null;
  auto_cancel_others_on_complete?: boolean;
}

/** 更新日程 payload（全部可选） */
export interface CalendarEventUpdate {
  title?: string | null;
  description?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  type?: string | null;
  project_id?: number | null;
  status?: "scheduled" | "confirmed" | "completed" | "cancelled" | null;
  candidate_group_id?: string | null;
  candidate_policy?: string | null;
  auto_cancel_others_on_complete?: boolean | null;
}

/** 日历日程实体 */
export interface CalendarEvent {
  id: number;
  title: string;
  description: string | null;
  start_time: string;
  end_time: string;
  type: string;
  project_id: number | null;
  created_at: string | null;
  updated_at: string | null;
  owner_user_id?: number | null;
  access_role?: "owner" | "collaborator";
  status?: "scheduled" | "confirmed" | "completed" | "cancelled";
  candidate_group_id?: string | null;
  candidate_policy?: string | null;
  auto_cancel_others_on_complete?: boolean;
}
