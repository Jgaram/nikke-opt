"""실험 36 곁가지 — 카메라 재장전 규칙(`sim.camera_reload_cancel`)을 켜고 후처리 167덱을 다시 돈다. README §카메라 재장전 규칙으로 후처리 다시.

    source .cache/evaluators.env && python -I experiments/36_season_refresh/cr36.py check
      기록된 최종 선택지로 167덱을 시뮬 1번씩: 옵션 끔(= 기록 값이어야) · 옵션 켬(새 규칙 · 옛 선택지) → run_log/cr_check.json
    source .cache/evaluators.env && python -I experiments/36_season_refresh/cr36.py run --season 33,34 --jobs 2 --workers 2
      우리 A 5덱(post_cr/ · post_cr.json) → 랭커 묶음(rpost_cr.json). 끝난 덱 · 시즌은 건너뛴다. 옵션 없는 요청이 나가면 멈춘다.
    python -I experiments/36_season_refresh/cr36.py analyze     # 시뮬 0 → cr_analysis.json · cr_results.md

후처리 절차 · 예산 · 난수 시드(덱 id)는 run36.post_deck 그대로다. 바뀌는 것은 요청 options.sim에 camera_reload_cancel = true 하나.
옛 기록(post/ · post.json · rpost.json · trace/ · analysis.json)과 사이트(web/)는 건드리지 않는다.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import threading
import time
from pathlib import Path
from typing import Any, Sequence

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]
import run36 as X  # noqa: E402
import rpost36 as RP  # noqa: E402
import trace36 as T  # noqa: E402

FLAG = {"camera_reload_cancel": True}
NEW = "post_cr"
LOG = HERE / "run_log"
CHECK = LOG / "cr_check.json"


def use_new() -> None:
    X.POST_NAME, X.SIM_EXTRA = NEW, dict(FLAG)


def use_old() -> None:
    X.POST_NAME, X.SIM_EXTRA = "post", {}


class Guard:
    """평가기 감싸기 — 나가는 요청마다 options.sim.camera_reload_cancel이 켜졌는지 본다. 하나라도 빠지면 멈춘다."""

    def __init__(self, ev: Any):
        self._ev, self._lock, self.checked = ev, threading.Lock(), 0

    def _check(self, reqs: Sequence[Any]) -> None:
        for r in reqs:
            if not ((r.options or {}).get("sim") or {}).get("camera_reload_cancel"):
                raise RuntimeError(f"카메라 재장전 옵션 없는 요청: {list(r.squad)}")
        with self._lock:
            self.checked += len(reqs)

    def evaluate(self, reqs: Sequence[Any]) -> list[Any]:
        self._check(reqs)
        return self._ev.evaluate(reqs)

    def submit(self, reqs: Sequence[Any]) -> list[Any]:
        self._check(reqs)
        return self._ev.submit(reqs)

    def __getattr__(self, k: str) -> Any:
        return getattr(self._ev, k)


def final_request(s: int, x: dict[str, Any]) -> Any:
    """기록된 최종 선택지 · 배분으로 요청 하나(trace36.request와 같은 길, trace 없이)."""
    from nikke_opt.evaluator import EvalRequest
    squad = list(x["squad"])
    al = {n: X.run35.parse(lb) for n, lb in (x.get("alloc") or {}).items()}
    sp = X.control_space(s, squad, al)
    sel = sp.from_labels(x.get("final_variants") or [])
    if sel is None:
        raise RuntimeError(f"{x['id']}: 최종 선택지로 요청을 지을 수 없다 — {x.get('final_variants')}")
    return EvalRequest(tuple(squad), boss=None, options=sp.options(sel))


def cmd_check(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    use_old()
    decks = [(s, x) for s in X.SEASONS for x in T.decks(s)]
    off = [final_request(s, x) for s, x in decks]
    use_new()
    on = [final_request(s, x) for s, x in decks]
    use_old()
    assert all(not (r.options.get("sim") or {}).get("camera_reload_cancel") for r in off)
    assert all(r.options["sim"]["camera_reload_cancel"] for r in on)
    t0 = time.time()
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        ver = f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"
        r_off, r_on = ev.evaluate(off), ev.evaluate(on)
    rows = []
    for (s, x), a0, a1 in zip(decks, r_off, r_on):
        if a0.error or a1.error:
            raise RuntimeError(f"{x['id']}: {a0.error or a1.error}")
        rows.append({"id": x["id"], "season": s, "ours": "-r" not in x["id"], "final": x["final"],
                     "off": a0.total_damage / X.E8, "on": a1.total_damage / X.E8,
                     "off_match": abs(a0.total_damage - round(x["final"] * X.E8)) <= 1})
    out = {"evaluator": ver, "decks": len(rows), "off_match": sum(r["off_match"] for r in rows),
           "changed": sum(abs(r["on"] / r["off"] - 1) > 1e-9 for r in rows), "seconds": round(time.time() - t0, 1), "rows": rows}
    X.jdump(CHECK, out)
    d = [r["on"] / r["off"] - 1 for r in rows]
    print(json.dumps({k: out[k] for k in ("evaluator", "decks", "off_match", "changed", "seconds")}, ensure_ascii=False))
    print(f"−1% 밑 {sum(x < -0.01 for x in d)} · −3% 밑 {sum(x < -0.03 for x in d)} · 최소 {min(d):+.2%} · 덱 중앙 {st.median(d):+.2%}")
    return 0 if out["off_match"] == out["decks"] else 1


def cmd_run(a: argparse.Namespace) -> int:
    X.need_config()
    from nikke_opt.evaluator import make_evaluator
    use_new()
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        g = Guard(ev)
        ver = f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"
        for s in [int(x) for x in str(a.season).split(",")]:
            pf = X.sdir(s) / f"part_{NEW}.json"
            if pf.exists():
                continue
            n0, t0 = ev.sim_count, time.time()
            tot = X.part_post(s, g, a.workers)
            rp = RP.run_season(s, g, a.workers)
            out = {"season": s, "part": NEW, "evaluator": ver, "flag": FLAG, "sims": ev.sim_count - n0, "checked": g.checked,
                   "seconds": round(time.time() - t0, 1), "A": tot["total"],
                   "rankers": {k: None if v is None else v["total"] for k, v in rp["sets"].items()}}
            X.jdump(pf, out)
            print(json.dumps({k: out[k] for k in ("season", "sims", "seconds")} | {"A_final": round(tot["total"]["final"], 2)},
                             ensure_ascii=False), flush=True)
    return 0


# ---------------------------------------------------------------- 분석(시뮬 0)

def _sum(rows: list[dict[str, Any]], key: str) -> float:
    return sum(r[key] for r in rows)


def analyze() -> dict[str, Any]:
    chk = {r["id"]: r for r in (X.jload(CHECK) or {}).get("rows", [])}
    seasons = {}
    for s in X.SEASONS:
        d = X.sdir(s)
        old_a, new_a = X.jload(d / "post.json"), X.jload(d / f"{NEW}.json")
        old_r, new_r = X.jload(d / "rpost.json") or {}, X.jload(d / f"r{NEW}.json")
        if not (old_a and new_a and new_r):
            continue
        row = {"A": {"old": old_a["total"]["final"], "new": new_a["total"]["final"],
                     "old_choice": _sum([chk[x["id"]] for x in old_a["decks"]], "on") if chk else None}, "sets": {}}
        for k in RP.SETS:
            o, n = (old_r.get("sets") or {}).get(k), (new_r.get("sets") or {}).get(k)
            if not (o and n):
                row["sets"][k] = None
                continue
            row["sets"][k] = {"old": o["total"]["final"], "new": n["total"]["final"],
                              "old_choice": _sum([chk[x["id"]] for x in o["decks"]], "on") if chk else None}
        seasons[s] = row
    med = lambda xs: st.median(xs) if xs else None  # noqa: E731
    a_new = [r["A"]["new"] / r["A"]["old"] - 1 for r in seasons.values()]
    a_choice = [r["A"]["old_choice"] / r["A"]["old"] - 1 for r in seasons.values() if r["A"]["old_choice"]]
    vs = {k: {"old": [r["sets"][k]["old"] / r["A"]["old"] for r in seasons.values() if r["sets"].get(k)],
              "new": [r["sets"][k]["new"] / r["A"]["new"] for r in seasons.values() if r["sets"].get(k)]} for k in RP.SETS}
    return {"seasons": seasons, "done": len(seasons), "A_new_vs_old_median": med(a_new), "A_old_choice_vs_old_median": med(a_choice),
            "ranker_over_A": {k: {"old_median": med(v["old"]), "new_median": med(v["new"]),
                                  "old_wins": sum(x > 1 for x in v["old"]), "new_wins": sum(x > 1 for x in v["new"]), "n": len(v["new"])}
                              for k, v in vs.items()}}


def write_md(an: dict[str, Any]) -> str:
    p = lambda x: "—" if x is None else f"{x:+.2%}"  # noqa: E731
    L = ["# 실험 36 곁가지 — 카메라 재장전 규칙으로 후처리 다시", "",
         "`cr36.py analyze`가 만든다. 값 = 코어 없음 5덱 합(억), 후처리 뒤. 옛 = 옛 규칙 기록(post · rpost), 옛 선택지 = 옛 최종 선택지를 새 규칙으로 1번, 새 = 새 규칙에서 후처리 다시.", "",
         "| 시즌 | 우리 A 옛 | 옛 선택지 | 새 | 새 ÷ 옛 | 랭커 대표 ÷ A 옛 → 새 | 랭커 1위 ÷ A 옛 → 새 | 스쿼드 최선 ÷ A 옛 → 새 |", "|---|---|---|---|---|---|---|---|"]
    for s, r in an["seasons"].items():
        A = r["A"]
        cells = []
        for k in ("top", "r1", "pack"):
            x = r["sets"].get(k)
            cells.append("—" if not x else f"{x['old'] / A['old']:.1%} → {x['new'] / A['new']:.1%}")
        oc = "—" if A["old_choice"] is None else f"{A['old_choice']:.1f} ({p(A['old_choice'] / A['old'] - 1)})"
        L.append(f"| S{s} | {A['old']:.1f} | {oc} | {A['new']:.1f} | {p(A['new'] / A['old'] - 1)} | " + " | ".join(cells) + " |")
    ro = an["ranker_over_A"]
    L += ["", f"- 끝난 시즌 {an['done']}/10 · 우리 A 새 ÷ 옛 시즌 중앙 {p(an['A_new_vs_old_median'])} · 옛 선택지 ÷ 옛 {p(an['A_old_choice_vs_old_median'])}"]
    for k, name in (("top", "랭커 대표"), ("r1", "랭커 1위"), ("pack", "랭커 스쿼드 최선")):
        x = ro[k]
        if x["n"]:
            L.append(f"- {name} ÷ 우리 A 시즌 중앙: 옛 {x['old_median']:.1%}(우리보다 높은 시즌 {x['old_wins']}) → 새 {x['new_median']:.1%}({x['new_wins']}) · {x['n']}시즌")
    return "\n".join(L) + "\n"


def cmd_analyze(a: argparse.Namespace) -> int:
    an = analyze()
    X.jdump(HERE / "cr_analysis.json", an)
    md = write_md(an)
    (HERE / "cr_results.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--jobs", type=int, default=4)
    r = sub.add_parser("run")
    r.add_argument("--season", required=True)
    r.add_argument("--jobs", type=int, default=2)
    r.add_argument("--workers", type=int, default=2)
    sub.add_parser("analyze")
    a = p.parse_args(argv)
    return {"check": cmd_check, "run": cmd_run, "analyze": cmd_analyze}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
