"""실험 6 W1 crosscheck.py — 요청 정의 · 대조 · 표 생성(가짜 평가기). W1 소유."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

EXP_DIR = Path(__file__).resolve().parent.parent / "experiments" / "06_control_menu"
if str(EXP_DIR) not in sys.path:
    sys.path.insert(0, str(EXP_DIR))

import crosscheck  # noqa: E402
from nikke_opt.evaluator import EvalResult  # noqa: E402


class FakeEvaluator:
    """총딜 = 요청 순번 기반 고정값. rust는 scale배."""

    def __init__(self, kind, scale):
        self.version = {"repo": kind}
        self.sim_count = 0
        self.cache_hits = 0
        self.scale = scale

    def evaluate(self, reqs):
        out = []
        for i, q in enumerate(reqs):
            self.sim_count += 1
            tot = int((10**9 + i * 1000) * self.scale)
            out.append(EvalResult(tot, {"members": [{"name": n, "damage": tot // 5} for n in q.squad],
                                        "control_detail": {"preempted": {}}}))
        return out

    def close(self):
        pass


def fake_factory(rust_scale):
    return lambda kind: FakeEvaluator(kind, rust_scale if kind == "rust" else 1.0)


class TestCrosscheck(unittest.TestCase):
    def test_requests(self):
        pairs = crosscheck.build_requests()
        ids = [s["id"] for s, _ in pairs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(15 <= len(ids) <= 20)
        for spec, q in pairs:
            line = q.to_line()
            self.assertEqual(line["sim"]["burst_gauge_mode"],
                             spec["options"].get("sim", {}).get("burst_gauge_mode", "accumulate"))
            for name in spec["options"].get("chars", {}):
                self.assertIn(name, q.squad)
            self.assertIn(spec["axis"], crosscheck.AXIS_HINTS)
        with self.assertRaises(ValueError):
            crosscheck.build_requests(["없음"])
        self.assertEqual([s["id"] for s, _ in crosscheck.build_requests(["A9", "A0"])], ["A0", "A9"])

    def test_dry_run(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(crosscheck.main(["--dry-run"]), 0)
        lines = [json.loads(l) for l in buf.getvalue().splitlines()]
        self.assertEqual(len(lines), len(crosscheck.REQUESTS))

    def test_compare(self):
        r = EvalResult(102, {"members": [{"name": "a", "damage": 51}, {"name": "b", "damage": 51}]})
        p = EvalResult(100, {"members": [{"name": "a", "damage": 50}, {"name": "b", "damage": 50}]})
        row = crosscheck.compare(crosscheck.REQUESTS[0], r, p)
        self.assertAlmostEqual(row["diff"], 0.02)
        self.assertTrue(row["flag"])
        self.assertFalse(crosscheck.compare(crosscheck.REQUESTS[0], p, p)["flag"])
        self.assertTrue(crosscheck.compare(crosscheck.REQUESTS[0], EvalResult(None, {"error": {}}), p)["flag"])

    def test_main_writes_md(self):
        for scale, flagged in ((1.0, False), (1.05, True)):
            with tempfile.TemporaryDirectory() as d, mock.patch.object(crosscheck, "make_evaluator",
                                                                       fake_factory(scale)):
                out = Path(d) / "x.md"
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(crosscheck.main(["--out", str(out), "--raw", str(Path(d) / "r.jsonl")]), 0)
                md = out.read_text(encoding="utf-8")
                self.assertIn(f"Rust {len(crosscheck.REQUESTS)} · Python {len(crosscheck.REQUESTS)}", md)
                self.assertNotIn("미실행 |", md)
                self.assertEqual("**표시**" in md, flagged)
                self.assertEqual(len((Path(d) / "r.jsonl").read_text().splitlines()), len(crosscheck.REQUESTS))


if __name__ == "__main__":
    unittest.main()
