"""실험 14 실행기(run14.py) — 합성 기록으로 확인한다."""

import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parent.parent
for d in ("14_seed_pairs",):
    p = ROOT / "experiments" / d
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import run14 as W  # noqa: E402
from tests.test_exp13_run import fake_sources  # noqa: E402


def write_sources(d: Path, srcs):
    import gzip
    for k, (pj, recs) in srcs.items():
        m = W.U13.seed_method(k)
        (d / f"precompute_{m}.json").write_text(json.dumps(pj, ensure_ascii=False))
        with gzip.open(d / f"precompute_{m}.jsonl.gz", "wt", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


class TestRun14(unittest.TestCase):
    def test_precompute_names(self):
        for bad in ("PB15s3", "PBD", "PB15s4,PBSs5", "PB1510k"):
            with self.assertRaises(ValueError):
                W.cmd_precompute(argparse.Namespace(which=bad, out=Path(".")))

    def test_merge_pairs(self):
        srcs = fake_sources(seeds=W.SEEDS)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            write_sources(d, srcs)
            self.assertEqual(sorted(W.load_sources(d)), [4, 5, 6, 7])
            W.cmd_merge(argparse.Namespace(pre=d, out=d))
            for nm, seeds in W.FULL.items():
                p = W.load_pre(nm, d)
                self.assertEqual(p["seeds"], list(seeds))
                self.assertEqual(len(p["coef"]), 177)
                for k in seeds:
                    self.assertGreaterEqual(p["final"]["total"], srcs[k][0]["final"]["total"] - 1e-9)
            obs = json.loads((d / "merges.json").read_text(encoding="utf-8"))
            self.assertEqual(len(obs), 20)
            self.assertIn("U2-s4s5", [o["name"] for o in obs])
        with self.assertRaises(ValueError):
            W.load_pre("U4", Path("."))


if __name__ == "__main__":
    unittest.main()
