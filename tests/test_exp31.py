"""실험 31(최근 10시즌 편성안 지도) — 평가기 없이: 시즌 자료 · 날짜 경계 · 계정 · options · 판 고르기 · 분류 · 랭커 지표."""

import gzip
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "31_recent_seasons"


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load("run31", EXP / "run31.py")
S31 = _load("seasons31", EXP / "seasons31.py")


def _book():
    """니케 75명(15줄 × 5). 줄 덱 15개가 가장 좋고, 대각 덱은 그보다 낮다 — 서로 먼 5덱이 여럿 있다(실험 30 테스트와 같다)."""
    g = [tuple(f"{r}{c}" for c in range(5)) for r in "ABCDEFGHIJKLMNO"]
    book = {frozenset(d): (20.0 - 0.1 * i, d) for i, d in enumerate(g)}
    for s in range(1, 5):
        for c in range(5):
            d = tuple(g[(r + s * c) % 15][(c + r) % 5] for r in range(5))
            if len(set(x[0] for x in d)) == 5:
                book.setdefault(frozenset(d), (14.0 - 0.1 * c - s, d))
    return g, book


class _Res:
    def __init__(self, sq, w):
        self.total_damage = int(sum(w[n] * (1 + 0.1 * i) for i, n in enumerate(sq)) * 1e8)
        self.raw = {"members": [{"name": n, "damage": int(w[n] * 1e8)} for n in sq]}
        self.error, self.cached = None, False


class FakeEv:
    """니케마다 정한 값의 합(배치 순서에 따라 조금 다름). 받은 요청 options를 남긴다."""

    def __init__(self):
        import random
        rng = random.Random(7)
        self.w = {n: rng.uniform(1, 10) for n in R.R10.P177}
        self.sim_count, self.options = 0, []
        self.version = {"repo": "fake", "commit": "0000000"}

    def evaluate(self, reqs):
        self.sim_count += len(reqs)
        self.options.extend(r.options for r in reqs)
        return [_Res(r.squad, self.w) for r in reqs]


class TestSeasons31(unittest.TestCase):
    def test_ten_recent_seasons(self):
        self.assertEqual(R.SEASONS, tuple(range(33, 43)))
        for s in R.SEASONS:
            v = R.season(s)
            self.assertEqual(v["season"], s)
            self.assertLessEqual(set(v["favorite0"]), set(v["pool"]))
            used = {n for n, _ in v["rankers"]["units"]}
            self.assertLessEqual(used, set(v["pool"]), s)          # 랭커가 쓴 니케는 모두 그 시즌 풀에 있다
            self.assertEqual(v["rankers"]["unsupported_share"], 0.0)
            self.assertEqual(len(v["rankers"]["top_five"]["squads"]), 5)

    def test_after_maintenance(self):
        f = S31.after_maintenance
        self.assertEqual(f("2026-07-23T00:00:00+09:00"), "2026-07-23T05:00:00+09:00")
        self.assertEqual(f("2026-07-16T05:00:00+09:00"), "2026-07-16T05:00:00+09:00")   # 시각이 있으면 그대로
        self.assertEqual(f("2024-10-03T12:00:00+09:00"), "2024-10-03T12:00:00+09:00")
        self.assertGreater(f("2026-07-23T00:00:00+09:00"), R.season(39)["end"])          # 점검 날 끝난 시즌보다 뒤
        self.assertEqual(f(""), "")

    def test_boundary_fix(self):
        """시즌 끝나는 날 점검 뒤에 들어온 니케 · 애장품은 그 시즌에 없다(실험 22 규칙과 다른 점)."""
        self.assertNotIn("레이블", R.season(33)["pool"])
        self.assertIn("레이블", R.season(34)["pool"])
        self.assertNotIn("라플라스 : 얼티밋 히어로", R.season(39)["pool"])
        self.assertIn("라플라스 : 얼티밋 히어로", R.season(40)["pool"])
        self.assertEqual(R.season(39)["favorite0"], ["로산나", "슈가", "팬텀", "플로라"])
        self.assertEqual(R.season(40)["favorite0"], [])
        self.assertEqual(len(R.season(33)["favorite0"]), 8)
        b = json.loads((EXP / "seasons.json").read_text(encoding="utf-8"))["boundary"]
        for x in b:
            if x["kind"] == "출시":
                self.assertEqual(x["used"], 0, x)                   # 그 시즌 랭커 사용 0회가 규칙의 근거
        self.assertGreaterEqual(sum(x["kind"] == "출시" for x in b), 15)


class TestRun31(unittest.TestCase):
    def test_registered_values(self):
        self.assertEqual((R.SEED_BUDGET, R.PREFIX, R.CORE_PX), (12500, 6250, 30))
        self.assertEqual((R.GOOD, R.LOW, R.SHOW, R.MORE, R.SUB_CAP), (0.97, 0.95, 3, 20, 400))
        self.assertEqual(R.PARTS, ("B_s0", "B_s1", "W", "core30", "members"))

    def test_options(self):
        self.assertEqual(R.options(42), {"enemy": {"code": "수냉"}})
        self.assertEqual(R.options(42, 30), {"enemy": {"code": "수냉", "core_px": 30}})
        o = R.options(39, 30)
        self.assertEqual(o["enemy"], {"code": "전격", "core_px": 30})
        self.assertEqual(o["profile"], {"base": "default", "chars": {n: {"favorite_stage": 0} for n in ("로산나", "슈가", "팬텀", "플로라")}})

    def test_account(self):
        for s in (33, 39, 42):
            a0, a1 = R.account(s, 0), R.account(s, 1)
            self.assertEqual((a0.id, a1.id), (f"pre-S{s}", f"pre-S{s}-s1"))
            self.assertEqual(set(a0.names), set(R.season(s)["pool"]))
            self.assertEqual(a0.options, R.options(s))
            self.assertEqual(set(a0.tier.values()), {"상"})

    def test_arm_needs_decision(self):
        self.assertIsNone(R.USE_W)                                  # 실험 30 판정 전(README §판)
        with self.assertRaises(RuntimeError):
            R.arm_of()
        self.assertEqual(R.arm_of(True), "W")
        self.assertEqual(R.arm_of(False), "B")

    def test_arm_recs_cut(self):
        tmp = Path(tempfile.mkdtemp())
        old = R.LOG
        R.LOG = tmp
        try:
            d = R.sdir(40)
            d.mkdir(parents=True)
            for k in (0, 1):
                with gzip.open(d / f"B_s{k}.jsonl.gz", "wt", encoding="utf-8") as f:
                    for i in range(R.PREFIX + 5):
                        f.write(json.dumps({"squad": [f"s{k}", str(i)], "total_damage": 1.0}) + "\n")
            with gzip.open(d / "W.jsonl.gz", "wt", encoding="utf-8") as f:
                f.write(json.dumps({"squad": ["w", "0"], "total_damage": 1.0}) + "\n")
            self.assertEqual(len(R.arm_recs(40, "B")), 2 * (R.PREFIX + 5))
            w = R.arm_recs(40, "W")
            self.assertEqual(len(w), 2 * R.PREFIX + 1)
            self.assertEqual(w[R.PREFIX - 1]["squad"], ["s0", str(R.PREFIX - 1)])
            self.assertEqual(w[R.PREFIX]["squad"], ["s1", "0"])
        finally:
            R.LOG = old

    def test_classes_of(self):
        g, book = _book()
        m = R.R30.class_map(book, limit=10, low=0.0, max_reps=3)
        cl = R.classes_of(m, book)
        self.assertEqual([c["name"] for c in cl], ["A", "B", "C"])
        self.assertAlmostEqual(cl[0]["ratio"], 1.0)
        best = m["best"]
        for c in cl:
            self.assertAlmostEqual(c["total"], sum(v for v, _ in c["decks"]))
            for o, v in c["vs"].items():
                self.assertLessEqual(v["J"], 0.2 + 1e-12)          # 큰 분류 대표끼리 J ≤ 0.2
            self.assertLessEqual(len(c["subs"]), R.MORE)
            for s in c["subs"]:
                self.assertGreaterEqual(s["J"], 0.5 - 1e-12)        # 세부 분류: 대표와 J ≥ 0.5
                self.assertGreaterEqual(s["total"], R.GOOD * best - 1e-9)
                self.assertIn(len(s["changed"]), (1, 2))
                self.assertNotIn("new_unposted", s)
                self.assertEqual(set(s["J_other"]), {x["name"] for x in cl} - {c["name"]})

    def test_core_rc_with_fake_evaluator(self):
        """코어 30 = 재평가(후보 전부) → 이어 찾기 CORE_CONT. 요청은 모두 시즌 options + 코어 30이다."""
        s = 39
        pool = sorted(R.season(s)["pool"])
        decks = [tuple(pool[i:i + 5]) for i in range(0, 100, 5)]
        nb = {frozenset(d): (20.0 - 0.2 * i, d) for i, d in enumerate(decks)}
        m = R.R30.class_map(nb, limit=5, max_reps=2, low=0.0)
        ev = FakeEv()
        old = R.CORE_CONT
        R.CORE_CONT = 200
        try:
            out, recs = R.core_rc(s, ev, nb, m)
        finally:
            R.CORE_CONT = old
        self.assertEqual(out["requests"], len(R.R30.core_candidates(nb, [m])))
        self.assertLessEqual(out["extra_evals"], 200)
        self.assertEqual(len(recs), out["requests"] + out["extra_evals"])
        self.assertTrue(ev.options)
        for o in ev.options:
            self.assertEqual(o, R.options(s, 30))
        self.assertGreater(len(R.R30.book_of(recs)), 0)

    def test_ranker_metrics(self):
        """우리 A가 랭커 대표 5덱 그대로면 J = 1, V_top = 100%."""
        s = 40
        rk = R.season(s)["rankers"]
        top = [list(q) for q in rk["top_five"]["squads"]]
        rv = {",".join(q): {"nocore": 10.0 + i} for i, q in enumerate(top)}
        A = {"name": "A", "total": sum(10.0 + i for i in range(5)), "decks": [[10.0 + i, q] for i, q in enumerate(top)]}
        m = R.ranker_metrics(s, "nocore", [A], rv)
        self.assertAlmostEqual(m["J_top"]["A"], 1.0)
        self.assertAlmostEqual(m["V_top"], 1.0)
        top25 = {n for n, _ in rk["units"][:25]}
        self.assertEqual(m["N25"], len({n for q in top for n in q} & top25))
        self.assertEqual(m["D4"], 5)
        if any(",".join(q) not in rv for q in rk["rank1"]["squads"]):
            self.assertIsNone(m["V_r1"])                            # 값을 모르는 덱이 있으면 비운다
        m0 = R.ranker_metrics(s, "nocore", [A], None)               # 랭커 덱 평가 전: 값 지표 없음
        self.assertNotIn("V_top", m0)

    def test_analyze_pending(self):
        tmp = Path(tempfile.mkdtemp())
        old = R.LOG
        R.LOG = tmp
        try:
            row = R.analyze_season(33, "B")
        finally:
            R.LOG = old
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["by_boss"], {})
        self.assertEqual(row["sims_total"], 0)


if __name__ == "__main__":
    unittest.main()
