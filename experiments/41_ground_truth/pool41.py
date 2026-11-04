"""실험 41 — 답안지 풀: 시즌마다 기계적 규칙으로 40명 안팎의 풀을 고르고 구조 통과 구성을 센다(시뮬 0). README §풀 규칙.

    python -I experiments/41_ground_truth/pool41.py          # → experiments/41_ground_truth/pool41.json

규칙(결과 전 고정):
1. 후보 = 그 시즌 랭커 상위 40 스쿼드 ∪ 대표 5덱 ∪ 1위 5덱의 니케 ∪ 실험 36 우리 A 5덱 25명(평가기 SSR 풀 · 시즌 풀 안).
2. 40명을 넘으면 우리 A 25명은 두고 나머지를 랭커 니케 사용 수(`rankers.units`, 없으면 0)가 적은 순으로 뺀다.
   동점은 (사용 수 내림차순, 이름순)으로 줄 세운 줄의 **끝에서부터** 뺀다 — 사전 등록 표(README, 2026-11-04 계산)를 만든 규칙이다.
   S42에서만 갈린다(사용 5회 셋 중 프리바티 : 언카인드 메이드가 빠진다. 이름순 앞에서 빼면 아르카나 : 포츈 메이트 → 27.8만 구성).
3. 표의 행 = 풀 안에서 구조 규칙(실험 10 `STRUCT_FRAMES`)을 통과하는 5인 구성 전부.
"""

from __future__ import annotations

import json
import sys
from itertools import combinations
from math import comb
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXPS = HERE.parent
ROOT = EXPS.parent
SEASONS = (36, 39, 42)
CAP = 40
SEASON_DATA = json.loads((EXPS / "31_recent_seasons" / "seasons.json").read_text(encoding="utf-8"))["seasons"]
BURST: dict[str, str] = dict(json.loads((EXPS / "10_rankerless_start" / "roster_ssr.json").read_text(encoding="utf-8"))["roster"])
EXP36_LOG = EXPS / "36_season_refresh" / "run_log"
REAL = EXPS / "32_primitive_control" / "diag" / "real_vs_calc.json.gz"
REAL_MIN = 10   # 실전 덱: 랭커 10명 이상이 쓴 덱(실험 32 R0)
OUT = HERE / "pool41.json"
# 실험 10 구조 틀 (B1, B2, B3, A): 1 · 2 · 3단계 각 1~3명, A(레드 후드) 0~1명, 3단계 + A ≥ 2
FRAMES = tuple((a, b, c, d) for a in range(1, 4) for b in range(1, 4) for c in range(1, 4) for d in range(2)
               if a + b + c + d == 5 and c + d >= 2)


def ranker_sets(s: int) -> dict[str, list[list[str]]]:
    r = SEASON_DATA[str(s)]["rankers"]
    return {"squads": [list(q["members"]) for q in r["squads"]], "top_five": r["top_five"]["squads"],
            "rank1": r["rank1"]["squads"]}


def our_a(s: int) -> list[list[str]]:
    """실험 36 우리 A(코어 없음 지도의 최선 5덱 — maps.json `nocore|A` 대표 0번)."""
    m = json.loads((EXP36_LOG / f"S{s}" / "maps.json").read_text(encoding="utf-8"))["nocore|A"]
    return [list(q) for q in m["reps"][0]["decks"]]


def usage(s: int) -> dict[str, int]:
    return {n: c for n, c in SEASON_DATA[str(s)]["rankers"]["units"]}


def real_decks(s: int) -> list[dict[str, Any]]:
    import gzip
    d = json.loads(gzip.open(REAL).read().decode("utf-8"))
    return [x for x in d[str(s)] if x["n"] >= REAL_MIN]


def frame(comp: Sequence[str]) -> tuple[int, int, int, int]:
    c = [BURST[n] for n in comp]
    return (c.count("1"), c.count("2"), c.count("3"), c.count("A"))


def passes(comp: Sequence[str]) -> bool:
    return len(set(comp)) == 5 and frame(comp) in FRAMES


def stages(pool: Sequence[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {k: [] for k in "123A"}
    for n in sorted(pool):
        out[BURST[n]].append(n)
    return out


def count_comps(pool: Sequence[str]) -> int:
    st = stages(pool)
    return sum(comb(len(st["1"]), a) * comb(len(st["2"]), b) * comb(len(st["3"]), c) * comb(len(st["A"]), d)
               for a, b, c, d in FRAMES)


def iter_comps(pool: Sequence[str]) -> Iterator[tuple[str, ...]]:
    """구조 통과 구성 전부(결정론 순서: 틀 순 → 단계마다 이름순 조합). 원소는 이름순 튜플."""
    st = stages(pool)
    for a, b, c, d in FRAMES:
        for x1 in combinations(st["1"], a):
            for x2 in combinations(st["2"], b):
                for x3 in combinations(st["3"], c):
                    for xa in combinations(st["A"], d):
                        yield tuple(sorted(x1 + x2 + x3 + xa))


def build(s: int, cap: int = CAP) -> dict[str, Any]:
    v = SEASON_DATA[str(s)]
    season_pool = set(v["pool"]) & set(BURST)
    rk = ranker_sets(s)
    a = our_a(s)
    ranker_names = {n for qs in rk.values() for q in qs for n in q}
    a_names = {n for q in a for n in q}
    cand = sorted((ranker_names | a_names) & season_pool)
    use = usage(s)
    pool = list(cand)
    dropped: list[str] = []
    if len(pool) > cap:
        keep_order = sorted((n for n in pool if n not in a_names), key=lambda n: (-use.get(n, 0), n))
        dropped = keep_order[len(keep_order) - (len(pool) - cap):][::-1]   # 줄 끝(사용 수 가장 적은 쪽)부터
        pool = sorted(set(pool) - set(dropped))
    st = stages(pool)
    pset = set(pool)
    sq = SEASON_DATA[str(s)]["rankers"]["squads"]
    inside = [q for q in sq if set(q["members"]) <= pset]
    return {
        "season": s, "boss": v["boss"], "element": v["element"], "code": v["code"],
        "candidates": len(cand), "outside_season_or_ssr": sorted((ranker_names | a_names) - set(cand)),
        "pool": pool, "dropped": [[n, use.get(n, 0)] for n in dropped],
        "stages": {k: len(x) for k, x in st.items()}, "comps": count_comps(pool),
        "our_a": a, "our_a_outside_rankers": sorted(a_names - ranker_names),
        "ranker_squads_in": len(inside), "ranker_squads_total": len(sq),
        "ranker_squads_in_weighted": round(sum(q["count"] for q in inside) / sum(q["count"] for q in sq), 4),
        "ranker_sets_in": {k: sum(set(q) <= pset for q in qs) for k, qs in rk.items()},
        "real_decks_in": sum(set(x["deck"].split(",")) <= pset for x in real_decks(s)), "real_decks_total": len(real_decks(s)),
    }


def main() -> int:
    out = {"rule": "랭커 상위 40 스쿼드 ∪ 대표 5덱 ∪ 1위 5덱 ∪ 실험 36 우리 A 25명(SSR · 시즌 풀 안), 40명 초과 시 A 밖을 "
                   "(rankers.units 사용 수 내림차순, 이름순)으로 줄 세워 끝에서부터 뺀다. 행 = 실험 10 구조 틀 통과 5인 구성 전부",
           "cap": CAP, "frames": [list(f) for f in FRAMES], "seasons": {}}
    for s in SEASONS:
        out["seasons"][str(s)] = build(s)
        b = out["seasons"][str(s)]
        print(f"S{s}: 후보 {b['candidates']} 풀 {len(b['pool'])} 단계 {b['stages']} 구성 {b['comps']:,} "
              f"랭커 스쿼드 {b['ranker_squads_in']}/{b['ranker_squads_total']} ({b['ranker_squads_in_weighted']:.0%}) "
              f"실전 덱 {b['real_decks_in']}/{b['real_decks_total']} 뺀 니케 {b['dropped']} A 밖 {b['our_a_outside_rankers']}")
    out["total_comps"] = sum(b["comps"] for b in out["seasons"].values())
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"합 {out['total_comps']:,} → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
