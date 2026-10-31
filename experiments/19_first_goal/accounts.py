"""실험 19 — 개발에 쓰지 않은 검증 계정 t1~t8 (README §평가 계정).

계정 조건은 고정 시드로 만든다(결과를 보고 바꾸지 않는다). 실험 5~18이 쓴 계정(d1~d8 · v1~v8)과 시드가 다르다.
개발 계정과 다른 점: 미보유 니케를 177명 풀의 강한 니케에서도 뽑고, 큐브 결손 · 큐브 레벨 · 장비 옵션의 최대 장탄 수 줄 수를 바꾼다
(2026-10-31 사용자: 장탄 수는 스킬 레벨 · 장비 옵션 · 큐브에 따라 달라지고 컨트롤이 그에 따라 달라진다).

    python experiments/19_first_goal/accounts.py        # 계정 요약 표
"""

from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXP17 = HERE.parent / "17_cube_control"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(EXP17))
R17 = sys.modules.get("run17") or _load("run17", EXP17 / "run17.py")
R10, R9, CB = R17.R10, R17.R9, R17.CB

SEED_TEST = 20261101
AMMO_DEFAULT = 2          # 평가기 기본 육성의 최대 장탄 수 옵션 줄 수(spec/tables.rs)
CUBE_PREF = (CB.DEFAULT_CUBE, "택티컬 베어 큐브")   # 출발 큐브: 앞에서부터 가진 것, 없으면 큐브 목록 순서로 첫 보유

STRONG_FILE = HERE / "strong_pool.json"   # 미보유 후보(아래 strong_nikkes) — 결과 전에 커밋


def strong_nikkes() -> list[str]:
    """미보유로 뽑을 강한 니케 후보: 실험 9 핵심(랭커 사용률 95% 이상) ∪ 실험 13 U4 · 2,000 검증 8개 계정의 최종 5덱 니케.
    (평가 답이 아니라 「빠지면 계정이 어려워지는 니케」를 고르는 데만 쓴다.) 시험용 니케(test_*)는 뺀다."""
    if STRONG_FILE.exists():
        return json.loads(STRONG_FILE.read_text(encoding="utf-8"))["names"]
    names = set(R9.core_nikkes())
    summ = R17.R16.load_summaries()
    for run, s in summ.items():
        if run.endswith("_P177_U4_2000"):
            for _, sq in s["final"]["squads"]:
                names.update(sq)
    return sorted(n for n in names if not n.startswith("test_"))


def start_cube(cubes: Mapping[str, int]) -> str:
    for c in CUBE_PREF:
        if c in cubes:
            return c
    return next(c for c in CB.supported() if c in cubes)


def _tiers(names: Sequence[str], rng: random.Random) -> dict[str, str]:
    return R9._random_tiers(names, rng)


def test_scenarios() -> list[dict[str, Any]]:
    strong = strong_nikkes()
    pool = [n for n in R10.P177 if not n.startswith("test_")]
    cubes_all = CB.supported()
    alt = [c for c in cubes_all if c != CB.DEFAULT_CUBE]

    def rng(tag: str) -> random.Random:
        return random.Random(f"{SEED_TEST}-{tag}")

    out: list[dict[str, Any]] = []

    def add(name: str, missing=(), tiers=None, cubes=None, ammo=None) -> None:
        cubes = dict(cubes or {c: 15 for c in cubes_all})
        out.append({"name": name, "missing": sorted(missing), "tiers": dict(tiers or {}), "cubes": cubes,
                    "start_cube": start_cube(cubes), "ammo": dict(ammo or {})})

    miss = rng("t1-miss").sample(strong, 4)
    drop = set(rng("t1-cube").sample(alt, 2))
    add("미보유 강한 니케 4명 + 큐브 2종 없음", miss, cubes={c: 15 for c in cubes_all if c not in drop})

    add("미보유 강한 니케 8명", rng("t2-miss").sample(strong, 8))

    r = rng("t3-cube")
    add("육성 무작위 + 큐브 레벨 무작위(5~15)", tiers=_tiers(pool, rng("t3-tiers")),
        cubes={c: r.randint(5, 15) for c in cubes_all})

    r = rng("t4-ammo")
    add("육성 무작위 + 장탄 옵션 무작위(0~3줄)", tiers=_tiers(pool, rng("t4-tiers")),
        ammo={n: r.randint(0, 3) for n in pool})

    add("렐릭 베어 없음 + 미보유 3명", rng("t5-miss").sample(strong, 3),
        cubes={c: 15 for c in cubes_all if c != CB.DEFAULT_CUBE})

    add("큐브 3종만(렐릭 베어 12 · 택티컬 베어 9 · 렐릭 퀀텀 7) + 육성 무작위", tiers=_tiers(pool, rng("t6-tiers")),
        cubes={CB.DEFAULT_CUBE: 12, "택티컬 베어 큐브": 9, "렐릭 퀀텀 큐브": 7})

    core6 = rng("t7-core").sample(strong, 6)
    add("강한 니케 6명 육성 하 + 전원 장탄 옵션 0줄", tiers={n: "하" for n in core6}, ammo={n: 0 for n in pool})

    miss = rng("t8-miss").sample(strong, 5)
    r = rng("t8-cube")
    keep = [c for c in cubes_all if c not in set(r.sample(alt, 4))]
    r2 = rng("t8-ammo")
    add("혼합: 미보유 5명 + 육성 무작위 + 큐브 4종 없음 · 레벨 무작위 + 장탄 무작위", miss,
        tiers=_tiers([n for n in pool if n not in miss], rng("t8-tiers")),
        cubes={c: r.randint(5, 15) for c in keep}, ammo={n: r2.randint(0, 3) for n in pool if n not in miss})

    for i, s in enumerate(out, 1):
        s.update(id=f"t{i}", set="test")
    return out


class AccountT:
    """검증 계정: 로스터 · 요청 options(육성 등급 + 장탄 줄 수 + 출발 큐브) · 큐브 보유. 실험 10 `Account10`과 같은 칸을 둔다."""

    def __init__(self, sc_: Mapping[str, Any]):
        self.id, self.name, self.pool = sc_["id"], sc_["name"], 177
        self.missing = list(sc_["missing"])
        names = [n for n in R10.P177 if n not in self.missing]
        self.owned = {n: {"burst": R10.BURST_ALL[n]} for n in names}
        self.names = sorted(self.owned)
        self.tier = {n: sc_["tiers"].get(n, "상") for n in self.owned}
        self.cubes = dict(sc_["cubes"])
        self.start = sc_["start_cube"]
        self.ammo = {n: k for n, k in sc_["ammo"].items() if n in self.owned}
        chars: dict[str, Any] = {}
        for n in self.names:
            e: dict[str, Any] = json.loads(json.dumps(R9.TIERS[self.tier[n]]))
            if n in self.ammo and self.ammo[n] != AMMO_DEFAULT:
                e.setdefault("overload", {})["max_ammo_pct"] = self.ammo[n]
            if self.start != CB.DEFAULT_CUBE or self.cubes[self.start] != CB.MAX_LEVEL:
                e["cube"] = {"name": self.start, "level": self.cubes[self.start]}
            if e:
                chars[n] = e
        self.options: dict[str, Any] = {"profile": {"base": "default", "chars": chars}} if chars else {}


def main() -> int:
    for s in test_scenarios():
        a = AccountT(s)
        ammo = sum(1 for k in a.ammo.values() if k != AMMO_DEFAULT)
        tiers = sum(1 for t in a.tier.values() if t != "상")
        print(f"{s['id']} {s['name']}: 미보유 {len(s['missing'])} · 등급 중/하 {tiers} · 큐브 {len(s['cubes'])}종"
              f"(출발 {s['start_cube']} Lv{s['cubes'][s['start_cube']]}) · 장탄 기본 밖 {ammo}명")
        if s["missing"]:
            print("   미보유:", ", ".join(s["missing"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
