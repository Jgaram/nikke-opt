"""실험 39 — 후보 생성 고치기 (a) 묶음을 아는 후보 생성 · (b) 탐험 몫을 검증 시즌 S23~S32에서 지금 절차(base)와 비교. README.

    source .cache/evaluators.env && python -I experiments/39_bundle_explore/run39.py run --arm base --season 23 --part B_s0
      부분: B_s0 · B_s1(판마다, 서로 독립 — 프로세스 둘로 동시에) · rankers(판 무관, base 세션만)
    source .cache/evaluators.env && python -I experiments/39_bundle_explore/run39.py dev --arm a --season 40 --seed 0 --budget 3000
      개발용 짧은 실행(S33~S42만 — 실험 38 원인 찾기 시즌). dev/<판>/에 쓴다. 랭커 값은 실험 36 기록.
    python -I experiments/39_bundle_explore/run39.py analyze      # 시뮬 0 → analysis.json · results.md

- 판(arm)은 실험 10 `run_method` G+E의 `local_round`(라운드마다 다음에 계산할 구성 고르기)만 바꿔 끼운다.
  base = 실험 10 그대로(= 실험 36 A 사전 계산), a = `arm_a.local_round`, b = `arm_b.local_round`. 설계 · 구성 · 킥 · 순서 다듬기 ·
  예산(시드 s0 · s1 × 12,500) · 난수 시드(계정 id에서 나옴)는 판끼리 같다 — 같은 출발에서 라운드 고르기만 다르다.
- 계정 · options는 실험 31 `account` · `options`(시즌 풀 전원 보유 · 상, 보스 속성, 그때 없던 애장품 0단계, 레이어 1시뮬)와 같다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics as st
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXPS = HERE.parent
ROOT = EXPS.parent
sys.path.insert(0, str(ROOT))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


run31 = sys.modules.get("run31") or _load("run31", EXPS / "31_recent_seasons" / "run31.py")
R10, R9, R30 = run31.R10, run31.R9, run31.R30
E8 = 1e8

# ---------------------------------------------------------------- 정한 값(README §사전 등록)
VERIFY = json.loads((HERE / "seasons.json").read_text(encoding="utf-8"))["seasons"]
SEASONS = tuple(int(s) for s in VERIFY)          # 검증 S23~S32
DEV_SEASONS = tuple(run31.SEASONS)               # 개발 S33~S42(실험 38 정답지 — 여기서 고친 방법을 검증하지 않는다)
run31.SEASON_DATA = {**run31.SEASON_DATA, **VERIFY}   # run31.account · options가 두 묶음 모두 읽게
SEEDS = run31.SEEDS                              # (0, 1)
SEED_BUDGET = run31.SEED_BUDGET                  # 12,500
ARMS = ("base", "a", "b")
LOG = HERE / "run_log"
DEV = HERE / "dev"
EXP36_LOG = EXPS / "36_season_refresh" / "run_log"
GOOD, BAD, DROP, MAX_DROPS, BAD_DROPS = 0.005, -0.005, -0.01, 1, 3   # 판정(README §사전 등록)


def arm_round(arm: str) -> Callable:
    """판의 라운드 고르기. 인터페이스: local_round(sess, n, lineage, fitf) -> list[tuple] — 실험 10 `local_round`와 같다."""
    if arm == "base":
        return R10.local_round
    mod = sys.modules.get(f"arm_{arm}") or _load(f"arm_{arm}", HERE / f"arm_{arm}.py")
    return mod.local_round


def arm_params(arm: str) -> dict[str, Any]:
    if arm == "base":
        return {}
    mod = sys.modules.get(f"arm_{arm}") or _load(f"arm_{arm}", HERE / f"arm_{arm}.py")
    return dict(getattr(mod, "PARAMS", {}))


def jload(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def jdump(p: Path, x: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(x, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def sdir(arm: str, s: int) -> Path:
    return LOG / arm / f"S{int(s):02d}"


def rk_file(s: int) -> Path:
    return LOG / "rankers" / f"S{int(s):02d}.json"


# ---------------------------------------------------------------- 실행

def run_arm(arm: str, s: int, k: int, budget: int, ev: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    acct = run31.account(s, k)
    orig = R10.local_round
    R10.local_round = arm_round(arm)
    try:
        r, recs, _ = R10.run_method(acct, "G+E", budget, ev, pool=177)
    finally:
        R10.local_round = orig
    out = {"arm": arm, "params": arm_params(arm), "season": s, "seed": k, "budget": budget, "evals": r["evals"],
           "seconds": r["seconds"], "best": r["final"]["total"], "errors": r["errors"], "kicks": len(r["kicks"]),
           "history": r["history"]}
    return out, recs


def part_rankers(s: int, ev: Any) -> dict[str, Any]:
    """랭커 대표 5덱 · 1위 5덱 · 상위 40 스쿼드(가장 흔한 순서)를 코어 없음 레이어 1시뮬로(실험 36 rankers.json의 nocore와 같은 값)."""
    from nikke_opt.evaluator import EvalRequest
    decks = run31.ranker_decks(s)
    todo = sorted({tuple(q) for v in decks.values() for q in v if all(n[0] not in "?!" for n in q)})
    res = ev.evaluate([EvalRequest(list(q), boss=None, options=run31.options(s, 0)) for q in todo])
    out = {"season": s, "squads": {",".join(q): {"nocore": None if r.error else r.total_damage / E8} for q, r in zip(todo, res)}}
    jdump(rk_file(s), out)
    return {"squads": len(todo), "errors": sum(r.error is not None for r in res)}


def cmd_run(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        ver = f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"
        for s in [int(x) for x in str(a.season).split(",")]:
            if s not in SEASONS:
                raise SystemExit(f"S{s}는 검증 시즌이 아니다({SEASONS[0]}~{SEASONS[-1]}) — 개발은 dev 명령으로")
            for part in a.part.split(","):
                n0, t0 = ev.sim_count, time.time()
                if part == "rankers":
                    if rk_file(s).exists():
                        continue
                    out = part_rankers(s, ev)
                    pf = LOG / "rankers" / f"part_S{s:02d}.json"
                else:
                    k = int(part.removeprefix("B_s"))
                    pf = sdir(a.arm, s) / f"part_{part}.json"
                    if pf.exists():
                        continue
                    out, recs = run_arm(a.arm, s, k, SEED_BUDGET, ev)
                    run31.write_recs(sdir(a.arm, s) / f"{part}.jsonl.gz", recs)
                out.update(season=s, part=part, evaluator=ver, sims=ev.sim_count - n0, wall=round(time.time() - t0, 1))
                jdump(pf, out)
                print(json.dumps({k2: v for k2, v in out.items() if k2 != "history"}, ensure_ascii=False), flush=True)
    return 0


def cmd_dev(a: argparse.Namespace) -> int:
    """개발용: S33~S42에서 짧게 돌리고 실험 36 랭커 값으로 놓친 몫(G) · 랭커 덱 방문을 바로 본다."""
    from nikke_opt.evaluator import make_evaluator
    if a.season not in DEV_SEASONS:
        raise SystemExit(f"dev는 S{DEV_SEASONS[0]}~S{DEV_SEASONS[-1]}만 — 검증 시즌은 run으로")
    tag = f"S{a.season}_s{a.seed}_b{a.budget}" + (f"_{a.tag}" if a.tag else "")
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        n0 = ev.sim_count
        out, recs = run_arm(a.arm, a.season, a.seed, a.budget, ev)
        out["sims"] = ev.sim_count - n0
    run31.write_recs(DEV / a.arm / f"{tag}.jsonl.gz", recs)
    out.update(summarize(a.season, R30.book_of(recs)))
    jdump(DEV / a.arm / f"{tag}.json", out)
    print(json.dumps({k: v for k, v in out.items() if k != "history"}, ensure_ascii=False), flush=True)
    return 0


# ---------------------------------------------------------------- 요약(시뮬 0)

def ranker_vals(s: int) -> dict[frozenset, tuple[float, tuple]]:
    """랭커 덱 → (값, 순서). 검증 시즌은 이 실험 기록, 개발 시즌은 실험 36 기록."""
    f = rk_file(s) if s in SEASONS else EXP36_LOG / f"S{s:02d}" / "rankers.json"
    rv = (jload(f) or {}).get("squads", {})
    out: dict[frozenset, tuple[float, tuple]] = {}
    for key, e in rv.items():
        v = e.get("nocore")
        if v is None:
            continue
        q = tuple(key.split(","))
        c = frozenset(q)
        if c not in out or v > out[c][0]:
            out[c] = (v, q)
    return out


def summarize(s: int, bk: Mapping[frozenset, tuple[float, tuple]]) -> dict[str, Any]:
    """최선 5덱 합 · 놓친 몫 G(우리 기록 ∪ 랭커 덱으로 다시 묶은 값 ÷ 우리 최선 − 1) · 랭커 덱 방문(사용 수 기준)."""
    best = R9.pack_vals(bk)[0]
    rk = ranker_vals(s)
    add = {c: x for c, x in rk.items() if c not in bk or x[0] > bk[c][0]}
    merged = R9.pack_vals({**bk, **add})[0] if rk else None
    used = run31.season(s)["rankers"]["squads"]
    w = sum(q["count"] for q in used)
    seen = sum(q["count"] for q in used if frozenset(q["members"]) in bk)
    return {"pack": best, "G": None if merged is None else merged / best - 1, "visit": seen / w if w else None}


def med(xs: Sequence[float | None]) -> float | None:
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def verdict(rs: Sequence[float]) -> str:
    m, drops = st.median(rs), sum(r < DROP for r in rs)
    if m >= GOOD and drops <= MAX_DROPS:
        return "좋음"
    if m <= BAD or drops >= BAD_DROPS:
        return "나쁨"
    return "비김"


def analyze() -> dict[str, Any]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for arm in ARMS:
        for s in SEASONS:
            parts = {k: jload(sdir(arm, s) / f"part_B_s{k}.json") for k in SEEDS}
            if any(p is None for p in parts.values()):
                continue
            recs = {k: run31.load_recs(sdir(arm, s) / f"B_s{k}.jsonl.gz") for k in SEEDS}
            row = {"season": s, **summarize(s, R30.book_of([r for k in SEEDS for r in recs[k]]))}
            row["seed"] = {k: summarize(s, R30.book_of(recs[k])) for k in SEEDS}
            row["sims"] = sum(p["sims"] for p in parts.values())
            row["evals"] = sum(p["evals"] for p in parts.values())
            row["evaluator"] = sorted({p["evaluator"] for p in parts.values()})
            row["params"] = parts[SEEDS[0]].get("params", {})
            rows.setdefault(arm, []).append(row)
    base = {r["season"]: r for r in rows.get("base", [])}
    out: dict[str, Any] = {"seasons": list(SEASONS), "rows": rows, "compare": {}}
    if base:
        noise = [abs(r["seed"][1]["pack"] / r["seed"][0]["pack"] - 1) for r in base.values()]
        out["seed_noise_median"] = med(noise)
    for arm in ARMS[1:]:
        pair = [(r, base[r["season"]]) for r in rows.get(arm, []) if r["season"] in base]
        if not pair:
            continue
        rs = [r["pack"] / b["pack"] - 1 for r, b in pair]
        per_seed = [r["seed"][k]["pack"] / b["seed"][k]["pack"] - 1 for r, b in pair for k in SEEDS]
        out["compare"][arm] = {
            "seasons": [r["season"] for r, _ in pair], "ratio": rs, "median": med(rs), "drops": sum(x < DROP for x in rs),
            "per_seed_median": med(per_seed), "G_arm": med([r["G"] for r, _ in pair]), "G_base": med([b["G"] for _, b in pair]),
            "visit_arm": med([r["visit"] for r, _ in pair]), "visit_base": med([b["visit"] for _, b in pair]),
            "verdict": verdict(rs) if len(pair) == len(SEASONS) else f"진행 중 {len(pair)}/{len(SEASONS)}"}
    return out


def pct(x: float | None, d: int = 2, sign: bool = True) -> str:
    return "—" if x is None else f"{x * 100:+.{d}f}%" if sign else f"{x * 100:.{d}f}%"


def write_md(an: Mapping[str, Any]) -> str:
    rows = an["rows"]
    base = {r["season"]: r for r in rows.get("base", [])}
    lines = ["# 실험 39 결과 표", "", "`run39.py analyze`가 만든다. 값 = 코어 없음 최선 5덱 합(억, 두 시드 기록 합쳐 묶기, 사전 값).", ""]
    lines += ["| 시즌 | base | G base | 방문 base | a | a/base | G a | 방문 a | b | b/base | G b | 방문 b |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    by = {arm: {r["season"]: r for r in rows.get(arm, [])} for arm in ARMS}
    for s in SEASONS:
        b = base.get(s)
        cells = [f"S{s}", f"{b['pack']:.1f}" if b else "—", pct(b and b["G"]), pct(b and b["visit"], 1, False)]
        for arm in ARMS[1:]:
            r = by[arm].get(s)
            cells += [f"{r['pack']:.1f}" if r else "—", pct(r["pack"] / b["pack"] - 1) if (r and b) else "—",
                      pct(r and r["G"]), pct(r and r["visit"], 1, False)]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", f"시드 잡음(base s1 ÷ s0 − 1의 절댓값, 시즌 중앙): {pct(an.get('seed_noise_median'), sign=False)}", ""]
    for arm, c in an["compare"].items():
        lines.append(f"- **{arm}**: 시즌 중앙 {pct(c['median'])} · −1% 밑 {c['drops']}시즌 · 시드별 중앙 {pct(c['per_seed_median'])} · "
                     f"G 중앙 {pct(c['G_base'])} → {pct(c['G_arm'])} · 방문 중앙 {pct(c['visit_base'], 1, False)} → {pct(c['visit_arm'], 1, False)} · "
                     f"**판정 {c['verdict']}**")
    return "\n".join(lines) + "\n"


def cmd_analyze(a: argparse.Namespace) -> int:
    an = analyze()
    jdump(HERE / "analysis.json", an)
    md = write_md(an)
    (HERE / "results.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--arm", choices=ARMS, default="base")
    r.add_argument("--season", required=True)
    r.add_argument("--part", required=True, help="B_s0 · B_s1 · rankers (쉼표로 여럿)")
    r.add_argument("--jobs", type=int, default=None)
    d = sub.add_parser("dev")
    d.add_argument("--arm", choices=ARMS, required=True)
    d.add_argument("--season", type=int, required=True)
    d.add_argument("--seed", type=int, default=0)
    d.add_argument("--budget", type=int, default=3000)
    d.add_argument("--tag", default="")
    d.add_argument("--jobs", type=int, default=None)
    sub.add_parser("analyze")
    a = p.parse_args(argv)
    return {"run": cmd_run, "dev": cmd_dev, "analyze": cmd_analyze}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
