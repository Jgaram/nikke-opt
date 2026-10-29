"""실험 6 W4 탐색 실행기(search.py) — 가짜 평가기 · 가짜 선택지로 확인한다."""

import io
import itertools
import json
import sys
import tempfile
import types
import unittest
from concurrent.futures import Future
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

EXP_DIR = Path(__file__).resolve().parent.parent / "experiments" / "06_control_menu"
if str(EXP_DIR) not in sys.path:
    sys.path.insert(0, str(EXP_DIR))

import common  # noqa: E402
import menu  # noqa: E402
import search  # noqa: E402
from nikke_opt.evaluator import BudgetExceeded, EvalResult  # noqa: E402

SQUAD = ["A", "B", "C"]
COMP = {"id": "c01", "squad": SQUAD, "skeleton": "1-1-3", "tags": [], "source": "test", "default_damage": 0}


def var(nikke, axis, name):
    who = nikke or "squad"
    patch = {"chars": {nikke: {"control": {axis: name}}}} if nikke else {"operation": {axis: name}}
    return {"nikke": nikke, "axis": axis, "label": f"{who}:{axis}:{name}", "patch": patch}


def fake_apply(options, chosen):
    keys = [(v["nikke"], v["axis"]) for v in chosen]
    if len(set(keys)) != len(keys):
        raise ValueError("같은 (니케, 축)이 둘")
    out = dict(options)
    for v in chosen:
        out = common.deep_merge(out, v["patch"])
    return out


def labels_of(line):
    """요청 줄에서 적용된 선택지 label 집합을 되짚는다."""
    out = set()
    for n, c in (line.get("chars") or {}).items():
        for axis, name in c.get("control", {}).items():
            out.add(f"{n}:{axis}:{name}")
    for axis, name in (line.get("operation") or {}).items():
        if axis != "auto":
            out.add(f"squad:{axis}:{name}")
    return frozenset(out)


class FakeEvaluator:
    """선택지 조합 → 결정론적 딜. 캐시를 흉내 내 같은 요청은 시뮬로 세지 않는다."""

    def __init__(self, score, budget=None):
        self.score = score  # (labels frozenset, line) -> int | None(오류)
        self.version = {"repo": "fake", "commit": "0" * 40}
        self.sim_count = 0
        self.cache_hits = 0
        self.budget = budget
        self.batches = []
        self._cache = {}

    def submit(self, requests):
        lines = [r.to_line() for r in requests]
        keys = [json.dumps(ln, sort_keys=True, ensure_ascii=False) for ln in lines]
        new = {k for k in keys if k not in self._cache}
        if self.budget is not None and self.sim_count + len(new) > self.budget:
            raise BudgetExceeded("가짜 예산")
        self.batches.append(len(lines))
        futs = []
        for k, ln in zip(keys, lines):
            f = Future()
            if k in self._cache:
                self.cache_hits += 1
                f.set_result(EvalResult(self._cache[k]["total_damage"], self._cache[k], cached=True))
            else:
                self.sim_count += 1
                d = self.score(labels_of(ln), ln)
                raw = {"total_damage": d, "control_detail": {"blocked": []}} if d is not None else \
                    {"total_damage": None, "error": {"code": "bad", "message": "x"}}
                self._cache[k] = raw
                f.set_result(EvalResult(d, raw))
            futs.append(f)
        return futs

    def evaluate(self, requests):
        return [f.result() for f in self.submit(requests)]

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


# 가짜 선택지: 키 셋, 각 2~3개
MENU = {
    ("A", "click"): [var("A", "click", "tap"), var("A", "click", "hold")],
    ("B", "reload"): [var("B", "reload", "a"), var("B", "reload", "b"), var("B", "reload", "c")],
    (None, "camera"): [var(None, "camera", "A"), var(None, "camera", "B")],
}
GAIN = {"A:click:tap": 5, "A:click:hold": 20, "B:reload:a": 3, "B:reload:b": -4, "B:reload:c": 10,
        "squad:camera:A": 7, "squad:camera:B": 1}


def separable(labels, line):
    return 1000 + sum(GAIN[lb] for lb in labels)


def all_selections(menu):
    keys = list(menu)
    for pick in itertools.product(*[[None] + vs for vs in menu.values()]):
        yield {k: v for k, v in zip(keys, pick) if v is not None}


def brute_best(menu, score):
    vals = []
    for sel in all_selections(menu):
        lbs = frozenset(v["label"] for v in sel.values())
        d = score(lbs, {})
        if d is not None:
            vals.append(d)
    return max(vals)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "run.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def run_c(self, condition, ev, menu=MENU, **kw):
        return search.run_condition(COMP, condition, ev, out=self.out, variants_fn=lambda s: menu,
                                    apply_fn=fake_apply, **kw)

    def records(self):
        return list(common.read_records([self.out])) if self.out.exists() else []


class TestSingle(Base):
    def test_single_conditions(self):
        ev = FakeEvaluator(separable)
        for cond in ("auto", "layer", "fixed_layer"):
            s = self.run_c(cond, ev)
            self.assertEqual((s["best_damage"], s["best_variants"], s["evals"]), (1000, [], 1))
        recs = self.records()
        self.assertEqual([(r["condition"], r["start"], r["step"], r["variants"]) for r in recs],
                         [("auto", "auto", 0, []), ("layer", "layer", 0, []), ("fixed_layer", "layer", 0, [])])
        self.assertIs(recs[0]["request"]["operation"]["auto"], True)
        self.assertNotIn("operation", recs[1]["request"])
        self.assertEqual(recs[1]["request"]["sim"]["burst_gauge_mode"], "accumulate")
        self.assertEqual(recs[2]["request"]["sim"]["burst_gauge_mode"], "fixed")
        for r in recs:
            self.assertEqual(set(r), set(common.RECORD_KEYS))
            self.assertEqual(r["request"]["squad"], SQUAD)
        # 다시 돌리면 재생만 — 기록이 늘지 않는다
        s = self.run_c("layer", ev)
        self.assertEqual((s["new_evals"], s["replayed"]), (0, 1))
        self.assertEqual(len(self.records()), 3)

    def test_unknown_condition(self):
        with self.assertRaises(ValueError):
            self.run_c("nope", FakeEvaluator(separable))


class TestDescent(Base):
    def test_separable_reaches_optimum(self):
        ev = FakeEvaluator(separable)
        s = self.run_c("search_from_layer", ev)
        self.assertEqual(s["best_damage"], brute_best(MENU, separable))
        self.assertEqual(s["best_variants"], ["A:click:hold", "B:reload:c", "squad:camera:A"])
        recs = self.records()
        self.assertEqual([r["step"] for r in recs], list(range(len(recs))))
        self.assertEqual(len({tuple(r["variants"]) for r in recs}), len(recs))  # 같은 선택 집합은 한 번
        self.assertEqual(s["evals"], len(recs))
        self.assertEqual(s["sims"], ev.sim_count)
        # 출발점 1 + 키 하나씩: 2 + 3 + 2. 마지막 키에서 개선 뒤 앞 두 키를 다시 보면 되돌리기 후보만 새로 생긴다
        self.assertEqual(ev.batches[:4], [1, 2, 3, 2])
        self.assertTrue(all(r["variants"] == sorted(r["variants"]) for r in recs))

    def test_from_auto(self):
        ev = FakeEvaluator(separable)
        s = self.run_c("search_from_auto", ev)
        recs = self.records()
        self.assertEqual(recs[0]["start"], "auto")
        self.assertTrue(all(r["request"]["operation"]["auto"] is True for r in recs))
        self.assertEqual(s["best_damage"], brute_best(MENU, separable))

    def test_removal_candidate(self):
        # A:tap를 먼저 고른 뒤 B:c를 더하면, A를 「바꾸지 않음」으로 되돌리는 것이 더 낫다
        menu = {("A", "click"): [var("A", "click", "tap")], ("B", "reload"): [var("B", "reload", "c")]}

        def score(lbs, line):
            d = 100 + (5 if "A:click:tap" in lbs else 0) + (10 if "B:reload:c" in lbs else 0)
            return d - (7 if {"A:click:tap", "B:reload:c"} <= lbs else 0)  # 함께 108 < c 혼자 110

        s = self.run_c("search_from_layer", FakeEvaluator(score), menu=menu)
        self.assertEqual((s["best_damage"], s["best_variants"]), (110, ["B:reload:c"]))
        self.assertIn(["B:reload:c"], [r["variants"] for r in self.records()])

    def test_ties_keep_current(self):
        def score(lbs, line):
            return 100 + (5 if "B:reload:c" in lbs or "B:reload:a" in lbs else 0)

        s = self.run_c("search_from_layer", FakeEvaluator(score))
        # A·camera는 동률이라 바꾸지 않고, B는 동률 후보 a·c 중 앞(a)
        self.assertEqual(s["best_variants"], ["B:reload:a"])

    def test_errors_recorded_and_skipped(self):
        def score(lbs, line):
            return None if "A:click:hold" in lbs else separable(lbs, line)

        s = self.run_c("search_from_layer", FakeEvaluator(score))
        recs = self.records()
        errs = [r for r in recs if r["error"]]
        self.assertTrue(errs)
        self.assertTrue(all(r["total_damage"] is None and "A:click:hold" in r["variants"] for r in errs))
        self.assertNotIn("A:click:hold", s["best_variants"])
        self.assertEqual(s["best_damage"], brute_best(MENU, score))

    def test_start_error(self):
        def score(lbs, line):
            return None if not lbs else separable(lbs, line)

        s = self.run_c("search_from_layer", FakeEvaluator(score))
        self.assertEqual(self.records()[0]["error"]["code"], "bad")
        self.assertEqual(s["best_damage"], brute_best(MENU, score))

    def test_budget(self):
        ev = FakeEvaluator(separable)
        s = self.run_c("search_from_layer", ev, budget=4)
        recs = self.records()
        self.assertEqual(len(recs), 4)
        self.assertTrue(s["exhausted"])
        self.assertEqual(s["best_damage"], max(r["total_damage"] for r in recs))  # 잘린 키 안의 후보도 반영
        self.assertEqual(s["best_damage"], 1023)  # 출발 · A 둘 · B 하나(hold + a)

    def test_evaluator_budget_exceeded(self):
        ev = FakeEvaluator(separable, budget=3)
        s = self.run_c("search_from_layer", ev)
        self.assertTrue(s["exhausted"])
        self.assertEqual(len(self.records()), 3)
        self.assertEqual(s["best_damage"], 1020)

    def test_resume_same_path(self):
        full = Path(self.tmp.name) / "full.jsonl"
        s_full = search.run_condition(COMP, "search_from_layer", FakeEvaluator(separable), out=full,
                                      variants_fn=lambda s: MENU, apply_fn=fake_apply)
        ev = FakeEvaluator(separable)
        self.run_c("search_from_layer", ev, budget=5)  # 키 중간에서 끊긴다
        s = self.run_c("search_from_layer", ev)
        self.assertEqual(s["replayed"], 5)
        strip = lambda rs: [(r["step"], r["variants"], r["total_damage"]) for r in rs]  # noqa: E731
        self.assertEqual(strip(self.records()), strip(common.read_records([full])))
        self.assertEqual((s["best_damage"], s["best_variants"], s["evals"]),
                         (s_full["best_damage"], s_full["best_variants"], s_full["evals"]))
        s = self.run_c("search_from_layer", ev)
        self.assertEqual(s["new_evals"], 0)
        self.assertEqual(len(self.records()), s_full["evals"])

    def test_resume_rejects_changed_menu(self):
        self.run_c("search_from_layer", FakeEvaluator(separable))
        changed = {k: [{**v, "patch": {"chars": {"A": {"control": {"x": 1}}}}} for v in vs]
                   for k, vs in MENU.items()}
        with self.assertRaises(ValueError):
            self.run_c("search_from_layer", FakeEvaluator(separable), menu=changed)


def interactive(lbs, line):
    """A:hold와 B:b가 함께일 때만 크게 좋다 — 레이어에서 출발한 하강은 놓친다."""
    d = separable(lbs, line)
    return d + (100 if {"A:click:hold", "B:reload:b"} <= lbs and "squad:camera:B" in lbs else 0)


class TestReference(Base):
    def test_layer_descent_misses_interaction(self):
        s = self.run_c("search_from_layer", FakeEvaluator(interactive))
        self.assertLess(s["best_damage"], brute_best(MENU, interactive))

    def test_reference_deterministic_and_finds_better(self):
        s1 = self.run_c("reference", FakeEvaluator(interactive), seed=3, reference_starts=6, reference_kicks=4)
        recs1 = self.records()
        self.out.unlink()
        s2 = self.run_c("reference", FakeEvaluator(interactive), seed=3, reference_starts=6, reference_kicks=4)
        strip = lambda rs: [(r["start"], r["step"], r["variants"]) for r in rs]  # noqa: E731
        self.assertEqual(strip(recs1), strip(self.records()))
        self.assertEqual(s1["best_damage"], s2["best_damage"])
        starts = [st["start"] for st in s1["starts"]]
        self.assertEqual(starts, [f"random:{i}" for i in range(3, 9)] + [f"kick:{i}" for i in range(3, 7)])
        for st in starts:  # 출발점마다 step이 0부터
            steps = [r["step"] for r in recs1 if r["start"] == st]
            self.assertEqual(steps, list(range(len(steps))))
        self.assertEqual(s1["best_damage"], brute_best(MENU, interactive))
        self.assertGreaterEqual(s1["best_damage"], max(st["best_damage"] for st in s1["starts"]))

    def test_reference_resume_and_budget(self):
        ev = FakeEvaluator(interactive)
        a = self.run_c("reference", ev, reference_starts=3, reference_kicks=2, budget=7)
        self.assertTrue(a["exhausted"])
        self.assertEqual(len(self.records()), 7)
        b = self.run_c("reference", ev, reference_starts=3, reference_kicks=2)
        full = Path(self.tmp.name) / "full.jsonl"
        c = search.run_condition(COMP, "reference", FakeEvaluator(interactive), out=full,
                                 variants_fn=lambda s: MENU, apply_fn=fake_apply,
                                 reference_starts=3, reference_kicks=2)
        strip = lambda rs: [(r["start"], r["step"], r["variants"]) for r in rs]  # noqa: E731
        self.assertEqual(strip(self.records()), strip(common.read_records([full])))
        self.assertEqual((b["best_damage"], b["evals"], b["replayed"]), (c["best_damage"], c["evals"], 7))


CONFLICT = {"A:click:hold", "squad:camera:A"}  # 함께면 조립 불가 — 막지 않으면 최선이 되는 짝


def conflict_apply(options, chosen):
    if CONFLICT <= {v["label"] for v in chosen}:
        raise menu.MenuConflict("A 홀드와 카메라 A는 함께 못 쓴다")
    return fake_apply(options, chosen)


def ok_best(score):
    vals = [score(frozenset(v["label"] for v in sel.values()), {}) for sel in all_selections(MENU)
            if not CONFLICT <= {v["label"] for v in sel.values()}]
    return max(vals)


class TestConflict(Base):
    def run_x(self, condition, ev, **kw):
        return search.run_condition(COMP, condition, ev, out=self.out, variants_fn=lambda s: MENU,
                                    apply_fn=conflict_apply, **kw)

    def assert_clean(self):
        recs = self.records()
        self.assertFalse([r for r in recs if CONFLICT <= set(r["variants"])])
        for st in {r["start"] for r in recs}:
            steps = [r["step"] for r in recs if r["start"] == st]
            self.assertEqual(steps, list(range(len(steps))))
        return recs

    def test_descent_skips_conflict(self):
        ev = FakeEvaluator(separable)
        s = self.run_x("search_from_layer", ev)
        recs = self.assert_clean()
        self.assertGreater(s["conflicts"], 0)
        self.assertEqual(ev.sim_count, len(recs))  # 충돌은 시뮬하지 않는다
        self.assertEqual(s["evals"], len(recs))
        self.assertEqual(s["best_damage"], ok_best(separable))
        self.assertLess(s["best_damage"], brute_best(MENU, separable))

    def test_budget_ignores_conflict(self):
        s = self.run_x("search_from_layer", FakeEvaluator(separable), budget=6)
        self.assertEqual(len(self.assert_clean()), 6)
        self.assertTrue(s["exhausted"])

    def test_resume_with_conflict(self):
        full = Path(self.tmp.name) / "full.jsonl"
        f = search.run_condition(COMP, "search_from_layer", FakeEvaluator(separable), out=full,
                                 variants_fn=lambda s: MENU, apply_fn=conflict_apply)
        ev = FakeEvaluator(separable)
        self.run_x("search_from_layer", ev, budget=6)
        s = self.run_x("search_from_layer", ev)
        strip = lambda rs: [(r["step"], r["variants"], r["total_damage"]) for r in rs]  # noqa: E731
        self.assertEqual(strip(self.assert_clean()), strip(common.read_records([full])))
        self.assertEqual((s["best_damage"], s["evals"], s["replayed"]), (f["best_damage"], f["evals"], 6))

    def test_reference_redraws_conflicting_start(self):
        s = self.run_x("reference", FakeEvaluator(separable), seed=0, reference_starts=12, reference_kicks=4)
        recs = self.assert_clean()
        self.assertEqual({r["start"] for r in recs if r["step"] == 0}, {st["start"] for st in s["starts"]})
        self.assertEqual(s["best_damage"], ok_best(separable))


class TestCli(Base):
    def test_main(self):
        comps = Path(self.tmp.name) / "comps.json"
        comps.write_text(json.dumps([COMP, {**COMP, "id": "c02", "squad": ["C", "B", "A"]}]), encoding="utf-8")
        fake_menu = types.ModuleType("menu")
        fake_menu.variants = lambda squad: MENU
        fake_menu.apply = fake_apply
        ev = FakeEvaluator(separable)
        argv = ["--comps", "all", "--conditions", "layer,search_from_layer,reference", "--out", str(self.out),
                "--compositions", str(comps), "--reference-starts", "2", "--seed", "1"]
        buf = io.StringIO()
        with mock.patch.dict(sys.modules, {"menu": fake_menu}), \
                mock.patch("nikke_opt.evaluator.make_evaluator", return_value=ev), redirect_stdout(buf), \
                mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(search.main(argv), 0)
            lines = [json.loads(x) for x in buf.getvalue().splitlines()]
            self.assertEqual([(x["comp_id"], x["condition"]) for x in lines],
                             [(c, k) for c in ("c01", "c02") for k in ("layer", "search_from_layer", "reference")])
            n = len(self.records())
            self.assertEqual({r["comp_id"] for r in self.records()}, {"c01", "c02"})
            buf.truncate(0)
            buf.seek(0)
            self.assertEqual(search.main(argv[:1] + ["c02"] + argv[2:]), 0)  # 재개: 기록이 늘지 않는다
            self.assertEqual(len(self.records()), n)
            with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
                search.main(["--comps", "c99", "--out", str(self.out), "--compositions", str(comps)])


if __name__ == "__main__":
    unittest.main()
