"""실험 10 분석 — README §잴 것 · §판단 기준 · §풀 누출의 처리.

    python experiments/10_rankerless_start/analyze10.py --runs <val P60 dir> [--p177 <val P177 dir>] [--dev-runs <dev dir>]
        [--precompute <precompute_P*.json dir>] [--exp9-log experiments/09_account_pack/run_log]
        --out experiments/10_rankerless_start/results.md [--json <요약.json>] [--meta <실행 메모.json>]

실행 요약 JSON의 형식은 SESSIONS.md 「인터페이스 — 실행 요약 JSON」을 따른다. 값은 억 단위, 후처리 전.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

METHODS = ("K", "K+E", "R", "R+E", "G", "G+E", "P", "P+E")
STARTS = ("K", "R", "G", "P")
RANKERLESS = ("R", "R+E", "G", "G+E", "P", "P+E")
NO_PRECOMPUTE = ("R", "R+E", "G", "G+E")  # 동점 깨기 (1): 사전 계산이 없는 R · G 계열을 P보다 먼저
BUDGETS = (300, 800, 2000)
JUDGE_BUDGETS = (800, 2000)  # 질문 1의 판단 예산. 300은 따로 적는다
TOP = 2000
VAL_SCENARIOS = tuple(f"v{i}" for i in range(1, 9))
MAIN_POOL, LEAK_POOL = 60, 177

# 판단 기준 (사전 등록 초안 — 관리자가 확정 때 고친다)
MARGIN = 0.005  # 「낫다」 · 「못하다」의 중앙 폭
SHARE = 0.75  # 시나리오 수의 이 몫 이상(8개면 6개)
NONINF_MEDIAN = -0.005  # 「못지않다」: 중앙 ≥ 이 값
NONINF_LOW = -0.03  # 「못지않다」: H가 이 값보다 낮은 시나리오가
NONINF_MAX_LOW = 1  # 이 개수 이하
EPS = 1e-12  # 경계값의 부동소수 오차(예: 99.5 / 100 − 1)를 경계 안으로 본다
PACK_TOL = 1e-9  # 곡선에서 목표값에 「닿았다」의 허용 오차(억)

EXP9_LOG = Path(__file__).resolve().parent.parent / "09_account_pack" / "run_log"

Key = tuple[str, int, str, int]  # (시나리오, 풀, 기법, 예산)


# ---------------------------------------------------------------- 읽기

def _warn(msg: str) -> None:
    print(msg, file=sys.stderr)


def load_dir(d: Path | None) -> dict[Key, dict[str, Any]]:
    """실행 요약 `*.json`을 (시나리오, 풀, 기법, 예산)으로 읽는다. `precompute_*.json`은 건너뛴다."""
    out: dict[Key, dict[str, Any]] = {}
    if d is None:
        return out
    if not d.is_dir():
        _warn(f"실행 폴더 없음: {d}")
        return out
    for p in sorted(d.glob("*.json")):
        if p.name.startswith("precompute_"):
            continue
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
            k = (str(r["scenario"]), int(r["pool"]), str(r["method"]), int(r["budget"]))
            r["final"]["total"]
        except (OSError, ValueError, KeyError, TypeError) as e:
            _warn(f"읽을 수 없는 요약 건너뜀: {p.name} ({e!r})")
            continue
        if k in out:
            _warn(f"같은 실행이 두 번: {k} — 나중 파일({p.name})을 쓴다")
        out[k] = r
    return out


def load_precompute(dirs: Iterable[Path | None]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for d in dirs:
        if d is None or not d.is_dir():
            continue
        for p in sorted(d.glob("precompute_P*.json")):
            try:
                r = json.loads(p.read_text(encoding="utf-8"))
                out.setdefault(int(r.get("pool") or p.stem.split("_P")[-1]), r)
            except (OSError, ValueError, TypeError) as e:
                _warn(f"읽을 수 없는 사전 계산 건너뜀: {p.name} ({e!r})")
    return out


def load_exp9(path: Path | None) -> list[dict[str, Any]]:
    """실험 9 검증 요약(`val_summary.jsonl`). 폴더를 주면 그 안의 파일을 읽는다."""
    if path is None:
        return []
    f = path / "val_summary.jsonl" if path.is_dir() else path
    if not f.is_file():
        _warn(f"실험 9 기록 없음: {f} — 알려진 최고는 실험 10 실행만으로 낸다")
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


# ---------------------------------------------------------------- 판단 규칙

def med(xs: Iterable[float]) -> float | None:
    xs = list(xs)
    return statistics.median(xs) if xs else None


def need(n: int) -> int:
    return math.ceil(SHARE * n)


def better(gs: Sequence[float]) -> bool:
    return bool(gs) and statistics.median(gs) >= MARGIN - EPS and sum(g > 0 for g in gs) >= need(len(gs))


def worse(gs: Sequence[float]) -> bool:
    return bool(gs) and statistics.median(gs) <= -MARGIN + EPS and sum(g < 0 for g in gs) >= need(len(gs))


def n_low(gs: Sequence[float]) -> int:
    return sum(g < NONINF_LOW - EPS for g in gs)


def noninferior(gs: Sequence[float]) -> bool:
    return bool(gs) and statistics.median(gs) >= NONINF_MEDIAN - EPS and n_low(gs) <= NONINF_MAX_LOW


def rel(T: Mapping[Key, float], scen: Sequence[str], pool: int, m: str, base: str, b: int) -> list[float]:
    """T(m) / T(base) − 1, 같은 풀 · 예산 · 시나리오. 둘 다 있는 시나리오만."""
    return [T[(s, pool, m, b)] / T[(s, pool, base, b)] - 1 for s in scen
            if (s, pool, m, b) in T and (s, pool, base, b) in T and T[(s, pool, base, b)]]


def gstats(gs: Sequence[float]) -> dict[str, Any]:
    return {"n": len(gs), "median": med(gs), "pos": sum(g > 0 for g in gs), "neg": sum(g < 0 for g in gs),
            "min": min(gs) if gs else None, "max": max(gs) if gs else None, "low": n_low(gs),
            "better": better(gs), "worse": worse(gs), "noninf": noninferior(gs)}


def pair_of(m: str) -> str:
    return m[:-2] if m.endswith("+E") else m + "+E"


def judge1(T: Mapping[Key, float], scen: Sequence[str], pool: int = MAIN_POOL) -> dict[str, Any]:
    """질문 1 — 랭커 없는 기법(R · G · P와 각 +E)이 K에 못지않은가."""
    g = {m: {b: rel(T, scen, pool, m, "K", b) for b in BUDGETS} for m in RANKERLESS}
    md = {m: {b: med(g[m][b]) for b in BUDGETS} for m in RANKERLESS}
    ninf = {m: [b for b in BUDGETS if noninferior(g[m][b])] for m in RANKERLESS}
    wins = {m: [b for b in BUDGETS if better(g[m][b])] for m in RANKERLESS}
    loses = {m: [b for b in BUDGETS if worse(g[m][b])] for m in RANKERLESS}
    both = [m for m in RANKERLESS if all(b in ninf[m] for b in JUDGE_BUDGETS)]
    only2000 = [m for m in RANKERLESS if TOP in ninf[m] and m not in both]
    pick, names = None, []
    if both:
        # (1) R · G 계열 먼저 (2) 2,000의 H 중앙이 큰 쪽 (3) 800의 H 중앙. 모두 같으면 METHODS 순서의 앞
        pick = max(both, key=lambda m: (m in NO_PRECOMPUTE, md[m][TOP], md[m][800]))
        line, names = 1, both
    elif only2000:
        line, names = 2, only2000
    else:
        line = 3
    if pick is not None:
        selected = pick
    else:
        cand = [m for m in RANKERLESS if md[m][TOP] is not None]
        selected = max(cand, key=lambda m: md[m][TOP]) if cand else None
    small = {"noninf": [m for m in RANKERLESS if 300 in ninf[m]], "better": [m for m in RANKERLESS if 300 in wins[m]],
             "worse": [m for m in RANKERLESS if 300 in loses[m]]}
    return {"line": line, "pick": pick, "names": names, "selected": selected,
            "pair": pair_of(selected) if selected else None,
            "noninf": ninf, "wins": wins, "loses": loses, "median": md, "small_budget": small}


def judge2(T: Mapping[Key, float], scen: Sequence[str], pool: int = MAIN_POOL) -> dict[str, Any]:
    """질문 2 — 탈출 E 채택: X+E가 X보다 2,000에서 「낫다」이고 800에서 「못하다」가 아니다. 판단 줄은 K."""
    per = {}
    for x in STARTS:
        g8, g20 = rel(T, scen, pool, x + "+E", x, 800), rel(T, scen, pool, x + "+E", x, TOP)
        per[x] = {"adopt": better(g20) and not worse(g8), "better2000": better(g20), "worse800": worse(g8),
                  "median800": med(g8), "median2000": med(g20), "n800": len(g8), "n2000": len(g20)}
    return {"adopt": per["K"]["adopt"], "per_start": per}


LEAK_SAME = "풀 누출을 걷어도 결론이 같다"
LEAK_ONLY = "선별된 풀에서만"


def leak_check(T: Mapping[Key, float], scen: Sequence[str], selected: str | None) -> dict[str, Any] | None:
    """P177 확인(예산 2,000): 고른 기법 · 그 탈출 짝 · K+E의 H(K(177) 대비)와, 같은 기법의 P177 / P60."""
    if not any(k[1] == LEAK_POOL for k in T):
        return None
    methods = [m for m in dict.fromkeys([selected, pair_of(selected) if selected else None, "K", "K+E"]) if m]
    rows = {m: gstats(rel(T, scen, LEAK_POOL, m, "K", TOP)) for m in methods if m != "K"}
    ratio = {s: {m: T[(s, LEAK_POOL, m, TOP)] / T[(s, MAIN_POOL, m, TOP)]
                 for m in methods if (s, LEAK_POOL, m, TOP) in T and T.get((s, MAIN_POOL, m, TOP))}
             for s in scen}
    ratio_med = {m: med(r[m] for r in ratio.values() if m in r) for m in methods}
    if selected is None or not rows.get(selected, {}).get("n"):
        verdict = None
    else:
        verdict = LEAK_SAME if rows[selected]["noninf"] else LEAK_ONLY
    return {"selected": selected, "methods": methods, "rows": rows, "ratio": ratio, "ratio_median": ratio_med,
            "verdict": verdict}


# ---------------------------------------------------------------- 곡선 지표

def reach_evals(r: Mapping[str, Any], target: float) -> int | None:
    """곡선에서 pack이 target(그 시나리오의 K · 2,000 최종값)에 처음 닿은 평가 수. 못 닿으면 None."""
    for h in r.get("history") or []:
        if h["pack"] >= target - PACK_TOL:
            return h["evals"]
    return None


def stall_evals(r: Mapping[str, Any]) -> int | None:
    """정체 시점 — 배치 순서 다듬기 직전 값(pre_order.pack)에 처음 닿은 평가 수(실험 9와 같은 정의)."""
    h = r.get("history") or []
    po = r.get("pre_order")
    if po is None:
        if len(h) < 2:
            return None
        target = h[-2]["pack"]
    else:
        target = po["pack"]
    for x in h:
        if x["pack"] >= target - PACK_TOL:
            return x["evals"]
    return po["evals"] if po else None


def known_best(runs: Mapping[Key, Mapping[str, Any]], exp9: Sequence[Mapping[str, Any]],
               scen: Sequence[str], pool: int) -> dict[str, dict[str, Any]]:
    """시나리오별 알려진 최고(후처리 전): 실험 9 검증 모든 실행(P60만) + 같은 풀의 실험 10 모든 실행."""
    out: dict[str, dict[str, Any]] = {}

    def put(s, v, src):
        if s in scen and v and (s not in out or v > out[s]["total"]):
            out[s] = {"total": v, "source": src}
    if pool == MAIN_POOL:
        for r in exp9:
            put(r.get("scenario"), r.get("final", {}).get("total"), f"실험 9 {r.get('method')} · {r.get('budget')}")
    for k, r in runs.items():
        if k[1] == pool:
            put(k[0], r["final"]["total"], f"실험 10 {k[2]} · {k[3]}")
    return out


# ---------------------------------------------------------------- 분석

def _sel(runs: Mapping[Key, Any], pool: int, m: str, b: int) -> list[tuple[Key, dict[str, Any]]]:
    return [(k, r) for k, r in sorted(runs.items()) if k[1] == pool and k[2] == m and k[3] == b]


def missing_runs(runs: Mapping[Key, Any], pool: int, methods: Sequence[str], budgets: Sequence[int],
                 scen: Sequence[str] = VAL_SCENARIOS) -> list[str]:
    return [f"{s}_P{pool}_{m}_{b}" for s in scen for m in methods for b in budgets if (s, pool, m, b) not in runs]


def progress_rows(runs: Mapping[Key, Mapping[str, Any]], T: Mapping[Key, float], pool: int) -> list[dict[str, Any]]:
    rows = []
    for m in METHODS:
        for b in BUDGETS:
            xs = _sel(runs, pool, m, b)
            if not xs:
                continue
            reach, unreached = [], 0
            for k, r in xs:
                tgt = T.get((k[0], pool, "K", TOP))
                if tgt is None:
                    continue
                e = reach_evals(r, tgt)
                if e is None:
                    unreached += 1
                else:
                    reach.append(e)
            stall = [e for _, r in xs if (e := stall_evals(r)) is not None]
            st = [r["start"]["pack"] / r["final"]["total"] for _, r in xs if r.get("start") and r["final"]["total"]]
            rows.append({"method": m, "budget": b, "n": len(xs),
                         "evals": med(r.get("evals", 0) for _, r in xs),
                         "start_evals": med(r["start"]["evals"] for _, r in xs if r.get("start")),
                         "start_ratio": med(st),
                         "reach": med(reach), "reached": len(reach), "unreached": unreached,
                         "stall": med(stall),
                         "kicks": med(len(r.get("kicks") or []) for _, r in xs),
                         "improved": med(sum(bool(x.get("improved")) for x in r.get("kicks") or []) for _, r in xs)})
    return rows


def alt_rows(runs: Mapping[Key, Mapping[str, Any]], pool: int) -> list[dict[str, Any]]:
    rows = []
    for m in METHODS:
        for b in BUDGETS:
            xs = _sel(runs, pool, m, b)
            if not xs:
                continue
            row = {"method": m, "budget": b, "n": len(xs)}
            for key in ("alt", "alt20"):
                have = [r for _, r in xs if (r.get(key) or {}).get("total") and r["final"]["total"]]
                row[key] = {"found": len(have), "ratio": med(r[key]["total"] / r["final"]["total"] for r in have),
                            "shared": med(r[key]["shared_nikkes"] for r in have if r[key].get("shared_nikkes") is not None)}
            rows.append(row)
    return rows


def cost(runs: Mapping[Key, Mapping[str, Any]], pool: int | None = None) -> dict[str, Any]:
    xs = [r for k, r in runs.items() if pool is None or k[1] == pool]
    return {"runs": len(xs), "evals": sum(r.get("evals", 0) for r in xs), "sims": sum(r.get("sims_during", 0) for r in xs),
            "seconds": sum(r.get("seconds", 0.0) for r in xs), "errors": sum(r.get("errors", 0) or 0 for r in xs)}


def analyze(runs: Mapping[Key, Mapping[str, Any]], dev: Mapping[Key, Mapping[str, Any]] | None = None,
            exp9: Sequence[Mapping[str, Any]] = (), precompute: Mapping[int, Mapping[str, Any]] | None = None,
            expect_p177: bool = False) -> dict[str, Any]:
    """runs: 검증 실행(P60 · P177을 한데). 검증 시나리오(v1~v8) 밖의 실행은 판단에서 뺀다."""
    other = sorted({k[0] for k in runs if k[0] not in VAL_SCENARIOS})
    runs = {k: r for k, r in runs.items() if k[0] in VAL_SCENARIOS}
    scen = sorted({k[0] for k in runs if k[1] == MAIN_POOL}, key=VAL_SCENARIOS.index)
    names = {k[0]: r.get("name", "") for k, r in runs.items()}
    T = {k: r["final"]["total"] for k, r in runs.items()}
    j1, j2 = judge1(T, scen), judge2(T, scen)
    rows = [{"budget": b, "method": m, **gstats(rel(T, scen, MAIN_POOL, m, "K", b))} for b in BUDGETS for m in METHODS[1:]]
    per = [{"scenario": s, "name": names.get(s, ""), "budget": b,
            "totals": {m: T.get((s, MAIN_POOL, m, b)) for m in METHODS}} for s in scen for b in BUDGETS]
    escape = [{"start": x, "budget": b, **gstats(rel(T, scen, MAIN_POOL, x + "+E", x, b))} for x in STARTS for b in BUDGETS]
    has177 = any(k[1] == LEAK_POOL for k in runs)
    leak = leak_check(T, scen, j1["selected"])
    pools = [MAIN_POOL] + ([LEAK_POOL] if has177 else [])
    kb = {p: known_best(runs, exp9, scen, p) for p in pools}
    kb_rows = []
    for p in pools:
        for m in METHODS:
            xs = [T[(s, p, m, TOP)] / kb[p][s]["total"] for s in scen if (s, p, m, TOP) in T and s in kb[p]]
            if xs:
                kb_rows.append({"pool": p, "method": m, "n": len(xs), "median": med(xs), "min": min(xs)})
    miss = missing_runs(runs, MAIN_POOL, METHODS, BUDGETS)
    if expect_p177 or has177:
        lm = leak["methods"] if leak else [x for x in [j1["selected"], j1["pair"], "K", "K+E"] if x]
        miss += missing_runs(runs, LEAK_POOL, lm, (TOP,))
    devrows = None
    if dev:
        dscen = sorted({k[0] for k in dev if k[1] == MAIN_POOL})
        Td = {k: r["final"]["total"] for k, r in dev.items()}
        devrows = [{"budget": b, "method": m, **gstats(rel(Td, dscen, MAIN_POOL, m, "K", b))}
                   for b in BUDGETS for m in METHODS[1:] if any(k[2] == m and k[3] == b for k in dev)]
    pre = {p: {"evals": r.get("evals"), "sims": r.get("sims"), "seconds": r.get("seconds"), "budget": r.get("budget"),
               "sets": len(r.get("sets") or []), "set_totals": r.get("set_totals"),
               "final": (r.get("final") or {}).get("total")} for p, r in (precompute or {}).items()}
    costs = {f"검증 P{p}": cost(runs, p) for p in pools}
    if dev:
        costs["개발"] = cost(dev)
    return {"scenarios": scen, "names": names, "judge1": j1, "judge2": j2, "leak": leak, "rows": rows, "per": per,
            "escape": escape, "progress": {p: progress_rows(runs, T, p) for p in pools},
            "alt": {p: alt_rows(runs, p) for p in pools}, "known_best": kb, "known_best_rows": kb_rows,
            "missing": miss, "errors": sorted(f"{k[0]}_P{k[1]}_{k[2]}_{k[3]}" for k, r in runs.items() if r.get("errors")),
            "ignored_scenarios": other, "dev": devrows, "precompute": pre, "cost": costs, "exp9_runs": len(exp9)}


# ---------------------------------------------------------------- 쓰기

def pct(x: float | None, nd: int = 1) -> str:
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def num(x: float | None, nd: int = 1) -> str:
    return "—" if x is None else f"{x:.{nd}f}"


def ratio(x: float | None, nd: int = 1) -> str:
    return "—" if x is None else f"{x * 100:.{nd}f}%"


def blist(bs: Sequence[int]) -> str:
    return "[" + ", ".join(f"{b:,}" for b in bs) + "]" if bs else "없음"


def mlist(ms: Sequence[str]) -> str:
    return ", ".join(ms) if ms else "없음"


def yes(v: bool) -> str:
    return "예" if v else ""


LINE_TEXT = {1: ("랭커 없이도 된다", "1단계 기본 출발을 {pick}(으)로 바꾼다. P177 확인 결과로 풀을 정하고 2단계(큐브)로."),
             2: ("예산이 넉넉하면 된다", "예산 800 이하는 K를 쓴다(랭커 자료가 있을 때). 도달 평가 수를 줄이는 출발 개선(설계 크기 · 구성 라운드 수)을 다음 회차로."),
             3: ("랭커 출발이 아직 필요하다", "출발 품질과 탐색 중 어디서 지는지(출발 직후 비율 · 도달 곡선)로 원인을 나눠 다음 회차로.")}


def render(a: Mapping[str, Any], meta: Mapping[str, Any] | None = None) -> str:
    j1, j2, lk = a["judge1"], a["judge2"], a["leak"]
    n = len(a["scenarios"])
    L = ["# 실험 10 결과 — 랭커 정보 없는 출발과 국소 최적 탈출", "",
         "`analyze10.py` 생성. 판단은 검증 시나리오 8개 · 풀 60명(P60)의 최선 5덱 180초 총딜 합(기본 레이어, 후처리 전). "
         "H = 기법 / K − 1(같은 풀 · 예산 · 시나리오).", "",
         "P60은 랭커가 미리 거른 로스터라 랭커 없는 기법의 절대 품질은 낙관적이다 — 누출은 P177 확인으로 본다(README 「풀 누출의 처리」).", ""]
    if meta and meta.get("evaluator"):
        L += [f"평가기: {meta['evaluator']}", ""]
    L += ["## 판단", ""]
    if a["missing"]:
        L += [f"> 빠진 실행 {len(a['missing'])}개 — 있는 시나리오로만 판단했다(아래 「빠진 실행」). 확정 판단이 아니다.", ""]
    title, nxt = LINE_TEXT[j1["line"]]
    who = j1["pick"] if j1["line"] == 1 else (mlist(j1["names"]) if j1["line"] == 2 else "")
    L += [f"**질문 1 — {j1['line']}줄 「{title}」" + (f": {who}" if who else "") + ".** "
          + (f"예산 800 · 2,000 모두에서 못지않은 기법: {mlist(j1['names'])}. " if j1["line"] == 1 else "")
          + ("2,000에서만 못지않다. " if j1["line"] == 2 else "")
          + "다음: " + nxt.format(pick=j1["pick"]), "",
          f"- 「못지않다」(중앙 ≥ {pct(NONINF_MEDIAN)} 그리고 H < {pct(NONINF_LOW, 0)}가 {NONINF_MAX_LOW}개 이하) 예산: "
          + " · ".join(f"{m} {blist(j1['noninf'][m])}" for m in RANKERLESS) + ".",
          f"- 「낫다」(중앙 ≥ {pct(MARGIN)} 그리고 H > 0이 {need(n)}개 이상) 예산: "
          + " · ".join(f"{m} {blist(j1['wins'][m])}" for m in RANKERLESS) + ".",
          "- 「못하다」 예산: " + " · ".join(f"{m} {blist(j1['loses'][m])}" for m in RANKERLESS) + ".",
          f"- 동점 깨기: (1) R · G 계열을 P 계열보다 (2) 2,000의 H 중앙이 큰 쪽 (3) 800의 H 중앙.",
          f"- P177 확인에 고른 기법: **{j1['selected'] or '—'}**"
          + (" (1줄 선택)" if j1["line"] == 1 else " (1줄이 아니라 2,000의 H 중앙이 가장 큰 랭커 없는 기법)")
          + f", 탈출 짝 {j1['pair'] or '—'}.",
          f"- 예산 300(판단 밖): 못지않다 {mlist(j1['small_budget']['noninf'])} · 낫다 {mlist(j1['small_budget']['better'])}"
          f" · 못하다 {mlist(j1['small_budget']['worse'])}.", ""]
    k = j2["per_start"]["K"]
    L += [f"**질문 2 — E {'채택' if j2['adopt'] else '채택하지 않음'}.** K+E / K − 1: 2,000 중앙 {pct(k['median2000'], 2)}"
          f"(「낫다」 {'예' if k['better2000'] else '아니오'}), 800 중앙 {pct(k['median800'], 2)}"
          f"(「못하다」 {'예' if k['worse800'] else '아니오'}).", ""]
    for x in STARTS[1:]:
        p = j2["per_start"][x]
        L.append(f"- {x}+E 대 {x}(같은 규칙, 따로 적음): 2,000 중앙 {pct(p['median2000'], 2)} · 800 중앙 {pct(p['median800'], 2)}"
                 f" → {'채택 조건 충족' if p['adopt'] else '채택 조건 미충족'}"
                 f"(2,000 낫다 {'예' if p['better2000'] else '아니오'}, 800 못하다 {'예' if p['worse800'] else '아니오'}).")
    L.append("")
    if lk is None:
        L += ["**P177 확인 — 실행 없음.**", ""]
    else:
        s = lk["selected"]
        r = lk["rows"].get(s) if s else None
        if lk["verdict"] is None:
            L += [f"**P177 확인 — 판단 불가**(고른 기법 {s or '—'}의 P177 실행 없음).", ""]
        else:
            L += [f"**P177 확인 — 「{lk['verdict']}」.** {s} / K − 1(P177, 2,000): 중앙 {pct(r['median'], 2)}, "
                  f"H < {pct(NONINF_LOW, 0)} {r['low']}/{r['n']}개 → 「못지않다」 {'예' if r['noninf'] else '아니오'}.", ""]
    # ---- 표
    L += [f"## 기법별 H (검증 {n}개, P60)", "",
          "| 예산 | 기법 | 중앙 | H>0 | H<0 | 최소 | 최대 | H<−3% | 낫다 | 못하다 | 못지않다 |",
          "|---:|---|---:|---:|---:|---:|---:|---:|---|---|---|"]
    for r in a["rows"]:
        L.append(f"| {r['budget']:,} | {r['method']} | {pct(r['median'], 2)} | {r['pos']}/{r['n']} | {r['neg']}/{r['n']} | "
                 f"{pct(r['min'])} | {pct(r['max'])} | {r['low']} | {yes(r['better'])} | {yes(r['worse'])} | {yes(r['noninf'])} |")
    if lk is not None:
        L += ["", "## P177 확인 (예산 2,000)", "", "K(P177) 대비 H:", "",
              "| 기법 | 중앙 | H>0 | H<0 | 최소 | 최대 | H<−3% | 못지않다 | P177 / P60 중앙 |", "|---|---:|---:|---:|---:|---:|---:|---|---:|"]
        for m in lk["methods"]:
            rm = lk["ratio_median"].get(m)
            if m == "K":
                L.append(f"| K | (기준) | | | | | | | {ratio(rm)} |")
                continue
            r = lk["rows"][m]
            L.append(f"| {m} | {pct(r['median'], 2)} | {r['pos']}/{r['n']} | {r['neg']}/{r['n']} | {pct(r['min'])} | "
                     f"{pct(r['max'])} | {r['low']} | {yes(r['noninf'])} | {ratio(rm)} |")
        L += ["", "같은 기법의 P177 / P60 (시나리오별):", "",
              "| 시나리오 | " + " | ".join(lk["methods"]) + " |", "|---|" + "---:|" * len(lk["methods"])]
        for s in a["scenarios"]:
            L.append(f"| {s} {a['names'].get(s, '')} | " + " | ".join(ratio(lk["ratio"].get(s, {}).get(m)) for m in lk["methods"]) + " |")
    L += ["", "## 시나리오별 5덱 합 (억, P60)", "", "| 시나리오 | 예산 | " + " | ".join(METHODS) + " |",
          "|---|---:|" + "---:|" * len(METHODS)]
    for r in a["per"]:
        L.append(f"| {r['scenario']} {r['name']} | {r['budget']:,} | " + " | ".join(num(r["totals"][m]) for m in METHODS) + " |")
    L += ["", "## 탈출 효과 P(X+E) / P(X) − 1 (P60)", "", "| 출발 | 예산 | 중앙 | 양수 | 최소 | 최대 | 낫다 | 못하다 |",
          "|---|---:|---:|---:|---:|---:|---|---|"]
    for r in a["escape"]:
        L.append(f"| {r['start']} | {r['budget']:,} | {pct(r['median'], 2)} | {r['pos']}/{r['n']} | {pct(r['min'])} | "
                 f"{pct(r['max'])} | {yes(r['better'])} | {yes(r['worse'])} |")
    for p, rows in a["progress"].items():
        L += ["", f"## 탐색 경과 (P{p}, 시나리오 중앙)", "",
              "출발 = 출발 단계 직후(K 옮기기 · R 설계 · G 구성 · P 옮기기). 도달 = 그 시나리오의 K · 2,000 최종값(같은 풀)에 처음 닿은 평가 수"
              "(닿은 실행만의 중앙, 미도달은 개수). 정체 = 배치 순서 다듬기 직전 값에 처음 닿은 평가 수.", "",
              "| 기법 | 예산 | 쓴 평가 | 출발 평가 | 출발 / 최종 | 도달 평가 | 미도달 | 정체 시점 | 킥 수 | 오른 킥 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for r in rows:
            L.append(f"| {r['method']} | {r['budget']:,} | {num(r['evals'], 0)} | {num(r['start_evals'], 0)} | {ratio(r['start_ratio'])} | "
                     f"{num(r['reach'], 0)} | {r['unreached']}/{r['reached'] + r['unreached']} | {num(r['stall'], 0)} | "
                     f"{num(r['kicks'], 0)} | {num(r['improved'], 0)} |")
    for p, rows in a["alt"].items():
        L += ["", f"## 대안 5덱 (P{p}) — (a) 최선과 덱 2개 이하 공유 (b) 그중 니케 공유 20명 이하", "",
              "| 기법 | 예산 | (a) 있음 | (a) 최선 대비 | (a) 공유 니케 | (b) 있음 | (b) 최선 대비 | (b) 공유 니케 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for r in rows:
            x, y = r["alt"], r["alt20"]
            L.append(f"| {r['method']} | {r['budget']:,} | {x['found']}/{r['n']} | {ratio(x['ratio'])} | {num(x['shared'], 0)}/25 | "
                     f"{y['found']}/{r['n']} | {ratio(y['ratio'])} | {num(y['shared'], 0)}/25 |")
    L += ["", "## 알려진 최고 대비 (예산 2,000)", "",
          f"알려진 최고 = 시나리오별로 실험 9 검증 모든 실행(후처리 전, {a['exp9_runs']}개 — P60에만)과 같은 풀의 실험 10 모든 실행 중 최고.", "",
          "| 풀 | 기법 | 최종 / 알려진 최고 중앙 | 최소 |", "|---:|---|---:|---:|"]
    for r in a["known_best_rows"]:
        L.append(f"| P{r['pool']} | {r['method']} | {ratio(r['median'])} | {ratio(r['min'])} |")
    L += ["", "| 풀 | 시나리오 | 알려진 최고 | 출처 |", "|---:|---|---:|---|"]
    for p, kb in a["known_best"].items():
        for s, v in kb.items():
            L.append(f"| P{p} | {s} | {v['total']:.1f} | {v['source']} |")
    L += ["", "## 비용", ""]
    if a["precompute"]:
        L += ["| 공유 사전 계산 | 요청 평가 | 실제 시뮬 | 초 | 8벌 중 만든 벌 | 최종 5덱 합 |", "|---|---:|---:|---:|---:|---:|"]
        for p, r in sorted(a["precompute"].items()):
            L.append(f"| P{p} | {num(r['evals'], 0)} | {num(r['sims'], 0)} | {num(r['seconds'], 0)} | {r['sets']} | {num(r['final'])} |")
        L.append("")
    else:
        L += ["공유 사전 계산 기록 없음.", ""]
    L += ["| 묶음 | 실행 | 요청 평가 합 | 실제 시뮬 합 | 초 합 | 오류 |", "|---|---:|---:|---:|---:|---:|"]
    for name, c in a["cost"].items():
        L.append(f"| {name} | {c['runs']} | {c['evals']:,} | {c['sims']:,} | {c['seconds']:,.0f} | {c['errors']} |")
    if a["dev"]:
        L += ["", "## 개발 8개 (P60, 참고 — 판단에 쓰지 않음)", "", "| 예산 | 기법 | 중앙 H | H>0 | H<−3% | 못지않다 |",
              "|---:|---|---:|---:|---:|---|"]
        for r in a["dev"]:
            L.append(f"| {r['budget']:,} | {r['method']} | {pct(r['median'], 2)} | {r['pos']}/{r['n']} | {r['low']} | {yes(r['noninf'])} |")
    if a["missing"] or a["errors"] or a["ignored_scenarios"]:
        L += ["", "## 빠진 실행 · 오류", ""]
        if a["missing"]:
            L.append(f"- 빠진 실행 {len(a['missing'])}개: " + ", ".join(a["missing"]))
        if a["errors"]:
            L.append(f"- 오류가 있는 실행 {len(a['errors'])}개: " + ", ".join(a["errors"]))
        if a["ignored_scenarios"]:
            L.append("- 검증 시나리오가 아니라 뺀 시나리오: " + ", ".join(a["ignored_scenarios"]))
    if meta:
        rest = {k: v for k, v in meta.items() if k != "evaluator"}
        if rest:
            L += ["", "## 실행", ""] + [f"- {k}: {v}" for k, v in rest.items()]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", type=Path, required=True, help="검증 P60 실행 요약 dir")
    ap.add_argument("--p177", type=Path, help="검증 P177 실행 요약 dir(P60과 같은 dir이어도 된다)")
    ap.add_argument("--dev-runs", type=Path)
    ap.add_argument("--precompute", type=Path, help="precompute_P*.json dir(기본: --runs · --p177 dir)")
    ap.add_argument("--exp9-log", type=Path, default=EXP9_LOG, help="실험 9 run_log dir 또는 val_summary.jsonl")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--meta", type=Path, help="실행 메모 JSON(평가기 · 시뮬 수 등)")
    args = ap.parse_args(argv)
    runs = load_dir(args.runs)
    if args.p177 and args.p177 != args.runs:
        runs.update(load_dir(args.p177))
    dev = load_dir(args.dev_runs) if args.dev_runs else None
    pre = load_precompute([args.precompute] if args.precompute else [args.runs, args.p177])
    a = analyze(runs, dev, load_exp9(args.exp9_log), pre, expect_p177=args.p177 is not None)
    if a["missing"]:
        _warn(f"빠진 실행 {len(a['missing'])}개: {a['missing'][:6]}{' …' if len(a['missing']) > 6 else ''}")
    meta = json.loads(args.meta.read_text(encoding="utf-8")) if args.meta else None
    args.out.write_text(render(a, meta), encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(a, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"q1": {k: a["judge1"][k] for k in ("line", "pick", "names", "selected", "pair")},
                      "q2_adopt_E": a["judge2"]["adopt"], "p177": a["leak"]["verdict"] if a["leak"] else None,
                      "missing": len(a["missing"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
