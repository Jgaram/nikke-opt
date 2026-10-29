"""실험 7 탐색 기법(methods.py) · 분석(analyze7.py) — 가짜 평가기 · 가짜 선택지로 확인한다."""

import itertools
import json
import math
import random
import sys
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

EXP7 = Path(__file__).resolve().parent.parent / "experiments" / "07_control_search"
if str(EXP7) not in sys.path:
    sys.path.insert(0, str(EXP7))

import analyze7  # noqa: E402
import methods as M  # noqa: E402
import common  # noqa: E402  (methods가 실험 6 폴더를 sys.path에 넣는다)

K, NO = 12, 3
GROUP = [(0, 1), (3, 0), (7, 2), (10, 1)]


def vfn(squad):
    return {(f"N{k}", "reload"): [{"nikke": f"N{k}", "axis": "reload", "label": f"N{k}:reload:o{o}",
                                   "patch": {"chars": {f"N{k}": {"control": {"o": o}}}}} for o in range(NO)]
            for k in range(K)}


def afn(opts, chosen):
    out = dict(opts)
    for v in chosen:
        out = common.deep_merge(out, v["patch"])
    return out


def make_value(seed=1):
    rng = random.Random(seed)
    main = {(k, o): rng.gauss(-0.01, 0.005) for k in range(K) for o in range(NO)}
    for g in GROUP:
        main[g] = -0.01
    pair = {(a, b): 0.012 for a, b in itertools.combinations(GROUP, 2)}

    def val(options):
        ch = sorted((int(n[1:]), c["control"]["o"]) for n, c in options.get("chars", {}).items())
        y = sum(main[x] for x in ch) + sum(pair.get(p, 0.0) for p in itertools.combinations(ch, 2))
        return int(1e9 * math.exp(y))
    return val


class FakeEv:
    def __init__(self, val):
        self.val, self.sim_count, self.calls = val, 0, 0

    def submit(self, reqs):
        self.calls += 1
        out = []
        for r in reqs:
            f = Future()
            self.sim_count += 1
            f.set_result(SimpleNamespace(error=None, total_damage=self.val(r.options), cached=False))
            out.append(f)
        return out


COMP = {"id": "s1", "squad": ["N0"]}
PRIOR = M.Prior("flat", {"main": (0.0, 1e-4), "pair": (0.0, 1e-4)}, 1e-6)


def space():
    return M.Space(COMP["squad"], variants_fn=vfn, apply_fn=afn)


class TestLabels(unittest.TestCase):
    def test_name_with_colon_nikke(self):
        v = {"nikke": "미하라 : 본딩 체인", "axis": "click", "label": "미하라 : 본딩 체인:click:hold_own_fb"}
        self.assertEqual(M._name(v), "hold_own_fb")
        self.assertEqual(M.main_group(v), "click|hold_own_fb")
        t = {"nikke": None, "axis": "tactic", "label": "squad:tactic:버충=레드 후드"}
        self.assertEqual(M.main_group(t), "tactic|버충")
        self.assertEqual(M._subject(t), "레드 후드")
        r = {"nikke": "레드 후드", "axis": "reload", "label": "레드 후드:reload:A0.3"}
        self.assertEqual(M.pair_group(t, r), "reload|tactic|same")


class TestMethods(unittest.TestCase):
    def run_spec(self, spec, budget=300):
        ev = FakeEv(make_value())
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "r.jsonl"
            s = M.run_job(COMP, spec, ev, budget=budget, out=out, priors={"flat": PRIOR, "attr": PRIOR}, space=space())
            recs = [json.loads(x) for x in out.read_text().splitlines()]
        return s, recs, ev

    def test_records_and_budget(self):
        for spec in ("M0", "M1:flat", "M2:flat:t0.3", "M3:k2"):
            s, recs, ev = self.run_spec(spec, budget=150)
            self.assertLessEqual(s["evals"], 150, spec)
            self.assertEqual([r["step"] for r in recs], list(range(len(recs))), spec)
            self.assertEqual(len({tuple(r["variants"]) for r in recs}), len(recs), spec)  # 같은 선택은 한 번
            self.assertEqual(recs[0]["variants"], [], spec)  # 출발은 기본 레이어
            self.assertEqual(s["best_damage"], max(r["total_damage"] for r in recs), spec)
            self.assertEqual(ev.sim_count, len(recs), spec)

    def test_m0_is_coordinate_descent(self):
        s, recs, _ = self.run_spec("M0", budget=10_000)
        self.assertFalse(s["exhausted"])
        sp = space()
        best = sp.from_labels(s["best_variants"])
        val = make_value()
        here = val(sp.options(best))
        for k in range(sp.K):  # 수렴점은 한 키 이동으로 엄격히 좋아지지 않는다
            for nb in sp.neighbors(best, k):
                self.assertLessEqual(val(sp.options(nb)), here)

    def test_interaction_found_by_global_methods(self):
        sp = space()
        val = make_value()
        planted = list(sp.empty())
        for k, o in GROUP:
            planted[k] = sp.opts[k][o]
        planted = tuple(planted)
        target = val(sp.options(planted))
        m0, _, _ = self.run_spec("M0", budget=400)
        self.assertLess(m0["best_damage"], target)  # 하나씩은 손해라 좌표 하강은 못 닿는다
        for spec in ("M3:k2", "M2:flat:t0.3"):
            s, _, _ = self.run_spec(spec, budget=400)
            self.assertGreaterEqual(s["best_damage"], target, spec)

    def test_parse_method(self):
        self.assertEqual(M.parse_method("M2:attr:t0.3"), ("M2", {"prior_kind": "attr", "temp": 0.3}))
        self.assertEqual(M.parse_method("M3:k4"), ("M3", {"kick": 4}))
        with self.assertRaises(ValueError):
            M.parse_method("M9")


class TestPrior(unittest.TestCase):
    def test_em_shapes(self):
        sp = space()
        val = make_value()
        rng = random.Random(0)
        sels = [sp.empty()] + [M.random_sel(sp, rng) for _ in range(80)]
        base = val(sp.options(sp.empty()))
        y = [math.log(val(sp.options(s)) / base) for s in sels]
        import numpy as np
        for kind in ("attr", "flat"):
            p = M.learn_prior(kind, {"s1": (sp, sels, np.array(y))}, iters=3)
            self.assertGreater(p.sigma2, 0)
            self.assertTrue(all(v > 0 for _, v in p.groups.values()))
            if kind == "flat":
                self.assertEqual(set(p.groups), {"main", "pair"})
            q = M.Prior.from_json(json.loads(json.dumps(p.to_json())))
            self.assertEqual(q.groups.keys(), p.groups.keys())


class TestAnalyze(unittest.TestCase):
    def runs(self, curves):
        """curves: {(comp, method): [딜...]} → load_runs 형식."""
        out = {}
        for (cid, m), ds in curves.items():
            out[(cid, m)] = [{"comp_id": cid, "method": m, "step": i, "variants": [] if i == 0 else [f"x{i}"],
                              "total_damage": d} for i, d in enumerate(ds)]
        return out

    def test_decide_prefers_cheapest_and_m3_rule(self):
        comps = [f"v{i}" for i in range(16)]
        curves = {}
        for c in comps:
            curves[(c, "M0")] = [100] * 50
            curves[(c, "M3:k2")] = [100] * 150 + [1000] * 650  # 150평가 뒤 닿음
            curves[(c, "M2:attr:t0.3")] = [100] * 150 + [1000] * 650  # 같음 — M3보다 낫지 않다
        s = analyze7.summarize(self.runs(curves), {}, comps)
        d = analyze7.decide(s)
        self.assertEqual((d["line"], d["method"], d["budget"]), (1, "M3:k2", 200))

    def test_decide_none(self):
        comps = ["v1", "v2"]
        curves = {(c, "M0"): [100, 101] for c in comps}
        s = analyze7.summarize(self.runs(curves), {"v1": 1000, "v2": 1000}, comps)
        self.assertEqual(analyze7.decide(s)["line"], 3)


if __name__ == "__main__":
    unittest.main()
