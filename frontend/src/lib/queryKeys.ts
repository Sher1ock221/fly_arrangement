/**
 * 统一 query key，便于删除/新增/编辑后精确 invalidate，避免漏刷新或全量刷。
 */
export const queryKeys = {
  userScope: (actingUserId?: number | null) => actingUserId ?? "self",
  projects: (actingUserId?: number | null) =>
    ["projects", queryKeys.userScope(actingUserId)] as const,
  projectDetail: (id: number, actingUserId?: number | null) =>
    ["projects", queryKeys.userScope(actingUserId), id] as const,
  projectCollaborators: (projectId: number) => ["project-collaborators", projectId] as const,
  projectShareMembers: (projectId: number) => ["project-share-members", projectId] as const,
  projectUpdates: (projectId: number) => ["project-updates", projectId] as const,
  projectOwnerRepairQueue: () => ["project-owner-repair-queue"] as const,
  projectGovernanceSummary: () => ["admin", "project-governance", "summary"] as const,
  projectGovernanceRepairQueue: (
    issueType?: string,
    status?: string,
    severity?: string,
    activeOnly?: boolean,
    overdueOnly?: boolean
  ) =>
    [
      "admin",
      "project-governance",
      "repair-queue",
      issueType ?? "all",
      status ?? "all",
      severity ?? "all",
      activeOnly === true ? "unsettled" : "all",
      overdueOnly === true ? "overdue" : "all",
    ] as const,

  customers: (actingUserId?: number | null) =>
    ["customers", queryKeys.userScope(actingUserId)] as const,
  customerDetail: (id: number, actingUserId?: number | null) =>
    ["customers", queryKeys.userScope(actingUserId), id] as const,
  customerCollaborators: (customerId: number) => ["customer-collaborators", customerId] as const,
  customerFollowups: (customerId: number) => ["customer-followups", customerId] as const,

  /** 日历事件列表（月历、工作台、按日）均以此为前缀，invalidate 后全部刷新 */
  calendarEvents: () => ["calendar", "events"] as const,
  calendarEventDetail: (id: number) => ["calendar-event", id] as const,
  calendarEventCollaborators: (eventId: number) => ["calendar-collaborators", eventId] as const,
  calendarEventComments: (eventId: number) => ["calendar-comments", eventId] as const,
  eventCollaborators: (eventId: number) => ["event-collaborators", eventId] as const,
  eventComments: (eventId: number) => ["event-comments", eventId] as const,

  allUsers: () => ["all-users"] as const,
  projectSelectableUsers: () => ["projects", "selectable-users"] as const,
  /** 管理员账号列表（设置 -> 账号管理） */
  adminUsers: () => ["admin", "users"] as const,
  aiConfig: () => ["ai-config"] as const,
  aiReady: () => ["ai-ready"] as const,
  /** AI 会话列表（GET /api/v1/chat/conversations） */
  chatConversations: () => ["chat", "conversations"] as const,
  /** 某个会话的消息（按 conversationId 隔离缓存） */
  chatMessages: (conversationId: number) => ["chat", "messages", conversationId] as const,
  /** 个人提醒计划列表（设置 → 我的提醒） */
  reminders: () => ["reminders"] as const,
} as const;
