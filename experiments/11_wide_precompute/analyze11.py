"""실험 11 분석 — README §판단 기준(질문 1 · 2) · 사전 계산 비용 · 출발 품질과 도달.

    python experiments/11_wide_precompute/analyze11.py --runs <실행 요약 dir> [--summary val_summary.jsonl]
        [--exp10-log experiments/10_rankerless_start/run_log] [--precompute <precompute_PB15 등 dir>]
        --out experiments/11_wide_precompute/results.md [--json <요약.json>] [--meta <실행 메모.json>]

실행 요약 JSON의 형식은 실험 10 SESSIONS.md 「인터페이스 — 실행 요약 JSON」을 따른다(값은 억 단위, 후처리 전).
`--summary`는 한 줄에 {"run": 이름, **요약}인 jsonl이다(`--runs`와 함께 줄 수 있다).
같은 실행이 여러 곳에 있으면 `--runs` > `--summary` > `--exp10-log` 순으로 쓰고, 최종 5덱 합이 1e-6보다 다르면 경고한다.
판단 상수 · 규칙 함수는 analyze10을 그대로 쓴다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXP10 = HERE.parent / "10_rankerless_start"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


A = sys.modules.get("analyze10") or _load("analyze10", EXP10 / "analyze10.py")

POOL = 177
BASE = "K"  # 질문 1의 기준(랭커 30명 옮기기 + 177명 L0)
REF = "P"  # 질문 2의 기준(실험 10 P177 사전 계산 = 지금의 랭커 없는 기본)
CANDS = ("PB15", "PB30", "PN", "PM")
SHOWN = (REF,) + CANDS  # K 대비 H를 표로 보이는 기법(P는 참고 행)
ALL_METHODS = (BASE,) + SHOWN
BUDGETS = (800, 2000)
TOP = 2000
VAL_SCENARIOS = A.VAL_SCENARIOS
RANDOM_TIER = ("v5", "v6", "v8")
PRE_NAMES = ("P",) + CANDS  # 사전 계산 표 순서. P = 실험 10 precompute_P177.json
PACK_TOL, EPS = A.PACK_TOL, A.EPS
MARGIN, SHARE, NONINF_MEDIAN, NONINF_LOW, NONINF_MAX_LOW = A.MARGIN, A.SHARE, A.NONINF_MEDIAN, A.NONINF_LOW, A.NONINF_MAX_LOW
DIFF_TOL = 1e-6  # 같은 실행이 두 곳에 있을 때 최종 합이 이보다 다르면 경고
ACCOUNTS = (1, 10, 100)
CURVE_AT = {"PB30": (5000, 10000, 15000, 20000, 25000), "PB15": (5000, 10000)}
CURVE_COLS = (5000, 10000, 15000, 20000, 25000)

EXP10_LOG = EXP10 / "run_log"
POOL_JSON = HERE.parent / "02_score_distribution" / "pool.json"

Key = tuple[str, int, str, int]  # (시나리오, 풀, 기법, 예산) — 풀은 항상 177


# ---------------------------------------------------------------- 읽기

def _warn(msg: str) -> None:
    print(msg, file=sys.stderr)


def _key_of(r: Mapping[str, Any]) -> Key:
    k = (str(r["scenario"]), int(r["pool"]), str(r["method"]), int(r["budget"]))
    r["final"]["total"]
    return k


def load_dir(d: Path | None) -> dict[Key, dict[str, Any]]:
    """`<시나리오>_P177_<기법>_<예산>.json`. 풀 177만 쓴다. `precompute_*.json`은 건너뛴다."""
    out = {}
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
            k = _key_of(r)
        except (OSError, ValueError, KeyError, TypeError) as e:
            _warn(f"읽을 수 없는 요약 건너뜀: {p.name} ({e!r})")
            continue
        if k[1] != POOL:
            continue
        if k in out:
            _warn(f"같은 실행이 두 번: {k} — 나중 파일({p.name})을 쓴다")
        out[k] = r
    return out


def load_jsonl(path: Path | None, methods: Iterable[str] | None = None) -> dict[Key, dict[str, Any]]:
    """한 줄 = {"run": 이름, **요약}. 풀 177만, `methods`가 있으면 그 기법만."""
    out = {}
    if path is None:
        return out
    if path.is_dir():
        path = path / "val177_summary.jsonl"
    if not path.is_file():
        _warn(f"요약 jsonl 없음: {path}")
        return out
    keep = set(methods) if methods is not None else None
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            k = _key_of(r)
        except (ValueError, KeyError, TypeError) as e:
            _warn(f"읽을 수 없는 줄 건너뜀: {path.name}:{i} ({e!r})")
            continue
        if k[1] != POOL or (keep is not None and k[2] not in keep):
            continue
        if k in out:
            _warn(f"같은 실행이 두 번: {k} — 나중 줄({path.name}:{i})을 쓴다")
        out[k] = r
    return out


def merge_runs(layers: Sequence[tuple[str, Mapping[Key, dict[str, Any]]]]) -> dict[Key, dict[str, Any]]:
    """layers: 낮은 우선순위부터. 뒤의 것이 앞의 것을 덮고, 최종 합이 크게 다르면 경고한다."""
    out: dict[Key, dict[str, Any]] = {}
    src: dict[Key, str] = {}
    for name, runs in layers:
        for k, r in runs.items():
            if k in out:
                a, b = out[k]["final"]["total"], r["final"]["total"]
                if abs(a - b) > DIFF_TOL:
                    _warn(f"같은 실행의 최종 합이 다르다: {k} — {src[k]} {a:.6f} / {name} {b:.6f}; {name}을 쓴다")
            out[k] = r
            src[k] = name
    return out


def load_precompute(dirs: Iterable[Path | None], exp10_log: Path | None = None) -> dict[str, dict[str, Any]]:
    """기호 → 사전 계산 기록. P는 실험 10 `precompute_P177.json`, 나머지는 `precompute_<기호>.json`."""
    out: dict[str, dict[str, Any]] = {}

    def read(p: Path, name: str):
        try:
            out[name] = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as e:
            _warn(f"읽을 수 없는 사전 계산 건너뜀: {p.name} ({e!r})")

    if exp10_log is not None and (exp10_log / "precompute_P177.json").is_file():
        read(exp10_log / "precompute_P177.json", "P")
    for d in dirs:
        if d is None or not d.is_dir():
            continue
        for name in CANDS:
            p = d / f"precompute_{name}.json"
            if p.is_file() and name not in out:
                read(p, name)
    for name in PRE_NAMES:
        if name not in out:
            _warn(f"사전 계산 기록 없음: {name}")
    return out


def load_pool_names(path: Path | None) -> list[str] | None:
    if path is None or not path.is_file():
        _warn(f"P60 풀 파일 없음: {path}")
        return None
    try:
        return list(json.loads(path.read_text(encoding="utf-8"))["pool"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        _warn(f"P60 풀을 읽을 수 없음: {path} ({e!r})")
        return None


# ---------------------------------------------------------------- 판단 규칙

def stat(gs: Sequence[float], n_all: int = len(VAL_SCENARIOS)) -> dict[str, Any]:
    """analyze10.gstats + 시나리오가 다 있어야 판단한다(모자라면 판단 불가)."""
    s = A.gstats(gs)
    s["complete"] = len(gs) == n_all
    s["n_all"] = n_all
    for f in ("better", "worse", "noninf"):
        s[f] = bool(s[f]) and s["complete"]
    return s


def label(s: Mapping[str, Any]) -> str:
    if not s["complete"]:
        return f"판단 불가({s['n']}/{s['n_all']})"
    out = [t for t, f in (("낫다", "better"), ("못하다", "worse"), ("못지않다", "noninf")) if s[f]]
    return " · ".join(out) if out else "해당 없음"


def rel(T: Mapping[Key, float], m: str, base: str, b: int, scen: Sequence[str] = VAL_SCENARIOS) -> list[float]:
    return A.rel(T, scen, POOL, m, base, b)


def judge1(T: Mapping[Key, float], pre_evals: Mapping[str, float | None],
           scen: Sequence[str] = VAL_SCENARIOS) -> dict[str, Any]:
    """질문 1 — 후보(PB15 · PB30 · PN · PM)가 K177에 못지않은가. P는 참고."""
    st = {m: {b: stat(rel(T, m, BASE, b, scen), len(scen)) for b in BUDGETS} for m in SHOWN}
    md = {m: {b: st[m][b]["median"] for b in BUDGETS} for m in SHOWN}
    both = [m for m in CANDS if all(st[m][b]["noninf"] for b in BUDGETS)]
    only2000 = [m for m in CANDS if st[m][TOP]["noninf"] and m not in both]

    def order(m: str):  # 사전 계산 평가 수가 작은 쪽 → 2,000의 H 중앙이 큰 쪽 → 800의 H 중앙이 큰 쪽
        e = pre_evals.get(m)
        return (float("inf") if e is None else e, -(md[m][TOP] if md[m][TOP] is not None else -9.0),
                -(md[m][800] if md[m][800] is not None else -9.0))

    if both:
        line, names = 1, both
    elif only2000:
        line, names = 2, only2000
    else:
        line, names = 3, []
    pick = min(names, key=order) if names else None
    return {"line": line, "names": names, "pick": pick, "stats": st, "median": md,
            "noninf": {m: [b for b in BUDGETS if st[m][b]["noninf"]] for m in SHOWN}}


def judge2(T: Mapping[Key, float], q1: Mapping[str, Any], pre_evals: Mapping[str, float | None],
           scen: Sequence[str] = VAL_SCENARIOS) -> dict[str, Any]:
    """질문 2 — 후보가 P(실험 10)보다 나은가. 새 기본 = 질문 1의 선택, 아니면 새 기본 자격 후보 중 2,000의 H(K 대비) 중앙 최대, 없으면 P."""
    per = {}
    for m in CANDS:
        g8, g20 = rel(T, m, REF, 800, scen), rel(T, m, REF, TOP, scen)
        s8, s20 = stat(g8, len(scen)), stat(g20, len(scen))
        per[m] = {"g800": s8, "g2000": s20,
                  "eligible": bool(s20["better"] and s20["complete"] and s8["complete"] and not s8["worse"])}
    eligible = [m for m in CANDS if per[m]["eligible"]]
    md = q1["median"]
    if q1["line"] in (1, 2):
        default, how = q1["pick"], f"질문 1의 {q1['line']}줄 선택"
    elif eligible:
        default = min(eligible, key=lambda m: (-(md[m][TOP] if md[m][TOP] is not None else -9.0),
                                               float("inf") if pre_evals.get(m) is None else pre_evals[m]))
        how = "새 기본 자격 후보 중 2,000의 H(K 대비) 중앙 최대"
    else:
        default, how = REF, "새 기본 자격 후보 없음 — P 유지"
    return {"per": per, "eligible": eligible, "default": default, "how": how}


# ---------------------------------------------------------------- 지표

def med(xs: Iterable[float]) -> float | None:
    return A.med(xs)


def squad_names(r: Mapping[str, Any]) -> set[str]:
    """final.squads(= [[값, [니케 5명]], ...] 또는 [[니케 5명], ...])의 니케 이름 모음."""
    out: set[str] = set()
    for sq in (r.get("final") or {}).get("squads") or []:
        names = sq[1] if len(sq) == 2 and isinstance(sq[1], (list, tuple)) else sq
        out.update(n for n in names if isinstance(n, str))
    return out


def recall_rows(runs: Mapping[Key, Mapping[str, Any]], narrowed: Sequence[str] | None,
                p60: Sequence[str] | None, scen: Sequence[str] = VAL_SCENARIOS) -> dict[str, Any]:
    """K · 2,000 최종 편성의 니케가 좁힌 60명(PN) · P60 풀 안에 몇 명 있는가."""
    per = {}
    for s in scen:
        r = runs.get((s, POOL, BASE, TOP))
        if r is None:
            continue
        names = squad_names(r)
        per[s] = {"total": len(names),
                  "narrowed": len(names & set(narrowed)) if narrowed else None,
                  "p60": len(names & set(p60)) if p60 else None}
    return {"per": per, "narrowed_size": len(narrowed) if narrowed else None, "p60_size": len(p60) if p60 else None,
            "median_narrowed": med(v["narrowed"] for v in per.values() if v["narrowed"] is not None),
            "median_p60": med(v["p60"] for v in per.values() if v["p60"] is not None)}


def reach_rows(runs: Mapping[Key, Mapping[str, Any]], T: Mapping[Key, float],
               scen: Sequence[str] = VAL_SCENARIOS) -> list[dict[str, Any]]:
    out = []
    for m in ALL_METHODS:
        xs = [(s, runs[(s, POOL, m, TOP)]) for s in scen if (s, POOL, m, TOP) in runs]
        if not xs:
            continue
        reach = []
        for s, r in xs:
            tgt = T.get((s, POOL, BASE, TOP))
            if tgt is not None and (e := A.reach_evals(r, tgt)) is not None:
                reach.append(e)
        out.append({"method": m, "n": len(xs),
                    "start_ratio": med(r["start"]["pack"] / r["final"]["total"] for _, r in xs
                                       if r.get("start") and r["final"]["total"]),
                    "start_evals": med(r["start"]["evals"] for _, r in xs if r.get("start")),
                    "reached": len(reach), "reach": med(reach)})
    return out


def alt_rows(runs: Mapping[Key, Mapping[str, Any]], scen: Sequence[str] = VAL_SCENARIOS) -> list[dict[str, Any]]:
    out = []
    for m in ALL_METHODS:
        xs = [runs[(s, POOL, m, TOP)] for s in scen if (s, POOL, m, TOP) in runs]
        if not xs:
            continue
        row = {"method": m, "n": len(xs)}
        for key in ("alt", "alt20"):
            have = [r for r in xs if (r.get(key) or {}).get("total") and r["final"]["total"]]
            row[key] = {"found": len(have), "ratio": med(r[key]["total"] / r["final"]["total"] for r in have)}
        have = [r for r in xs if (r.get("alt") or {}).get("shared_nikkes") is not None and r["alt"].get("total")]
        row["shared"] = med(r["alt"]["shared_nikkes"] for r in have)
        out.append(row)
    return out


def tier_rows(T: Mapping[Key, float]) -> list[dict[str, Any]]:
    rnd = [s for s in VAL_SCENARIOS if s in RANDOM_TIER]
    oth = [s for s in VAL_SCENARIOS if s not in RANDOM_TIER]
    out = []
    for m in SHOWN:
        a, b = rel(T, m, BASE, TOP, rnd), rel(T, m, BASE, TOP, oth)
        out.append({"method": m, "random": med(a), "random_n": len(a), "other": med(b), "other_n": len(b)})
    return out


def pack_at(history: Sequence[Mapping[str, Any]], evals: int) -> float | None:
    """기록에서 평가 수가 evals 이상인 첫 점의 pack."""
    for h in history or []:
        if h["evals"] >= evals:
            return h["pack"]
    return None


def pre_rows(pre: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for name in PRE_NAMES:
        r = pre.get(name)
        if r is None:
            out.append({"name": name, "present": False})
            continue
        ev = r.get("evals")
        st = r.get("set_totals") or []
        out.append({"name": name, "present": True, "budget": r.get("budget"), "evals": ev, "sims": r.get("sims"),
                    "seconds": r.get("seconds"), "final": (r.get("final") or {}).get("total"),
                    "set_min": min(st) if st else None, "set_max": max(st) if st else None, "sets": len(r.get("sets") or []),
                    "per_account": {n: (round(ev / n) if ev is not None else None) for n in ACCOUNTS},
                    "stages": [{"what": s.get("what"), "budget": s.get("budget"), "evals": s.get("evals"),
                                "best": s.get("best")} for s in r.get("stages") or []]})
    return out


def curve_rows(pre: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for name in ("PB30", "PB15", "P"):
        r = pre.get(name)
        if r is None:
            continue
        at = CURVE_AT.get(name, ())
        out.append({"name": name, "at": {t: (pack_at(r.get("history") or [], t) if t in at else None) for t in CURVE_COLS},
                    "final": (r.get("final") or {}).get("total")})
    return out


# ---------------------------------------------------------------- 분석

def missing_runs(runs: Mapping[Key, Any]) -> list[str]:
    return [f"{s}_P{POOL}_{m}_{b}" for s in VAL_SCENARIOS for m in ALL_METHODS for b in BUDGETS
            if (s, POOL, m, b) not in runs]


def analyze(runs: Mapping[Key, Mapping[str, Any]], pre: Mapping[str, Mapping[str, Any]] | None = None,
            p60: Sequence[str] | None = None) -> dict[str, Any]:
    pre = pre or {}
    other = sorted({k[0] for k in runs if k[0] not in VAL_SCENARIOS})
    runs = {k: r for k, r in runs.items() if k[0] in VAL_SCENARIOS and k[1] == POOL}
    T = {k: r["final"]["total"] for k, r in runs.items()}
    names = {k[0]: r.get("name", "") for k, r in runs.items()}
    pre_evals = {n: (pre[n].get("evals") if n in pre else None) for n in PRE_NAMES}
    q1 = judge1(T, pre_evals)
    q2 = judge2(T, q1, pre_evals)
    narrowed = (pre.get("PN") or {}).get("narrowed")
    return {"names": names, "q1": q1, "q2": q2,
            "per": {b: [{"scenario": s, "name": names.get(s, ""), "k_total": T.get((s, POOL, BASE, b)),
                         "h": {m: (T[(s, POOL, m, b)] / T[(s, POOL, BASE, b)] - 1
                                   if (s, POOL, m, b) in T and T.get((s, POOL, BASE, b)) else None) for m in SHOWN}}
                        for s in VAL_SCENARIOS] for b in BUDGETS},
            "precompute": pre_rows(pre), "curve": curve_rows(pre), "reach": reach_rows(runs, T),
            "tier": tier_rows(T), "recall": recall_rows(runs, narrowed, p60), "alt": alt_rows(runs),
            "missing": missing_runs(runs), "errors": sorted(f"{k[0]}_P{k[1]}_{k[2]}_{k[3]}" for k, r in runs.items() if r.get("errors")),
            "ignored_scenarios": other, "pre_evals": pre_evals}


# ---------------------------------------------------------------- 쓰기

pct, num, ratio = A.pct, A.num, A.ratio


def n_or(x: float | None, nd: int = 0) -> str:
    return "—" if x is None else f"{x:,.{nd}f}"


ROW_TEXT = {1: "랭커 없이 넓은 풀에서도 된다", 2: "예산이 넉넉하면 된다", 3: "아직 K177에 못 미친다"}


def render(a: Mapping[str, Any], meta: Mapping[str, Any] | None = None) -> str:
    q1, q2 = a["q1"], a["q2"]
    st = q1["stats"]
    L = ["# 실험 11 결과 — 넓은 풀(177명)에서 랭커 없는 사전 계산", "",
         "`analyze11.py` 생성. 판단은 검증 시나리오 8개 · 풀 177명의 최선 5덱 180초 총딜 합(기본 레이어, 후처리 전, 억). "
         "H = 기법 / K − 1, G = 기법 / P − 1(같은 예산 · 시나리오). 계정 탐색은 모두 실험 10의 P 절차이고 사전 계산만 다르다. "
         f"판단 규칙은 실험 10과 같다(낫다 ≥ {pct(A.MARGIN)} 그리고 H>0이 {A.need(8)}개 이상, 못지않다 ≥ {pct(A.NONINF_MEDIAN)} "
         f"그리고 H<{pct(A.NONINF_LOW, 0)}가 {A.NONINF_MAX_LOW}개 이하, 시나리오 8개가 다 있어야 판단).", ""]
    if meta and meta.get("evaluator"):
        L += [f"평가기: {meta['evaluator']}", ""]
    L += ["## 판단", ""]
    if a["missing"]:
        L += [f"> 빠진 실행 {len(a['missing'])}개 — 있는 시나리오로 낸 값이며 8개가 안 되면 「판단 불가」다(아래 「빠진 실행 · 오류」).", ""]
    row = q1["line"]
    who = q1["pick"]
    L.append(f"**질문 1 — {row}줄 「{ROW_TEXT[row]}」" + (f": {who}" if who else "") + ".** "
             + {1: f"예산 800 · 2,000 모두에서 K에 못지않은 후보: {A.mlist(q1['names'])}. 그중 사전 계산 평가 수가 가장 작은 {who}을(를) 고른다"
                   f"(동점이면 2,000의 H 중앙, 그다음 800의 H 중앙).",
                2: f"2,000에서만 못지않은 후보: {A.mlist(q1['names'])}. 그중 사전 계산 평가 수가 가장 작은 {who}을(를) 고른다"
                   f"(동점이면 2,000의 H 중앙, 그다음 800의 H 중앙).",
                3: "어느 후보도 2,000에서 K177에 못지않다고 보기 어렵다."}[row])
    L += ["", "- 후보별 사전 계산 평가 수: " + " · ".join(f"{m} {n_or(a['pre_evals'].get(m))}" for m in CANDS) + ".",
          "- 후보별 「못지않다」 예산: " + " · ".join(f"{m} {A.blist(q1['noninf'][m])}" for m in CANDS)
          + f" (참고 P {A.blist(q1['noninf'][REF])}).", ""]
    L.append(f"**질문 2 — 랭커 없는 기본: {q2['default']}.** 근거: {q2['how']}.")
    L.append("")
    for m in CANDS:
        p = q2["per"][m]
        L.append(f"- {m}: G(2,000) 중앙 {pct(p['g2000']['median'], 2)}({label(p['g2000'])}), G(800) 중앙 {pct(p['g800']['median'], 2)}"
                 f"({label(p['g800'])}) → 새 기본 자격 {'있음' if p['eligible'] else '없음'}.")
    # ---- 표 1
    L += ["", "## 1. 질문 1 — K177 대비 H (검증 8개)", "",
          "| 기법 | 예산 | H 중앙 | 최소 · 최대 | H<−3% | H>0 | 판단 |", "|---|---:|---:|---|---:|---:|---|"]
    for m in SHOWN:
        for b in BUDGETS:
            s = st[m][b]
            L.append(f"| {m}{' (참고)' if m == REF else ''} | {b:,} | {pct(s['median'], 2)} | {pct(s['min'])} · {pct(s['max'])} | "
                     f"{s['low']} | {s['pos']}/{s['n']} | {label(s)} |")
    # ---- 표 2
    for b in sorted(BUDGETS, reverse=True):
        L += ["", f"## 2. 시나리오별 H (예산 {b:,})", "",
              "| 시나리오 | K 합(억) | " + " | ".join(SHOWN) + " |", "|---|---:|" + "---:|" * len(SHOWN)]
        for r in a["per"][b]:
            L.append(f"| {r['scenario']} {r['name']} | {num(r['k_total'])} | " + " | ".join(pct(r["h"][m]) for m in SHOWN) + " |")
    # ---- 표 3
    L += ["", "## 3. 질문 2 — P(실험 10) 대비 G", "",
          "| 후보 | 예산 | G 중앙 | G>0 | 판단 | 새 기본 자격 |", "|---|---:|---:|---:|---|---|"]
    for m in CANDS:
        for b in BUDGETS:
            s = q2["per"][m]["g800" if b == 800 else "g2000"]
            L.append(f"| {m} | {b:,} | {pct(s['median'], 2)} | {s['pos']}/{s['n']} | {label(s)} | "
                     f"{('예' if q2['per'][m]['eligible'] else '아니오') if b == TOP else ''} |")
    L += ["", "새 기본 자격 = G(2,000)이 「낫다」이고 G(800)이 「못하다」가 아니다."]
    # ---- 표 4
    L += ["", "## 4. 사전 계산 비용", "",
          "| 사전 계산 | 예산 | 요청 평가 | 실제 시뮬 | 초 | 계정 전 5덱 합(억) | 8벌 합 최소–최대 | 평가/계정 1 | 10 | 100 |",
          "|---|---:|---:|---:|---:|---:|---|---:|---:|---:|"]
    for r in a["precompute"]:
        if not r["present"]:
            L.append(f"| {r['name']} | — | — | — | — | — | — | — | — | — |")
            continue
        pa = r["per_account"]
        L.append(f"| {r['name']}{' (실험 10)' if r['name'] == 'P' else ''} | {n_or(r['budget'])} | {n_or(r['evals'])} | "
                 f"{n_or(r['sims'])} | {n_or(r['seconds'])} | {num(r['final'])} | {num(r['set_min'])}–{num(r['set_max'])} | "
                 f"{n_or(pa[1])} | {n_or(pa[10])} | {n_or(pa[100])} |")
    for r in a["precompute"]:
        if r["present"] and r["stages"]:
            L += ["", f"{r['name']}의 단계:", "", "| 단계 | 예산 | 요청 평가 | 단계 끝 최선(억) |", "|---|---:|---:|---:|"]
            for s in r["stages"]:
                L.append(f"| {s['what']} | {n_or(s['budget'])} | {n_or(s['evals'])} | {num(s['best'])} |")
    # ---- 표 5
    L += ["", "## 5. 사전 계산 곡선 — 예산을 늘리면 사전 계산 최선이 오르는가", "",
          "기록에서 평가 수가 그 값 이상인 첫 점의 pack(억). 계정 전 5덱 합 기준.", "",
          "| 사전 계산 | " + " | ".join(f"{t:,}" for t in CURVE_COLS) + " | 최종 |", "|---|" + "---:|" * (len(CURVE_COLS) + 1)]
    for r in a["curve"]:
        L.append(f"| {r['name']} | " + " | ".join(num(r["at"][t]) for t in CURVE_COLS) + f" | {num(r['final'])} |")
    if not a["curve"]:
        L.append("| (기록 없음) |" + " |" * (len(CURVE_COLS) + 1))
    # ---- 표 6
    L += ["", "## 6. 출발 품질과 도달 (예산 2,000, 시나리오 중앙)", "",
          "도달 = 그 시나리오의 K 2,000 최종값(pack, 허용 오차 1e-9)에 기록이 닿은 시나리오 수와, 닿은 실행의 첫 도달 평가 수 중앙.", "",
          "| 기법 | 실행 | 출발 pack / 최종 | 출발 평가 | 도달 시나리오 | 도달 평가 중앙 |", "|---|---:|---:|---:|---:|---:|"]
    for r in a["reach"]:
        L.append(f"| {r['method']} | {r['n']} | {ratio(r['start_ratio'])} | {n_or(r['start_evals'])} | "
                 f"{r['reached']}/{r['n']} | {n_or(r['reach'])} |")
    # ---- 표 7
    L += ["", "## 7. 관찰 — 무작위 티어(v5 · v6 · v8) 대 나머지 5개 (K 대비 H 중앙, 예산 2,000)", "",
          "| 기법 | 무작위 티어 | 나머지 |", "|---|---:|---:|"]
    for r in a["tier"]:
        L.append(f"| {r['method']} | {pct(r['random'], 2)} ({r['random_n']}개) | {pct(r['other'], 2)} ({r['other_n']}개) |")
    # ---- 표 8
    rc = a["recall"]
    L += ["", "## 8. 관찰 — 좁힌 풀의 재현율", "",
          f"K · 2,000 최종 편성(5덱)의 니케가 좁힌 60명(PN, {n_or(rc['narrowed_size'])}명)과 실험 10 P60 풀({n_or(rc['p60_size'])}명) 안에 몇 명 있는가.", "",
          "| 시나리오 | K 편성 니케 | PN 좁힌 60 안 | P60 풀 안 |", "|---|---:|---:|---:|"]
    for s, v in rc["per"].items():
        L.append(f"| {s} {a['names'].get(s, '')} | {v['total']} | {n_or(v['narrowed'])} | {n_or(v['p60'])} |")
    L.append(f"| 중앙 | | {n_or(rc['median_narrowed'], 1)} | {n_or(rc['median_p60'], 1)} |")
    # ---- 표 9
    L += ["", "## 9. 대안 5덱 (예산 2,000, 시나리오 중앙)", "",
          "최선과 덱 2개 이하 공유(실험 9 정의). 비율 = 대안 합 / 최선 합. 니케 공유 20명 이하 대안은 이번 회차에 계산하지 않았다(README).", "",
          "| 기법 | 있음 | 최선 대비 | 공유 니케 |", "|---|---:|---:|---:|"]
    for r in a["alt"]:
        L.append(f"| {r['method']} | {r['alt']['found']}/{r['n']} | {ratio(r['alt']['ratio'])} | {n_or(r['shared'])}/25 |")
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
    ap.add_argument("--runs", type=Path, help="새 실행 요약 dir(<시나리오>_P177_<기법>_<예산>.json)")
    ap.add_argument("--summary", type=Path, help="모은 요약 jsonl(한 줄 = {\"run\": 이름, **요약})")
    ap.add_argument("--exp10-log", type=Path, default=EXP10_LOG, help="실험 10 run_log(val177_summary.jsonl · precompute_P177.json)")
    ap.add_argument("--precompute", type=Path, help="precompute_PB15 · PB30 · PN · PM .json dir(기본: --runs dir)")
    ap.add_argument("--pool-json", type=Path, default=POOL_JSON, help="P60 풀 파일(02_score_distribution/pool.json)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--meta", type=Path, help="실행 메모 JSON(평가기 · 시뮬 수 등)")
    args = ap.parse_args(argv)
    layers = [("실험 10 기록", load_jsonl(args.exp10_log, (BASE, REF)) if args.exp10_log else {})]
    if args.summary:
        layers.append((f"요약 {args.summary.name}", load_jsonl(args.summary)))
    if args.runs:
        layers.append((f"실행 {args.runs.name}", load_dir(args.runs)))
    runs = merge_runs(layers)
    pre = load_precompute([args.precompute or args.runs, args.summary.parent if args.summary else None], args.exp10_log)
    a = analyze(runs, pre, load_pool_names(args.pool_json))
    if a["missing"]:
        _warn(f"빠진 실행 {len(a['missing'])}개: {a['missing'][:6]}{' …' if len(a['missing']) > 6 else ''}")
    meta = json.loads(args.meta.read_text(encoding="utf-8")) if args.meta else None
    args.out.write_text(render(a, meta), encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(a, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"q1": {k: a["q1"][k] for k in ("line", "pick", "names")}, "q2_default": a["q2"]["default"],
                      "q2_eligible": a["q2"]["eligible"], "missing": len(a["missing"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
