"""#9 Reorganising Drive (M10): a plan of moves to the current layout, approved by Harjot, then applied.

Nothing moves silently. `build_plan` compares where each filed document sits with where layout v2 says it belongs
(its unit and tenant from the stored links, so a link the owner fixed counts and one he removed does not) and records
the differences as plan items. Harjot approves all or some; `apply_plan` then relocates the files. Every step is safe
to repeat: a relocation that already happened changes nothing, an item is marked once, and an item whose document
moved since the plan was made is skipped as stale.
"""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.db.enums import DocLinkKind, DocumentStatus, PersonKind, ReorgItemStatus, ReorgPlanStatus
from app.db.models import DocumentLink, DocumentRow, DriveReorgItem, DriveReorgPlan, Person, Unit
from app.pipeline.document_layout import LAYOUT_VERSION, UNSORTED, description, drive_properties, folder_path_v2
from app.pipeline.document_policy import name_date, parse_name, slug
from app.storage.drive import DriveApiError, DriveStore

log = get_logger(__name__)
_OPEN_ITEMS = (ReorgItemStatus.proposed, ReorgItemStatus.approved)


@dataclass(frozen=True)
class Target:
    folder: str
    name: str
    reason: str


def _best(session: Session, company_id: UUID, document_id: UUID, kind: DocLinkKind) -> list[UUID]:
    rows = session.scalars(
        select(DocumentLink.ref_id)
        .where(
            DocumentLink.company_id == company_id,
            DocumentLink.document_id == document_id,
            DocumentLink.kind == kind,
            DocumentLink.method != "removed",
        )
        .order_by(DocumentLink.score.desc(), DocumentLink.created_at)
    )
    return list(rows)


def target_for(session: Session, company_id: UUID, doc: DocumentRow) -> Target | None:
    """Where layout v2 puts this document now; None when its name does not follow the naming rule."""
    parsed = parse_name(doc.file_name)
    if parsed is None:
        return None
    day_text, kind, party, title, ext = parsed
    unit_ids = _best(session, company_id, doc.id, DocLinkKind.unit)
    unit_label = (
        session.scalar(select(Unit.label).where(Unit.id == unit_ids[0], Unit.company_id == company_id))
        if unit_ids
        else None
    )
    tenants = session.execute(
        select(Person.id, Person.display_name).where(
            Person.company_id == company_id,
            Person.kind == PersonKind.tenant,
            Person.id.in_(_best(session, company_id, doc.id, DocLinkKind.person)),
        )
    ).all()
    order = {pid: i for i, pid in enumerate(_best(session, company_id, doc.id, DocLinkKind.person))}
    tenant = min(tenants, key=lambda t: order[t[0]])[1] if tenants else None
    day = name_date(doc.file_name) or date.fromisoformat(day_text)
    folder = "/".join(folder_path_v2(doc.doc_type, unit_label, day))
    name = f"{day_text}_{kind}_{slug(tenant) if tenant else party}_{title}.{ext}"
    if (folder, name) == (doc.drive_folder, doc.file_name):
        return None
    where = f"unit {unit_label}" if unit_label else "no unit known yet"
    return Target(folder, name, f"layout {LAYOUT_VERSION}: {where}")


def build_plan(
    engine: Engine, company_id: UUID, created_by: str, document_ids: list[UUID] | None = None
) -> UUID | None:
    """A new plan with one item per filed document that is not where it belongs; None when nothing differs.
    Documents that already have an open item are left out, so two builds never double-plan a move."""
    with Session(engine) as session, session.begin():
        session.execute(
            select(func.pg_advisory_xact_lock(func.hashtext(f"drive-reorg:{company_id}")))
        )  # one builder at a time
        busy = select(DriveReorgItem.document_id).where(
            DriveReorgItem.company_id == company_id, DriveReorgItem.status.in_(_OPEN_ITEMS)
        )
        query = select(DocumentRow).where(
            DocumentRow.company_id == company_id,
            DocumentRow.status == DocumentStatus.filed,
            DocumentRow.drive_file_id.is_not(None),
            DocumentRow.drive_folder.is_not(None),
            DocumentRow.id.not_in(busy),
        )
        if document_ids is not None:
            query = query.where(DocumentRow.id.in_(document_ids))
        moves = [
            (d, t)
            for d in session.scalars(query.order_by(DocumentRow.created_at))
            if (t := target_for(session, company_id, d))
        ]
        if not moves:
            return None
        plan = DriveReorgPlan(company_id=company_id, layout_version=LAYOUT_VERSION, created_by=created_by)
        session.add(plan)
        session.flush()
        for doc, target in moves:
            session.add(
                DriveReorgItem(
                    company_id=company_id, plan_id=plan.id, document_id=doc.id,
                    from_folder=doc.drive_folder or "", to_folder=target.folder,
                    from_name=doc.file_name, to_name=target.name, reason=target.reason[:200],
                )
            )  # fmt: skip
        return plan.id


def decide_plan(
    engine: Engine, company_id: UUID, plan_id: UUID, approve: bool, item_ids: set[UUID] | None
) -> ReorgPlanStatus:
    """Harjot's choice on a proposed plan: all items, some of them (the rest are rejected), or none.
    A plan already decided keeps its status, so a double tap changes nothing."""
    with Session(engine) as session, session.begin():
        plan = session.scalar(
            select(DriveReorgPlan)
            .where(DriveReorgPlan.id == plan_id, DriveReorgPlan.company_id == company_id)
            .with_for_update()
        )
        if plan is None:
            raise NotFoundError(f"reorg plan {plan_id} not found")
        if plan.status is not ReorgPlanStatus.proposed:
            return plan.status
        items = list(
            session.scalars(
                select(DriveReorgItem).where(DriveReorgItem.plan_id == plan_id, DriveReorgItem.company_id == company_id)
            )
        )
        chosen = [i for i in items if approve and (item_ids is None or i.id in item_ids)]
        for item in items:
            item.status = ReorgItemStatus.approved if item in chosen else ReorgItemStatus.rejected
        plan.status = ReorgPlanStatus.approved if chosen else ReorgPlanStatus.rejected
        return plan.status


def _apply_item(engine: Engine, drive: DriveStore, company_id: UUID, item: DriveReorgItem) -> ReorgItemStatus:
    with Session(engine) as session:
        doc = session.scalar(
            select(DocumentRow).where(DocumentRow.id == item.document_id, DocumentRow.company_id == company_id)
        )
    if doc is None or doc.drive_file_id is None:
        return ReorgItemStatus.failed
    already = (doc.drive_folder, doc.file_name) == (item.to_folder, item.to_name)
    if not already and (doc.drive_folder, doc.file_name) != (item.from_folder, item.from_name):
        return ReorgItemStatus.failed  # stale: the document moved or was renamed after the plan was made
    try:
        folder_id = drive.ensure_folder(tuple(item.to_folder.split("/")))
        drive.relocate(doc.drive_file_id, folder_id, item.to_name)
        parts = item.to_folder.split("/")
        unit = parts[1] if len(parts) > 1 and parts[1] != UNSORTED else None
        named = parse_name(item.to_name)
        party = named[2] if named and named[2] != "unknown" else None
        day = name_date(item.to_name) or doc.created_at.date()
        drive.annotate(
            doc.drive_file_id, description(doc.title, doc.summary), drive_properties(doc.doc_type, unit, party, day)
        )
    except DriveApiError as exc:
        if exc.retryable:
            raise
        log.warning("documents.reorg_item_failed", item_id=str(item.id), status=exc.status)
        return ReorgItemStatus.failed
    with Session(engine) as session, session.begin():
        session.execute(
            update(DocumentRow)
            .where(DocumentRow.id == doc.id, DocumentRow.company_id == company_id)
            .values(drive_folder=item.to_folder, file_name=item.to_name)
        )
    return ReorgItemStatus.moved


def apply_plan(engine: Engine, drive: DriveStore, company_id: UUID, plan_id: UUID) -> dict[str, int]:
    """Relocate the approved items of an approved plan. Repeating it moves nothing twice; a transient Drive error
    propagates (the DBOS step retries) and the items already done stay done."""
    with Session(engine) as session:
        plan = session.scalar(
            select(DriveReorgPlan).where(DriveReorgPlan.id == plan_id, DriveReorgPlan.company_id == company_id)
        )
        if plan is None:
            raise NotFoundError(f"reorg plan {plan_id} not found")
        if plan.status not in (ReorgPlanStatus.approved, ReorgPlanStatus.applied):
            return {}
        items = list(session.scalars(select(DriveReorgItem).where(
            DriveReorgItem.plan_id == plan_id, DriveReorgItem.company_id == company_id,
            DriveReorgItem.status == ReorgItemStatus.approved).order_by(DriveReorgItem.created_at)))  # fmt: skip
    counts: dict[str, int] = {}
    for item in items:
        outcome = _apply_item(engine, drive, company_id, item)
        with Session(engine) as session, session.begin():
            mine = (DriveReorgItem.id == item.id) & (DriveReorgItem.company_id == company_id)
            session.execute(update(DriveReorgItem).where(mine).values(status=outcome))
        counts[outcome.value] = counts.get(outcome.value, 0) + 1
    with Session(engine) as session, session.begin():
        mine_plan = (DriveReorgPlan.id == plan_id) & (DriveReorgPlan.company_id == company_id)
        session.execute(
            update(DriveReorgPlan).where(mine_plan).values(status=ReorgPlanStatus.applied, applied_at=func.now())
        )
    log.info("documents.reorg_applied", plan_id=str(plan_id), **counts)
    return counts


@dataclass(frozen=True)
class PlanItemView:
    id: UUID
    document_id: UUID
    title: str
    from_folder: str
    to_folder: str
    from_name: str
    to_name: str
    reason: str
    status: ReorgItemStatus


@dataclass(frozen=True)
class PlanView:
    id: UUID
    status: ReorgPlanStatus
    created_by: str
    created_at: datetime
    items: list[PlanItemView]


def latest_plan(session: Session, company_id: UUID) -> PlanView | None:
    """The newest plan of the company with its items, whatever its status (the dashboard shows progress too)."""
    plan = session.scalar(
        select(DriveReorgPlan)
        .where(DriveReorgPlan.company_id == company_id)
        .order_by(DriveReorgPlan.created_at.desc())
        .limit(1)
    )
    if plan is None:
        return None
    rows = session.execute(
        select(DriveReorgItem, DocumentRow.title)
        .join(DocumentRow, DocumentRow.id == DriveReorgItem.document_id)
        .where(
            DriveReorgItem.plan_id == plan.id,
            DriveReorgItem.company_id == company_id,
            DocumentRow.company_id == company_id,
        )
        .order_by(DriveReorgItem.created_at, DriveReorgItem.id)
    ).all()
    items = [
        PlanItemView(i.id, i.document_id, title, i.from_folder, i.to_folder, i.from_name, i.to_name, i.reason, i.status)
        for i, title in rows
    ]
    return PlanView(plan.id, plan.status, plan.created_by, plan.created_at, items)
