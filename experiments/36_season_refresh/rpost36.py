"""실험 36 — 랭커 덱 후처리(사용자 요청 2026-11-03 「비교를 위해 랭커 대표덱과 랭커 최선덱도 후처리한 후에 보여줄 수 있을까?」).

    source .cache/evaluators.env && python -I experiments/36_season_refresh/rpost36.py --season 33,34 --jobs 2 --workers 2
    → run_log/S??/rpost.json · post/S??-r<j>.json(덱마다, run36 post_deck 모양)

세 묶음을 우리 A와 **같은 후처리**(run36.post_deck: ① 컨트롤 + 큐브 → ② 장비 옵션 12줄 · Lv11 → ③ 컨트롤 + 큐브 다시, 각 400평가)에 넣는다. 코어 없음만.
  top  = 랭커 대표 5덱(그 시즌 상위 300명이 5덱을 그대로 가장 많이 쓴 묶음, seasons.json `top_five`)
  pack = 랭커 스쿼드로 짠 최선 5덱(rankers.json의 코어 없음 사전 값으로 겹치지 않게 묶은 합 최대 = 화면의 V_pack 묶음)
  r1   = 랭커 1위 5덱(seasons.json `rank1`) — 2026-11-03 사용자 선택 「랭커 칸을 후처리 값으로 + 1위도」로 더함
지원하지 않는 니케가 든 묶음은 None. 같은 순서의 같은 덱은 한 번만 돈다(우리 A 후처리에 이미 있으면 그 기록을 쓴다).
묶음을 더하면(r1) rpost.json을 다시 만든다 — 덱 번호(r<j>)는 top → pack → r1 순서로 매겨 앞서 돈 덱 기록을 그대로 쓴다.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]
import run36 as X  # noqa: E402

SETS = ("top", "pack", "r1")
KEYS = ("pre", "ctrl", "E0", "O", "final")


def ranker_sets(s: int) -> dict[str, list[tuple[tuple[str, ...], float]] | None]:
    """{"top" | "pack": [(덱, 사전 값), ...] 5개 또는 None}."""
    rk = X.run31.season(s)["rankers"]
    rv = (X.jload(X.sdir(s) / "rankers.json") or {})["squads"]

    def val(q: tuple[str, ...]) -> float | None:
        return (rv.get(",".join(q)) or {}).get("nocore")

    def five(sq: list) -> list[tuple[tuple[str, ...], float]] | None:
        qs = [tuple(q) for q in sq]
        return [(q, val(q)) for q in qs] if len(qs) == 5 and all(val(q) is not None for q in qs) else None

    pack_in = {frozenset(k.split(",")): (e["nocore"], tuple(k.split(","))) for k, e in rv.items() if e.get("nocore") is not None}
    _, ch = X.R9.pack_vals(pack_in) if len(pack_in) >= 5 else (None, [])
    return {"top": five(rk["top_five"]["squads"]), "pack": [(tuple(q), v) for v, q in ch] if len(ch) == 5 else None,
            "r1": five(rk["rank1"]["squads"])}


def run_season(s: int, ev: Any, workers: int = 2) -> dict[str, Any]:
    f = X.sdir(s) / "rpost.json"
    old = X.jload(f) or {}
    if set(old.get("sets") or {}) >= set(SETS):
        return old
    sets = ranker_sets(s)
    ours = {tuple(d["squad"]): d for d in (X.jload(X.sdir(s) / "post.json") or {}).get("decks", [])}
    todo: list[tuple[tuple[str, ...], float]] = []
    for v in sets.values():
        for q, pre in v or []:
            if q not in ours and all(q != t[0] for t in todo):
                todo.append((q, pre))
    n0 = ev.sim_count
    with ThreadPoolExecutor(workers) as pool:
        recs = list(pool.map(lambda x: X.post_deck(s, f"r{x[0]}", x[1][0], None, x[1][1], ev), enumerate(todo)))
    for (q, _), r in zip(todo, recs):           # 앞서 돈 덱 기록을 번호로 다시 쓸 때 같은 덱인지
        assert tuple(r["squad"]) == q, (s, r["id"], q)
    by = {**ours, **{tuple(r["squad"]): r for r in recs}}
    out: dict[str, Any] = {"season": s, "arm": X.ARM, "sets": {}, "decks_new": len(todo),
                           "reused_from_A": sorted({",".join(q) for v in sets.values() for q, _ in v or [] if q in ours}),
                           "sims": (old.get("sims") or 0) + ev.sim_count - n0}
    for k in SETS:
        v = sets[k]
        if v is None:
            out["sets"][k] = None
            continue
        decks = [by[q] for q, _ in v]
        out["sets"][k] = {"decks": decks, "total": {key: sum(d[key] for d in decks) for key in KEYS}}
    X.jdump(f, out)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--season", required=True)
    p.add_argument("--jobs", type=int, default=2)
    p.add_argument("--workers", type=int, default=2)
    a = p.parse_args()
    X.need_config()
    from nikke_opt.evaluator import make_evaluator
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        for s in [int(x) for x in a.season.split(",")]:
            if not (X.sdir(s) / "rankers.json").exists() or not (X.sdir(s) / "post.json").exists():
                raise RuntimeError(f"S{s}: 먼저 rankers · post")
            out = run_season(s, ev, a.workers)
            print({"season": s, "sims": out["sims"], "decks_new": out["decks_new"],
                   **{k: None if x is None else round(x["total"]["final"], 2) for k, x in out["sets"].items()}}, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
