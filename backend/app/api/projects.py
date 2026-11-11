"""
项目 CRUD API，并在 update/delete 时写入审计日志以支持撤销。
按 effective_user_id 隔离：列表/详情/创建/更新/删除/撤销均按归属用户。
"""
from datetime import date, datetime, timedelta, timezone
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field

from app.api.auth import get_current_user
from app.db.session import get_db
from app.models import AuditLog, Project, ACTION_DELETE, ACTION_UPDATE, TARGET_TYPE_PROJECT
from app.models.project_customer import ProjectCustomer
from app.models.calendar_event import CalendarEvent
from app.models.collaboration import ProjectCollaborator
from app.models.user import User
from app.schemas.project import (
    ProjectCreate,
    ProjectInDB,
    ProjectRead,
    ProjectUpdate,
    CustomerBrief,
    ProjectView,
    ProjectShareMembersView,
    MemberBrief,
)
from app.services.effective_user import (
    EffectiveUserContext,
    get_effective_user_context,
    require_effective_owner,
    write_data_access_denied_and_raise,
)
from app.services.project_owner_repair_queue_runtime import (
    ensure_project_owner_repair_queue_table,
    fetch_project_owner_repair_queue_for_project,
    list_project_owner_repair_queue_all,
)

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCustomersLinkBody(BaseModel):
    customer_ids: list[int] = Field(default_factory=list)


class OwnerRepairQueueItem(BaseModel):
    project_id: int
    owner_text: str | None = None
    reason: str
    created_at: datetime | None = None


class ResolveOwnerRepairBody(BaseModel):
    owner_user_id: int


class TransferInitiatorRequest(BaseModel):
    target_user_id: int


class LegacyMemberCleanupResponse(BaseModel):
    ok: bool
    removed: bool
    legacy_key: str


async def _get_next_project_no(db: AsyncSession) -> str:
    """生成下一个项目编号 P001, P002, ..."""
    result = await db.execute(
        select(Project.project_no).where(Project.project_no.isnot(None))
    )
    rows = result.scalars().all()
    max_n = 0
    for row in rows:
        no = row[0] if isinstance(row, (tuple, list)) else getattr(row, "project_no", row)
        if no and isinstance(no, str):
            m = re.match(r"^P(\d+)$", no.strip(), re.IGNORECASE)
            if m:
                max_n = max(max_n, int(m.group(1)))
    return f"P{max_n + 1:03d}"


def _project_to_log_value(orm: Project) -> dict:
    """将 Project ORM 转为可写入 AuditLog JSON 的字典。"""
    return ProjectInDB.model_validate(orm).model_dump(mode="json")


def _project_to_read(orm: Project) -> ProjectRead:
    """将 Project ORM 转为 ProjectRead（含 related_customers）。"""
    data = ProjectInDB.model_validate(orm).model_dump()
    related: list[CustomerBrief] = []
    for pc in (orm.project_customers or []):
        if pc.customer is None:
            continue
        item = CustomerBrief.model_validate(pc.customer).model_dump()
        item["owner_user_id"] = pc.customer.owner_user_id
        related.append(CustomerBrief(**item))
    return ProjectRead(**data, related_customers=related)


def _parse_project_old_value(data: dict) -> dict:
    """将 AuditLog 中的 JSON 日期字符串转为 Python 类型。"""
    out = dict(data)
    if out.get("deadline") and isinstance(out["deadline"], str):
        out["deadline"] = date.fromisoformat(out["deadline"].split("T")[0])
    if out.get("start_date") and isinstance(out["start_date"], str):
        out["start_date"] = date.fromisoformat(out["start_date"].split("T")[0])
    if out.get("update_date") and isinstance(out["update_date"], str):
        s = out["update_date"].replace("Z", "+00:00")
        out["update_date"] = datetime.fromisoformat(s)
    if out.get("start_time") and isinstance(out["start_time"], str):
        s = out["start_time"].replace("Z", "+00:00")
        out["start_time"] = datetime.fromisoformat(s)
    if out.get("deadline_at") and isinstance(out["deadline_at"], str):
        s = out["deadline_at"].replace("Z", "+00:00")
        out["deadline_at"] = datetime.fromisoformat(s)
    return out


def _set_project_from_dict(orm: Project, data: dict) -> None:
    """用字典（来自 AuditLog.old_value）覆盖 ORM 字段，跳过 id。"""
    parsed = _parse_project_old_value(data)
    for key, value in parsed.items():
        if key == "id":
            continue
        if hasattr(orm, key):
            setattr(orm, key, value)


@router.get("", response_model=list[ProjectView])
async def list_projects(
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """获取当前有效用户可见的项目列表。

    Source of truth:
    - 发起人: initiator_user_id
    - 负责人: owner_user_id
    - 协作者: project_collaborators
    """
    from app.services.collaboration_service import project_visible_filter
    result = await db.execute(
        select(Project)
        .where(project_visible_filter(ctx.effective_user_id))
        .order_by(Project.id)
        .options(
            selectinload(Project.project_customers).selectinload(ProjectCustomer.customer),
        )
    )
    projects = list(result.scalars().unique().all())
    user_ids = {p.initiator_user_id for p in projects if p.initiator_user_id is not None}
    user_name_map: dict[int, str] = {}
    if user_ids:
        users_res = await db.execute(select(User).where(User.id.in_(list(user_ids))))
        for u in users_res.scalars().all():
            user_name_map[int(u.id)] = (u.display_name or u.username or str(u.id))
    out = []
    for p in projects:
        d = _project_to_read(p).model_dump(mode="json")
        d["access_role"] = "owner" if p.owner_user_id == ctx.effective_user_id else "collaborator"
        d["is_initiator"] = p.initiator_user_id == ctx.effective_user_id
        d["is_owner"] = p.owner_user_id == ctx.effective_user_id
        d["initiator_display_name"] = user_name_map.get(p.initiator_user_id) if p.initiator_user_id is not None else None
        out.append(d)
    return out


@router.get("/owner-repair-queue", response_model=list[OwnerRepairQueueItem])
async def list_owner_repair_queue(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OwnerRepairQueueItem]:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看修复队列")
    rows = await list_project_owner_repair_queue_all(db)
    return [OwnerRepairQueueItem(**r) for r in rows]


@router.get("/selectable-users", response_model=list[dict])
async def list_project_selectable_users(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(
        select(User)
        .where(User.is_active.is_(True))
        .order_by(User.display_name.asc().nulls_last(), User.username.asc())
    )
    rows = list(result.scalars().all())
    return [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "role": u.role,
        }
        for u in rows
    ]


@router.post("/owner-repair-queue/{project_id}/resolve", response_model=dict)
async def resolve_owner_repair_queue_item(
    project_id: int,
    body: ResolveOwnerRepairBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可处理修复队列")
    owner_user = await db.get(User, int(body.owner_user_id))
    if owner_user is None or not owner_user.is_active:
        raise HTTPException(status_code=400, detail="负责人不存在或不可用")
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    project.owner_user_id = int(owner_user.id)
    project.owner = (owner_user.display_name or owner_user.username or "").strip() or project.owner
    project.update_date = datetime.now(timezone.utc)
    await ensure_project_owner_repair_queue_table(db)
    await db.execute(
        text("DELETE FROM project_owner_repair_queue WHERE project_id = :project_id"),
        {"project_id": project_id},
    )
    await db.flush()
    return {"success": True, "project_id": project_id, "owner_user_id": project.owner_user_id}


@router.get("/{project_id}", response_model=ProjectView)
async def get_project(
    project_id: int,
    request: Request,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """根据 id 获取单个项目详情（字段与列表契约一致）。"""
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.project_customers).selectinload(ProjectCustomer.customer),
        )
    )
    row = result.scalars().unique().one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="项目不存在")
    from app.services.collaboration_service import require_at_least_collaborator
    role = await require_at_least_collaborator(db, "project", project_id, ctx.effective_user_id)
    d = _project_to_read(row).model_dump(mode="json")
    owner_map = {
        pc.customer_id: (pc.customer.owner_user_id if pc.customer else None)
        for pc in (row.project_customers or [])
    }
    for c in d.get("related_customers", []):
        owner_id = owner_map.get(c.get("id"))
        c["owner_user_id"] = owner_id
        c["access_role"] = "owner" if owner_id == ctx.effective_user_id else "collaborator"
    d["access_role"] = role
    d["is_initiator"] = row.initiator_user_id == ctx.effective_user_id
    d["is_owner"] = row.owner_user_id == ctx.effective_user_id
    if row.initiator_user_id is not None:
        initiator = await db.get(User, int(row.initiator_user_id))
        if initiator is not None:
            d["initiator_display_name"] = (initiator.display_name or initiator.username or str(initiator.id))
    return d


@router.post("/{project_id}/customers/link", response_model=dict)
async def link_existing_customers(
    project_id: int,
    body: ProjectCustomersLinkBody,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """将一个或多个已有客户关联到当前项目（owner-only）。"""
    from app.models.customer import Customer
    from app.services.collaboration_service import require_owner as require_resource_owner, require_at_least_collaborator
    from app.services.audit_log_service import write_audit_log

    await require_resource_owner(db, "project", project_id, ctx.effective_user_id)
    project = await db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="项目不存在")

    customer_ids = list(dict.fromkeys(body.customer_ids or []))
    linked_count = 0
    skipped_existing_count = 0
    failed_ids: list[int] = []

    for cid in customer_ids:
        try:
            await require_at_least_collaborator(db, "customer", cid, ctx.effective_user_id)
            customer = await db.get(Customer, cid)
            if not customer:
                failed_ids.append(cid)
                continue
            existing = (
                await db.execute(
                    select(ProjectCustomer).where(
                        ProjectCustomer.project_id == project_id,
                        ProjectCustomer.customer_id == cid,
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if existing:
                skipped_existing_count += 1
                continue
            db.add(ProjectCustomer(project_id=project_id, customer_id=cid))
            linked_count += 1
            await write_audit_log(
                db,
                action="project_link_customer",
                actor_user_id=ctx.effective_user_id,
                target_type="project",
                target_id=str(project_id),
                detail=f"linked customer_id={cid} to project_id={project_id}",
                metadata_json={"project_id": project_id, "customer_id": cid, "mode": "from_project_detail"},
            )
            await write_audit_log(
                db,
                action="customer_link_project",
                actor_user_id=ctx.effective_user_id,
                target_type="customer",
                target_id=str(cid),
                detail=f"linked project_id={project_id} to customer_id={cid}",
                metadata_json={"project_id": project_id, "customer_id": cid, "mode": "from_project_detail"},
            )
        except HTTPException:
            failed_ids.append(cid)

    await db.flush()
    return {
        "success": True,
        "linked_count": linked_count,
        "skipped_existing_count": skipped_existing_count,
        "failed_ids": failed_ids,
    }


@router.delete("/{project_id}/customers/{customer_id}/link", response_model=dict)
async def unlink_customer_from_project(
    project_id: int,
    customer_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """解除项目与客户关联（仅删关系，不删实体，owner-only）。"""
    from app.services.collaboration_service import require_owner as require_resource_owner
    from app.services.audit_log_service import write_audit_log

    await require_resource_owner(db, "project", project_id, ctx.effective_user_id)
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
        action="project_unlink_customer",
        actor_user_id=ctx.effective_user_id,
        target_type="project",
        target_id=str(project_id),
        detail=f"unlinked customer_id={customer_id} from project_id={project_id}",
        metadata_json={"project_id": project_id, "customer_id": customer_id, "mode": "from_project_detail"},
    )
    await write_audit_log(
        db,
        action="customer_unlink_project",
        actor_user_id=ctx.effective_user_id,
        target_type="customer",
        target_id=str(customer_id),
        detail=f"unlinked project_id={project_id} from customer_id={customer_id}",
        metadata_json={"project_id": project_id, "customer_id": customer_id, "mode": "from_project_detail"},
    )
    return {"success": True, "removed": True}


@router.post("", response_model=ProjectRead, status_code=201)
async def create_project(
    body: ProjectCreate,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> ProjectRead:
    """创建项目。支持 customer_ids（多对多）或 customer_id（兼容）。归属当前有效用户。"""
    owner_user = await db.get(User, int(body.owner_user_id))
    if owner_user is None or not owner_user.is_active:
        raise HTTPException(status_code=400, detail="负责人不存在或不可用，请重新选择")
    target_owner_user_id = int(owner_user.id)
    owner_display = (owner_user.display_name or owner_user.username or "").strip() or body.owner

    project_no = body.project_no
    if not project_no or not str(project_no).strip():
        project_no = await _get_next_project_no(db)
    orm = Project(
        project_no=project_no.strip() if isinstance(project_no, str) else project_no,
        name=body.name,
        deadline=body.deadline,
        start_date=body.start_date,
        start_time=body.start_time,
        deadline_at=body.deadline_at,
        goal=body.goal,
        owner=owner_display,
        requirements=body.requirements,
        progress_text=body.progress_text,
        customer_name=body.customer_name,
        update_date=datetime.now(timezone.utc),
        owner_user_id=target_owner_user_id,
        initiator_user_id=ctx.effective_user_id,
    )
    if body.start_time is not None and orm.start_date is None:
        orm.start_date = body.start_time.date()
    if body.deadline_at is not None and orm.deadline is None:
        orm.deadline = body.deadline_at.date()
    db.add(orm)
    await db.flush()
    await db.refresh(orm)

    # 创建人与负责人不同时，保留创建人为协作者，避免创建后“看不到”
    if target_owner_user_id != ctx.effective_user_id:
        existing = (
            await db.execute(
                select(ProjectCollaborator).where(
                    ProjectCollaborator.project_id == orm.id,
                    ProjectCollaborator.user_id == ctx.effective_user_id,
                ).limit(1)
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                ProjectCollaborator(
                    project_id=orm.id,
                    user_id=ctx.effective_user_id,
                    created_by_user_id=ctx.effective_user_id,
                )
            )
            await db.flush()

    # 多对多 / 兼容单客户
    ids_to_link: list[int] = []
    if body.customer_ids is not None:
        ids_to_link = list(body.customer_ids)
    elif body.customer_id is not None:
        ids_to_link = [body.customer_id]
    if ids_to_link:
        for cid in ids_to_link:
            db.add(ProjectCustomer(project_id=orm.id, customer_id=cid))
        orm.customer_id = ids_to_link[0]
    await db.flush()

    # 自动创建日历日程（type=project）
    start_dt = datetime.now(timezone.utc)
    end_dt = datetime.now(timezone.utc)
    if body.start_time:
        start_dt = body.start_time
    elif body.start_date:
        start_dt = datetime(body.start_date.year, body.start_date.month, body.start_date.day, 0, 0, 0, tzinfo=timezone.utc)
    if body.deadline_at:
        end_dt = body.deadline_at
    elif body.deadline:
        end_dt = datetime(body.deadline.year, body.deadline.month, body.deadline.day, 23, 59, 59, tzinfo=timezone.utc)
    elif body.start_date:
        end_dt = datetime(body.start_date.year, body.start_date.month, body.start_date.day, 23, 59, 59, tzinfo=timezone.utc)
    else:
        end_dt = start_dt + timedelta(days=1)
    cal = CalendarEvent(
        title=body.name,
        description=None,
        start_time=start_dt,
        end_time=end_dt,
        type="project",
        project_id=orm.id,
        owner_user_id=target_owner_user_id,
    )
    db.add(cal)
    await db.flush()
    # 构建 ProjectRead.related_customers（已写入 project_customers）
    from app.models.customer import Customer
    related_customers = []
    if ids_to_link:
        cust_result = await db.execute(select(Customer).where(Customer.id.in_(ids_to_link)))
        for c in cust_result.scalars().all():
            related_customers.append(CustomerBrief.model_validate(c))
    data = ProjectInDB.model_validate(orm).model_dump()
    return ProjectRead(**data, related_customers=related_customers)


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ProjectRead:
    """更新项目（部分字段）；写入审计日志以便撤销。支持 customer_ids / customer_id。校验归属。"""
    orm = await db.get(Project, project_id)
    if not orm:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        await require_effective_owner(ctx, orm.owner_user_id, "project", str(project_id))
    except HTTPException as e:
        if e.status_code == 403:
            await write_data_access_denied_and_raise(
                ctx, orm.owner_user_id or 0, "project", str(project_id), request, db
            )
        raise

    old_value = _project_to_log_value(orm)

    update_data = body.model_dump(exclude_unset=True)
    customer_ids_param = update_data.pop("customer_ids", None)
    customer_id_param = update_data.pop("customer_id", None)
    owner_user_id_param = update_data.pop("owner_user_id", None)

    if owner_user_id_param is not None:
        owner_user = await db.get(User, int(owner_user_id_param))
        if owner_user is None or not owner_user.is_active:
            raise HTTPException(status_code=400, detail="负责人不存在或不可用，请重新选择")
        next_owner_user_id = int(owner_user.id)
        prev_owner_user_id = orm.owner_user_id
        orm.owner_user_id = next_owner_user_id
        update_data["owner"] = (owner_user.display_name or owner_user.username or "").strip() or update_data.get("owner")
        if prev_owner_user_id is not None and prev_owner_user_id != next_owner_user_id:
            existing_prev = (
                await db.execute(
                    select(ProjectCollaborator).where(
                        ProjectCollaborator.project_id == project_id,
                        ProjectCollaborator.user_id == prev_owner_user_id,
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if existing_prev is None:
                db.add(
                    ProjectCollaborator(
                        project_id=project_id,
                        user_id=prev_owner_user_id,
                        created_by_user_id=ctx.effective_user_id,
                    )
                )
    else:
        owner_name_param = update_data.get("owner")
        if isinstance(owner_name_param, str) and owner_name_param.strip():
            raise HTTPException(status_code=400, detail="请通过 owner_user_id 传递负责人")

    for key, value in update_data.items():
        setattr(orm, key, value)
    # 兼容：传 datetime 时同步 date 字段，避免旧逻辑显示空
    if body.start_time is not None:
        orm.start_date = body.start_time.date()
    if body.deadline_at is not None:
        orm.deadline = body.deadline_at.date()
    orm.update_date = datetime.now(timezone.utc)
    await db.flush()

    # 多对多 / 兼容单客户
    ids_to_link: list[int] | None = None
    if customer_ids_param is not None:
        ids_to_link = list(customer_ids_param)
    elif customer_id_param is not None:
        ids_to_link = [customer_id_param]
    if ids_to_link is not None:
        await db.execute(delete(ProjectCustomer).where(ProjectCustomer.project_id == project_id))
        for cid in ids_to_link:
            db.add(ProjectCustomer(project_id=project_id, customer_id=cid))
        orm.customer_id = ids_to_link[0] if ids_to_link else None
        await db.flush()

    await db.refresh(orm)
    new_value = _project_to_log_value(orm)

    log = AuditLog(
        target_type=TARGET_TYPE_PROJECT,
        target_id=project_id,
        action=ACTION_UPDATE,
        old_value=old_value,
        new_value=new_value,
    )
    db.add(log)
    await db.flush()

    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.project_customers).selectinload(ProjectCustomer.customer),
        )
    )
    orm_loaded = result.scalars().unique().one()
    return _project_to_read(orm_loaded)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> None:
    """删除项目；写入审计日志以便撤销。校验归属。"""
    orm = await db.get(Project, project_id)
    if not orm:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        await require_effective_owner(ctx, orm.owner_user_id, "project", str(project_id))
    except HTTPException as e:
        if e.status_code == 403:
            await write_data_access_denied_and_raise(
                ctx, orm.owner_user_id or 0, "project", str(project_id), request, db
            )
        raise

    old_value = _project_to_log_value(orm)
    log = AuditLog(
        target_type=TARGET_TYPE_PROJECT,
        target_id=project_id,
        action=ACTION_DELETE,
        old_value=old_value,
        new_value=None,
    )
    db.add(log)
    await db.delete(orm)
    await db.flush()
    return None


async def _undo_project_impl(
    db: AsyncSession,
    project_id: int,
    *,
    operator_source: str = "system",
    operator_external_id: str | None = None,
) -> Project:
    """内部实现：根据审计记录撤销项目（不做归属校验）。供 Web 路由（校验后调用）与飞书撤销链接使用。"""
    from sqlalchemy import desc
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.target_type == TARGET_TYPE_PROJECT, AuditLog.target_id == project_id)
        .order_by(desc(AuditLog.id))
        .limit(1)
    )
    log = result.scalar_one_or_none()
    if not log or not log.old_value:
        raise HTTPException(status_code=404, detail="无可撤销记录")
    parsed = _parse_project_old_value(log.old_value)
    owner_from_log = parsed.get("owner_user_id")
    initiator_from_log = parsed.get("initiator_user_id")

    if log.action == ACTION_DELETE:
        orm = Project(
            project_no=parsed.get("project_no"),
            name=parsed["name"],
            deadline=parsed.get("deadline"),
            start_date=parsed.get("start_date"),
            goal=parsed.get("goal"),
            owner=parsed.get("owner"),
            requirements=parsed.get("requirements"),
            customer_name=parsed.get("customer_name"),
            update_date=parsed.get("update_date") or datetime.now(timezone.utc),
            owner_user_id=owner_from_log,
            initiator_user_id=initiator_from_log or owner_from_log,
        )
        db.add(orm)
        await db.flush()
        await db.refresh(orm)
        db.add(
            AuditLog(
                target_type=TARGET_TYPE_PROJECT,
                target_id=orm.id,
                action=ACTION_UPDATE,
                old_value=None,
                new_value=_project_to_log_value(orm),
                operator_source=operator_source,
                operator_external_id=operator_external_id,
            )
        )
        await db.flush()
        return orm

    orm = await db.get(Project, project_id)
    if not orm:
        raise HTTPException(status_code=404, detail="项目已被删除，无法撤销该次更新")
    before = _project_to_log_value(orm)
    _set_project_from_dict(orm, log.old_value)
    orm.update_date = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(orm)
    db.add(
        AuditLog(
            target_type=TARGET_TYPE_PROJECT,
            target_id=orm.id,
            action=ACTION_UPDATE,
            old_value=before,
            new_value=_project_to_log_value(orm),
            operator_source=operator_source,
            operator_external_id=operator_external_id,
        )
    )
    await db.flush()
    return orm


@router.post("/{project_id}/undo", response_model=ProjectInDB)
async def undo_project(
    project_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
    *,
    operator_source: str = "system",
    operator_external_id: str | None = None,
) -> Project:
    """根据该项目最新一条审计记录恢复数据（仅对 update 有效；delete 后请使用全局 undo）。校验归属。"""
    orm = await db.get(Project, project_id)
    if orm:
        try:
            await require_effective_owner(ctx, orm.owner_user_id, "project", str(project_id))
        except HTTPException as e:
            if e.status_code == 403:
                await write_data_access_denied_and_raise(
                    ctx, orm.owner_user_id or 0, "project", str(project_id), request, db
                )
            raise
    else:
        result = await db.execute(
            select(AuditLog)
            .where(AuditLog.target_type == TARGET_TYPE_PROJECT, AuditLog.target_id == project_id)
            .order_by(desc(AuditLog.id))
            .limit(1)
        )
        log = result.scalar_one_or_none()
        if not log or not log.old_value:
            raise HTTPException(status_code=404, detail="无可撤销记录")
        if log.action == ACTION_DELETE:
            parsed = _parse_project_old_value(log.old_value)
            owner_from_log = parsed.get("owner_user_id")
            if owner_from_log is not None and owner_from_log != ctx.effective_user_id:
                await write_data_access_denied_and_raise(
                    ctx, owner_from_log, "project", str(project_id), request, db
                )
    from sqlalchemy import desc
    return await _undo_project_impl(db, project_id, operator_source=operator_source, operator_external_id=operator_external_id)


# ── 协作者管理（仅 owner） ──────────────────────────

from app.schemas.collaboration import CollaboratorAdd, CollaboratorOut, ProjectActivityCreate, ProjectActivityOut, TransferOwnerRequest
from app.services.collaboration_service import (
    add_project_collaborator,
    remove_project_collaborator,
    list_project_collaborators,
    require_owner as require_resource_owner,
    require_at_least_collaborator,
    add_project_activity,
    list_project_activities,
    delete_project_activity,
    transfer_project_owner as transfer_project_owner_svc,
)
from app.services.audit_log_service import write_audit_log


@router.get("/{project_id}/collaborators", response_model=list[CollaboratorOut])
async def get_collaborators(
    project_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await require_at_least_collaborator(db, "project", project_id, ctx.effective_user_id)
    return await list_project_collaborators(db, project_id)


@router.get("/{project_id}/share-members", response_model=ProjectShareMembersView)
async def get_share_members(
    project_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_at_least_collaborator(db, "project", project_id, ctx.effective_user_id)
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    def _user_payload(u: User | None) -> MemberBrief | None:
        if u is None:
            return None
        return MemberBrief(**{
            "user_id": u.id,
            "display_name": (u.display_name or u.username or str(u.id)),
            "username": u.username,
            "is_active": u.is_active,
        })

    initiator_user = await db.get(User, int(project.initiator_user_id)) if project.initiator_user_id else None
    owner_user = await db.get(User, int(project.owner_user_id)) if project.owner_user_id else None
    collaborators = await list_project_collaborators(db, project_id)
    filtered_collaborators = [
        c for c in collaborators
        if c.get("user_id") not in {project.initiator_user_id, project.owner_user_id}
    ]

    legacy_members: list[dict] = []
    queue_row = await fetch_project_owner_repair_queue_for_project(db, project_id)
    if queue_row is not None:
        legacy_members.append(
            {
                "legacy_key": "owner_text",
                "display_name": queue_row.get("owner_text") or "旧负责人文本",
                "reason": queue_row.get("reason") or "legacy_owner_text",
                "created_at": queue_row.get("created_at"),
            }
        )

    return {
        "initiator": _user_payload(initiator_user),
        "owner": _user_payload(owner_user),
        "collaborators": filtered_collaborators,
        "legacy_members": legacy_members,
    }


@router.post("/{project_id}/collaborators", response_model=CollaboratorOut, status_code=201)
async def post_collaborator(
    project_id: int,
    body: CollaboratorAdd,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_resource_owner(db, "project", project_id, ctx.effective_user_id)
    row = await add_project_collaborator(db, project_id, body.user_id, ctx.effective_user_id)
    await write_audit_log(
        db, action="project_add_collaborator", actor_user_id=ctx.effective_user_id,
        target_type="project", target_id=str(project_id),
        detail=f"added collaborator user_id={body.user_id}",
        metadata_json={"collaborator_user_id": body.user_id},
    )
    brief = await _get_user_brief_for_collab(db, row.user_id)
    return {"id": row.id, "user_id": row.user_id, "created_by_user_id": row.created_by_user_id, "created_at": row.created_at, **brief}


@router.delete("/{project_id}/collaborators/{user_id}", status_code=204)
async def del_collaborator(
    project_id: int,
    user_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_resource_owner(db, "project", project_id, ctx.effective_user_id)
    await remove_project_collaborator(db, project_id, user_id)
    await write_audit_log(
        db, action="project_remove_collaborator", actor_user_id=ctx.effective_user_id,
        target_type="project", target_id=str(project_id),
        detail=f"removed collaborator user_id={user_id}",
        metadata_json={"collaborator_user_id": user_id},
    )


@router.delete("/{project_id}/legacy-members/{legacy_key}", response_model=LegacyMemberCleanupResponse)
async def cleanup_legacy_member(
    project_id: int,
    legacy_key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LegacyMemberCleanupResponse:
    """清理旧成员数据（legacy member），不影响 owner/initiator/标准 collaborator。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if current_user.role != "admin" and current_user.id not in {project.owner_user_id, project.initiator_user_id}:
        raise HTTPException(status_code=403, detail="仅发起人/负责人/管理员可清理旧成员")
    if legacy_key != "owner_text":
        raise HTTPException(status_code=400, detail="不支持的 legacy_key")
    await ensure_project_owner_repair_queue_table(db)
    result = await db.execute(
        text("DELETE FROM project_owner_repair_queue WHERE project_id = :project_id"),
        {"project_id": project_id},
    )
    await db.flush()
    return LegacyMemberCleanupResponse(ok=True, removed=(result.rowcount or 0) > 0, legacy_key=legacy_key)


# ── 项目更新/进度（owner + collaborator 可添加） ──

@router.get("/{project_id}/updates", response_model=list[ProjectActivityOut])
async def get_updates(
    project_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await require_at_least_collaborator(db, "project", project_id, ctx.effective_user_id)
    return await list_project_activities(db, project_id)


@router.post("/{project_id}/updates", response_model=ProjectActivityOut, status_code=201)
async def post_update(
    project_id: int,
    body: ProjectActivityCreate,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_at_least_collaborator(db, "project", project_id, ctx.effective_user_id)
    row = await add_project_activity(db, project_id, ctx.effective_user_id, body.content, body.update_type)
    await write_audit_log(
        db, action="project_add_update", actor_user_id=ctx.effective_user_id,
        target_type="project", target_id=str(project_id),
        detail=f"added {body.update_type} update",
    )
    from app.services.collaboration_service import _get_user_brief
    brief = await _get_user_brief(db, ctx.effective_user_id)
    return {
        "id": row.id, "project_id": row.project_id, "author_user_id": row.author_user_id,
        "content": row.content, "update_type": row.update_type, "created_at": row.created_at,
        "author_display_name": brief.get("display_name"),
    }


@router.delete("/{project_id}/updates/{update_id}", status_code=204)
async def del_update(
    project_id: int,
    update_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_at_least_collaborator(db, "project", project_id, ctx.effective_user_id)
    await delete_project_activity(db, project_id, update_id, ctx.effective_user_id)
    await write_audit_log(
        db, action="project_delete_update", actor_user_id=ctx.effective_user_id,
        target_type="project", target_id=str(project_id),
        detail=f"deleted update id={update_id}",
        metadata_json={"update_id": update_id},
    )


@router.post("/{project_id}/transfer-owner")
async def transfer_owner(
    project_id: int,
    body: TransferOwnerRequest,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_resource_owner(db, "project", project_id, ctx.effective_user_id)
    result = await transfer_project_owner_svc(db, project_id, ctx.effective_user_id, body.target_user_id)
    await write_audit_log(
        db, action="project_transfer_owner", actor_user_id=ctx.effective_user_id,
        target_type="project", target_id=str(project_id),
        detail=f"transferred ownership to user_id={body.target_user_id}",
        metadata_json=result,
    )
    return {"ok": True, **result}


@router.post("/{project_id}/transfer-initiator")
async def transfer_initiator(
    project_id: int,
    body: TransferInitiatorRequest,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """转移发起人（initiator_user_id）。
    关键写操作必须经由业务接口与审计链路，不允许绕开服务层直接改库。
    """
    await require_resource_owner(db, "project", project_id, ctx.effective_user_id)
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    user = await db.get(User, int(body.target_user_id))
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail="目标发起人不存在或不可用")

    prev_initiator = project.initiator_user_id
    project.initiator_user_id = int(user.id)
    project.update_date = datetime.now(timezone.utc)
    if prev_initiator is not None and prev_initiator != project.initiator_user_id:
        existing_prev = (
            await db.execute(
                select(ProjectCollaborator).where(
                    ProjectCollaborator.project_id == project_id,
                    ProjectCollaborator.user_id == prev_initiator,
                ).limit(1)
            )
        ).scalar_one_or_none()
        if existing_prev is None:
            db.add(
                ProjectCollaborator(
                    project_id=project_id,
                    user_id=prev_initiator,
                    created_by_user_id=ctx.effective_user_id,
                )
            )
    await db.flush()
    await write_audit_log(
        db, action="project_transfer_initiator", actor_user_id=ctx.effective_user_id,
        target_type="project", target_id=str(project_id),
        detail=f"transferred initiator to user_id={body.target_user_id}",
        metadata_json={"target_user_id": body.target_user_id},
    )
    return {"ok": True, "project_id": project_id, "initiator_user_id": project.initiator_user_id}


async def _get_user_brief_for_collab(db: AsyncSession, user_id: int) -> dict:
    from app.services.collaboration_service import _get_user_brief
    return await _get_user_brief(db, user_id)
