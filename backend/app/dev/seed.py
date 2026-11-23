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

        # Seed authorized users for platform login (only Harjot, Suryansh, Astra, and Aditya)
        default_allowed = [
            ("harjot@estateos.internal", "Harjot Singh", "owner"),
            ("tyagisurya.04@gmail.com", "Suryansh Tyagi", "owner"),
            ("aditya@seedicon.com", "Aditya", "owner"),
            ("astrahrrealestate@gmail.com", "Astra Real Estate", "owner"),
        ]
        for u_email, u_name, u_role in default_allowed:
            existing = session.scalar(
                select(AllowedUser).where(AllowedUser.company_id == company_id, AllowedUser.email == u_email)
            )
            if existing:
                existing.role = u_role
                existing.is_active = True
            else:
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

        # The dev sign-in ("Continue as dev owner") is the company's owner account: it needs a profile of its own,
        # or the whitelist above would sign it out (`access_for`). Nobody is reactivated, only missing rows added.
        for own in session.scalars(select(OwnerAccount).where(OwnerAccount.company_id == company_id)):
            own_email = (own.email or "").strip().lower()
            if (
                own_email
                and session.scalar(
                    select(AllowedUser.id).where(AllowedUser.company_id == company_id, AllowedUser.email == own_email)
                )
                is None
            ):
                session.add(
                    AllowedUser(
                        id=uuid4(),
                        company_id=company_id,
                        email=own_email,
                        display_name=own.display_name,
                        role="owner",
                        is_active=True,
                        invited_by="system",
                    )
                )

        # Remove non-staff accounts from login whitelist if previously seeded
        for removed_email in [
            "vipint9902@gmail.com",
            "suryanstyagi.work@gmail.com",
            "chandan.p@fwc.co.in",
            "sambit.b@fwc.co.in",
            "avinash.p@fwc.co.in",
        ]:
            to_remove = session.scalar(
                select(AllowedUser).where(AllowedUser.company_id == company_id, AllowedUser.email == removed_email)
            )
            if to_remove:
                session.delete(to_remove)

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


if __name__ == "__main__":
    from app.core.settings import get_settings
    from app.db.session import make_engine

    settings = get_settings()
    engine = make_engine(str(settings.database_url))
    tenant = seed_dev_tenant(engine)
    print(f"Successfully seeded tenant: company_id={tenant.company_id}")
