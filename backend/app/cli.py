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
from pathlib import Path

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


async def _import_legacy(args: argparse.Namespace) -> None:
    from app.importer.legacy import run_import

    data_dir = Path(args.dir)
    async with SessionLocal() as session:
        report = await run_import(session, data_dir, dry_run=args.dry_run)

    print("SINOV (bazaga yozilmadi)" if args.dry_run else "Import yakunlandi")
    for key, value in sorted(report.counts.items()):
        print(f"  {key:45} {value}")
    report_path = Path(args.report) if args.report else data_dir / "import-problems.csv"
    try:
        report.write_csv(report_path)
        print(f"Muammoli qatorlar: {len(report.problems)} -> {report_path}")
    except OSError as exc:
        print(f"Hisobotni yozib bo'lmadi ({exc}); muammoli qatorlar: {len(report.problems)}")


async def _sync_diagnoses() -> None:
    from app.modules.diagnoses import service as diagnoses

    async with SessionLocal() as session:
        counts = await diagnoses.sync(session)
        await session.commit()
    for key, value in sorted(counts.items()):
        print(f"  {key:30} {value}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-user", help="yangi foydalanuvchi yaratish")
    create.add_argument("--username", required=True)
    create.add_argument("--full-name", required=True)
    create.add_argument("--role", required=True, choices=[r.value for r in Role])

    imp = sub.add_parser("import-legacy", help="eski Excel bazasini import qilish")
    imp.add_argument("--dir", required=True, help="Excel fayllar turgan papka")
    imp.add_argument("--dry-run", action="store_true", help="faqat tekshirish, bazaga yozmaslik")
    imp.add_argument(
        "--report", help="muammoli qatorlar CSV fayli (standart: <dir>/import-problems.csv)"
    )

    sub.add_parser("sync-diagnoses", help="tashxislar uchun toifa takliflarini yangilash")

    args = parser.parse_args()
    if args.command == "create-user":
        asyncio.run(_create_user(args))
    elif args.command == "sync-diagnoses":
        asyncio.run(_sync_diagnoses())
    elif args.command == "import-legacy":
        if not Path(args.dir).is_dir():
            sys.exit(f"Papka topilmadi: {args.dir}")
        asyncio.run(_import_legacy(args))


if __name__ == "__main__":
    main()
