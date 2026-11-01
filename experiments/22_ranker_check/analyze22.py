"""실험 22 분석 — README §지표 · §판단 기준 그대로.

    python experiments/22_ranker_check/analyze22.py     → results.md · run_log/analysis.json

입력: seasons.json, run_log/precompute_S<k>_<보스>.json(우리 최선 5덱), run_log/members_*.json(우리 덱 니케별 딜, 없으면 주력 생략),
run_log/rankers_S<k>.json(랭커 덱 시뮬 값). 시뮬은 하지 않는다.
"""

from __future__ import annotations

import importlib.util
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
LOG = HERE / "run_log"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R22 = sys.modules.get("run22") or _load("run22", HERE / "run22.py")
R9 = R22.R9
BOSSES = tuple(R22.BOSSES)
N25_MIN, V_MIN = 15, 0.90          # README §판단 기준(사전 등록)


def load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main_dealer(members: list[list]) -> str:
    return max(members, key=lambda m: (m[1], m[0]))[0]


def five_value(squads: list[list[str]], vals: dict[str, dict], boss: str) -> float | None:
    out = 0.0
    for q in squads:
        v = vals.get(",".join(q), {}).get(boss)
        if v is None:
            return None
        out += v
    return out


def season_metrics(s: int) -> dict[str, Any]:
    v = R22.season(s)
    rk = v["rankers"]
    top25 = [n for n, _ in rk["units"][:25]]
    rsq = [set(q["members"]) for q in rk["squads"]]
    rv = (load(LOG / f"rankers_S{s:02d}.json") or {}).get("squads", {})
    base = v["baseline"]
    out: dict[str, Any] = {"season": s, "boss_name": v["boss"], "code": v["code"], "weak": v["weak"], "pool": len(v["pool"]),
                           "top25": top25, "N25_prev": len(set(base["prev"]["top25"]) & set(top25)),
                           "N25_same": len(set(base["same"]["top25"]) & set(top25)) if "same" in base else None,
                           "same_season": base.get("same", {}).get("season"), "by_boss": {}}
    for b in BOSSES:
        pre = load(LOG / f"precompute_{R22.run_name(s, b)}.json")
        if pre is None:
            continue
        ours = [list(sq) for _, sq in pre["final"]["squads"]]
        total = pre["final"]["total"]
        our25 = {n for sq in ours for n in sq}
        best_match = [max(len(set(sq) & q) for q in rsq) for sq in ours]
        pack_in = {frozenset(k.split(",")): (e[b], tuple(k.split(","))) for k, e in rv.items() if e.get(b) is not None}
        pv, _ = R9.pack_vals(pack_in) if len(pack_in) >= 5 else (None, [])
        vt, vr1 = five_value(rk["top_five"]["squads"], rv, b), five_value(rk["rank1"]["squads"], rv, b)
        m: dict[str, Any] = {
            "total": total, "evals": pre["evals"], "sims": pre["sims"], "seconds": pre["seconds"], "squads": ours,
            "N25": len(our25 & set(top25)), "D4": sum(x >= 4 for x in best_match), "match": best_match,
            "V_top": None if vt is None else vt / total, "V_r1": None if vr1 is None else vr1 / total,
            "V_pack": None if pv is None else pv / total,
            "ours_only": sorted(our25 - set(top25)), "rankers_only": [n for n in top25 if n not in our25],
        }
        mem = load(LOG / f"members_{R22.run_name(s, b)}.json")
        if mem:
            ours_main = [main_dealer(r["members"]) for r in mem["squads"]]
            rk_main = Counter()
            for q in rk["squads"]:
                e = rv.get(",".join(q["order"]), {})
                if e.get(f"{b}_members"):
                    rk_main[main_dealer(e[f"{b}_members"])] += q["count"]
            m["main_ours"] = ours_main
            m["main_rankers"] = rk_main.most_common(8)
            m["main_overlap"] = sum(d in rk_main for d in ours_main)
        out["by_boss"][b] = m
    if len(out["by_boss"]) == len(BOSSES):
        key = lambda b: (out["by_boss"][b]["N25"], out["by_boss"][b]["D4"], out["by_boss"][b]["V_top"] or 0.0)
        out["better"] = max(BOSSES, key=key)
        out["tie"] = key(BOSSES[0]) == key(BOSSES[1])
    return out


def med(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def judge(rows: list[dict[str, Any]]) -> dict[str, Any]:
    done = [r for r in rows if "better" in r]
    n25 = med([r["by_boss"][r["better"]]["N25"] for r in done])
    vt = med([r["by_boss"][r["better"]]["V_top"] for r in done])
    a, b = n25 is not None and n25 >= N25_MIN, vt is not None and vt >= V_MIN
    verdict = "얼추 비슷" if a and b else "일부 다름" if a or b else "다름"
    return {"seasons": len(done), "N25_med": n25, "V_top_med": vt, "n25_ok": a, "v_ok": b, "verdict": verdict,
            "better_count": Counter(r["better"] for r in done), "ties": sum(r["tie"] for r in done),
            "per_boss": {bb: {"N25_med": med([r["by_boss"][bb]["N25"] for r in done]),
                              "D4_med": med([r["by_boss"][bb]["D4"] for r in done]),
                              "V_top_med": med([r["by_boss"][bb]["V_top"] for r in done]),
                              "V_pack_med": med([r["by_boss"][bb]["V_pack"] for r in done])} for bb in BOSSES},
            "N25_prev_med": med([r["N25_prev"] for r in done]), "N25_same_med": med([r["N25_same"] for r in done])}


def pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f}%"


def write_md(rows: list[dict[str, Any]], j: dict[str, Any]) -> str:
    L = ["# 실험 22 결과 (analyze22.py가 만든 표)", "",
         f"**판단: {j['verdict']}** — 시즌마다 더 맞는 보스의 N25 중앙 {j['N25_med']} (기준 ≥ {N25_MIN}), V_top 중앙 {pct(j['V_top_med'])} (기준 ≥ {pct(V_MIN)}), 시즌 {j['seasons']}개.",
         f"더 맞는 보스: " + " · ".join(f"{b} {j['better_count'].get(b, 0)}" for b in BOSSES) + f" (N25 · D4 · V_top 모두 같은 시즌 {j['ties']}).",
         f"비교 눈금: 랭커끼리 N25_prev 중앙 {j['N25_prev_med']} · N25_same 중앙 {j['N25_same_med']}.", "",
         "## 시즌 × 보스", "",
         "| 시즌 | 보스 · 약점 | 풀 | 보스 | 우리 합(억) | N25 | D4 | V_top | V_r1 | V_pack | 주력 겹침 | N25_prev · same |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        for b, m in r["by_boss"].items():
            mark = " ◀" if r.get("better") == b else ""
            L.append(f"| {r['season']} | {r['boss_name']} · {r['weak']} | {r['pool']} | {b}{mark} | {m['total']:.1f} | {m['N25']} | {m['D4']} | "
                     f"{pct(m['V_top'])} | {pct(m['V_r1'])} | {pct(m['V_pack'])} | {m.get('main_overlap', '—')}/5 | "
                     f"{r['N25_prev']} · {r['N25_same']} (S{r['same_season']}) |")
    L += ["", "◀ = 그 시즌에 더 맞는 보스(N25 → D4 → V_top 순).", "", "## 보스별 중앙", "",
          "| 보스 | N25 | D4 | V_top | V_pack |", "|---|---|---|---|---|"]
    for b, x in j["per_boss"].items():
        L.append(f"| {b} | {x['N25_med']} | {x['D4_med']} | {pct(x['V_top_med'])} | {pct(x['V_pack_med'])} |")
    oo, ro = Counter(), Counter()
    for r in rows:
        if "better" in r:
            m = r["by_boss"][r["better"]]
            oo.update(m["ours_only"])
            ro.update(m["rankers_only"])
    L += ["", "## 니케 단위 차이 (더 맞는 보스, 시즌 수)", "",
          "- 우리만 쓰는 니케: " + ", ".join(f"{n} {c}" for n, c in oo.most_common(15)),
          "- 랭커 상위 25인데 우리가 안 쓴 니케: " + ", ".join(f"{n} {c}" for n, c in ro.most_common(15)), "",
          "## 시즌별 덱", ""]
    for r in rows:
        if "better" not in r:
            continue
        b = r["better"]
        m = r["by_boss"][b]
        L.append(f"### S{r['season']} {r['boss_name']} ({r['code']} · 약점 {r['weak']}) — {b}")
        L.append("")
        for sq, x in zip(m["squads"], m["match"]):
            L.append(f"- 우리: {', '.join(sq)} (랭커 상위 40과 최대 {x}명 같음)")
        tf = R22.season(r["season"])["rankers"]["top_five"]
        L.append(f"- 랭커 대표 5덱({tf['count']}명): " + " / ".join(", ".join(q) for q in tf["squads"]))
        if m.get("main_ours"):
            L.append(f"- 주력: 우리 {', '.join(m['main_ours'])} · 랭커 {', '.join(n for n, _ in m['main_rankers'][:6])}")
        L.append("")
    return "\n".join(L) + "\n"


def main() -> int:
    rows = [season_metrics(s) for s in sorted(int(k) for k in R22.SEASON_DATA)]
    j = judge(rows)
    (HERE / "results.md").write_text(write_md(rows, j), encoding="utf-8")
    LOG.mkdir(parents=True, exist_ok=True)
    (LOG / "analysis.json").write_text(json.dumps({"judge": {**j, "better_count": dict(j["better_count"])}, "seasons": rows},
                                                  ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"판단 {j['verdict']}: N25 중앙 {j['N25_med']} · V_top 중앙 {pct(j['V_top_med'])} · 시즌 {j['seasons']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
