"""실험 39 — 검증 시즌 자료: S23~S32의 니케 풀 · 그때 없던 애장품 · 보스 속성 · 랭커 덱.

    python -I experiments/39_bundle_explore/seasons39.py <nikke-analysis 경로>   → experiments/39_bundle_explore/seasons.json

실험 31 `seasons31.Data31`(날짜 경계 수정 포함)을 그대로 쓰고 시즌만 바꾼다. 실험 38이 원인 찾기에 쓴 S33~S42는 넣지 않는다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEASONS = tuple(range(23, 33))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


S31 = sys.modules.get("seasons31") or _load("seasons31", HERE.parent / "31_recent_seasons" / "seasons31.py")


def build(an: Path) -> dict:
    S31.SEASONS = SEASONS
    out = S31.build(an)
    out["boundary"] = [b for b in out["boundary"] if b["season"] in SEASONS]
    return out


def main(argv: list[str]) -> int:
    out = build(Path(argv[1]))
    (HERE / "seasons.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for s, v in out["seasons"].items():
        r = v["rankers"]
        print(s, v["boss"], v["code"], "풀", len(v["pool"]), "새 니케", len(v["new"]), "애장품 끔", len(v["favorite0"]),
              "대표 5덱", r["top_five"]["count"], "미지원", r["unsupported_share"])
    for b in out["boundary"]:
        print("경계", b)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
