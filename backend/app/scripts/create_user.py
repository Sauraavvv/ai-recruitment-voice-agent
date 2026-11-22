"""Create or reset an account (until the super admin can add users in the app).

    python -m app.scripts.create_user --email you@example.com --name "Your Name" \
        [--role super_admin] [--organization "Acme Hiring"]

New accounts join the organization named by --organization (created if there is none with that
name); without it, the only organization there is (or a new "My organization" when there are
none). With several organizations, --organization is required.

The password is prompted for (never pass it on the command line). Running it again for an
existing email resets that user's password and re-activates the account; --role changes the
role only when it's given (new accounts default to recruiter).
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.connection import dispose_engine, get_sessionmaker, init_engine
from app.database.models import Organization, User, UserRole
from app.repositories import user_repo
from app.schemas.auth import MIN_PASSWORD_LENGTH
from app.services.auth_service import hash_password
from app.utils.candidate_fields import normalize_email


def _read_password() -> str:
    if not sys.stdin.isatty():
        # Allows `echo "$PASSWORD" | python -m app.scripts.create_user ...` in scripts.
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords don't match")
    return first


async def _organization(session: AsyncSession, name: str | None) -> Organization:
    if name:
        stmt = select(Organization).where(func.lower(Organization.name) == name.lower())
        found = (await session.execute(stmt)).scalars().first()
        return found or Organization(name=name)
    existing = (await session.execute(select(Organization).limit(2))).scalars().all()
    if len(existing) > 1:
        raise SystemExit("There are several organizations: pass --organization")
    return existing[0] if existing else Organization(name="My organization")


async def _save(
    email: str, name: str, password: str, role: str | None, organization: str | None
) -> str:
    init_engine(get_settings().database_url.get_secret_value())
    try:
        async with get_sessionmaker()() as session:
            user = await user_repo.get_by_email(session, email)
            if user is None:
                session.add(
                    User(
                        organization=await _organization(session, organization),
                        email=email,
                        name=name,
                        password_hash=hash_password(password),
                        role=role or UserRole.RECRUITER.value,
                    )
                )
                action = "Created"
            else:
                user.name = name
                user.password_hash = hash_password(password)
                user.is_active = True
                if role:
                    user.role = role
                action = "Updated"
            await session.commit()
            return action
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", choices=[r.value for r in UserRole], default=None)
    parser.add_argument("--organization", default=None, help="new accounts only")
    args = parser.parse_args()

    try:
        email = normalize_email(args.email).lower()
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    password = _read_password()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    action = asyncio.run(_save(email, args.name.strip(), password, args.role, args.organization))
    print(f"{action} account {email}" + (f" ({args.role})" if args.role else ""))


if __name__ == "__main__":
    main()
