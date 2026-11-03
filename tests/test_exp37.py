"""실험 37(니케별 옵션 프리셋) — 환경 구성 규칙. 평가기 없이 facts.json만 쓴다."""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R = sys.modules.get("run37") or _load("run37", ROOT / "experiments" / "37_option_presets" / "run37.py")


class EnvTest(unittest.TestCase):
    def test_stage2_20s_gets_fake_1_and_3_with_cdr(self):
        (e,) = R.envs("레오나")
        self.assertEqual(e["squad"], ["레오나", "test_F1_cdr75", "test_F3"])
        self.assertEqual(e["chars"], {})

    def test_own_cdr_drops_fake_cdr(self):
        (e,) = R.envs("리타")
        self.assertEqual(e["cdr"], 0.0)
        self.assertNotIn("cdr", "".join(e["squad"][1:]))

    def test_fullburst_change_moves_fake_cdr(self):
        self.assertEqual(R.envs("이사벨")[0]["cdr"], 12.5)   # 풀버 −5초
        self.assertEqual(R.envs("모더니아")[0]["cdr"], 2.5)  # 풀버 +5초

    def test_40s_alternates_with_same_stage_partner(self):
        es = R.envs("이사벨")
        self.assertEqual([e["phase"] for e in es], ["1/2", "2/2"])
        for e in es:
            mine = e["chars"]["이사벨"]["control"]["burst"]["pattern"]
            rest = e["chars"][e["squad"][-1]]["control"]["burst"]["pattern"]
            self.assertEqual(sorted(mine + rest), list(range(1, R.CYCLES + 1)))
            self.assertFalse(set(mine) & set(rest))

    def test_60s_has_three_phases(self):
        self.assertEqual(len(R.envs("블랑")), 3)

    def test_reentry_gets_all_three_fakes(self):
        (e,) = R.envs("티아")
        self.assertEqual(e["squad"][1:], ["test_F1", "test_F2", "test_F3"])

    def test_options_set_element_and_full_overload(self):
        (e,) = R.envs("레오나")
        code = R.facts()["레오나"]["code"]
        adv = R.env_options("레오나", e, True, R.E0)
        non = R.env_options("레오나", e, False, R.E0)
        self.assertEqual(adv["enemy"]["code"], R.BEATS[code])
        self.assertEqual(non["enemy"]["code"], code)
        self.assertEqual(set(adv["profile"]["chars"]["레오나"]["overload"]), set(R.KEYS9))


if __name__ == "__main__":
    unittest.main()
