"""실험 33(역할 지문) — 평가기 없이."""

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R = sys.modules.get("run33") or _load("run33", ROOT / "experiments" / "33_role_vectors" / "run33.py")
A = sys.modules.get("analyze33") or _load("analyze33", ROOT / "experiments" / "33_role_vectors" / "analyze33.py")

# 작은 세계: 단계마다 니케 몇 명. B1은 동료 딜을 1.3배로 올리는 버퍼, D3은 본인 딜이 큰 딜러.
STAGES = {"B1": "1", "N1": "1", "M1": "1", "O1": "1", "P1": "1", "Q1": "1", "B2": "2", "N2": "2", "M2": "2", "O2": "2",
          "D3": "3", "E3": "3", "F3": "3", "G3": "3", "H3": "3"}
AT = {n: {"weapon": "AR" if n.startswith(("D", "E")) else "SMG", "code": "작열" if n != "D3" else "수냉",
          "stage": s, "class": "화력형"} for n, s in STAGES.items()}
BASE = {"B1": 10, "N1": 20, "M1": 20, "O1": 20, "P1": 20, "Q1": 20, "B2": 20, "N2": 20, "M2": 20, "O2": 20,
        "D3": 200, "E3": 50, "F3": 50, "G3": 50, "H3": 50}


def fake_sim(squad, element):
    """B1이 있으면 다른 넷 ×1.3. 우코(BEATS[코드] = 보스 속성)면 본인 ×1.5."""
    out = []
    for n in squad:
        v = BASE[n] * (1.3 if "B1" in squad and n != "B1" else 1.0)
        if R.adv_element(AT[n]["code"]) == element:
            v *= 1.5
        out.append(v)
    return out


def probe_recs(decks, set_name="R"):
    recs = []
    for i, d in enumerate(decks):
        for stage, x, sq in R.probe_squads(d, i, STAGES):
            for el in R.ELEMENTS:
                m = fake_sim(sq, el)
                recs.append({"set": set_name, "deck": i, "stage": stage, "x": x, "element": el, "squad": list(sq),
                             "total_damage": sum(m), "members": m})
    return recs


DECKS = [("N1", "B2", "D3", "E3", "F3"), ("M1", "N2", "G3", "H3", "E3"), ("N1", "M2", "F3", "G3", "D3")]


class TestRegistered(unittest.TestCase):
    def test_values(self):
        self.assertEqual(R.ELEMENTS, ("전격", "풍압", "철갑", "수냉", "작열"))
        self.assertEqual((R.SEEDS, R.SEED_BUDGET), ((0, 1), 12500))
        self.assertEqual((R.TOP_PER_ELEMENT, R.SHARE_MAX, R.K_R, R.K_R2, R.K_T), (200, 2, 20, 10, 10))
        self.assertEqual((A.REPRO_MIN, A.ADV_MATCH_MIN, A.TOP_THIRD, A.SPREAD_TOP, A.TOVE_LIFT_MIN, A.TOVE_TOP),
                         (0.8, 0.90, 1 / 3, 1 / 4, 1.5, 0.10))
        self.assertEqual(set(R.NEW_NIKKES), {"홍련 : 신살", "라푼젤 : 생츄어리", "마리안 : 퀸"})

    def test_beats_is_cycle(self):
        self.assertEqual(sorted(R.BEATS), sorted(R.ELEMENTS))
        self.assertEqual(sorted(R.BEATS.values()), sorted(R.ELEMENTS))
        x, seen = "작열", []
        for _ in range(5):
            seen.append(x)
            x = R.BEATS[x]
        self.assertEqual((x, len(set(seen))), ("작열", 5))

    def test_pool_and_new_nikkes(self):
        ro = R.roster()
        self.assertEqual(len(ro), 177)
        self.assertFalse(set(R.NEW_NIKKES) & set(ro))
        at = R.attrs()
        self.assertEqual(set(at), set(ro) | set(R.NEW_NIKKES))
        for n, s in ro.items():
            self.assertEqual(at[n]["stage"], s)
            self.assertIn(at[n]["code"], R.BEATS)


class TestMembers(unittest.TestCase):
    def test_member_vec(self):
        sq = ["a", "b", "c"]
        m = [{"name": "c", "damage": 3}, {"name": "a", "damage": 1}, {"name": "b", "damage": 2}]
        self.assertEqual(R.member_vec(sq, m), [1, 2, 3])
        self.assertIsNone(R.member_vec(sq, m[:2]))
        self.assertIsNone(R.member_vec(sq, None))
        self.assertIsNone(R.member_vec(["a", "b", "x"], m))

    def test_member_log(self):
        class Ev:
            version, sim_count, cache_hits = {"commit": "x"}, 7, 1

            def evaluate(self, reqs):
                return [SimpleNamespace(total_damage=6, raw={"members": [{"name": n, "damage": i + 1}
                                                                      for i, n in enumerate(q.squad)]}) for q in reqs]
        ev = R.MemberLog(Ev())
        self.assertEqual((ev.sim_count, ev.cache_hits, ev.version), (7, 1, {"commit": "x"}))
        ev.evaluate([SimpleNamespace(squad=["a", "b", "c"])])
        recs = [{"squad": ["a", "b", "c"], "total_damage": 6}, {"squad": ["z"], "total_damage": None}]
        self.assertEqual(ev.attach(recs), 0)
        self.assertEqual(recs[0]["members"], [1, 2, 3])
        self.assertIsNone(recs[1]["members"])


class TestRefs(unittest.TestCase):
    def test_pick_refs_share_and_avoid(self):
        cands = [(1.0, ("a", "b", "c", "d", "e")), (0.99, ("a", "b", "c", "x", "y")), (0.98, ("a", "b", "p", "q", "r")),
                 (0.97, ("s", "t", "u", "v", "w"))]
        self.assertEqual(R.pick_refs(cands, 5), [("a", "b", "c", "d", "e"), ("a", "b", "p", "q", "r"), ("s", "t", "u", "v", "w")])
        self.assertEqual(R.pick_refs(cands, 1, avoid={frozenset("abcde")}), [("a", "b", "c", "x", "y")])

    def test_ref_candidates(self):
        books = {"전격": {frozenset("abcde"): (10.0, tuple("abcde")), frozenset("fghij"): (5.0, tuple("fghij")),
                         frozenset(["test_B1", "a", "b", "c", "d"]): (9.0, ("test_B1", "a", "b", "c", "d"))},
                 "풍압": {frozenset("fghij"): (8.0, tuple("jihgf")), frozenset("klmno"): (10.0, tuple("klmno"))}}
        got = dict((frozenset(sq), (r, sq)) for r, sq in R.ref_candidates(books))
        self.assertEqual(set(got), {frozenset("abcde"), frozenset("fghij"), frozenset("klmno")})
        self.assertEqual(got[frozenset("fghij")], (0.8, tuple("jihgf")))      # 풍압 비율 0.8 > 전격 0.5


class TestProbe(unittest.TestCase):
    def test_slot_rotation(self):
        d = ("N1", "B2", "D3", "E3", "F3")
        self.assertEqual([R.slot_of(d, i, "3", STAGES) for i in range(4)], [2, 3, 4, 2])
        self.assertEqual(R.slot_of(d, 5, "1", STAGES), 0)
        self.assertEqual(R.slot_of(d, 1, "A", STAGES), R.slot_of(d, 1, "3", STAGES))

    def test_probe_squads(self):
        d = DECKS[0]
        ps = R.probe_squads(d, 0, STAGES)
        self.assertEqual(ps[0], ("0", "", d))
        n_expect = sum(1 for n in STAGES if n not in d)
        self.assertEqual(len(ps) - 1, n_expect)
        for st, x, sq in ps[1:]:
            self.assertEqual(STAGES[x], st)
            diff = [j for j in range(5) if sq[j] != d[j]]
            self.assertEqual(len(diff), 1)
            self.assertEqual(sq[diff[0]], x)
            self.assertEqual(STAGES[d[diff[0]]], st)

    def test_tove_squads(self):
        st = dict(STAGES, **{R.TOVE: "1"})
        d = ("N1", "B2", "D3", "E3", "F3")
        ts = R.tove_squads(d, 0, st)
        self.assertEqual(ts[0][2], (R.TOVE, "B2", "D3", "E3", "F3"))
        self.assertTrue(all(sq[0] == R.TOVE and STAGES.get(x) == "2" for _, x, sq in ts[1:]))
        self.assertIsNone(R.tove_squads((R.TOVE, "B2", "D3", "E3", "F3"), 0, st))


class TestFingerprint(unittest.TestCase):
    def setUp(self):
        self.fp = R.fingerprints(probe_recs(DECKS), AT)

    def test_buffer_and_dealer(self):
        fp = self.fp
        self.assertGreater(fp["B1"]["buffer"], 0.1)                 # 동료 ×1.3
        self.assertAlmostEqual(fp["N1"]["buffer"], fp["M1"]["buffer"], places=9)
        self.assertAlmostEqual(fp["N1"]["buffer"], 0.0, places=9)      # 칸 중앙 = 평범한 니케
        self.assertGreater(fp["D3"]["dealer"], fp["E3"]["dealer"])
        self.assertAlmostEqual(fp["E3"]["buffer"], fp["F3"]["buffer"], places=9)

    def test_adv(self):
        fp = self.fp
        for n in STAGES:
            self.assertAlmostEqual(fp[n]["adv_lift"], 1.5, places=9)
            self.assertEqual(fp[n]["adv_argmax"], R.adv_element(AT[n]["code"]))
        self.assertEqual(A.check_adv(fp, AT)["match"], 1.0)

    def test_boost_weapon(self):
        b = self.fp["B1"]["boost_weapon"]
        self.assertGreater(min(b.values()), 0.1)

    def test_repro_and_spearman(self):
        self.assertAlmostEqual(R.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(R.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        fp2 = R.fingerprints(probe_recs(DECKS[:2], "R2"), AT)
        rp = A.check_repro(self.fp, fp2)
        self.assertIn("stable", rp)

    def test_cells_keep_sets_apart(self):
        recs = probe_recs(DECKS, "R") + probe_recs(DECKS, "R2")
        keys = R.cells(recs).keys()
        self.assertEqual({k[0][0] for k in keys}, {"R", "R2"})

    def test_tove_lifts(self):
        probe = [{"stage": "2", "deck": 0, "element": "전격", "x": "B2", "squad": ["a", "B2"], "members": [1, 10]}]
        tove = [{"stage": "2", "deck": 0, "element": "전격", "x": "B2", "squad": ["토브", "B2"], "members": [1, 25]}]
        self.assertEqual(R.tove_lifts(probe, tove), {"B2": 2.5})

    def test_rank_and_top(self):
        self.assertEqual(R.rank_of({"a": 3, "b": 2, "c": None}, "b", ["a", "b", "c"]), (2, 2))
        self.assertTrue(A.in_top(13, 39, 1 / 3))
        self.assertFalse(A.in_top(14, 39, 1 / 3))
        self.assertTrue(A.in_top(5, 58, 0.10))
        self.assertFalse(A.in_top(6, 58, 0.10))


if __name__ == "__main__":
    unittest.main()
