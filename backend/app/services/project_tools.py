"""
项目相关 AI 工具：按 project_id 更新项目，写 AuditLog。
支持 customer_ids / append 同步 project_customers。
"""
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Project
from app.models.audit_log import ACTION_UPDATE, TARGET_TYPE_PROJECT
from app.models.project_customer import ProjectCustomer
from app.schemas.project import ProjectInDB


def _project_to_log_value(orm: Project) -> dict:
    return ProjectInDB.model_validate(orm).model_dump(mode="json")


# 中文字段名 -> 模型字段名（供上层映射后传入 fields）
FIELD_LABELS: dict[str, str] = {
    "项目名称": "name",
    "截止日期": "deadline",
    "负责人": "owner",
    "项目目标": "goal",
    "项目内需": "requirements",
    "客户名称": "customer_name",
    "客户": "customer_id",
}


async def update_project_by_id(
    db: AsyncSession,
    project_id: int,
    fields: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    """
    根据 project_id 更新项目字段，写 update_date、AuditLog。
    支持 customer_ids (list[int]) 与 append (bool)：同步 project_customers；
    append=True 表示追加关联客户，False 或未传表示覆盖。
    若提供 operator_user_id（如飞书 bound_user_id），仅允许修改该用户名下的项目。
    """
    orm = await db.get(Project, project_id)
    if not orm:
        return {"success": False, "message": "项目不存在"}
    if operator_user_id is not None and orm.owner_user_id != operator_user_id:
        return {"success": False, "message": "无权限操作该项目或项目不存在"}

    customer_ids = fields.pop("customer_ids", None)
    append = fields.pop("append", None)
    if isinstance(append, str):
        append = append.strip().lower() in ("true", "1", "yes")
    elif append is None:
        append = False

    old_value = _project_to_log_value(orm)
    updated_labels: list[str] = []

    for key, value in fields.items():
        if key in ("project_id", "id"):
            continue
        if not hasattr(orm, key):
            continue
        if value is None and key not in ("deadline", "goal", "owner", "requirements", "customer_name", "customer_id"):
            continue
        if key == "deadline" and isinstance(value, str):
            value = date.fromisoformat(value.split("T")[0]) if value else None
        setattr(orm, key, value)
        label = next((k for k, v in FIELD_LABELS.items() if v == key), key)
        if label not in updated_labels:
            updated_labels.append(label)

    if customer_ids is not None:
        ids_to_link = [int(x) for x in customer_ids if x is not None]
        if not append:
            await db.execute(delete(ProjectCustomer).where(ProjectCustomer.project_id == project_id))
        for cid in ids_to_link:
            db.add(ProjectCustomer(project_id=project_id, customer_id=cid))
        orm.customer_id = ids_to_link[0] if ids_to_link else None
        if "关联客户" not in updated_labels:
            updated_labels.append("关联客户")

    orm.update_date = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(orm)
    new_value = _project_to_log_value(orm)

    log = AuditLog(
        target_type=TARGET_TYPE_PROJECT,
        target_id=orm.id,
        action=ACTION_UPDATE,
        old_value=old_value,
        new_value=new_value,
        operator_source=operator_source,
        operator_external_id=operator_external_id,
    )
    db.add(log)
    await db.flush()

    execution_summary = "已更新项目【" + (orm.name or "").strip() + "】。"
    if "关联客户" in updated_labels:
        execution_summary += "已更新关联客户。"
    execution_summary += "可前往项目详情页查看。"
    return {
        "success": True,
        "result": {
            "project_id": orm.id,
            "project_no": (orm.project_no or "").strip(),
            "name": (orm.name or "").strip(),
            "detail_url": f"/projects/{orm.id}",
        },
        "execution_summary": execution_summary,
    }
