"""실험 6 W5 — 실행 기록 분석 → results.md. (골격: 관리자. 구현: W5)

README §잴 것 1~5를 계산한다. 입력은 common.Record JSON Lines와 compositions.json뿐이다(평가기를 부르지 않는다).
표준 라이브러리만 쓴다(Spearman·사분위는 직접 계산).

    python experiments/06_control_menu/analyze.py experiments/06_control_menu/run_log/*.jsonl \
        --out experiments/06_control_menu/results.md [--json <scratchpad>/summary.json]

기록 파일을 주지 않으면 「본 실행 전 — 형식만」 본문을 낸다.

지표 정의는 아래 DEFINITIONS(그대로 results.md에 들어간다)가 정본이다. summarize()가 돌려주는 dict의 키:

- `params`: 판단 기준 수치(`gain_median_max` · `spearman_min` · `top_k` · `ref_gap_min` · `exception_gain_min` ·
  `mode_ratio_min` · `explained_min` · `reversals_max`)와 `thresholds`(수렴 비율).
- `data`: 줄 수 · 오류 줄 수 · 조건별 줄 수 · 조건별 실제 시뮬 수(cached false) · 조합 수 · compositions에 없는 comp_id.
- `comps`: 조합별 표 — 조건별 최선 딜, 이득(`gain_vs_layer` · `gain_vs_auto`), 참조 차이(`ref_gap`), 최선 선택 label.
- `gains`: `vs_layer` · `vs_auto` 각각 분포 요약 `{n, min, q1, median, q3, max}`.
- `rank`: `pairs` — 조건 쌍마다 `{a, b, n, spearman, top_a, top_b, top_overlap, top_same, reversals, reversal_count}`.
- `uniqueness`: `items` — (니케, 축)마다 최빈 선택 · 비율 · 조합별 선택 · 예외 목록, `pooled` 요약.
- `convergence`: `runs` — (조합, 조건, 출발점)마다 임계 비율별 도달 step · 실제 시뮬 수, `by_start` 분포 요약.
- `camera`: 조합별 최선 기록의 `control_detail` 요약과 전 기록의 니케별 `preempted` 집계, 모르는 키.
- `reference`: 참조 조건이 있는 조합의 `ref_gap` 목록과 분포.
- `criteria`: 판단 기준 표 각 줄의 수치와 해당 여부(True · False · None=판정 불가). `candidate`: 적용 순서로 고른 후보 줄
  `{line, notes}`(line None = 없음). 최종 판단은 관리자.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent.parent)]
from common import AXES, COMPOSITIONS, NIKKE_AXES, Composition, Record, load_compositions, read_records  # noqa: E402

# 판단 기준 표(README §판단 기준)의 수치. 인자로 바꿀 수 있다.
GAIN_MEDIAN_MAX = 0.01   # 첫째 줄: 탐색 이득 중앙값이 이보다 작음
SPEARMAN_MIN = 0.95      # 첫째 줄: Spearman 이 값 이상
TOP_K = 5                # 첫째 줄: 상위 K개 유지
REF_GAP_MIN = 0.01       # 넷째 줄: 참조 최선이 좌표 하강 최선보다 이 비율 이상 좋음
EXCEPTION_GAIN_MIN = 0.003  # 유의 예외: 예외 이득이 이 값 이상(또는 미측정)
MODE_RATIO_MIN = 0.8     # 둘째 줄: 실질 최빈 비율 하한 (셋째 줄은 미만)
EXPLAINED_MIN = 0.6      # 둘째 줄: 유의 예외 중 동료 조건 후보가 있는 비율 하한 (셋째 줄은 미만)
REVERSALS_MAX = 3        # 셋째 줄: layer↔search_from_layer 상위권 역전이 이 건수 이상
CRITERIA_ORDER = (4, 1, 2, 3)  # README §판단 기준 줄 적용 순서 (2·3은 같은 단계)
THRESHOLDS = (0.99, 0.999)  # 잴 것 4: 탐색 최선의 이 비율에 닿는 step

NO_CHANGE = "(바꾸지 않음)"
RANK_CONDITIONS = ("auto", "layer", "search_from_layer", "fixed_layer")
SEARCH_CONDITIONS = ("search_from_layer", "search_from_auto", "reference")
# 선택지가 얹히는 바탕. 같은 선택지 집합이라도 바탕이 다르면 다른 요청이다(예외 이득 조회에 쓴다).
BASE_OF = {"layer": "layer", "search_from_layer": "layer", "reference": "layer",
           "auto": "auto", "search_from_auto": "auto", "fixed_layer": "fixed"}
CONTROL_DETAIL_KEYS = ("mode", "camera_mode", "by_char", "max_concurrent", "overlap_t", "overlaps", "preempted")
MAX_REVERSALS = 10

_LABEL_RE = re.compile(r"^(.*?):(" + "|".join(AXES) + r"):(.*)$")

DEFINITIONS = f"""\
## 지표 정의

입력은 실행 기록(`common.Record` JSON Lines)과 `compositions.json`뿐이다. `total_damage`가 없는(오류) 줄은 최선 계산에서 뺀다.

- **조건의 최선**: 조합 · 조건의 기록 중 총딜 최대. 동률이면 선택지 수가 적은 것, 그다음 step이 작은 것.
  `layer` · `auto` 조건 기록이 없으면 같은 바탕의 탐색 출발점(step 0, 선택지 없음)으로 대신한다.
- **이득 (잴 것 1)**: `search_from_layer` 최선 / `layer` − 1, / `auto` − 1. 분포는 최소 · 1사분위 · 중앙 · 3사분위 · 최대
  (사분위는 선형 보간, 표본 분위수 7형).
- **순위 상관 (잴 것 2)**: `auto` · `layer` · `search_from_layer` · `fixed_layer` 각 쌍에서 두 조건이 모두 있는 조합의
  최선 딜로 Spearman ρ(동순위는 평균 순위, 순위에 대한 Pearson). 상위 K개(동률은 comp_id 순)가 같은 집합인지와 겹친 수.
  **상위권 역전**: 두 조건에서 순서가 뒤집힌 조합 쌍 중 한쪽이라도 어느 조건에서 상위 K개에 드는 것.
- **니케 고유성 (잴 것 3)**: 조합마다 `search_from_layer` 최선 기록의 선택지에서 (니케, 축)의 label을 읽는다. 그 축의
  label이 없으면 「{NO_CHANGE}」. 그 조합 기록에 (니케, 축) 선택지가 한 번도 없으면 그 축은 메뉴에 없던 것으로 보고 세지 않는다.
  최빈 비율 = 최빈 선택을 고른 조합 수 / 그 니케 · 축이 있는 조합 수(최빈 동률은 「{NO_CHANGE}」, 그다음 label 순).
  **예외**는 최빈과 다른 선택을 한 조합이다. **예외 이득** = 예외 최선 딜 / (그 축만 최빈 선택으로 바꾼 선택지 집합의 딜) − 1.
  그 집합을 같은 조합 · 같은 바탕(layer 계열)에서 평가한 기록이 없으면 「미측정」.
  **동료 조건 후보** = 해당 예외 조합 모두에 있고 최빈 선택 조합에는 하나도 없는 동료(예외 label별, 그리고 예외 전체).
  스쿼드 단위 축(camera · tactic)은 니케 고유성에서 빼고 조합 표에만 보인다.
- **수렴 (잴 것 4)**: (조합, 탐색 조건, 출발점)마다 step 순으로 누적 최선이 기준 딜의 {' · '.join(f'{t:.1%}' for t in THRESHOLDS)}에
  처음 닿는 step과 그때까지(그 step 포함) `cached: false`인 줄 수(= 실제 시뮬). 기준 딜은 ① 그 실행의 마지막 최선,
  ② 그 조합의 모든 탐색 조건(`search_from_layer` · `search_from_auto` · `reference`) 최선. 닿지 못하면 「미도달」.
- **카메라 경합 (잴 것 5)**: `control_detail`(nikke-calc `docs/SIM-JSON.md` §결과에서 — `control_detail`, `23164e4`)의
  `preempted`(니케 → 카메라를 빼앗긴 횟수) · `overlap_t` · `max_concurrent`. 조합별 `search_from_layer` 최선 기록 값과,
  그 조합 전 기록에서 니케별 빼앗긴 횟수 합 · 빼앗긴 기록 수. 모르는 키는 따로 센다.
- **참조 차이**: `reference` 최선 / `search_from_layer` 최선 − 1.
- **실제 시뮬 수**: `cached: false`인 줄 수(조건별). 오류 줄도 센다.
- **유의 예외**: 예외 이득이 `exception_gain_min` 이상이거나 미측정인 예외. 그보다 작은 예외는 사실상 최빈 선택으로 친다.
  **실질 최빈 비율** = 1 − 유의 예외 수 / 전체 (니케, 축, 조합) 수(니케 단위 축 합산).
  **설명 비율** = 동료 조건 후보가 있는 유의 예외 / 유의 예외(유의 예외가 없으면 1). 이때 후보는 같은 예외 선택의 유의 예외
  조합 모두에 있고, 최빈 조합과 유의하지 않은 예외 조합에는 없는 동료다. 후보가 유의 예외 조합 하나에서만 나온 것은
  **약한 근거**로 따로 세고, 설명 비율에는 넣되 약한 근거를 뺀 비율도 보인다.
- **조건이 일부 조합에만 있을 때**: `search_from_auto` · `reference`가 없는 조합은 그 조건을 쓰는 지표(이득 vs auto는 아님 —
  `auto`는 전 조합)에서 빠진다. 참조 차이 · 넷째 줄은 참조가 있는 조합만, 수렴의 「조합 탐색 최선」은 그 조합에 있는 탐색 조건만으로 정한다.
- **판단 기준 표시**: README §판단 기준(사전 등록 2026-10-29)의 각 줄 수치와 해당 여부(판정 불가 = 필요한 수치가 없음).
  줄 적용 순서 4 → 1 → 2·3으로 **후보 줄**을 고른다 — 4줄 해당이면 4, 아니면 1줄 해당이면 1(2줄도 맞으면 메모),
  아니면 2 · 3 중 하나만 해당이면 그 줄, 둘 다거나 아무것도 아니면 없음. 후보는 기계적 표시이고 최종 판단은 관리자.
"""


# ---------------------------------------------------------------- 기본 계산

def parse_label(label: str) -> tuple[str | None, str, str]:
    """`"<니케|squad>:<axis>:<이름>"` → (니케 또는 None, 축, 이름). 니케 이름의 「 : 」는 그대로 둔다."""
    m = _LABEL_RE.match(label)
    if not m or not m.group(1):
        raise ValueError(f"label 형식이 아니다: {label!r}")
    owner = m.group(1)
    return (None if owner == "squad" else owner), m.group(2), m.group(3)


def quantile(xs: Sequence[float], q: float) -> float:
    """선형 보간 표본 분위수(7형)."""
    s = sorted(xs)
    if not s:
        raise ValueError("빈 표본")
    pos = (len(s) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def describe(xs: Iterable[float | None]) -> dict[str, Any]:
    vals = [x for x in xs if x is not None]
    if not vals:
        return {"n": 0, "min": None, "q1": None, "median": None, "q3": None, "max": None}
    return {"n": len(vals), "min": min(vals), "q1": quantile(vals, 0.25), "median": quantile(vals, 0.5),
            "q3": quantile(vals, 0.75), "max": max(vals)}


def average_ranks(xs: Sequence[float]) -> list[float]:
    """오름차순 순위(1부터). 동순위는 평균 순위."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman ρ = 평균 순위의 Pearson. 표본 2개 미만이거나 한쪽 분산이 0이면 None."""
    if len(xs) != len(ys):
        raise ValueError("길이가 다르다")
    if len(xs) < 2:
        return None
    rx, ry = average_ranks(xs), average_ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def _ratio(a: float | None, b: float | None) -> float | None:
    if a is None or not b:
        return None
    return a / b - 1


def _ok(r: Mapping[str, Any]) -> bool:
    return r.get("total_damage") is not None


def _best(recs: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    cands = [r for r in recs if _ok(r)]
    if not cands:
        return None
    return min(cands, key=lambda r: (-r["total_damage"], len(r.get("variants") or []), r.get("step", 0),
                                     str(r.get("start"))))


def _top(values: Mapping[str, float], k: int) -> list[str]:
    return [c for c, _ in sorted(values.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


# ---------------------------------------------------------------- 요약

def summarize(records: Sequence[Record], compositions: Sequence[Composition], *,
              gain_median_max: float = GAIN_MEDIAN_MAX, spearman_min: float = SPEARMAN_MIN,
              top_k: int = TOP_K, ref_gap_min: float = REF_GAP_MIN,
              exception_gain_min: float = EXCEPTION_GAIN_MIN, mode_ratio_min: float = MODE_RATIO_MIN,
              explained_min: float = EXPLAINED_MIN, reversals_max: int = REVERSALS_MAX,
              thresholds: Sequence[float] = THRESHOLDS) -> dict[str, Any]:
    """잴 것 1~5의 수치를 dict로. 키는 모듈 docstring, 정의는 DEFINITIONS."""
    comps_by_id = {c["id"]: c for c in compositions}
    by_comp: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in records:
        by_comp[r["comp_id"]].append(r)
    comp_ids = sorted(by_comp)

    data = {
        "records": len(records),
        "errors": sum(1 for r in records if not _ok(r)),
        "by_condition": dict(sorted(Counter(r["condition"] for r in records).items())),
        "sims_by_condition": dict(sorted(Counter(r["condition"] for r in records if not r.get("cached")).items())),
        "sims": sum(1 for r in records if not r.get("cached")),
        "comps": len(comp_ids),
        "missing_compositions": [c for c in comp_ids if c not in comps_by_id],
    }

    # 조합별 조건 최선
    best: dict[str, dict[str, Mapping[str, Any] | None]] = {}
    for cid in comp_ids:
        rs = by_comp[cid]
        b = {cond: _best(r for r in rs if r["condition"] == cond) for cond in
             ("auto", "layer", "search_from_layer", "search_from_auto", "reference", "fixed_layer")}
        for base_cond in ("layer", "auto"):  # 대신: 같은 바탕 탐색의 출발점
            if b[base_cond] is None:
                b[base_cond] = _best(r for r in rs if BASE_OF.get(r["condition"]) == base_cond
                                     and r["condition"] != base_cond and r.get("step") == 0
                                     and not r.get("variants"))
        best[cid] = b

    def dmg(cid: str, cond: str) -> int | None:
        r = best[cid][cond]
        return r["total_damage"] if r else None

    comps_table = []
    for cid in comp_ids:
        comp = comps_by_id.get(cid)
        sfl = best[cid]["search_from_layer"]
        comps_table.append({
            "comp_id": cid,
            "squad": list(comp["squad"]) if comp else None,
            "skeleton": comp.get("skeleton") if comp else None,
            "damage": {c: dmg(cid, c) for c in ("auto", "layer", "search_from_layer", "search_from_auto",
                                                 "reference", "fixed_layer")},
            "gain_vs_layer": _ratio(dmg(cid, "search_from_layer"), dmg(cid, "layer")),
            "gain_vs_auto": _ratio(dmg(cid, "search_from_layer"), dmg(cid, "auto")),
            "ref_gap": _ratio(dmg(cid, "reference"), dmg(cid, "search_from_layer")),
            "best_variants": sorted(sfl.get("variants") or []) if sfl else None,
        })
    gains = {"vs_layer": describe(c["gain_vs_layer"] for c in comps_table),
             "vs_auto": describe(c["gain_vs_auto"] for c in comps_table)}

    rank = {"top_k": top_k, "pairs": _rank_pairs(comp_ids, dmg, top_k)}
    uniqueness = _uniqueness(comp_ids, by_comp, best, comps_by_id, exception_gain_min)
    convergence = _convergence(comp_ids, by_comp, thresholds)
    camera = _camera(comp_ids, by_comp, best)
    ref_rows = [{"comp_id": c["comp_id"], "ref_gap": c["ref_gap"]} for c in comps_table if c["ref_gap"] is not None]
    reference = {"rows": ref_rows, "summary": describe(r["ref_gap"] for r in ref_rows)}

    params = {"gain_median_max": gain_median_max, "spearman_min": spearman_min, "top_k": top_k,
              "ref_gap_min": ref_gap_min, "exception_gain_min": exception_gain_min,
              "mode_ratio_min": mode_ratio_min, "explained_min": explained_min, "reversals_max": reversals_max,
              "thresholds": list(thresholds)}
    summary = {"params": params, "data": data, "comps": comps_table, "gains": gains, "rank": rank,
               "uniqueness": uniqueness, "convergence": convergence, "camera": camera, "reference": reference}
    summary["criteria"] = _criteria(summary)
    summary["candidate"] = _candidate(summary["criteria"])
    return summary


def _rank_pairs(comp_ids, dmg, top_k) -> list[dict[str, Any]]:
    out = []
    for i, a in enumerate(RANK_CONDITIONS):
        for b in RANK_CONDITIONS[i + 1:]:
            common_ids = [c for c in comp_ids if dmg(c, a) is not None and dmg(c, b) is not None]
            va = {c: dmg(c, a) for c in common_ids}
            vb = {c: dmg(c, b) for c in common_ids}
            rho = spearman([va[c] for c in common_ids], [vb[c] for c in common_ids])
            ta, tb = _top(va, top_k), _top(vb, top_k)
            pos_a = {c: k + 1 for k, c in enumerate(_top(va, len(va)))}
            pos_b = {c: k + 1 for k, c in enumerate(_top(vb, len(vb)))}
            top_any = set(ta) | set(tb)
            revs = []
            for x_i, x in enumerate(common_ids):
                for y in common_ids[x_i + 1:]:
                    if (va[x] - va[y]) * (vb[x] - vb[y]) < 0 and (x in top_any or y in top_any):
                        hi, lo = (x, y) if va[x] > va[y] else (y, x)
                        revs.append({"hi_in_a": hi, "lo_in_a": lo, "rank_a": [pos_a[hi], pos_a[lo]],
                                     "rank_b": [pos_b[hi], pos_b[lo]]})
            revs.sort(key=lambda r: (min(r["rank_a"] + r["rank_b"]), r["rank_a"]))
            out.append({"a": a, "b": b, "n": len(common_ids), "spearman": rho, "top_a": ta, "top_b": tb,
                        "top_overlap": len(set(ta) & set(tb)),
                        "top_same": (set(ta) == set(tb)) if len(common_ids) >= top_k else None,
                        "reversal_count": len(revs), "reversals": revs[:MAX_REVERSALS]})
    return out


def _uniqueness(comp_ids, by_comp, best, comps_by_id, exception_gain_min: float = EXCEPTION_GAIN_MIN) -> dict[str, Any]:
    # 조합마다 메뉴에 있던 (니케, 축) — 그 조합 기록에서 한 번이라도 시도된 label로 안다
    offered: dict[tuple[str, str], list[str]] = defaultdict(list)
    choices: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    squad_choices: dict[str, list[str]] = {}
    for cid in comp_ids:
        b = best[cid]["search_from_layer"]
        if b is None:
            continue
        keys = set()
        for r in by_comp[cid]:
            for lab in r.get("variants") or []:
                owner, axis, _ = parse_label(lab)
                if owner is not None and axis in NIKKE_AXES:
                    keys.add((owner, axis))
        chosen = {}
        squad_choices[cid] = []
        for lab in b.get("variants") or []:
            owner, axis, _ = parse_label(lab)
            if owner is None:
                squad_choices[cid].append(lab)
            else:
                chosen[(owner, axis)] = lab
        for key in sorted(keys):
            offered[key].append(cid)
            choices[key][cid] = chosen.get(key, NO_CHANGE)

    # 같은 조합 · 같은 바탕의 (선택지 집합 → 딜)
    lookup: dict[tuple[str, str, tuple[str, ...]], int] = {}
    for cid in comp_ids:
        for r in by_comp[cid]:
            if _ok(r) and BASE_OF.get(r["condition"]) == "layer":
                k = (cid, "layer", tuple(sorted(r.get("variants") or [])))
                lookup[k] = max(lookup.get(k, r["total_damage"]), r["total_damage"])

    items = []
    total = mode_total = exc_total = exc_measured = exc_explained = 0
    sig_total = sig_explained = sig_weak = 0
    for key in sorted(choices):
        nikke, axis = key
        ch = choices[key]
        cnt = Counter(ch.values())
        mode = min(cnt, key=lambda lab: (-cnt[lab], lab != NO_CHANGE, lab))
        tie = sum(1 for v in cnt.values() if v == cnt[mode]) > 1
        mode_comps = [c for c in sorted(ch) if ch[c] == mode]
        exc_comps = [c for c in sorted(ch) if ch[c] != mode]
        exceptions = []
        for cid in exc_comps:
            b = best[cid]["search_from_layer"]
            cur = set(b.get("variants") or [])
            if ch[cid] != NO_CHANGE:
                cur.discard(ch[cid])
            if mode != NO_CHANGE:
                cur.add(mode)
            alt = lookup.get((cid, "layer", tuple(sorted(cur))))
            gain = _ratio(b["total_damage"], alt) if alt is not None else None
            exceptions.append({"comp_id": cid, "choice": ch[cid], "damage": b["total_damage"],
                               "mode_damage": alt, "gain": gain, "measured": alt is not None,
                               "significant": alt is None or gain >= exception_gain_min})

        def peers(cids: Sequence[str], against: Sequence[str] = tuple(mode_comps)) -> list[str] | None:
            if not cids or any(c not in comps_by_id for c in list(cids) + list(against)):
                return None
            common_set = set.intersection(*(set(comps_by_id[c]["squad"]) - {nikke} for c in cids))
            in_mode = set().union(*(set(comps_by_id[c]["squad"]) for c in against)) if against else set()
            return sorted(common_set - in_mode)

        by_label = {}
        for lab in sorted({e["choice"] for e in exceptions}):
            cids = [e["comp_id"] for e in exceptions if e["choice"] == lab]
            by_label[lab] = {"comps": cids, "peer_candidates": peers(cids)}
        for e in exceptions:
            pc = by_label[e["choice"]]["peer_candidates"]
            e["peer_candidates"] = pc
        # 유의 예외만으로 다시: 유의하지 않은 예외 조합은 사실상 최빈 선택으로 치고 「최빈 쪽」에 넣는다
        eff_mode = sorted(mode_comps + [e["comp_id"] for e in exceptions if not e["significant"]])
        for e in exceptions:
            e["sig_peer_candidates"] = None
            e["sig_group_size"] = 0
        for lab in sorted({e["choice"] for e in exceptions if e["significant"]}):
            grp = [e for e in exceptions if e["significant"] and e["choice"] == lab]
            pc = peers([e["comp_id"] for e in grp], eff_mode)
            for e in grp:
                e["sig_peer_candidates"] = pc
                e["sig_group_size"] = len(grp)
        for e in exceptions:
            e["explained"] = bool(e["significant"] and e["sig_peer_candidates"])
            e["weak"] = e["explained"] and e["sig_group_size"] == 1
        n = len(ch)
        total += n
        mode_total += cnt[mode]
        exc_total += len(exceptions)
        exc_measured += sum(1 for e in exceptions if e["measured"])
        exc_explained += sum(1 for e in exceptions if e["peer_candidates"])
        sig_total += sum(1 for e in exceptions if e["significant"])
        sig_explained += sum(1 for e in exceptions if e["explained"])
        sig_weak += sum(1 for e in exceptions if e["weak"])
        items.append({"nikke": nikke, "axis": axis, "n": n, "mode": mode, "mode_count": cnt[mode],
                      "mode_share": cnt[mode] / n, "mode_tie": tie, "counts": dict(sorted(cnt.items())),
                      "choices": dict(sorted(ch.items())), "exceptions": exceptions,
                      "exceptions_by_label": by_label,
                      "peer_candidates_all": peers(exc_comps) if exc_comps else None})
    pooled = {"keys": len(items), "keys_n3": sum(1 for it in items if it["n"] >= 3),
              "observations": total, "mode_share": (mode_total / total) if total else None,
              "exceptions": exc_total, "exceptions_measured": exc_measured,
              "exceptions_with_peer_candidate": exc_explained,
              "exception_gain": describe(e["gain"] for it in items for e in it["exceptions"]),
              "exception_gain_min": exception_gain_min,
              "significant": sig_total,
              "significant_unmeasured": sum(1 for it in items for e in it["exceptions"] if not e["measured"]),
              "effective_mode_share": (1 - sig_total / total) if total else None,
              "significant_explained": sig_explained, "significant_weak": sig_weak,
              # 유의 예외가 없으면 설명할 예외가 없다 — 1.0으로 둔다
              "explained_share": (sig_explained / sig_total) if sig_total else (1.0 if total else None),
              "explained_share_strong": ((sig_explained - sig_weak) / sig_total) if sig_total
              else (1.0 if total else None)}
    return {"items": items, "pooled": pooled, "squad_choices": squad_choices}


def _convergence(comp_ids, by_comp, thresholds) -> dict[str, Any]:
    runs = []
    for cid in comp_ids:
        search = [r for r in by_comp[cid] if r["condition"] in SEARCH_CONDITIONS and _ok(r)]
        comp_best = max((r["total_damage"] for r in search), default=None)
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for r in by_comp[cid]:
            if r["condition"] in SEARCH_CONDITIONS:
                groups[(r["condition"], str(r.get("start")))].append(r)
        for (cond, start), rs in sorted(groups.items()):
            rs = sorted(rs, key=lambda r: r.get("step", 0))
            final = max((r["total_damage"] for r in rs if _ok(r)), default=None)

            def reach(target):
                if target is None:
                    return {str(t): None for t in thresholds}
                out = {}
                for t in thresholds:
                    cur = None
                    sims = 0
                    hit = None
                    for r in rs:
                        if not r.get("cached"):
                            sims += 1
                        if _ok(r):
                            cur = r["total_damage"] if cur is None else max(cur, r["total_damage"])
                        if cur is not None and cur >= t * target:
                            hit = {"step": r.get("step", 0), "sims": sims}
                            break
                    out[str(t)] = hit
                return out

            runs.append({"comp_id": cid, "condition": cond, "start": start, "evals": len(rs),
                         "sims": sum(1 for r in rs if not r.get("cached")), "final": final,
                         "comp_best": comp_best, "to_own": reach(final), "to_comp": reach(comp_best)})
    by_start = {}
    for kind in ("search_from_layer", "search_from_auto", "reference"):
        rr = [r for r in runs if r["condition"] == kind]
        if not rr:
            continue
        entry = {"runs": len(rr), "evals": describe(r["evals"] for r in rr), "sims": describe(r["sims"] for r in rr)}
        for target in ("to_own", "to_comp"):
            for t in thresholds:
                hits = [r[target][str(t)] for r in rr]
                entry[f"{target}:{t}:step"] = describe(h["step"] for h in hits if h)
                entry[f"{target}:{t}:sims"] = describe(h["sims"] for h in hits if h)
                entry[f"{target}:{t}:missed"] = sum(1 for h in hits if h is None)
        by_start[kind] = entry
    return {"runs": runs, "by_start": by_start}


def _camera(comp_ids, by_comp, best) -> dict[str, Any]:
    rows = []
    unknown_keys: Counter = Counter()
    missing = 0
    for cid in comp_ids:
        per_nikke: dict[str, dict[str, int]] = defaultdict(lambda: {"preempted": 0, "records": 0})
        recs = [r for r in by_comp[cid] if _ok(r)]
        for r in recs:
            cd = r.get("control_detail")
            if not isinstance(cd, Mapping):
                missing += 1
                continue
            for k in cd:
                if k not in CONTROL_DETAIL_KEYS:
                    unknown_keys[k] += 1
            for nikke, n in (cd.get("preempted") or {}).items():
                if n:
                    per_nikke[nikke]["preempted"] += n
                    per_nikke[nikke]["records"] += 1
        b = best[cid]["search_from_layer"]
        bcd = b.get("control_detail") if b else None
        bcd = bcd if isinstance(bcd, Mapping) else {}
        rows.append({"comp_id": cid, "records": len(recs),
                     "best_preempted": {k: v for k, v in (bcd.get("preempted") or {}).items() if v},
                     "best_overlap_t": bcd.get("overlap_t"), "best_max_concurrent": bcd.get("max_concurrent"),
                     "best_mode": bcd.get("mode"), "best_by_char": dict(bcd.get("by_char") or {}),
                     "all_preempted": {k: dict(v) for k, v in sorted(per_nikke.items())}})
    return {"rows": rows, "unknown_keys": dict(sorted(unknown_keys.items())), "missing_control_detail": missing,
            "comps_with_preemption_in_best": sum(1 for r in rows if r["best_preempted"]),
            "comps_with_preemption_any": sum(1 for r in rows if r["all_preempted"])}


def _all(parts: Sequence[bool | None]) -> bool | None:
    return False if False in parts else (None if None in parts else True)


def _any(parts: Sequence[bool | None]) -> bool | None:
    return True if True in parts else (None if None in parts else False)


def _criteria(s: Mapping[str, Any]) -> list[dict[str, Any]]:
    p = s["params"]
    med = s["gains"]["vs_layer"]["median"]
    pair = next((x for x in s["rank"]["pairs"] if (x["a"], x["b"]) == ("layer", "search_from_layer")), None)
    rho = pair["spearman"] if pair else None
    top_same = pair["top_same"] if pair else None
    line1 = _all([None if med is None else med < p["gain_median_max"],
                  None if rho is None else rho >= p["spearman_min"], top_same])
    u = s["uniqueness"]["pooled"]
    mr, ex = u["effective_mode_share"], u["explained_share"]
    revs = pair["reversal_count"] if pair and pair["n"] else None
    line2 = _all([None if mr is None else mr >= p["mode_ratio_min"],
                  None if ex is None else ex >= p["explained_min"]])
    line3 = _any([_all([None if mr is None else mr < p["mode_ratio_min"],
                        None if ex is None else ex < p["explained_min"]]),
                  None if revs is None else revs >= p["reversals_max"]])
    ref = s["reference"]["summary"]
    line4 = None if ref["n"] == 0 else ref["max"] >= p["ref_gap_min"]
    return [
        {"line": 1, "text": f"탐색 이득 중앙 {p['gain_median_max']:.0%} 미만 · Spearman {p['spearman_min']} 이상 · "
                            f"상위 {p['top_k']}개 같은 집합 (layer ↔ search_from_layer)",
         "values": {"gain_median": med, "spearman": rho, "top_same": top_same}, "met": line1},
        {"line": 2, "text": f"실질 최빈 비율 {p['mode_ratio_min']} 이상 · 유의 예외(이득 ≥ {p['exception_gain_min']:.1%} 또는 "
                            f"미측정)의 {p['explained_min']:.0%} 이상에 동료 조건 후보",
         "values": {"effective_mode_share": mr, "explained_share": ex,
                    "explained_share_strong": u["explained_share_strong"], "significant": u["significant"],
                    "significant_explained": u["significant_explained"], "significant_weak": u["significant_weak"]},
         "met": line2},
        {"line": 3, "text": f"(실질 최빈 비율 {p['mode_ratio_min']} 미만 · 설명 비율 {p['explained_min']:.0%} 미만) 또는 "
                            f"layer ↔ search_from_layer 상위권 역전 {p['reversals_max']}건 이상",
         "values": {"effective_mode_share": mr, "explained_share": ex, "top_reversals_layer_vs_search": revs},
         "met": line3},
        {"line": 4, "text": f"참조 조합 중 하나라도 reference / search_from_layer − 1 ≥ {p['ref_gap_min']:.0%}",
         "values": {"ref_gap_max": ref["max"], "ref_gap_median": ref["median"], "n": ref["n"]}, "met": line4},
    ]


def _candidate(criteria: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """README 줄 적용 순서(4 → 1 → 2·3)로 고른 후보 줄. 최종 판단은 관리자."""
    met = {c["line"]: c["met"] for c in criteria}
    notes = [f"{n}줄 판정 불가(수치 없음)" for n in CRITERIA_ORDER if met[n] is None]
    if met[4]:
        return {"line": 4, "notes": notes + ["4줄 해당 — 다른 줄 판단은 보류하고 탐색법을 고친다"]}
    if met[1]:
        if met[2]:
            notes.append("2줄도 해당 — 더 단순한 1줄을 고르고 2줄 수치는 다음 회차 참고")
        return {"line": 1, "notes": notes}
    if met[2] and not met[3]:
        return {"line": 2, "notes": notes}
    if met[3] and not met[2]:
        return {"line": 3, "notes": notes}
    if met[2] and met[3]:
        notes.append("2줄과 3줄(역전 조건)이 함께 해당 — 관리자 판단")
    else:
        notes.append("어느 줄에도 딱 맞지 않음 — 관리자 판단")
    return {"line": None, "notes": notes}


# ---------------------------------------------------------------- 출력

def _pct(x: float | None, nd: int = 2) -> str:
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def _num(x: Any) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.4g}" if not x.is_integer() else f"{int(x):,}"
    if isinstance(x, int):
        return f"{x:,}"
    return str(x)


def _met(m: bool | None) -> str:
    return {True: "해당", False: "해당 아님", None: "판정 불가"}[m]


def _desc_row(name: str, d: Mapping[str, Any], fmt=_pct) -> str:
    return f"| {name} | {d['n']} | " + " | ".join(fmt(d[k]) for k in ("min", "q1", "median", "q3", "max")) + " |"


def _esc(s: Any) -> str:
    return str(s).replace("|", "\\|")


def render(summary: dict[str, Any]) -> str:
    """summarize() 결과 → results.md 본문(Markdown)."""
    s = summary
    d = s["data"]
    p = s["params"]
    L: list[str] = ["# 실험 6 결과 — 분석 (analyze.py 생성)", ""]
    if d["records"] == 0:
        L += ["**본 실행 전 — 형식만.** 기록이 없어 수치가 없다. 본 실행 뒤 관리자가 다시 만든다:", "",
              "```bash", "python experiments/06_control_menu/analyze.py experiments/06_control_menu/run_log/*.jsonl \\",
              "    --out experiments/06_control_menu/results.md", "```", ""]
    L += ["이 파일은 `analyze.py`가 만든다. 손으로 고치지 않는다. 해석과 최종 판단은 [README](README.md) 「결과」에 둔다.", "",
          DEFINITIONS, "## 기록", "",
          f"- 줄 {d['records']:,} (오류 {d['errors']:,}) · 조합 {d['comps']} · 실제 시뮬(cached false) {d['sims']:,}",
          "- 조건별 줄: " + (", ".join(f"`{k}` {v:,}" for k, v in d["by_condition"].items()) or "—"),
          "- 조건별 실제 시뮬: " + (", ".join(f"`{k}` {v:,}" for k, v in d["sims_by_condition"].items()) or "—")]
    if d["missing_compositions"]:
        L.append("- compositions.json에 없는 comp_id: " + ", ".join(d["missing_compositions"]))
    L.append("")

    L += ["## 판단 기준 표시", "", f"수치는 인자(`--gain-median-max {p['gain_median_max']}` · `--spearman-min {p['spearman_min']}` · "
          f"`--top-k {p['top_k']}` · `--ref-gap-min {p['ref_gap_min']}` · `--exception-gain-min {p['exception_gain_min']}` · "
          f"`--mode-ratio-min {p['mode_ratio_min']}` · `--explained-min {p['explained_min']}` · "
          f"`--reversals-max {p['reversals_max']}`). 기본값은 README §판단 기준(사전 등록 2026-10-29).", "",
          "| 줄 | 기준 | 수치 | 해당 여부 |", "|---|---|---|---|"]
    for c in s["criteria"]:
        vals = " · ".join(f"{k} {_num(v) if not isinstance(v, bool) else v}" for k, v in c["values"].items())
        L.append(f"| {c['line']} | {_esc(c['text'])} | {_esc(vals)} | {_met(c['met'])} |")
    cand = s["candidate"]
    L += ["", f"**후보 줄**(적용 순서 {' → '.join('2·3' if n == 2 else str(n) for n in CRITERIA_ORDER if n != 3)}): "
          + (f"{cand['line']}줄" if cand["line"] else "없음")
          + (" — " + "; ".join(cand["notes"]) if cand["notes"] else "")
          + ". 기계적으로 고른 후보일 뿐이고 최종 판단은 관리자가 README 「결과」에 쓴다.", ""]

    L += ["## 1. 탐색 이득", "", "| 비교 | n | 최소 | 1사분위 | 중앙 | 3사분위 | 최대 |", "|---|---|---|---|---|---|---|",
          _desc_row("search_from_layer / layer − 1", s["gains"]["vs_layer"]),
          _desc_row("search_from_layer / auto − 1", s["gains"]["vs_auto"]), "",
          "| 조합 | 틀 | auto | layer | fixed_layer | search_from_layer | search_from_auto | reference | 이득 vs layer | 이득 vs auto | 참조 차이 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in s["comps"]:
        dm = c["damage"]
        L.append(f"| {c['comp_id']} | {c['skeleton'] or '—'} | " + " | ".join(_num(dm[k]) for k in
                 ("auto", "layer", "fixed_layer", "search_from_layer", "search_from_auto", "reference"))
                 + f" | {_pct(c['gain_vs_layer'])} | {_pct(c['gain_vs_auto'])} | {_pct(c['ref_gap'])} |")
    L += ["", "조합별 `search_from_layer` 최선 선택:", "", "| 조합 | 스쿼드 | 선택지 |", "|---|---|---|"]
    for c in s["comps"]:
        v = c["best_variants"]
        L.append(f"| {c['comp_id']} | {_esc(' · '.join(c['squad'])) if c['squad'] else '—'} | "
                 f"{_esc(', '.join(f'`{x}`' for x in v)) if v else ('없음' if v == [] else '—')} |")
    L.append("")

    L += ["## 2. 조건 사이 순위 상관", "", f"| 조건 A | 조건 B | n | Spearman | 상위 {s['rank']['top_k']} 겹침 | 같은 집합 | 상위권 역전 |",
          "|---|---|---|---|---|---|---|"]
    for x in s["rank"]["pairs"]:
        L.append(f"| {x['a']} | {x['b']} | {x['n']} | {_num(x['spearman'])} | {x['top_overlap']} | "
                 f"{'—' if x['top_same'] is None else ('예' if x['top_same'] else '아니오')} | {x['reversal_count']} |")
    rev_lines = []
    for x in s["rank"]["pairs"]:
        for r in x["reversals"]:
            rev_lines.append(f"| {x['a']} → {x['b']} | {r['hi_in_a']} · {r['lo_in_a']} | {r['rank_a'][0]}·{r['rank_a'][1]} | "
                             f"{r['rank_b'][0]}·{r['rank_b'][1]} |")
    if rev_lines:
        L += ["", f"상위권 역전 사례(쌍마다 최대 {MAX_REVERSALS}개):", "", "| 쌍 | 조합 (A에서 위 · 아래) | A 순위 | B 순위 |",
              "|---|---|---|---|"] + rev_lines
    L.append("")

    u = s["uniqueness"]
    pu = u["pooled"]
    L += ["## 3. 니케 고유성", "",
          f"- (니케, 축) {pu['keys']}개 (조합 3개 이상: {pu['keys_n3']}) · 관측 {pu['observations']} · "
          f"최빈 비율(전체) {_num(pu['mode_share'])}",
          f"- 예외 {pu['exceptions']} (이득 측정 {pu['exceptions_measured']} · 동료 조건 후보 있음 "
          f"{pu['exceptions_with_peer_candidate']})",
          f"- 유의 예외(이득 ≥ {pu['exception_gain_min']:.1%} 또는 미측정) {pu['significant']} (미측정 "
          f"{pu['significant_unmeasured']}) · 실질 최빈 비율 {_num(pu['effective_mode_share'])}",
          f"- 유의 예외 중 동료 조건 후보 있음 {pu['significant_explained']} (약한 근거 = 예외 조합 하나뿐 "
          f"{pu['significant_weak']}) · 설명 비율 {_num(pu['explained_share'])} · 약한 근거 제외 "
          f"{_num(pu['explained_share_strong'])}", "",
          "| 예외 이득 | n | 최소 | 1사분위 | 중앙 | 3사분위 | 최대 |", "|---|---|---|---|---|---|---|",
          _desc_row("예외 최선 / 최빈 적용 − 1", pu["exception_gain"]), "",
          "| 니케 | 축 | 조합 수 | 최빈 선택 | 최빈 비율 | 선택 분포 |", "|---|---|---|---|---|---|"]
    for it in u["items"]:
        dist = ", ".join(f"`{k}` {v}" for k, v in it["counts"].items())
        L.append(f"| {_esc(it['nikke'])} | {it['axis']} | {it['n']} | `{_esc(it['mode'])}`{' (동률)' if it['mode_tie'] else ''} | "
                 f"{it['mode_share']:.2f} | {_esc(dist)} |")
    exc_lines = []
    for it in u["items"]:
        for e in it["exceptions"]:
            pc = e["peer_candidates"]
            spc = e["sig_peer_candidates"]
            sig = ("아니오" if not e["significant"] else
                   ("예 · " + (_esc(" · ".join(spc)) if spc else "후보 없음") + (" (약한 근거)" if e["weak"] else "")))
            exc_lines.append(f"| {_esc(it['nikke'])} | {it['axis']} | {e['comp_id']} | `{_esc(e['choice'])}` | `{_esc(it['mode'])}` | "
                             f"{_pct(e['gain']) if e['measured'] else '미측정'} | "
                             f"{'—' if pc is None else (_esc(' · '.join(pc)) if pc else '없음')} | {sig} |")
    if exc_lines:
        L += ["", "예외 (동료 조건 후보: 같은 예외 선택 조합 모두에 있고 최빈 조합엔 없는 동료. 유의 열의 후보는 유의하지 않은 "
              "예외 조합을 최빈 쪽에 넣고 다시 구한 것):", "",
              "| 니케 | 축 | 조합 | 예외 선택 | 최빈 선택 | 예외 이득 | 동료 조건 후보 | 유의 · 후보 |",
              "|---|---|---|---|---|---|---|---|"] + exc_lines
    sq = {k: v for k, v in u["squad_choices"].items() if v}
    if sq:
        L += ["", "스쿼드 단위 선택(카메라 · 택틱):", "", "| 조합 | 선택지 |", "|---|---|"]
        L += [f"| {k} | {_esc(', '.join(f'`{x}`' for x in v))} |" for k, v in sorted(sq.items())]
    L.append("")

    cv = s["convergence"]
    L += ["## 4. 수렴", ""]
    if cv["by_start"]:
        L += ["| 조건 | 기준 | 비율 | 실행 수 | 미도달 | step 중앙 | step 최대 | 실제 시뮬 중앙 | 실제 시뮬 최대 |",
              "|---|---|---|---|---|---|---|---|---|"]
        for kind, e in cv["by_start"].items():
            for target, tname in (("to_own", "자기 최선"), ("to_comp", "조합 탐색 최선")):
                for t in p["thresholds"]:
                    st, sm = e[f"{target}:{t}:step"], e[f"{target}:{t}:sims"]
                    L.append(f"| {kind} | {tname} | {t:.1%} | {e['runs']} | {e[f'{target}:{t}:missed']} | "
                             f"{_num(st['median'])} | {_num(st['max'])} | {_num(sm['median'])} | {_num(sm['max'])} |")
        L += ["", "| 조합 | 조건 | 출발점 | 평가 | 실제 시뮬 | " +
              " | ".join(f"{t:.1%} 자기 (step/시뮬)" for t in p["thresholds"]) + " | " +
              " | ".join(f"{t:.1%} 조합 (step/시뮬)" for t in p["thresholds"]) + " |",
              "|---|---|---|---|---|" + "---|" * (2 * len(p["thresholds"]))]

        def hit(h):
            return "미도달" if h is None else f"{h['step']}/{h['sims']}"
        for r in cv["runs"]:
            L.append(f"| {r['comp_id']} | {r['condition']} | {_esc(r['start'])} | {r['evals']} | {r['sims']} | " +
                     " | ".join(hit(r["to_own"][str(t)]) for t in p["thresholds"]) + " | " +
                     " | ".join(hit(r["to_comp"][str(t)]) for t in p["thresholds"]) + " |")
    else:
        L.append("탐색 기록 없음.")
    L.append("")

    cam = s["camera"]
    L += ["## 5. solo 카메라 경합", "",
          f"- 최선 기록에서 빼앗긴 조작이 있는 조합 {cam['comps_with_preemption_in_best']} · 어느 기록에서든 있는 조합 "
          f"{cam['comps_with_preemption_any']} · `control_detail` 없는 줄 {cam['missing_control_detail']}"]
    if cam["unknown_keys"]:
        L.append("- 모르는 `control_detail` 키(줄 수): " + ", ".join(f"`{k}` {v}" for k, v in cam["unknown_keys"].items()))
    L += ["", "| 조합 | 최선 기록: 빼앗긴 횟수 | 최선 기록: 겹친 시간 · 최대 동시 | 전 기록: 니케별 빼앗긴 횟수 (기록 수) |",
          "|---|---|---|---|"]
    for r in cam["rows"]:
        bp = ", ".join(f"{k} {v}" for k, v in r["best_preempted"].items()) or "없음"
        ap = ", ".join(f"{k} {v['preempted']} ({v['records']}/{r['records']})" for k, v in r["all_preempted"].items()) or "없음"
        L.append(f"| {r['comp_id']} | {_esc(bp)} | {_num(r['best_overlap_t'])} · {_num(r['best_max_concurrent'])} | {_esc(ap)} |")
    L.append("")

    ref = s["reference"]
    L += ["## 참조 탐색 대비", ""]
    if ref["rows"]:
        L += ["| 비교 | n | 최소 | 1사분위 | 중앙 | 3사분위 | 최대 |", "|---|---|---|---|---|---|---|",
              _desc_row("reference / search_from_layer − 1", ref["summary"]), "",
              "| 조합 | 참조 차이 |", "|---|---|"] + [f"| {r['comp_id']} | {_pct(r['ref_gap'], 3)} |" for r in ref["rows"]]
    else:
        L.append("참조 조건 기록 없음.")
    L.append("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="실험 6 실행 기록 분석 → results.md")
    ap.add_argument("records", nargs="*", type=Path, help="실행 기록 JSON Lines (없으면 형식만)")
    ap.add_argument("--compositions", type=Path, default=COMPOSITIONS)
    ap.add_argument("--out", type=Path, help="Markdown 출력 경로 (없으면 표준 출력)")
    ap.add_argument("--json", type=Path, help="summarize() 결과를 JSON으로 쓸 경로")
    ap.add_argument("--gain-median-max", type=float, default=GAIN_MEDIAN_MAX)
    ap.add_argument("--spearman-min", type=float, default=SPEARMAN_MIN)
    ap.add_argument("--top-k", type=int, default=TOP_K)
    ap.add_argument("--ref-gap-min", type=float, default=REF_GAP_MIN)
    ap.add_argument("--exception-gain-min", type=float, default=EXCEPTION_GAIN_MIN)
    ap.add_argument("--mode-ratio-min", type=float, default=MODE_RATIO_MIN)
    ap.add_argument("--explained-min", type=float, default=EXPLAINED_MIN)
    ap.add_argument("--reversals-max", type=int, default=REVERSALS_MAX)
    a = ap.parse_args(argv)
    records = list(read_records(a.records))
    comps = load_compositions(a.compositions) if a.compositions.exists() else []
    s = summarize(records, comps, gain_median_max=a.gain_median_max, spearman_min=a.spearman_min,
                  top_k=a.top_k, ref_gap_min=a.ref_gap_min, exception_gain_min=a.exception_gain_min,
                  mode_ratio_min=a.mode_ratio_min, explained_min=a.explained_min, reversals_max=a.reversals_max)
    text = render(s)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if a.json:
        a.json.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
