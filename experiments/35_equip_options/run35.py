"""실험 35 R0 — 장비 옵션 12줄(종류당 최대 4줄, 모두 Lv11)을 덱마다 시뮬로 찾으면 얼마나 바뀌나(README §R0 사전 등록).

    source .cache/evaluators.env && python -I experiments/35_equip_options/run35.py d1           # 최선 5덱(A · B′) × 4시즌, 후처리 컨트롤 위
    source .cache/evaluators.env && python -I experiments/35_equip_options/run35.py d2           # A 지도 대표 덱(기본 컨트롤 위)
    source .cache/evaluators.env && python -I experiments/35_equip_options/run35.py transplant   # 조합 의존: 시즌 최빈 배분으로 바꿔 끼우기
    source .cache/evaluators.env && python -I experiments/35_equip_options/run35.py shake        # 탐색 흔들림
    python -I experiments/35_equip_options/run35.py analyze                                      # → r0.json · r0.md

옵션 탐색(O, 덱 하나 400시뮬):
  E0 = 다섯 명 모두 우월 코드 4 · 공격력 4 · 최대 장탄 4(계산기 기본 스펙 4 · 2 · 2를 12줄로 늘린 것, Lv11) — 니케별 규칙 없음.
  ① 거르기(45시뮬): 니케마다 9종 각각 「4줄 덩어리 값」 = E0에서 그 종류를 4줄 ↔ 0줄로 바꾼 차이.
  ② 메뉴: 니케마다 덩어리 값 상위 4종 위의 모든 배분(0~4줄, 합 12) = 35개. 니케 = 메뉴 키 하나(컨트롤 메뉴와 같은 틀).
  ③ 실험 7 M3(좌표 하강 + 흔들기 2) — 남은 예산.
컨트롤은 그 덱의 후처리 결과(D1) 또는 기본(D2)으로 고정한다. D1은 옵션을 찾은 뒤 컨트롤을 한 번 더 찾는다(상호작용, 400).
"""

from __future__ import annotations

import argparse
import collections
import gzip
import itertools
import json
import random
import statistics as st
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXP32 = HERE.parent / "32_primitive_control"
sys.path[:0] = [str(EXP32)]
import r3  # noqa: E402
import r3b  # noqa: E402
from r3 import r1, r0, run31, M, R9, R30, E8, jdump, jload, menu6  # noqa: E402

OUT = HERE / "r0"
SEASONS = r3.SEASONS
KEYS9 = ("element_bonus", "atk_pct", "max_ammo_pct", "crit_rate", "crit_dmg",
         "charge_speed_pct", "charge_dmg_pct", "accuracy_pct", "def_pct")
SHORT = {"element_bonus": "우코", "atk_pct": "공", "max_ammo_pct": "장탄", "crit_rate": "크확", "crit_dmg": "크뎀",
         "charge_speed_pct": "차속", "charge_dmg_pct": "차뎀", "accuracy_pct": "명중", "def_pct": "방어"}
LV, CAP, TOTAL = 11, 4, 12
E0 = {"element_bonus": 4, "atk_pct": 4, "max_ammo_pct": 4}
TOP_T = 4
O_BUDGET = 400          # 거르기 포함
C_BUDGET = 400          # D1 컨트롤 다시 찾기
SPEC = "O:M3:k2"
LAYER_EQUIP = {"앨리스": "차속", "리버렐리오": "차속", "홍련 : 흑영": "차속", "네온 : 비전 아이": "차속",
               "미하라 : 본딩 체인": "공(+1%p)", "프리바티": "장탄 0", "아니스 : 스파클링 서머": "장탄 0", "헬름": "장탄 0"}


# ---------------------------------------------------------------- 배분 표기

def overload(alloc: Mapping[str, int]) -> dict[str, Any]:
    """계산기 프로필 `overload` — 9종 모두 적는다(적지 않은 종류는 아래 층 값이 남으므로)."""
    return {k: ([LV] * alloc[k] if alloc.get(k) else 0) for k in KEYS9}


def label(alloc: Mapping[str, int]) -> str:
    return "+".join(f"{SHORT[k]}{alloc[k]}" for k in KEYS9 if alloc.get(k))


def parse(lb: str) -> dict[str, int]:
    inv = {v: k for k, v in SHORT.items()}
    out = {}
    for part in lb.split("+"):
        name = part.rstrip("0123456789")
        out[inv[name]] = int(part[len(name):])
    return out


def with_alloc(options: Mapping[str, Any], per: Mapping[str, Mapping[str, int]]) -> dict[str, Any]:
    patch = {"profile": {"base": "default", "chars": {n: {"overload": overload(a)} for n, a in per.items()}}}
    return menu6.deep_merge(options, patch)


def allocs(types: Sequence[str]) -> list[dict[str, int]]:
    out = []
    for c in itertools.product(range(CAP + 1), repeat=len(types)):
        if sum(c) == TOTAL:
            out.append({t: n for t, n in zip(types, c) if n})
    return out


def e0_all(squad: Sequence[str]) -> dict[str, dict[str, int]]:
    return {n: dict(E0) for n in squad}


# ---------------------------------------------------------------- 옵션 탐색

def screen(squad: Sequence[str], base: Mapping[str, Any], ev: Any) -> tuple[float | None, dict[str, dict[str, float | None]]]:
    """base = 컨트롤을 얹은 options(E0 포함). 니케 × 9종의 4줄 덩어리 값(억)."""
    from nikke_opt.evaluator import EvalRequest
    reqs, idx = [base], [None]
    for n in squad:
        for k in KEYS9:
            a = dict(E0)
            if a.get(k):
                a.pop(k)
            else:
                a[k] = CAP
            reqs.append(with_alloc(base, {n: a}))
            idx.append((n, k))
    res = ev.evaluate([EvalRequest(list(squad), boss=None, options=o) for o in reqs])
    v0 = None if res[0].error else res[0].total_damage / E8
    b: dict[str, dict[str, float | None]] = {n: {} for n in squad}
    for (n, k), r in zip(idx[1:], res[1:]):
        v = None if (r.error or v0 is None) else r.total_damage / E8
        b[n][k] = None if v is None else (v0 - v if E0.get(k) else v - v0)
    return v0, b


def top_types(bn: Mapping[str, float | None]) -> list[str]:
    return sorted(KEYS9, key=lambda k: (-(bn[k] if bn[k] is not None else -1e9), KEYS9.index(k)))[:TOP_T]


def equip_space(squad: Sequence[str], base: Mapping[str, Any], top: Mapping[str, Sequence[str]]) -> Any:
    def variants(q):
        out = {}
        for n in q:
            out[(n, "equip")] = [{"nikke": n, "axis": "equip", "label": f"{n}:equip:{label(a)}", "alloc": a,
                                  "patch": {"profile": {"chars": {n: {"overload": overload(a)}}}}}
                                 for a in allocs(top[n]) if a != E0]
        return out

    def apply(options, chosen):
        out = dict(options)
        for v in chosen:
            out = menu6.deep_merge(out, v["patch"])
        return out
    return M.Space(list(squad), variants_fn=variants, apply_fn=apply, base=base)


def best_alloc(sp: Any, sel: Sequence[int]) -> dict[str, dict[str, int]]:
    out = e0_all(sp.squad)
    for v in sp.chosen(sel):
        out[v["nikke"]] = dict(v["alloc"])
    return out


def gz_log(log: Path) -> int:
    raw = log.read_bytes()
    with gzip.open(log.with_suffix(".jsonl.gz"), "wb") as g:
        g.write(raw)
    log.unlink()
    return sum(1 for ln in raw.decode().splitlines() if json.loads(ln)["error"])


def m3_from(run: Any, start: tuple[int, ...], kick: int = 2, seed: int = 0) -> None:
    """실험 7 `m3`와 같고 시작점만 받는다(이전 후처리 선택에서 다시 찾기)."""
    sp = run.space
    rng = random.Random(seed)
    M.descend(run, start)
    stale = 0
    while not run.exhausted and stale < 200:
        before = run.used
        s = list(run.best_sel)
        for k in rng.sample(range(sp.K), min(kick, sp.K)):
            s[k] = rng.choice([o for o in sp.opts[k] + [-1] if o != s[k]])
        M.descend(run, tuple(s))
        stale = stale + 1 if run.used == before else 0


def osearch(job_id: str, squad: Sequence[str], base: Mapping[str, Any], ev: Any, out_dir: Path, tag: str = "") -> dict[str, Any]:
    """base = 컨트롤을 얹고 장비 옵션은 E0인 options. 거르기 → 메뉴 → M3."""
    n0, t0 = ev.sim_count, time.time()
    v0, b = screen(squad, base, ev)
    top = {n: top_types(b[n]) for n in squad}
    sp = equip_space(squad, base, top)
    log = out_dir / f"{job_id}{tag}.o.jsonl"
    run = M.Run({"id": job_id, "squad": list(squad)}, sp, ev, method=SPEC, budget=O_BUDGET - (1 + 9 * len(squad)), out=log)
    try:
        M.m3(run, kick=2, seed=M.job_seed(job_id + tag, SPEC))
    finally:
        run.close()
    errs = gz_log(log)
    al = best_alloc(sp, run.best_sel)
    return {"v_E0": v0, "v_O": None if run.best is None else run.best / E8, "base_check": None if run.base_damage is None else run.base_damage / E8,
            "screen": b, "top": top, "alloc": {n: label(a) for n, a in al.items()}, "o_evals": run.used, "o_errors": errs,
            "sims": ev.sim_count - n0, "seconds": round(time.time() - t0, 1)}


# ---------------------------------------------------------------- 덱 집합

def control_space(s: int, squad: Sequence[str], arm: str, win: str | None, per: Mapping[str, Mapping[str, int]] | None) -> Any:
    """그 판의 후처리 메뉴. per가 있으면 바탕에 장비 옵션 배분을 얹는다."""
    if arm == "A":
        base = r0.opts(s, True)
        return M.Space(list(squad), variants_fn=r1.l_variants, base=with_alloc(base, per) if per else base)
    base = r3.probe_patch(s, squad, win)
    return M.Space(list(squad), variants_fn=r3.v3_variants, apply_fn=r3.v3_apply, base=with_alloc(base, per) if per else base)


def d1_decks() -> list[dict[str, Any]]:
    out = []
    for s in SEASONS:
        for arm, sd in (("A", r3.sdir(s)), (r3b.ARM, r3b.sdir(s))):
            for d in jload(sd / f"best5_{arm}.json"):
                post = jload(sd / "post" / f"{d['id']}.json")
                out.append({**d, "arm": arm, "post": post})
    return out


def d1_one(d: Mapping[str, Any], ev: Any) -> dict[str, Any]:
    f = OUT / "d1" / f"{d['id']}.json"
    if f.exists():
        return jload(f)
    f.parent.mkdir(parents=True, exist_ok=True)
    s, q, arm = d["season"], d["squad"], d["arm"]
    csp = control_space(s, q, arm, d.get("win"), e0_all(q))
    sel = csp.from_labels(d["post"]["best_variants"])
    o = osearch(d["id"], q, csp.options(sel), ev, f.parent)
    # 상호작용: 찾은 배분 위에서 컨트롤을 이전 선택부터 다시 찾는다
    al = {n: parse(lb) for n, lb in o["alloc"].items()}
    csp2 = control_space(s, q, arm, d.get("win"), al)
    sel2 = csp2.from_labels(d["post"]["best_variants"])
    log = f.parent / f"{d['id']}.c.jsonl"
    n0 = ev.sim_count
    run = M.Run({"id": d["id"], "squad": list(q)}, csp2, ev, method="C2:M3:k2", budget=C_BUDGET, out=log)
    try:
        m3_from(run, sel2, kick=2, seed=M.job_seed(d["id"] + "C2", SPEC))
    finally:
        run.close()
    errs = gz_log(log)
    out = {"id": d["id"], "season": s, "arm": arm, "squad": q, "win": d.get("win"), "v_spec": d["post"]["best"],
           "ctrl": d["post"]["best_variants"], **o, "v_start2": None if run.value(sel2) is None else run.value(sel2) / E8,
           "v_OC": None if run.best is None else run.best / E8, "ctrl2": list(csp2.labels(run.best_sel)),
           "c_evals": run.used, "c_errors": errs, "sims": o["sims"] + ev.sim_count - n0}
    jdump(f, out)
    return out


def d2_decks() -> list[dict[str, Any]]:
    out = []
    for s in SEASONS:
        bk, _ = r3.book_win(r3.recs_of(s, "A"))
        m = jload(r3.sdir(s) / "map_A.json")
        seen = {}
        for r in m["reps"]:
            if r.get("below"):
                continue
            for q in r["decks"]:
                c = frozenset(q)
                if c not in seen:
                    seen[c] = list(bk[c][1])
        for i, c in enumerate(sorted(seen, key=lambda c: (-bk[c][0], bk[c][1]))):
            out.append({"id": f"d2-S{s}-{i:03d}", "season": s, "squad": seen[c], "v_spec": bk[c][0]})
    return out


def d2_one(d: Mapping[str, Any], ev: Any) -> dict[str, Any]:
    f = OUT / "d2" / f"{d['id']}.json"
    if f.exists():
        return jload(f)
    f.parent.mkdir(parents=True, exist_ok=True)
    o = osearch(d["id"], d["squad"], with_alloc(r0.opts(d["season"], True), e0_all(d["squad"])), ev, f.parent)
    out = {**d, **o}
    jdump(f, out)
    return out


def _pool(jobs: Sequence[Any], fn: Any, workers: int, n_jobs: int) -> None:
    from nikke_opt.evaluator import make_evaluator
    lock = threading.Lock()
    t0 = time.time()
    with make_evaluator("rust", jobs=n_jobs, cache=False) as ev:
        def job(d):
            r = fn(d, ev)
            with lock:
                print(json.dumps({"id": r["id"], "v_spec": round(r["v_spec"], 3), "v_E0": r["v_E0"] and round(r["v_E0"], 3),
                                  "v_O": r["v_O"] and round(r["v_O"], 3), "v_OC": r.get("v_OC") and round(r["v_OC"], 3),
                                  "sims": ev.sim_count, "t": round(time.time() - t0)}, ensure_ascii=False), flush=True)
        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(job, jobs))


def cmd_d1(a: argparse.Namespace) -> int:
    _pool(d1_decks(), d1_one, a.workers, a.jobs)
    return 0


def cmd_d2(a: argparse.Namespace) -> int:
    _pool(d2_decks(), d2_one, a.workers, a.jobs)
    return 0


# ---------------------------------------------------------------- 조합 의존 · 흔들림

def d2_results() -> list[dict[str, Any]]:
    return [jload(OUT / "d2" / f"{d['id']}.json") for d in d2_decks()]


def cmd_transplant(a: argparse.Namespace) -> int:
    """D2(같은 시즌 · 같은 기본 컨트롤)에서 니케마다 그 시즌 최빈 배분(그 덱 자신은 빼고 센다)으로 바꿔 끼운 값."""
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    f = OUT / "transplant.json"
    rows = d2_results()
    reqs, meta = [], []
    for s in SEASONS:
        rs = [r for r in rows if r["season"] == s]
        for r in rs:
            for n in r["squad"]:
                others = collections.Counter(x["alloc"][n] for x in rs if x is not r and n in x["squad"])
                if not others:
                    continue
                mode = sorted(others.items(), key=lambda t: (-t[1], t[0]))[0][0]
                row = {"id": r["id"], "season": s, "nikke": n, "own": r["alloc"][n], "mode": mode, "n_other": sum(others.values()),
                       "v_O": r["v_O"], "v": r["v_O"] if mode == r["alloc"][n] else None}
                if row["v"] is None:
                    al = {m: parse(lb) for m, lb in r["alloc"].items()}
                    al[n] = parse(mode)
                    reqs.append(EvalRequest(r["squad"], boss=None, options=with_alloc(r0.opts(s, True), al)))
                meta.append(row)
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        res = iter(ev.evaluate(reqs))
        for row in meta:
            if row["v"] is None:
                x = next(res)
                row["v"] = None if x.error else x.total_damage / E8
        jdump(f, {"rows": meta, "sims": ev.sim_count})
    print(len(meta), "rows", len(reqs), "sims")
    return 0


def cmd_shake(a: argparse.Namespace) -> int:
    """시즌마다 A 최선 덱 하나(D1)를 다른 탐색 시드로 한 번 더(옵션 탐색만)."""
    from nikke_opt.evaluator import make_evaluator
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        for s in SEASONS:
            f = OUT / "shake" / f"S{s}.json"
            if f.exists():
                continue
            f.parent.mkdir(parents=True, exist_ok=True)
            d = [x for x in d1_decks() if x["season"] == s and x["arm"] == "A"][0]
            csp = control_space(s, d["squad"], "A", None, e0_all(d["squad"]))
            o = osearch(d["id"], d["squad"], csp.options(csp.from_labels(d["post"]["best_variants"])), ev, f.parent, tag="-rep")
            jdump(f, {"id": d["id"], **o})
            print(s, o["v_O"], flush=True)
    return 0


# ---------------------------------------------------------------- 분석(시뮬 0)

def q(xs: Sequence[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def summ(xs: Sequence[float]) -> dict[str, Any]:
    return {"n": len(xs), "median": st.median(xs), "p25": q(xs, 0.25), "p75": q(xs, 0.75), "min": min(xs), "max": max(xs),
            "ge1": sum(x >= 0.01 for x in xs), "ge3": sum(x >= 0.03 for x in xs)}


def cmd_analyze(a: argparse.Namespace) -> int:
    d1 = [jload(OUT / "d1" / f"{d['id']}.json") for d in d1_decks()]
    d1 = [x for x in d1 if x]
    d2 = [x for x in d2_results() if x]
    res: dict[str, Any] = {"d1": len(d1), "d2": len(d2)}
    if d1:
        for arm in ("A", r3b.ARM):
            xs = [x for x in d1 if x["arm"] == arm]
            if not xs:
                continue
            res[f"d1_{arm}"] = {
                "O_vs_E0": summ([x["v_O"] / x["v_E0"] - 1 for x in xs]),
                "O_vs_spec": summ([x["v_O"] / x["v_spec"] - 1 for x in xs]),
                "E0_vs_spec": summ([x["v_E0"] / x["v_spec"] - 1 for x in xs]),
                "OC_vs_O": summ([x["v_OC"] / x["v_O"] - 1 for x in xs]),
                "start2_check": max(abs(x["v_start2"] / x["v_O"] - 1) for x in xs),
                "sums": {s: {k: sum(x[k] for x in xs if x["season"] == s) for k in ("v_spec", "v_E0", "v_O", "v_OC")} for s in SEASONS},
            }
    if d2:
        seas = {}
        for s in SEASONS:
            rs = {frozenset(x["squad"]): x for x in d2 if x["season"] == s}
            m = jload(r3.sdir(s) / "map_A.json")
            reps = [r for r in m["reps"] if not r.get("below")]
            tot = [(r["total"], sum(rs[frozenset(qq)]["v_O"] for qq in r["decks"])) for r in reps]
            bkO = {c: (x["v_O"], tuple(x["squad"])) for c, x in rs.items()}
            bkS = {c: (x["v_spec"], tuple(x["squad"])) for c, x in rs.items()}
            pO, chO = R9.pack_vals(bkO)
            pS, chS = R9.pack_vals(bkS)
            rank_O = sorted(range(len(tot)), key=lambda i: -tot[i][1])
            seas[s] = {"reps": len(reps), "rep_totals": tot, "rep1_rank_under_O": rank_O.index(0) + 1,
                       "pack_spec": pS, "pack_O": pO, "rep1_O": tot[0][1], "loss_post": 1 - tot[0][1] / pO,
                       "pack_O_same_as_rep1": {frozenset(qq) for _, qq in chO} == {frozenset(qq) for qq in reps[0]["decks"]},
                       "rho_spec_O": r0.spearman([x["v_spec"] for x in rs.values()], [x["v_O"] for x in rs.values()]),
                       "rho_spec_E0": r0.spearman([x["v_spec"] for x in rs.values()], [x["v_E0"] for x in rs.values()])}
        res["d2_seasons"] = seas
        res["loss_post_median"] = st.median(v["loss_post"] for v in seas.values())
        res["d2_O_vs_E0"] = summ([x["v_O"] / x["v_E0"] - 1 for x in d2])
        # 레이어 장비 규칙(사람이 넣은 8명)을 탐색이 다시 찾나
        lay = collections.defaultdict(collections.Counter)
        for x in d1 + d2:
            for n, lb in x["alloc"].items():
                if n in LAYER_EQUIP:
                    lay[n][lb] += 1
        res["layer_equip"] = {n: {"rule": LAYER_EQUIP[n], "found": dict(c.most_common(4))} for n, c in lay.items()}
        # 많이 나온 배분(니케 · 시즌)
        cnt = collections.Counter(lb for x in d2 for lb in x["alloc"].values())
        res["alloc_top"] = cnt.most_common(15)
    tp = jload(OUT / "transplant.json")
    if tp:
        ls = [1 - r["v"] / r["v_O"] for r in tp["rows"] if r["v"] is not None]
        res["transplant"] = {**summ(ls), "same_share": sum(r["own"] == r["mode"] for r in tp["rows"]) / len(tp["rows"]),
                             "p90": q(ls, 0.9), "ge05": sum(x >= 0.005 for x in ls)}
    sh = [jload(OUT / "shake" / f"S{s}.json") for s in SEASONS]
    if all(sh) and d1:
        by = {x["id"]: x for x in d1}
        res["shake"] = [{"id": x["id"], "first": by[x["id"]]["v_O"], "rep": x["v_O"], "diff": x["v_O"] / by[x["id"]]["v_O"] - 1} for x in sh]
    jdump(HERE / "r0.json", res)
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str)[:6000])
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=("d1", "d2", "transplant", "shake", "analyze"))
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args()
    return {"d1": cmd_d1, "d2": cmd_d2, "transplant": cmd_transplant, "shake": cmd_shake, "analyze": cmd_analyze}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
