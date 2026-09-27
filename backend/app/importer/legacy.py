"""Loads the legacy Excel exports into patients (phase 0.4).

Idempotent: every imported row carries a reference (patients.legacy_ref, conditions.source),
so re-running the import skips what is already there. Phone-only sources (cold base,
psoriasis/vitiligo lists) are matched to existing patients by phone number.
"""

import csv
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import search_key
from app.importer.parsing import (
    ParsedPatient,
    district_from_filename,
    read_cold_phones,
    read_conditions,
    read_patient_list,
)
from app.modules.audit import service as audit
from app.modules.patients.constants import UNKNOWN_NAME
from app.modules.patients.models import (
    Patient,
    PatientCondition,
    PatientKind,
    PatientPhone,
    Source,
)

CHECK_TAG = "tekshirish-kerak"  # data problems an operator should fix when calling
NO_NAME_TAG = "ismsiz"
FLUSH_EVERY = 2000


@dataclass
class ImportReport:
    counts: Counter[str] = field(default_factory=Counter)
    problems: list[dict[str, str]] = field(default_factory=list)

    def problem(self, source: str, row: object, kind: str, detail: str) -> None:
        self.counts[f"problem:{kind}"] += 1
        self.problems.append({"source": source, "row": str(row), "problem": kind, "detail": detail})

    def write_csv(self, path: Path) -> None:
        with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel shows Cyrillic
            writer = csv.DictWriter(f, fieldnames=["source", "row", "problem", "detail"])
            writer.writeheader()
            writer.writerows(self.problems)


def find_files(data_dir: Path) -> dict[str, list[Path]]:
    xlsx = sorted(data_dir.glob("*.xlsx"))
    main = [p for p in xlsx if "за_весь_период" in p.name]
    return {
        "main": main,
        "district": [
            p for p in xlsx if p.name.startswith("Список_всех_пациентов") and p not in main
        ],
        "conditions": sorted(data_dir.glob("*ПСОРИАЗ*.xls*")),
        "cold": [p for p in xlsx if p.name.lower().startswith("nomer")],
    }


class _Importer:
    def __init__(self, session: AsyncSession, report: ImportReport) -> None:
        self.session = session
        self.report = report
        self.by_phone: dict[str, uuid.UUID] = {}  # number -> first live patient with it
        self.by_ref: dict[str, uuid.UUID] = {}  # legacy_ref -> patient
        self.by_identity: dict[tuple[str, object], uuid.UUID] = {}  # (name key, dob) -> patient
        self.condition_refs: set[str] = set()
        self.pending = 0

    async def load_existing(self) -> None:
        rows = await self.session.execute(
            select(PatientPhone.number, PatientPhone.patient_id)
            .join(Patient)
            .where(Patient.merged_into_id.is_(None))
        )
        for number, pid in rows:
            self.by_phone.setdefault(number, pid)
        rows = (
            await self.session.execute(
                select(
                    Patient.legacy_ref, Patient.id, Patient.search_key, Patient.birth_date,
                    Patient.merged_into_id,
                )
            )
        ).all()  # fmt: skip
        merged = {pid: into for _, pid, _, _, into in rows if into}

        def live(pid: uuid.UUID) -> uuid.UUID:
            """A card merged into another one is imported into that one (no duplicate comes back
            when the import is run again)."""
            seen = set()
            while pid in merged and pid not in seen:
                seen.add(pid)
                pid = merged[pid]
            return pid

        for ref, pid, _, _, _ in rows:
            if ref:
                self.by_ref[ref] = live(pid)
        # live cards first; a merged card's name + birth date still lead to the card it went into
        for _, pid, key, dob, _into in sorted(rows, key=lambda r: r[4] is not None):
            if key and dob:
                self.by_identity.setdefault((key, dob), live(pid))
        self.condition_refs = set(
            await self.session.scalars(
                select(PatientCondition.source).where(PatientCondition.source.like("import:%"))
            )
        )

    async def _added(self) -> None:
        self.pending += 1
        if self.pending >= FLUSH_EVERY:
            await self.session.flush()
            self.pending = 0

    def _add_condition(self, patient_id: uuid.UUID, text: str, ref: str, visit: str | None) -> None:
        if ref in self.condition_refs:
            return
        self.condition_refs.add(ref)
        self.session.add(
            PatientCondition(
                patient_id=patient_id, raw_text=text[:500], visit_type=visit, source=ref
            )
        )
        self.report.counts["conditions_added"] += 1

    async def _add_phone(self, patient_id: uuid.UUID, number: str) -> None:
        if self.by_phone.get(number) == patient_id:
            return
        existing = await self.session.scalar(
            select(PatientPhone.id).where(
                PatientPhone.patient_id == patient_id, PatientPhone.number == number
            )
        )
        if existing is None:
            self.session.add(PatientPhone(patient_id=patient_id, number=number, is_primary=False))
            self.report.counts["phones_added_to_existing"] += 1
        self.by_phone.setdefault(number, patient_id)

    async def patient_row(self, p: ParsedPatient, ref: str) -> uuid.UUID | None:
        label = f"{p.source}:{p.legacy_no}"
        for problem in p.problems:
            self.report.problem(label, p.row, problem, f"{p.full_name} | {p.raw_phone}")
        if "name_missing" in p.problems:
            self.report.counts["skipped_no_name"] += 1
            return None

        if ref in self.by_ref:
            self.report.counts[f"{p.source}:already_imported"] += 1
            return self.by_ref[ref]

        key = search_key(p.full_name)
        # the export lists some people twice (same name + birth date)
        same = self.by_identity.get((key, p.birth_date)) if p.birth_date else None
        if same:
            self.report.counts[f"{p.source}:same_person_merged"] += 1
            if p.phone:
                await self._add_phone(same, p.phone)
            self.by_ref[ref] = same
            return same

        tags = [CHECK_TAG] if p.problems else []
        notes = f"Eski bazadagi telefon: {p.raw_phone}" if p.raw_phone and not p.phone else None
        patient = Patient(
            id=uuid.uuid4(),
            full_name=p.full_name,
            search_key=key,
            birth_date=p.birth_date,
            gender=p.gender,
            address=p.address,
            district=p.district,
            kind=PatientKind.LEGACY,
            source=Source.IMPORT,
            tags=tags,
            notes=notes,
            legacy_ref=ref,
            phones=[PatientPhone(number=p.phone, is_primary=True)] if p.phone else [],
        )
        self.session.add(patient)
        self.report.counts[f"{p.source}:created"] += 1
        self.by_ref[ref] = patient.id
        if p.birth_date:
            self.by_identity[(key, p.birth_date)] = patient.id
        if p.phone:
            self.by_phone.setdefault(p.phone, patient.id)
        await self._added()
        return patient.id

    async def import_main(self, path: Path) -> None:
        for p in read_patient_list(path, "main"):
            # the "No" column is the row's identity across re-runs; without it the row number
            # stands in (reported: re-running with a different export can't match such rows)
            no = p.legacy_no or f"row{p.row}"
            if not p.legacy_no:
                self.report.problem("main", p.row, "number_missing", p.full_name)
            pid = await self.patient_row(p, f"main:{no}")
            if pid and p.diagnosis:
                self._add_condition(pid, p.diagnosis, f"import:main:{no}", None)

    async def import_district(self, path: Path) -> None:
        district = district_from_filename(path.name)
        if district is None:
            self.report.problem(path.name, "-", "district_file_unknown", path.name)
            return
        for p in read_patient_list(path, "district", district=district):
            pid = self.by_phone.get(p.phone) if p.phone else None
            if pid:
                patient = await self.session.get(Patient, pid)
                if patient and search_key(patient.full_name) == search_key(p.full_name):
                    patient.district = district  # the per-district list is authoritative
                    self.report.counts["district:confirmed"] += 1
                    continue
            no = p.legacy_no or f"row{p.row}"
            if not p.legacy_no:
                self.report.problem(district, p.row, "number_missing", p.full_name)
            await self.patient_row(p, f"district:{district}:{no}")

    async def import_conditions(self, path: Path) -> None:
        for c in read_conditions(path):
            ref = f"import:{c.sheet}:{c.row}"
            if c.phone is None:
                self.report.problem(f"conditions:{c.sheet}", c.row, "phone_invalid", c.raw_phone)
                continue
            pid = self.by_phone.get(c.phone)
            if pid is None:
                patient = Patient(
                    id=uuid.uuid4(),
                    full_name=UNKNOWN_NAME,
                    search_key=search_key(UNKNOWN_NAME),
                    kind=PatientKind.LEGACY,
                    source=Source.IMPORT,
                    tags=[NO_NAME_TAG],
                    legacy_ref=f"conditions:{c.sheet}:{c.row}",
                    phones=[PatientPhone(number=c.phone, is_primary=True)],
                )
                self.session.add(patient)
                pid = patient.id
                self.by_phone[c.phone] = pid
                self.report.counts["conditions:created_without_name"] += 1
                await self._added()
            else:
                self.report.counts["conditions:matched_patient"] += 1
            if c.diagnosis:
                self._add_condition(pid, c.diagnosis, ref, c.visit_type)

    async def import_cold(self, path: Path) -> None:
        for c in read_cold_phones(path):
            if c.phone is None:
                self.report.counts["cold:invalid_phone"] += 1
                continue
            if c.phone in self.by_phone:
                self.report.counts["cold:already_known"] += 1
                continue
            patient = Patient(
                id=uuid.uuid4(),
                full_name=UNKNOWN_NAME,
                search_key=search_key(UNKNOWN_NAME),
                kind=PatientKind.COLD,
                source=Source.COLD_BASE,
                tags=[],
                phones=[PatientPhone(number=c.phone, is_primary=True)],
            )
            self.session.add(patient)
            self.by_phone[c.phone] = patient.id
            self.report.counts["cold:created"] += 1
            await self._added()


async def run_import(
    session: AsyncSession, data_dir: Path, *, dry_run: bool = False
) -> ImportReport:
    """Imports everything found in data_dir in dependency order. Commits unless dry_run."""
    report = ImportReport()
    files = find_files(data_dir)
    for kind, paths in files.items():
        report.counts[f"files:{kind}"] = len(paths)

    importer = _Importer(session, report)
    await importer.load_existing()
    # order matters: named patients first, then lists that are matched to them by phone
    for path in files["main"]:
        await importer.import_main(path)
    await session.flush()
    for path in files["district"]:
        await importer.import_district(path)
    for path in files["conditions"]:
        await importer.import_conditions(path)
    await session.flush()
    for path in files["cold"]:
        await importer.import_cold(path)
    await session.flush()

    # key the new diagnoses and suggest categories for texts never seen before (phase 0.5)
    from app.modules.diagnoses import service as diagnoses

    for key, value in (await diagnoses.sync(session)).items():
        report.counts[f"diagnoses:{key}"] = value

    audit.record(session, "import.legacy", after={"dry_run": dry_run, **dict(report.counts)})
    if dry_run:
        await session.rollback()
    else:
        await session.commit()
    return report
