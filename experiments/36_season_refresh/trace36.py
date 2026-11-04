"""실험 36 — 후처리 뒤 덱의 컨트롤 타임라인(사용자 요청 2026-11-03 「결과 덱에서의 컨트롤 요소를 시각화」).

    source .cache/evaluators.env && python -I experiments/36_season_refresh/trace36.py --season 33-42 --jobs 4
    → run_log/S??/trace/<덱 id>.json (우리 A 5덱 S??-0~4 · 랭커 덱 S??-r<j>)

후처리가 고른 최종 선택지(`final_variants`)와 장비 옵션 배분(`alloc`)으로 덱마다 **시뮬 1번**을 `sim.trace`를 켜고 다시 돈다
(nikke-calc-rs의 `sim.trace` — 결과에 버스트 · 풀버스트 · 클릭/엄폐 구간 · 카메라가 붙는다, 총딜은 그대로).
요청은 run36.post_deck과 같은 길(`control_space(시즌, 덱, 배분).options(선택지)`)로 짓고, 다시 돈 총딜이 기록된 최종 값과 같은지
(`match`) 적는다 — 같으면 화면의 타임라인이 그 값을 낸 바로 그 전투다. 이미 있는 덱 파일은 건너뛴다(`--force`로 다시).
화면용 모양은 `nikke_opt/timeline.py`(compact).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]
import run36 as X  # noqa: E402

from nikke_opt.evaluator import EvalRequest, make_evaluator  # noqa: E402
from nikke_opt.timeline import compact, traced  # noqa: E402


def seasons_arg(v: str) -> list[int]:
    out: list[int] = []
    for p in v.split(","):
        a, _, b = p.partition("-")
        out += list(range(int(a), int(b) + 1)) if b else [int(a)]
    return out


def decks(s: int) -> list[dict[str, Any]]:
    """그 시즌 후처리 덱 기록: 우리 A(post.json) 다음 랭커 묶음(rpost.json) — 같은 id는 한 번."""
    d = X.sdir(s)
    recs = list((X.jload(d / f"{X.POST_NAME}.json") or {}).get("decks") or [])
    for x in ((X.jload(d / f"r{X.POST_NAME}.json") or {}).get("sets") or {}).values():
        recs += (x or {}).get("decks") or []
    seen: dict[str, dict[str, Any]] = {}
    for r in recs:
        seen.setdefault(r["id"], r)
    return list(seen.values())


def request(s: int, x: dict[str, Any]) -> EvalRequest:
    squad = list(x["squad"])
    al = {n: X.run35.parse(lb) for n, lb in (x.get("alloc") or {}).items()}
    sp = X.control_space(s, squad, al)
    sel = sp.from_labels(x.get("final_variants") or [])
    opts = None if sel is None else sp.options(sel)
    if opts is None:
        raise RuntimeError(f"{x['id']}: 최종 선택지로 요청을 지을 수 없다 — {x.get('final_variants')}")
    # boss = None: 후처리 탐색(실험 7 M.Run)과 같다 — 보스 조건은 options(enemy 등)에 들어 있다
    return traced(EvalRequest(tuple(squad), boss=None, options=opts))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", default="33-42", help="예: 33-42 · 40 · 33,35")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--force", action="store_true", help="이미 있는 덱 파일도 다시")
    a = ap.parse_args(argv)
    X.need_config()
    t0, bad = time.time(), []
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        for s in seasons_arg(a.season):
            out = X.sdir(s) / X.POST_NAME.replace("post", "trace")
            todo = [x for x in decks(s) if a.force or not (out / f"{x['id']}.json").exists()]
            if not todo:
                continue
            res = ev.evaluate([request(s, x) for x in todo])
            out.mkdir(parents=True, exist_ok=True)
            for x, r in zip(todo, res):
                if r.error or "trace" not in r.raw:
                    raise RuntimeError(f"{x['id']}: 평가 실패 또는 trace 없음(평가기가 sim.trace를 모름?) — {r.error}")
                want = round(x["final"] * X.E8)
                ok = abs(r.total_damage - want) <= 1
                if not ok:
                    bad.append((x["id"], r.total_damage, want))
                X.jdump(out / f"{x['id']}.json", {
                    "id": x["id"], "season": s, "squad": list(x["squad"]), "final": x["final"], "total_damage": r.total_damage,
                    "match": ok, "final_variants": x.get("final_variants"), "evaluator": r.raw.get("evaluator"),
                    "timeline": compact(r.raw["trace"], x["squad"], r.raw["duration"])})
            print(f"S{s}: 덱 {len(todo)}개 · 값 같음 {sum(1 for x, r in zip(todo, res) if abs(r.total_damage - round(x['final'] * X.E8)) <= 1)}"
                  f"/{len(todo)}", flush=True)
        print(f"시뮬 {ev.sim_count} · {time.time() - t0:.0f}초 · 값 다름 {len(bad)}개 {bad[:5]}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
