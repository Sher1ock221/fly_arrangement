/** 将后端 diagnostic.shortcut 转为用户可见文案 */
export function formatShortcutBadgeLabel(shortcut: string): string {
  const map: Record<string, string> = {
    local_smalltalk: "本地闲聊",
    simple_calendar_event: "日程快捷创建",
    compound_schedule: "复合行程",
    simple_local_reminder: "本地提醒",
    simple_customer_create: "快速创建客户",
    compound_project_customer_communication: "项目+客户+沟通",
    compound_project_customer: "复合业务",
  };
  return map[shortcut] ?? shortcut;
}
