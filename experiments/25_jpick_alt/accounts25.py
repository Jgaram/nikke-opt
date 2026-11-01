"""실험 25 — 새 검증 계정 w1~w8 (README §평가 계정). 결과를 보기 전에 고정했다.

실험 21 `check_scenarios`와 같은 8가지 계정 모양(미보유 · 육성 · 장탄 · 큐브 결손 · 렐릭 베어 없음 · 낮음)을
**시드만 20261104로 바꿔** 만든다. 개발 · 검증 계정(실험 9 20261007 · 20261030, 실험 19 20261101, 실험 20 20261102, 실험 21 20261103)과 시드가 다르다.

    python experiments/25_jpick_alt/accounts25.py      # 계정 요약 표
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP21 = HERE.parent / "21_first_goal_recheck"

SEED = 20261104


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(EXP21))
A21 = sys.modules.get("accounts21") or _load("accounts21", EXP21 / "accounts21.py")
AC = A21.AC


def check_scenarios() -> list[dict[str, Any]]:
    old = A21.SEED_CHECK
    A21.SEED_CHECK = SEED
    try:
        out = A21.check_scenarios()
    finally:
        A21.SEED_CHECK = old
    for i, s in enumerate(out, 1):
        s.update(id=f"w{i}", set="check25")
    return out


def main() -> int:
    for s in check_scenarios():
        a = AC.AccountT(s)
        ammo = sum(1 for k in a.ammo.values() if k != AC.AMMO_DEFAULT)
        nt = sum(1 for t in a.tier.values() if t != "상")
        print(f"{s['id']} {s['name']}: 미보유 {len(s['missing'])} · 등급 중/하 {nt} · 큐브 {len(s['cubes'])}종"
              f"(출발 {s['start_cube']} Lv{s['cubes'][s['start_cube']]}) · 장탄 기본 밖 {ammo}명")
    return 0


if __name__ == "__main__":
    sys.exit(main())
