"""실험 31 — 시즌 자료 준비: 최근 10시즌(S33~S42)의 니케 풀 · 그때 없던 애장품 · 보스 속성 · 랭커 덱.

    python -I experiments/31_recent_seasons/seasons31.py <nikke-analysis 경로>   → experiments/31_recent_seasons/seasons.json

실험 22 `seasons22.Data`를 그대로 쓰고 **날짜 경계 하나만 고친다.**
- nikke-analysis의 출시일 · 애장품 날짜 중 시각 없이 날짜만 있는 것(`T00:00:00`)은 그날 업데이트 점검 뒤에 들어온 것이다
  (`treasures.csv`의 `after_maintenance` = 1, 로스터 출처 = 패치 노트). 솔로 레이드는 점검 날 04:59:59에 끝나므로
  **시즌이 끝나는 날 날짜만 있는 출시 · 애장품은 그 시즌에 없던 것**으로 본다. 실험 22 규칙은 이것을 그 시즌에 넣었다.
  - 근거(`check_boundary`, S1~S42): 시즌 끝나는 날 날짜만으로 나온 니케 15명은 **그 시즌 랭커 사용이 모두 0회**다.
    그중 블랑(S1) · 레오나(S9) · 델타 : 닌자 시프(S30) · 솔린 : 프로스트 티켓(S31) 등 6명은 다음 시즌에 156~299회 쓰였다.
    애장품은 같은 날 점검으로 들어왔다(공지 · `after_maintenance` = 1). 사용 수로는 애장품 유무를 가릴 수 없다.
  - 이번 10시즌에서 바뀌는 것: S33 풀에서 레이블, S39 풀에서 라플라스 : 얼티밋 히어로가 빠지고, S39에 로산나 · 슈가 · 팬텀 · 플로라 애장품이 꺼진다.
  - 실험 22의 8시즌(`22_ranker_check/seasons.json`)은 고치지 않는다(결과 보존). 그 시즌의 최선 5덱에는 해당 니케가 없었다.
- 그 밖(풀 = 시즌 끝까지 출시, 애장품 = 시즌 끝 뒤에 나왔으면 0단계 · 나머지 3단계, 랭커 = 마지막 수집본 300명 × 5덱)은 실험 22와 같다.
- 더하는 것: 직전 시즌 대비 새 니케(`new`), 시즌 보스 그림 이름(`boss_image`), 원자료 커밋(`source.commit`).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP22 = HERE.parent / "22_ranker_check"
SEASONS = tuple(range(33, 43))   # 최근 10시즌: 랭커 기록이 있는 마지막 시즌 S42(2026-10-22 끝)까지(2026-11-01 사용자 지시)
DATE_ONLY = "T00:00:00"
AFTER_MAINT = "T05:00:00"        # 날짜만 있는 시각을 그날 점검 뒤로 옮긴다(솔로 레이드 끝 04:59:59보다 뒤)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


S22 = sys.modules.get("seasons22") or _load("seasons22", EXP22 / "seasons22.py")


def after_maintenance(ts: str) -> str:
    """날짜만 있는 시각(`YYYY-MM-DDT00:00:00+09:00`)은 그날 점검 뒤(05:00)로 본다. 시각이 있으면 그대로."""
    return ts.replace(DATE_ONLY, AFTER_MAINT, 1) if ts and ts[10:19] == DATE_ONLY else ts


class Data31(S22.Data):
    """실험 22 자료 읽기 + 날짜 경계 수정(출시 · 애장품)."""

    def __init__(self, an: Path):
        super().__init__(an)
        self.treasure = {k: after_maintenance(v) for k, v in self.treasure.items()}

    def released(self, uid: str) -> str:
        return after_maintenance(super().released(uid))

    def season(self, s: int) -> dict[str, Any]:
        v = super().season(s)
        v["boss_image"] = self.seasons[s].get("boss_image") or None
        prev = super().season(s - 1)["pool"] if s - 1 in self.seasons else []
        v["new"] = sorted(set(v["pool"]) - set(prev))
        return v

    def check_boundary(self, seasons: Any = None) -> list[dict[str, Any]]:
        """시즌 끝나는 날 날짜만으로 나온 니케 · 애장품과 그 시즌 · 다음 시즌 랭커 사용 수(규칙 근거)."""
        out = []
        seasons = sorted(self.seasons) if seasons is None else seasons
        for s in seasons:
            end = self.seasons[s]["end_at"]
            day = end[:10]
            if not self.ranks_exist(s):
                continue
            used = Counter(self.to_eval(ch, end) for p in self.ranks(s) for t in p["teams"] for ch in t["characters"])
            nxt = None
            if s + 1 in self.seasons and self.ranks_exist(s + 1):
                e2 = self.seasons[s + 1]["end_at"]
                nxt = Counter(self.to_eval(ch, e2) for p in self.ranks(s + 1) for t in p["teams"] for ch in t["characters"])
            for uid, r in self.roster.items():
                raw = r["release_at"] or (r["release_date"] + DATE_ONLY + "+09:00")
                n = self.eval_name(uid)
                if n and raw[:10] == day and raw[10:19] == DATE_ONLY:
                    out.append({"season": s, "kind": "출시", "name": n, "at": raw, "used": used.get(n, 0),
                                "used_next": None if nxt is None else nxt.get(n, 0)})
            for uid, t in self.treasure.items():
                n = self.eval_name(uid)
                if n and t[:10] == day:
                    out.append({"season": s, "kind": "애장품", "name": n, "at": t[:10], "used": used.get(n, 0),
                                "used_next": None if nxt is None else nxt.get(n, 0)})
        return out

    def ranks_exist(self, s: int) -> bool:
        return any((self.an / "data" / "raw" / "enikk_soloraid").glob(f"*/season-{s:03d}.json"))


def commit_of(an: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(an), "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def build(an: Path) -> dict[str, Any]:
    d = Data31(an)
    seasons = {str(s): d.season(s) for s in SEASONS}
    for v in seasons.values():   # 랭커가 쓴 니케는 모두 그 시즌 풀에 있어야 한다(풀을 너무 좁히지 않았는지)
        used = {n for n, _ in v["rankers"]["units"]}
        outside = sorted(n for n in used if n[0] not in "?!" and n not in v["pool"])
        assert not outside, (v["season"], outside)
    return {"source": {"repo": "Jgaram/nikke-analysis", "commit": commit_of(an),
                       "note": "enikk 랭킹 원자료 · 출시일 · 애장품 · 시즌 달력. 날짜만 있는 출시 · 애장품은 그날 점검 뒤로 본다"},
            "boundary": [b for b in d.check_boundary() if b["season"] <= max(SEASONS)],
            "seasons": seasons}


def main(argv: list[str]) -> int:
    out = build(Path(argv[1]))
    (HERE / "seasons.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for s, v in out["seasons"].items():
        r = v["rankers"]
        print(s, v["boss"], v["code"], "약점", v["weak"], "풀", len(v["pool"]), "새 니케", len(v["new"]),
              "애장품 끔", len(v["favorite0"]), "대표 5덱", r["top_five"]["count"], "미지원", r["unsupported_share"])
    for b in out["boundary"]:
        print("경계", b)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
