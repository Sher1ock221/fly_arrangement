from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.project_governance import (
    ISSUE_TYPE_DIRTY_COLLABORATOR_RELATION,
    ISSUE_TYPE_LEGACY_OWNER_TEXT,
    ISSUE_TYPE_MISSING_INITIATOR,
    ISSUE_TYPE_MISSING_OWNER,
    ISSUE_TYPE_VISIBILITY_MISMATCH,
    MISMATCH_KIND_DETAIL_READABLE_NOT_LISTED,
    MISMATCH_KIND_LIST_VISIBLE_DETAIL_FORBIDDEN,
    REPAIR_STATUS_PENDING,
    TARGET_ID_SUFFIX_DETAIL_READABLE_NOT_LISTED,
    TARGET_ID_SUFFIX_LIST_VISIBLE_DETAIL_FORBIDDEN,
    TARGET_TYPE_VISIBILITY_PAIR,
)
from app.models.collaboration import ProjectCollaborator
from app.models.project import Project
from app.models.project_repair_queue import ProjectRepairQueue
from app.services.collaboration_service import get_project_access_role, project_visible_filter
from app.services.project_owner_repair_queue_runtime import list_project_owner_repair_queue_legacy_scan
from app.services.repair_queue_cause_service import infer_suspected_cause

logger = logging.getLogger(__name__)

# Scanner 与已关闭条目：仅当不存在同 target 的 pending/running 时会新建 pending。
# running 与 pending 同属「活跃」：任一存在即阻止重复入队，避免管理员处理中被 scanner 复制一条新 pending。
# 已 resolved/ignored/false_positive 的同 target 条目保留为历史；若问题再次出现，可再入队一条新的 pending
# （未做 payload 指纹去重，避免误杀真实复发）。
# 后续可扩展：对长时间 running 的 SLA 告警、超时自动退回 pending（本轮未实现）。


async def _enqueue_issue(
    db: AsyncSession,
    *,
    issue_type: str,
    severity: str,
    target_type: str,
    target_id: str,
    payload_json: dict[str, Any] | None = None,
) -> bool:
    existing = (
        await db.execute(
            select(ProjectRepairQueue.id).where(
                ProjectRepairQueue.module == "project",
                ProjectRepairQueue.issue_type == issue_type,
                ProjectRepairQueue.target_type == target_type,
                ProjectRepairQueue.target_id == target_id,
                ProjectRepairQueue.status.in_(["pending", "running"]),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    merged: dict[str, Any] = dict(payload_json or {})
    cause = infer_suspected_cause(issue_type, merged)
    merged["suspected_cause"] = cause
    now = datetime.now(timezone.utc)
    db.add(
        ProjectRepairQueue(
            module="project",
            issue_type=issue_type,
            severity=severity,
            target_type=target_type,
            target_id=target_id,
            payload_json=merged,
            suspected_cause=cause,
            status=REPAIR_STATUS_PENDING,
            detected_at=now,
            status_updated_at=now,
        )
    )
    return True


async def _project_matches_list_visible(db: AsyncSession, project_id: int, user_id: int) -> bool:
    """与 GET /projects 列表一致：project_visible_filter(user_id) 命中该项目。"""
    res = await db.execute(
        select(Project.id).where(Project.id == project_id, project_visible_filter(user_id)).limit(1)
    )
    return res.scalar_one_or_none() is not None


async def _scan_visibility_mismatches(db: AsyncSession) -> dict[str, int]:
    """对比「列表可见」与「详情可读」链路，发现口径分叉并入队。

    扫描范围：每个项目的 initiator_user_id、owner_user_id、project_collaborators.user_id 去重，
    不做全库用户 × 全项目笛卡尔积。

    不覆盖管理员 acting / effective 代操视角（仅持久化在项目/协作者表上的用户 id）。
    第二类 mismatch（详情可读但列表未列出）已纳入检测；若与第一类同时不可能成立，队列仍可能为空。
    """
    proj_rows = (
        await db.execute(select(Project.id, Project.initiator_user_id, Project.owner_user_id))
    ).all()
    if not proj_rows:
        return {
            "visibility_mismatch_new": 0,
            "visibility_pairs_scanned": 0,
            "visibility_case1_list_visible_detail_forbidden": 0,
            "visibility_case2_detail_readable_not_listed": 0,
            "visibility_scan_errors": 0,
        }

    pids = [int(r[0]) for r in proj_rows]
    collab_rows = (
        await db.execute(
            select(ProjectCollaborator.project_id, ProjectCollaborator.user_id).where(
                ProjectCollaborator.project_id.in_(pids)
            )
        )
    ).all()
    collab_map: dict[int, set[int]] = {}
    for pid, uid in collab_rows:
        collab_map.setdefault(int(pid), set()).add(int(uid))

    new_enqueued = 0
    pairs_scanned = 0
    case1 = 0
    case2 = 0
    errors = 0

    for row in proj_rows:
        pid, ini, own = int(row[0]), row[1], row[2]
        users: set[int] = set()
        if ini is not None:
            users.add(int(ini))
        if own is not None:
            users.add(int(own))
        users.update(collab_map.get(pid, ()))

        for uid in users:
            pairs_scanned += 1
            collab_match = uid in collab_map.get(pid, set())
            try:
                list_vis = await _project_matches_list_visible(db, pid, uid)
                role = await get_project_access_role(db, pid, uid)
                detail_ok = role != "none"
                detail_result = "ok" if detail_ok else "forbidden"
                list_result = "visible" if list_vis else "not_visible"

                base_payload: dict[str, Any] = {
                    "user_id": uid,
                    "project_id": pid,
                    "initiator_user_id": ini,
                    "owner_user_id": own,
                    "collaborator_match": collab_match,
                    "detection_context": (
                        "project_governance_scan: SQL project_visible_filter vs get_project_access_role; "
                        "admin acting/effective 视角未扫"
                    ),
                    "detail_check_result": detail_result,
                    "list_check_result": list_result,
                }

                if list_vis and not detail_ok:
                    case1 += 1
                    payload = {
                        **base_payload,
                        "mismatch_kind": MISMATCH_KIND_LIST_VISIBLE_DETAIL_FORBIDDEN,
                    }
                    tid = f"p{pid}:u{uid}:{TARGET_ID_SUFFIX_LIST_VISIBLE_DETAIL_FORBIDDEN}"
                    new_enqueued += int(
                        await _enqueue_issue(
                            db,
                            issue_type=ISSUE_TYPE_VISIBILITY_MISMATCH,
                            severity="high",
                            target_type=TARGET_TYPE_VISIBILITY_PAIR,
                            target_id=tid,
                            payload_json=payload,
                        )
                    )
                elif detail_ok and not list_vis:
                    case2 += 1
                    payload = {
                        **base_payload,
                        "mismatch_kind": MISMATCH_KIND_DETAIL_READABLE_NOT_LISTED,
                    }
                    tid = f"p{pid}:u{uid}:{TARGET_ID_SUFFIX_DETAIL_READABLE_NOT_LISTED}"
                    new_enqueued += int(
                        await _enqueue_issue(
                            db,
                            issue_type=ISSUE_TYPE_VISIBILITY_MISMATCH,
                            severity="medium",
                            target_type=TARGET_TYPE_VISIBILITY_PAIR,
                            target_id=tid,
                            payload_json=payload,
                        )
                    )
            except Exception:
                errors += 1
                logger.exception("visibility mismatch scan failed project_id=%s user_id=%s", pid, uid)

    logger.info(
        "project_governance visibility scan: pairs=%s new_enqueued=%s case1=%s case2=%s errors=%s",
        pairs_scanned,
        new_enqueued,
        case1,
        case2,
        errors,
    )
    return {
        "visibility_mismatch_new": new_enqueued,
        "visibility_pairs_scanned": pairs_scanned,
        "visibility_case1_list_visible_detail_forbidden": case1,
        "visibility_case2_detail_readable_not_listed": case2,
        "visibility_scan_errors": errors,
    }


async def scan_project_repair_issues(db: AsyncSession) -> dict[str, int]:
    created = 0
    stats: dict[str, int] = {
        "missing_initiator": 0,
        "missing_owner": 0,
        "legacy_owner_text": 0,
        "legacy_member_residual": 0,
        "dirty_collaborator_relation": 0,
        "display_orphan_member": 0,
    }

    missing_initiator_rows = (
        await db.execute(select(Project.id).where(Project.initiator_user_id.is_(None)))
    ).scalars().all()
    for pid in missing_initiator_rows:
        stats["missing_initiator"] += 1
        created += int(
            await _enqueue_issue(
                db,
                issue_type=ISSUE_TYPE_MISSING_INITIATOR,
                severity="high",
                target_type="project",
                target_id=str(pid),
                payload_json={"project_id": int(pid)},
            )
        )

    missing_owner_rows = (
        await db.execute(
            select(Project.id, Project.initiator_user_id).where(Project.owner_user_id.is_(None))
        )
    ).all()
    for pid, ini in missing_owner_rows:
        stats["missing_owner"] += 1
        created += int(
            await _enqueue_issue(
                db,
                issue_type=ISSUE_TYPE_MISSING_OWNER,
                severity="high",
                target_type="project",
                target_id=str(pid),
                payload_json={"project_id": int(pid), "initiator_present": ini is not None},
            )
        )

    legacy_owner_rows = await list_project_owner_repair_queue_legacy_scan(db)
    for row in legacy_owner_rows:
        stats["legacy_owner_text"] += 1
        stats["legacy_member_residual"] += 1
        created += int(
            await _enqueue_issue(
                db,
                issue_type=ISSUE_TYPE_LEGACY_OWNER_TEXT,
                severity="medium",
                target_type="project",
                target_id=str(row["project_id"]),
                payload_json={
                    "owner_text": row.get("owner_text"),
                    "reason": row.get("reason"),
                    "project_id": int(row["project_id"]),
                },
            )
        )

    dirty_rows = (
        await db.execute(
            text(
                """
                SELECT pc.project_id, pc.user_id,
                    (u.id IS NULL) AS user_ref_missing,
                    (p.id IS NULL) AS project_ref_missing
                FROM project_collaborators pc
                LEFT JOIN users u ON u.id = pc.user_id
                LEFT JOIN projects p ON p.id = pc.project_id
                WHERE u.id IS NULL
                   OR p.id IS NULL
                   OR pc.user_id = p.owner_user_id
                   OR pc.user_id = p.initiator_user_id
                """
            )
        )
    ).mappings().all()
    for row in dirty_rows:
        stats["dirty_collaborator_relation"] += 1
        uid = row["user_id"]
        created += int(
            await _enqueue_issue(
                db,
                issue_type=ISSUE_TYPE_DIRTY_COLLABORATOR_RELATION,
                severity="medium",
                target_type="project",
                target_id=f"{row['project_id']}:{uid}",
                payload_json={
                    "project_id": int(row["project_id"]),
                    "user_id": int(uid) if uid is not None else None,
                    "user_ref_missing": bool(row["user_ref_missing"]),
                    "project_ref_missing": bool(row["project_ref_missing"]),
                },
            )
        )

    # 预留：展示型孤儿成员（当前实现先复用 legacy owner 队列作为信号）
    stats["display_orphan_member"] = stats["legacy_member_residual"]

    vis = await _scan_visibility_mismatches(db)
    created += int(vis.get("visibility_mismatch_new", 0))

    await db.flush()
    return {"queued": created, **stats, **vis}

