"""실험 15 실행기(run15.py) — 경우 목록 · 구 풀 · 미보유 계정 · 합치기 · I2 단계 예산을 확인한다."""

import json
import os
import random
import re
import sys
import unittest
from collections import Counter
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parent.parent
EXP15 = ROOT / "experiments" / "15_new_nikke"
if str(EXP15) not in sys.path:
    sys.path.insert(0, str(EXP15))

import run15 as W  # noqa: E402
from tests.test_exp10_run import FakeEv  # noqa: E402

R10, R9 = W.R10, W.R9


def struct_records(names, n, seed, ev):
    """구조 틀 균형 무작위 스쿼드 n개를 가짜 평가기로 평가한 기록."""
    sqs = R10.design(names, W.BURST, random.Random(seed), n=n)
    res = ev.evaluate([type("Q", (), {"squad": sq, "options": {}})() for sq in sqs])
    return [{"squad": list(sq), "total_damage": r.total_damage, "phase": "설계", "error": None, "cached": False}
            for sq, r in zip(sqs, res)]


def fake_o_sources(case, ev, n=150):
    names = W.old_account(case, 0).names
    out = {}
    for k in W.SEEDS:
        recs = struct_records(names, n, f"o-{case}-{k}", ev)
        best = R9.pack_vals(R9.book_of(recs))[0]
        out[f"O-s{k}"] = ({"evals": len(recs), "sims": len(recs), "seconds": 1.0, "final": {"total": best}}, recs)
    return out


class TestCases(unittest.TestCase):
    def test_cases_match_readme(self):
        text = (EXP15 / "README.md").read_text(encoding="utf-8")
        sizes = {"C1": 1, "C2": 2, "C3": 3, "C4": 10, "C5": 5}
        for c, names in W.CASES.items():
            row = next(line for line in text.splitlines() if line.startswith(f"| **{c}**"))
            self.assertEqual(len(names), sizes[c], c)
            self.assertEqual(len(set(names)), len(names), c)
            for n in names:
                if c == "C4" and n in W.CASES["C3"]:
                    continue  # README는 「C3 3명 + …」으로 적었다
                self.assertIn(n, row, (c, n))
            self.assertTrue(all(n in W.BURST for n in names), c)
        self.assertTrue(set(W.CASES["C3"]) <= set(W.CASES["C4"]))
        self.assertEqual(W.META_CASES, ("C1", "C2", "C3", "C4"))

    def test_cases_reproduce_from_records(self):
        """C3 · C4 = 최선 16벌 모두에 든 니케의 U4 계수 상위 3 · 10, C5 = 16벌 · 실험 10 · 11 177명 계정 최종 5덱 밖에서
        `random.Random("exp15-C5").sample`."""
        sets = []
        for p in (ROOT / "experiments/13_seed_merge/run_log/precompute_U4.json",
                  ROOT / "experiments/14_seed_pairs/run_log/precompute_U4n.json"):
            sets += json.loads(p.read_text(encoding="utf-8"))["sets"]
        self.assertEqual(len(sets), 16)
        cnt = Counter(n for s in sets for n in {m for sq in s for m in sq})
        in16 = [n for n, k in cnt.items() if k == 16]
        coef = json.loads((ROOT / "experiments/13_seed_merge/run_log/precompute_U4.json").read_text(encoding="utf-8"))["coef"]
        top = sorted(in16, key=lambda n: -coef[n])
        self.assertEqual(set(top[:3]), set(W.CASES["C3"]))
        self.assertEqual(set(top[:10]), set(W.CASES["C4"]))
        self.assertIn("아르카나 : 포츈 메이트", in16)
        self.assertIn("도로시 : 세렌디피티", in16)
        acct = set()
        for p in sorted((ROOT / "experiments").glob("1[01]_*/run_log/*summary.jsonl")):
            for line in p.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                if r.get("pool") == 177:
                    acct |= {n for _, sq in r["final"]["squads"] for n in sq}
        out = sorted(n for n in W.BURST if n not in cnt and n not in acct)
        self.assertEqual(len(out), 119)
        self.assertEqual(random.Random("exp15-C5").sample(out, 5), list(W.CASES["C5"]))


class TestAccounts(unittest.TestCase):
    def test_old_pool(self):
        for c, rm in W.CASES.items():
            a = W.old_account(c, 2)
            self.assertEqual(a.id, f"pre-{c}-s2")
            self.assertEqual(len(a.names), 177 - len(rm))
            self.assertFalse(set(rm) & set(a.names) or set(rm) & set(a.owned))
            self.assertEqual(a.options, {})
        with self.assertRaises(ValueError):
            W.removed("C9")

    def test_missing_new_keeps_tiers(self):
        for sc in R10.scenarios("val"):
            base = W.val_account(sc)
            a = W.val_account(sc, "C4")
            self.assertEqual(a.id, f"{sc['id']}n")
            self.assertEqual(set(a.names), set(base.names) - set(W.CASES["C4"]))
            self.assertEqual(a.tier, {n: t for n, t in base.tier.items() if n not in W.CASES["C4"]})
            chars = (a.options.get("profile") or {}).get("chars", {})
            self.assertFalse(set(chars) & set(W.CASES["C4"]))
            self.assertEqual(set(chars), {n for n, t in a.tier.items() if t != "상"})
        self.assertNotEqual(W.val_account(R10.scenarios("val")[4]).tier, {})  # v5는 177명 확장 등급이 있다


class TestMerge(unittest.TestCase):
    def test_o_i1_approx(self):
        ev = FakeEv()
        case = "C2"
        o_srcs = fake_o_sources(case, ev)
        o = W.merged(o_srcs, W.old_account(case, 0), "O", case)
        self.assertEqual(o["evals"], 600)
        self.assertFalse(set(W.CASES[case]) & set(o["coef"]))
        self.assertFalse(any(set(W.CASES[case]) & set(sq) for s in o["sets"] for sq in s))
        self.assertEqual((o["new_decks"], o["new_in_final"]), (0, 0))
        s4 = {"PB15s4": ({"evals": 100, "sims": 90, "seconds": 1.0, "final": {"total": 0.0}},
                         struct_records(W.full_account("x").names, 100, "s4", ev))}
        i1 = W.merged({**o_srcs, **s4}, W.full_account("pre-C2-I1"), "I1", case)
        self.assertEqual(i1["evals"], 700)
        self.assertEqual(len(i1["coef"]), 177)
        self.assertGreaterEqual(i1["final"]["total"], o["final"]["total"] - 1e-9)
        ap = W.approx_obs(case, s4, o)
        self.assertFalse(any(set(W.CASES[case]) & set(sq) for _, sq in ap["final"]["squads"]))
        self.assertIn("vs_O", ap)


class TestUpdate(unittest.TestCase):
    def test_i2_stage_budgets(self):
        ev = FakeEv()
        for case, budget in (("C1", 700), ("C4", 1200)):
            new = W.CASES[case]
            o_srcs = fake_o_sources(case, ev, n=120)
            o = W.merged(o_srcs, W.old_account(case, 0), "O", case)
            out, recs = W.run_update(case, o_srcs, o, ev, budget=budget)
            u = out["update"]
            self.assertEqual(u["evals"], len(recs))
            self.assertLessEqual(u["evals"], budget)
            n1 = max(W.DESIGN_MIN, W.DESIGN_PER * len(new))
            st = {s["what"]: s["evals"] for s in u["stages"]}
            self.assertEqual(st["I2 신캐 설계"], n1)
            self.assertLessEqual(st["I2 신캐 넣기"], min(W.INSERT_TOP * 40 * len(new), int(W.INSERT_SHARE * budget)))
            self.assertGreater(st["I2 신캐 넣기"], 0)
            self.assertGreater(st["I2 국소 탐색"], 0)
            design = [r["squad"] for r in recs if r["phase"] == "신캐 설계"]
            ins = [r["squad"] for r in recs if r["phase"] == "신캐 넣기"]
            self.assertTrue(all(set(new) & set(sq) for sq in design + ins))
            per = Counter(next(n for n in new if n in sq) for sq in design if sum(n in sq for n in new) == 1)
            self.assertTrue(all(per[n] > 0 for n in new))
            decks = {tuple(d) for s in o["sets"] for d in s}
            for sq in ins:  # O 덱 하나에서 같은 단계 한 명을 새 니케로 바꾼 이웃
                self.assertTrue(any(sum(a != b for a, b in zip(sq, d)) == 1 and
                                    all(W.BURST[a] == W.BURST[b] for a, b in zip(sq, d)) for d in decks))
            old = {tuple(r["squad"]) for _, rs in o_srcs.values() for r in rs}
            self.assertFalse(old & {tuple(r["squad"]) for r in recs})  # 이전 기록은 다시 요청하지 않는다
            self.assertEqual(len(out["coef"]), 177)
            self.assertGreaterEqual(out["final"]["total"], o["final"]["total"] - 1e-9)
            self.assertEqual(out["evals"], o["evals"] + u["evals"])

    def test_squad_with(self):
        rng = random.Random(1)
        names = W.full_account("x").names
        for t in W.CASES["C4"] + W.CASES["C5"]:
            sq = W.squad_with(t, names, Counter(), rng)
            self.assertIn(t, sq)
            self.assertEqual(len(set(sq)), 5)
            self.assertIn(R10.frame_of(sq, W.BURST), R10.STRUCT_FRAMES)


class TestCli(unittest.TestCase):
    def test_search_rejects(self):
        import argparse
        ns = dict(case="C1", log=None, out=Path("/nonexistent"), budgets="800", only=None, workers=1)
        with self.assertRaises(ValueError):
            W.cmd_search(argparse.Namespace(methods="F4", missing_new=False, **ns))
        with self.assertRaises(ValueError):
            W.cmd_search(argparse.Namespace(methods="U4", missing_new=True, **ns))
        with self.assertRaises(ValueError):
            W.cmd_precompute(argparse.Namespace(case="C1", log=Path("/tmp/x15"), seed="4"))

    def test_names(self):
        self.assertTrue(re.fullmatch(r"v1n_P177_O_800", R10.run_name("v1n", 177, "O", 800)))


if __name__ == "__main__":
    unittest.main()
