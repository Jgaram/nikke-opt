"""실험 6 W3 조합 선정(select_comps.py) — 가짜 평가기로 후보 규칙 · 선정 규칙 · 출력 형식을 확인한다."""

import hashlib
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

EXP_DIR = Path(__file__).resolve().parent.parent / "experiments" / "06_control_menu"
if str(EXP_DIR) not in sys.path:
    sys.path.insert(0, str(EXP_DIR))

import common  # noqa: E402
import select_comps as S  # noqa: E402
from nikke_opt.evaluator import EvalResult  # noqa: E402


def fake_damage(squad, salt=""):
    h = hashlib.sha256((salt + "|".join(squad)).encode()).hexdigest()
    return 10**9 + int(h[:8], 16)


class FakeEvaluator:
    version = {"repo": "fake", "commit": "0" * 40, "dirty": False}

    def __init__(self, salt="", fail=()):
        self.salt, self.fail = salt, set(fail)
        self.sim_count = self.cache_hits = 0
        self.requests = []

    def evaluate(self, reqs):
        out = []
        for r in reqs:
            self.requests.append(r)
            self.sim_count += 1
            if r.squad in self.fail:
                out.append(EvalResult(None, {"error": {"type": "invalid_input", "message": "가짜"}}))
            else:
                d = fake_damage(r.squad, self.salt)
                out.append(EvalResult(d, {"total_damage": d}))
        return out


class TestCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.burst, cls.ranker = S.load_sources()
        cls.cands = S.candidates(cls.burst, cls.ranker)

    def test_info_covers_pool(self):
        self.assertEqual(set(S.NIKKE_INFO), set(self.burst))
        for m in S.LAYER_TARGETS + (S.REDHOOD,):
            self.assertIn(m, self.burst)

    def test_deterministic_and_bounded(self):
        again = S.candidates(self.burst, self.ranker)
        self.assertEqual(again, self.cands)
        self.assertLessEqual(len(self.cands), 500)  # 평가 수백 회 이내
        self.assertEqual(len({frozenset(c["squad"]) for c in self.cands}), len(self.cands))
        self.assertEqual(len({c["id"] for c in self.cands}), len(self.cands))

    def test_squads_valid(self):
        for c in self.cands:
            self.assertEqual(len(set(c["squad"])), 5)
            self.assertTrue(all(m in self.burst for m in c["squad"]))
            self.assertEqual(c["skeleton"], S.skeleton(c["squad"], self.burst))
            if c["skeleton"] == "redhood":
                self.assertIn(S.stage_counts(c["squad"], self.burst)[:3], S.REDHOOD_FRAMES)

    def test_ranker_order_is_most_frequent(self):
        first = {}
        for s in self.ranker:
            first.setdefault(frozenset(s["squad"]), s["squad"])
        rk = [c for c in self.cands if c["source"].startswith("ranker")]
        self.assertEqual(len(rk), len(first))
        for c in rk:
            self.assertEqual(c["squad"], first[frozenset(c["squad"])])

    def test_swaps_keep_slots(self):
        bases = S.base_compositions(self.ranker)
        for c in self.cands:
            if not c["source"].startswith("swap"):
                continue
            base = bases[c["base"]]["squad"]
            diff = [i for i, (a, b) in enumerate(zip(base, c["squad"])) if a != b]
            self.assertEqual(len(diff), 1)
            i = diff[0]
            if c["squad"][i] != S.REDHOOD:
                self.assertEqual(self.burst[base[i]], self.burst[c["squad"][i]])

    def test_focus_coverage(self):
        cnt = Counter(m for c in self.cands for m in c["squad"])
        for m in S.LAYER_TARGETS:
            self.assertGreaterEqual(cnt[m], S.MIN_APPEAR, m)
        self.assertTrue(any(S.miranda_rule(c["squad"]) and "에이다" in c["squad"] for c in self.cands))
        sk = Counter(c["skeleton"] for c in self.cands)
        for s in S.SKELETONS:
            self.assertGreater(sk[s], S.QUOTA[s], s)


class TestSelect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cands = S.candidates()

    def damages(self, salt):
        return {c["id"]: fake_damage(c["squad"], salt) for c in self.cands}

    def test_rules_hold_across_damage_patterns(self):
        for salt in map(str, range(12)):
            sel, log = S.select(self.cands, self.damages(salt))
            self.assertEqual(log["violations"], [], salt)
            self.assertEqual(S.check(sel), [])
            cnt = Counter(m for c in sel for m in c["squad"])
            self.assertTrue(all(n >= S.MIN_APPEAR for n in cnt.values()))
            self.assertTrue(all(m in cnt for m in S.LAYER_TARGETS))
            self.assertTrue(all(c["band"] in ("high", "mid") for c in sel))
            self.assertTrue(S.MIN_N <= len(sel) <= S.MAX_N)
            sk = Counter(c["skeleton"] for c in sel)
            for s in S.SKELETONS:
                self.assertLessEqual(sk[s], S.QUOTA[s] + 1)

    def test_deterministic(self):
        d = self.damages("x")
        a, _ = S.select(self.cands, d)
        b, _ = S.select(self.cands, d)
        self.assertEqual([c["id"] for c in a], [c["id"] for c in b])

    def test_bands_per_skeleton(self):
        d = self.damages("b")
        band = S.bands(self.cands, d)
        for sk in S.SKELETONS:
            ids = [c["id"] for c in self.cands if c["skeleton"] == sk]
            hi = [d[i] for i in ids if band[i] == "high"]
            mid = [d[i] for i in ids if band[i] == "mid"]
            low = [d[i] for i in ids if band[i] == "low"]
            self.assertTrue(hi and mid and low)
            self.assertGreater(min(hi), max(mid))
            self.assertGreater(min(mid), max(low))

    def test_errors_excluded(self):
        d = self.damages("e")
        bad = self.cands[0]["id"]
        d[bad] = None
        sel, log = S.select(self.cands, d)
        self.assertNotIn(bad, [c["id"] for c in sel])
        self.assertEqual(log["evaluated_ok"], len(self.cands) - 1)


class TestExtract(unittest.TestCase):
    def test_extract_from_fake_data(self):
        nikke = {
            "가짜AR": {"weapon_type": "AR", "is_charge": False, "input_type": "DOWN", "full_charge_only": False,
                     "fire_rate": 12.0, "max_ammo": 60, "reload_time": 1.0, "pellets": 1, "muzzles": 1,
                     "burst_energy": 0.4},
            "가짜SR": {"weapon_type": "SR", "is_charge": True, "input_type": "UP", "full_charge_only": False,
                     "fire_stance_hold": 0.0, "charge_time": 1.0, "max_ammo": 6, "reload_time": 2.0,
                     "pellets": 1, "muzzles": 1, "burst_energy": 5.6},
        }
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "data"
            d.mkdir()
            (d / "parsed_nikke.json").write_text(json.dumps(nikke, ensure_ascii=False), encoding="utf-8")
            (d / "weapon_delays.json").write_text(json.dumps({"_exceptions": {"가짜SR": {"post_reload_delay": 0.5}}}),
                                                  encoding="utf-8")
            info = S.extract_info(Path(tmp), ["가짜AR", "가짜SR"])
        self.assertEqual(info["가짜AR"], ("AR", False, "DOWN", False, round(0.4 * 60 / (60 / 12 + 1.0), 3)))
        self.assertEqual(info["가짜SR"], ("SR", True, "UP", False, round(5.6 * 6 / (6 * 1.38 + 2.0 + 0.5), 3)))


class TestPick(unittest.TestCase):
    def test_run_pick_outputs(self):
        cands = S.candidates()
        fail = {tuple(cands[3]["squad"])}
        ev = FakeEvaluator("p", fail=fail)
        with tempfile.TemporaryDirectory() as tmp:
            j, md = Path(tmp) / "c.json", Path(tmp) / "s.md"
            comps, log = S.run_pick(ev, out_json=j, out_md=md)
            self.assertEqual(json.loads(j.read_text(encoding="utf-8")), comps)
            self.assertEqual(common.load_compositions(j), comps)
            text = md.read_text(encoding="utf-8")
        self.assertEqual(ev.sim_count, len(cands))
        self.assertEqual(log["sim_count"], len(cands))
        self.assertEqual(log["violations"], [])
        self.assertIn(f"**{len(cands)}회**", text)
        self.assertIn("니케별 등장 조합 수", text)
        self.assertIn("규칙 점검: **통과**", text)
        self.assertIn("오류 후보", text)
        # 요청: 기본 레이어(options 없음) · 기본 적 · 어댑터 기본 sim(accumulate)
        for r in ev.requests:
            self.assertIsNone(r.boss)
            self.assertEqual(dict(r.options), {})
            self.assertEqual(r.to_line()["sim"]["burst_gauge_mode"], "accumulate")
            self.assertNotIn("boss", r.to_line())
        keys = set(common.Composition.__annotations__)
        for i, c in enumerate(comps, 1):
            self.assertEqual(set(c), keys)
            self.assertEqual(c["id"], f"c{i:02d}")
            self.assertIsInstance(c["default_damage"], int)
            self.assertEqual(c["default_damage"], fake_damage(tuple(c["squad"]), "p"))
            self.assertIn(c["skeleton"], S.SKELETONS)
            self.assertTrue(c["tags"][0].startswith("band:"))
        self.assertNotIn(cands[3]["squad"], [c["squad"] for c in comps])

    def test_candidates_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "k.json"
            self.assertEqual(S.main(["candidates", "--no-md", "--out", str(out)]), 0)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), S.candidates())

    def test_unpicked_md(self):
        text = S.selection_md(S.candidates())
        self.assertIn("`pick` 미실행", text)
        self.assertIn(S.CALC_SOURCE, text)


if __name__ == "__main__":
    unittest.main()
