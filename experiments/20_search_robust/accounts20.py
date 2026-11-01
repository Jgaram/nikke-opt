"""실험 20 — 개발 계정: 실험 19 t1~t8(검증을 마쳐 이제 개발용) + 렐릭 베어 없음 · 낮음 d1~d4 (README §개발 계정).

d1~d4는 고정 시드로 만든다(결과를 보고 바꾸지 않는다). 2026-11-01 사용자: 렐릭 베어 없는 계정을 일반 문제로 보고 고친다
— 개발 계정에 렐릭 베어 있음 · 없음을 둘 다 넣는다.

    python experiments/20_search_robust/accounts20.py      # 계정 요약 표
"""

from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP19 = HERE.parent / "19_first_goal"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(EXP19))
AC = sys.modules.get("accounts") or _load("accounts", EXP19 / "accounts.py")
R10, R9, CB = AC.R10, AC.R9, AC.CB

SEED_DEV = 20261102


def new_dev_scenarios() -> list[dict[str, Any]]:
    strong = AC.strong_nikkes()
    pool = [n for n in R10.P177 if not n.startswith("test_")]
    cubes_all = CB.supported()
    no_bear = [c for c in cubes_all if c != CB.DEFAULT_CUBE]

    def rng(tag: str) -> random.Random:
        return random.Random(f"{SEED_DEV}-{tag}")

    out: list[dict[str, Any]] = []

    def add(name: str, missing=(), tiers=None, cubes=None, ammo=None) -> None:
        cubes = dict(cubes)
        out.append({"name": name, "missing": sorted(missing), "tiers": dict(tiers or {}), "cubes": cubes,
                    "start_cube": AC.start_cube(cubes), "ammo": dict(ammo or {})})

    add("렐릭 베어 없음(그 밖 큐브 전부 15)", cubes={c: 15 for c in no_bear})

    miss = rng("d2-miss").sample(strong, 4)
    add("렐릭 베어 없음 + 육성 무작위 + 미보유 강한 니케 4명", miss,
        tiers=AC._tiers([n for n in pool if n not in miss], rng("d2-tiers")), cubes={c: 15 for c in no_bear})

    miss = rng("d3-miss").sample(strong, 3)
    r = rng("d3-cube")
    cubes = {c: r.randint(5, 15) for c in no_bear}
    cubes["택티컬 베어 큐브"] = 8
    r2 = rng("d3-ammo")
    add("렐릭 베어 없음 + 택티컬 베어 8 · 큐브 레벨 무작위 + 장탄 무작위 + 미보유 3명", miss, cubes=cubes,
        ammo={n: r2.randint(0, 3) for n in pool if n not in miss})

    miss = rng("d4-miss").sample(strong, 2)
    cubes = {c: 15 for c in cubes_all}
    cubes[CB.DEFAULT_CUBE] = 3
    add("렐릭 베어 3(낮음) + 육성 무작위 + 미보유 2명", miss,
        tiers=AC._tiers([n for n in pool if n not in miss], rng("d4-tiers")), cubes=cubes)

    for i, s in enumerate(out, 1):
        s.update(id=f"d{i}", set="dev20")
    return out


def dev_scenarios() -> list[dict[str, Any]]:
    """개발 계정 12개: 실험 19 t1~t8 + d1~d4."""
    return AC.test_scenarios() + new_dev_scenarios()


def main() -> int:
    for s in dev_scenarios():
        a = AC.AccountT(s)
        ammo = sum(1 for k in a.ammo.values() if k != AC.AMMO_DEFAULT)
        tiers = sum(1 for t in a.tier.values() if t != "상")
        print(f"{s['id']} {s['name']}: 미보유 {len(s['missing'])} · 등급 중/하 {tiers} · 큐브 {len(s['cubes'])}종"
              f"(출발 {s['start_cube']} Lv{s['cubes'][s['start_cube']]}) · 장탄 기본 밖 {ammo}명")
    return 0


if __name__ == "__main__":
    sys.exit(main())
