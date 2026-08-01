#!/usr/bin/env python3
"""Check the dialect files against this repository's allocation policy.

The policy enforced here is the one the repository documents in README.md,
IDMAPPING.md and the military.xml header, not a new one:

- Upstream MAVLink (all.xml) reserves message IDs 53000-53999 for this
  dialect.
- military.xml, the shared dialect, allocates messages and MAV_CMD entries
  from the shared window 53000-53899 (53000-53099 active, 53100-53899
  reserved for future shared growth).
- 53900-53999 is the private/downstream block: military.xml must never
  allocate from it, and military_extensions.xml, the downstream template,
  must allocate only from it.
- Message, enum and enum-entry names are UPPER_SNAKE_CASE and field names
  are lower_snake_case, matching MAVLink conventions.
- No duplicate message IDs or names inside a file, and the template must
  not collide with a shared message or enum name.

Structure beyond this policy (schema conformance, field types, duplicates
against common.xml) is owned by the schema check and by mavgen, which parse
the full include tree. This script runs on the Python standard library only
so it needs no checkout besides this repository.

Exit status: 0 when every check passes, 1 with one line per violation.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DIALECT_RESERVATION = range(53000, 54000)  # upstream all.xml reservation
SHARED_ALLOCATION = range(53000, 53900)  # military.xml draws from here
PRIVATE_ALLOCATION = range(53900, 54000)  # military_extensions.xml only

UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9_]*$")
LOWER_SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")


class Dialect:
    """The names and IDs one dialect file defines (includes not followed)."""

    def __init__(self, path: Path):
        self.path = path
        root = ET.parse(path).getroot()
        self.messages = [
            (int(m.get("id")), m.get("name")) for m in root.findall("./messages/message")
        ]
        self.enums = root.findall("./enums/enum")
        self.commands = [
            (int(e.get("value")), e.get("name"))
            for enum in self.enums
            if enum.get("name") == "MAV_CMD"
            for e in enum.findall("entry")
        ]
        self.fields = [
            (m.get("name"), f.get("name"))
            for m in root.findall("./messages/message")
            for f in m.findall("field")
        ]


def check_allocation(d: Dialect, allocation: range, label: str) -> list[str]:
    errors = []
    for kind, entries in (("message", d.messages), ("MAV_CMD entry", d.commands)):
        for value, name in entries:
            if value not in DIALECT_RESERVATION:
                errors.append(
                    f"{d.path.name}: {kind} {name} uses ID {value}, outside the "
                    f"53000-53999 block upstream all.xml reserves for this dialect"
                )
            elif value not in allocation:
                errors.append(
                    f"{d.path.name}: {kind} {name} uses ID {value}, outside the "
                    f"{label} allocation {allocation.start}-{allocation.stop - 1}"
                )
    return errors


def check_duplicates(d: Dialect) -> list[str]:
    errors = []
    for kind, entries in (("message ID", [i for i, _ in d.messages]),
                          ("message name", [n for _, n in d.messages]),
                          ("MAV_CMD value", [v for v, _ in d.commands])):
        seen: set = set()
        for item in entries:
            if item in seen:
                errors.append(f"{d.path.name}: duplicate {kind} {item}")
            seen.add(item)
    return errors


def check_naming(d: Dialect) -> list[str]:
    errors = []
    for _, name in d.messages:
        if not UPPER_SNAKE.match(name or ""):
            errors.append(f"{d.path.name}: message name {name} is not UPPER_SNAKE_CASE")
    for enum in d.enums:
        enum_name = enum.get("name") or ""
        if not UPPER_SNAKE.match(enum_name):
            errors.append(f"{d.path.name}: enum name {enum_name} is not UPPER_SNAKE_CASE")
        for entry in enum.findall("entry"):
            entry_name = entry.get("name") or ""
            if not UPPER_SNAKE.match(entry_name):
                errors.append(
                    f"{d.path.name}: enum entry {entry_name} is not UPPER_SNAKE_CASE"
                )
    for message_name, field_name in d.fields:
        if not LOWER_SNAKE.match(field_name or ""):
            errors.append(
                f"{d.path.name}: field {message_name}.{field_name} is not lower_snake_case"
            )
    return errors


def check_template_collisions(shared: Dialect, template: Dialect) -> list[str]:
    errors = []
    shared_ids = {i for i, _ in shared.messages}
    shared_names = {n for _, n in shared.messages}
    shared_enums = {e.get("name") for e in shared.enums} - {"MAV_CMD"}
    for msg_id, name in template.messages:
        if msg_id in shared_ids:
            errors.append(
                f"{template.path.name}: message {name} reuses shared dialect ID {msg_id}"
            )
        if name in shared_names:
            errors.append(
                f"{template.path.name}: message name {name} collides with the shared dialect"
            )
    for enum in template.enums:
        if enum.get("name") in shared_enums:
            errors.append(
                f"{template.path.name}: enum {enum.get('name')} collides with the shared dialect"
            )
    return errors


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else REPO_ROOT
    shared = Dialect(root / "military.xml")
    template = Dialect(root / "military_extensions.xml")

    errors = []
    errors += check_allocation(shared, SHARED_ALLOCATION, "shared")
    errors += check_allocation(template, PRIVATE_ALLOCATION, "private/downstream")
    for dialect in (shared, template):
        errors += check_duplicates(dialect)
        errors += check_naming(dialect)
    errors += check_template_collisions(shared, template)

    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        print(f"FAIL: {len(errors)} policy violation(s)", file=sys.stderr)
        return 1

    print(
        f"PASS: {shared.path.name}: {len(shared.messages)} messages and "
        f"{len(shared.commands)} MAV_CMD entries inside "
        f"{SHARED_ALLOCATION.start}-{SHARED_ALLOCATION.stop - 1}; "
        f"{template.path.name}: {len(template.messages)} template messages inside "
        f"{PRIVATE_ALLOCATION.start}-{PRIVATE_ALLOCATION.stop - 1}; "
        "naming and duplicate checks clean"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
