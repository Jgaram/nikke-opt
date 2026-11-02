"""실험 32 R1 — 원시 입력 + 일반 사건이 사람 규칙만큼 표현하나(README §R1 사전 등록).

    python -I experiments/32_primitive_control/r1.py plan          # 덱 고르기 → r1/decks.json (시뮬 0, 결과 전에 커밋)
    python -I experiments/32_primitive_control/r1.py menu [n]      # 덱 n번의 L · P 메뉴 크기 · 선택지 출력
    source .cache/evaluators.env && python -I experiments/32_primitive_control/r1.py run   # L · P 각 400평가
    python -I experiments/32_primitive_control/r1.py analyze       # → r1.json · r1.md

판(둘 다 실험 7 M3:k2 — 좌표 하강 + 키 2개 킥, 예산 400평가, 시드 = 덱 id):
  L  바탕 = 시즌 options(레이어 켬), 메뉴 = 실험 6 `menu.variants`(지금 메뉴; 패턴은 지금 카탈로그에 있는 이름만)
  P  바탕 = 시즌 options + operation.auto(레이어 끔), 메뉴 = 아래 `prim_variants`(니케 이름 · 카탈로그 · 정책 이름 없음)
"""

from __future__ import annotations

import copy
import gzip
import importlib.util
import json
import math
import statistics as st
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXP = ROOT / "experiments"
sys.path[:0] = [str(ROOT), str(EXP / "31_recent_seasons"), str(EXP / "06_control_menu"), str(HERE)]
import run31  # noqa: E402
import menu as menu6  # noqa: E402
from menu import MenuConflict  # noqa: E402
import r0  # noqa: E402


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


M = sys.modules.get("methods") or _load("methods", EXP / "07_control_search" / "methods.py")
OUT = HERE / "r1"
BUDGET = 400
SPEC = "M3:k2"
CYCLES = 40                      # 사이클 번호 1..40(180초에 풀버스트는 많아야 15번 남짓)
N_T, N_G, N_D = 14, 10, 10       # 덱 묶음 크기(사전 등록)
REF_NAME = "미란다"               # 보조 집계: 미란다 덱(실전 대비 차이가 육성 의존 — 사용자 2026-11-02)을 뺀 판단도 함께 낸다
PASS_RATIO, PASS_SHARE = 0.99, 0.90


# ---------------------------------------------------------------- 덱 고르기(시뮬 0)

def nikke_info() -> dict[str, Any]:
    return menu6.info()["nikke"]


def layer_targets() -> list[str]:
    return sorted(n for n, v in nikke_info().items() if v["layer"])


def stage_of(n: str) -> str:
    return str(nikke_info()[n]["burst_stage"] or "")


def same_stage_two(q: Sequence[str]) -> bool:
    for s in ("1", "2"):
        if sum(stage_of(n) == s for n in q) >= 2:
            return True
    return False


def cmd_plan() -> int:
    old = json.loads(gzip.open(HERE / "diag" / "rotate10.json.gz").read())
    res = json.loads((HERE / "r0.json").read_text(encoding="utf-8"))
    r0rows = []                                  # (season, deck tuple, L, A, old)
    for s in run31.SEASONS:
        V = json.loads((OUT.parent / "r0" / f"S{s}.json").read_text(encoding="utf-8"))["vals"]
        ov = old[str(s)]["vals"]
        for k, v in V.items():
            if v["L"] and v["A"]:
                r0rows.append((s, tuple(k.split(",")), v["L"], v["A"], (ov.get(k) or {}).get("base")))
    chosen: list[dict[str, Any]] = []
    seen: set[frozenset] = set()

    def add(group: str, s: int, q: Sequence[str], why: str, judged: bool = True) -> bool:
        fs = frozenset(q)
        if fs in seen or any(n not in nikke_info() for n in q):
            return False
        seen.add(fs)
        chosen.append({"id": f"r1-{len(chosen):02d}", "group": group, "season": s, "squad": list(q), "why": why,
                       "judged": judged, "miranda": REF_NAME in q})
        return True

    # R: R0 실전 대비 크게 낮은 덱(미란다 덱은 참고)
    for r in res["seasons"]:
        for x in r["low"]:
            add("R", r["season"], x["deck"].split(","), f"R0 낮음 {x['under']:.2f}배")
    # T: 레이어 대상 니케마다 R0에서 |log(L/A)|가 가장 큰 덱
    exp16 = exp16_decks()
    for n in layer_targets():
        cands = sorted((r for r in r0rows if n in r[1]), key=lambda r: -abs(math.log(r[2] / r[3])))
        ok = any(add("T", s, q, f"레이어 대상 {n}, L/A {L / A:.3f}") for s, q, L, A, _ in cands[:1])
        if not ok:
            for s, q, L, A, _ in cands[1:]:
                if add("T", s, q, f"레이어 대상 {n}, L/A {L / A:.3f}"):
                    ok = True
                    break
        if not ok:
            for g, q in exp16:
                if n in q and add("T", 42, q, f"레이어 대상 {n}(R0에 없음), 실험 16 이득 {g:.3f}"):
                    break
    # G: 실험 16 이득 상위(S42 options)
    k = 0
    for g, q in exp16:
        if k >= N_G:
            break
        if add("G", 42, q, f"실험 16 이득 {g:.3f}"):
            k += 1
    # D: 같은 단계(1 · 2) 후보가 둘 이상인 R0 덱 중 새 규칙으로 가장 많이 오른 덱
    d = sorted((r for r in r0rows if same_stage_two(r[1]) and r[4]), key=lambda r: -(r[2] / r[4]))
    k = 0
    for s, q, L, A, ob in d:
        if k >= N_D:
            break
        if add("D", s, q, f"같은 단계 둘, 새/옛 {L / ob:.2f}"):
            k += 1
    OUT.mkdir(exist_ok=True)
    (OUT / "decks.json").write_text(json.dumps(chosen, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for c in chosen:
        print(c["id"], c["group"], f"S{c['season']}", "판단" if c["judged"] else "참고", c["why"], "|", " · ".join(c["squad"]))
    print(len(chosen), "덱, 판단", sum(c["judged"] for c in chosen))
    return 0


def exp16_decks() -> list[tuple[float, list[str]]]:
    """실험 16 구성(M3:k2 200평가)의 이득 best/base 내림차순 — S42 풀에 모두 있는 덱만."""
    pool = set(run31.season(42)["pool"])
    out = []
    for f in sorted((EXP / "16_control_miss" / "run_log" / "jobs").glob("*.json")):
        j = json.loads(f.read_text(encoding="utf-8"))
        if j.get("best_damage") and j.get("base_damage") and set(j["squad"]) <= pool:
            out.append((j["best_damage"] / j["base_damage"], list(j["squad"])))
    out.sort(key=lambda x: -x[0])
    return out


# ---------------------------------------------------------------- 메뉴

def registered_patterns() -> dict[str, list[str]]:
    """지금 평가기(원본 67835ca) `char_defaults.json`의 `_burst_patterns` 이름."""
    p = Path("/home/user/nikke-calc-rs/upstream/data/char_defaults.json")
    d = json.loads(p.read_text(encoding="utf-8"))
    return {k: list((v.get("_burst_patterns") or {}) if isinstance(v, dict) else {}) for k, v in d.items()}


def l_variants(squad: Sequence[str]) -> dict:
    """실험 6 메뉴. 지금 카탈로그에 없는 패턴 이름은 뺀다(요청 오류가 된다)."""
    reg = registered_patterns()
    out = {}
    for key, vs in menu6.variants(squad).items():
        who = key[0]
        keep = [v for v in vs if not (v["axis"] == "burst" and ":pattern=" in v["label"]
                                      and v["label"].split(":pattern=")[1] not in reg.get(who, []))]
        if keep:
            out[key] = keep
    return out


def _v(who, axis, name, patch):
    return {"nikke": who, "axis": axis, "label": f"{who if who is not None else 'squad'}:{axis}:{name}", "patch": patch}


def _c(who, control):
    return {"chars": {who: {"control": control}}}


TAP = {"window": "always", "mode": "tap", "rate": 3.6, "release": 0.03}
TAP_CHARGE = {"window": "burst_charge", "mode": "tap", "rate": 3.6, "release": 0.03}
HOLD_FB = {"window": "own_full_burst", "mode": "hold", "lead": 0.5}
HOLD_CHAIN = {"window": "burst_chain", "mode": "hold_until_close"}
HOLD_JUDGE = {"window": "after_own_fb", "mode": "hold_judge", "lead": 0.1}
# 엄폐 진입 = 앵커 + offset(− reload_total). 정책 이름(A · B · C)은 쓰지 않는다 — 같은 시각을 앵커로 적는다
COVER_AT = (
    ("fb_end-0.3", {"anchor": "fb_end", "offset": -0.3}),
    ("next_fb+0.1-rl", {"anchor": "next_fb_start", "offset": 0.1, "minus": "reload_total"}),
    ("next_fb+0.5-rl", {"anchor": "next_fb_start", "offset": 0.5, "minus": "reload_total"}),
    ("fb_end-0.1-rl", {"anchor": "fb_end", "offset": -0.1, "minus": "reload_total"}),
    ("fb_end-0.5-rl", {"anchor": "fb_end", "offset": -0.5, "minus": "reload_total"}),
    ("fb_end-0.1-rl_dry", {"anchor": "fb_end", "offset": -0.1, "minus": "reload_total", "if_dry": True}),
)


def prim_variants(squad: Sequence[str]) -> dict:
    """원시 입력 메뉴. 니케 속성(무기 차지 · 입력 방식 · 버스트 단계 · charge_hold 유무)만 보고 이름 · 카탈로그 · 레이어는 보지 않는다.

    키: 니케마다 click · cover_at(장전 엄폐 진입 앵커) · cover_fb(본인 풀버스트 엄폐) · cancel(탄충 취소) · burst_t(딜레이 · 쿨 대기),
    단계마다(후보 둘 이상) burst_who(이 단계를 사이클마다 누가 누르나), 스쿼드 camera(focus).
    """
    info = nikke_info()
    out: dict = {}
    for who in squad:
        n = info[who]
        if n["charge"] and n["input"] == "UP":
            vs = []
            if not n["full_charge_only"]:
                vs += [_v(who, "click", "tap", _c(who, {"click": [dict(TAP)]})),
                       _v(who, "click", "tap@charge", _c(who, {"click": [dict(TAP_CHARGE)]}))]
            vs.append(_v(who, "click", "hold@ownfb", _c(who, {"click": [dict(HOLD_FB)]})))
            if not n["full_charge_only"]:
                vs.append(_v(who, "click", "hold@ownfb+tap", _c(who, {"click": [dict(HOLD_FB), dict(TAP)]})))
            vs.append(_v(who, "click", "hold@chain", _c(who, {"click": [dict(HOLD_CHAIN)]})))
            if n["charge_hold"]:
                vs.append(_v(who, "click", "judge@ownfb", _c(who, {"click": [dict(HOLD_JUDGE)]})))
            out[(who, "click")] = vs
        out[(who, "cover_at")] = [_v(who, "cover_at", nm, _c(who, {"reload": dict(r)})) for nm, r in COVER_AT]
        out[(who, "cover_fb")] = [_v(who, "cover_fb", "on", _c(who, {"cover": {"policy": "own_full_burst"}}))]
        out[(who, "cancel")] = [_v(who, "cancel", "on", _c(who, {"reload": {"cancel_on_full": True}}))]
        if n["burst_stage"]:
            out[(who, "burst_t")] = [_v(who, "burst_t", f"delay{d:g}", _c(who, {"burst": {"delay": d}})) for d in (1.0, 2.0)] + \
                                    [_v(who, "burst_t", "wait2", _c(who, {"burst": {"wait_own_cooldown": 2.0}}))]
    for s in ("1", "2", "3"):
        cand = [w for w in squad if str(info[w]["burst_stage"]) == s]
        if len(cand) < 2:
            continue
        allc = list(range(1, CYCLES + 1))
        vs = []
        for i, w in enumerate(cand):                    # i번째 후보 우선(매 사이클 순위 0, 쿨이면 다음 후보)
            vs.append(_v(None, f"burst_who{s}", f"first={i + 1}", {"chars": {w: {"control": {"burst": {"pattern": allc}}}}}))
        if len(cand) == 2:                              # 번갈아: 홀수 사이클 i번째, 짝수 사이클 다른 쪽
            odd, even = allc[0::2], allc[1::2]
            for i in (0, 1):
                a, b = cand[i], cand[1 - i]
                vs.append(_v(None, f"burst_who{s}", f"alt={i + 1}",
                             {"chars": {a: {"control": {"burst": {"pattern": odd}}}, b: {"control": {"burst": {"pattern": even}}}}}))
        for i, w in enumerate(cand):                    # i번째 후보는 쓰지 않음
            vs.append(_v(None, f"burst_who{s}", f"none={i + 1}", {"operation": {"no_burst": w}}))
        out[(None, f"burst_who{s}")] = vs
    cams = [_v(None, "camera", f"slot{i + 1}", {"operation": {"camera": w}}) for i, w in enumerate(squad) if info[w]["charge"]]
    if cams:
        out[(None, "camera")] = cams
    return out


def prim_apply(options: Mapping[str, Any], chosen: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """menu6.apply + 원시 메뉴 조립 규칙: `no_burst`는 한 명만, 홀드(own_full_burst)와 본인 풀버스트 엄폐는 같은 니케에 같이 못 건다."""
    nb = [v for v in chosen if "no_burst" in v["patch"].get("operation", {})]
    if len(nb) > 1:
        raise MenuConflict("no_burst는 한 명만")
    by: dict[str, dict[str, Any]] = {}
    for v in chosen:
        if v["nikke"]:
            by.setdefault(v["nikke"], {})[v["axis"]] = v
    for who, ax in by.items():
        if "click" in ax and "cover_fb" in ax and menu6._holds_own_fb(ax["click"]["patch"]["chars"][who]["control"]):
            raise MenuConflict(f"{who}: 같은 창에 홀드와 엄폐")
    # 같은 니케의 burst 칸(패턴 · 딜레이)은 deep_merge로 합쳐진다. 패턴끼리는 단계 키가 하나라 겹치지 않는다
    seen = set()
    for v in chosen:
        k = (v["nikke"], v["axis"])
        if k in seen:
            raise ValueError(f"같은 키 둘: {k}")
        seen.add(k)
    out = menu6.deep_merge(options, {})
    for v in chosen:
        out = menu6.deep_merge(out, v["patch"])
    return out


def space(deck: Mapping[str, Any], arm: str) -> Any:
    if arm == "L":
        return M.Space(deck["squad"], variants_fn=l_variants, base=r0.opts(deck["season"], True))
    return M.Space(deck["squad"], variants_fn=prim_variants, apply_fn=prim_apply, base=r0.opts(deck["season"], False))


def cmd_menu(i: int) -> int:
    decks = json.loads((OUT / "decks.json").read_text(encoding="utf-8"))
    d = decks[i]
    for arm in ("L", "P"):
        sp = space(d, arm)
        print(arm, "키", sp.K, "선택지", sp.nv, "조립 불가 쌍", len(sp.conflict_pairs))
        for k, vs in sp.menu.items():
            print("  ", k, [v["label"].split(":", 2)[2] for v in vs])
    return 0


# ---------------------------------------------------------------- 실행

def run_one(d: Mapping[str, Any], arm: str, ev: Any) -> dict[str, Any]:
    f = OUT / "jobs" / f"{d['id']}_{arm}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    f.parent.mkdir(parents=True, exist_ok=True)
    sp = space(d, arm)
    log = OUT / "logs" / f"{d['id']}_{arm}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    comp = {"id": d["id"], "squad": list(d["squad"])}
    run = M.Run(comp, sp, ev, method=f"{arm}:{SPEC}", budget=BUDGET, out=log)
    t0 = time.time()
    try:
        M.m3(run, kick=2, seed=M.job_seed(d["id"], SPEC))
    finally:
        run.close()
    raw = log.read_bytes()
    with gzip.open(log.with_suffix(".jsonl.gz"), "wb") as g:
        g.write(raw)
    log.unlink()
    errs = sum(1 for ln in raw.decode().splitlines() if json.loads(ln)["error"])
    out = {"id": d["id"], "arm": arm, "evals": run.used, "errors": errs, "best": run.best, "base": run.base_damage,
           "best_variants": list(sp.labels(run.best_sel)), "keys": sp.K, "options": sp.nv,
           "exhausted": run.exhausted, "seconds": round(time.time() - t0, 1)}
    f.write_text(json.dumps(out, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def cmd_run(workers: int = 4) -> int:
    from nikke_opt.evaluator import make_evaluator
    decks = json.loads((OUT / "decks.json").read_text(encoding="utf-8"))
    lock = threading.Lock()
    t0 = time.time()
    with make_evaluator("rust", jobs=4, cache=False) as ev:
        def job(x):
            d, arm = x
            r = run_one(d, arm, ev)
            with lock:
                print(json.dumps({"id": d["id"], "arm": arm, "evals": r["evals"], "errors": r["errors"],
                                  "gain": None if not r["base"] else round(r["best"] / r["base"], 4),
                                  "sims": ev.sim_count, "t": round(time.time() - t0)}, ensure_ascii=False), flush=True)
            return r
        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(job, [(d, a) for d in decks for a in ("L", "P")]))
        (OUT / "run_meta.json").write_text(json.dumps({"sims": ev.sim_count, "seconds": round(time.time() - t0, 1),
                                                       "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"},
                                                      ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


# ---------------------------------------------------------------- 분석

def best_at(rows, budget):
    b = None
    for r in rows:
        if r["step"] >= budget:
            break
        if r["total_damage"] is not None and (b is None or r["total_damage"] > b):
            b = r["total_damage"]
    return b


def cmd_analyze() -> int:
    decks = json.loads((OUT / "decks.json").read_text(encoding="utf-8"))
    rows = []
    for d in decks:
        J = {a: json.loads((OUT / "jobs" / f"{d['id']}_{a}.json").read_text(encoding="utf-8")) for a in ("L", "P")}
        logs = {a: [json.loads(x) for x in gzip.open(OUT / "logs" / f"{d['id']}_{a}.jsonl.gz", "rt", encoding="utf-8") if x.strip()]
                for a in ("L", "P")}
        r = {"id": d["id"], "group": d["group"], "season": d["season"], "squad": d["squad"], "judged": d["judged"],
             "L_base": J["L"]["base"] / 1e8, "A_base": J["P"]["base"] / 1e8, "L": J["L"]["best"] / 1e8, "P": J["P"]["best"] / 1e8,
             "P_over_L": J["P"]["best"] / J["L"]["best"],
             "P200_over_L200": best_at(logs["P"], 200) / best_at(logs["L"], 200),
             "L_evals": J["L"]["evals"], "P_evals": J["P"]["evals"], "errors": J["L"]["errors"] + J["P"]["errors"],
             "L_vars": J["L"]["best_variants"], "P_vars": J["P"]["best_variants"],
             "keys": {"L": J["L"]["keys"], "P": J["P"]["keys"]}, "opts": {"L": J["L"]["options"], "P": J["P"]["options"]}}
        rows.append(r)
    judged = [r for r in rows if r["judged"]]
    ok = sum(r["P_over_L"] >= PASS_RATIO for r in judged)
    share = ok / len(judged)
    nm = [r for r in judged if REF_NAME not in r["squad"]]
    share_nm = sum(r["P_over_L"] >= PASS_RATIO for r in nm) / len(nm)
    axes = {"L": {}, "P": {}}
    for r in rows:
        for a in ("L", "P"):
            for lb in r[f"{a}_vars"]:
                ax = lb.split(":")[1] if lb.count(":") >= 2 else lb
                axes[a][ax] = axes[a].get(ax, 0) + 1
    summ = {"decks": len(rows), "judged": len(judged), "pass": ok, "share": share,
            "verdict": "원시 표현으로 충분" if share >= PASS_SHARE else "빠진 표현 찾기",
            "share_without_miranda": share_nm, "judged_without_miranda": len(nm),
            "P_over_L": {"median": st.median(r["P_over_L"] for r in judged), "min": min(r["P_over_L"] for r in judged),
                         "max": max(r["P_over_L"] for r in judged)},
            "P200_over_L200_median": st.median(r["P200_over_L200"] for r in judged),
            "gain_L_median": st.median(r["L"] / r["L_base"] for r in rows), "gain_P_over_A_median": st.median(r["P"] / r["A_base"] for r in rows),
            "evals": sum(r["L_evals"] + r["P_evals"] for r in rows), "errors": sum(r["errors"] for r in rows), "axes": axes}
    meta = OUT / "run_meta.json"
    if meta.exists():
        summ["run"] = json.loads(meta.read_text(encoding="utf-8"))
    (HERE / "r1.json").write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    md = ["| 덱 | 묶음 | 시즌 | 판단 | L 출발 → L | A 출발 → P | P/L | P/L(200) | 덱 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["P_over_L"]):
        md.append(f"| {r['id']} | {r['group']} | S{r['season']} | {'○' if r['judged'] else '참고'} | {r['L_base']:.1f} → {r['L']:.1f} | "
                  f"{r['A_base']:.1f} → {r['P']:.1f} | {r['P_over_L']:.3f} | {r['P200_over_L200']:.3f} | {' · '.join(r['squad'])} |")
    (HERE / "r1.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "plan":
        sys.exit(cmd_plan())
    if cmd == "menu":
        sys.exit(cmd_menu(int(sys.argv[2]) if len(sys.argv) > 2 else 0))
    if cmd == "run":
        sys.exit(cmd_run())
    if cmd == "analyze":
        sys.exit(cmd_analyze())
    print(__doc__)
    sys.exit(2)
