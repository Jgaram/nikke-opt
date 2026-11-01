"""실험 23 분석 — 5덱 편성안 유사도(쌍 자카드 · 바꿀 니케 수, `nikke_opt.similarity`)로 기존 결과를 다시 본다. 시뮬은 하지 않는다.

    python experiments/23_deck_similarity/analyze23.py     → results.md · analysis.json

1. 기준표: 25명 5덱에 손댄 정도별 값(해석 눈금).
2. 우리 예상 vs 랭커 실제: 실험 22 우리 최선 5덱(`precompute_S<k>_<보스>.json` final) 대 랭커 300명 각자의 5덱(`ranker_fives.json`),
   그리고 비교 눈금인 랭커끼리의 값.
3. 대안 분류: 실험 22 사전 계산 2~8순위 5덱(현황판 「대안」), 실험 20 대안(사전 등록 판 · 다듬은 판), 실험 21 유력 대안 — 각자의 최선 대비.
"""

from __future__ import annotations

import importlib.util
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
EXP = HERE.parent
LOG22 = EXP / "22_ranker_check" / "run_log"
SEASONS22 = EXP / "22_ranker_check" / "seasons.json"
FIVES = HERE / "ranker_fives.json"
LOG20 = EXP / "20_search_robust" / "run_log"
LOG21 = EXP / "21_first_goal_recheck" / "run_log"
BOSSES = ("nocore", "core30")
BINS = (1.0, 0.7, 0.5, 0.3, 0.1, 0.0)    # 관찰용 구간(판정 기준 아님) — 아래 기준표로 읽는다
REBUILD_SHARE = 4                         # 실험 20 `run20.REBUILD_SHARE`와 같다(니케 겹침 기준, 주력 개념 없음)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


SIM = sys.modules.get("nikke_opt.similarity") or _load("nikke_opt.similarity", ROOT / "nikke_opt" / "similarity.py")


def read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def med(xs: Sequence[float]) -> float | None:
    return statistics.median(xs) if xs else None


def wmedian(pairs_: Sequence[tuple[float, int]]) -> float | None:
    """(값, 무게)의 중앙(아래쪽 중앙)."""
    tot = sum(w for _, w in pairs_)
    if not tot:
        return None
    acc = 0
    for v, w in sorted(pairs_):
        acc += w
        if 2 * acc >= tot:
            return v
    return None


def bins(js: Sequence[float]) -> list[int]:
    """BINS 구간별 개수: [=1, [0.7,1), [0.5,0.7), [0.3,0.5), [0.1,0.3), [0,0.1)]."""
    out = [0] * len(BINS)
    for j in js:
        if j >= 1.0:
            out[0] += 1
            continue
        for i in range(1, len(BINS)):
            if j >= BINS[i]:
                out[i] += 1
                break
    return out


def rebuilt(best: Sequence[Sequence[str]], alt: Sequence[Sequence[str]]) -> int:
    """대안 덱 중 최선의 어느 덱과도 REBUILD_SHARE명 이상 겹치지 않는 덱 수(실험 20 「다시 짠 덱」)."""
    bd = [set(d) for d in best]
    return sum(1 for d in alt if max((len(set(d) & b) for b in bd), default=0) < REBUILD_SHARE)


# ---------------------------------------------------------------- 1. 기준표

def reference() -> list[dict[str, Any]]:
    """가상의 25명(행 = 덱 A~E, 열 0~4)에 손댄 정도별 값."""
    g = [[f"{r}{c}" for c in range(5)] for r in "ABCDE"]

    def edit(f) -> list[list[str]]:
        x = [list(d) for d in g]
        f(x)
        return x

    def swap(x, a, i, b, j):
        x[a][i], x[b][j] = x[b][j], x[a][i]

    cases = [
        ("밖의 니케 1명으로 교체", edit(lambda x: x[0].__setitem__(0, "Z0"))),
        ("두 덱 사이 1명 맞교환", edit(lambda x: swap(x, 0, 0, 1, 0))),
        ("덱 1개를 밖의 5명으로 통째 교체", edit(lambda x: x.__setitem__(0, [f"Z{i}" for i in range(5)]))),
        ("맞교환 2번(서로 다른 덱 쌍)", edit(lambda x: (swap(x, 0, 0, 1, 0), swap(x, 2, 0, 3, 0)))),
        ("두 덱 사이 2명씩 맞교환", edit(lambda x: (swap(x, 0, 0, 1, 0), swap(x, 0, 1, 1, 1)))),
        ("맞교환 3번(서로 다른 덱 쌍)", edit(lambda x: (swap(x, 0, 0, 1, 0), swap(x, 2, 0, 3, 0), swap(x, 4, 0, 0, 1)))),
        ("같은 25명, 덱마다 원래 덱 출신 1명씩(완전 재배치)", [[g[r][(c + r) % 5] for r in range(5)] for c in range(5)]),
        ("니케 25명 모두 다름", [[f"Z{r}{c}" for c in range(5)] for r in range(5)]),
    ]
    return [{"case": name, **SIM.compare(g, p)} for name, p in cases]


# ---------------------------------------------------------------- 2. 우리 vs 랭커

def ranker_baseline(fives: Sequence[Sequence[Sequence[str]]]) -> dict[str, Any]:
    """랭커끼리: 고유 5덱으로 묶어 계산하고 랭커 수로 무게를 준다."""
    cnt = Counter(frozenset(frozenset(d) for d in f) for f in fives)
    keys = list(cnt)
    n = sum(cnt.values())
    J = [[0.0] * len(keys) for _ in keys]
    M = [[0] * len(keys) for _ in keys]
    for i, a in enumerate(keys):
        J[i][i], M[i][i] = 1.0, 0
        for k in range(i + 1, len(keys)):
            c = SIM.compare(list(a), list(keys[k]))
            J[i][k] = J[k][i] = c["pair_jaccard"]
            M[i][k] = M[k][i] = c["moves"]
    pair_w: list[tuple[float, int]] = []
    mean_j, near_j, near_m = [], [], []
    for i, a in enumerate(keys):
        ci = cnt[a]
        pair_w.append((1.0, ci * (ci - 1) // 2))
        pair_w += [(J[i][k], ci * cnt[keys[k]]) for k in range(i + 1, len(keys))]
        others = [(J[i][k], M[i][k], cnt[keys[k]] - (k == i)) for k in range(len(keys))]
        others = [o for o in others if o[2] > 0]
        mj = sum(j * w for j, _, w in others) / (n - 1) if n > 1 else None
        nj = max((j for j, _, _ in others), default=None)
        nm = min((m for _, m, _ in others), default=None)
        mean_j += [mj] * ci
        near_j += [nj] * ci
        near_m += [nm] * ci
    return {"rankers": n, "distinct": len(keys), "pair_median": wmedian(pair_w),
            "near_j_median": med([x for x in near_j if x is not None]),
            "near_moves_median": med([x for x in near_m if x is not None]),
            "mean_j": [x for x in mean_j if x is not None]}


def vs_rankers(ours: Sequence[Sequence[str]], players: Sequence[dict], base: dict[str, Any],
               top_five: Sequence[Sequence[str]], rank1: Sequence[Sequence[str]]) -> dict[str, Any]:
    rows = []
    for p in players:
        c = SIM.compare(ours, p["decks"])
        rows.append({"rank": p["rank"], "server": p["server"], **c})
    js = [r["pair_jaccard"] for r in rows]
    near = max(rows, key=lambda r: (r["pair_jaccard"], -r["moves"], -r["rank"]))
    mj = statistics.fmean(js)
    return {"j_median": med(js), "j_max": near["pair_jaccard"], "moves_min": min(r["moves"] for r in rows),
            "near": {k: near[k] for k in ("rank", "server", "pair_jaccard", "moves", "shared_nikkes")},
            "bins": bins(js), "mean_j": mj,
            "typical_pct": sum(x < mj for x in base["mean_j"]) / len(base["mean_j"]),
            "top_five": SIM.compare(ours, top_five), "rank1": SIM.compare(ours, rank1)}


def ranker_part() -> dict[str, Any]:
    fives = read_json(FIVES)
    s22 = read_json(SEASONS22)
    if fives is None or s22 is None:
        return {"seasons": {}, "runs": []}
    seasons, runs = {}, []
    for s, players in fives["seasons"].items():
        base = ranker_baseline([p["decks"] for p in players])
        rk = s22["seasons"][s]["rankers"]
        seasons[s] = {k: v for k, v in base.items() if k != "mean_j"}
        for b in BOSSES:
            pre = read_json(LOG22 / f"precompute_S{int(s):02d}_{b}.json")
            if pre is None:
                runs.append({"season": int(s), "boss": b, "status": "pending"})
                continue
            ours = [q for _, q in pre["final"]["squads"]]
            runs.append({"season": int(s), "boss": b, "status": "done", "total": pre["final"]["total"],
                         **vs_rankers(ours, players, base, rk["top_five"]["squads"], rk["rank1"]["squads"])})
    return {"source": fives["source"], "seasons": seasons, "runs": runs}


# ---------------------------------------------------------------- 3. 대안 분류

def alt_row(group: str, name: str, best: Sequence[Sequence[str]], best_total: float,
            alt: Sequence[Sequence[str]], alt_total: float, **extra: Any) -> dict[str, Any]:
    return {"group": group, "name": name, "ratio": alt_total / best_total, **SIM.compare(best, alt),
            "rebuilt": rebuilt(best, alt), **extra}


def alt_part() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    # 실험 22 사전 계산 2~8순위(run11.extract: 앞 순위들과 같은 덱 2개 이하 공유) — 현황판 「대안」과 같은 목록
    for s in (4, 9, 14, 18, 23, 28, 34, 40):
        for b in BOSSES:
            pre = read_json(LOG22 / f"precompute_S{s:02d}_{b}.json")
            if pre is None:
                continue
            best = [q for _, q in pre["final"]["squads"]]
            shown: list[list[list[str]]] = [best]
            rank = 1
            for sets, tot in zip(pre.get("sets", []), pre.get("set_totals", [])):
                if {frozenset(q) for q in sets} == {frozenset(q) for q in best}:
                    continue
                rank += 1
                near_prev = max(SIM.pair_jaccard(sets, x) for x in shown)
                out.append(alt_row("exp22", f"S{s} {b} {rank}순위", best, pre["final"]["total"], sets, tot,
                                   rank=rank, near_prev=near_prev))
                shown.append(sets)
    # 실험 20: 사전 등록 판(plans의 alt, C0 · C3 · CL3) · 다듬은 판(alt2, C3)
    for p in sorted(LOG20.glob("plans_*.jsonl")):
        for r in read_jsonl(p):
            if r.get("alt") and r["alt"].get("decks"):
                out.append(alt_row("exp20_pre", f"{r['scenario']} {r['plan']}", [q for _, q in r["decks"]], r["total"],
                                   [q for _, q in r["alt"]["decks"]], r["alt"]["total"]))
    for p in sorted(LOG20.glob("alt2_*.jsonl")):
        for r in read_jsonl(p):
            out.append(alt_row("exp20_rebuild", f"{r['scenario']} {r['plan']}", [q for _, q in r["decks"]], r["total"],
                               [q for _, q in r["alt_decks"]], r["alt_total"]))
    # 실험 21: 유력 대안(다듬은 판, P)
    for p in sorted(LOG21.glob("plans_*.jsonl")):
        for r in read_jsonl(p):
            if r.get("plan") == "P" and r.get("alt"):
                out.append(alt_row("exp21", r["scenario"], [q for _, q in r["decks"]], r["total"],
                                   [q for _, q in r["alt"]["decks"]], r["alt"]["total"]))
    return out


GROUPS = {"exp22": "실험 22 사전 계산 2~8순위(현황판 대안)",
          "exp20_pre": "실험 20 사전 등록 판(주력 2명 빼기)",
          "exp20_rebuild": "실험 20 다듬은 판(덱 2개 다시 짜기)",
          "exp21": "실험 21 유력 대안(다듬은 판)"}


def summarize_alts(rows: Sequence[dict]) -> dict[str, dict]:
    out = {}
    for g in GROUPS:
        xs = [r for r in rows if r["group"] == g]
        if not xs:
            continue
        js = [r["pair_jaccard"] for r in xs]
        out[g] = {"n": len(xs), "j_median": med(js), "j_min": min(js), "j_max": max(js),
                  "moves_median": med([r["moves"] for r in xs]), "shared_median": med([r["shared_nikkes"] for r in xs]),
                  "ratio_median": med([r["ratio"] for r in xs]), "bins": bins(js)}
    return out


# ---------------------------------------------------------------- 보고

def f2(x: float | None) -> str:
    return "—" if x is None else f"{x:.2f}"


def num(x: float | None) -> str:
    """중앙값처럼 정수거나 .5인 값: 2.0 → 2, 5.5 → 5.5."""
    return "—" if x is None else f"{x:g}"


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


BIN_HEAD = "J=1 · 0.7~ · 0.5~ · 0.3~ · 0.1~ · ~0.1"


def report(a: dict[str, Any]) -> str:
    L = ["# 실험 23 결과 — 5덱 편성안 유사도", "",
         "`python experiments/23_deck_similarity/analyze23.py`가 만든다. 시뮬 0회. 정의는 [README](README.md#지표).", "",
         "- **J** = 쌍 자카드(같은 덱에 묶인 두 니케 쌍의 겹침, 0~1). **바꿀** = 덱을 가장 잘 짝지었을 때 옮기거나 교체할 니케 수(0~25).",
         "- **공유** = 덱 나누기를 보지 않는 니케 공유 수(참고, 지금까지 쓰던 값). 구간 개수는 관찰용이며 판정 기준이 아니다.", "",
         "## 1. 기준표 — 25명 5덱에 손댄 정도", "", "| 바꾼 것 | J | 바꿀 | 공유 |", "|---|---|---|---|"]
    for r in a["reference"]:
        L.append(f"| {r['case']} | {f2(r['pair_jaccard'])} | {r['moves']} | {r['shared_nikkes']} |")
    rp = a["rankers"]
    L += ["", "## 2. 우리 예상 vs 랭커 실제", "",
          f"랭커: {rp.get('source', {}).get('repo', '—')} @ `{rp.get('source', {}).get('commit', '—')}`, 시즌마다 6개 서버 상위 50명의 5덱. "
          "우리: 실험 22 사전 계산 최선 5덱(시즌 풀 · 기본 레이어).", "",
          "### 비교 눈금 — 랭커끼리", "",
          "| 시즌 | 랭커 | 고유 5덱 | 두 랭커 J 중앙 | 가장 가까운 다른 랭커 J 중앙 | 가장 가까운 다른 랭커까지 바꿀 중앙 |", "|---|---|---|---|---|---|"]
    for s, v in rp["seasons"].items():
        L.append(f"| S{s} | {v['rankers']} | {v['distinct']} | {f2(v['pair_median'])} | {f2(v['near_j_median'])} | {num(v['near_moves_median'])} |")
    L += ["", "### 우리 최선 5덱 대 랭커 300명", "",
          "- **전형성** = 우리 안의 랭커 전체 대비 평균 J가 랭커 한 명의 (다른 랭커 대비) 평균 J보다 큰 랭커 비율. 50%면 랭커 한가운데 수준.", "",
          f"| 시즌 | 보스 | J 중앙 | 가장 가까운 랭커(순위 · 서버): J · 바꿀 · 공유 | 구간별 랭커 수({BIN_HEAD}) | 대표 5덱 J · 바꿀 | 1위 J · 바꿀 | 전형성 |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rp["runs"]:
        if r["status"] != "done":
            L.append(f"| S{r['season']} | {r['boss']} | 계산 전 |  |  |  |  |  |")
            continue
        n = r["near"]
        L.append(f"| S{r['season']} | {r['boss']} | {f2(r['j_median'])} | {n['rank']}위 {n['server']}: {f2(n['pair_jaccard'])} · {n['moves']} · {n['shared_nikkes']} | "
                 f"{' · '.join(map(str, r['bins']))} | {f2(r['top_five']['pair_jaccard'])} · {r['top_five']['moves']} | "
                 f"{f2(r['rank1']['pair_jaccard'])} · {r['rank1']['moves']} | {pct(r['typical_pct'])} |")
    L += ["", "## 3. 대안 분류 — 각자의 최선 5덱 대비", "",
          f"| 묶음 | 수 | J 중앙 (범위) | 바꿀 중앙 | 공유 중앙 | 값 비율 중앙 | 구간별 수({BIN_HEAD}) |", "|---|---|---|---|---|---|---|"]
    for g, v in a["alt_summary"].items():
        L.append(f"| {GROUPS[g]} | {v['n']} | {f2(v['j_median'])} ({f2(v['j_min'])}~{f2(v['j_max'])}) | {num(v['moves_median'])} | "
                 f"{num(v['shared_median'])} | {pct(v['ratio_median'])} | {' · '.join(map(str, v['bins']))} |")
    for g in ("exp21", "exp20_rebuild", "exp20_pre"):
        xs = [r for r in a["alts"] if r["group"] == g]
        if not xs:
            continue
        L += ["", f"### {GROUPS[g]}", "", "| 계정 · 판 | 값 비율 | J | 바꿀 | 공유 | 다시 짠 덱(4명 기준) |", "|---|---|---|---|---|---|"]
        for r in xs:
            L.append(f"| {r['name']} | {pct(r['ratio'])} | {f2(r['pair_jaccard'])} | {r['moves']} | {r['shared_nikkes']} | {r['rebuilt']} |")
    xs = [r for r in a["alts"] if r["group"] == "exp22"]
    if xs:
        L += ["", f"### {GROUPS['exp22']}", "",
              "- **앞 순위와 J 최대** = 최선과 그보다 앞 순위 대안 중 가장 비슷한 것과의 J(목록이 새 안을 보여 주는지).", "",
              "| 시즌 · 보스 | 순위별 J (2~8순위) | 순위별 앞 순위와 J 최대 | 순위별 값 비율 |", "|---|---|---|---|"]
        runs: dict[str, list[dict]] = {}
        for r in xs:
            runs.setdefault(r["name"].rsplit(" ", 1)[0], []).append(r)
        for k, rs in runs.items():
            L.append(f"| {k} | {' · '.join(f2(r['pair_jaccard']) for r in rs)} | {' · '.join(f2(r['near_prev']) for r in rs)} | "
                     f"{' · '.join(format(r['ratio'] * 100, '.1f') for r in rs)} |")
    return "\n".join(L) + "\n"


def analyze() -> dict[str, Any]:
    alts = alt_part()
    return {"reference": reference(), "rankers": ranker_part(), "alts": alts, "alt_summary": summarize_alts(alts)}


def main() -> int:
    a = analyze()
    (HERE / "analysis.json").write_text(json.dumps(a, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (HERE / "results.md").write_text(report(a), encoding="utf-8")
    done = [r for r in a["rankers"]["runs"] if r["status"] == "done"]
    print(f"results.md · analysis.json: 랭커 비교 {len(done)}판, 대안 {len(a['alts'])}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
