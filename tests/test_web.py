"""현황판 사이트(web/build.py) — 지금 run_log로 만들어지는지, 지표가 analyze22와 같은지, 결과 전 판을 「계산 전」으로 두는지,
화면에 나오는 니케 · 보스 · 속성 그림이 빠짐없이 있는지."""

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

    def test_every_nikke_has_face(self):
        """화면에 나오는 니케는 모두 얼굴 그림이 있다(니케 이름은 글자로 쓰지 않으므로). 없으면 web/sync_icons.py를 다시 돌린다."""
        names = B.site_names(self.data["seasons"])
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
