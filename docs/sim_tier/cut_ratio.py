"""솔로 레이드 상위 % 컷 ÷ 같은 시즌 KR 상위 50명 점수 중앙값. 계정 수준(3% · 10%)을 비율로 맞출 때의 근거. 시뮬 0회.

    git -C <nikke-soloraid-cutoff> fetch --depth 1 origin gh-pages
    git -C <nikke-soloraid-cutoff> show FETCH_HEAD:data.json > cutoff.json
    python docs/sim_tier/cut_ratio.py --cutoff cutoff.json --entries ../nikke-analysis/data/processed/raid_entries.csv

컷 단위는 억(점수 ÷ 1e8)이다. 시즌 번호는 두 저장소가 같다(S19 베히모스 · S29 마더 웨일 · S42 앨트루이아로 확인).
검토 기록: docs/SIM_TIER.md.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", type=Path, required=True, help="nikke-soloraid-cutoff gh-pages의 data.json")
    ap.add_argument("--entries", type=Path, required=True, help="nikke-analysis raid_entries.csv")
    ap.add_argument("--server", default="KR")
    args = ap.parse_args()
    cut = json.loads(args.cutoff.read_text(encoding="utf-8"))
    e = pd.read_csv(args.entries)
    e = e[e["content"] == "soloraid"]
    players = e.drop_duplicates(["season", "server", "player"])
    rows = []
    for c in cut["past"]:
        season, cuts = int(c["season"][1:]), c["cuts"].get(args.server, {})
        score = players[(players["season"] == season) & (players["server"] == args.server)]["score"] / 1e8
        if score.empty or "3" not in cuts:
            continue
        med = score.median()
        rows.append(dict(season=season, boss=c["boss"], top50_median=round(med, 1), cut3=cuts.get("3"), cut10=cuts.get("10"),
                         r3=round(cuts["3"] / med, 2), r10=round(cuts["10"] / med, 2) if cuts.get("10") else None))
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
