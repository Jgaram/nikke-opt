"""현황판 — 실험 36(최근 10시즌 현황판 다시 계산) GitHub Pages 정적 사이트 만들기.

    python web/build.py --out _site          → _site/index.html · app.js · style.css · data.json
    python -m http.server -d _site 8000       (로컬에서 보기: http://localhost:8000)
    python web/build.py --out _site --exp <폴더>   (개발용: 다른 폴더의 analysis.json · run_log를 읽는다)

- 시즌 자료(풀 · 새 니케 · 그때 없던 애장품 · 날짜 경계로 뺀 것 · 랭커 덱)는 계속 `experiments/31_recent_seasons/seasons.json`,
  우리 쪽(큰 분류 · 세부 분류 · 랭커 대조 지표)은 `run36.py analyze`(= run31 analyze 모양 + 맨 위 `procedure`)가 만든
  `experiments/36_season_refresh/analysis.json`을 그대로 옮긴다. 정의 · 계산을 여기서 다시 하지 않는다(실험 모듈도 불러오지 않는다).
- 화면용으로 더하는 것: 세부 분류 새 덱의 자리 맞춤 · 덱 사이 옮긴 니케(겹침 최대, 되돌린 f83f54a 화면과 같은 규칙),
  덱별 니케 딜(`run_log/S??/members.json`), 랭커 덱 값(`run_log/S??/rankers.json`),
  후처리 뒤 최선 5덱(`run_log/S??/post.json` — 값은 그대로, 니케별 장비 옵션 배분 · 큐브와 선택지 라벨만 화면용으로 펼친다).
  같은 후처리를 한 랭커 대표 5덱 · 랭커 스쿼드로 짠 최선 5덱(`run_log/S??/rpost.json`, rpost36.py — 비교용).
- 아직 없는 결과는 「계산 전」(후처리는 「계산 중」)으로 둔다. 시뮬은 하지 않는다. 평가기 · numpy도 필요 없다.
- 니케 얼굴 · 속성 · 버스트 · 보스 그림은 `web/icons/`(nikke-analysis에서 `web/sync_icons.py`로 받은 것)를
  그대로 복사하고, 이름 → 그림은 `web/icons/icons.json`으로 잇는다.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from itertools import permutations
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EXP = ROOT / "experiments" / "36_season_refresh"                       # 결과(analysis.json · run_log)
SEASONS = ROOT / "experiments" / "31_recent_seasons" / "seasons.json"   # 시즌 자료(실험 36도 이것을 쓴다)
NIKKE_INFO = ROOT / "experiments" / "06_control_menu" / "nikke_info.json"
STATIC = ("index.html", "app.js", "style.css")
ICONS = HERE / "icons"
ICON_DIRS = ("units", "bosses", "elements", "bursts")
REPO_URL = "https://github.com/Jgaram/nikke-opt"
BURST_STAGE = {"I": "1", "II": "2", "III": "3", "I-II-III": "A"}   # 로스터 표기 → nikke_info burst_stage
EL_EN = {"전격": "Electric", "풍압": "Wind", "철갑": "Iron", "수냉": "Water", "작열": "Fire"}
BOSS_INFO = {"nocore": {"label": "코어 없음", "core_px": 0}, "core30": {"label": "코어 30px", "core_px": 30}}
BOSSES = tuple(BOSS_INFO)
PARTS = ("B_s0", "B_s1", "end", "core30", "members", "rankers", "post")   # run36.PARTS
PART_KEYS = ("evals", "sims", "sims_new", "seconds", "best", "requests", "blocks_n", "arm", "copied_from", "skipped", "squads")
EVALUATOR = "nikke-calc-rs 8bc51a2(원본 nikke-calc 67835ca 포팅)"   # 실험 36 README
EVALUATOR_ID = "nikke-calc-rs 8bc51a2"                             # part_*.json의 evaluator 값
POST_VALUES = ("pre", "ctrl", "E0", "O", "C2", "final")            # run36.post_deck의 단계별 값(억)
DEFAULT_CUBE = "렐릭 베어 큐브"                                     # 실험 17 cubes.DEFAULT_CUBE(출발 큐브 = 기본 스펙)
CLASS_SHOW = 3             # 큰 분류: 앞 3개는 펼쳐 두고 나머지는 더보기(2026-11-01 사용자 결정, 실험 28)
SUB_SHOW = 3               # 세부 분류: 앞 3개 = 보일 것, 나머지 = 더보기(실험 28 tree28.SHOW)


def read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def provenance(exp: Path) -> dict[str, Any]:
    """데이터의 출처 커밋: 결과 폴더(기본 실험 36)를 마지막으로 바꾼 커밋(얕은 clone이면 HEAD)."""
    rel = exp.relative_to(ROOT).as_posix() if exp.is_relative_to(ROOT) else None
    line = (git("log", "-1", "--format=%H|%cI|%s", "--", rel) if rel else "") or git("log", "-1", "--format=%H|%cI|%s")
    h, date, subj = (line.split("|", 2) + ["", "", ""])[:3] if line else ("", "", "")
    return {"commit": h, "short": h[:7], "date": date, "subject": subj}


# ---------------------------------------------------------------- 시즌 하나

def align_sub(rep: list[list[str]], s: dict[str, Any]) -> dict[str, Any]:
    """세부 분류 하나: 새 덱을 바뀐 덱 자리에 겹침이 가장 큰 순서로 놓고, 덱 사이 옮긴 니케를 찾는다."""
    ch = [i - 1 for i in s["changed"]]
    new = list(zip(s["new_decks"], s.get("new_values") or [None] * len(s["new_decks"])))
    best = max(permutations(range(len(new))),
               key=lambda p: sum(len(set(rep[ch[k]]) & set(new[p[k]][0])) for k in range(len(ch))))
    slots = [{"no": ch[k] + 1, "order": list(new[best[k]][0]), "value": new[best[k]][1]} for k in range(len(ch))]
    home = {n: i + 1 for i, q in enumerate(rep) for n in q}
    moved = [[n, home[n], sl["no"]] for sl in slots for n in sl["order"] if n in home and home[n] != sl["no"]]
    out = {k: s.get(k) for k in ("total", "J", "J_other", "changed", "out", "in", "moves")}
    out.update({"slots": slots, "moved": moved})
    return out


def deck(order: list[str], value: float | None, mem: dict[str, Any] | None) -> dict[str, Any]:
    m = (mem or {}).get(",".join(order)) or {}
    return {"order": list(order), "value": value, "members": m.get("members")}


def class_block(c: dict[str, Any], mem: dict[str, Any] | None) -> dict[str, Any]:
    rep = [list(q) for _, q in c["decks"]]
    out = {k: c.get(k) for k in ("name", "total", "ratio", "exact", "subs_count", "capped", "subs_1deck", "vs")}
    out["decks"] = [deck(list(q), v, mem) for v, q in c["decks"]]
    out["subs"] = [align_sub(rep, s) for s in c.get("subs") or []]
    out["more_left"] = max(0, (c.get("subs_count") or 0) - len(out["subs"]))
    return out


def ranker_set(squads: list[list[str]], rv: dict[str, Any] | None, b: str) -> dict[str, Any]:
    decks = []
    for q in squads:
        e = (rv or {}).get(",".join(q)) or {}
        decks.append({"order": list(q), "value": e.get(b), "members": e.get(f"{b}_members")})
    vals = [d["value"] for d in decks]
    return {"total": sum(vals) if vals and all(v is not None for v in vals) else None, "decks": decks}


# ---------------------------------------------------------------- 후처리 5덱(run36 part_post · post_deck)

def short_alloc(lb: str | None) -> list[str]:
    """장비 옵션 배분 라벨(run35.label) → 화면용 짧은 조각. 「우코4+공4+크확2+크뎀2」 → [우4, 공4, 크확2, 크뎀2]."""
    return [("우" + p[2:]) if p.startswith("우코") else p for p in (lb or "").split("+") if p]


def short_cube(name: str) -> str:
    """「렐릭 어설트 큐브」 → 「어설트」, 「택티컬 베어 큐브」 → 「택티컬 베어」(원래 이름은 cube에 그대로 둔다)."""
    n = name.removesuffix(" 큐브")
    return n.removeprefix("렐릭 ") or n


def choice(label: str, squad: list[str]) -> dict[str, Any]:
    """선택지 라벨 `<니케|squad>:<축>:<값>` → {who, axis, value, target, label}. 니케 이름에 「 : 」가 있어 앞에서 자르지 않고
    스쿼드 이름과 맞춘다. 값이 스쿼드 니케(카메라)거나 `이름=니케`(버충 담당)면 그 니케를 target으로 뗀다."""
    who = next((n for n in sorted(squad, key=len, reverse=True) if label.startswith(f"{n}:")), None)
    rest = label[len(who) + 1:] if who else label.removeprefix("squad:")
    axis, _, value = rest.partition(":")
    target = None
    head, eq, tail = value.rpartition("=")
    if value in squad:
        target, value = value, ""
    elif eq and tail in squad:
        target, value = tail, head
    return {"who": who, "axis": axis, "value": value, "target": target, "label": label}


def post_deck_view(x: dict[str, Any]) -> dict[str, Any]:
    """덱 하나: 값(사전 · 단계별 · 최종)은 그대로, 니케별 배분 · 큐브(최종 선택에 없으면 기본 큐브)와 큐브 밖 선택지를 펼친다."""
    q = list(x["squad"])
    alloc = x.get("alloc") or {}
    picks = [choice(lb, q) for lb in x.get("final_variants") or []]
    cubes = {c["who"]: c["value"] for c in picks if c["axis"] == "cube" and c["who"]}
    gear = {n: {"alloc": alloc.get(n), "alloc_short": short_alloc(alloc.get(n)), "cube": cubes.get(n, DEFAULT_CUBE),
                "cube_short": short_cube(cubes[n]) if n in cubes else None} for n in q}
    return {"id": x.get("id"), "order": q, "win": x.get("win"), **{k: x.get(k) for k in POST_VALUES}, "value": x.get("final"),
            "gear": gear, "choices": [c for c in picks if c["axis"] != "cube"], "sims": x.get("sims"), "seconds": x.get("seconds")}


def post_block(d: Path, row: dict[str, Any] | None) -> dict[str, Any]:
    """`run_log/S??/post.json`(없으면 analysis.json 줄의 `post`). 없으면 「계산 중」 — 끝난 덱 수만 센다(덱 값은 5덱이 다 끝난 뒤 보인다)."""
    p = read_json(d / "post.json") or (row or {}).get("post")
    if not p:
        return {"status": "running", "decks_done": len(list((d / "post").glob("S*-[0-9].json"))) if (d / "post").is_dir() else 0}
    return {"status": "done", "decks_done": len(p["decks"]), "total": p.get("total"),
            "procedure": {k: p.get(k) for k in ("arm", "opt", "c2", "cube")},
            "decks": [post_deck_view(x) for x in p["decks"]]}


def rpost_block(p: dict[str, Any] | None) -> dict[str, Any]:
    """`run_log/S??/rpost.json`(rpost36.py): 랭커 대표 5덱(top) · 랭커 스쿼드로 짠 최선 5덱(pack)을 우리 A와 같은 후처리로.
    없으면 「계산 전」. 지원하지 않는 니케가 든 묶음은 None."""
    if not p:
        return {"status": "pending"}
    return {"status": "done", "sims": p.get("sims"), "decks_new": p.get("decks_new"),
            "sets": {k: None if x is None else {"total": x["total"], "decks": [post_deck_view(y) for y in x["decks"]]}
                     for k, x in (p.get("sets") or {}).items()}}


def season_block(s: int, v: dict[str, Any], row: dict[str, Any] | None, exp: Path, boundary: list[dict[str, Any]]) -> dict[str, Any]:
    d = exp / "run_log" / f"S{s:02d}"
    rv = (read_json(d / "rankers.json") or {}).get("squads")
    mem = read_json(d / "members.json") or {}
    rk = v["rankers"]
    parts = {p: x for p in PARTS if (x := read_json(d / f"part_{p}.json"))}
    rp = read_json(d / "rpost.json") or (row or {}).get("rpost")
    if rp:                                  # 랭커 덱 후처리(rpost36.py)도 시뮬 비용에 넣는다
        parts["rpost"] = {"sims": rp.get("sims") or 0, "evaluator": EVALUATOR_ID}
    blk: dict[str, Any] = {
        "season": s, "boss_name": v["boss"], "element": v["element"], "weak": v["weak"], "code": v["code"],
        "start": v["start"], "end": v["end"], "pool": len(v["pool"]), "new": v.get("new") or [], "favorite0": v["favorite0"],
        "excluded_nikke": sorted(x["name"] for x in boundary if x["season"] == s and x["kind"] == "출시"),
        "excluded_treasure": sorted(x["name"] for x in boundary if x["season"] == s and x["kind"] == "애장품"),
        "rankers": {"players": rk["players"], "decks": rk["decks"], "distinct_squads": rk["distinct_squads"],
                    "top_five_count": rk["top_five"]["count"], "rank1_server": rk["rank1"]["server"],
                    "rank1_damage": rk["rank1"]["damage"], "units": rk["units"][:25],
                    "squads": [{"order": q["order"], "count": q["count"],
                                "values": {b: ((rv or {}).get(",".join(q["order"])) or {}).get(b) for b in BOSSES}}
                               for q in rk["squads"]],
                    "evaluated": rv is not None},
        "parts": {p: {k: x.get(k) for k in PART_KEYS if x.get(k) is not None} for p, x in parts.items()},
        "sims_total": sum(x.get("sims") or 0 for x in parts.values()),
        "sims_new": sum(x.get("sims_new", x.get("sims")) or 0 for x in parts.values()),   # 실험 32 기록을 옮긴 부분은 0
        "evaluators": sorted({x["evaluator"] for x in parts.values() if x.get("evaluator")}),
        "status": "pending", "arm": None, "by_boss": {}, "post": post_block(d, row), "rpost": rpost_block(rp),
    }
    for b in BOSSES:
        blk["by_boss"][b] = {"status": "pending",
                             "ranker_sets": {"top_five": ranker_set(rk["top_five"]["squads"], rv, b),
                                             "rank1": ranker_set(rk["rank1"]["squads"], rv, b)}}
    if row:
        blk["status"], blk["arm"] = row["status"], row.get("arm")
        for b, x in (row.get("by_boss") or {}).items():
            blk["by_boss"][b].update({
                "status": "done", "best": x["best"], "n97": x["n97"], "comps": x["comps"], "map_exact": x["map_exact"],
                "classes": [class_block(c, mem.get(b)) for c in x["classes"]],
                "metrics": x["rankers"],
            })
    A = (blk["by_boss"]["nocore"].get("classes") or [None])[0]
    if A and blk["post"]["status"] == "done":   # 후처리한 5덱이 코어 없음 큰 분류 A와 같은 5덱인가(화면 안내용)
        blk["post"]["same_as_A"] = {frozenset(x["order"]) for x in A["decks"]} == {frozenset(x["order"]) for x in blk["post"]["decks"]}
    return blk


# ---------------------------------------------------------------- 그림

def base_name(n: str) -> str:
    """랭커 덱의 평가기 밖 니케는 `!이름`(로스터에 있음) · `?영문`(못 찾음)으로 적혀 있다 — 앞 표시를 뗀다."""
    return n[1:] if n[:1] in "!?" else n


def icon_index() -> dict[str, Any]:
    return read_json(ICONS / "icons.json") or {"units": {}, "bosses": {}}


def site_names(seasons: list[dict[str, Any]]) -> set[str]:
    """화면에 니케로 나오는 이름 전부(덱 · 세부 분류 · 새 니케 · 애장품 · 랭커 스쿼드 · 사용 순위)."""
    lists = ("order", "new", "favorite0", "excluded_nikke", "excluded_treasure", "ours_only", "rankers_only", "out", "in")
    pairs = ("units", "members", "moved")      # [이름, 값, …] 목록
    out: set[str] = set()

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k in lists and isinstance(v, list):
                    out.update(x for x in v if isinstance(x, str))
                elif k in pairs and isinstance(v, list):
                    out.update(x[0] for x in v if isinstance(x, list) and x and isinstance(x[0], str))
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(seasons)
    return out


def pool_names() -> set[str]:
    """10시즌 풀 전원. 그림은 이것까지 받아 둔다 — 결과가 들어와 새 니케가 화면에 나와도 다시 받지 않게."""
    sd = read_json(SEASONS) or {"seasons": {}}
    return set().union(*(set(v["pool"]) for v in sd["seasons"].values()))


def nikke_table(names: set[str], icons: dict[str, Any]) -> dict[str, Any]:
    """이름 → 무기 · 버스트(평가기 nikke_info) + 얼굴 번호 · 속성(nikke-analysis 로스터)."""
    info = (read_json(NIKKE_INFO) or {}).get("nikke", {})
    units = icons.get("units", {})
    out: dict[str, Any] = {}
    for n in sorted(names):
        i, u = info.get(n), units.get(base_name(n))
        if not i and not u:
            continue
        e: dict[str, Any] = {}
        if i:
            e.update({"w": i["weapon"], "b": i["burst_stage"]})
        if u:
            e.update({"img": f"icons/units/{u['id']}.webp", "el": u.get("el") or []})
            e.setdefault("b", BURST_STAGE.get(u.get("b") or ""))
        out[n] = e
    return out


def boss_image(s: int, icons: dict[str, Any]) -> str | None:
    img = icons.get("bosses", {}).get(str(s))
    return f"icons/bosses/{img}.webp" if img and (ICONS / "bosses" / f"{img}.webp").exists() else None


# ---------------------------------------------------------------- 전체

def build_data(exp: Path = EXP) -> dict[str, Any]:
    sd = read_json(SEASONS)
    an = read_json(exp / "analysis.json") or {}
    rows = {r["season"]: r for r in an.get("rows") or []}
    seasons = [season_block(int(k), v, rows.get(int(k)), exp, sd.get("boundary") or []) for k, v in sd["seasons"].items()]
    icons = icon_index()
    for x in seasons:
        x["boss_img"] = boss_image(x["season"], icons)
    names = site_names(seasons)
    nikke = nikke_table(names, icons)
    done = [x for x in seasons if x["status"] == "done"]

    def readme(d: str) -> str:
        return f"{REPO_URL}/blob/main/experiments/{d}/README.md"

    return {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": provenance(exp), "repo": REPO_URL,
        "experiment": {"id": 36, "title": "최근 10시즌 현황판 다시 계산",
                       "readme": readme("36_season_refresh"), "exp31_readme": readme("31_recent_seasons"),
                       "exp28_readme": readme("28_plan_tree"), "exp30_readme": readme("30_element_map"),
                       "exp32_readme": readme("32_primitive_control"), "exp35_readme": readme("35_equip_options"),
                       "ranker_repo": "https://github.com/Jgaram/nikke-analysis",
                       "analysis_repo_commit": (sd.get("source") or {}).get("commit"),
                       "evaluator": EVALUATOR, "arm": an.get("arm"), "procedure": an.get("procedure")},
        "summary": an.get("summary"),
        "progress": {"done": len(done), "total": len(seasons), "sims": sum(x["sims_total"] for x in seasons),
                     "sims_new": sum(x["sims_new"] for x in seasons),
                     "post": sum(1 for x in seasons if x["post"]["status"] == "done"),
                     "started": sum(1 for x in seasons if x["parts"])},
        "show": {"classes": CLASS_SHOW, "subs": SUB_SHOW},
        "bosses": BOSS_INFO, "seasons": seasons, "nikke": nikke,
        "icons": {"source": icons.get("source") or {},
                  "missing": sorted(n for n in names if not nikke.get(n, {}).get("img"))},
    }


def build(out: Path, exp: Path = EXP) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    data = build_data(exp)
    for f in STATIC:
        shutil.copyfile(HERE / f, out / f)
    for d in ICON_DIRS:
        if (ICONS / d).is_dir():
            shutil.copytree(ICONS / d, out / "icons" / d, dirs_exist_ok=True)
    (out / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=ROOT / "_site")
    p.add_argument("--exp", type=Path, default=EXP, help="analysis.json · run_log가 있는 폴더(개발용, 기본은 실험 36 폴더). "
                   "시즌 자료는 늘 실험 31의 seasons.json")
    a = p.parse_args(argv)
    d = build(a.out, a.exp)
    pr = d["progress"]
    print(f"{a.out}: 시즌 {pr['done']}/{pr['total']} 완료 · 후처리 {pr['post']} · 시작 {pr['started']} · 시뮬 {pr['sims']} · data.json "
          f"{(a.out / 'data.json').stat().st_size / 1024:.0f} KB")
    if d["icons"]["missing"]:
        print(f"얼굴 그림 없는 니케 {len(d['icons']['missing'])}명: {', '.join(d['icons']['missing'])} "
              "— python web/sync_icons.py --analysis <nikke-analysis 경로>", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
