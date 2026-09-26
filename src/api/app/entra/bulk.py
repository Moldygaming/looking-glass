"""Parse Entra bulk-edit CSV without touching Graph or the database."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

MAX_ROWS = 200

ACTIONS = frozenset(
    {
        "create",
        "update",
        "enable",
        "disable",
        "reset_password",
        "add_groups",
        "remove_groups",
        "assign_licenses",
        "remove_licenses",
    }
)


@dataclass
class BulkRow:
    line: int
    action: str
    user_principal_name: str
    display_name: str = ""
    job_title: str = ""
    department: str = ""
    usage_location: str = ""
    password: str = ""
    template: str = ""
    groups: list[str] = field(default_factory=list)
    licenses: list[str] = field(default_factory=list)


def validate_usage_location(value: str) -> str:
    location = (value or "").strip().upper()
    if not location:
        return ""
    if len(location) != 2 or not location.isalpha():
        raise ValueError("Usage location must be a two-letter country code, for example GB")
    return location


def _split_list(value: str) -> list[str]:
    return [part.strip() for part in (value or "").replace("|", ";").split(";") if part.strip()]


def parse_bulk_csv(text: str) -> list[BulkRow]:
    raw = (text or "").lstrip("\ufeff").strip()
    if not raw:
        raise ValueError("CSV is empty")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        raise ValueError("CSV needs a header row")
    fields = {name.strip().lower(): name for name in reader.fieldnames if name and name.strip()}
    missing = [name for name in ("action", "user_principal_name") if name not in fields]
    if missing:
        raise ValueError("CSV header must include action and user_principal_name")

    rows: list[BulkRow] = []
    for index, record in enumerate(reader, start=2):
        if not record or all(not (value or "").strip() for value in record.values()):
            continue

        def column(key: str) -> str:
            header = fields.get(key)
            if not header:
                return ""
            return (record.get(header) or "").strip()

        rows.append(
            BulkRow(
                line=index,
                action=column("action").lower(),
                user_principal_name=column("user_principal_name"),
                display_name=column("display_name"),
                job_title=column("job_title"),
                department=column("department"),
                usage_location=column("usage_location"),
                password=column("password"),
                template=column("template"),
                groups=_split_list(column("groups")),
                licenses=_split_list(column("licenses")),
            )
        )
        if len(rows) > MAX_ROWS:
            raise ValueError(f"CSV is limited to {MAX_ROWS} rows")
    if not rows:
        raise ValueError("CSV has no data rows")
    return rows
