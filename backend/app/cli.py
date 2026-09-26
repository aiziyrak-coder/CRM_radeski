"""Admin CLI. Usage (on the server):

    docker compose -f docker-compose.prod.yml exec api \
        python -m app.cli create-user --username admin --full-name "Admin" --role admin

The password is read from the CRM_PASSWORD env var or prompted (never passed as an argument,
so it doesn't end up in shell history).
"""

import argparse
import asyncio
import getpass
import os
import sys

from pydantic import ValidationError

from app.core.db import SessionLocal
from app.modules.audit import service as audit
from app.modules.users import service
from app.modules.users.models import Role
from app.modules.users.schemas import UserCreate


def _read_password() -> str:
    if pw := os.environ.get("CRM_PASSWORD"):
        return pw
    pw = getpass.getpass("Parol: ")
    if pw != getpass.getpass("Parolni takrorlang: "):
        sys.exit("Parollar mos kelmadi")
    return pw


async def _create_user(args: argparse.Namespace) -> None:
    try:
        data = UserCreate(
            username=args.username,
            full_name=args.full_name,
            role=Role(args.role),
            password=_read_password(),
        )
    except ValidationError as exc:
        sys.exit(f"Xato: {exc}")

    async with SessionLocal() as session:
        try:
            user = await service.create_user(session, data)
        except service.UsernameTakenError:
            sys.exit(f"'{data.username}' allaqachon mavjud")
        audit.record(
            session,
            "user.create",
            entity="user",
            entity_id=user.id,
            after={**service.snapshot(user), "via": "cli"},
        )
        await session.commit()
    print(f"Yaratildi: {data.username} ({data.role})")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-user", help="yangi foydalanuvchi yaratish")
    create.add_argument("--username", required=True)
    create.add_argument("--full-name", required=True)
    create.add_argument("--role", required=True, choices=[r.value for r in Role])

    args = parser.parse_args()
    if args.command == "create-user":
        asyncio.run(_create_user(args))


if __name__ == "__main__":
    main()
