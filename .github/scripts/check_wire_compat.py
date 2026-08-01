#!/usr/bin/env python3
"""Report wire-format differences between two versions of military.xml.

A message's wire identity is its ID, its name and its CRC_EXTRA. CRC_EXTRA
is computed from the message name and the name, type and order of every
non-extension field, so any change a peer notices on the wire surfaces as a
CRC_EXTRA change, and a peer with a different CRC_EXTRA silently drops the
message. Both versions are parsed with pymavlink's own generator, the same
computation every consumer of this dialect runs, and the diff reports:

- messages removed, or renamed on an existing ID (renames also change the
  CRC, so the rename is called out by name)
- messages whose CRC_EXTRA changes: a field added, removed, retyped,
  reordered or renamed in the non-extension part of the payload
- messages added (informational; the policy check owns the allocation)

Changes confined to `<extensions>` fields keep CRC_EXTRA stable and are the
wire-compatible evolution path by design, so they are not reported.

The report is advisory by default: the dialect is under active development
and replacing a message body is at times the right call, so the job makes
the wire impact visible in the run log and step summary instead of vetoing
it. Set WIRE_COMPAT_ENFORCE=1 to turn breaking findings into a failure once
the dialect freezes.

Usage: check_wire_compat.py <base military.xml> <head military.xml>
Requires pymavlink importable, e.g. PYTHONPATH pointing at the directory
that contains a pymavlink checkout. Includes are not followed: CRC_EXTRA
depends only on what the file itself defines.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pymavlink.generator import mavparse


def wire_map(path: str) -> dict[int, tuple[str, int]]:
    xml = mavparse.MAVXML(path, wire_protocol_version=mavparse.PROTOCOL_2_0)
    return {m.id: (m.name, m.crc_extra) for m in xml.message}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    base = wire_map(argv[1])
    head = wire_map(argv[2])

    removed = [(i, base[i][0]) for i in sorted(base.keys() - head.keys())]
    added = [(i, head[i][0]) for i in sorted(head.keys() - base.keys())]
    breaking = []
    for msg_id in sorted(base.keys() & head.keys()):
        (base_name, base_crc), (head_name, head_crc) = base[msg_id], head[msg_id]
        if base_crc == head_crc and base_name == head_name:
            continue
        what = f"CRC_EXTRA {base_crc} -> {head_crc}"
        if base_name != head_name:
            what = f"renamed to {head_name}, {what}"
        breaking.append((msg_id, base_name, what))

    lines = []
    for msg_id, name in removed:
        lines.append(f"BREAKING: message {msg_id} {name} removed")
    for msg_id, name, what in breaking:
        lines.append(f"BREAKING: message {msg_id} {name}: {what}")
    for msg_id, name in added:
        lines.append(f"INFO: message {msg_id} {name} added")

    for line in lines:
        prefix = "::warning title=wire-format change::" if "BREAKING" in line else ""
        print(prefix + line)

    total_breaks = len(removed) + len(breaking)
    verdict = (
        f"{total_breaks} wire-breaking change(s), {len(added)} addition(s), "
        f"{len(base.keys() & head.keys()) - len(breaking)} message(s) untouched on the wire"
    )
    print(verdict)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary:
            summary.write("## Wire-compatibility report\n\n")
            if lines:
                summary.write("\n".join(f"- {line}" for line in lines))
                summary.write("\n\n")
            summary.write(f"{verdict}\n\n")
            if total_breaks:
                summary.write(
                    "A peer built from the base definitions silently drops these "
                    "messages. Deliberate while the dialect is under development; "
                    "downstream consumers pinning this repository must regenerate.\n"
                )

    if total_breaks and os.environ.get("WIRE_COMPAT_ENFORCE") == "1":
        print("WIRE_COMPAT_ENFORCE=1: failing on wire-breaking changes", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
