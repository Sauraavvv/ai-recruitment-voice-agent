"""Create or reset a recruiter account. There is no public sign-up.

    python -m app.scripts.create_user --email you@example.com --name "Your Name" [--role admin]

The password is prompted for (never pass it on the command line). Running it again for an
existing email resets that user's password and re-activates the account; --role changes the
role only when it's given (new accounts default to recruiter). Admins may also change the
Google Sheet the candidates are copied to.
"""

import argparse
import asyncio
import getpass
import sys

from app.config import get_settings
from app.database.connection import dispose_engine, get_sessionmaker, init_engine
from app.database.models import User, UserRole
from app.repositories import user_repo
from app.services.auth_service import hash_password
from app.utils.candidate_fields import normalize_email

MIN_PASSWORD_LENGTH = 10


def _read_password() -> str:
    if not sys.stdin.isatty():
        # Allows `echo "$PASSWORD" | python -m app.scripts.create_user ...` in scripts.
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords don't match")
    return first


async def _save(email: str, name: str, password: str, role: str | None) -> str:
    init_engine(get_settings().database_url.get_secret_value())
    try:
        async with get_sessionmaker()() as session:
            user = await user_repo.get_by_email(session, email)
            if user is None:
                session.add(
                    User(
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
    args = parser.parse_args()

    try:
        email = normalize_email(args.email).lower()
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    password = _read_password()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    action = asyncio.run(_save(email, args.name.strip(), password, args.role))
    print(f"{action} account {email}" + (f" ({args.role})" if args.role else ""))


if __name__ == "__main__":
    main()
