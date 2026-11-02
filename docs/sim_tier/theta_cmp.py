"""analysis 체급(랭커 덱으로 잰 덱 대미지 배수)과 실험 33 넣어 보기(기준 덱 R에 한 명씩 넣은 덱 대미지)를
같은 버스트 단계 · 같은 쪽(자기 속성 / 다른 속성) 안에서 순위로 비교한다. 시뮬 0회.

    python docs/sim_tier/theta_cmp.py --analysis ../nikke-analysis [--out theta_cmp.csv]

analysis 쪽은 먼저 `pip install -e ".[dev]"` · `nikke build raids`가 필요하다(raid_entries.csv).
검토 기록: docs/SIM_TIER.md.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
E33 = ROOT / "experiments" / "33_role_vectors"
BEATS = {"작열": "풍압", "풍압": "철갑", "철갑": "전격", "전격": "수냉", "수냉": "작열"}  # run33.py와 같다


def spearman(a, b) -> float:
    return float(np.corrcoef(pd.Series(list(a)).rank(), pd.Series(list(b)).rank())[0, 1])


def analysis_theta(analysis_dir: Path) -> pd.DataFrame:
    sys.path.insert(0, str(analysis_dir / "src"))
    from nikke_analysis import power  # noqa: E402

    raw, history, _roster, config = power.load(analysis_dir / "data" / "processed")
    result = power.fit(power.cells(raw, history), weighting=config.rank_weighting)
    table = power.weights(result)
    names = history.drop_duplicates("unit_id").set_index("unit_id")["name_ko"]
    table["name"] = table["unit_id"].map(names)
    table["side"] = table["cell"].str.split(":").str[-1]
    # 애장품 칸이 있으면 그 칸(지금 상태)을 쓴다
    table = table.sort_values("treasure").drop_duplicates(["name", "side"], keep="last")
    return table.set_index(["name", "side"])[["log", "weight", "status", "decks"]]


def probe_theta() -> pd.DataFrame:
    attrs = json.loads((E33 / "attrs.json").read_text(encoding="utf-8"))["attrs"]
    rows = [json.loads(line) for line in gzip.open(E33 / "run_log" / "probe_R.jsonl.gz", "rt", encoding="utf-8")]
    base = {(r["deck"], r["element"]): r["total_damage"] for r in rows if r["stage"] == "0"}
    acc = defaultdict(list)
    for r in rows:
        if r["stage"] == "0" or not r["x"] or r["error"] or r["x"].startswith("test_"):
            continue
        stage = "3" if r["stage"] == "A" else r["stage"]  # 전 단계 버스트는 3단계 칸에 넣었다
        side = "own" if BEATS[attrs[r["x"]]["code"]] == r["element"] else "other"
        acc[(r["x"], stage, side)].append(math.log(r["total_damage"] / base[(r["deck"], r["element"])]))
    return pd.DataFrame([dict(name=x, stage=st, side=sd, slog=float(np.mean(v)), n=len(v))
                         for (x, st, sd), v in acc.items()])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis", type=Path, required=True, help="nikke-analysis 저장소 경로")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    m = probe_theta().join(analysis_theta(args.analysis.resolve()), on=["name", "side"], how="inner")
    m = m[m["status"] == "ok"]
    print("단계 쪽 n 순위상관(시뮬 대 analysis)")
    for (stage, side), g in m.groupby(["stage", "side"]):
        print(stage, side, len(g), round(spearman(g["slog"], g["log"]), 2))
    m["r_sim"] = m.groupby(["stage", "side"])["slog"].rank(pct=True)
    m["r_ana"] = m.groupby(["stage", "side"])["log"].rank(pct=True)
    m["diff"] = m["r_sim"] - m["r_ana"]
    cols = ["name", "stage", "side", "weight", "decks", "r_sim", "r_ana", "diff"]
    print("\n시뮬이 더 높게 보는 니케")
    print(m.sort_values("diff", ascending=False)[cols].head(15).round(2).to_string(index=False))
    print("\n시뮬이 더 낮게 보는 니케")
    print(m.sort_values("diff")[cols].head(15).round(2).to_string(index=False))
    if args.out:
        m.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
