#!/usr/bin/env python3
"""Check the payload enums against the repository's codebook policy.

The policy enforced here is the one the repository documents in the
military.xml header and the design record:

- The payload meaning enums are named slots into a shared eight-bit
  codebook, the extended binary Hamming [8,4,4] code. Every value in those
  enums MUST be a codebook word, and entry i (0-based, in file order)
  MUST carry codebook[i]. Slot 0 is therefore always 0x00, so a
  zero-filled field still reads as the enum's UNKNOWN / NONE anchor.
- The codebook is small (16 words, minimal pairwise distance 4) so a bit
  glitch on the wire lands off the codebook rather than on a different
  state. The words are not "close to" one another: 0x00 and 0x1E are 4
  bits apart, 0x1E and 0x27 are 4, 0x1E and 0x4B are 4, and so on. The
  full codebook is listed in the military.xml header where the payload
  enums are defined.
- The bitmask enums (PAYLOAD_STATUS_FLAGS) and the sensor registry
  (PAYLOAD_SENSOR_TYPE, which is also used as a bit index into the
  uint32_t readiness masks) are out of scope: their values are powers of
  two or slot indices, and renumbering them would move bits in masks
  that carriers already rely on.

Each violation is printed as "file:line: message"; under GitHub Actions
it is also an error annotation on that line of the pull request.

Exit status: 0 when every check passes, 1 with one line per violation.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from _helpers import Finding, parse, report

REPO_ROOT = Path(__file__).resolve().parents[3]

# The extended binary Hamming [8,4,4] codebook, sorted by value. Entry i
# of an in-scope enum carries codebook[i]; in particular entry 0 carries
# 0x00, which is the zero-fill / UNKNOWN / NONE anchor.
CODEBOOK = (0x00, 0x1E, 0x27, 0x39, 0x4B, 0x55, 0x6C, 0x72, 0x8D, 0x93,
            0xAA, 0xB4, 0xC6, 0xD8, 0xE1, 0xFF)
MIN_DISTANCE = 4


def codebook_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def check_codebook_shape() -> list[Finding]:
    """Sanity-check the codebook itself against the constants above."""
    errors = []
    if len(CODEBOOK) != 16:
        errors.append(Finding("codebook", 0, f"codebook must have 16 words (it has {len(CODEBOOK)})"))
        return errors
    if CODEBOOK[0] != 0x00:
        errors.append(Finding("codebook", 0, "codebook[0] must be 0x00 (the zero-fill anchor)"))
        return errors
    for i in range(len(CODEBOOK)):
        for j in range(i + 1, len(CODEBOOK)):
            d = codebook_distance(CODEBOOK[i], CODEBOOK[j])
            if d < MIN_DISTANCE:
                errors.append(
                    Finding(
                        "codebook", 0,
                        f"codebook[{i}] 0x{CODEBOOK[i]:02X} and codebook[{j}] "
                        f"0x{CODEBOOK[j]:02X} are only {d} bits apart "
                        f"(minimum distance is {MIN_DISTANCE})",
                    )
                )
    return errors


def check_enum(
    enum: ET.Element, lines: dict[ET.Element, int], file: str = "military.xml"
) -> list[Finding]:
    """One in-scope enum: entry i carries codebook[i]."""
    name = enum.get("name") or ""
    if name == "MAV_CMD" or enum.get("bitmask") == "true":
        return []
    if not name.startswith("MAVLINK_M_PAYLOAD_"):
        return []
    if name in ("MAVLINK_M_PAYLOAD_STATUS_FLAGS", "MAVLINK_M_PAYLOAD_SENSOR_TYPE"):
        return []
    errors = []
    entries = enum.findall("entry")
    for i, entry in enumerate(entries):
        raw = entry.get("value") or ""
        try:
            value = int(raw, 0)
        except ValueError:
            line = lines.get(entry, 0)
            errors.append(
                Finding(file, line,
                        f"{name} entry {i} ({entry.get('name') or ''}) has a non-numeric value {raw!r}")
            )
            continue
        expected = CODEBOOK[i]
        line = lines.get(entry, 0)
        if value != expected:
            errors.append(
                Finding(file, line,
                        f"{name} entry {i} ({entry.get('name') or ''}) has value 0x{value:02X}, "
                        f"but codebook[{i}] is 0x{expected:02X} — in-scope payload enums "
                        "must take their values from the extended Hamming [8,4,4] codebook "
                        "in file order")
            )
    return errors


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else REPO_ROOT
    path = root / "military.xml"
    root_el, lines = parse(path)
    errors = check_codebook_shape()
    for enum in root_el.findall("./enums/enum"):
        errors += check_enum(enum, lines, file=path.name)
    for e in errors:
        report(e, title="codebook policy")
    if errors:
        print(f"FAIL: {len(errors)} codebook violation(s)", file=sys.stderr)
        return 1
    print(
        f"PASS: {path.name}: every in-scope payload enum entry matches the "
        "extended Hamming [8,4,4] codebook slot-for-slot"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
