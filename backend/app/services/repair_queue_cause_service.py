"""Repair queue 启发式根因推断（非智能诊断，仅供运营初筛）。"""
from __future__ import annotations

from typing import Any

from app.constants.project_governance import (
    ISSUE_TYPE_DIRTY_COLLABORATOR_RELATION,
    ISSUE_TYPE_LEGACY_OWNER_TEXT,
    ISSUE_TYPE_MISSING_INITIATOR,
    ISSUE_TYPE_MISSING_OWNER,
    ISSUE_TYPE_VISIBILITY_MISMATCH,
    MISMATCH_KIND_DETAIL_READABLE_NOT_LISTED,
    MISMATCH_KIND_LIST_VISIBLE_DETAIL_FORBIDDEN,
    SUSPECTED_CAUSE_HISTORICAL_DATA_GAP,
    SUSPECTED_CAUSE_INCOMPLETE_CREATE_FLOW,
    SUSPECTED_CAUSE_INVALID_REFERENCE,
    SUSPECTED_CAUSE_LEGACY_DATA_NOT_MIGRATED,
    SUSPECTED_CAUSE_LEGACY_VISIBILITY_POLLUTION,
    SUSPECTED_CAUSE_LIST_FILTER_DIVERGED,
    SUSPECTED_CAUSE_PERMISSION_LOGIC_DIVERGED,
    SUSPECTED_CAUSE_STALE_RELATION_DATA,
)


def infer_suspected_cause(issue_type: str, payload: dict[str, Any] | None) -> str:
    """按 issue_type 与 payload 给出最小可读 suspected_cause 标签。"""
    p = payload or {}

    if issue_type == ISSUE_TYPE_VISIBILITY_MISMATCH:
        kind = p.get("mismatch_kind")
        collab = bool(p.get("collaborator_match"))
        if kind == MISMATCH_KIND_LIST_VISIBLE_DETAIL_FORBIDDEN:
            if collab:
                return SUSPECTED_CAUSE_STALE_RELATION_DATA
            return SUSPECTED_CAUSE_PERMISSION_LOGIC_DIVERGED
        if kind == MISMATCH_KIND_DETAIL_READABLE_NOT_LISTED:
            if collab:
                return SUSPECTED_CAUSE_STALE_RELATION_DATA
            return SUSPECTED_CAUSE_LIST_FILTER_DIVERGED
        return SUSPECTED_CAUSE_LEGACY_VISIBILITY_POLLUTION

    if issue_type == ISSUE_TYPE_MISSING_INITIATOR:
        return SUSPECTED_CAUSE_HISTORICAL_DATA_GAP

    if issue_type == ISSUE_TYPE_MISSING_OWNER:
        if p.get("initiator_present") is True:
            return SUSPECTED_CAUSE_INCOMPLETE_CREATE_FLOW
        return SUSPECTED_CAUSE_HISTORICAL_DATA_GAP

    if issue_type == ISSUE_TYPE_LEGACY_OWNER_TEXT:
        return SUSPECTED_CAUSE_LEGACY_DATA_NOT_MIGRATED

    if issue_type == ISSUE_TYPE_DIRTY_COLLABORATOR_RELATION:
        if p.get("user_ref_missing") or p.get("project_ref_missing"):
            return SUSPECTED_CAUSE_INVALID_REFERENCE
        return SUSPECTED_CAUSE_STALE_RELATION_DATA

    return SUSPECTED_CAUSE_HISTORICAL_DATA_GAP


def effective_suspected_cause(stored: str | None, issue_type: str, payload: dict[str, Any] | None) -> str:
    """列展示用：库里有值用库里的，否则现场推断（兼容迁移前数据）。"""
    if stored:
        return stored
    return infer_suspected_cause(issue_type, payload)
