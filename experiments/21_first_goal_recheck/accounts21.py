"""실험 21 — 새 검증 계정 u1~u8 (README §평가 계정). 실험 20 결과를 보기 전에 고정했다.

시드 20261103. 개발 계정(실험 5~18의 d1~d8 · v1~v8, 실험 20의 t1~t8 · d1~d4)과 시드가 다르다.
렐릭 베어 없음 · 낮음 계정을 넣는다(2026-11-01 사용자: 렐릭 베어 없는 계정을 일반 문제로 고친다).

    python experiments/21_first_goal_recheck/accounts21.py      # 계정 요약 표
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

SEED_CHECK = 20261103


def check_scenarios() -> list[dict[str, Any]]:
    strong = AC.strong_nikkes()
    pool = [n for n in R10.P177 if not n.startswith("test_")]
    cubes_all = CB.supported()
    alt = [c for c in cubes_all if c != CB.DEFAULT_CUBE]

    def rng(tag: str) -> random.Random:
        return random.Random(f"{SEED_CHECK}-{tag}")

    out: list[dict[str, Any]] = []

    def add(name: str, missing=(), tiers=None, cubes=None, ammo=None) -> None:
        cubes = dict(cubes or {c: 15 for c in cubes_all})
        out.append({"name": name, "missing": sorted(missing), "tiers": dict(tiers or {}), "cubes": cubes,
                    "start_cube": AC.start_cube(cubes), "ammo": dict(ammo or {})})

    def tiers(names, tag):
        return AC._tiers(list(names), rng(tag))

    miss = rng("u1-miss").sample(strong, 5)
    drop = set(rng("u1-cube").sample(alt, 3))
    add("미보유 강한 니케 5명 + 큐브 3종 없음", miss, cubes={c: 15 for c in cubes_all if c not in drop})

    add("렐릭 베어 없음 + 육성 무작위", tiers=tiers(pool, "u2-tiers"), cubes={c: 15 for c in alt})

    r, r2 = rng("u3-cube"), rng("u3-ammo")
    add("육성 무작위 + 장탄 무작위 + 큐브 레벨 무작위(5~15)", tiers=tiers(pool, "u3-tiers"),
        cubes={c: r.randint(5, 15) for c in cubes_all}, ammo={n: r2.randint(0, 3) for n in pool})

    miss = rng("u4-miss").sample(strong, 4)
    r2 = rng("u4-ammo")
    add("렐릭 베어 없음 + 미보유 4명 + 장탄 무작위", miss, cubes={c: 15 for c in alt},
        ammo={n: r2.randint(0, 3) for n in pool if n not in miss})

    core = rng("u5-core").sample(strong, 5)
    r = rng("u5-cube")
    add("강한 니케 5명 육성 하 + 큐브 레벨 무작위(5~15)", tiers={n: "하" for n in core},
        cubes={c: r.randint(5, 15) for c in cubes_all})

    miss = rng("u6-miss").sample(strong, 3)
    cubes = {c: 15 for c in cubes_all}
    cubes[CB.DEFAULT_CUBE] = 5
    add("렐릭 베어 5(낮음) + 미보유 3명", miss, cubes=cubes)

    add("미보유 강한 니케 10명", rng("u7-miss").sample(strong, 10))

    miss = rng("u8-miss").sample(strong, 3)
    keep = [c for c in alt if c not in set(rng("u8-cube").sample(alt, 4))]
    r2 = rng("u8-ammo")
    add("혼합: 렐릭 베어 없음 + 미보유 3명 + 육성 무작위 + 장탄 무작위 + 큐브 4종 더 없음", miss,
        tiers=tiers([n for n in pool if n not in miss], "u8-tiers"), cubes={c: 15 for c in keep},
        ammo={n: r2.randint(0, 3) for n in pool if n not in miss})

    for i, s in enumerate(out, 1):
        s.update(id=f"u{i}", set="check21")
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
