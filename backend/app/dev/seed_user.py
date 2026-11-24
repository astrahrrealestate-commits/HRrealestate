"""CLI utility and helper to manage the allowed users whitelist in PostgreSQL."""

import argparse
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.models import AllowedUser, Company
from app.db.session import make_engine


def add_allowed_user(email: str, name: str = "", role: str = "manager", invited_by: str = "admin") -> bool:
    """Adds or updates an allowed user in the database whitelist."""
    clean_email = email.strip().lower()
    if not clean_email or "@" not in clean_email:
        print(f"Error: Invalid email format '{email}'")
        return False

    display_name = name.strip() or clean_email.split("@")[0].replace(".", " ").title()

    settings = get_settings()
    engine = make_engine(str(settings.database_url))

    with Session(engine) as session, session.begin():
        company = session.scalars(select(Company).limit(1)).first()
        if not company:
            print("Error: No company found in database. Run dev seed first.")
            return False

        existing = session.scalars(
            select(AllowedUser).where(AllowedUser.company_id == company.id, AllowedUser.email == clean_email)
        ).first()

        if existing:
            existing.is_active = True
            existing.display_name = display_name
            existing.role = role
            print(f"Updated allowed user: {clean_email} ({display_name}, role: {role})")
        else:
            new_user = AllowedUser(
                id=uuid4(),
                company_id=company.id,
                email=clean_email,
                display_name=display_name,
                role=role,
                is_active=True,
                invited_by=invited_by,
            )
            session.add(new_user)
            print(f"Added new allowed user: {clean_email} ({display_name}, role: {role})")

    return True


def list_allowed_users() -> list[dict[str, Any]]:
    """Returns all whitelisted users."""
    settings = get_settings()
    engine = make_engine(str(settings.database_url))

    with Session(engine) as session:
        users = session.scalars(select(AllowedUser).order_by(AllowedUser.email.asc())).all()
        return [
            {
                "id": str(u.id),
                "email": u.email,
                "name": u.display_name,
                "role": u.role,
                "is_active": u.is_active,
            }
            for u in users
        ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage EstateOS Allowed Users Whitelist")
    parser.add_argument("--add", help="Email to whitelist")
    parser.add_argument("--name", default="", help="Display name of user")
    parser.add_argument("--role", default="manager", help="Role (owner, manager, auditor)")
    parser.add_argument("--list", action="store_true", help="List all whitelisted users")

    args = parser.parse_args()

    if args.list:
        users = list_allowed_users()
        print(f"Total whitelisted users: {len(users)}")
        for u in users:
            status = "ACTIVE" if u["is_active"] else "DISABLED"
            print(f"  - [{status}] {u['email']} ({u['name']}) - Role: {u['role']}")
    elif args.add:
        add_allowed_user(args.add, name=args.name, role=args.role)
    else:
        # Default seed run (only Harjot, Suryansh, Astra, and Aditya)
        print("Seeding default allowed users...")
        add_allowed_user("harjot@estateos.internal", name="Harjot Singh", role="owner")
        add_allowed_user("tyagisurya.04@gmail.com", name="Suryansh Tyagi", role="owner")
        add_allowed_user("aditya@seedicon.com", name="Aditya", role="owner")
        add_allowed_user("astrahrrealestate@gmail.com", name="Astra Real Estate", role="owner")

        # Cleanup removed users
        settings = get_settings()
        engine = make_engine(str(settings.database_url))
        with Session(engine) as session, session.begin():
            for rm in [
                "vipint9902@gmail.com",
                "suryanstyagi.work@gmail.com",
                "chandan.p@fwc.co.in",
                "sambit.b@fwc.co.in",
                "avinash.p@fwc.co.in",
            ]:
                company = session.scalars(select(Company).limit(1)).first()  # the dev company, as add_allowed_user
                u = session.scalar(
                    select(AllowedUser).where(AllowedUser.company_id == company.id, AllowedUser.email == rm)
                    if company
                    else select(AllowedUser).where(AllowedUser.email == rm)
                )
                if u:
                    session.delete(u)
                    print(f"Removed '{rm}' from allowed users.")
