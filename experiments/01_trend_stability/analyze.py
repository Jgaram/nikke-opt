"""사전 실험 1 — 경향 안정성.

랭커 데이터만으로, 보스가 바뀔 때 과거 데이터가 "이번 시즌에 무엇이 쓰일지"를 얼마나 맞히는지 잰다.
딜 수치는 쓰지 않는다(docs/SEARCH.md 「지식의 세 출처」). 쓰는 것은 사용 여부·같은 덱 동반·5인 구성·버스트 구성.

입력: nikke-analysis 의 data/processed/{raid_entries,roster,metrics_seasons}.csv
      (raid_entries.csv 는 커밋돼 있지 않으니 그 레포에서 `nikke build raids` 로 만든다)
사용: python analyze.py <nikke-analysis 경로>  → 표준출력에 마크다운 표
"""

from __future__ import annotations

import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

TOP_UNITS = 25   # 한 시즌 "주력" 니케 수 (5덱 × 5명)
TOP_PAIRS = 100
MIN_HISTORY = 4  # 이 시즌부터 평가 (과거 3시즌 이상 필요)


def load(root: Path):
    p = root / "data" / "processed"
    # 서버 코드 "NA"(북미)가 결측으로 읽히지 않게 한다
    e = pd.read_csv(p / "raid_entries.csv", dtype={"unit_id": str, "player": str, "server": str},
                    keep_default_na=False, na_values={"unit_cp": [""], "unit_cores": [""]})
    roster = pd.read_csv(p / "roster.csv", dtype={"unit_id": str})
    seasons = pd.read_csv(p / "metrics_seasons.csv")
    seasons = seasons[seasons["final"]]
    e = e[(e["content"] == "soloraid") & e["season"].isin(seasons["season"])]
    return e, roster, seasons.set_index("season")


def unit_presence(e: pd.DataFrame) -> pd.DataFrame:
    """시즌 × 니케: 그 니케를 쓴 랭커 비율."""
    rankers = e.groupby("season")[["server", "player"]].apply(lambda d: len(d.drop_duplicates()))
    used = e.drop_duplicates(["season", "server", "player", "unit_id"]).groupby(["season", "unit_id"]).size()
    return (used / rankers.reindex(used.index.get_level_values(0)).values).unstack(fill_value=0.0)


def squads(e: pd.DataFrame) -> pd.DataFrame:
    g = e.groupby(["season", "server", "player", "deck"])
    d = g["unit_id"].apply(lambda s: frozenset(s)).rename("squad").reset_index()
    d = d.merge(g["deck_score"].first().reset_index(), on=["season", "server", "player", "deck"])
    d["deck_rank"] = d.groupby(["season", "server", "player"])["deck_score"].rank(ascending=False, method="first")
    return d[d["squad"].map(len) == 5]


def pair_rate(sq: pd.DataFrame) -> pd.DataFrame:
    """시즌 × 짝: 그 두 니케가 같은 덱에 선 덱 비율."""
    rows = {}
    for season, grp in sq.groupby("season"):
        c = Counter(p for s in grp["squad"] for p in combinations(sorted(s), 2))
        rows[season] = {k: v / len(grp) for k, v in c.items()}
    return pd.DataFrame(rows).T.fillna(0.0).sort_index()


def priors(table: pd.DataFrame, seasons: pd.DataFrame, t: int) -> dict[str, pd.Series]:
    past = table.loc[table.index < t]
    weak = seasons.loc[t, "weak_element"]
    same = [s for s in past.index if seasons.loc[s, "weak_element"] == weak]
    out = {
        "직전 시즌": past.iloc[-1],
        "최근 3시즌 평균": past.iloc[-3:].mean(),
        "누적 평균(감쇠 0.8)": (past.mul(0.8 ** (t - past.index.to_numpy() - 1), axis=0)).sum()
        / (0.8 ** (t - past.index.to_numpy() - 1)).sum(),
    }
    if same:
        out["같은 약점 속성 직전"] = past.loc[same[-1]]
        out["혼합(3시즌+같은 속성)"] = 0.5 * out["최근 3시즌 평균"] + 0.5 * out["같은 약점 속성 직전"]
    return out


def score(prior: pd.Series, actual: pd.Series, k: int) -> dict[str, float]:
    """실제 상위 k(주력)를 과거 기반 예측이 얼마나 맞히나.
    topk: 예측 상위 k와 겹치는 비율. mass: 예측 상위 k가 덮는 실제 사용량(실제 상위 k 대비).
    x2/x4: 예측 상위 2k·4k로 넓게 잡으면 실제 상위 k 중 몇 %가 들어오나(후보 생성 관점)."""
    idx = prior.index.union(actual.index)
    p, a = prior.reindex(idx, fill_value=0), actual.reindex(idx, fill_value=0)
    top_a = set(a.nlargest(k).index)
    out = {"topk": len(top_a & set(p.nlargest(k).index)) / k,
           "mass": a[p.nlargest(k).index].sum() / a[list(top_a)].sum()}
    for m in (2, 4):
        wide = set(p[p > 0].nlargest(m * k).index)
        out[f"x{m}"] = len(top_a & wide) / k
    return out


COLS = ["topk", "mass", "x2", "x4"]


def evaluate(table: pd.DataFrame, seasons: pd.DataFrame, k: int) -> pd.DataFrame:
    rows = []
    for t in table.index[table.index >= MIN_HISTORY]:
        for name, pr in priors(table, seasons, t).items():
            rows.append({"season": t, "prior": name, **score(pr, table.loc[t], k)})
    return pd.DataFrame(rows)


def main(root: Path) -> None:
    e, roster, seasons = load(root)
    print(f"시즌 {e['season'].min()}–{e['season'].max()} (최종 집계만), 슬롯 {len(e):,}행\n")

    # ---- 1. 니케 사용률 ----
    pres = unit_presence(e)
    r = evaluate(pres, seasons, TOP_UNITS)
    print(f"## 1. 니케 사용률 예측 (시즌 {MIN_HISTORY}~, 시즌 평균)\n")
    print(r.groupby("prior")[COLS].agg(["mean", "min"]).round(2).to_markdown(), "\n")

    # 약점 속성이 직전과 같을 때 vs 다를 때
    last = r[r["prior"] == "직전 시즌"].copy()
    last["same_elem"] = [seasons.loc[t, "weak_element"] == seasons.loc[t - 1, "weak_element"] for t in last["season"]]
    print("직전 시즌 예측, 약점 속성이 직전과 같은가:\n")
    print(last.groupby("same_elem")[["topk", "x2"]].agg(["mean", "count"]).round(2).to_markdown(), "\n")

    # 신캐 몫: 이전 시즌에 한 번도 안 쓰인 니케가 차지한 슬롯 비율
    seen: set[str] = set()
    new_share = {}
    for t, grp in e.groupby("season"):
        new_share[t] = (~grp["unit_id"].isin(seen)).mean()
        seen |= set(grp["unit_id"])
    ns = pd.Series(new_share)
    ns = ns[ns.index >= MIN_HISTORY]
    print(f"처음 쓰인 니케(과거 기록 없음)가 차지한 슬롯: 평균 {ns.mean():.1%}, 최대 {ns.max():.1%} "
          f"(시즌 {ns.idxmax()}), 0 초과 시즌 {int((ns > 0).sum())}/{len(ns)}\n")

    # ---- 2. 짝 ----
    sq = squads(e)
    pr = pair_rate(sq)
    rp = evaluate(pr, seasons, TOP_PAIRS)
    print(f"## 2. 같은 덱 짝 예측 (상위 {TOP_PAIRS}쌍)\n")
    print(rp.groupby("prior")[COLS].agg(["mean", "min"]).round(2).to_markdown(), "\n")

    # ---- 3. 5인 구성 ----
    print("## 3. 5인 구성(스쿼드)의 재등장\n")
    hist_sq: set[frozenset] = set()
    hist_4: set[frozenset] = set()
    rows = []
    for t, grp in sq.groupby("season"):
        prev = sq[sq["season"] == t - 1]
        prev_sq = set(prev["squad"])
        prev_4 = {frozenset(c) for s in prev_sq for c in combinations(s, 4)}
        four = grp["squad"].map(lambda s: any(frozenset(c) in hist_4 for c in combinations(s, 4)))
        counts = grp["squad"].value_counts()
        if t >= MIN_HISTORY:
            rows.append({
                "season": t,
                "distinct": len(counts),
                "top10_share": counts.head(10).sum() / len(grp),
                "exact_prev": grp["squad"].isin(prev_sq).mean(),
                "exact_any": grp["squad"].isin(hist_sq).mean(),
                "4of5_prev": grp["squad"].map(lambda s: any(frozenset(c) in prev_4 for c in combinations(s, 4))).mean(),
                "4of5_any": four.mean(),
                **{f"4of5_any_d{d}": four[grp["deck_rank"] == d].mean() for d in (1, 5)},
            })
        hist_sq |= set(grp["squad"])
        hist_4 |= {frozenset(c) for s in grp["squad"] for c in combinations(s, 4)}
    s3 = pd.DataFrame(rows).set_index("season")
    print(f"덱 수/시즌 약 {len(sq) / sq['season'].nunique():.0f}\n")
    print(s3.agg(["mean", "min", "max"]).round(2).to_markdown(), "\n")

    # ---- 4. 버스트 구성 ----
    burst = roster.set_index("unit_id")["burst"].replace({"I-II-III": "X"})
    tmpl = sq["squad"].map(lambda s: "-".join(str(sum(burst.get(u) == b for u in s)) for b in ("I", "II", "III"))
                           + ("+X" if any(burst.get(u) == "X" for u in s) else ""))
    tab = pd.crosstab(sq["season"], tmpl, normalize="index")
    top = tab.mean().sort_values(ascending=False).head(6)
    print("## 4. 버스트 구성 (I-II-III 인원수)\n")
    print(pd.DataFrame({"평균 비율": top, "최소": tab[top.index].min(), "최대": tab[top.index].max()}).round(2).to_markdown(), "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
