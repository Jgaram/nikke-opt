"""실험 10 분석(analyze10.py) — 합성 실행 요약으로 판단 규칙 · 곡선 지표 · 결과 쓰기를 확인한다."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

EXP10 = Path(__file__).resolve().parent.parent / "experiments" / "10_rankerless_start"
if str(EXP10) not in sys.path:
    sys.path.insert(0, str(EXP10))

import analyze10 as A  # noqa: E402

SCEN = list(A.VAL_SCENARIOS)
BASE = 100.0


def T_of(g, pool=60, budgets=A.BUDGETS):
    """g: 기법 → 예산 → [시나리오별 H]. K = 100, 나머지 = 100 · (1 + H). 없는 기법은 H = 0."""
    out = {}
    for i, s in enumerate(SCEN):
        for b in budgets:
            out[(s, pool, "K", b)] = BASE
            for m in A.METHODS[1:]:
                out[(s, pool, m, b)] = BASE * (1 + g.get(m, {}).get(b, [0.0] * 8)[i])
    return out


def bad(m_list, budgets=(800, 2000)):
    """명시한 기법 · 예산 외의 모든 랭커 없는 기법을 「못하다」로 둔다(기본 H = 0은 「못지않다」라서)."""
    down = [-0.05] * 8
    return {m: {b: down for b in A.BUDGETS} for m in A.RANKERLESS if m not in m_list}


def summary(s, pool, m, b, total, history=None, pre_order=None, kicks=None, alt=None, alt20=None, start=None):
    history = history or [{"evals": 40, "pack": total * 0.8, "kick": False}, {"evals": b, "pack": total, "kick": False}]
    return {"scenario": s, "name": f"이름 {s}", "pool": pool, "method": m, "budget": b, "evals": history[-1]["evals"],
            "errors": 0, "start": start or {"evals": history[0]["evals"], "pack": history[0]["pack"]},
            "history": history, "pre_order": pre_order or {"evals": history[-1]["evals"], "pack": total},
            "kicks": kicks or [], "final": {"total": total, "squads": []},
            "alt": alt or {"total": total * 0.98, "squads": [], "shared_nikkes": 23},
            "alt20": alt20 or {"total": 0, "squads": [], "shared_nikkes": 0}, "sims_during": 10, "seconds": 1.5}


class TestRules(unittest.TestCase):
    def test_noninferior_edges(self):
        one_low = [0.0] * 7 + [-0.031]
        self.assertTrue(A.noninferior(one_low))
        self.assertFalse(A.noninferior([0.0] * 6 + [-0.031, -0.04]))
        # 정확히 −3%는 「−3%보다 낮다」가 아니다 · 정확히 −0.5% 중앙은 통과(부동소수 경계 포함)
        self.assertTrue(A.noninferior([99.5 / 100 - 1] * 6 + [0.97 - 1] * 2))
        self.assertFalse(A.noninferior([-0.006] * 8))
        self.assertFalse(A.noninferior([]))

    def test_better_worse(self):
        self.assertTrue(A.better([0.01] * 6 + [-0.01, -0.02]))
        self.assertFalse(A.better([0.01] * 5 + [-0.01] * 3))
        self.assertTrue(A.worse([-0.01] * 6 + [0.01] * 2))
        self.assertFalse(A.worse([-0.004] * 8))

    def test_pair(self):
        self.assertEqual(A.pair_of("R"), "R+E")
        self.assertEqual(A.pair_of("G+E"), "G")


class TestJudge1(unittest.TestCase):
    def test_line1_rg_before_p(self):
        g = bad(["G", "P+E"])
        g["G"] = {b: [0.0] * 8 for b in A.BUDGETS}
        g["P+E"] = {b: [0.02] * 8 for b in A.BUDGETS}  # P가 H는 더 커도 R · G 계열이 먼저
        j = A.judge1(T_of(g), SCEN)
        self.assertEqual((j["line"], j["pick"], j["selected"], j["pair"]), (1, "G", "G", "G+E"))
        self.assertEqual(sorted(j["names"]), ["G", "P+E"])

    def test_line1_by_2000_then_800(self):
        g = bad(["R", "G+E"])
        g["R"] = {800: [0.03] * 8, 2000: [0.01] * 8, 300: [0.0] * 8}
        g["G+E"] = {800: [0.0] * 8, 2000: [0.02] * 8, 300: [0.0] * 8}
        self.assertEqual(A.judge1(T_of(g), SCEN)["pick"], "G+E")
        g["G+E"][2000] = [0.01] * 8  # 2,000 같으면 800
        self.assertEqual(A.judge1(T_of(g), SCEN)["pick"], "R")

    def test_line2(self):
        g = bad(["R+E", "P"])
        g["R+E"] = {300: [-0.1] * 8, 800: [-0.02] * 8, 2000: [0.0] * 8}
        g["P"] = {300: [-0.1] * 8, 800: [0.0] * 8, 2000: [0.01] * 8}
        j = A.judge1(T_of(g), SCEN)
        self.assertEqual((j["line"], j["pick"]), (1, "P"))  # P는 둘 다 통과 → 1줄
        g["P"][800] = [-0.01] * 8
        j = A.judge1(T_of(g), SCEN)
        self.assertEqual((j["line"], j["pick"], sorted(j["names"])), (2, None, ["P", "R+E"]))
        self.assertEqual(j["selected"], "P")  # 2,000 중앙이 가장 큰 랭커 없는 기법
        self.assertEqual(j["pair"], "P+E")

    def test_line3_and_two_low(self):
        g = bad(["R"])
        g["R"] = {b: [0.0] * 6 + [-0.04, -0.05] for b in A.BUDGETS}  # 중앙은 0이지만 −3% 아래가 2개
        j = A.judge1(T_of(g), SCEN)
        self.assertEqual(j["line"], 3)
        self.assertEqual(j["selected"], "R")
        self.assertEqual(j["noninf"]["R"], [])

    def test_exactly_one_low_passes(self):
        g = bad(["R"])
        g["R"] = {b: [0.0] * 7 + [-0.2] for b in A.BUDGETS}
        j = A.judge1(T_of(g), SCEN)
        self.assertEqual((j["line"], j["pick"]), (1, "R"))
        self.assertEqual(j["small_budget"]["noninf"], ["R"])

    def test_300_not_judged(self):
        g = bad(["R"])
        g["R"] = {300: [0.05] * 8, 800: [-0.02] * 8, 2000: [-0.02] * 8}
        j = A.judge1(T_of(g), SCEN)
        self.assertEqual(j["line"], 3)
        self.assertEqual(j["small_budget"]["better"], ["R"])

    def test_missing_scenarios(self):
        T = T_of({})
        for s in SCEN[:3]:
            for m in A.METHODS:
                T.pop((s, 60, m, 2000))
        j = A.judge1(T, SCEN)
        self.assertEqual(j["line"], 1)  # 남은 5개로 판단
        T = {k: v for k, v in T.items() if k[2] == "K"}  # 랭커 없는 실행이 전혀 없음
        j = A.judge1(T, SCEN)
        self.assertEqual((j["line"], j["selected"]), (3, None))


class TestJudge2(unittest.TestCase):
    def test_adopt(self):
        up = [0.01] * 6 + [-0.01, -0.02]
        j = A.judge2(T_of({"K+E": {2000: up, 800: [-0.004] * 8}, "R+E": {2000: up, 800: [-0.01] * 8}}), SCEN)
        self.assertTrue(j["adopt"])
        self.assertFalse(j["per_start"]["R"]["adopt"])  # 800에서 「못하다」
        self.assertTrue(j["per_start"]["R"]["better2000"])
        j = A.judge2(T_of({"K+E": {2000: [0.004] * 8}}), SCEN)
        self.assertFalse(j["adopt"])

    def test_escape_vs_own_start(self):
        # G+E는 K보다 낮아도 G 대비로 잰다
        g = {"G": {b: [-0.10] * 8 for b in A.BUDGETS}, "G+E": {b: [-0.09] * 8 for b in A.BUDGETS}}
        j = A.judge2(T_of(g), SCEN)
        self.assertTrue(j["per_start"]["G"]["adopt"])
        self.assertAlmostEqual(j["per_start"]["G"]["median2000"], 0.91 / 0.90 - 1)


class TestLeak(unittest.TestCase):
    def test_verdicts(self):
        T = T_of({}, budgets=(2000,))
        T.update(T_of({"R": {2000: [-0.004] * 8}}, pool=177, budgets=(2000,)))
        lk = A.leak_check(T, SCEN, "R")
        self.assertEqual(lk["verdict"], A.LEAK_SAME)
        self.assertEqual(lk["methods"], ["R", "R+E", "K", "K+E"])
        self.assertAlmostEqual(lk["ratio_median"]["R"], 0.996)
        T.update(T_of({"R": {2000: [-0.01] * 8}}, pool=177, budgets=(2000,)))
        self.assertEqual(A.leak_check(T, SCEN, "R")["verdict"], A.LEAK_ONLY)
        self.assertIsNone(A.leak_check(T_of({}), SCEN, "R"))  # P177 실행 없음
        self.assertIsNone(A.leak_check(T, SCEN, None)["verdict"])


class TestCurves(unittest.TestCase):
    H = [{"evals": 36, "pack": 150.0, "kick": False}, {"evals": 136, "pack": 170.0, "kick": False},
         {"evals": 236, "pack": 180.0, "kick": True}, {"evals": 336, "pack": 180.0, "kick": False},
         {"evals": 400, "pack": 181.0, "kick": False}]

    def test_reach(self):
        r = {"history": self.H}
        self.assertEqual(A.reach_evals(r, 170.0), 136)
        self.assertEqual(A.reach_evals(r, 180.0 + 1e-12), 236)
        self.assertIsNone(A.reach_evals(r, 181.5))

    def test_stall(self):
        self.assertEqual(A.stall_evals({"history": self.H, "pre_order": {"evals": 336, "pack": 180.0}}), 236)
        self.assertEqual(A.stall_evals({"history": self.H}), 236)  # pre_order 없으면 끝에서 두 번째 줄
        self.assertIsNone(A.stall_evals({"history": self.H[:1]}))

    def test_progress_and_alt(self):
        runs = {}
        for s in SCEN[:2]:
            runs[(s, 60, "K", 2000)] = summary(s, 60, "K", 2000, 180.0)
            kicks = [{"evals": 236, "best": 180.0, "improved": True}, {"evals": 336, "best": 180.0, "improved": False}]
            runs[(s, 60, "R+E", 2000)] = summary(s, 60, "R+E", 2000, 181.0, history=self.H,
                                                  pre_order={"evals": 336, "pack": 180.0}, kicks=kicks,
                                                  alt20={"total": 170.0, "squads": [], "shared_nikkes": 18})
        runs[("v3", 60, "R+E", 2000)] = summary("v3", 60, "R+E", 2000, 100.0)  # K 없음 → 도달 계산에서 뺀다
        T = {k: r["final"]["total"] for k, r in runs.items()}
        rows = {(r["method"], r["budget"]): r for r in A.progress_rows(runs, T, 60)}
        x = rows[("R+E", 2000)]
        self.assertEqual((x["reach"], x["reached"], x["unreached"]), (236, 2, 0))
        self.assertEqual((x["kicks"], x["improved"]), (2, 1))
        self.assertEqual(x["n"], 3)
        self.assertAlmostEqual(rows[("K", 2000)]["start_ratio"], 0.8)
        alt = {(r["method"], r["budget"]): r for r in A.alt_rows(runs, 60)}[("R+E", 2000)]
        self.assertEqual(alt["alt20"]["found"], 2)
        self.assertEqual(alt["alt20"]["shared"], 18)
        self.assertAlmostEqual(alt["alt20"]["ratio"], 170.0 / 181.0)

    def test_unreached(self):
        runs = {("v1", 60, "K", 2000): summary("v1", 60, "K", 2000, 200.0),
                ("v1", 60, "R", 800): summary("v1", 60, "R", 800, 190.0)}
        T = {k: r["final"]["total"] for k, r in runs.items()}
        x = {(r["method"], r["budget"]): r for r in A.progress_rows(runs, T, 60)}[("R", 800)]
        self.assertEqual((x["reach"], x["unreached"]), (None, 1))

    def test_known_best(self):
        runs = {("v1", 60, "R", 2000): summary("v1", 60, "R", 2000, 190.0),
                ("v1", 177, "R", 2000): summary("v1", 177, "R", 2000, 195.0)}
        exp9 = [{"scenario": "v1", "method": "L2", "budget": 800, "final": {"total": 192.0}},
                {"scenario": "d1", "method": "L2", "budget": 800, "final": {"total": 999.0}}]
        kb = A.known_best(runs, exp9, SCEN, 60)
        self.assertEqual(kb["v1"], {"total": 192.0, "source": "실험 9 L2 · 800"})
        self.assertEqual(A.known_best(runs, exp9, SCEN, 177)["v1"]["total"], 195.0)  # 실험 9는 P60에만


class TestMain(unittest.TestCase):
    def _write(self, d, r):
        (d / f"{r['scenario']}_P{r['pool']}_{r['method']}_{r['budget']}.json").write_text(
            json.dumps(r, ensure_ascii=False), encoding="utf-8")

    def test_main_writes_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            val, p177, dev = tmp / "val", tmp / "p177", tmp / "dev"
            for d in (val, p177, dev):
                d.mkdir()
            for i, s in enumerate(SCEN):
                for m in A.METHODS:
                    for b in A.BUDGETS:
                        if (s, m, b) == ("v8", "P+E", 300):
                            continue  # 빠진 실행 하나
                        tot = 180.0 + i + (0.5 if m.startswith("G") else 0.0) - (5.0 if m.startswith("P") else 0.0)
                        self._write(val, summary(s, 60, m, b, tot))
                for m in ("G", "G+E", "K", "K+E"):
                    self._write(p177, summary(s, 177, m, 2000, 185.0 + i + (0.2 if m == "G+E" else 0.0)))
                self._write(dev, summary(s.replace("v", "d"), 60, "R", 800, 170.0))
                self._write(dev, summary(s.replace("v", "d"), 60, "K", 800, 171.0))
            (val / "precompute_P60.json").write_text(json.dumps(
                {"pool": 60, "budget": 5000, "evals": 5000, "sims": 4100, "seconds": 160.0, "sets": [[]] * 8,
                 "set_totals": [190.0] * 8, "coef": {}, "final": {"total": 191.0}}), encoding="utf-8")
            exp9 = tmp / "val_summary.jsonl"
            exp9.write_text(json.dumps({"scenario": "v1", "method": "L0", "budget": 2000, "final": {"total": 999.0}}) + "\n",
                            encoding="utf-8")
            out, js = tmp / "results.md", tmp / "summary.json"
            rc = A.main(["--runs", str(val), "--p177", str(p177), "--dev-runs", str(dev), "--exp9-log", str(exp9),
                         "--out", str(out), "--json", str(js)])
            self.assertEqual(rc, 0)
            text = out.read_text(encoding="utf-8")
            self.assertIn("analyze10.py", text)
            self.assertIn("1줄 「랭커 없이도 된다」: G", text)  # G · G+E 동점 → 앞의 G
            self.assertIn(A.LEAK_SAME, text)
            self.assertIn("v8_P60_P+E_300", text)
            self.assertIn("실험 9 L0 · 2000", text)
            self.assertLess(text.index("## 판단"), text.index("## 기법별 H"))
            a = json.loads(js.read_text(encoding="utf-8"))
            self.assertEqual(a["judge1"]["pick"], "G")
            self.assertEqual(a["missing"], ["v8_P60_P+E_300"])  # P177은 G · G+E · K · K+E가 다 있다
            self.assertEqual(a["precompute"]["60"]["sims"], 4100)
            self.assertFalse(a["judge2"]["adopt"])

    def test_main_empty_and_bad_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "broken.json").write_text("{", encoding="utf-8")
            out = tmp / "results.md"
            rc = A.main(["--runs", str(tmp), "--p177", str(tmp / "없음"), "--exp9-log", str(tmp / "없음"),
                         "--out", str(out)])
            self.assertEqual(rc, 0)
            text = out.read_text(encoding="utf-8")
            self.assertIn("3줄", text)
            self.assertIn("빠진 실행", text)


if __name__ == "__main__":
    unittest.main()
