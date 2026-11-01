"""실험 23 — 랭커별 5덱 추출: 실험 22와 같은 enikk 원자료 · 같은 이름 변환(`seasons22.Data`)으로 랭커 300명 각자의 5덱을 남긴다.

    python -I experiments/23_deck_similarity/rankers23.py <nikke-analysis 경로>   → experiments/23_deck_similarity/ranker_fives.json

실험 22 `seasons.json`은 랭커 덱을 집계(상위 40 스쿼드 · 대표 5덱 · 1위 5덱)로만 남긴다. 유사도는 랭커 한 명의 5덱 묶음이 필요해서 따로 뽑는다.
시즌 · 수집본(시즌마다 마지막) · 이름 변환은 실험 22와 같다. 평가기 풀 밖 니케는 `?이름` · `!이름` 그대로 둔다.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP22 = HERE.parent / "22_ranker_check"
OUT = HERE / "ranker_fives.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


S22 = sys.modules.get("seasons22") or _load("seasons22", EXP22 / "seasons22.py")


def players(d: "S22.Data", s: int) -> list[dict]:
    end = d.seasons[s]["end_at"]
    out = []
    for p in d.ranks(s):
        decks = [[d.to_eval(c, end) for c in t["characters"]] for t in p["teams"]]
        out.append({"rank": p["rank"], "server": p["server"], "damage": p["damage"], "decks": decks})
    return out


def main(argv: list[str]) -> int:
    an = Path(argv[1])
    d = S22.Data(an)
    rev = subprocess.run(["git", "-C", str(an), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    seasons = {str(s): players(d, s) for s in S22.SEASONS}
    lines = ["{", f' "source": {json.dumps({"repo": "Jgaram/nikke-analysis", "commit": rev, "note": "enikk 원자료, 시즌마다 마지막 수집본 · 실험 22 이름 변환"}, ensure_ascii=False)},',
             ' "seasons": {']
    for i, (s, ps) in enumerate(seasons.items()):
        rows = ",\n".join("   " + json.dumps(p, ensure_ascii=False) for p in ps)
        lines.append(f'  "{s}": [\n{rows}\n  ]' + ("," if i < len(seasons) - 1 else ""))
    lines += [" }", "}"]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{OUT.name}: " + " · ".join(f"S{s} {len(ps)}명" for s, ps in seasons.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
