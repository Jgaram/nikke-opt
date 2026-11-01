"""실험 22 — 시즌 자료 준비: nikke-analysis 원자료(공개 enikk 랭킹 · 출시일 · 애장품 · 시즌 달력)만 읽어 seasons.json을 만든다.

    python -I experiments/22_ranker_check/seasons22.py <nikke-analysis 경로>   → experiments/22_ranker_check/seasons.json

- 풀: 그 시즌 **끝**까지 출시된 니케 중 평가기 SSR 풀(실험 10 roster_ssr.json)에 있는 것. 시즌 중 출시된 니케도 랭커가 쓴다.
  평가기 시험용 test_B1~B3과 출시일 자료에 없는 니케는 늘 뺀다(`missing`).
- 보스: 시즌 보스 속성(enemy.code). 약점 속성 = 그 속성을 이기는 쪽.
- 애장품: 그 시즌 끝보다 뒤에 애장품이 나온 니케는 0단계(그때 없던 애장품을 끈다). 나머지는 평가기 기본(3단계).
- 랭커: 시즌마다 마지막 수집본(6개 서버 상위 50명 × 5덱). 니케 사용 수, 스쿼드(5명 집합) 빈도 · 가장 흔한 순서, 대표 5덱.
  enikk의 「Rei」는 레이(아야나미 레이, 831) 출시 전 시즌이면 라이(392)다.
"""

from __future__ import annotations

import csv
import glob
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
POOL177 = json.loads((HERE.parent / "10_rankerless_start" / "roster_ssr.json").read_text(encoding="utf-8"))["roster"]
SEASONS = (4, 9, 14, 18, 23, 28, 34, 40)   # README §시즌 — 시기 · 약점 속성이 고르게(결과 전 고정)
CODE = {"Water": "수냉", "Fire": "작열", "Wind": "풍압", "Iron": "철갑", "Electric": "전격"}
TOP_UNITS, TOP_SQUADS = 40, 40


def norm(s: str) -> str:
    return re.sub(r"\s*:\s*", ":", s.strip()).replace(" ", "")


class Data:
    def __init__(self, an: Path):
        p = an / "data" / "processed"
        self.an = an
        self.pooln = {norm(k): k for k in POOL177 if not k.startswith("test_")}
        self.roster = {r["unit_id"]: r for r in csv.DictReader(open(p / "roster.csv", encoding="utf-8"))}
        self.en2id: dict[str, set[str]] = defaultdict(set)
        self.id2ko: dict[str, str] = {}
        for r in csv.DictReader(open(p / "unit_aliases.csv", encoding="utf-8")):
            if r["language"] == "en" and r["kind"] == "full":
                self.en2id[r["alias"].strip().lower()].add(r["unit_id"])
            if r["language"] == "ko" and r["kind"] == "full":
                self.id2ko[r["unit_id"]] = r["alias"]
        for k, ids in list(self.en2id.items()):   # 같은 영어 이름(사쿠라 SSR · SR 등)은 SSR 쪽
            if len(ids) > 1:
                ssr = {i for i in ids if self.roster.get(i, {}).get("rarity") == "SSR"}
                if len(ssr) == 1:
                    self.en2id[k] = ssr
        self.seasons = {int(r["season"]): r for r in csv.DictReader(open(p / "soloraid_seasons.csv", encoding="utf-8"))}
        self.treasure = {r["unit_id"]: r["treasure_at"] for r in csv.DictReader(open(p / "treasures.csv", encoding="utf-8"))}

    def eval_name(self, uid: str) -> str | None:
        r = self.roster.get(uid, {})
        return self.pooln.get(norm(self.id2ko.get(uid) or r.get("name_ko", "")))

    def released(self, uid: str) -> str:
        r = self.roster[uid]
        return r["release_at"] or (r["release_date"] + "T00:00:00+09:00")

    def to_eval(self, en: str, end: str) -> str:
        k = en.strip().lower()
        if k == "rei":
            uid = "831" if self.released("831") <= end else "392"
        else:
            ids = self.en2id.get(k, set())
            if len(ids) != 1:
                return f"?{en}"
            uid = next(iter(ids))
        return self.eval_name(uid) or f"!{self.id2ko.get(uid) or en}"

    def season(self, s: int) -> dict:
        row = self.seasons[s]
        end = row["end_at"]
        pool = sorted({n for uid in self.roster if (n := self.eval_name(uid)) and self.released(uid) <= end})
        fav0 = sorted({n for uid, t in self.treasure.items() if (n := self.eval_name(uid)) and n in pool and t > end})
        fs = sorted(glob.glob(str(self.an / "data" / "raw" / "enikk_soloraid" / "*" / f"season-{s:03d}.json")))
        ranks = json.loads(Path(fs[-1]).read_text(encoding="utf-8"))["data"]["SRRankings"]
        units, squads, orders, fives = Counter(), Counter(), defaultdict(Counter), Counter()
        players = []
        unsupported = Counter()
        for p in ranks:
            decks = []
            for t in p["teams"]:
                names = [self.to_eval(c, end) for c in t["characters"]]
                unsupported.update(n for n in names if n[0] in "?!")
                units.update(names)
                fs_ = frozenset(names)
                squads[fs_] += 1
                orders[fs_][tuple(names)] += 1
                decks.append({"squad": names, "damage": t["damage"]})
            fives[frozenset(frozenset(d["squad"]) for d in decks)] += 1
            players.append({"rank": p["rank"], "server": p["server"], "damage": p["damage"], "decks": decks})
        n_slots = sum(units.values())
        top_sq = [{"members": sorted(fs_), "order": list(orders[fs_].most_common(1)[0][0]), "count": c}
                  for fs_, c in squads.most_common(TOP_SQUADS)]
        five, five_n = fives.most_common(1)[0]
        best = min(players, key=lambda x: x["rank"])
        return {
            "season": s, "boss": row["boss_ko"] or row["boss_en"], "element": row["element"], "weak": row["weak_element"],
            "code": CODE[row["element"]], "start": row["start_at"], "end": end,
            "pool": pool, "missing": sorted(set(POOL177) - set(pool)), "favorite0": fav0,
            "rankers": {
                "players": len(players), "decks": sum(len(p["decks"]) for p in players),
                "unsupported_share": round(sum(unsupported.values()) / n_slots, 4), "unsupported": unsupported.most_common(5),
                "units": units.most_common(TOP_UNITS), "squads": top_sq, "distinct_squads": len(squads),
                "top_five": {"count": five_n, "squads": [list(orders[q].most_common(1)[0][0]) for q in five]},
                "rank1": {"server": best["server"], "damage": best["damage"], "squads": [d["squad"] for d in best["decks"]]},
            },
        }


def main(argv: list[str]) -> int:
    d = Data(Path(argv[1]))
    out = {"source": {"repo": "Jgaram/nikke-analysis", "note": "enikk 랭킹 원자료 · 출시일 · 애장품 · 시즌 달력"},
           "seasons": {str(s): d.season(s) for s in SEASONS}}
    (HERE / "seasons.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for s, v in out["seasons"].items():
        r = v["rankers"]
        print(s, v["boss"], v["code"], "약점", v["weak"], "풀", len(v["pool"]), "애장품 끔", len(v["favorite0"]),
              "미지원 칸 %.1f%%" % (100 * r["unsupported_share"]), "대표 5덱", r["top_five"]["count"], "명")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
