"""Idempotent dev tenant: one company with a WhatsApp number, a Gmail mailbox and owner Harjot (simulator + demo)."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.core.errors import UnsafeConfigurationError
from app.db.models import AllowedUser, ChannelAccount, Company, OwnerAccount
from app.dev import fixtures as fx


@dataclass(frozen=True)
class DevTenant:
    company_id: UUID
    whatsapp_account_id: UUID
    gmail_account_id: UUID


def seed_dev_tenant(
    engine: Engine,
    *,
    pnid: str = fx.DEV_PNID,
    mailbox: str = fx.DEV_MAILBOX,
    owner_e164: str = fx.DEV_OWNER_E164,
    owner_email: str = fx.DEV_OWNER_EMAIL,
) -> DevTenant:
    """Create what is missing, reuse what exists. Both endpoints must belong to the same company."""
    with Session(engine) as session, session.begin():
        wa, gm = _account(session, Channel.whatsapp, pnid), _account(session, Channel.gmail, mailbox)
        owners = {a.company_id for a in (wa, gm) if a is not None}
        if len(owners) > 1:
            raise UnsafeConfigurationError(f"{pnid} and {mailbox} belong to different companies")
        company_id = owners.pop() if owners else _new_company(session)
        wa = wa or _add(session, ChannelAccount(company_id=company_id, channel=Channel.whatsapp, address=pnid))
        gm = gm or _add(session, ChannelAccount(company_id=company_id, channel=Channel.gmail, address=mailbox))
        owner = session.scalar(
            select(OwnerAccount).where(OwnerAccount.company_id == company_id, OwnerAccount.whatsapp_e164 == owner_e164)
        )
        if owner is None:
            _add(
                session,
                OwnerAccount(
                    company_id=company_id, display_name=fx.DEV_OWNER_NAME, whatsapp_e164=owner_e164, email=owner_email
                ),
            )

        # Seed authorized users for platform login
        default_allowed = [
            ("harjot@estateos.internal", "Harjot Singh", "owner"),
            ("vipint9902@gmail.com", "Vipin Tyagi", "owner"),
            ("tyagisurya.04@gmail.com", "Surya Tyagi", "owner"),
            ("chandan.p@fwc.co.in", "Chandan P", "manager"),
            ("aditya@seedicon.com", "Aditya", "manager"),
            ("sambit.b@fwc.co.in", "Sambit B", "manager"),
            ("avinash.p@fwc.co.in", "Avinash P", "manager"),
        ]
        for u_email, u_name, u_role in default_allowed:
            exists = session.scalar(select(AllowedUser).where(AllowedUser.email == u_email))
            if not exists:
                session.add(
                    AllowedUser(
                        id=uuid4(),
                        company_id=company_id,
                        email=u_email,
                        display_name=u_name,
                        role=u_role,
                        is_active=True,
                        invited_by="system",
                    )
                )

        return DevTenant(company_id, wa.id, gm.id)


def _account(session: Session, channel: Channel, address: str) -> ChannelAccount | None:
    return session.scalar(
        select(ChannelAccount).where(ChannelAccount.channel == channel, ChannelAccount.address == address)
    )


def _new_company(session: Session) -> UUID:
    return _add(session, Company(name=fx.DEV_COMPANY)).id


def _add[T: (Company, ChannelAccount, OwnerAccount)](session: Session, row: T) -> T:
    session.add(row)
    session.flush()
    return row
