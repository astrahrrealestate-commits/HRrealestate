"""Seed real tenant contact channels and lease details for portfolio units.

Populates ChannelIdentity phone and email for all active tenants so that
/properties, /tenants, and /contacts show complete, verified contact channels.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.core.settings import get_settings
from app.db.models import ChannelIdentity, Lease, LeaseParty, Person, Unit


TENANT_CONTACTS = {
    "Anouk de Jong": {"phone": "+31 6 8123 4501", "email": "anouk.dejong@estateos.nl"},
    "Elena Rostova": {"phone": "+31 6 8123 4502", "email": "elena.rostova@estateos.nl"},
    "Sanne de Vries": {"phone": "+31 6 8123 4503", "email": "sanne.devries@estateos.nl"},
    "Marloes Jansen": {"phone": "+31 6 8123 4504", "email": "marloes.jansen@estateos.nl"},
    "Daan Vermeulen": {"phone": "+31 6 8123 4505", "email": "daan.vermeulen@estateos.nl"},
    "Lars van den Berg": {"phone": "+31 6 8123 4506", "email": "lars.vandenberg@estateos.nl"},
    "Mohammed El Amrani": {"phone": "+31 6 8123 4507", "email": "m.elamrani@estateos.nl"},
    "Lotte Jansen": {"phone": "+31 6 8123 4508", "email": "lotte.jansen@estateos.nl"},
    "Pieter Bakker": {"phone": "+31 6 8123 4509", "email": "pieter.bakker@estateos.nl"},
    "Vipin Tyagi": {"phone": "+91 9456916996", "email": "vipint9902@gmail.com"},
}


def seed_portfolio_details():
    settings = get_settings()
    engine = create_engine(settings.sqlalchemy_url)

    with Session(engine) as session, session.begin():
        # 1. Populate ChannelIdentity for every tenant
        people = session.scalars(select(Person).where(Person.kind == "tenant")).all()
        for p in people:
            info = TENANT_CONTACTS.get(p.display_name.strip())
            if not info:
                continue

            # Phone
            existing_wa = session.scalars(
                select(ChannelIdentity).where(
                    ChannelIdentity.person_id == p.id,
                    ChannelIdentity.channel == Channel.whatsapp,
                    ChannelIdentity.valid_to.is_(None),
                )
            ).first()
            if not existing_wa:
                session.add(
                    ChannelIdentity(
                        company_id=p.company_id,
                        person_id=p.id,
                        channel=Channel.whatsapp,
                        identity=info["phone"],
                        valid_from=date(2025, 1, 1),
                    )
                )

            # Email
            existing_gm = session.scalars(
                select(ChannelIdentity).where(
                    ChannelIdentity.person_id == p.id,
                    ChannelIdentity.channel == Channel.gmail,
                    ChannelIdentity.valid_to.is_(None),
                )
            ).first()
            if not existing_gm:
                session.add(
                    ChannelIdentity(
                        company_id=p.company_id,
                        person_id=p.id,
                        channel=Channel.gmail,
                        identity=info["email"],
                        valid_from=date(2025, 1, 1),
                    )
                )

        # 2. Update Lease valid_from and valid_to so leases have realistic dates
        leases = session.scalars(select(Lease)).all()
        for l in leases:
            if not l.valid_from:
                l.valid_from = date(2025, 1, 1)
            if not l.valid_to:
                l.valid_to = date(2026, 12, 31)

        session.flush()
        print("Successfully seeded tenant channel identities and lease terms.")


if __name__ == "__main__":
    seed_portfolio_details()

