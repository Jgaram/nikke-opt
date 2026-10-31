"""실험 16 분석 — README §잴 것 · §판단 기준(사전 등록).

    python experiments/16_control_miss/analyze16.py --log experiments/16_control_miss/run_log
        --out experiments/16_control_miss/results.md [--json <dir>/analysis.json]

- 기본 레이어 값 B는 실험 13 U4 · 2,000 기록, 컨트롤 최선 J는 `jobs/`(M3:k2 200평가)의 best_damage.
  S4 구성은 계정 기록에 없으므로 B = 그 작업의 base_damage(바꾸지 않음 = 기본 레이어)다.
- 5덱 조립은 실험 9 `repack_post`와 같다: 컨트롤을 찾은 구성은 max(B, J), 나머지는 B.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run16 as R  # noqa: E402

E8 = R.E8
LOSS = 0.003          # 놓침 문턱(임시)
BIG = 0.01            # 큰 놓침
N_SCEN = 8
Z90 = 1.6448536269514722
AXES = ("click", "reload", "cover", "cancel", "burst", "camera", "tactic")
OUTSIDE = ("S1", "S2", "S3", "S4")
MEASURED_SETS = {"P5": ("S0",), "P10": ("S0", "S0p"), "Pstar": R.LAYERS}


# ---------------------------------------------------------------- 통계 도구

def ranks(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else None


def wilson(k: int, n: int, z: float = Z90) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def pct(xs: Sequence[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        return float("nan")
    i = (len(s) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def axes_of(labels: Iterable[str]) -> list[str]:
    out = []
    for lb in labels:
        for ax in AXES:
            if f":{ax}:" in lb:
                out.append(ax)
                break
    return out


# ---------------------------------------------------------------- 시나리오 하나

def scenario_values(best: Mapping[frozenset, tuple[float, tuple]], measured: Mapping[str, Sequence[Mapping[str, Any]]],
                    layers: Iterable[str]) -> dict[frozenset, tuple[float, tuple]]:
    """고른 층의 컨트롤 결과를 반영한 구성 값. measured: 층 → 작업 결과(B · J · squad)."""
    vals = dict(best)
    for lay in layers:
        for r in measured.get(lay, ()):
            c = frozenset(r["squad"])
            b = vals[c][0] if c in vals else r["B"]
            vals[c] = (max(b, r["J"]), tuple(r["squad"]))
    return vals


def scenario(sid: str, tgt: Mapping[str, Any], best: Mapping[frozenset, tuple[float, tuple]],
             jobs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    measured: dict[str, list[dict[str, Any]]] = {}
    missing: Counter = Counter()
    for lay in R.LAYERS:
        for e in tgt["layers"][lay]:
            j = jobs.get(R.comp_id(sid, e["squad"]))
            if j is None or j.get("best_damage") is None:
                missing[lay] += 1
                continue
            b = e["B"] if e["B"] is not None else j["base_damage"] / E8
            jv = j["best_damage"] / E8
            measured.setdefault(lay, []).append({
                "squad": e["squad"], "B": b, "J": jv, "g": jv / b - 1, "frame": e["frame"], "rank": e["frame_rank"],
                "half": e.get("half"), "axes": axes_of(j["best_variants"]), "variants": j["best_variants"],
                "B_pre": e.get("B_pre"), "base_match": e["B"] is None or j["base_damage"] == round(e["B"] * E8)})
    p0 = R.R9.pack_vals(best)
    packs = {k: R.R9.pack_vals(scenario_values(best, measured, lays)) for k, lays in MEASURED_SETS.items()}
    tot = {k: v[0] for k, v in packs.items()}
    tot["P0"] = p0[0]
    lay_of = {frozenset(r["squad"]): lay for lay, rs in measured.items() for r in rs}
    ctrl = {frozenset(r["squad"]): r for rs in measured.values() for r in rs}
    p10_decks = {frozenset(sq) for _, sq in packs["P10"][1]}
    star = []
    for v, sq in packs["Pstar"][1]:
        c = frozenset(sq)
        r = ctrl.get(c)
        star.append({"squad": list(sq), "value": v, "layer": lay_of.get(c, "미측정"),
                     "controlled": r is not None and r["J"] > r["B"] and abs(v - r["J"]) < 1e-9,
                     "in_P10": c in p10_decks, "g": r["g"] if r else None})
    missed = [d for d in star if d["layer"] in OUTSIDE and d["controlled"]]
    w5 = min(v for v, _ in packs["P5"][1])
    sizes = tgt["sizes"]
    enter = {}
    for lay, rs in measured.items():
        if lay == "S1":
            parts = [(h, [r for r in rs if r["half"] == h], sizes[f"S1_{h}"]) for h in ("up", "lo")]
        else:
            parts = [(None, rs, sizes[lay])]
        exp_n = lo_n = hi_n = 0.0
        k_all = n_all = 0
        for _, sub, size in parts:
            k = sum(r["J"] >= w5 for r in sub)
            n = len(sub)
            k_all += k
            n_all += n
            if n:
                lo, hi = wilson(k, n)
                exp_n += k / n * size
                lo_n += lo * size
                hi_n += hi * size
        enter[lay] = {"k": k_all, "n": n_all, "size": sum(p[2] for p in parts), "expected": exp_n,
                      "ci90": [lo_n, hi_n] if lay in ("S1", "S2", "S3", "S4") else [exp_n, exp_n]}
    return {
        "scenario": sid, "name": tgt["name"], "m": tgt["m"], "totals": tot,
        "P0_record": tgt["P0_record"], "L": tot["Pstar"] / tot["P5"] - 1, "L10": tot["P10"] / tot["P5"] - 1,
        "Lout": tot["Pstar"] / tot["P10"] - 1, "P5_vs_P0": tot["P5"] / tot["P0"] - 1, "w5": w5,
        "star": star, "missed": missed, "enter": enter, "missing": dict(missing),
        "measured": measured, "base_mismatch": sum(not r["base_match"] for rs in measured.values() for r in rs)}


# ---------------------------------------------------------------- 판단

def judge(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """README §판단 기준(사전 등록). rows: 시나리오별 L · Lout · missed."""
    if len(rows) != N_SCEN or any(r["missing"] for r in rows):
        return {"case": None, "verdict": "판단 불가(시나리오 8개 전부 · 모든 층 측정이 아님)"}
    L = [r["L"] for r in rows]
    Lo = [r["Lout"] for r in rows]
    med_L, med_Lo = statistics.median(L), statistics.median(Lo)
    big_L, big_Lo = sum(x >= BIG for x in L), sum(x >= BIG for x in Lo)
    src = Counter(d["layer"] for r in rows for d in r["missed"])
    base = {"median_L": med_L, "big_L": big_L, "median_Lout": med_Lo, "big_Lout": big_Lo, "missed_by_layer": dict(src)}
    if med_L < LOSS and big_L <= 1:
        return {**base, "case": 1, "verdict": "지금 후처리로 충분(측정 범위 안)"}
    if med_Lo < LOSS and big_Lo <= 1:
        return {**base, "case": 2, "verdict": "후처리 대상만 넓히면 된다"}
    s1 = src["S1"]
    rest = src["S2"] + src["S3"] + src["S4"]
    if s1 + rest == 0:
        return {**base, "case": None, "verdict": "판단 불가(Lout은 크지만 컨트롤로 들어온 S1~S4 구성이 없다)"}
    if s1 >= rest:
        return {**base, "case": 3, "verdict": "상위권 근처의 예외를 기본 레이어 순위가 못 고른다"}
    return {**base, "case": 4, "verdict": "기본 레이어 탐색이 구조적으로 놓친다"}


NEXT = {1: "틀별 상위 5 후처리를 계정 흐름의 기본으로 넣고 큐브(2단계) 등으로 넘어간다",
        2: "기본을 틀별 상위 10 후처리로 바꾸고 다음 회차 A로 비용을 줄인다",
        3: "다음 회차 A(후처리 대상 고르기)", 4: "다음 회차 B(조합 탐색 중 컨트롤 탐침)"}


# ---------------------------------------------------------------- 입출력

def load_jobs(d: Path) -> dict[str, dict[str, Any]]:
    out = {}
    for p in sorted(d.glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        out[r["comp_id"]] = r
    return out


def analyze(log: Path) -> dict[str, Any]:
    targets = json.loads((log / "targets.json").read_text(encoding="utf-8"))
    jobs = load_jobs(log / "jobs")
    sids = list(targets["scenarios"])
    runs = R.load_runs(wanted=[targets["scenarios"][s]["run"] for s in sids])
    rows = []
    deck = json.loads((log / "deckpost.json").read_text(encoding="utf-8")) if (log / "deckpost.json").exists() else None
    obs = []
    for sid in sids:
        t = targets["scenarios"][sid]
        best = R.R9.book_of(runs[t["run"]])
        rows.append(scenario(sid, t, best, jobs))
        if deck is not None:
            obs.append(deck_obs(sid, rows[-1], best, jobs, deck[sid]))
    sims = [json.loads(x) for x in (log / "control_log.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    return {"rows": rows, "judge": judge(rows), "sims": sum(s["sims"] for s in sims), "runs": sims,
            "jobs": len(jobs), "deck": obs}


def deck_obs(sid: str, row: Mapping[str, Any], best: Mapping[frozenset, tuple[float, tuple]],
             jobs: Mapping[str, Mapping[str, Any]], deck: Mapping[str, Any]) -> dict[str, Any]:
    """관찰(결과를 본 뒤 추가, 판단에 쓰지 않음): 5덱 구성 후처리 D0 · D5 · D* 와 측정한 모든 구성을 반영한 P_all."""
    mine = [j for c, j in jobs.items() if c.startswith(sid + "|")]
    p_all, ch = R.R9.pack_vals(R.measured_values(best, mine))
    out = {"scenario": sid, "P5": row["totals"]["P5"], "Pstar": row["totals"]["Pstar"], "Pall": p_all,
           "Pall_unmeasured": sum(R.comp_id(sid, sq) not in jobs for _, sq in ch)}
    for k in R.DECK_BASES:
        if k in deck:
            out[k] = {"total": deck[k]["total"], "jobs_added": len(deck[k]["extra"]), "complete": deck[k]["complete"],
                      "rounds": len(deck[k]["rounds"]) - 1}
    return out


def f_pct(x: float | None, d: int = 2) -> str:
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:+.{d}f}%"


def render(a: Mapping[str, Any]) -> str:
    rows, jd = a["rows"], a["judge"]
    out = ["# 실험 16 결과 표", "", "`analyze16.py`가 만든다. 값은 억(5덱 합) · 이득은 J/B − 1. 판단 규칙은 README §판단 기준(사전 등록).", ""]
    out += [f"**판단: {jd['case'] or '—'}. {jd['verdict']}**" + (f" → {NEXT[jd['case']]}" if jd.get("case") else ""), ""]
    if "median_L" in jd:
        out += [f"- L 중앙 {f_pct(jd['median_L'])}, L ≥ +1% 시나리오 {jd['big_L']}개 · Lout 중앙 {f_pct(jd['median_Lout'])}, "
                f"Lout ≥ +1% 시나리오 {jd['big_Lout']}개 · 컨트롤로 P\\* 5덱에 들어온 S0 · S0′ 밖 구성(층별) {jd['missed_by_layer'] or '없음'}",
                f"- 측정 구성 {a['jobs']}개, 이번 실험 새 시뮬 {a['sims']:,}회(control_log 합)", ""]
    out += ["## 시나리오별 5덱 합", "",
            "| 시나리오 | P0 | P5 | P10 | P\\* | P5/P0 | L | L10 | Lout | P\\* 5덱 새 구성(층 · g) |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in rows:
        t = r["totals"]
        new = ", ".join(f"{d['layer']} {f_pct(d['g'], 1)}" for d in r["star"] if not d["in_P10"]) or "—"
        out.append(f"| {r['scenario']} {r['name']} | {t['P0']:.2f} | {t['P5']:.2f} | {t['P10']:.2f} | {t['Pstar']:.2f} | "
                   f"{f_pct(r['P5_vs_P0'])} | {f_pct(r['L'])} | {f_pct(r['L10'])} | {f_pct(r['Lout'])} | {new} |")
    out += ["", "## 층별 이득 분포(8개 시나리오 합)", "",
            "| 층 | 구성 | g 중앙 | 90백분위 | 최대 | g ≥ +10% | g ≥ +20% | J ≥ w5 | Spearman(B, J) 중앙 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for lay in R.LAYERS:
        gs = [x["g"] for r in rows for x in r["measured"].get(lay, ())]
        if not gs:
            continue
        k = sum(r["enter"].get(lay, {}).get("k", 0) for r in rows)
        sp = [spearman([x["B"] for x in r["measured"][lay]], [x["J"] for x in r["measured"][lay]])
              for r in rows if lay in r["measured"]]
        sp = [s for s in sp if s is not None]
        sp_s = f"{statistics.median(sp):.2f}" if sp else "—"
        out.append(f"| {lay} | {len(gs)} | {f_pct(statistics.median(gs), 1)} | {f_pct(pct(gs, 0.9), 1)} | {f_pct(max(gs), 1)} | "
                   f"{sum(g >= 0.1 for g in gs)} | {sum(g >= 0.2 for g in gs)} | {k} | {sp_s} |")
    out += ["", "## 층별 「들어올 수 있는」 구성 — J ≥ w5(P5 5덱 중 가장 약한 덱), 시나리오당 기대 개수(90% 구간)", "",
            "| 시나리오 | w5 | " + " | ".join(R.LAYERS) + " |", "|---|---:|" + "---:|" * len(R.LAYERS)]
    for r in rows:
        cells = []
        for lay in R.LAYERS:
            e = r["enter"].get(lay)
            if not e:
                cells.append("—")
            elif lay in ("S0", "S0p"):
                cells.append(f"{e['k']}/{e['n']}")
            else:
                cells.append(f"{e['k']}/{e['n']} → {e['expected']:.0f} ({e['ci90'][0]:.0f}~{e['ci90'][1]:.0f}) / {e['size']}")
        out.append(f"| {r['scenario']} | {r['w5']:.2f} | " + " | ".join(cells) + " |")
    big = sorted((x for r in rows for rs in r["measured"].values() for x in rs), key=lambda x: -x["g"])[:15]
    lay_of = {(r["scenario"], tuple(x["squad"])): lay for r in rows for lay, rs in r["measured"].items() for x in rs}
    sid_of = {id(x): r["scenario"] for r in rows for rs in r["measured"].values() for x in rs}
    out += ["", "## 이득이 큰 구성 상위 15", "", "| 시나리오 | 층 | 틀 | 틀 순위 | B | J | g | 이득 축 |", "|---|---|---|---:|---:|---:|---:|---|"]
    for x in big:
        sid = sid_of[id(x)]
        out.append(f"| {sid} | {lay_of[(sid, tuple(x['squad']))]} | {x['frame']} | {x['rank'] or '—'} | {x['B']:.2f} | {x['J']:.2f} | "
                   f"{f_pct(x['g'], 1)} | {', '.join(sorted(set(x['axes']))) or '—'} |")
    ax = Counter(a_ for r in rows for rs in r["measured"].values() for x in rs if x["g"] >= 0.05 for a_ in set(x["axes"]))
    ax_all = Counter(a_ for r in rows for rs in r["measured"].values() for x in rs for a_ in set(x["axes"]))
    n_all = sum(len(rs) for r in rows for rs in r["measured"].values())
    n_big = sum(x["g"] >= 0.05 for r in rows for rs in r["measured"].values() for x in rs)
    out += ["", f"## 이득 축 — 최선 컨트롤에 그 축 선택지가 든 구성 수(전체 {n_all} · g ≥ +5% {n_big})", "",
            "| 축 | 전체 | g ≥ +5% |", "|---|---:|---:|"]
    for a_ in AXES:
        out.append(f"| {a_} | {ax_all[a_]} | {ax[a_]} |")
    if a.get("deck"):
        ob = a["deck"]
        out += ["", "## 관찰(결과를 본 뒤 추가, 판단에 쓰지 않음) — 5덱 구성 후처리", "",
                "5덱 조립 → 컨트롤을 안 찾은 5덱 구성에 M3:k2 → 다시 조립을 반복(최대 4번). D0 = 5덱 구성만, D5 = S0 + 5덱 구성, "
                "D\\* = 측정한 모든 층 + 5덱 구성. P_all = 측정한 모든 구성(층 + 5덱 구성)을 반영한 5덱(측정 범위 안의 최선).", "",
                "| 시나리오 | P5 | D0 (작업) | D5 (+작업) | D\\* | P_all | D0/P5 | D5/P5 | P_all/D0 | P_all/D5 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for o in ob:
            out.append(f"| {o['scenario']} | {o['P5']:.2f} | {o['D0']['total']:.2f} ({o['D0']['jobs_added']}) | "
                       f"{o['D5']['total']:.2f} (+{o['D5']['jobs_added']}) | {o['Dstar']['total']:.2f} | {o['Pall']:.2f} | "
                       f"{f_pct(o['D0']['total'] / o['P5'] - 1)} | {f_pct(o['D5']['total'] / o['P5'] - 1)} | "
                       f"{f_pct(o['Pall'] / o['D0']['total'] - 1)} | {f_pct(o['Pall'] / o['D5']['total'] - 1)} |")
        med = lambda f: statistics.median(f(o) for o in ob)  # noqa: E731
        out += ["", f"- 중앙: D0/P5 {f_pct(med(lambda o: o['D0']['total'] / o['P5'] - 1))} · D5/P5 {f_pct(med(lambda o: o['D5']['total'] / o['P5'] - 1))} · "
                f"P_all/P5 {f_pct(med(lambda o: o['Pall'] / o['P5'] - 1))} · P_all/D0 {f_pct(med(lambda o: o['Pall'] / o['D0']['total'] - 1))} · "
                f"P_all/D5 {f_pct(med(lambda o: o['Pall'] / o['D5']['total'] - 1))}. "
                f"모두 1번 반복으로 수렴: {all(o[k]['complete'] and o[k]['rounds'] == 1 for o in ob for k in ('D0', 'D5', 'Dstar'))}. "
                f"P_all 5덱에 컨트롤을 안 찾은 구성: {sum(o['Pall_unmeasured'] for o in ob)}개."]
    mm = sum(r["base_mismatch"] for r in rows)
    miss = {r["scenario"]: r["missing"] for r in rows if r["missing"]}
    out += ["", f"- 기본 레이어 값 재현: 기록 B와 작업 첫 평가가 다른 구성 {mm}개. 측정 못 한 구성: {miss or '없음'}.", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", type=Path, default=HERE / "run_log")
    ap.add_argument("--out", type=Path, default=HERE / "results.md")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    a = analyze(args.log)
    args.out.write_text(render(a), encoding="utf-8")
    if args.json:
        slim = {"judge": a["judge"], "sims": a["sims"], "jobs": a["jobs"], "deck": a.get("deck"),
                "rows": [{k: v for k, v in r.items() if k != "measured"} for r in a["rows"]]}
        args.json.write_text(json.dumps(slim, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(a["judge"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
