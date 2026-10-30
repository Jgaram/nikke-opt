"""실험 8 분석 — 후처리(S, K)의 재현율 · 비용과 사전 등록한 판단 기준 (README §잴 것 · §판단 기준).

    python experiments/08_control_postproc/analyze8.py --runs <joint dir> --reload <reload dir> --out results.md [--json r.json]

- J(c) = `<runs>/<id>.done`의 best_damage, L(c) = `<runs>/<id>.jsonl`의 step 0, 시뮬 = 그 기록의 줄 수(평가 수 — 빈 캐시에서
  혼자 돌렸을 때의 시뮬 수. 시운전 8개가 캐시로 다시 읽혀 `cached`로 세면 0이 된다).
- S2(c) = `<reload>/reload_eval.jsonl`의 total_damage.
- 순위의 동률은 id 순. 표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXP6 = HERE.parent / "06_control_menu"
EXP7 = HERE.parent / "07_control_search"
KS = (10, 20, 40, 80)
TOP = 10
RECALL_MIN = 0.9   # 판단 기준: 재현율 이 값 이상
K_MAX = 40         # 판단 기준: 이 K 이하에서
RECALL_FLOOR = 0.7  # K = 80에서 이 값 미만이면 순위 변화가 크다
VALUE_MIN = 0.995  # 보조: 값 기준 재현
SKEL_TOP = 3
MISSED_K = 40


# ---------------------------------------------------------------- 지표

def ranked(values: Mapping[str, int | float]) -> list[str]:
    """값 내림차순, 동률은 id 순."""
    return sorted(values, key=lambda i: (-values[i], i))


def avg_ranks(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for t in range(i, j + 1):
            r[order[t]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    ra, rb = avg_ranks(a), avg_ranks(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else float("nan")


def postproc(S: Mapping[str, int], J: Mapping[str, int], sims: Mapping[str, int], k: int,
             top: int = TOP, overlap: int = 0) -> dict[str, Any]:
    """S 상위 k개에만 컨트롤 탐색을 붙였을 때의 지표. S · J는 같은 id 집합.
    `overlap` = 1차 평가가 컨트롤 탐색의 첫 평가(기본 레이어)와 같은 요청이면 1(S1), 아니면 0(S2)."""
    sk = ranked(S)[:k]
    jr = ranked(J)
    t = jr[:top]
    found = set(sk)
    pp = ranked({i: J[i] for i in sk})[:top]
    ratios = [J[pp[i]] / J[t[i]] if i < len(pp) else 0.0 for i in range(min(top, len(t)))]
    return {
        "k": k,
        "recall": sum(1 for i in t if i in found) / len(t),
        "hits": sum(1 for i in t if i in found),
        "top1_in": jr[0] in found,
        "top1_ratio": max(J[i] for i in sk) / J[jr[0]],
        "value_min": min(ratios),
        "cost": len(S) + sum(sims[i] - overlap for i in sk),  # 1차 순위 1회씩 + 상위 k의 컨트롤 탐색
        "missed": [i for i in t if i not in found],
    }


def skeleton_recall(S: Mapping[str, int], J: Mapping[str, int], skel: Mapping[str, str], k: int,
                    top: int = SKEL_TOP) -> dict[str, tuple[int, int]]:
    """틀마다 J 상위 top개 중 S 상위 k(전체 순위)에 든 수 / 그 틀의 상위 수."""
    found = set(ranked(S)[:k])
    out = {}
    for sk in sorted(set(skel.values())):
        ids = ranked({i: J[i] for i in J if skel[i] == sk})[:top]
        out[sk] = (sum(1 for i in ids if i in found), len(ids))
    return out


def recall_meets(rows: Sequence[Mapping[str, Any]]) -> int | None:
    """재현율 ≥ RECALL_MIN인 가장 작은 K(≤ K_MAX). 없으면 None."""
    ok = [r["k"] for r in rows if r["k"] <= K_MAX and r["recall"] >= RECALL_MIN]
    return min(ok) if ok else None


def judge(rows1: Sequence[Mapping[str, Any]], rows2: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """사전 등록 판단 — 1(S1 후처리) · 2(S2 후처리) · 3(공동 탐색 설계)."""
    k1, k2 = recall_meets(rows1), recall_meets(rows2)
    r80 = {name: next((r["recall"] for r in rows if r["k"] == 80), None) for name, rows in (("S1", rows1), ("S2", rows2))}
    if k1 is not None and (k2 is None or k1 <= k2):
        line, k = 1, k1
    elif k2 is not None:
        line, k = 2, k2
    else:
        line, k = 3, None
    weak = all(v is not None and v < RECALL_FLOOR for v in r80.values())
    return {"line": line, "k": k, "k_s1": k1, "k_s2": k2, "recall80": r80, "large_change": weak}


# ---------------------------------------------------------------- 읽기

def load_runs(d: Path) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, list[str]]]:
    """→ (J, L, sims, best_variants). 오류 후보(L 또는 J 없음)는 뺀다."""
    J, L, sims, best = {}, {}, {}, {}
    for p in sorted(d.glob("*.done")):
        s = json.loads(p.read_text(encoding="utf-8"))
        cid = s["comp_id"]
        n, first = 0, None
        with open(d / f"{cid}.jsonl", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r["step"] == 0:
                    first = r["total_damage"]
                n += 1
        if s.get("best_damage") is None or first is None:
            continue
        J[cid], L[cid], sims[cid], best[cid] = s["best_damage"], first, n, s["best_variants"]
    return J, L, sims, best


def load_reload(d: Path) -> tuple[dict[str, int], int, int]:
    """→ (S2, 시뮬 수, 재사용 수)."""
    S2, n_sim, n_reuse = {}, 0, 0
    with open(d / "reload_eval.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["reused"]:
                n_reuse += 1
            elif not r.get("cached"):
                n_sim += 1
            if r["total_damage"] is not None:
                S2[r["comp_id"]] = r["total_damage"]
    return S2, n_sim, n_reuse


def _records(paths: Iterable[Path]) -> Iterable[dict[str, Any]]:
    for p in paths:
        if not p.exists():
            continue
        op = gzip.open if p.suffix == ".gz" else open
        with op(p, "rt", encoding="utf-8") as f:
            for line in f:
                yield json.loads(line)


def prior_best() -> dict[frozenset, tuple[str, int]]:
    """실험 6 · 7 기록의 조합(구성) → (id, 최선 총딜). J의 신뢰도 확인용.
    실험 6의 `fixed_layer`(버스트 게이지 `fixed`)는 조건이 달라 뺀다."""
    comps = {}
    for path in (EXP6 / "compositions.json", EXP7 / "val_compositions.json"):
        for c in json.loads(path.read_text(encoding="utf-8")):
            comps[c["id"]] = frozenset(c["squad"])
    best: dict[str, int] = {}
    paths = [EXP6 / "run_log" / "main.jsonl.gz"] + sorted((EXP7 / "run_log").glob("*.jsonl.gz"))
    for r in _records(paths):
        d = r.get("total_damage")
        if r.get("condition") == "fixed_layer":
            continue
        if d is not None and r["comp_id"] in comps and d > best.get(r["comp_id"], -1):
            best[r["comp_id"]] = d
    return {comps[i]: (i, v) for i, v in best.items()}


# ---------------------------------------------------------------- 보고

def _pct(x: float) -> str:
    return f"{100 * x:.2f}%"


def analyze(cands: Sequence[Mapping[str, Any]], J: Mapping[str, int], L: Mapping[str, int], sims: Mapping[str, int],
            S2: Mapping[str, int], prior: Mapping[frozenset, tuple[str, int]] | None = None) -> dict[str, Any]:
    ids = sorted(set(J) & set(L) & set(S2))
    J = {i: J[i] for i in ids}
    S1 = {i: L[i] for i in ids}
    S2 = {i: S2[i] for i in ids}
    cmap = {c["id"]: c for c in cands}
    skel = {i: cmap[i]["skeleton"] for i in ids}
    rows = {name: [postproc(S, J, sims, k, overlap=ov) for k in KS] for name, S, ov in (("S1", S1, 1), ("S2", S2, 0))}
    jr = ranked(J)
    rank_of = {name: {i: r + 1 for r, i in enumerate(ranked(S))} for name, S in (("S1", S1), ("S2", S2))}
    top = [{"id": i, "rank_j": n + 1, "rank_s1": rank_of["S1"][i], "rank_s2": rank_of["S2"][i], "J": J[i],
            "gain": J[i] / S1[i] - 1, "skeleton": skel[i], "squad": cmap[i]["squad"], "kind": cmap[i]["kind"]}
           for n, i in enumerate(jr[:TOP])]
    rel = []
    for i in ids:
        hit = (prior or {}).get(frozenset(cmap[i]["squad"]))
        if hit:
            rel.append({"id": i, "prior_id": hit[0], "ratio": J[i] / hit[1]})
    gains = [J[i] / S1[i] - 1 for i in ids]
    return {
        "n": len(ids), "excluded": sorted(set(c["id"] for c in cands) - set(ids)),
        "joint_sims": sum(sims[i] for i in ids),
        "spearman": {"S1": spearman([S1[i] for i in ids], [J[i] for i in ids]),
                     "S2": spearman([S2[i] for i in ids], [J[i] for i in ids]),
                     "S1_S2": spearman([S1[i] for i in ids], [S2[i] for i in ids])},
        "gain": {"median": statistics.median(gains), "q3": statistics.quantiles(gains, n=4)[2], "max": max(gains)},
        "s2_vs_s1": statistics.median(S2[i] / S1[i] - 1 for i in ids),
        "rows": rows, "top": top,
        "skeleton": {name: skeleton_recall(S, J, skel, MISSED_K) for name, S in (("S1", S1), ("S2", S2))},
        "reliability": rel, "judge": judge(rows["S1"], rows["S2"]),
    }


def render(a: Mapping[str, Any], meta: Mapping[str, Any]) -> str:
    j = a["judge"]
    out = ["# 실험 8 결과 (analyze8.py 생성 — 손으로 고치지 않는다)", "",
           f"후보 {a['n']}개(제외 {len(a['excluded'])}개{': ' + ', '.join(a['excluded']) if a['excluded'] else ''}) · "
           f"공동 탐색 시뮬 {a['joint_sims']:,}회 · S2 시뮬 {meta.get('s2_sims', 0)}회(재사용 {meta.get('s2_reused', 0)}개)", "",
           "## 판단", "",
           f"- **{j['line']}줄**" + (f" — K = {j['k']}" if j["k"] else "") +
           f". S1 기준 충족 K: {j['k_s1']}, S2 기준 충족 K: {j['k_s2']}, K = 80 재현율 S1 {j['recall80']['S1']:.1f} · S2 {j['recall80']['S2']:.1f}"
           + (" — 둘 다 0.7 미만(순위 변화 큼)" if j["large_change"] else ""), "",
           "## 후처리 재현율과 비용", "",
           "| 1차 순위 | K | 재현율(상위 10) | J 1위 포함 | 상위 K 최선 / J 1위 | 값 기준 재현(최소) | 비용(시뮬) | 공동 탐색 대비 |",
           "|---|---:|---:|---|---:|---:|---:|---:|"]
    for name in ("S1", "S2"):
        for r in a["rows"][name]:
            out.append(f"| {name} | {r['k']} | {r['hits']}/10 | {'예' if r['top1_in'] else '아니오'} | {_pct(r['top1_ratio'])} | "
                       f"{_pct(r['value_min'])} | {r['cost']:,} | {_pct(r['cost'] / a['joint_sims'])} |")
    s = a["spearman"]
    g = a["gain"]
    out += ["", "S2 비용에는 기본값 학습에 쓴 다른 계열의 J(사전 계산)를 넣지 않았다.", "",
            "## 순위 상관과 컨트롤 이득", "",
            f"- Spearman(S1, J) {s['S1']:.3f} · Spearman(S2, J) {s['S2']:.3f} · Spearman(S1, S2) {s['S1_S2']:.3f}",
            f"- 컨트롤 이득 J / S1 − 1: 중앙 {_pct(g['median'])} · 3사분위 {_pct(g['q3'])} · 최대 {_pct(g['max'])}",
            f"- S2 / S1 − 1 중앙 {_pct(a['s2_vs_s1'])}", "",
            "## 공동 탐색 상위 10", "",
            "| J 순위 | id | 틀 | 출처 | S1 순위 | S2 순위 | J(억) | 이득 | 배치 순서 |", "|---:|---|---|---|---:|---:|---:|---:|---|"]
    for t in a["top"]:
        out.append(f"| {t['rank_j']} | {t['id']} | {t['skeleton']} | {t['kind']} | {t['rank_s1']} | {t['rank_s2']} | "
                   f"{t['J'] / 1e8:.2f} | {_pct(t['gain'])} | {' · '.join(t['squad'])} |")
    out += ["", f"## 틀별 상위 {SKEL_TOP}개 재현 (K = {MISSED_K}, 보조)", "", "| 틀 | S1 | S2 |", "|---|---:|---:|"]
    for sk in a["skeleton"]["S1"]:
        h1, n1 = a["skeleton"]["S1"][sk]
        h2, n2 = a["skeleton"]["S2"][sk]
        out.append(f"| {sk} | {h1}/{n1} | {h2}/{n2} |")
    rel = a["reliability"]
    out += ["", "## J의 신뢰도 (실험 6 · 7과 겹치는 후보)", ""]
    if rel:
        rs = sorted(r["ratio"] for r in rel)
        out.append(f"- {len(rel)}개: J / 실험 6 · 7 기록 최선 — 중앙 {_pct(statistics.median(rs))} · 최소 {_pct(rs[0])} · "
                   f"99.5% 이상 {sum(1 for r in rs if r >= 0.995)}개")
        worst = sorted(rel, key=lambda r: r["ratio"])[:5]
        out.append("- 낮은 5개: " + " · ".join(f"{r['id']}({r['prior_id']}) {_pct(r['ratio'])}" for r in worst))
    else:
        out.append("- 겹치는 후보 없음")
    out += ["", "## 평가기", "", f"`{json.dumps(meta.get('evaluator'), ensure_ascii=False)}`", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--reload", type=Path, required=True)
    ap.add_argument("--candidates", type=Path, default=HERE / "candidates.json")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--evaluator", default="", help="평가기 version JSON 문자열(보고용)")
    args = ap.parse_args(argv)
    cands = json.loads(args.candidates.read_text(encoding="utf-8"))
    J, L, sims, _ = load_runs(args.runs)
    S2, n_sim, n_reuse = load_reload(args.reload)
    a = analyze(cands, J, L, sims, S2, prior_best())
    meta = {"s2_sims": n_sim, "s2_reused": n_reuse, "evaluator": json.loads(args.evaluator) if args.evaluator else None}
    args.out.write_text(render(a, meta), encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps({**a, "meta": meta}, ensure_ascii=False, indent=1, default=list) + "\n",
                             encoding="utf-8")
    print(f"판단 {a['judge']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
