"""실험 32 R3 — 큰 축(버스트 버튼)을 덱 평가 안에서 같이 찾으면 지금 절차보다 나은 덱을 찾는가(README §R3 사전 등록).

    python -I experiments/32_primitive_control/r3.py types                    # R2 학습 6시즌 → 탐침 종류 순위(시뮬 0)
    source .cache/evaluators.env && python -I experiments/32_primitive_control/r3.py pilot      # S38 B 시드 s0(판단에 안 씀)
    source .cache/evaluators.env && python -I experiments/32_primitive_control/r3.py run --season 36 --arm B --seed 0
    source .cache/evaluators.env && python -I experiments/32_primitive_control/r3.py post --season 36 --arm B
    source .cache/evaluators.env && python -I experiments/32_primitive_control/r3.py rankers --season 36
    python -I experiments/32_primitive_control/r3.py analyze                  # → r3.json · r3.md

판:
  A  사전 계산 = 실험 31 B 판(실험 10 `run_method` G+E, 시드 s0 · s1 × 12,500, 레이어 켬). 후처리 = R1 L(실험 6 메뉴, 레이어 위) M3:k2 400.
  B  같은 사전 계산에서 실험 9 `Session.run`만 바꾼다: 바탕 = P0(R1 `p_base`) 1시뮬 → 바탕 ≥ 0.75 × 지금 최선 5덱의 가장 약한 덱이면
     버스트 탐침 4(R2 학습 6시즌 순위에서 그 덱에 쓸 수 있는 앞 4종). 덱 값 = 최고, 예산 = 실제 시뮬.
     후처리 = 원시 메뉴 v3의 작은 축(click · start_hold · cover_at · cover_fb · cancel · camera), 버스트는 탐침 최선 고정. M3:k2 400.
큐브는 두 판 모두 기본(찾지 않는다).
"""

from __future__ import annotations

import argparse
import collections
import copy
import gzip
import json
import statistics as st
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]
import r1  # noqa: E402
from r1 import run31, r0, M, menu6  # noqa: E402
from menu import MenuConflict  # noqa: E402

R30, R10, R9, SIM = run31.R30, run31.R10, run31.R9, run31.SIM
OUT = HERE / "r3"
E8 = 1e8
SEASONS = (36, 39, 41, 42)
PILOT = 38
TRAIN = (33, 34, 35, 37, 38, 40)    # 탐침 종류는 이 6시즌의 R2 기록으로만 고른다
K_PROBE = 4
GATE = 0.75
WIN_MIN = 0.01                      # R2: 「그 덱 버스트 선택지 중 최선이고 이득 ≥ 1%」
BUDGET = 400
SPEC = "M3:k2"
SMALL = ("click", "start_hold", "cover_at", "cover_fb", "cancel", "camera")
TAP_FIRE_CHARGE = {"rate": 4.0, "release": 0.03, "window": "burst_charge", "priority": "high"}   # 버충 택틱(tactics.json)의 톡톡이
# 판단 기준(사전 등록, 임시 수치)
T_SUM, T_SUM_N = 0.005, 3
T_RHO = 0.03
T_J = 0.05


def jdump(p: Path, x: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(x, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def jload(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ---------------------------------------------------------------- 탐침 종류(시뮬 0)

def burst_type(label: str, squad: Sequence[str]) -> str | None:
    """선택지 이름에서 니케 이름을 뺀 종류: `burst_who3:first=2`, `burst_t:wait2@2/2`(2단계 후보 중 두 번째)."""
    if label.startswith("squad:burst_who"):
        return label[len("squad:"):]
    who, ax, name = label.rsplit(":", 2)
    if ax != "burst_t":
        return None
    info = r1.nikke_info()
    s = str(info[who]["burst_stage"])
    cand = [x for x in squad if str(info[x]["burst_stage"]) == s]
    return f"burst_t:{name}@{s}/{cand.index(who) + 1}"


def cmd_types() -> int:
    D = jload(HERE / "r2" / "decks.json")
    recs = {json.loads(x)["id"]: json.loads(x) for x in (HERE / "r2" / "sample.jsonl").read_text(encoding="utf-8").splitlines()}
    win, app = collections.Counter(), collections.Counter()
    n = 0
    for d in D["sample"]:
        if d["season"] not in TRAIN:
            continue
        r, n = recs[d["id"]], n + 1
        best, seen = None, set()
        for lab, ax, v in r["vars"]:
            if ax not in ("burst_who", "burst_t"):
                continue
            t = burst_type(lab, d["squad"])
            seen.add(t)
            if v and (best is None or v > best[1]):
                best = (t, v)
        app.update(seen)
        if best and best[1] / r["base"] - 1 >= WIN_MIN:
            win[best[0]] += 1
    rank = sorted(app, key=lambda t: (-win[t], -app[t], t))
    out = {"train": list(TRAIN), "decks": n, "wins": sum(win.values()),
           "rank": [{"type": t, "win": win[t], "applicable": app[t]} for t in rank]}
    jdump(OUT / "probe_types.json", out)
    for x in out["rank"][:10]:
        print(x)
    return 0


def rank_types() -> list[str]:
    return [x["type"] for x in jload(OUT / "probe_types.json")["rank"]]


def probes(season: int, squad: Sequence[str]) -> list[tuple[str, dict[str, Any]]]:
    """그 덱에 쓸 수 있는 탐침 종류 순위 앞 K_PROBE개 → (종류, 요청 options)."""
    by = {}
    for (who, ax), vs in r1.prim_variants(squad, v=2).items():
        if ax.startswith("burst_who") or ax == "burst_t":
            for v in vs:
                by[burst_type(v["label"], squad)] = v
    base = r1.p_base(season, squad)
    return [(t, r1.prim_apply(base, [by[t]])) for t in rank_types() if t in by][:K_PROBE]


def probe_patch(season: int, squad: Sequence[str], t: str | None) -> dict[str, Any]:
    """B 후처리 바탕 = P0 + 이긴 탐침(없으면 P0)."""
    if t is None:
        return r1.p_base(season, squad)
    return dict(dict(probes_all(season, squad))[t])


def probes_all(season: int, squad: Sequence[str]) -> list[tuple[str, dict[str, Any]]]:
    by = {}
    for (who, ax), vs in r1.prim_variants(squad, v=2).items():
        if ax.startswith("burst_who") or ax == "burst_t":
            for v in vs:
                by[burst_type(v["label"], squad)] = v
    base = r1.p_base(season, squad)
    return [(t, r1.prim_apply(base, [v])) for t, v in by.items()]


# ---------------------------------------------------------------- B 사전 계산: Session 바꿔 끼우기

class ProbeSession(R9.Session):
    """실험 9 Session과 같은 기록 · 예산 규칙, 다만 used = 실제 시뮬 수. 바탕은 P0, 문턱을 넘은 덱만 탐침."""

    def __init__(self, acct: Any, ev: Any, budget: int, season: int):
        super().__init__(acct, ev, budget)
        self.season = season
        self.stat = collections.Counter()

    def gate(self) -> float:
        _, ch = R9.pack_vals(self.book.best)
        return GATE * min(v for v, _ in ch) if len(ch) == 5 else 0.0

    def run(self, squads, phase: str, cap: int | None = None) -> int:
        from nikke_opt.evaluator import EvalRequest
        room = self.left if cap is None else min(self.left, cap)
        todo = [sq for sq in dict.fromkeys(squads) if sq not in self.asked][:max(room, 0)]
        if not todo:
            return 0
        res = self.ev.evaluate([EvalRequest(sq, boss=None, options=r1.p_base(self.season, sq)) for sq in todo])
        self.used += len(todo)
        base = {}
        for sq, r in zip(todo, res):
            self.asked.add(sq)
            base[sq] = (None if r.error else r.total_damage, r.error, r.cached)
            if base[sq][0] is not None:
                self.book.add(sq, base[sq][0] / E8)
        thr = self.gate()
        cand = sorted((sq for sq, b in base.items() if b[0] is not None and b[0] / E8 >= thr), key=lambda sq: -base[sq][0])
        jobs: list[tuple[tuple, str, dict]] = []
        cut = 0
        for sq in cand:
            ps = probes(self.season, sq)
            if len(jobs) + len(ps) > self.left:
                cut += 1
                continue
            jobs += [(sq, t, o) for t, o in ps]
        pv: dict[tuple, list] = collections.defaultdict(list)
        if jobs:
            res2 = self.ev.evaluate([EvalRequest(sq, boss=None, options=o) for sq, _, o in jobs])
            self.used += len(jobs)
            for (sq, t, _), r in zip(jobs, res2):
                pv[sq].append([t, None if r.error else r.total_damage])
                self.stat["probe_errors"] += bool(r.error)
        self.stat.update(base_sims=len(todo), probe_sims=len(jobs), probed=len(pv), gated_out=len(base) - len(cand), cut=cut)
        for sq in todo:
            b, err, cached = base[sq]
            best, win = b, None
            for t, v in pv.get(sq, []):
                if v is not None and (best is None or v > best):
                    best, win = v, t
            if best is not None and win is not None:
                self.book.add(sq, best / E8)
            self.records.append({"squad": list(sq), "total_damage": best, "phase": phase, "error": err, "cached": cached,
                                 "base": b, "probes": pv.get(sq), "win": win, "gate": thr})
        return len(todo)


# ---------------------------------------------------------------- 사전 계산 실행

def sdir(s: int) -> Path:
    return OUT / f"S{s}"


def run_pre(s: int, arm: str, seed: int, ev: Any, out_dir: Path) -> dict[str, Any]:
    f = out_dir / f"{arm}_s{seed}.json"
    if f.exists():
        return jload(f)
    out_dir.mkdir(parents=True, exist_ok=True)
    acct = run31.account(s, seed)
    sims0 = ev.sim_count
    if arm == "B":
        orig = R9.Session
        R9.Session = lambda a, e, b: ProbeSession(a, e, b, s)   # run_method 안의 R9.Session(acct, ev, budget)
        try:
            summ, recs, sess = R10.run_method(acct, "G+E", run31.SEED_BUDGET, ev, pool=177)
        finally:
            R9.Session = orig
        stat = dict(sess.stat)
    else:
        summ, recs, sess = R10.run_method(acct, "G+E", run31.SEED_BUDGET, ev, pool=177)
        stat = {}
    R30.write_recs(out_dir / f"{arm}_s{seed}.jsonl.gz", recs)
    out = {"season": s, "arm": arm, "seed": seed, "evals": summ["evals"], "records": len(recs), "sims": ev.sim_count - sims0,
           "seconds": summ["seconds"], "best": summ["final"]["total"], "errors": summ["errors"], "kicks": len(summ["kicks"]),
           "stat": stat, "history": summ["history"],
           "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"}
    jdump(f, out)
    print(json.dumps({k: v for k, v in out.items() if k != "history"}, ensure_ascii=False), flush=True)
    return out


def cmd_run(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        for s in [int(x) for x in str(a.season).split(",")]:
            for arm in a.arm.split(","):
                for k in [int(x) for x in str(a.seed).split(",")]:
                    run_pre(s, arm, k, ev, sdir(s))
    return 0


def cmd_pilot(a: argparse.Namespace) -> int:
    """S38 B 시드 s0 — 탐침 비율 · 실제 덱 수 · v3 선택지 요청 확인(판단에 안 씀)."""
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        d = OUT / "pilot"
        # v3 선택지(충전 창 tap_fire 4.0 · high)가 요청으로 받아지는지
        sq = ["아니스 : 스타", "나유타", "프리카", "홍련 : 흑영", "리버렐리오"]   # R2 S38 표본 덱(차지 UP 니케가 든 첫 덱)
        sp = small_space(PILOT, sq, None)
        v3 = [i for i, v in enumerate(sp.vars) if v["label"].endswith(":click:tapfire@charge4")]
        reqs = [EvalRequest(sq, boss=None, options=sp.options(tuple(i if k == sp.key_of[i] else -1 for k in range(sp.K)))) for i in v3]
        res = ev.evaluate([EvalRequest(sq, boss=None, options=sp.base)] + reqs)
        chk = {"squad": sq, "base": res[0].total_damage, "v3": [[sp.vars[i]["label"], r.total_damage, r.error] for i, r in zip(v3, res[1:])]}
        jdump(d / "v3_check.json", chk)
        print(json.dumps(chk, ensure_ascii=False), flush=True)
        run_pre(PILOT, "B", 0, ev, d)
    return 0


# ---------------------------------------------------------------- 기록 → 최선 5덱

def recs_of(s: int, arm: str) -> list[dict[str, Any]]:
    return [r for k in run31.SEEDS for r in R30.load_recs(sdir(s) / f"{arm}_s{k}.jsonl.gz")]


def book_win(recs: Sequence[Mapping[str, Any]]) -> tuple[dict, dict]:
    """book(구성 → (값, 순서)) + 구성 → 이긴 탐침(B)."""
    bk: dict[frozenset, tuple[float, tuple]] = {}
    win: dict[frozenset, str | None] = {}
    for r in recs:
        if r.get("total_damage") is None:
            continue
        sq, v, c = tuple(r["squad"]), r["total_damage"] / E8, frozenset(r["squad"])
        if c not in bk or v > bk[c][0]:
            bk[c], win[c] = (v, sq), r.get("win")
    return bk, win


def best5(s: int, arm: str) -> list[dict[str, Any]]:
    bk, win = book_win(recs_of(s, arm))
    total, ch = R9.pack_vals(bk)
    return [{"id": f"r3-S{s}-{arm}-{i}", "season": s, "squad": list(q), "value": v, "win": win.get(frozenset(q))}
            for i, (v, q) in enumerate(ch)]


# ---------------------------------------------------------------- 후처리

def v3_variants(squad: Sequence[str]) -> dict:
    """원시 메뉴 v2의 작은 축 + v3: 충전 창 tap_fire 4.0 · high(버충 택틱의 톡톡이 값 · 등급)."""
    info = r1.nikke_info()
    out = {}
    for (who, ax), vs in r1.prim_variants(squad, v=2).items():
        if ax not in SMALL:
            continue
        vs = list(vs)
        if ax == "click" and not info[who]["full_charge_only"]:
            vs.append(r1._v(who, "click", "tapfire@charge4", r1._c(who, {"tap_fire": dict(TAP_FIRE_CHARGE)})))
        out[(who, ax)] = vs
    return out


def _charge_tap(v: Mapping[str, Any]) -> bool:
    if v["axis"] != "click":
        return False
    c = v["patch"]["chars"][v["nikke"]]["control"]
    return any(e.get("window") == "burst_charge" for e in c.get("click", [])) or \
        (isinstance(c.get("tap_fire"), dict) and c["tap_fire"].get("window") == "burst_charge")


def v3_apply(options: Mapping[str, Any], chosen: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """r1 `prim_apply` 규칙 + 충전 창 톡톡이(click · tap_fire) 한 명만. 바탕에 이미 붙은 버스트(탐침)는 그대로 둔다."""
    if sum(_charge_tap(v) for v in chosen) > 1:
        raise MenuConflict("버스트 충전 창 톡톡이는 한 명만")
    by: dict[str, dict[str, Any]] = {}
    for v in chosen:
        if v["nikke"]:
            by.setdefault(v["nikke"], {})[v["axis"]] = v
    for who, ax in by.items():
        if "click" in ax and "cover_fb" in ax and menu6._holds_own_fb(ax["click"]["patch"]["chars"][who]["control"]):
            raise MenuConflict(f"{who}: 같은 창에 홀드와 엄폐")
    out = menu6.deep_merge(options, {})
    for v in chosen:
        out = menu6.deep_merge(out, v["patch"])
    return out


def small_space(s: int, squad: Sequence[str], win: str | None) -> Any:
    return M.Space(list(squad), variants_fn=v3_variants, apply_fn=v3_apply, base=probe_patch(s, squad, win))


def post_one(d: Mapping[str, Any], arm: str, ev: Any, tag: str = "") -> dict[str, Any]:
    f = sdir(d["season"]) / "post" / f"{d['id']}{tag}.json"
    if f.exists():
        return jload(f)
    if arm == "A":
        sp = r1.space({"squad": d["squad"], "season": d["season"]}, "L")
    else:
        sp = small_space(d["season"], d["squad"], d["win"])
    log = f.with_suffix(".jsonl")
    log.parent.mkdir(parents=True, exist_ok=True)
    run = M.Run({"id": d["id"], "squad": list(d["squad"])}, sp, ev, method=f"{arm}:{SPEC}", budget=BUDGET, out=log)
    t0 = time.time()
    try:
        M.m3(run, kick=2, seed=M.job_seed(d["id"] + tag, SPEC))
    finally:
        run.close()
    raw = log.read_bytes()
    with gzip.open(log.with_suffix(".jsonl.gz"), "wb") as g:
        g.write(raw)
    log.unlink()
    errs = sum(1 for ln in raw.decode().splitlines() if json.loads(ln)["error"])
    out = {**d, "arm": arm, "tag": tag, "evals": run.used, "errors": errs, "best": run.best / E8, "base": run.base_damage / E8,
           "best_variants": list(sp.labels(run.best_sel)), "keys": sp.K, "options": sp.nv, "seconds": round(time.time() - t0, 1)}
    jdump(f, out)
    return out


def cmd_post(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    lock = threading.Lock()
    t0 = time.time()
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        jobs = []
        for s in [int(x) for x in str(a.season).split(",")]:
            for arm in a.arm.split(","):
                ds = best5(s, arm)
                jdump(sdir(s) / f"best5_{arm}.json", ds)
                jobs += [(d, arm, "") for d in ds]
                if a.repeat:   # 탐색 흔들림: 최선 덱 하나를 다른 탐색 시드로 한 번 더
                    jobs.append((ds[0], arm, "-rep"))

        def job(x):
            d, arm, tag = x
            r = post_one(d, arm, ev, tag)
            with lock:
                print(json.dumps({"id": d["id"] + tag, "evals": r["evals"], "errors": r["errors"], "gain": round(r["best"] / r["base"], 4),
                                  "sims": ev.sim_count, "t": round(time.time() - t0)}, ensure_ascii=False), flush=True)
        with ThreadPoolExecutor(a.workers) as pool:
            list(pool.map(job, jobs))
    return 0


# ---------------------------------------------------------------- 랭커 덱(실전 짝)

def cmd_rankers(a: argparse.Namespace) -> int:
    """R0 실전 짝(랭커 10명 이상)을 A = 레이어 바탕 1시뮬, B = P0 + 탐침 4(문턱 없이) 최고로 잰다."""
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    R0 = {r["season"]: r for r in jload(HERE / "r0.json")["seasons"]}
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        for s in [int(x) for x in str(a.season).split(",")]:
            f = sdir(s) / "rankers.json"
            if f.exists():
                continue
            n0 = ev.sim_count
            rows = R0[s]["real_rows"]
            qs = [r["deck"].split(",") for r in rows]
            reqs, idx = [], []
            for i, q in enumerate(qs):
                reqs.append(EvalRequest(q, boss=None, options=r0.opts(s, True)))
                idx.append((i, "A", None))
                reqs.append(EvalRequest(q, boss=None, options=r1.p_base(s, q)))
                idx.append((i, "B", None))
                for t, o in probes(s, q):
                    reqs.append(EvalRequest(q, boss=None, options=o))
                    idx.append((i, "B", t))
            res = ev.evaluate(reqs)
            out = [{"deck": r["deck"], "n": r["n"], "real": r["real"], "A": None, "B_base": None, "B": None, "win": None} for r in rows]
            for (i, arm, t), r in zip(idx, res):
                v = None if r.error else r.total_damage / E8
                o = out[i]
                if arm == "A":
                    o["A"] = v
                elif t is None:
                    o["B_base"] = o["B"] = v
                elif v is not None and (o["B"] is None or v > o["B"]):
                    o["B"], o["win"] = v, t
            jdump(f, {"season": s, "rows": out, "sims": ev.sim_count - n0})
            print(json.dumps({"season": s, "decks": len(out), "sims": ev.sim_count - n0}), flush=True)
    return 0


# ---------------------------------------------------------------- 분석(시뮬 0)

def judge(vals: Sequence[float], thr: float, n_need: int | None = None) -> str:
    """vals = 시즌별 B − A(또는 B/A − 1). 중앙 ≥ thr (+ 같은 방향 시즌 수) → B, 반대 방향 같은 크기 → A."""
    m = st.median(vals)
    if n_need is None:
        return "B" if m >= thr else "A" if m <= -thr else "-"
    if m >= thr and sum(v >= 0 for v in vals) >= n_need:
        return "B"
    if m <= -thr and sum(v <= 0 for v in vals) >= n_need:
        return "A"
    return "-"


def cmd_analyze(a: argparse.Namespace) -> int:
    targets = set(r1.layer_targets())
    rows = []
    for s in SEASONS:
        row: dict[str, Any] = {"season": s, "arms": {}}
        rk = run31.ranker_decks(s)
        top = [list(q) for q in rk["top_five"]]
        rr = (jload(sdir(s) / "rankers.json") or {}).get("rows", [])
        for arm in ("A", "B"):
            pre = {k: jload(sdir(s) / f"{arm}_s{k}.json") for k in run31.SEEDS}
            if not all(pre.values()):
                continue
            recs = recs_of(s, arm)
            bk, _ = book_win(recs)
            seed_best = {k: R9.pack_vals(book_win(R30.load_recs(sdir(s) / f"{arm}_s{k}.jsonl.gz"))[0])[0] for k in run31.SEEDS}
            ds = jload(sdir(s) / f"best5_{arm}.json") or best5(s, arm)
            posts = [jload(sdir(s) / "post" / f"{d['id']}.json") for d in ds]
            rep = jload(sdir(s) / "post" / f"{ds[0]['id']}-rep.json")
            five = [d["squad"] for d in ds]
            x: dict[str, Any] = {
                "sims_pre": sum(p["sims"] for p in pre.values()), "records": len(recs), "comps": len(bk),
                "pre_total": sum(d["value"] for d in ds), "seed_pack": seed_best,
                "post_total": sum(p["best"] for p in posts) if all(posts) else None,
                "post_sims": sum(p["evals"] for p in posts) if all(posts) else None,
                "five": [{"squad": d["squad"], "value": d["value"], "win": d["win"],
                          "post": None if not p else p["best"], "variants": None if not p else p["best_variants"]} for d, p in zip(ds, posts)],
                "J_top": SIM.pair_jaccard(top, five),
                "targets_in_five": sorted({n for q in five for n in q} & targets),
                "rep_post": None if not rep else {"best": rep["best"], "first": posts[0]["best"] if posts[0] else None},
            }
            if arm == "B":
                st_ = collections.Counter()
                for p in pre.values():
                    st_.update(p["stat"])
                x["probe"] = dict(st_)
                x["probe_share"] = st_["probe_sims"] / max(1, st_["probe_sims"] + st_["base_sims"])
            ok = [r for r in rr if r.get(arm) is not None]
            x["rho"] = r0.spearman([r["real"] for r in ok], [r[arm] for r in ok])
            x["rho_decks"] = len(ok)
            if a.maps:
                m = R30.class_map(bk)
                reps = [r for r in m["reps"] if not r.get("below")]
                x["map"] = {"reps": len(reps), "best": m["best"], "targets": dict(collections.Counter(
                    n for r in reps for q in r["decks"] for n in q if n in targets))}
            row["arms"][arm] = x
        if len(row["arms"]) == 2 and all(row["arms"][k]["post_total"] for k in "AB"):
            A, B = row["arms"]["A"], row["arms"]["B"]
            row["sum_ratio"] = B["post_total"] / A["post_total"] - 1
            row["rho_diff"] = None if A["rho"] is None or B["rho"] is None else B["rho"] - A["rho"]
            row["J_diff"] = B["J_top"] - A["J_top"]
        rows.append(row)
    summ: dict[str, Any] = {}
    done = [r for r in rows if "sum_ratio" in r]
    if len(done) == len(SEASONS):
        sr = [r["sum_ratio"] for r in done]
        rd = [r["rho_diff"] for r in done if r["rho_diff"] is not None]
        jd = [r["J_diff"] for r in done]
        v = {"sum": judge(sr, T_SUM, T_SUM_N), "rho": judge(rd, T_RHO), "J": judge(jd, T_J)}
        nb, na = sum(x == "B" for x in v.values()), sum(x == "A" for x in v.values())
        summ = {"sum_ratio_median": st.median(sr), "sum_B_ge_A": sum(x >= 0 for x in sr), "rho_diff_median": st.median(rd),
                "J_diff_median": st.median(jd), "votes": v,
                "verdict": "B" if nb >= 2 else "A" if na >= 2 else "-"}
    jdump(HERE / "r3.json", {"summary": summ, "seasons": rows})
    pc = lambda x: "—" if x is None else f"{x:+.2%}"  # noqa: E731
    f3 = lambda x: "—" if x is None else f"{x:.3f}"  # noqa: E731
    md = ["| 시즌 | A 5덱(후처리) | B 5덱(후처리) | B/A − 1 | 시드 s0 · s1 사전 5덱 A | B | ρ A · B | J A · B | B 탐침 비율 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        A, B = r["arms"].get("A"), r["arms"].get("B")
        if not (A and B):
            md.append(f"| S{r['season']} | 대기 | | | | | | | |")
            continue
        sp = lambda x: " · ".join(f"{v:.2f}" for v in x["seed_pack"].values())  # noqa: E731
        md.append(f"| S{r['season']} | {A['post_total'] or 0:.2f} | {B['post_total'] or 0:.2f} | {pc(r.get('sum_ratio'))} | {sp(A)} | {sp(B)} | "
                  f"{f3(A['rho'])} · {f3(B['rho'])} | {A['J_top']:.2f} · {B['J_top']:.2f} | {B.get('probe_share', 0):.0%} |")
    if summ:
        md += ["", f"판단: 5덱 합 {summ['votes']['sum']} (중앙 {summ['sum_ratio_median']:+.2%}, B ≥ A {summ['sum_B_ge_A']}/4) · "
                   f"ρ {summ['votes']['rho']} (중앙 {summ['rho_diff_median']:+.3f}) · J {summ['votes']['J']} (중앙 {summ['J_diff_median']:+.3f}) "
                   f"→ **{summ['verdict']}**"]
    (HERE / "r3.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=("types", "pilot", "run", "post", "rankers", "analyze"))
    p.add_argument("--season", default=",".join(map(str, SEASONS)))
    p.add_argument("--arm", default="A,B")
    p.add_argument("--seed", default="0,1")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--repeat", action="store_true")
    p.add_argument("--maps", action="store_true")
    a = p.parse_args()
    if a.cmd == "types":
        return cmd_types()
    return {"pilot": cmd_pilot, "run": cmd_run, "post": cmd_post, "rankers": cmd_rankers, "analyze": cmd_analyze}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
