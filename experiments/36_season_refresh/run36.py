"""실험 36 — 최근 10시즌 현황판 다시 계산(평가기 nikke-calc-rs 8bc51a2, 실험 32 · 35 판단대로의 절차). README §절차.

    source .cache/evaluators.env && python -I experiments/36_season_refresh/run36.py run --season 33 --part B_s0
    부분(시즌마다 이 순서): B_s0 · B_s1(서로 독립) → end → core30 → members · rankers · post
    python -I experiments/36_season_refresh/run36.py analyze      # → analysis.json · results.md(실험 31 모양 + 후처리)

실험 31의 기록 모양(run_log/S??/part_*.json · *.jsonl.gz · members.json · rankers.json · maps.json · analysis.json)을 그대로 따라
현황판(web/build.py --exp)이 읽게 한다. 실험 31 함수는 경로(LOG · HERE)와 덱 값(book)만 바꿔 끼워 다시 쓴다.
실험 32 R3 시즌(S36 · S39 · S41 · S42)의 사전 계산 · 끝 탐침은 실험 32 기록을 옮겨 쓴다(같은 평가기 · 같은 절차).
"""

from __future__ import annotations

import argparse
import collections
import copy
import gzip
import json
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXP32 = HERE.parent / "32_primitive_control"
EXP35 = HERE.parent / "35_equip_options"
EXP17 = HERE.parent / "17_cube_control"
sys.path[:0] = [str(EXP35), str(EXP32), str(EXP17)]
import r3  # noqa: E402
import r3b  # noqa: E402
import r3c  # noqa: E402  (r3.probes · r3b.post_one를 수정 1로 바꿔 끼운다 — 이 파일은 r3b 실행 함수를 부르지 않는다)
import run35  # noqa: E402
import cubes as CB  # noqa: E402
from r3 import r1, r0, run31, M, R9, R10, R30, E8, menu6  # noqa: E402

# ---------------------------------------------------------------- 절차(실험 32 · 35 판단으로 정한다 — README §절차)
ARM: str | None = "A"      # "A" = 레이어 바탕(지금 절차) · "Bc" = 실험 32 R3c(P0 바탕 + 끝 탐침 + 원시 메뉴 후처리)
OPT: str | None = "final5" # "final5" = 최종 5덱에만 옵션 탐색 · "reps" = 지도 대표 덱 전부에 옵션 탐색 → 다시 묶기
C2: bool | None = True     # 옵션 뒤 컨트롤 + 큐브를 한 번 더 찾는가
CUBE = True                # 후처리에 큐브를 같이 찾는다(지금 운용 기본 JT와 같은 뜻 — 사용자에게 알림, 2026-11-02)
POST_BUDGET = 400          # 컨트롤(+큐브) · 옵션 · 다시 찾기 각각
SPEC = "M3:k2"
POST_NAME = "post"         # 후처리 기록 이름(post/ · post.json · rpost.json · trace/). cr36.py가 카메라 재장전 판(post_cr)으로 바꾼다
SIM_EXTRA: dict[str, Any] = {}  # 후처리 요청 options.sim에 더할 것(cr36.py: camera_reload_cancel). 비면 그대로

R3_SEASONS = set(r3.SEASONS)
SEASONS = run31.SEASONS
BOSSES = run31.BOSSES                  # {"nocore": 0, "core30": 30}
PARTS = ("B_s0", "B_s1", "end", "core30", "members", "rankers", "post")

run31.LOG = HERE / "run_log"
run31.HERE = HERE                      # run31 analyze가 analysis.json · results.md를 여기에 쓴다
run31.PARTS = PARTS                    # analyze_season의 부분별 시뮬 합
run31.arm_of = lambda use_w=None: ARM  # 지도 캐시(maps.json) 키 · 화면의 판 이름을 이 실험의 판으로


def need_config() -> None:
    if ARM is None or OPT is None or C2 is None:
        raise RuntimeError("ARM · OPT · C2가 정해지지 않았다 — 실험 32 · 35 판단 뒤 README §절차에 적고 정한다")


def sdir(s: int) -> Path:
    return run31.sdir(s)


def jload(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def jdump(p: Path, x: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(x, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 덱 하나의 값(판마다)

def with_core(o: Mapping[str, Any], core: int) -> dict[str, Any]:
    o = copy.deepcopy(dict(o))
    if core:
        o.setdefault("enemy", {})["core_px"] = core
    return o


def p0(s: int, squad: Sequence[str], core: int = 0) -> dict[str, Any]:
    return with_core(r1.p_base(s, squad), core)


def deck_requests(s: int, squad: Sequence[str], core: int) -> list[tuple[str | None, dict[str, Any]]]:
    """판의 「덱 하나 재기」: A = 레이어 1시뮬, Bc = P0 + 탐침(수정 1 종류) 중 최고."""
    if ARM == "A":
        return [(None, run31.options(s, core))]
    try:
        ps = r3c.probes_c(s, squad)
    except KeyError:          # 평가기 니케 정보에 없는 니케(랭커 덱) — 탐침 없이 P0만
        ps = []
    return [(None, p0(s, squad, core))] + [(t, with_core(o, core)) for t, o in ps]


def eval_decks(s: int, squads: Sequence[Sequence[str]], core: int, ev: Any) -> list[dict[str, Any]]:
    """squads마다 {value, win, members} — 판의 덱 재기 방식 최고."""
    from nikke_opt.evaluator import EvalRequest
    reqs, idx = [], []
    for i, q in enumerate(squads):
        for t, o in deck_requests(s, q, core):
            reqs.append(EvalRequest(list(q), boss=None, options=o))
            idx.append((i, t))
    res = ev.evaluate(reqs)
    out = [{"value": None, "win": None, "members": None} for _ in squads]
    for (i, t), r in zip(idx, res):
        v = None if r.error else r.total_damage / E8
        if v is not None and (out[i]["value"] is None or v > out[i]["value"]):
            out[i] = {"value": v, "win": t, "members": [[x["name"], round(x["damage"] / E8, 3)] for x in r.raw.get("members", [])]}
    return out


class CoreP0Session(r3b.P0Session):
    """P0Session과 같고 적에 코어를 단다."""

    def __init__(self, acct: Any, ev: Any, budget: int, season: int, core: int):
        super().__init__(acct, ev, budget, season)
        self.core = core

    def run(self, squads, phase: str, cap: int | None = None) -> int:
        from nikke_opt.evaluator import EvalRequest
        room = self.left if cap is None else min(self.left, cap)
        todo = [sq for sq in dict.fromkeys(squads) if sq not in self.asked][:max(room, 0)]
        if not todo:
            return 0
        res = self.ev.evaluate([EvalRequest(sq, boss=None, options=p0(self.season, sq, self.core)) for sq in todo])
        for sq, r in zip(todo, res):
            self.asked.add(sq)
            dmg = None if r.error else r.total_damage
            if dmg is not None:
                self.book.add(sq, dmg / E8)
            self.records.append({"squad": list(sq), "total_damage": dmg, "phase": phase, "error": r.error, "cached": r.cached})
        self.used += len(todo)
        return len(todo)


# ---------------------------------------------------------------- 끝 탐침(Bc) — r3b.end_probe와 같은 규칙, book · 코어를 받는다

def end_probe(s: int, base: Mapping[frozenset, tuple[float, tuple]], core: int, ev: Any) -> dict[str, Any]:
    from nikke_opt.evaluator import EvalRequest
    order = sorted(base, key=lambda c: (-base[c][0], base[c][1]))
    cur = dict(base)
    rows: dict[frozenset, dict[str, Any]] = {}
    n0, t0, rnd = ev.sim_count, time.time(), 0
    while len(rows) < r3b.N_END:
        pick = r3b.end_pick(order, cur, set(rows), r3b.N_END - len(rows))
        if not pick:
            break
        jobs = [(c, t, with_core(o, core)) for c in pick for t, o in r3c.probes_c(s, base[c][1])]
        res = ev.evaluate([EvalRequest(base[c][1], boss=None, options=o) for c, _, o in jobs])
        for c in pick:
            rows[c] = {"squad": list(base[c][1]), "base": base[c][0], "probes": [], "win": None, "round": rnd}
        for (c, t, _), r in zip(jobs, res):
            v = None if r.error else r.total_damage / E8
            x = rows[c]
            x["probes"].append([t, v])
            if v is not None and v > cur[c][0]:
                cur[c], x["win"] = (v, base[c][1]), t
        rnd += 1
    return {"season": s, "core": core, "rounds": rnd, "comps": len(rows), "sims": ev.sim_count - n0,
            "seconds": round(time.time() - t0, 1), "errors": sum(v is None for x in rows.values() for _, v in x["probes"]),
            "rows": list(rows.values())}


def apply_end(bk: dict, end: Mapping[str, Any] | None) -> tuple[dict, dict]:
    win: dict[frozenset, str | None] = {}
    for x in (end or {}).get("rows", []):
        if x["win"]:
            c = frozenset(x["squad"])
            v = max(v for _, v in x["probes"] if v is not None)
            bk[c], win[c] = (v, tuple(x["squad"])), x["win"]
    return bk, win


# ---------------------------------------------------------------- book(실험 31 `book`을 바꿔 끼운다)

def book_win(s: int, boss: str) -> tuple[dict, dict]:
    d = sdir(s)
    if boss == "nocore":
        bk = R30.book_of([r for k in run31.SEEDS for r in run31.load_recs(d / f"B_s{k}.jsonl.gz")])
        return apply_end(bk, jload(d / "end.json")) if ARM != "A" else (bk, {})
    bk = R30.book_of(run31.load_recs(d / "core30.jsonl.gz"))
    return apply_end(bk, jload(d / "end_core30.json")) if ARM != "A" else (bk, {})


def book36(s: int, boss: str, arm: str) -> dict:
    return book_win(s, boss)[0]


run31.book = book36


# ---------------------------------------------------------------- 실행 부분

def part_B(s: int, k: int, ev: Any) -> dict[str, Any]:
    d = sdir(s)
    if s in R3_SEASONS:   # 실험 32 기록을 옮긴다
        src_dir, name = (r3.sdir(s), f"A_s{k}") if ARM == "A" else (r3b.pre_dir(s), f"Bp_s{k}")
        shutil.copyfile(src_dir / f"{name}.jsonl.gz", d / f"B_s{k}.jsonl.gz")
        src = jload(src_dir / f"{name}.json")
        return {k2: src[k2] for k2 in ("evals", "seconds", "best", "errors", "kicks", "history", "sims")} | \
            {"copied_from": str((src_dir / name).relative_to(HERE.parent.parent)), "sims_new": 0}
    acct = run31.account(s, k)
    orig = R9.Session
    if ARM != "A":
        R9.Session = lambda a, e, b: r3b.P0Session(a, e, b, s)
    try:
        r, recs, _ = R10.run_method(acct, "G+E", run31.SEED_BUDGET, ev, pool=177)
    finally:
        R9.Session = orig
    run31.write_recs(d / f"B_s{k}.jsonl.gz", recs)
    return {"evals": r["evals"], "seconds": r["seconds"], "best": r["final"]["total"], "errors": r["errors"],
            "kicks": len(r["kicks"]), "history": r["history"]}


def part_end(s: int, ev: Any) -> dict[str, Any]:
    d = sdir(s)
    if ARM == "A":
        return {"skipped": "A"}
    if s in R3_SEASONS:
        src = jload(r3b.OUT / f"S{s}" / "end.json")   # r3c가 바꿔 끼운 OUT = r3c/
        jdump(d / "end.json", src)
        return {k: src[k] for k in ("rounds", "comps", "sims", "seconds", "errors")} | {"copied_from": f"32_primitive_control/r3c/S{s}/end.json", "sims_new": 0}
    bk = R30.book_of([r for k in run31.SEEDS for r in run31.load_recs(d / f"B_s{k}.jsonl.gz")])
    out = end_probe(s, bk, 0, ev)
    jdump(d / "end.json", out)
    return {k: out[k] for k in ("rounds", "comps", "sims", "seconds", "errors")}


def part_core30(s: int, ev: Any) -> dict[str, Any]:
    d = sdir(s)
    nb = book36(s, "nocore", ARM)
    m = run31.class_map(s, "nocore", ARM)
    if ARM == "A":
        out, recs = run31.core_rc(s, ev, nb, m)
        run31.write_recs(d / "core30.jsonl.gz", recs)
        return out
    core = run31.CORE_PX
    acct = run31.account(s, 0, core)
    cands = R30.core_candidates(nb, [m])
    t0, n0 = time.time(), ev.sim_count
    sess = CoreP0Session(acct, ev, len(cands), s, core)
    sess.run(cands, "코어 30 재평가")
    r_recs = list(sess.records)
    r_sims = ev.sim_count - n0
    orig = R9.Session
    R9.Session = lambda a, e, b: CoreP0Session(a, e, b, s, core)
    try:
        cs, c_recs = R30.continue_search(acct, ev, r_recs, run31.CORE_CONT)
    finally:
        R9.Session = orig
    recs = r_recs + list(c_recs)
    run31.write_recs(d / "core30.jsonl.gz", recs)
    end = end_probe(s, R30.book_of(recs), core, ev)
    jdump(d / "end_core30.json", end)
    return {"requests": len(cands), "reeval_sims": r_sims, "reeval_best": R9.pack_vals(R30.book_of(r_recs))[0],
            "extra_evals": cs["evals"], "evals": len(cands) + cs["evals"], "end_sims": end["sims"], "seconds": round(time.time() - t0, 1)}


def part_members(s: int, ev: Any) -> dict[str, Any]:
    """지도 대표 덱을 판의 덱 재기 방식으로 다시 재서 니케별 딜을 남긴다(화면용)."""
    out: dict[str, Any] = {}
    for b, core in BOSSES.items():
        todo = run31.rep_decks(run31.class_map(s, b, ARM))
        res = eval_decks(s, todo, core, ev)
        out[b] = {",".join(q): {"total": x["value"], "win": x["win"], "members": x["members"]} for q, x in zip(todo, res)}
    jdump(sdir(s) / "members.json", out)
    return {"decks": {b: len(v) for b, v in out.items()}}


def part_rankers(s: int, ev: Any) -> dict[str, Any]:
    """랭커 대표 5덱 · 1위 5덱 · 상위 40 스쿼드를 판의 덱 재기 방식으로(실험 31 `rankers`와 같은 모양)."""
    decks = run31.ranker_decks(s)
    todo = sorted({tuple(q) for v in decks.values() for q in v if all(n[0] not in "?!" for n in q)})
    out: dict[str, Any] = {"season": s, "squads": {}}
    for b, core in BOSSES.items():
        for q, x in zip(todo, eval_decks(s, todo, core, ev)):
            e = out["squads"].setdefault(",".join(q), {})
            e[b], e[f"{b}_members"], e[f"{b}_win"] = x["value"], x["members"], x["win"]
    jdump(sdir(s) / "rankers.json", out)
    return {"squads": len(todo)}


# ---------------------------------------------------------------- 후처리(코어 없음 최선 5덱): 컨트롤(+큐브) → 옵션 → (컨트롤 다시)

def cube_keys(squad: Sequence[str]) -> dict:
    inv = CB.full_inventory()
    return {(w, "cube"): cv for w in squad if (cv := CB.cube_variants(w, inv, start=CB.DEFAULT_CUBE))}


def sim_extra(o: Any) -> Any:
    return {**o, "sim": {**(o.get("sim") or {}), **SIM_EXTRA}} if SIM_EXTRA else o  # 비면 같은 객체(옛 동작 그대로)


def control_space(s: int, squad: Sequence[str], per: Mapping[str, Mapping[str, int]] | None) -> Any:
    """판의 후처리 메뉴(+ 큐브). per가 있으면 바탕에 장비 옵션 배분을 얹는다."""
    if ARM == "A":
        fn = (lambda q: {**r1.l_variants(q), **cube_keys(q)}) if CUBE else r1.l_variants
        base = sim_extra(r0.opts(s, True))
        return M.Space(list(squad), variants_fn=fn, base=run35.with_alloc(base, per) if per else base)
    fn = (lambda q: {**r3c.full_variants(q), **cube_keys(q)}) if CUBE else r3c.full_variants
    base = sim_extra(r1.p_base(s, squad))
    return M.Space(list(squad), variants_fn=fn, apply_fn=r3c.full_apply, base=run35.with_alloc(base, per) if per else base)


def _run(job_id: str, squad: Sequence[str], sp: Any, start: tuple[int, ...], ev: Any, out: Path, tag: str) -> Any:
    log = out / f"{job_id}.{tag}.jsonl"
    run = M.Run({"id": job_id, "squad": list(squad)}, sp, ev, method=f"{tag}:{SPEC}", budget=POST_BUDGET, out=log)
    try:
        r3c.m3_from(run, start, kick=2, seed=M.job_seed(job_id + tag, SPEC))
    finally:
        run.close()
    run35.gz_log(log)
    return run


def post_deck(s: int, i: int, squad: Sequence[str], win: str | None, pre: float, ev: Any) -> dict[str, Any]:
    out_dir = sdir(s) / POST_NAME
    f = out_dir / f"S{s}-{i}.json"
    if f.exists():
        return jload(f)
    out_dir.mkdir(parents=True, exist_ok=True)
    jid = f"S{s}-{i}"
    n0, t0 = ev.sim_count, time.time()
    e0 = run35.e0_all(squad)
    sp1 = control_space(s, squad, None)
    st1 = r3c.start_sel(sp1, squad, win) if ARM != "A" else sp1.empty()
    run1 = _run(jid, squad, sp1, st1, ev, out_dir, "C")
    labels1 = sp1.labels(run1.best_sel)
    sp1e = control_space(s, squad, e0)
    o = run35.osearch(jid, squad, sp1e.options(sp1e.from_labels(labels1)), ev, out_dir)
    al = {n: run35.parse(lb) for n, lb in o["alloc"].items()}
    rec = {"id": jid, "season": s, "squad": list(squad), "win": win, "pre": pre, "ctrl": run1.best / E8, "ctrl_variants": list(labels1),
           "E0": o["v_E0"], "O": o["v_O"], "alloc": o["alloc"], "screen": o["screen"], "top": o["top"]}
    final, final_labels = o["v_O"], list(labels1)
    if C2:
        sp2 = control_space(s, squad, al)
        run2 = _run(jid, squad, sp2, sp2.from_labels(labels1), ev, out_dir, "C2")
        rec.update(C2=run2.best / E8, ctrl2_variants=list(sp2.labels(run2.best_sel)))
        if run2.best / E8 > final:
            final, final_labels = run2.best / E8, list(sp2.labels(run2.best_sel))
    rec.update(final=final, final_variants=final_labels, sims=ev.sim_count - n0, seconds=round(time.time() - t0, 1))
    jdump(f, rec)
    return rec


def post_targets(s: int, ev: Any) -> list[tuple[tuple, str | None, float]]:
    """후처리할 5덱: final5 = 코어 없음 book의 최선 5덱. reps = 지도 대표 덱 전부에 옵션 탐색(기본 컨트롤) → 그 값으로 다시 묶은 5덱."""
    bk, win = book_win(s, "nocore")
    if OPT == "final5":
        _, ch = R9.pack_vals(bk)
        return [(tuple(q), win.get(frozenset(q)), v) for v, q in ch]
    reps = run31.rep_decks(run31.class_map(s, "nocore", ARM))
    f = sdir(s) / "post_reps.json"
    got = jload(f) or {}
    for q in reps:
        key = ",".join(q)
        if key in got:
            continue
        w = win.get(frozenset(q))
        base = (r0.opts(s, True) if ARM == "A" else
                (r3.probe_patch(s, q, None) if w is None else dict(dict(r3c.probes_c(s, q))[w])))
        o = run35.osearch(f"S{s}-rep-{len(got)}", q, run35.with_alloc(base, run35.e0_all(q)), ev, sdir(s) / "post")
        got[key] = {"v_O": o["v_O"], "v_E0": o["v_E0"], "alloc": o["alloc"], "win": w, "pre": bk[frozenset(q)][0]}
        jdump(f, got)
    vals = {frozenset(k.split(",")): (x["v_O"], tuple(k.split(","))) for k, x in got.items() if x["v_O"] is not None}
    _, ch = R9.pack_vals(vals)
    return [(tuple(q), got[",".join(q)]["win"], got[",".join(q)]["pre"]) for _, q in ch]


def part_post(s: int, ev: Any, workers: int = 2) -> dict[str, Any]:
    targets = post_targets(s, ev)
    with ThreadPoolExecutor(workers) as pool:
        recs = list(pool.map(lambda x: post_deck(s, x[0], x[1][0], x[1][1], x[1][2], ev), enumerate(targets)))
    out = {"season": s, "arm": ARM, "opt": OPT, "c2": C2, "cube": CUBE, "decks": recs,
           "total": {k: sum(r[k] for r in recs) for k in ("pre", "ctrl", "E0", "O", "final")}}
    jdump(sdir(s) / f"{POST_NAME}.json", out)
    return {"total": out["total"]}


def cmd_run(a: argparse.Namespace) -> int:
    need_config()
    from nikke_opt.evaluator import make_evaluator
    parts = PARTS if a.part == "all" else tuple(a.part.split(","))
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        ver = f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"
        for s in [int(x) for x in str(a.season).split(",")]:
            sdir(s).mkdir(parents=True, exist_ok=True)
            for part in parts:
                pf = run31.part_file(s, part)
                if pf.exists():
                    continue
                need = {"end": ["B_s0", "B_s1"], "core30": ["end"], "members": ["core30"], "rankers": [], "post": ["end"]}.get(part, [])
                miss = [x for x in need if not run31.part_file(s, x).exists()]
                if miss:
                    raise RuntimeError(f"S{s} {part}: 먼저 {miss}")
                n0 = ev.sim_count
                if part.startswith("B_s"):
                    out = part_B(s, int(part[3:]), ev)
                else:
                    out = {"end": part_end, "core30": part_core30, "members": part_members, "rankers": part_rankers,
                           "post": lambda s_, e_: part_post(s_, e_, a.workers)}[part](s, ev)
                out.update(season=s, part=part, arm=ARM, evaluator=ver)
                out.setdefault("sims", ev.sim_count - n0)
                jdump(pf, out)
                print(json.dumps({k: v for k, v in out.items() if k not in ("history",)}, ensure_ascii=False), flush=True)
    return 0


# ---------------------------------------------------------------- 분석(시뮬 0)

def cmd_analyze(a: argparse.Namespace) -> int:
    need_config()
    rc = run31.cmd_analyze(argparse.Namespace(season=a.season))
    an = jload(HERE / "analysis.json")
    an["procedure"] = {"arm": ARM, "opt": OPT, "c2": C2, "cube": CUBE, "post_budget": POST_BUDGET}
    for row in an["rows"]:
        p = jload(sdir(row["season"]) / "post.json")
        if p:
            row["post"] = p
        rp = jload(sdir(row["season"]) / "rpost.json")     # 랭커 덱 후처리(rpost36.py)
        if rp:
            row["rpost"] = rp
    jdump(HERE / "analysis.json", an)
    return rc


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--season", required=True)
    r.add_argument("--part", required=True, help=f"{PARTS} 중 쉼표로 여럿 · all")
    r.add_argument("--jobs", type=int, default=4)
    r.add_argument("--workers", type=int, default=2)
    n = sub.add_parser("analyze")
    n.add_argument("--season", default=None)
    a = p.parse_args()
    return {"run": cmd_run, "analyze": cmd_analyze}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
