"""项目治理扫描、repair queue 与根因分类常量（与治理文档口径一致）。"""

# ── Repair queue 状态 ─────────────────────────────────
REPAIR_STATUS_PENDING = "pending"
REPAIR_STATUS_RUNNING = "running"
REPAIR_STATUS_RESOLVED = "resolved"
REPAIR_STATUS_IGNORED = "ignored"
REPAIR_STATUS_FALSE_POSITIVE = "false_positive"
REPAIR_STATUS_FAILED = "failed"

REPAIR_ACTIVE_STATUSES = (REPAIR_STATUS_PENDING, REPAIR_STATUS_RUNNING)
REPAIR_TERMINAL_STATUSES = (
    REPAIR_STATUS_RESOLVED,
    REPAIR_STATUS_IGNORED,
    REPAIR_STATUS_FALSE_POSITIVE,
    REPAIR_STATUS_FAILED,
)

# 管理员可将队列项更新的终态（不含 failed 的批量入口时可单独扩展）
REPAIR_ADMIN_SETTABLE_TERMINAL = (
    REPAIR_STATUS_RESOLVED,
    REPAIR_STATUS_IGNORED,
    REPAIR_STATUS_FALSE_POSITIVE,
)

# ── Repair queue SLA（默认仅对 running + started_at 生效）──────────────
# 未来可按 severity / issue_type 覆盖时长或读配置表；本轮统一单常量。
PROJECT_REPAIR_QUEUE_DEFAULT_SLA_HOURS = 24

# ── issue_type（与 scanner 写入值一致）────────────────
ISSUE_TYPE_VISIBILITY_MISMATCH = "visibility_mismatch"
ISSUE_TYPE_MISSING_INITIATOR = "missing_initiator"
ISSUE_TYPE_MISSING_OWNER = "missing_owner"
ISSUE_TYPE_LEGACY_OWNER_TEXT = "legacy_owner_text"  # 历史命名；等同于 legacy owner/member residue
ISSUE_TYPE_DIRTY_COLLABORATOR_RELATION = "dirty_collaborator_relation"

# ── suspected_cause（启发式根因标签）──────────────────
SUSPECTED_CAUSE_PERMISSION_LOGIC_DIVERGED = "permission_logic_diverged"
SUSPECTED_CAUSE_STALE_RELATION_DATA = "stale_relation_data"
SUSPECTED_CAUSE_LEGACY_VISIBILITY_POLLUTION = "legacy_visibility_pollution"
SUSPECTED_CAUSE_LIST_FILTER_DIVERGED = "list_filter_diverged"
SUSPECTED_CAUSE_HISTORICAL_DATA_GAP = "historical_data_gap"
SUSPECTED_CAUSE_INCOMPLETE_CREATE_FLOW = "incomplete_create_flow"
SUSPECTED_CAUSE_LEGACY_DATA_NOT_MIGRATED = "legacy_data_not_migrated"
SUSPECTED_CAUSE_INVALID_REFERENCE = "invalid_reference"

# ── visibility payload ─────────────────────────────
TARGET_TYPE_VISIBILITY_PAIR = "visibility_pair"
MISMATCH_KIND_LIST_VISIBLE_DETAIL_FORBIDDEN = "list_visible_detail_forbidden"
MISMATCH_KIND_DETAIL_READABLE_NOT_LISTED = "detail_readable_but_not_listed"

TARGET_ID_SUFFIX_LIST_VISIBLE_DETAIL_FORBIDDEN = "lvdf"
TARGET_ID_SUFFIX_DETAIL_READABLE_NOT_LISTED = "drnl"

# ── 审计 action ───────────────────────────────────────
AUDIT_REPAIR_QUEUE_STARTED = "repair_queue_started"
AUDIT_REPAIR_QUEUE_RESOLVED = "repair_queue_resolved"
AUDIT_REPAIR_QUEUE_IGNORED = "repair_queue_ignored"
AUDIT_REPAIR_QUEUE_FALSE_POSITIVE = "repair_queue_false_positive"
