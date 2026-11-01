"""실험 22 현황판 — GitHub Pages 정적 사이트 만들기.

    python web/build.py --out _site          → _site/index.html · app.js · style.css · data.json
    python -m http.server -d _site 8000       (로컬에서 보기: http://localhost:8000)

- 지표(N25 · D4 · V_top · V_r1 · V_pack · 주력 · 더 맞는 보스 · 판단)는 실험 22 `analyze22.season_metrics` · `judge`를
  그대로 부른다. 정의를 여기서 다시 쓰지 않는다.
- 그 밖에 화면에 필요한 것(수렴 곡선 · 단계별 시뮬 수 · 2~8순위 5덱 · 덱별 딜 · 랭커 덱 값 · 기본 레이어 컨트롤)을
  같은 run_log에서 읽어 붙인다. 시뮬은 하지 않는다. 아직 없는 결과 파일은 「계산 전」으로 둔다.
- 니케 얼굴 · 속성 · 버스트 · 보스 그림은 `web/icons/`(nikke-analysis에서 `web/sync_icons.py`로 받은 것)를
  그대로 복사하고, 이름 → 그림은 `web/icons/icons.json`으로 잇는다.
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EXP = ROOT / "experiments" / "22_ranker_check"
NIKKE_INFO = ROOT / "experiments" / "06_control_menu" / "nikke_info.json"
STATIC = ("index.html", "app.js", "style.css")
ICONS = HERE / "icons"
ICON_DIRS = ("units", "bosses", "elements", "bursts")
REPO_URL = "https://github.com/Jgaram/nikke-opt"
E8 = 1e8
BURST_STAGE = {"I": "1", "II": "2", "III": "3", "I-II-III": "A"}   # 로스터 표기 → nikke_info burst_stage

WEAK_KO = {"Electric": "전격", "Wind": "풍압", "Iron": "철갑", "Water": "수냉", "Fire": "작열"}
BOSS_INFO = {"nocore": {"label": "코어 없음", "core_px": 0}, "core30": {"label": "코어 30px", "core_px": 30}}
PHASES = ("설계", "구성", "탐색", "킥", "순서")          # precompute 기록의 phase(「탐색 N」은 탐색으로 묶는다)
REACH = (0.95, 0.99, 0.995, 1.0)
COEF_TOP = 20


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


A22 = sys.modules.get("analyze22") or _load("analyze22", EXP / "analyze22.py")
R22, R9 = A22.R22, A22.R9


def read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def provenance() -> dict[str, Any]:
    """데이터의 출처 커밋: 실험 22 폴더를 마지막으로 바꾼 커밋(얕은 clone이면 HEAD)."""
    line = git("log", "-1", "--format=%H|%cI|%s", "--", str(EXP.relative_to(ROOT))) or git("log", "-1", "--format=%H|%cI|%s")
    h, date, subj = (line.split("|", 2) + ["", "", ""])[:3] if line else ("", "", "")
    return {"commit": h, "short": h[:7], "date": date, "subject": subj}


# ---------------------------------------------------------------- 사전 계산 한 판(시즌 × 보스)

def deck_index(name: str) -> dict[tuple, float]:
    """평가한 스쿼드(배치 순서 그대로) → 180초 딜(억)."""
    p = A22.LOG / f"precompute_{name}.jsonl.gz"
    if not p.exists():
        return {}
    out: dict[tuple, float] = {}
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                if r.get("total_damage"):
                    out[tuple(r["squad"])] = r["total_damage"] / E8
    return out


def phase_counts(name: str) -> dict[str, int]:
    p = A22.LOG / f"precompute_{name}.jsonl.gz"
    c: Counter = Counter()
    if p.exists():
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    ph = json.loads(line).get("phase") or "기타"
                    c["탐색" if ph.startswith("탐색") else ph if ph in PHASES else "기타"] += 1
    return {k: c[k] for k in (*PHASES, "기타") if c[k]}


def reach(history: list[dict], final: float) -> dict[str, int | None]:
    """수렴 곡선에서 최종 합의 p 이상에 처음 닿은 평가 수."""
    out: dict[str, int | None] = {}
    for p in REACH:
        hit = next((h["evals"] for h in history if h["pack"] >= p * final - 1e-9), None)
        out[f"{p * 100:g}"] = hit
    return out


def leader(members: list[list] | None) -> str | None:
    return A22.main_dealer(members) if members else None


def pack_summary(sets: list[list[str]], idx: dict[tuple, float]) -> list[dict[str, Any]]:
    return [{"order": list(q), "value": idx.get(tuple(q))} for q in sets]


def alternatives(pre: dict[str, Any], idx: dict[tuple, float]) -> list[dict[str, Any]]:
    """2~8순위: 사전 계산이 뽑은 「앞 순위들과 같은 덱을 2개 이하만 공유하는」 다음 최선 5덱(run11.extract)."""
    best = [list(q) for _, q in pre["final"]["squads"]]
    best_set = {frozenset(q) for q in best}
    best25 = {n for q in best for n in q}
    out = []
    for sets, tot in zip(pre.get("sets", []), pre.get("set_totals", [])):
        if {frozenset(q) for q in sets} == best_set:
            continue
        s25 = {n for q in sets for n in q}
        out.append({"total": tot, "ratio": tot / pre["final"]["total"], "decks": pack_summary(sets, idx),
                    "same_decks": sum(frozenset(q) in best_set for q in sets), "shared": len(s25 & best25),
                    "in": sorted(s25 - best25), "out": sorted(best25 - s25)})
    for i, a in enumerate(out):
        a["rank"] = i + 2
    return out


def ranker_side(s: int, b: str, ours: list[list[str]], rv: dict[str, dict]) -> dict[str, Any]:
    """랭커 대표 5덱 · 1위 5덱 · 상위 40 스쿼드로만 짠 5덱의 이 보스 시뮬 값."""
    rk = R22.season(s)["rankers"]

    def decks(squads: list[list[str]]) -> dict[str, Any]:
        rows = []
        for q in squads:
            e = rv.get(",".join(q), {})
            rows.append({"order": list(q), "value": e.get(b), "members": e.get(f"{b}_members"), "leader": leader(e.get(f"{b}_members"))})
        tot = None if any(r["value"] is None for r in rows) else sum(r["value"] for r in rows)
        return {"decks": rows, "total": tot}

    pack_in = {frozenset(k.split(",")): (e[b], tuple(k.split(","))) for k, e in rv.items() if e.get(b) is not None}
    pv, chosen = R9.pack_vals(pack_in) if len(pack_in) >= 5 else (None, [])
    out = {"top_five": dict(decks(rk["top_five"]["squads"]), count=rk["top_five"]["count"]),
           "rank1": dict(decks(rk["rank1"]["squads"]), server=rk["rank1"].get("server"),
                         real=(rk["rank1"].get("damage") or 0) / E8 or None),
           "pack": dict(decks([list(q) for _, q in chosen]), total=pv) if chosen else None}
    our_sets = [set(q) for q in ours]
    sq = []
    for q in rk["squads"]:
        e = rv.get(",".join(q["order"]), {})
        sq.append({"order": q["order"], "count": q["count"], "value": e.get(b), "leader": leader(e.get(f"{b}_members")),
                   "members": e.get(f"{b}_members"),
                   "overlap": max((len(set(q["members"]) & o) for o in our_sets), default=0)})
    out["squads"] = sq
    return out


def boss_run(s: int, b: str, m: dict[str, Any] | None, rv: dict[str, dict]) -> dict[str, Any]:
    name = R22.run_name(s, b)
    pre = read_json(A22.LOG / f"precompute_{name}.json")
    if pre is None or m is None:              # 우리 결과 전이어도 랭커 덱 시뮬 값은 보여 준다
        return {"status": "pending", "name": name, "rankers": ranker_side(s, b, [], rv)}
    idx = deck_index(name)
    mem = read_json(A22.LOG / f"members_{name}.json")
    rk = R22.season(s)["rankers"]
    rsq = [(set(q["members"]), q) for q in rk["squads"]]
    decks = []
    for i, (val, q) in enumerate(pre["final"]["squads"]):
        members = None
        if mem and i < len(mem["squads"]) and mem["squads"][i]["squad"] == list(q):
            members = mem["squads"][i]["members"]
        elif rv.get(",".join(q), {}).get(f"{b}_members"):          # 랭커 덱 평가에 같은 순서가 있으면 그 값
            members = rv[",".join(q)][f"{b}_members"]
        near = max(rsq, key=lambda t: (len(set(q) & t[0]), t[1]["count"]), default=None)
        decks.append({"order": list(q), "value": val, "members": members, "leader": leader(members),
                      "match": len(set(q) & near[0]) if near else 0,
                      "near": {"order": near[1]["order"], "count": near[1]["count"]} if near else None})
    hist = pre.get("history", [])
    out = {k: m.get(k) for k in ("total", "evals", "sims", "seconds", "N25", "D4", "V_top", "V_r1", "V_pack",
                                 "ours_only", "rankers_only", "main_ours", "main_rankers", "main_overlap")}
    coef = pre.get("coef") or {}
    ours25 = {n for q in pre["final"]["squads"] for n in q[1]}
    top25 = set(n for n, _ in rk["units"][:25])
    out.update({
        "status": "done", "name": name, "budget": pre.get("budget"), "options": pre.get("options"),
        "evaluator": pre.get("evaluator"), "decks": decks, "alts": alternatives(pre, idx),
        "history": [[h["evals"], h["pack"]] for h in hist],
        "kicks": [[k["evals"], k["best"], bool(k.get("improved"))] for k in pre.get("kicks", [])],
        "reach": reach(hist, pre["final"]["total"]), "phases": phase_counts(name),
        "coef_top": [[n, v, n in ours25, n in top25] for n, v in sorted(coef.items(), key=lambda t: (-t[1], t[0]))[:COEF_TOP]],
        "members_ready": mem is not None,
        "rankers": ranker_side(s, b, [list(q) for _, q in pre["final"]["squads"]], rv),
    })
    return out


# ---------------------------------------------------------------- 시즌 · 전체

def season_block(s: int, prev_pool: set[str] | None) -> dict[str, Any]:
    v = R22.season(s)
    m = A22.season_metrics(s)
    rk = v["rankers"]
    rv = (read_json(A22.LOG / f"rankers_S{s:02d}.json") or {}).get("squads", {})
    pool = sorted(v["pool"])
    return {
        "season": s, "boss_name": v["boss"], "code": v["code"], "element": v["element"], "weak": v["weak"],
        "weak_ko": WEAK_KO.get(v["weak"], v["weak"]), "start": v["start"], "end": v["end"],
        "pool": pool, "pool_size": len(pool), "favorite0": v["favorite0"],
        "new_since_prev": None if prev_pool is None else sorted(set(pool) - prev_pool),
        "rankers": {"players": rk["players"], "decks": rk["decks"], "unsupported_share": rk.get("unsupported_share"),
                    "unsupported": rk.get("unsupported"), "units": rk["units"][:40], "top25": m["top25"],
                    "distinct_squads": rk.get("distinct_squads")},
        "baseline": {"N25_prev": m["N25_prev"], "N25_same": m["N25_same"], "prev_season": v["baseline"]["prev"]["season"],
                     "same_season": m.get("same_season")},
        "better": m.get("better"), "tie": m.get("tie"),
        "by_boss": {b: boss_run(s, b, m["by_boss"].get(b), rv) for b in R22.BOSSES},
    }


def runs_meta() -> dict[str, dict[str, Any]]:
    """작업 세션 meta_*.json: 실행마다 어느 세션이 언제 돌렸는지."""
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(A22.LOG.glob("meta_*.json")):
        meta = read_json(p) or {}
        for name, r in (meta.get("runs") or {}).items():
            out[name] = {"session": meta.get("session"), "start_utc": r.get("start_utc"), "end_utc": r.get("end_utc")}
    return out


def base_name(n: str) -> str:
    """랭커 덱의 평가기 밖 니케는 `!이름`(로스터에 있음) · `?영문`(못 찾음)으로 적혀 있다 — 앞 표시를 뗀다."""
    return n[1:] if n[:1] in "!?" else n


def icon_index() -> dict[str, Any]:
    return read_json(ICONS / "icons.json") or {"units": {}, "bosses": {}}


def site_names(seasons: list[dict[str, Any]]) -> set[str]:
    """화면에 니케로 나오는 이름 전부(풀 · 덱 · 랭커 스쿼드 · 사용 순위 · 대리 모델 표)."""
    lists = ("order", "pool", "favorite0", "new_since_prev", "ours_only", "rankers_only", "top25", "main_ours")
    pairs = ("units", "main_rankers", "coef_top", "members")      # [이름, 값, …] 목록
    out: set[str] = set()

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k in lists and isinstance(v, list):
                    out.update(x for x in v if isinstance(x, str))
                elif k in pairs and isinstance(v, list):
                    out.update(x[0] for x in v if isinstance(x, list) and x and isinstance(x[0], str))
                elif k == "leader" and isinstance(v, str):
                    out.add(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(seasons)
    return out


def nikke_table(names: set[str], icons: dict[str, Any]) -> dict[str, Any]:
    """이름 → 무기 · 버스트 · 기본 레이어(평가기 nikke_info) + 얼굴 번호 · 속성(nikke-analysis 로스터)."""
    info = (read_json(NIKKE_INFO) or {}).get("nikke", {})
    units = icons.get("units", {})
    out: dict[str, Any] = {}
    for n in sorted(names):
        i, u = info.get(n), units.get(base_name(n))
        if not i and not u:
            continue
        e: dict[str, Any] = {}
        if i:
            e.update({"w": i["weapon"], "b": i["burst_stage"], "layer": i.get("layer") or {}, "pat": i.get("burst_patterns") or []})
        if u:
            e.update({"img": f"icons/units/{u['id']}.webp", "el": u.get("el") or []})
            e.setdefault("b", BURST_STAGE.get(u.get("b") or ""))
        out[n] = e
    return out


def boss_image(s: int, icons: dict[str, Any]) -> str | None:
    img = icons.get("bosses", {}).get(str(s))
    return f"icons/bosses/{img}.webp" if img and (ICONS / "bosses" / f"{img}.webp").exists() else None


def build_data() -> dict[str, Any]:
    seasons, prev = [], None
    for s in sorted(int(k) for k in R22.SEASON_DATA):
        blk = season_block(s, prev)
        prev = set(blk["pool"])
        seasons.append(blk)
    rows = [A22.season_metrics(x["season"]) for x in seasons]
    j = A22.judge(rows)
    icons = icon_index()
    for x in seasons:
        x["boss_img"] = boss_image(x["season"], icons)
    names = site_names(seasons)
    nikke = nikke_table(names, icons)
    runs = [(x["season"], b, x["by_boss"][b]) for x in seasons for b in R22.BOSSES]
    done = [r for _, _, r in runs if r["status"] == "done"]
    return {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": provenance(), "repo": REPO_URL,
        "experiment": {"id": 22, "title": "랭커 대조: 시즌 풀 · 코어 유무에서 우리 예상과 랭커 5덱",
                       "readme": f"{REPO_URL}/blob/main/experiments/22_ranker_check/README.md",
                       "ranker_repo": "https://github.com/Jgaram/nikke-analysis"},
        "criteria": {"N25_MIN": A22.N25_MIN, "V_MIN": A22.V_MIN},
        "judge": {**j, "better_count": dict(j["better_count"])},
        "progress": {"done": len(done), "total": len(runs), "sims": sum(r["sims"] for r in done),
                     "seconds": sum(r["seconds"] for r in done)},
        "bosses": BOSS_INFO, "runs_meta": runs_meta(), "seasons": seasons, "nikke": nikke,
        "icons": {"source": icons.get("source") or {},
                  "missing": sorted(n for n in names if not nikke.get(n, {}).get("img"))},
    }


def build(out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    data = build_data()
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
    a = p.parse_args(argv)
    d = build(a.out)
    pr = d["progress"]
    print(f"{a.out}: 사전 계산 {pr['done']}/{pr['total']} · 판단 {d['judge']['verdict']} · data.json "
          f"{(a.out / 'data.json').stat().st_size / 1024:.0f} KB")
    if d["icons"]["missing"]:
        print(f"얼굴 그림 없는 니케 {len(d['icons']['missing'])}명: {', '.join(d['icons']['missing'])} "
              "— python web/sync_icons.py --analysis <nikke-analysis 경로>", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
