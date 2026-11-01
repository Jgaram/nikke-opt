"""실험 22 — 랭커 대조: 시즌 풀 · 시즌 속성 · 코어 유무 보스에서 랭커 없는 사전 계산 하나(README §절차).

    source .cache/evaluators.env && python experiments/22_ranker_check/run22.py precompute --season 4 --boss nocore
        → run_log/precompute_S04_nocore.json · .jsonl.gz   (--boss core30, --budget 15000 기본, --out 로 폴더 바꾸기)
    source .cache/evaluators.env && python experiments/22_ranker_check/run22.py rankers [--season 4,9]
        → run_log/rankers_S04.json (랭커 대표 5덱 · 1위 5덱 · 상위 스쿼드를 두 보스에서 평가)
    source .cache/evaluators.env && python experiments/22_ranker_check/run22.py members
        → run_log/members_S04_nocore.json (사전 계산 최선 5덱을 같은 보스로 다시 평가해 니케별 딜 — 주력 딜러용, 덱당 1시뮬)

- 사전 계산은 실험 12 PB15(실험 10 `run_method(G+E)` 15,000)와 같은 절차다. 계정은 그 시즌 풀 전원 보유 · 상(기본 스펙),
  그때 없던 애장품만 0단계. 운용(큐브 · 컨트롤)은 평가기 기본 레이어 고정 — 후처리는 하지 않는다.
- 두 보스의 계정 id(= 설계 · 구성 · 킥 난수)는 같다(`pre-S04`). 보스만 다르다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

HERE = Path(__file__).resolve().parent
EXPS = HERE.parent
LOG = HERE / "run_log"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


U13 = sys.modules.get("run13") or _load("run13", EXPS / "13_seed_merge" / "run13.py")
R12, R11, R10, R9 = U13.R12, U13.R11, U13.R10, U13.R9

PRE_BUDGET = 15000
BOSSES = {"nocore": 0, "core30": 30}
SEASON_DATA = json.loads((HERE / "seasons.json").read_text(encoding="utf-8"))["seasons"]


def season(s: int) -> dict[str, Any]:
    return SEASON_DATA[str(int(s))]


def options(s: int, boss: str) -> dict[str, Any]:
    """요청 options: 시즌 보스 속성 + 코어(30px 또는 없음) + 그때 없던 애장품 0단계."""
    v = season(s)
    enemy: dict[str, Any] = {"code": v["code"]}
    if BOSSES[boss]:
        enemy["core_px"] = BOSSES[boss]
    out: dict[str, Any] = {"enemy": enemy}
    if v["favorite0"]:
        out["profile"] = {"base": "default", "chars": {n: {"favorite_stage": 0} for n in v["favorite0"]}}
    return out


def account(s: int, boss: str) -> Any:
    """시즌 풀 전원 보유 · 상 사전 계산 계정(실험 10 Account10, 177명 풀에서 그때 없던 니케를 뺀다)."""
    v = season(s)
    sc = dict(R10.pre_scenario(), id=f"pre-S{int(s):02d}", name=f"S{s} 풀 {len(v['pool'])}명 · {boss}", missing=list(v["missing"]))
    acct = R10.Account10(sc, pool=177, rankerless=True)
    assert set(acct.names) == set(v["pool"]), (sorted(set(acct.names) ^ set(v["pool"])))[:10]
    acct.options = options(s, boss)
    return acct


def run_name(s: int, boss: str) -> str:
    return f"S{int(s):02d}_{boss}"


def run_pre(s: int, boss: str, budget: int, ev: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    acct = account(s, boss)
    sims0 = ev.sim_count
    summ, recs, sess = R10.run_method(acct, "G+E", budget, ev, pool=177)
    st = R11.stage_rec(f"S{s} 풀 {len(acct.names)}명 G+E {budget} · {boss}", summ, ev.sim_count - sims0)
    out = R11.pre_out(run_name(s, boss), [st], R11.extract(sess, acct, R11.fit_big), summ, kind="PB15",
                      season=int(s), boss=boss, options=acct.options)
    out["pool"] = len(acct.names)
    return out, recs


def cmd_precompute(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    a.out.mkdir(parents=True, exist_ok=True)
    seasons = [int(x) for x in str(a.season).split(",")]
    bosses = a.boss.split(",")
    for b in bosses:
        if b not in BOSSES:
            raise ValueError(f"보스는 {tuple(BOSSES)} 중 하나: {b}")
    with make_evaluator() as ev:
        for s in seasons:
            for b in bosses:
                nm = run_name(s, b)
                if (a.out / f"precompute_{nm}.json").exists():
                    print(f"{nm}: 이미 있음", flush=True)
                    continue
                data, recs = run_pre(s, b, a.budget, ev)
                R12.write_pre(a.out, nm, data, recs, ev)
    return 0


def ranker_decks(s: int) -> dict[str, list[list[str]]]:
    """평가할 랭커 덱: 대표 5덱(가장 많은 랭커가 그대로 쓴 5덱) · 1위 5덱 · 상위 스쿼드(가장 흔한 순서)."""
    r = season(s)["rankers"]
    return {"top_five": r["top_five"]["squads"], "rank1": r["rank1"]["squads"],
            "squads": [q["order"] for q in r["squads"]]}


def cmd_rankers(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    LOG.mkdir(parents=True, exist_ok=True)
    seasons = [int(x) for x in str(a.season).split(",")] if a.season else [int(k) for k in SEASON_DATA]
    with make_evaluator() as ev:
        for s in seasons:
            t0, sims0 = time.time(), ev.sim_count
            decks = ranker_decks(s)
            todo = sorted({tuple(q) for v in decks.values() for q in v if all(n[0] not in "?!" for n in q)})
            out: dict[str, Any] = {"season": s, "squads": {}, "skipped": sorted({" , ".join(q) for v in decks.values() for q in v
                                                                                if any(n[0] in "?!" for n in q)})}
            for b in BOSSES:
                res = ev.evaluate([EvalRequest(list(q), boss=None, options=options(s, b)) for q in todo])
                for q, r in zip(todo, res):
                    e = out["squads"].setdefault(",".join(q), {})
                    e[b] = None if r.total_damage is None else r.total_damage / R10.E8
                    e[f"{b}_members"] = [[m["name"], round(m["damage"] / R10.E8, 3)] for m in r.raw.get("members", [])]
            out["sims"], out["seconds"] = ev.sim_count - sims0, round(time.time() - t0, 1)
            out["evaluator"] = f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"
            (LOG / f"rankers_S{s:02d}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(json.dumps({"season": s, "squads": len(todo), "sims": out["sims"], "s": out["seconds"]}, ensure_ascii=False), flush=True)
    return 0


def cmd_members(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    with make_evaluator() as ev:
        for f in sorted(LOG.glob("precompute_S*_*.json")):
            pre = json.loads(f.read_text(encoding="utf-8"))
            out_f = LOG / f"members_{pre['name']}.json"
            if out_f.exists():
                continue
            sims0 = ev.sim_count
            sqs = [sq for _, sq in pre["final"]["squads"]]
            res = ev.evaluate([EvalRequest(list(sq), boss=None, options=pre["options"]) for sq in sqs])
            rows = [{"squad": list(sq), "total": r.total_damage / R10.E8,
                     "members": [[m["name"], round(m["damage"] / R10.E8, 3)] for m in r.raw.get("members", [])]}
                    for sq, r in zip(sqs, res)]
            for row, (v, _) in zip(rows, pre["final"]["squads"]):
                assert abs(row["total"] - v) < 1e-6, (pre["name"], row["squad"], row["total"], v)   # 사전 계산 값과 같아야 한다
            out_f.write_text(json.dumps({"name": pre["name"], "squads": rows, "sims": ev.sim_count - sims0}, ensure_ascii=False, indent=1)
                             + "\n", encoding="utf-8")
            print(pre["name"], "sims", ev.sim_count - sims0, flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("precompute")
    s.add_argument("--season", required=True, help="시즌 번호(쉼표로 여럿)")
    s.add_argument("--boss", required=True, help="nocore · core30 (쉼표로 둘 다)")
    s.add_argument("--budget", type=int, default=PRE_BUDGET)
    s.add_argument("--out", type=Path, default=LOG)
    r = sub.add_parser("rankers")
    r.add_argument("--season", default=None)
    sub.add_parser("members")
    a = p.parse_args(argv)
    return {"precompute": cmd_precompute, "rankers": cmd_rankers, "members": cmd_members}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
