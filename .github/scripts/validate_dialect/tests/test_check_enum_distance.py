#!/usr/bin/env python3
"""Tests for check_enum_distance.py, on small dialects in a temporary directory.

From the repository root:

    python3 -m unittest discover --start-directory .github/scripts/validate_dialect/tests
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_enum_distance as distance  # noqa: E402


GOOD = """<?xml version="1.0"?>
<mavlink>
  <enums>
    <enum name="MAVLINK_M_PAYLOAD_STATUS">
      <description>Test lifecycle enum.</description>
      <entry value="0x00" name="MAVLINK_M_PAYLOAD_STATUS_UNKNOWN"><description>slot 0.</description></entry>
      <entry value="0x1E" name="MAVLINK_M_PAYLOAD_STATUS_IDLE"><description>slot 1.</description></entry>
      <entry value="0x27" name="MAVLINK_M_PAYLOAD_STATUS_SST"><description>slot 2.</description></entry>
      <entry value="0x39" name="MAVLINK_M_PAYLOAD_STATUS_DISARMED"><description>slot 3.</description></entry>
    </enum>
    <enum name="MAVLINK_M_PAYLOAD_STATE_CHANGE_REQUEST">
      <description>Test control enum.</description>
      <entry value="0x00" name="MAVLINK_M_PAYLOAD_STATE_CHANGE_REQUEST_NONE"><description>slot 0.</description></entry>
      <entry value="0x1E" name="MAVLINK_M_PAYLOAD_STATE_CHANGE_REQUEST_DISARM"><description>slot 1.</description></entry>
      <entry value="0x27" name="MAVLINK_M_PAYLOAD_STATE_CHANGE_REQUEST_ARM"><description>slot 2.</description></entry>
    </enum>
    <enum name="MAVLINK_M_PAYLOAD_STATUS_FLAGS" bitmask="true">
      <entry value="0x01" name="MAVLINK_M_PAYLOAD_FLAG_BUSY"><description>Busy.</description></entry>
      <entry value="0x02" name="MAVLINK_M_PAYLOAD_FLAG_FAULT"><description>Fault.</description></entry>
    </enum>
    <enum name="MAVLINK_M_PAYLOAD_SENSOR_TYPE">
      <entry value="0" name="MAVLINK_M_PAYLOAD_SENSOR_UNKNOWN"><description>Unknown.</description></entry>
      <entry value="1" name="MAVLINK_M_PAYLOAD_SENSOR_TEMP"><description>Temperature.</description></entry>
      <entry value="17" name="MAVLINK_M_PAYLOAD_SENSOR_NL_CHAFF"><description>Chaff.</description></entry>
    </enum>
  </enums>
  <messages>
    <message id="53030" name="PAYLOAD_STATE">
      <field type="uint8_t" name="payload_state">State.</field>
    </message>
  </messages>
</mavlink>
"""


class DistanceTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def check(self, shared: str = GOOD):
        (self.root / "military.xml").write_text(shared, encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = distance.main(["check_enum_distance.py", str(self.root)])
        return status, out.getvalue(), err.getvalue()

    def test_clean_passes(self) -> None:
        status, out, err = self.check()
        self.assertEqual(status, 0)
        self.assertEqual(err, "")
        self.assertIn("PASS: military.xml", out)

    def test_value_outside_codebook_fails(self) -> None:
        bad = GOOD.replace(
            '<entry value="0x27" name="MAVLINK_M_PAYLOAD_STATUS_SST">',
            '<entry value="2" name="MAVLINK_M_PAYLOAD_STATUS_SST">',
        )
        self.assertNotEqual(bad, GOOD)
        status, _, err = self.check(bad)
        self.assertEqual(status, 1)
        self.assertIn("MAVLINK_M_PAYLOAD_STATUS entry 2", err)
        self.assertIn("codebook[2] is 0x27", err)

    def test_anchor_not_zero_fails(self) -> None:
        bad = GOOD.replace(
            '<entry value="0x00" name="MAVLINK_M_PAYLOAD_STATUS_UNKNOWN">',
            '<entry value="0x1E" name="MAVLINK_M_PAYLOAD_STATUS_UNKNOWN">',
        )
        self.assertNotEqual(bad, GOOD)
        status, _, err = self.check(bad)
        self.assertEqual(status, 1)
        self.assertIn("entry 0", err)
        self.assertIn("codebook[0] is 0x00", err)

    def test_out_of_order_fails(self) -> None:
        # Swap slot 1 and slot 2 of MAVLINK_M_PAYLOAD_STATUS only. The
        # STATE_CHANGE_REQUEST enum (which also has 0x00/0x1E/0x27) stays
        # clean, so both failures should be attributed to STATUS.
        bad = GOOD.replace(
            '<entry value="0x1E" name="MAVLINK_M_PAYLOAD_STATUS_IDLE">',
            '<entry value="0x27" name="MAVLINK_M_PAYLOAD_STATUS_IDLE">',
        ).replace(
            '<entry value="0x27" name="MAVLINK_M_PAYLOAD_STATUS_SST">',
            '<entry value="0x1E" name="MAVLINK_M_PAYLOAD_STATUS_SST">',
        )
        self.assertNotEqual(bad, GOOD)
        status, _, err = self.check(bad)
        self.assertEqual(status, 1)
        self.assertIn("MAVLINK_M_PAYLOAD_STATUS entry 1", err)
        self.assertIn("MAVLINK_M_PAYLOAD_STATUS entry 2", err)
        self.assertIn("codebook[1] is 0x1E", err)
        self.assertIn("codebook[2] is 0x27", err)

    def test_bitmask_enum_is_scoped_out(self) -> None:
        # STATUS_FLAGS is a bitmask: powers of two, not codebook words.
        status, _, err = self.check()
        self.assertEqual(status, 0)
        self.assertNotIn("MAVLINK_M_PAYLOAD_STATUS_FLAGS", err)

    def test_sensor_type_is_scoped_out(self) -> None:
        # SENSOR_TYPE is dual-use (bit index in uint32_t masks); sequential.
        status, _, err = self.check()
        self.assertEqual(status, 0)
        self.assertNotIn("MAVLINK_M_PAYLOAD_SENSOR_TYPE", err)

    def test_non_payload_enums_are_scoped_out(self) -> None:
        extra = """
    <enum name="MAVLINK_M_TARGET_SENSOR_TYPE">
      <entry value="0" name="MAVLINK_M_TARGET_SENSOR_TYPE_UNKNOWN"><description>U.</description></entry>
      <entry value="1" name="MAVLINK_M_TARGET_SENSOR_TYPE_RWR"><description>R.</description></entry>
    </enum>
"""
        bad = GOOD.replace("  </enums>", extra + "  </enums>")
        self.assertNotEqual(bad, GOOD)
        status, _, err = self.check(bad)
        self.assertEqual(status, 0)
        self.assertNotIn("MAVLINK_M_TARGET_SENSOR_TYPE", err)

    def test_codebook_shape_check(self) -> None:
        # The codebook itself must be 16 words, anchored at 0, and with
        # every pair at least MIN_DISTANCE apart.
        errors = distance.check_codebook_shape()
        self.assertEqual(errors, [], [str(e) for e in errors])


if __name__ == "__main__":
    unittest.main()
