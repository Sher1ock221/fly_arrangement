"""
客户相关 AI 工具：按 customer_id 更新客户，写 AuditLog。
"""
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Customer
from app.models.audit_log import ACTION_UPDATE, TARGET_TYPE_CUSTOMER
from app.schemas.customer import CustomerInDB


def _customer_to_log_value(orm: Customer) -> dict:
    return CustomerInDB.model_validate(orm).model_dump(mode="json")


async def update_customer_by_id(
    db: AsyncSession,
    customer_id: int,
    fields: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    """
    根据 customer_id 更新客户字段，写 AuditLog。
    fields 仅包含要更新的键值（如 name, company, contact）。
    若提供 operator_user_id（如飞书 bound_user_id），仅允许修改该用户名下的客户。
    返回 {"success": True, "execution_summary": "已更新客户"} 或 {"success": False, "error": "..."}。
    """
    orm = await db.get(Customer, customer_id)
    if not orm:
        return {"success": False, "message": f"客户 {customer_id} 不存在"}
    if operator_user_id is not None and orm.owner_user_id != operator_user_id:
        return {"success": False, "message": "无权限操作该客户或客户不存在"}

    old_value = _customer_to_log_value(orm)

    for key, value in fields.items():
        if key in ("customer_id", "id"):
            continue
        if hasattr(orm, key):
            setattr(orm, key, value)

    await db.flush()
    await db.refresh(orm)
    new_value = _customer_to_log_value(orm)

    log = AuditLog(
        target_type=TARGET_TYPE_CUSTOMER,
        target_id=orm.id,
        action=ACTION_UPDATE,
        old_value=old_value,
        new_value=new_value,
        operator_source=operator_source,
        operator_external_id=operator_external_id,
    )
    db.add(log)
    await db.flush()

    return {
        "success": True,
        "result": {
            "customer_id": orm.id,
            "customer_name": (orm.name or "").strip(),
            "detail_url": f"/customers/{orm.id}",
        },
        "execution_summary": f"已更新客户【{(orm.name or '').strip()}】的信息，可前往客户详情页查看。",
    }
