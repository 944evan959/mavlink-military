"""Internal helpers shared by the dialect check scripts in this directory.

The check scripts live side by side, run from the same workflow, and share
the same finding/report shape: a NamedTuple carrying a file, a line, and a
message, printed as "file:line: message", annotated as a GitHub Actions
error under CI. The line-tracking XML parser and the report() printer have
been identical between check_dialect_policy.py and check_enum_distance.py
since both were written; this module is the place they now live.

Import from the sibling scripts as:

    import _helpers
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NamedTuple
from xml.parsers import expat


class Finding(NamedTuple):
    """One policy violation, at a line of a dialect file."""

    file: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.message}"


def parse(path: Path) -> tuple[ET.Element, dict[ET.Element, int]]:
    """Parse an XML file, recording the line each element starts on.

    ElementTree keeps no line numbers, so this drives expat with an
    ElementTree builder and notes the parser's line at each start tag.
    """
    builder = ET.TreeBuilder()
    lines: dict[ET.Element, int] = {}
    parser = expat.ParserCreate()

    def start(tag: str, attrs: dict[str, str]) -> None:
        lines[builder.start(tag, attrs)] = parser.CurrentLineNumber

    parser.StartElementHandler = start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    with path.open("rb") as xml:
        parser.ParseFile(xml)
    return builder.close(), lines


def report(finding: Finding, title: str = "dialect policy") -> None:
    """Print a finding, as an annotation on its line when run by GitHub Actions."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        text = str(finding).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(
            f"::error file={finding.file},line={finding.line},title={title}::{text}",
            file=sys.stderr,
        )
    else:
        print(f"ERROR: {finding}", file=sys.stderr)
