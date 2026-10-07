"""사전 실험 2 준비 — 니케 풀과 S40 랭커 스쿼드를 평가기 이름으로 만든다.

풀 = S40 랭커가 쓴 니케 ∪ S40 이전 시즌만으로 낸 사전 지식 상위 50명(실험 1의 「혼합」 예측).
랭커 스쿼드 = S40 랭커 덱의 5인 구성(배치 순서는 덱 슬롯 순서 그대로), 같은 순서 구성은 하나로 센다.
랭커마다 5덱이 어느 스쿼드인지도 남긴다(players) — 랭커 구성 기준선(같은 육성·같은 보스의 시뮬 합)용.

사용: python prepare.py <nikke-analysis 경로> <nikke-calc 경로>  → pool.json, ranker_squads.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

SEASON = 40
PRIOR_TOP = 50
HERE = Path(__file__).resolve().parent


def main(analysis: Path, calc: Path) -> None:
    p = analysis / "data" / "processed"
    e = pd.read_csv(p / "raid_entries.csv", dtype={"unit_id": str, "player": str, "server": str},
                    keep_default_na=False, na_values={"unit_cp": [""], "unit_cores": [""]})
    seasons = pd.read_csv(p / "metrics_seasons.csv")
    seasons = seasons[seasons["final"]].set_index("season")
    e = e[(e["content"] == "soloraid") & e["season"].isin(seasons.index)]
    roster = pd.read_csv(p / "roster.csv", dtype={"unit_id": str}).fillna("")
    nikke = json.loads((calc / "data" / "parsed_nikke.json").read_text(encoding="utf-8"))

    def calc_name(uid: str) -> str | None:
        r = roster[roster["unit_id"] == uid].iloc[0]
        for n in (r["full_name_ko"], r["name_ko"]):
            if n and n in nikke:
                return n
        return None

    # 시즌 × 니케 사용률 → 혼합 예측 (실험 1과 같은 정의)
    rankers = e.groupby("season")[["server", "player"]].apply(lambda d: len(d.drop_duplicates()))
    used = e.drop_duplicates(["season", "server", "player", "unit_id"]).groupby(["season", "unit_id"]).size()
    pres = (used / rankers.reindex(used.index.get_level_values(0)).values).unstack(fill_value=0.0)
    past = pres.loc[pres.index < SEASON]
    weak = seasons.loc[SEASON, "weak_element"]
    same = [s for s in past.index if seasons.loc[s, "weak_element"] == weak]
    prior = 0.5 * past.iloc[-3:].mean() + 0.5 * past.loc[same[-1]] if same else past.iloc[-3:].mean()

    s40 = e[e["season"] == SEASON]
    pool_ids = set(prior.sort_values(ascending=False).head(PRIOR_TOP).index) | set(s40["unit_id"])
    pool, unmapped = {}, []
    for uid in sorted(pool_ids):
        n = calc_name(uid)
        if n is None:
            unmapped.append(uid)
            continue
        pool[n] = {"unit_id": uid, "burst": nikke[n]["burst_stage"], "element": nikke[n]["element_code"],
                   "s40_use": float(pres.loc[SEASON].get(uid, 0.0)), "prior": float(prior.get(uid, 0.0))}

    decks = (s40.sort_values("slot").groupby(["server", "player", "deck"])
             .agg(units=("unit_id", list), deck_score=("deck_score", "first")).reset_index())
    decks = decks[decks["units"].map(len) == 5]
    decks["deck_rank"] = decks.groupby(["server", "player"])["deck_score"].rank(ascending=False, method="first")
    squads: dict[tuple, dict] = {}
    for _, d in decks.iterrows():
        names = tuple(calc_name(u) for u in d["units"])
        if None in names:
            continue
        s = squads.setdefault(names, {"squad": list(names), "count": 0, "deck_rank": []})
        s["count"] += 1
        s["deck_rank"].append(int(d["deck_rank"]))
    out = sorted(squads.values(), key=lambda s: -s["count"])
    for s in out:
        s["deck_rank"] = sorted(set(s["deck_rank"]))
    index = {tuple(s["squad"]): i for i, s in enumerate(out)}
    players = []  # 랭커마다 5덱 → ranker_squads 번호 (덱 점수 순)
    for (server, player), g in decks.sort_values("deck_rank").groupby(["server", "player"]):
        ids = [index.get(tuple(calc_name(u) for u in us)) for us in g["units"]]
        if len(ids) == 5 and None not in ids:
            players.append({"server": server, "player": player, "squads": ids})

    meta = {"season": SEASON, "boss": seasons.loc[SEASON, "boss_ko"], "weak_element": weak,
            "decks": int(len(decks)), "unmapped_units": unmapped}
    (HERE / "pool.json").write_text(json.dumps({"meta": meta, "pool": pool}, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    (HERE / "ranker_squads.json").write_text(json.dumps({"meta": meta, "squads": out, "players": players}, ensure_ascii=False,
                                                        indent=1), encoding="utf-8")
    print(f"풀 {len(pool)}명 (매핑 실패 {unmapped}), 랭커 덱 {len(decks)}개 → 순서 구분 스쿼드 {len(out)}개, "
          f"구성(순서 무시) {len({frozenset(s['squad']) for s in out})}개")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
