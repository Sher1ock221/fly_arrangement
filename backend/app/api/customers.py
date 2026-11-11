"""
客户 CRUD API，并在 update/delete 时写入审计日志以支持撤销。
支持客户详情（含项目与跟进记录）及跟进记录 CRUD。
按 effective_user_id 隔离：列表/详情/创建/更新/删除均按归属用户。
"""
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field

from app.db.session import get_db
from app.models import AuditLog, Customer, CustomerInteraction, Project
from app.models import ACTION_DELETE, ACTION_UPDATE, TARGET_TYPE_CUSTOMER
from app.models.project_customer import ProjectCustomer
from app.schemas.customer import (
    CustomerCreate,
    CustomerDetailRead,
    CustomerInDB,
    CustomerRead,
    CustomerUpdate,
)
from app.schemas.customer_interaction import (
    CustomerInteractionCreate,
    CustomerInteractionRead,
    CustomerInteractionUpdate,
)
from app.schemas.project import ProjectBriefForCustomer, CustomerBrief
from app.services.effective_user import (
    EffectiveUserContext,
    get_effective_user_context,
    require_effective_owner,
    write_data_access_denied_and_raise,
)

router = APIRouter(prefix="/customers", tags=["customers"])


class CustomerProjectsLinkBody(BaseModel):
    project_ids: list[int] = Field(default_factory=list)


def _customer_to_log_value(orm: Customer) -> dict:
    """将 Customer ORM 转为可写入 AuditLog JSON 的字典。"""
    return CustomerInDB.model_validate(orm).model_dump(mode="json")


def _set_customer_from_dict(orm: Customer, data: dict) -> None:
    """用字典（来自 AuditLog.old_value）覆盖 ORM 字段，跳过 id。"""
    for key, value in data.items():
        if key == "id":
            continue
        if hasattr(orm, key):
            setattr(orm, key, value)


@router.get("", response_model=list[dict])
async def list_customers(
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """获取当前有效用户的客户列表（含关联项目数、最近沟通时间）。owner + 共享给我的客户均可见。"""
    from app.services.collaboration_service import customer_visible_filter
    result = await db.execute(
        select(Customer).where(customer_visible_filter(ctx.effective_user_id)).order_by(Customer.id)
    )
    customers = list(result.scalars().all())
    if not customers:
        return []

    ids = [c.id for c in customers]
    # 每个客户关联的项目数（未软删且归属当前有效用户）：projects.customer_id ∪ project_customers
    proj_fk = await db.execute(
        select(Project.customer_id, Project.id).where(
            Project.customer_id.in_(ids),
            Project.is_deleted.is_(False),
            Project.owner_user_id == ctx.effective_user_id,
        )
    )
    proj_m2m = await db.execute(
        select(ProjectCustomer.customer_id, ProjectCustomer.project_id)
        .select_from(ProjectCustomer)
        .join(Project, Project.id == ProjectCustomer.project_id)
        .where(
            ProjectCustomer.customer_id.in_(ids),
            Project.is_deleted.is_(False),
            Project.owner_user_id == ctx.effective_user_id,
        )
    )
    distinct_projects: dict[int, set[int]] = defaultdict(set)
    for row in proj_fk.all():
        distinct_projects[row[0]].add(row[1])
    for row in proj_m2m.all():
        distinct_projects[row[0]].add(row[1])
    count_map = {cid: len(pids) for cid, pids in distinct_projects.items()}

    # 每个客户最近一次沟通时间
    last_q = (
        select(CustomerInteraction.customer_id, func.max(CustomerInteraction.meeting_time).label("last_at"))
        .where(CustomerInteraction.customer_id.in_(ids))
        .group_by(CustomerInteraction.customer_id)
    )
    last_result = await db.execute(last_q)
    last_map = {row[0]: row[1] for row in last_result.all()}

    out = []
    for c in customers:
        d = CustomerRead(
            **CustomerInDB.model_validate(c).model_dump(),
            project_count=count_map.get(c.id, 0),
            last_contact_at=last_map.get(c.id),
        ).model_dump(mode="json")
        d["access_role"] = "owner" if c.owner_user_id == ctx.effective_user_id else "collaborator"
        out.append(d)
    return out


@router.get("/{customer_id}", response_model=dict)
async def get_customer(
    customer_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> dict:
    """获取客户详情：基础信息 + 关联项目列表 + 沟通记录列表（按 meeting_time 倒序）。校验归属。"""
    orm = await db.get(Customer, customer_id)
    if not orm:
        raise HTTPException(status_code=404, detail="客户不存在")
    from app.services.collaboration_service import require_at_least_collaborator
    role = await require_at_least_collaborator(db, "customer", customer_id, ctx.effective_user_id)

    # 该客户关联的项目（未软删）：展示当前有效用户可见的项目（owner + collaborator）
    from app.services.collaboration_service import project_visible_filter
    proj_fk = await db.execute(
        select(Project)
        .where(
            Project.customer_id == customer_id,
            Project.is_deleted.is_(False),
            project_visible_filter(ctx.effective_user_id),
        )
        .order_by(Project.id)
        .options(
            selectinload(Project.project_customers).selectinload(ProjectCustomer.customer),
        )
    )
    proj_m2m = await db.execute(
        select(Project)
        .join(ProjectCustomer, ProjectCustomer.project_id == Project.id)
        .where(
            ProjectCustomer.customer_id == customer_id,
            Project.is_deleted.is_(False),
            project_visible_filter(ctx.effective_user_id),
        )
        .order_by(Project.id)
        .options(
            selectinload(Project.project_customers).selectinload(ProjectCustomer.customer),
        )
    )
    seen: set[int] = set()
    projects = []
    for p in list(proj_fk.scalars().all()) + list(proj_m2m.scalars().unique().all()):
        if p.id not in seen:
            seen.add(p.id)
            projects.append(p)
    projects.sort(key=lambda p: p.id)

    def to_brief(p: Project) -> ProjectBriefForCustomer:
        data = {
            "id": p.id,
            "project_no": p.project_no,
            "name": p.name,
            "status": p.status,
            "deadline": p.deadline,
            "owner": p.owner,
            "owner_user_id": p.owner_user_id,
            "access_role": "owner" if p.owner_user_id == ctx.effective_user_id else "collaborator",
        }
        related = [
            CustomerBrief.model_validate(pc.customer)
            for pc in (p.project_customers or [])
            if pc.customer is not None
        ]
        return ProjectBriefForCustomer(**data, related_customers=related)

    # 该客户的跟进记录，按 meeting_time 倒序
    int_result = await db.execute(
        select(CustomerInteraction)
        .where(CustomerInteraction.customer_id == customer_id)
        .order_by(desc(CustomerInteraction.meeting_time).nullslast(), desc(CustomerInteraction.id))
    )
    interactions = list(int_result.scalars().all())

    d = CustomerDetailRead(
        **CustomerInDB.model_validate(orm).model_dump(),
        projects=[to_brief(p) for p in projects],
        interactions=[CustomerInteractionRead.model_validate(i) for i in interactions],
    ).model_dump(mode="json")
    d["access_role"] = role
    return d


@router.post("/{customer_id}/projects/link", response_model=dict)
async def link_existing_projects(
    customer_id: int,
    body: CustomerProjectsLinkBody,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """将一个或多个已有项目关联到当前客户（owner-only）。"""
    from app.services.collaboration_service import require_owner as require_resource_owner, require_at_least_collaborator
    from app.services.audit_log_service import write_audit_log

    await require_resource_owner(db, "customer", customer_id, ctx.effective_user_id)
    customer = await db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")

    project_ids = list(dict.fromkeys(body.project_ids or []))
    linked_count = 0
    skipped_existing_count = 0
    failed_ids: list[int] = []

    for pid in project_ids:
        try:
            await require_at_least_collaborator(db, "project", pid, ctx.effective_user_id)
            project = await db.get(Project, pid)
            if not project or project.is_deleted:
                failed_ids.append(pid)
                continue
            existing = (
                await db.execute(
                    select(ProjectCustomer).where(
                        ProjectCustomer.project_id == pid,
                        ProjectCustomer.customer_id == customer_id,
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if existing:
                skipped_existing_count += 1
                continue
            db.add(ProjectCustomer(project_id=pid, customer_id=customer_id))
            linked_count += 1
            await write_audit_log(
                db,
                action="customer_link_project",
                actor_user_id=ctx.effective_user_id,
                target_type="customer",
                target_id=str(customer_id),
                detail=f"linked project_id={pid} to customer_id={customer_id}",
                metadata_json={"project_id": pid, "customer_id": customer_id, "mode": "from_customer_detail"},
            )
            await write_audit_log(
                db,
                action="project_link_customer",
                actor_user_id=ctx.effective_user_id,
                target_type="project",
                target_id=str(pid),
                detail=f"linked customer_id={customer_id} to project_id={pid}",
                metadata_json={"project_id": pid, "customer_id": customer_id, "mode": "from_customer_detail"},
            )
        except HTTPException:
            failed_ids.append(pid)

    await db.flush()
    return {
        "success": True,
        "linked_count": linked_count,
        "skipped_existing_count": skipped_existing_count,
        "failed_ids": failed_ids,
    }


@router.delete("/{customer_id}/projects/{project_id}/link", response_model=dict)
async def unlink_project_from_customer(
    customer_id: int,
    project_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """解除客户与项目关联（仅删关系，不删实体，owner-only）。"""
    from app.services.collaboration_service import require_owner as require_resource_owner
    from app.services.audit_log_service import write_audit_log

    await require_resource_owner(db, "customer", customer_id, ctx.effective_user_id)
    row = (
        await db.execute(
            select(ProjectCustomer).where(
                ProjectCustomer.project_id == project_id,
                ProjectCustomer.customer_id == customer_id,
            ).limit(1)
        )
    ).scalar_one_or_none()
    if not row:
        return {"success": True, "removed": False}

    await db.delete(row)
    await db.flush()
    await write_audit_log(
        db,
        action="customer_unlink_project",
        actor_user_id=ctx.effective_user_id,
        target_type="customer",
        target_id=str(customer_id),
        detail=f"unlinked project_id={project_id} from customer_id={customer_id}",
        metadata_json={"project_id": project_id, "customer_id": customer_id, "mode": "from_customer_detail"},
    )
    await write_audit_log(
        db,
        action="project_unlink_customer",
        actor_user_id=ctx.effective_user_id,
        target_type="project",
        target_id=str(project_id),
        detail=f"unlinked customer_id={customer_id} from project_id={project_id}",
        metadata_json={"project_id": project_id, "customer_id": customer_id, "mode": "from_customer_detail"},
    )
    return {"success": True, "removed": True}


@router.post("", response_model=CustomerInDB, status_code=201)
async def create_customer(
    body: CustomerCreate,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> Customer:
    """创建客户。归属当前有效用户。"""
    orm = Customer(
        name=body.name,
        origin=body.origin,
        company=body.company,
        profile=body.profile,
        contact=body.contact,
        future_direction=body.future_direction,
        position=body.position,
        business_direction=body.business_direction,
        notes=body.notes,
        acquaintance_source=body.acquaintance_source,
        owner_user_id=ctx.effective_user_id,
    )
    db.add(orm)
    await db.flush()
    await db.refresh(orm)
    return orm


@router.patch("/{customer_id}", response_model=CustomerInDB)
async def update_customer(
    customer_id: int,
    body: CustomerUpdate,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> Customer:
    """更新客户（部分字段）；写入审计日志以便撤销。校验归属。"""
    orm = await db.get(Customer, customer_id)
    if not orm:
        raise HTTPException(status_code=404, detail="客户不存在")
    try:
        await require_effective_owner(ctx, orm.owner_user_id, "customer", str(customer_id))
    except HTTPException as e:
        if e.status_code == 403:
            await write_data_access_denied_and_raise(
                ctx, orm.owner_user_id or 0, "customer", str(customer_id), request, db
            )
        raise

    old_value = _customer_to_log_value(orm)

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(orm, key, value)
    orm.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(orm)
    new_value = _customer_to_log_value(orm)

    log = AuditLog(
        target_type=TARGET_TYPE_CUSTOMER,
        target_id=customer_id,
        action=ACTION_UPDATE,
        old_value=old_value,
        new_value=new_value,
    )
    db.add(log)
    await db.flush()
    return orm


@router.delete("/{customer_id}", status_code=204)
async def delete_customer(
    customer_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> None:
    """删除客户；写入审计日志以便撤销。校验归属。"""
    orm = await db.get(Customer, customer_id)
    if not orm:
        raise HTTPException(status_code=404, detail="客户不存在")
    try:
        await require_effective_owner(ctx, orm.owner_user_id, "customer", str(customer_id))
    except HTTPException as e:
        if e.status_code == 403:
            await write_data_access_denied_and_raise(
                ctx, orm.owner_user_id or 0, "customer", str(customer_id), request, db
            )
        raise

    old_value = _customer_to_log_value(orm)
    log = AuditLog(
        target_type=TARGET_TYPE_CUSTOMER,
        target_id=customer_id,
        action=ACTION_DELETE,
        old_value=old_value,
        new_value=None,
    )
    db.add(log)
    await db.delete(orm)
    await db.flush()
    return None


@router.post("/{customer_id}/interactions", response_model=CustomerInteractionRead, status_code=201)
async def create_interaction(
    customer_id: int,
    body: CustomerInteractionCreate,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> CustomerInteraction:
    """新增客户沟通记录。校验客户归属。"""
    customer = await db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    from app.services.collaboration_service import require_at_least_collaborator
    await require_at_least_collaborator(db, "customer", customer_id, ctx.effective_user_id)
    orm = CustomerInteraction(
        customer_id=customer_id,
        meeting_time=body.meeting_time,
        talk_summary=body.talk_summary,
        cooperation_direction=body.cooperation_direction,
        cooperation_intent=body.cooperation_intent,
        next_cooperation_plan=body.next_cooperation_plan,
        specific_needs=body.specific_needs,
        importance=body.importance,
        source=body.source or "manual",
        raw_input=body.raw_input,
    )
    db.add(orm)
    await db.flush()
    await db.refresh(orm)
    return orm


@router.put("/{customer_id}/interactions/{interaction_id}", response_model=CustomerInteractionRead)
async def update_interaction(
    customer_id: int,
    interaction_id: int,
    body: CustomerInteractionUpdate,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> CustomerInteraction:
    """更新客户沟通记录。校验客户归属。"""
    orm = await db.get(CustomerInteraction, interaction_id)
    if not orm or orm.customer_id != customer_id:
        raise HTTPException(status_code=404, detail="跟进记录不存在")
    customer = await db.get(Customer, customer_id)
    if customer:
        await require_effective_owner(ctx, customer.owner_user_id, "customer", str(customer_id))
    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(orm, key, value)
    orm.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(orm)
    return orm


@router.delete("/{customer_id}/interactions/{interaction_id}", status_code=204)
async def delete_interaction(
    customer_id: int,
    interaction_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除客户沟通记录。校验客户归属。"""
    orm = await db.get(CustomerInteraction, interaction_id)
    if not orm or orm.customer_id != customer_id:
        raise HTTPException(status_code=404, detail="跟进记录不存在")
    customer = await db.get(Customer, customer_id)
    if customer:
        await require_effective_owner(ctx, customer.owner_user_id, "customer", str(customer_id))
    await db.delete(orm)
    await db.flush()
    return None


@router.post("/{customer_id}/undo", response_model=CustomerInDB)
async def undo_customer(
    customer_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> Customer:
    """根据该客户最新一条审计记录恢复数据（update 恢复旧值；delete 则重新插入）。校验归属。"""
    orm = await db.get(Customer, customer_id)
    if orm:
        try:
            await require_effective_owner(ctx, orm.owner_user_id, "customer", str(customer_id))
        except HTTPException as e:
            if e.status_code == 403:
                await write_data_access_denied_and_raise(
                    ctx, orm.owner_user_id or 0, "customer", str(customer_id), request, db
                )
            raise

    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.target_type == TARGET_TYPE_CUSTOMER, AuditLog.target_id == customer_id)
        .order_by(desc(AuditLog.id))
        .limit(1)
    )
    log = result.scalar_one_or_none()
    if not log or not log.old_value:
        raise HTTPException(status_code=404, detail="无可撤销记录")

    if log.action == ACTION_DELETE:
        owner_from_log = log.old_value.get("owner_user_id")
        if owner_from_log is not None and owner_from_log != ctx.effective_user_id:
            await write_data_access_denied_and_raise(
                ctx, owner_from_log, "customer", str(customer_id), request, db
            )
        orm = Customer(
            name=log.old_value["name"],
            origin=log.old_value.get("origin"),
            company=log.old_value.get("company"),
            profile=log.old_value.get("profile"),
            contact=log.old_value.get("contact"),
            future_direction=log.old_value.get("future_direction"),
            position=log.old_value.get("position"),
            business_direction=log.old_value.get("business_direction"),
            notes=log.old_value.get("notes"),
            acquaintance_source=log.old_value.get("acquaintance_source"),
            owner_user_id=owner_from_log if owner_from_log is not None else ctx.effective_user_id,
        )
        db.add(orm)
        await db.flush()
        await db.refresh(orm)
        return orm

    orm = await db.get(Customer, customer_id)
    if not orm:
        raise HTTPException(status_code=404, detail="客户已被删除，无法撤销该次更新")
    _set_customer_from_dict(orm, log.old_value)
    await db.flush()
    await db.refresh(orm)
    return orm


# ── 协作者管理（仅 owner） ──────────────────────────

from app.schemas.collaboration import CollaboratorAdd, CollaboratorOut, CustomerFollowupCreate, CustomerFollowupOut, TransferOwnerRequest
from app.services.collaboration_service import (
    add_customer_collaborator,
    remove_customer_collaborator,
    list_customer_collaborators,
    require_owner as require_resource_owner,
    require_at_least_collaborator as _require_at_least,
    add_customer_followup,
    list_customer_followups,
    delete_customer_followup,
    transfer_customer_owner as transfer_customer_owner_svc,
    _get_user_brief,
)
from app.services.audit_log_service import write_audit_log


@router.get("/{customer_id}/collaborators", response_model=list[CollaboratorOut])
async def get_customer_collaborators(
    customer_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _require_at_least(db, "customer", customer_id, ctx.effective_user_id)
    return await list_customer_collaborators(db, customer_id)


@router.post("/{customer_id}/collaborators", response_model=CollaboratorOut, status_code=201)
async def post_customer_collaborator(
    customer_id: int,
    body: CollaboratorAdd,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_resource_owner(db, "customer", customer_id, ctx.effective_user_id)
    row = await add_customer_collaborator(db, customer_id, body.user_id, ctx.effective_user_id)
    await write_audit_log(
        db, action="customer_add_collaborator", actor_user_id=ctx.effective_user_id,
        target_type="customer", target_id=str(customer_id),
        detail=f"added collaborator user_id={body.user_id}",
        metadata_json={"collaborator_user_id": body.user_id},
    )
    brief = await _get_user_brief(db, row.user_id)
    return {"id": row.id, "user_id": row.user_id, "created_by_user_id": row.created_by_user_id, "created_at": row.created_at, **brief}


@router.delete("/{customer_id}/collaborators/{user_id}", status_code=204)
async def del_customer_collaborator(
    customer_id: int,
    user_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_resource_owner(db, "customer", customer_id, ctx.effective_user_id)
    await remove_customer_collaborator(db, customer_id, user_id)
    await write_audit_log(
        db, action="customer_remove_collaborator", actor_user_id=ctx.effective_user_id,
        target_type="customer", target_id=str(customer_id),
        detail=f"removed collaborator user_id={user_id}",
        metadata_json={"collaborator_user_id": user_id},
    )


# ── 客户跟进（owner + collaborator 可添加） ────────

@router.get("/{customer_id}/followups", response_model=list[CustomerFollowupOut])
async def get_customer_followups(
    customer_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _require_at_least(db, "customer", customer_id, ctx.effective_user_id)
    return await list_customer_followups(db, customer_id)


@router.post("/{customer_id}/followups", response_model=CustomerFollowupOut, status_code=201)
async def post_customer_followup(
    customer_id: int,
    body: CustomerFollowupCreate,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _require_at_least(db, "customer", customer_id, ctx.effective_user_id)
    row = await add_customer_followup(db, customer_id, ctx.effective_user_id, body.content)
    await write_audit_log(
        db, action="customer_add_followup", actor_user_id=ctx.effective_user_id,
        target_type="customer", target_id=str(customer_id),
        detail="added followup",
    )
    brief = await _get_user_brief(db, ctx.effective_user_id)
    return {
        "id": row.id, "customer_id": row.customer_id, "author_user_id": row.author_user_id,
        "content": row.content, "created_at": row.created_at,
        "author_display_name": brief.get("display_name"),
    }


@router.delete("/{customer_id}/followups/{followup_id}", status_code=204)
async def del_customer_followup(
    customer_id: int,
    followup_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_at_least(db, "customer", customer_id, ctx.effective_user_id)
    await delete_customer_followup(db, customer_id, followup_id, ctx.effective_user_id)
    await write_audit_log(
        db, action="customer_delete_followup", actor_user_id=ctx.effective_user_id,
        target_type="customer", target_id=str(customer_id),
        detail=f"deleted followup id={followup_id}",
        metadata_json={"followup_id": followup_id},
    )


# ── ownership 转移 ────────────────────────────────


@router.post("/{customer_id}/transfer-owner")
async def transfer_customer_owner(
    customer_id: int,
    body: TransferOwnerRequest,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_resource_owner(db, "customer", customer_id, ctx.effective_user_id)
    result = await transfer_customer_owner_svc(db, customer_id, ctx.effective_user_id, body.target_user_id)
    await write_audit_log(
        db, action="customer_transfer_owner", actor_user_id=ctx.effective_user_id,
        target_type="customer", target_id=str(customer_id),
        detail=f"transferred ownership to user_id={body.target_user_id}",
        metadata_json=result,
    )
    return {"ok": True, **result}
