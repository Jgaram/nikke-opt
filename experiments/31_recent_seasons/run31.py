"""실험 31 — 최근 10시즌(S33~S42) 편성안 지도: 시즌 풀 · 보스 속성 · 그때 없던 애장품으로 사전 계산 → 큰 분류 · 세부 분류.

    python experiments/31_recent_seasons/run31.py run --season 33 --part B_s0      # B_s1 · W · core30 · members
    python experiments/31_recent_seasons/run31.py rankers --season 33,34           # 랭커 덱 평가(두 보스)
    python experiments/31_recent_seasons/run31.py analyze                          # 시뮬 0 → analysis.json · results.md

- 절차는 실험 30을 그대로 쓴다(2026-11-01 사용자 결정 「실험 30 판정대로」). 바꾸는 것은 계정과 요청 options뿐이다.
  - 계정: 그 시즌 풀 전원 보유 · 상(실험 22 `account`와 같은 Account10, 시드 1이면 id 끝에 `-s1`).
  - options: 시즌 보스 속성(`enemy.code`) + 그때 없던 애장품 0단계(`profile`) — 코어 30이면 `enemy.core_px` = 30.
  - B = 시드 둘 × 12,500평가(실제로는 끝 순서 다듬기에서 약 11,000에 끝남) 합치기.
    W(실험 30이 「넓게 찾기가 지도를 넓힌다」로 판정했을 때만) = B 기록 앞 6,250 × 2 + 넓게 찾기(B가 실제로 쓴 평가 수 − 앞부분, 실험 30 `w_budget_of`).
  - 지도 = 실험 30 `class_map`(대표끼리 J ≤ 0.2, 최선의 95% 아래면 멈춤, 최대 10개). 판정이 W면 W 판 기록, 아니면 B 판 기록.
  - 코어 30 = 실험 30 `corecheck`의 RC: 코어 없음 지도에서 고른 후보 2,000개(`core_candidates`) 재평가 → 그 위에서 코어 30 이어 찾기 2,000평가
    (`continue_search`). 코어 30 지도는 이 두 기록 값으로 만든다.
- 큰 분류 = 지도 대표(A = 최선, B · C … = 앞 대표 모두와 J ≤ 0.2인 5덱 중 합 최대). 세부 분류 = 실험 28 `subs`
  (대표에서 덱 1~2개만 바뀌고 대표와 J ≥ 0.5, 합 ≥ 최선의 97%). 표에 3개 · 더보기 20개(실험 28과 같다).
- 운용(큐브 · 컨트롤)은 평가기 기본 레이어 고정이다. 후처리는 하지 않는다(2026-11-01 사용자 결정).
- 랭커 대조(관찰): 실험 22 지표(N25 · D4 · V_top · V_r1 · V_pack)를 A 기준으로, 랭커 대표 5덱 · 1위 5덱과 큰 분류마다의 J를 더한다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

os.environ.setdefault("OMP_NUM_THREADS", "1")

HERE = Path(__file__).resolve().parent
EXPS = HERE.parent
ROOT = EXPS.parent
LOG = HERE / "run_log"
sys.path.insert(0, str(ROOT))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R30 = sys.modules.get("run30") or _load("run30", EXPS / "30_element_map" / "run30.py")
T28, R10, R9, SIM = R30.T28, R30.R10, R30.R9, R30.SIM
E8 = 1e8

# ---------------------------------------------------------------- 정한 값(README)
SEASON_DATA = json.loads((HERE / "seasons.json").read_text(encoding="utf-8"))["seasons"]
SEASONS = tuple(int(s) for s in SEASON_DATA)
SEEDS = R30.SEEDS                    # (0, 1)
SEED_BUDGET = R30.SEED_BUDGET        # 12,500
PREFIX = R30.PREFIX                  # 6,250
CORE_PX = R30.CORE_PX                # 30
BOSSES = {"nocore": 0, "core30": CORE_PX}
GOOD, LOW = R30.GOOD, R30.LOW        # 0.97 · 0.95
SHOW, MORE, SUB_CAP = T28.SHOW, T28.MORE, 400
CLASS_NAMES = "ABCDEFGHIJ"
# 실험 30 판정에 따라 정한다(README §판). None이면 W · core30 · analyze의 지도를 만들지 않는다.
# True = 「넓게 찾기가 지도를 넓힌다」 → W 판(B 앞 6,250 × 2 + W 12,500), False = 그 밖 → B 판(B 전체).
USE_W: bool | None = None
# 코어 30 이어 찾기 평가 수(실험 30 CORE_EXTRA). 실험 30 corecheck: 재평가만(R)은 따로 찾은 코어 30 최선의 S40 99.9% · S34 97.9%,
# 이어 찾기까지(RC)는 99.98% · 100.0% — 관찰 기준 「두 시즌 모두 99% 이상」을 채운 것은 RC다(README §절차).
CORE_CONT = R30.CORE_EXTRA          # 2,000
PARTS = ("B_s0", "B_s1", "W", "core30", "members")


def season(s: int) -> dict[str, Any]:
    return SEASON_DATA[str(int(s))]


def options(s: int, core: int = 0) -> dict[str, Any]:
    """시즌 보스 속성 + (코어) + 그때 없던 애장품 0단계 — 실험 22 `options`와 같은 모양."""
    v = season(s)
    enemy: dict[str, Any] = {"code": v["code"]}
    if core:
        enemy["core_px"] = core
    out: dict[str, Any] = {"enemy": enemy}
    if v["favorite0"]:
        out["profile"] = {"base": "default", "chars": {n: {"favorite_stage": 0} for n in v["favorite0"]}}
    return out


def account_id(s: int, seed: int) -> str:
    return f"pre-S{int(s):02d}" + (f"-s{seed}" if seed else "")


def account(s: int, seed: int = 0, core: int = 0) -> Any:
    """시즌 풀 전원 보유 · 상(Account10, 177명 풀에서 그때 없던 니케를 뺀다). options = 시즌 보스 속성(+ 코어) + 애장품 끔."""
    v = season(s)
    sc = dict(R10.pre_scenario(), id=account_id(s, seed), name=f"S{s} 풀 {len(v['pool'])}명", missing=list(v["missing"]))
    acct = R10.Account10(sc, pool=177, rankerless=True)
    assert set(acct.names) == set(v["pool"]), sorted(set(acct.names) ^ set(v["pool"]))[:10]
    acct.options = options(s, core)
    return acct


def sdir(s: int) -> Path:
    return LOG / f"S{int(s):02d}"


def part_file(s: int, part: str) -> Path:
    return sdir(s) / f"part_{part}.json"


def read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def write_json(p: Path, x: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(x, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load_recs(p: Path) -> list[dict[str, Any]]:
    return R30.load_recs(p) if p.exists() else []


def arm_of(use_w: bool | None = None) -> str:
    use_w = USE_W if use_w is None else use_w
    if use_w is None:
        raise RuntimeError("USE_W가 정해지지 않았다 — 실험 30 판정 뒤 README §판에 적고 run31.USE_W를 정한다")
    return "W" if use_w else "B"


def arm_recs(s: int, arm: str) -> list[dict[str, Any]]:
    """판 기록: B = 두 시드 전체, W = 두 시드 앞 PREFIX + W(실험 30 `arm_recs`와 같은 자르기)."""
    d = sdir(s)
    if arm == "B":
        return [r for k in SEEDS for r in load_recs(d / f"B_s{k}.jsonl.gz")]
    return [r for k in SEEDS for r in load_recs(d / f"B_s{k}.jsonl.gz")[:PREFIX]] + load_recs(d / "W.jsonl.gz")


def book(s: int, boss: str, arm: str) -> dict[frozenset, tuple[float, tuple]]:
    if boss == "nocore":
        return R30.book_of(arm_recs(s, arm))
    return R30.book_of(load_recs(sdir(s) / "core30.jsonl.gz"))


def class_map(s: int, boss: str, arm: str) -> dict[str, Any]:
    """지도(실험 30 `class_map`). 기록이 같으면 다시 계산하지 않도록 maps.json에 둔다."""
    f = sdir(s) / "maps.json"
    cache = read_json(f) or {}
    bk = book(s, boss, arm)
    key = f"{boss}|{arm}"
    if key in cache and cache[key].get("comps") == len(bk):
        return cache[key]
    m = R30.class_map(bk)
    cache[key] = m
    write_json(f, cache)
    return m


# ---------------------------------------------------------------- 실행(평가기 필요)

def write_recs(p: Path, recs: Sequence[Mapping[str, Any]]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    R30.write_recs(p, recs)


def core_rc(s: int, ev: Any, nb: Mapping[frozenset, tuple[float, tuple]], m: Mapping[str, Any]
            ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """실험 30 `corecheck`의 RC를 시즌 계정으로: 코어 없음 지도의 후보(`core_candidates`, 2,000개)를 코어 30으로 재평가 →
    그 위에서 코어 30 이어 찾기 CORE_CONT평가(`continue_search`: 국소 탐색 · 킥 없음, 끝 1/8 순서 다듬기)."""
    acct = account(s, 0, CORE_PX)
    cands = R30.core_candidates(nb, [m])
    t0, sims0 = time.time(), ev.sim_count
    sess = R9.Session(acct, ev, len(cands))
    sess.run(cands, "코어 30 재평가")
    r_recs = list(sess.records)
    r_sims = ev.sim_count - sims0
    cs, c_recs = R30.continue_search(acct, ev, r_recs, CORE_CONT)
    out = {"requests": len(cands), "reeval_sims": r_sims, "reeval_best": R9.pack_vals(R30.book_of(r_recs))[0],
           "extra_evals": cs["evals"], "evals": len(cands) + cs["evals"], "seconds": round(time.time() - t0, 1)}
    return out, r_recs + list(c_recs)


def rep_decks(m: Mapping[str, Any]) -> list[tuple]:
    """지도 대표(95% 아래 제외)의 덱 — 덱별 니케 딜(members)을 다시 평가할 것."""
    return list(dict.fromkeys(tuple(q) for r in m["reps"] if not r.get("below") for q in r["decks"]))


def run_members(s: int, ev: Any, arm: str) -> dict[str, Any]:
    """큰 분류 대표 덱을 두 보스로 다시 평가해 니케별 딜을 남긴다(덱당 1시뮬, 화면용)."""
    from nikke_opt.evaluator import EvalRequest
    out: dict[str, Any] = {}
    for b, core in BOSSES.items():
        todo = rep_decks(class_map(s, b, arm))
        res = ev.evaluate([EvalRequest(list(q), boss=None, options=options(s, core)) for q in todo])
        out[b] = {",".join(q): {"total": None if r.total_damage is None else r.total_damage / E8,
                                "members": [[x["name"], round(x["damage"] / E8, 3)] for x in r.raw.get("members", [])]}
                  for q, r in zip(todo, res)}
    return out


def cmd_run(a: argparse.Namespace) -> int:
    """--part 순서: B_s0 · B_s1(서로 독립 — 프로세스 둘로 동시에) → W(USE_W일 때만, B 둘 다 필요) → core30 → members."""
    from nikke_opt.evaluator import make_evaluator
    seasons = [int(x) for x in str(a.season).split(",")]
    parts = PARTS if a.part == "all" else tuple(a.part.split(","))
    for p in parts:
        if p not in PARTS:
            raise ValueError(f"--part는 {PARTS} · all 중: {p}")
    with make_evaluator() as ev:
        evaluator = f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"
        for s in seasons:
            d = sdir(s)
            d.mkdir(parents=True, exist_ok=True)
            for part in parts:
                if part_file(s, part).exists():
                    continue
                if part == "W" and arm_of() != "W":
                    continue
                need = {"W": ["B_s0", "B_s1"], "core30": ["B_s0", "B_s1"] + (["W"] if USE_W else []),
                        "members": ["core30"]}.get(part, [])
                missing = [x for x in need if not part_file(s, x).exists()]
                if missing:
                    raise RuntimeError(f"S{s} {part}: 먼저 {missing}가 필요하다")
                sims0 = ev.sim_count
                if part.startswith("B_s"):
                    k = int(part[3:])
                    r, recs, _ = R10.run_method(account(s, k), "G+E", SEED_BUDGET, ev, pool=177)
                    write_recs(d / f"{part}.jsonl.gz", recs)
                    out = {"evals": r["evals"], "seconds": r["seconds"], "best": r["final"]["total"],
                           "errors": r["errors"], "kicks": len(r["kicks"]), "history": r["history"]}
                elif part == "W":
                    prefix = [r for k in SEEDS for r in load_recs(d / f"B_s{k}.jsonl.gz")[:PREFIX]]
                    assert len(prefix) == 2 * PREFIX, (s, len(prefix))
                    # B와 W의 총평가를 같게(실험 30 `w_budget_of`): B 두 시드가 실제로 쓴 평가 수 − 앞부분
                    R30.W_BUDGET = sum(read_json(part_file(s, f"B_s{k}"))["evals"] for k in SEEDS) - len(prefix)
                    out, recs = R30.run_wide(account(s, 0), ev, prefix)
                    write_recs(d / "W.jsonl.gz", recs)
                    out.update(prefix_evals=len(prefix), w_budget=R30.W_BUDGET)
                elif part == "core30":
                    arm = arm_of()
                    out, recs = core_rc(s, ev, book(s, "nocore", arm), class_map(s, "nocore", arm))
                    write_recs(d / "core30.jsonl.gz", recs)
                    out["arm"] = arm
                else:
                    arm = arm_of()
                    write_json(d / "members.json", run_members(s, ev, arm))
                    out = {"arm": arm}
                out.update(season=s, part=part, sims=ev.sim_count - sims0, evaluator=evaluator)
                write_json(part_file(s, part), out)
                print(json.dumps({k: v for k, v in out.items() if k not in ("history", "blocks", "reps")}, ensure_ascii=False),
                      flush=True)
    return 0


def ranker_decks(s: int) -> dict[str, list[list[str]]]:
    r = season(s)["rankers"]
    return {"top_five": r["top_five"]["squads"], "rank1": r["rank1"]["squads"], "squads": [q["order"] for q in r["squads"]]}


def cmd_rankers(a: argparse.Namespace) -> int:
    """랭커 대표 5덱 · 1위 5덱 · 상위 40 스쿼드(가장 흔한 순서)를 두 보스로 평가한다(실험 22 `rankers`와 같은 모양)."""
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    seasons = [int(x) for x in str(a.season).split(",")] if a.season else list(SEASONS)
    with make_evaluator() as ev:
        for s in seasons:
            f = sdir(s) / "rankers.json"
            if f.exists():
                continue
            t0, sims0 = time.time(), ev.sim_count
            decks = ranker_decks(s)
            todo = sorted({tuple(q) for v in decks.values() for q in v if all(n[0] not in "?!" for n in q)})
            out: dict[str, Any] = {"season": s, "squads": {}}
            for b, core in BOSSES.items():
                res = ev.evaluate([EvalRequest(list(q), boss=None, options=options(s, core)) for q in todo])
                for q, r in zip(todo, res):
                    e = out["squads"].setdefault(",".join(q), {})
                    e[b] = None if r.total_damage is None else r.total_damage / E8
                    e[f"{b}_members"] = [[x["name"], round(x["damage"] / E8, 3)] for x in r.raw.get("members", [])]
            out["sims"], out["seconds"] = ev.sim_count - sims0, round(time.time() - t0, 1)
            out["evaluator"] = f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"
            write_json(f, out)
            print(json.dumps({"season": s, "squads": len(todo), "sims": out["sims"], "s": out["seconds"]}, ensure_ascii=False),
                  flush=True)
    return 0


# ---------------------------------------------------------------- 분석(시뮬 0)

def plan_vals(bk: Mapping[frozenset, tuple[float, tuple]], decks: Sequence[Sequence[str]]) -> list[tuple[float, tuple]]:
    return [(bk[frozenset(q)][0], tuple(q)) for q in decks]


def classes_of(m: Mapping[str, Any], bk: Mapping[frozenset, tuple[float, tuple]], sub_cap: int = SUB_CAP) -> list[dict[str, Any]]:
    """지도 대표(95% 아래 제외) → 큰 분류 A · B · C …, 대표마다 세부 분류(실험 28 `subs` · `order_subs`)."""
    best = m["best"]
    floor = GOOD * best
    reps = [r for r in m["reps"] if not r.get("below")]
    plans = [[list(q) for q in r["decks"]] for r in reps]
    out = []
    for i, r in enumerate(reps):
        rep = plan_vals(bk, r["decks"])
        t0 = time.time()
        ss = T28.order_subs(T28.subs(rep, bk, set(bk), floor, cap=sub_cap))
        name = CLASS_NAMES[i]
        for x in ss[:MORE]:
            plan = [list(rep[j][1]) for j in range(len(rep)) if j + 1 not in x["changed"]] + x["new_decks"]
            x["J_other"] = {CLASS_NAMES[o]: SIM.pair_jaccard(plans[o], plan) for o in range(len(plans)) if o != i}
            x.pop("new_unposted", None)   # 후처리를 하지 않으므로 모든 값이 기본 레이어다
        out.append({"name": name, "total": r["total"], "ratio": r["total"] / best, "exact": r["exact"],
                    "decks": [[v, list(q)] for v, q in rep], "subs_count": len(ss), "capped": len(ss) >= sub_cap,
                    "subs_1deck": sum(len(x["changed"]) == 1 for x in ss), "subs": ss[:MORE],
                    "vs": {CLASS_NAMES[o]: {"J": SIM.pair_jaccard(plans[i], plans[o]), "moves": SIM.moves(plans[i], plans[o])}
                           for o in range(len(plans)) if o != i},
                    "subs_seconds": round(time.time() - t0, 1)})
    return out


def five_value(squads: Sequence[Sequence[str]], rv: Mapping[str, Mapping], b: str) -> float | None:
    vals = [(rv.get(",".join(q)) or {}).get(b) for q in squads]
    return None if any(v is None for v in vals) or len(vals) != 5 else sum(vals)


def ranker_metrics(s: int, b: str, classes: Sequence[Mapping[str, Any]], rv: Mapping[str, Mapping] | None) -> dict[str, Any]:
    """실험 22 지표를 큰 분류 A 기준으로 + 랭커 대표 5덱 · 1위 5덱과 큰 분류마다의 J(관찰)."""
    rk = season(s)["rankers"]
    top25 = [n for n, _ in rk["units"][:25]]
    rsq = [set(q["members"]) for q in rk["squads"]]
    A = classes[0]
    ours = [q for _, q in A["decks"]]
    our25 = {n for q in ours for n in q}
    match = [max(len(set(q) & x) for x in rsq) for q in ours]
    out: dict[str, Any] = {"N25": len(our25 & set(top25)), "D4": sum(x >= 4 for x in match), "match": match,
                           "ours_only": sorted(our25 - set(top25)), "rankers_only": [n for n in top25 if n not in our25]}
    for k, sq in (("top", rk["top_five"]["squads"]), ("r1", rk["rank1"]["squads"])):
        out[f"J_{k}"] = {c["name"]: SIM.pair_jaccard([list(q) for q in sq], [list(q) for _, q in c["decks"]]) for c in classes}
    if rv:
        vt, vr1 = five_value(rk["top_five"]["squads"], rv, b), five_value(rk["rank1"]["squads"], rv, b)
        pack_in = {frozenset(k.split(",")): (e[b], tuple(k.split(","))) for k, e in rv.items() if e.get(b) is not None}
        pv = R9.pack_vals(pack_in)[0] if len(pack_in) >= 5 else None
        out.update(V_top=None if vt is None else vt / A["total"], V_r1=None if vr1 is None else vr1 / A["total"],
                   V_pack=None if not pv else pv / A["total"], top_total=vt, r1_total=vr1, pack_total=pv)
    return out


def analyze_season(s: int, arm: str) -> dict[str, Any]:
    parts = {p: read_json(part_file(s, p)) for p in PARTS}
    need = ["B_s0", "B_s1"] + (["W"] if arm == "W" else [])
    out: dict[str, Any] = {"season": s, "arm": arm, "parts": {p: {k: v for k, v in x.items() if k not in ("history", "blocks", "reps")}
                                                              for p, x in parts.items() if x},
                           "sims_total": sum(x["sims"] for x in parts.values() if x), "by_boss": {}}
    if not all(parts[p] for p in need):
        out["status"] = "pending"
        return out
    rv = (read_json(sdir(s) / "rankers.json") or {}).get("squads")
    for b in BOSSES:
        if b == "core30" and not parts["core30"]:
            continue
        bk = book(s, b, arm)
        m = class_map(s, b, arm)
        cl = classes_of(m, bk)
        out["by_boss"][b] = {"best": m["best"], "comps": m["comps"], "map_exact": m["exact"], "map_seconds": m["seconds"],
                             "n97": R30.count_at(m, m["best"]), "classes": cl, "rankers": ranker_metrics(s, b, cl, rv)}
    out["status"] = "done" if len(out["by_boss"]) == len(BOSSES) else "partial"
    return out


def med(xs: Sequence[float | None]) -> float | None:
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f}%"


def write_md(rows: Sequence[Mapping[str, Any]]) -> str:
    out = ["# 실험 31 결과 표 — 최근 10시즌 편성안 지도", "",
           "`run31.py analyze`가 만든다. 값 = 기본 레이어 180초 딜(억). 큰 분류 = 대표끼리 J ≤ 0.2, 세부 분류 = 대표에서 덱 1~2개만 바뀌고 J ≥ 0.5 · 최선의 97% 이상.", ""]
    for b, label in (("nocore", "코어 없음"), ("core30", "코어 30(코어 없음 후보 2,000 재평가)")):
        out += [f"## {label}", "", "| 시즌 | 보스 | 판 | 최선 | 큰 분류(≥95%) | ≥97% | 큰 분류 비율 | 세부 분류 수 | N25 | D4 | V_top | 랭커 대표 5덱과 가장 가까운 분류(J) |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            v = season(r["season"])
            x = r["by_boss"].get(b)
            if not x:
                out.append(f"| S{r['season']} | {v['boss']} · {v['code']} | {r['arm']} | 계산 전 | | | | | | | | |")
                continue
            cl, rk = x["classes"], x["rankers"]
            near = max(rk["J_top"].items(), key=lambda kv: kv[1])
            out.append(f"| S{r['season']} | {v['boss']} · {v['code']} | {r['arm']} | {x['best']:.1f} | {len(cl)} | {x['n97']} | "
                       + " · ".join(f"{c['name']} {pct(c['ratio'])}" for c in cl) + " | "
                       + " · ".join(f"{c['subs_count']}{'+' if c['capped'] else ''}" for c in cl)
                       + f" | {rk['N25']} | {rk['D4']} | {pct(rk.get('V_top'))} | {near[0]} {near[1]:.2f} |")
        out.append("")
    return "\n".join(out) + "\n"


def cmd_analyze(a: argparse.Namespace) -> int:
    arm = arm_of()
    seasons = [int(x) for x in str(a.season).split(",")] if a.season else list(SEASONS)
    rows = [analyze_season(s, arm) for s in seasons]
    for r in rows:
        print(json.dumps({"season": r["season"], "status": r["status"], "sims": r["sims_total"],
                          **{b: [round(c["ratio"], 4) for c in x["classes"]] for b, x in r["by_boss"].items()}}, ensure_ascii=False),
              flush=True)
    done = [r for r in rows if r["status"] == "done"]
    summary = {b: {"n97_median": med([r["by_boss"][b]["n97"] for r in done]),
                   "N25_median": med([r["by_boss"][b]["rankers"]["N25"] for r in done]),
                   "V_top_median": med([r["by_boss"][b]["rankers"].get("V_top") for r in done])} for b in BOSSES}
    write_json(HERE / "analysis.json", {"arm": arm, "summary": summary, "rows": rows})
    (HERE / "results.md").write_text(write_md(rows), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--season", required=True, help="시즌 번호(쉼표로 여럿)")
    r.add_argument("--part", required=True, help=f"{PARTS} 중 쉼표로 여럿 · all")
    k = sub.add_parser("rankers")
    k.add_argument("--season", default=None)
    n = sub.add_parser("analyze")
    n.add_argument("--season", default=None)
    a = p.parse_args(argv)
    return {"run": cmd_run, "rankers": cmd_rankers, "analyze": cmd_analyze}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
