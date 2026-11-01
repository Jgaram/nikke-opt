"""현황판 사이트(web/build.py) — 지금 run_log로 만들어지는지, 지표가 analyze22와 같은지, 결과 전 판을 「계산 전」으로 두는지,
화면에 나오는 니케 · 보스 · 속성 그림이 빠짐없이 있는지, 편성안 계층(실험 29가 있으면 그것, 없으면 실험 28)을 그대로 옮기는지."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def _load():
    name = "web_build"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, WEB / "build.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


B = _load()


class TestWebBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.data = B.build(cls.tmp / "site")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_files(self):
        for f in (*B.STATIC, "data.json", ".nojekyll"):
            self.assertTrue((self.tmp / "site" / f).exists(), f)
        on_disk = json.loads((self.tmp / "site" / "data.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["progress"], self.data["progress"])

    def test_every_season_and_boss(self):
        seasons = sorted(int(k) for k in B.R22.SEASON_DATA)
        self.assertEqual([s["season"] for s in self.data["seasons"]], seasons)
        n = 0
        for s in self.data["seasons"]:
            self.assertEqual(set(s["by_boss"]), set(B.R22.BOSSES))
            for b, r in s["by_boss"].items():
                self.assertIn(r["status"], ("done", "pending"))
                self.assertIn("rankers", r)               # 결과 전이어도 랭커 덱 값은 있다
                pre = B.A22.LOG / f"precompute_{B.R22.run_name(s['season'], b)}.json"
                self.assertEqual(r["status"] == "done", pre.exists())
                n += r["status"] == "done"
        self.assertEqual(self.data["progress"]["done"], n)
        self.assertEqual(self.data["progress"]["total"], len(seasons) * len(B.R22.BOSSES))

    def test_metrics_match_analyze22(self):
        for s in self.data["seasons"]:
            m = B.A22.season_metrics(s["season"])
            self.assertEqual(s.get("better"), m.get("better"))
            for b, r in s["by_boss"].items():
                if r["status"] != "done":
                    continue
                for k in ("total", "N25", "D4", "V_top", "V_r1", "V_pack", "sims", "seconds"):
                    self.assertEqual(r[k], m["by_boss"][b][k], (s["season"], b, k))

    def test_done_run_shape(self):
        for s in self.data["seasons"]:
            for b, r in s["by_boss"].items():
                if r["status"] != "done":
                    continue
                self.assertEqual(len(r["decks"]), 5)
                names = [n for d in r["decks"] for n in d["order"]]
                self.assertEqual(len(names), 25)
                self.assertEqual(len(set(names)), 25)
                self.assertAlmostEqual(sum(d["value"] for d in r["decks"]), r["total"], places=6)
                ranks = [a["rank"] for a in r["alts"]]
                self.assertEqual(ranks, list(range(2, 2 + len(ranks))))
                for a in r["alts"]:
                    self.assertLessEqual(a["ratio"], 1.0 + 1e-9)
                    self.assertLessEqual(a["same_decks"], 2)   # 앞 순위와 같은 덱 2개 이하(run11.extract)
                hits = [r["reach"][k] for k in ("95", "99", "99.5", "100")]
                self.assertTrue(all(x is not None for x in hits))
                self.assertEqual(hits, sorted(hits))
                self.assertEqual(r["history"][-1][1], r["total"])

    def test_pending_when_no_results(self):
        """precompute가 하나도 없는 run_log: 모두 계산 전, 판단은 시즌 0개."""
        log = self.tmp / "log_empty"
        log.mkdir()
        for f in B.A22.LOG.glob("rankers_S*.json"):
            shutil.copyfile(f, log / f.name)
        old = B.A22.LOG
        B.A22.LOG = log
        try:
            d = B.build_data()
        finally:
            B.A22.LOG = old
        self.assertEqual(d["progress"]["done"], 0)
        self.assertEqual(d["judge"]["seasons"], 0)
        for s in d["seasons"]:
            for r in s["by_boss"].values():
                self.assertEqual(r["status"], "pending")
                self.assertIsNotNone(r["rankers"]["top_five"]["total"])

    def test_tree_source(self):
        """실험 29 analysis.json이 있으면 그것, 없으면 실험 28 것."""
        t = self.data["tree"]
        self.assertIsNotNone(t)
        want = next(e for e, d in B.TREE_SOURCES if (d / "analysis.json").exists())
        self.assertEqual(t["experiment"], want)
        self.assertEqual([r["scenario"] for r in t["rows"]], [f"w{k}" for k in range(1, 9)])

    def test_tree_matches_analysis(self):
        """큰 분류 · 세부 분류 값은 analysis.json 그대로, 세부 분류 5덱은 대표에서 바뀐 덱만 다르다."""
        _, d = B.tree_source()
        src = {r["scenario"]: r for r in json.loads((d / "analysis.json").read_text(encoding="utf-8"))["rows"]}
        for r in self.data["tree"]["rows"]:
            a = src[r["scenario"]]
            self.assertEqual(r["best"], a["best"])
            self.assertEqual([c["name"] for c in r["classes"]], ["A", "B", "C"])
            for c, k in zip(r["classes"], a["classes"]):
                for f in ("found", "total", "ratio", "subs_count"):
                    self.assertEqual(c[f], k[f], (r["scenario"], c["name"], f))
                if not c["found"]:
                    continue
                self.assertEqual([x["order"] for x in c["decks"]], [q for _, q in k["decks"]])
                self.assertAlmostEqual(sum(x["value"] for x in c["decks"]), c["total"], places=6)
                self.assertEqual(c["more_left"], c["subs_count"] - len(c["subs"]))
                self.assertEqual(set(c["vs"]), {o["name"] for o in r["classes"] if o["found"]} - {c["name"]})
                rep = [x["order"] for x in c["decks"]]
                for s, t in zip(c["subs"], k["subs"]):
                    for f in ("total", "J", "changed", "out", "in", "moves", "new_unposted"):
                        self.assertEqual(s[f], t[f])
                    self.assertEqual([sl["no"] for sl in s["slots"]], s["changed"])
                    self.assertEqual(sorted(map(sorted, (sl["order"] for sl in s["slots"]))), sorted(map(sorted, t["new_decks"])))
                    plan = [list(q) for q in rep]
                    vals = [x["value"] for x in c["decks"]]
                    for sl in s["slots"]:
                        plan[sl["no"] - 1], vals[sl["no"] - 1] = sl["order"], sl["value"]
                    names = [n for q in plan for n in q]
                    self.assertEqual(len(set(names)), 25)
                    self.assertAlmostEqual(sum(vals), s["total"], places=6)
                    self.assertEqual(B.SIM.moves(rep, plan), s["moves"])
                    for n, a_, b_ in s["moved"]:
                        self.assertIn(n, rep[a_ - 1])
                        self.assertIn(n, plan[b_ - 1])

    def test_tree_falls_back_to_28(self):
        old = B.TREE_SOURCES
        B.TREE_SOURCES = ((29, self.tmp / "none"), old[-1])
        try:
            t = B.tree_block()
        finally:
            B.TREE_SOURCES = old
        self.assertEqual(t["experiment"], 28)
        self.assertEqual(t["file"], "experiments/28_plan_tree/analysis.json")
        B.TREE_SOURCES = ((29, self.tmp / "none"),)
        try:
            self.assertIsNone(B.tree_block())
        finally:
            B.TREE_SOURCES = old

    def test_every_nikke_has_face(self):
        """화면에 나오는 니케는 모두 얼굴 그림이 있다(니케 이름은 글자로 쓰지 않으므로). 없으면 web/sync_icons.py를 다시 돌린다."""
        names = B.all_names(self.data)
        self.assertTrue(B.tree_names(self.data["tree"]) <= names)
        self.assertGreater(len(names), 100)
        self.assertEqual(self.data["icons"]["missing"], [])
        for n in names:
            img = self.data["nikke"].get(n, {}).get("img")
            self.assertTrue(img, n)
            self.assertTrue((self.tmp / "site" / img).exists(), (n, img))
            for e in self.data["nikke"][n]["el"]:
                self.assertTrue((self.tmp / "site" / "icons" / "elements" / f"{e.lower()}.png").exists(), (n, e))
            self.assertIn(self.data["nikke"][n].get("b"), ("1", "2", "3", "A"), n)

    def test_boss_and_element_images(self):
        for s in self.data["seasons"]:
            self.assertTrue(s["boss_img"], s["season"])
            self.assertTrue((self.tmp / "site" / s["boss_img"]).exists(), s["boss_img"])
            for e in (s["element"], s["weak"]):
                self.assertTrue((self.tmp / "site" / "icons" / "elements" / f"{e.lower()}.png").exists(), e)
        for f in ("i", "ii", "iii", "i-ii-iii"):
            self.assertTrue((self.tmp / "site" / "icons" / "bursts" / f"{f}.png").exists(), f)

    def test_icon_index_matches_files(self):
        """icons.json이 가리키는 그림은 모두 있고, 가리키지 않는 얼굴 · 보스 그림은 남아 있지 않다."""
        idx = B.icon_index()
        units = {f"{u['id']}.webp" for u in idx["units"].values()}
        bosses = {f"{b}.webp" for b in idx["bosses"].values()}
        self.assertEqual({p.name for p in (B.ICONS / "units").iterdir()}, units)
        self.assertEqual({p.name for p in (B.ICONS / "bosses").iterdir()}, bosses)
        self.assertTrue(idx["source"].get("commit"))

    @unittest.skipUnless(shutil.which("node"), "node 없음")
    def test_app_js_syntax(self):
        subprocess.run(["node", "--check", str(WEB / "app.js")], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
