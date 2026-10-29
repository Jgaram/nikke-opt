"""실험 6 공용 형식(common.py)과 모듈 import 확인. 관리자 소유."""

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

EXP_DIR = Path(__file__).resolve().parent.parent / "experiments" / "06_control_menu"
if str(EXP_DIR) not in sys.path:
    sys.path.insert(0, str(EXP_DIR))

import common  # noqa: E402


class TestCommon(unittest.TestCase):
    def test_modules_import(self):
        for name in ("menu", "search", "analyze", "select_comps", "crosscheck"):
            importlib.import_module(name)
        import subprocess  # 표준 select가 가려지지 않았는지
        self.assertTrue(hasattr(importlib.import_module("select"), "select"))
        del subprocess

    def test_deep_merge(self):
        base = {"sim": {"expected": True}, "chars": {"A": {"control": {"reload": {"policy": "before_fb_end"}}}}}
        patch = {"chars": {"A": {"control": {"reload": {"cancel_on_full": True}}, "x": [1]}}}
        out = common.deep_merge(base, patch)
        self.assertEqual(out["chars"]["A"]["control"]["reload"],
                         {"policy": "before_fb_end", "cancel_on_full": True})
        self.assertEqual(base["chars"]["A"]["control"]["reload"], {"policy": "before_fb_end"})
        patch["chars"]["A"]["x"].append(2)
        self.assertEqual(out["chars"]["A"]["x"], [1])

    def test_record_roundtrip(self):
        rec = {k: None for k in common.RECORD_KEYS}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.jsonl"
            common.append_record(p, rec)
            self.assertEqual(list(common.read_records([p])), [rec])
            with self.assertRaises(ValueError):
                common.append_record(p, {"comp_id": "c01"})
        json.dumps(common.CONDITIONS)


if __name__ == "__main__":
    unittest.main()
