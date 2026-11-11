/**
 * 协作相关类型：collaborator / 项目更新 / 客户跟进 / 日程评论
 */

export type AccessRole = "owner" | "collaborator";

export interface Collaborator {
  id: number;
  user_id: number;
  created_by_user_id: number | null;
  created_at: string | null;
  display_name: string | null;
  username: string | null;
}

export interface CollaboratorAdd {
  user_id: number;
}

export interface ProjectActivity {
  id: number;
  project_id: number;
  author_user_id: number | null;
  content: string;
  update_type: string;
  created_at: string | null;
  author_display_name: string | null;
}

export interface ProjectActivityCreate {
  content: string;
  update_type?: string;
}

export interface CustomerFollowup {
  id: number;
  customer_id: number;
  author_user_id: number | null;
  content: string;
  created_at: string | null;
  author_display_name: string | null;
}

export interface CustomerFollowupCreate {
  content: string;
}

export interface CalendarEventComment {
  id: number;
  calendar_event_id: number;
  author_user_id: number | null;
  content: string;
  created_at: string | null;
  author_display_name: string | null;
}

export interface CalendarEventCommentCreate {
  content: string;
}

export interface TransferOwnerRequest {
  target_user_id: number;
}

export interface TransferOwnerResponse {
  ok: boolean;
  new_owner_user_id: number;
  new_owner_display_name: string | null;
  old_owner_user_id: number;
  project_id?: number;
  customer_id?: number;
  event_id?: number;
}
