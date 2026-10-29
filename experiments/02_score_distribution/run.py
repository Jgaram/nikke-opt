"""사전 실험 2 — 점수 분포. 한 보스(S40)·한 로스터(풀 60명, 전원 기본 스펙)에서 180초 시뮬을 돌린다.

세 묶음을 돌린다 (전부 기대값 모드, 결과는 어댑터 캐시에 쌓이므로 중단 후 다시 돌려도 이어진다):

- random  — 구조 규칙(버스트 틀)을 통과한 무작위 스쿼드. 틀은 랭커 빈도(실험 1 표 4)로 뽑고,
            단계마다 풀에서 균등하게 뽑는다. 같은 단계 안의 배치 순서도 무작위.
- ranker  — S40 랭커 덱의 구성, 랭커가 둔 배치 순서 그대로 (prepare.py의 ranker_squads.json).
- order   — random 앞쪽 일부의 "딜이 달라질 수 있는" 배치 순서 전부 (같은 버스트 단계 안의 순서 ×
            레드 후드(A)의 위치). 순서가 점수를 얼마나 흔드는지 본다.

사용: NIKKE_SIM_BIN=... (또는 NIKKE_CALC_DIR=...) python -m experiments.02_score_distribution.run   (레포 루트에서)
      python run.py --random 1500 --order 60   → results.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from itertools import permutations
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from nikke_opt.evaluator import EvalRequest, make_evaluator  # noqa: E402

BOSS = "솔로 레이드 S40"
SEED = 20261007
# (B1, B2, B3, A) 인원 → 랭커 빈도 (실험 1 표 4, 시즌 평균). A = 레드 후드(전 단계)
TEMPLATES = {(1, 1, 3, 0): 0.40, (1, 2, 2, 0): 0.24, (2, 1, 2, 0): 0.22,
             (1, 1, 2, 1): 0.06, (2, 1, 1, 1): 0.04}
CHUNK = 40  # 이만큼씩 평가하고 바로 기록한다


def stage_key(squad: tuple[str, ...], burst: dict[str, str]) -> tuple:
    """딜에 영향을 주는 순서 정보만 남긴 키: 단계마다 (A 포함) 그 단계 후보의 순서."""
    return tuple(tuple(n for n in squad if burst[n] in (s, "A")) for s in "123")


def distinct_orders(squad: tuple[str, ...], burst: dict[str, str]) -> list[tuple[str, ...]]:
    seen, out = set(), []
    for p in permutations(squad):
        k = stage_key(p, burst)
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def random_squads(pool: dict, n: int, rng: random.Random) -> list[tuple[str, ...]]:
    by_stage = {s: sorted(k for k, v in pool.items() if v["burst"] == s) for s in "123A"}
    temps, weights = zip(*TEMPLATES.items())
    seen, out = set(), []
    while len(out) < n:
        t = rng.choices(temps, weights)[0]
        members = [m for s, c in zip("123A", t) for m in rng.sample(by_stage[s], c)]
        if frozenset(members) in seen:
            continue
        seen.add(frozenset(members))
        stages = {s: [m for m in members if pool[m]["burst"] == s] for s in "123"}
        for v in stages.values():
            rng.shuffle(v)
        squad = stages["1"] + stages["2"] + stages["3"]
        if t[3]:
            squad.insert(rng.randrange(5), by_stage["A"][0])
        out.append(tuple(squad))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--random", type=int, default=1500)
    ap.add_argument("--order", type=int, default=60, help="순서 전수 평가할 random 스쿼드 수")
    ap.add_argument("--jobs", type=int)
    ap.add_argument("--out", default=str(HERE / "results.jsonl"))
    args = ap.parse_args()

    pool = json.loads((HERE / "pool.json").read_text(encoding="utf-8"))["pool"]
    burst = {k: v["burst"] for k, v in pool.items()}
    ranker = json.loads((HERE / "ranker_squads.json").read_text(encoding="utf-8"))["squads"]
    rng = random.Random(SEED)
    rand = random_squads(pool, args.random, rng)

    jobs: list[tuple[str, tuple[str, ...]]] = [("random", s) for s in rand]
    jobs += [("ranker", tuple(s["squad"])) for s in ranker]
    for s in rand[:args.order]:
        jobs += [("order", p) for p in distinct_orders(s, burst)]

    ev = make_evaluator(jobs=args.jobs)
    with open(args.out, "w", encoding="utf-8") as f:
        for i in range(0, len(jobs), CHUNK):
            part = jobs[i:i + CHUNK]
            res = ev.evaluate([EvalRequest(sq, boss=BOSS) for _, sq in part])
            for (group, sq), r in zip(part, res):
                row = {"group": group, "squad": list(sq), "key": [list(x) for x in stage_key(sq, burst)],
                       "total_damage": r.total_damage, "error": r.error,
                       "members": [m["damage"] for m in r.raw.get("members", [])]}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{min(i + CHUNK, len(jobs))}/{len(jobs)} · 시뮬 {ev.sim_count} · 캐시 {ev.cache_hits}",
                  file=sys.stderr, flush=True)
    meta = {"boss": BOSS, "evaluator": ev.version, "seed": SEED, "random": args.random,
            "order": args.order, "sims": ev.sim_count, "cache_hits": ev.cache_hits}
    (HERE / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
