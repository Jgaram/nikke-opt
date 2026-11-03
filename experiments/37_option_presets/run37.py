"""실험 37 — 니케별 장비 옵션 프리셋(혼자 + 가짜 버스트 환경)으로 후처리의 옵션 탐색을 없앨 수 있나(README §R0 사전 등록).

    python -I experiments/37_option_presets/run37.py facts --calc-dir ../nikke-calc-rs        # → facts.json(니케 속성 · 버스트 · 버쿨감 · 풀버 시간)
    source .cache/evaluators.env && python -I experiments/37_option_presets/run37.py presets  # → presets.json(니케 × 상성 있음/없음)
    source .cache/evaluators.env && python -I experiments/37_option_presets/run37.py check    # 실험 36 후처리 덱 45개: 재현 · 프리셋 바꿔 끼우기(V1)
    source .cache/evaluators.env && python -I experiments/37_option_presets/run37.py post     # 간소화 후처리(V2): 프리셋 위에서 컨트롤 + 큐브만 400
    python -I experiments/37_option_presets/run37.py analyze                                 # → r0.json · r0.md

프리셋 환경(사용자 설계, 2026-11-03): 타깃 니케 하나 + 스킬 없는 가짜 버스트 니케(nikke-calc-rs `test_F*`, 쿨 20초).
  - 타깃 단계가 아닌 단계는 가짜가 맡는다. 재진입(버스트 단계 A · `burst_reentry` 스킬)은 가짜 1 · 2 · 3버 모두.
  - 타깃 쿨 40초 = 짝수 · 홀수 사이클 둘 다, 60초 = 세 위상 모두 해 보고 고른다(같은 단계 가짜가 나머지 사이클).
  - 가짜 버쿨감 = 풀버스트 시작마다 아군 전체 7.5초. 타깃이 버쿨감 스킬을 가지면 넣지 않고,
    타깃이 풀버스트 시간을 Δ초 바꾸면 7.5 − Δ(−5초 → 12.5, +5초 → 2.5).
  - 값 = 타깃 본인 딜. 상성 있음(보스 코드 = 타깃이 이기는 코드) · 없음(보스 코드 = 타깃 코드) 두 벌.
  - 탐색: E0(우코 · 공 · 장탄 4) → 9종 4줄 덩어리 거르기(10시뮬) → 상위 5종 위 배분 전부(320).
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXP36 = HERE.parent / "36_season_refresh"
EXP35 = HERE.parent / "35_equip_options"
sys.path[:0] = [str(EXP36), str(EXP35)]
import run35  # noqa: E402
from run35 import E8  # noqa: E402


def r36() -> Any:
    """실험 36 모듈 — 불러오면 실험 31 모듈의 경로 · 판을 바꿔 끼우므로 쓸 때만 불러온다."""
    import run36
    return run36

FACTS = HERE / "facts.json"
PRESETS = HERE / "presets.json"
OUT = HERE / "r0"
KEYS9, E0 = run35.KEYS9, run35.E0
TOP_T = 5
CYCLES = 40
BASE_CDR = 7.5
CARRIERS = {7.5: "75", 12.5: "125", 2.5: "25"}
BEATS = {"전격": "수냉", "수냉": "작열", "작열": "풍압", "풍압": "철갑", "철갑": "전격"}
CDR_STATS = ("burst_cooldown_reduce", "burst_cooldown")


def jload(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def jdump(p: Path, x: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(x, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 니케 속성(계산기 데이터에서 한 번 뽑아 둔다)

def cmd_facts(a: argparse.Namespace) -> int:
    d = Path(a.calc_dir) / "upstream" / "data"
    nk = json.loads((d / "parsed_nikke.json").read_text(encoding="utf-8"))
    sk = json.loads((d / "parsed_skills.json").read_text(encoding="utf-8"))

    def effects(x: Any):
        if isinstance(x, dict):
            yield x
            for v in x.values():
                yield from effects(v)
        elif isinstance(x, list):
            for v in x:
                yield from effects(v)

    out = {}
    for n, v in nk.items():
        if n.startswith("test_") or v.get("rarity") != "SSR":
            continue
        effs = list(effects(sk.get(n, [])))
        fb = sum(float(e.get("fixed_value") or 0) for e in effs if e.get("stat") == "fullburst_duration")
        out[n] = {"code": v["element_code"], "stage": str(v.get("burst_stage") or ""), "cd": float(v.get("burst_cooldown") or 40.0),
                  "own_cdr": any(e.get("stat") in CDR_STATS for e in effs),
                  "reentry": str(v.get("burst_stage")) == "A" or any(e.get("stat") == "burst_reentry" for e in effs),
                  "fb_delta": round(fb, 2)}
    jdump(FACTS, {"_source": f"nikke-calc-rs upstream/data (원본 67835ca)", "nikke": out})
    print(f"{len(out)}명 → {FACTS}")
    return 0


def facts() -> dict[str, Any]:
    return jload(FACTS)["nikke"]


# ---------------------------------------------------------------- 프리셋 환경

def fake_cdr(f: Mapping[str, Any]) -> float:
    if f["own_cdr"]:
        return 0.0
    v = BASE_CDR - f["fb_delta"]
    return min(CARRIERS, key=lambda c: abs(c - v))


def envs(name: str) -> list[dict[str, Any]]:
    """타깃 하나의 환경 목록(버스트 위상마다 하나). squad · 타깃 패턴 · 같은 단계 가짜 패턴."""
    f = facts()[name]
    cdr = fake_cdr(f)
    if f["reentry"] or f["stage"] not in ("1", "2", "3"):
        stages, s = ["1", "2", "3"], None
    else:
        s = f["stage"]
        stages = [x for x in "123" if x != s]
    fakes = {x: f"test_F{x}" for x in stages}
    if cdr:
        c = "1" if "1" in fakes else "2"
        fakes[c] = f"test_F{c}_cdr{CARRIERS[cdr]}"
    base = [name] + [fakes[x] for x in sorted(fakes)]
    if s is None or f["cd"] <= 20:
        return [{"phase": "auto", "squad": base, "chars": {}, "cdr": cdr}]
    k = int(round(f["cd"] / 20))
    partner = f"test_F{s}b"
    out = []
    for j in range(k):
        mine = [c for c in range(1, CYCLES + 1) if c % k == (j + 1) % k]
        rest = [c for c in range(1, CYCLES + 1) if c % k != (j + 1) % k]
        out.append({"phase": f"{j + 1}/{k}", "squad": base + [partner], "cdr": cdr,
                    "chars": {name: {"control": {"burst": {"pattern": mine}}},
                              partner: {"control": {"burst": {"pattern": rest}}}}})
    return out


def env_options(name: str, env: Mapping[str, Any], adv: bool, alloc: Mapping[str, int]) -> dict[str, Any]:
    code = facts()[name]["code"]
    o: dict[str, Any] = {"enemy": {"code": BEATS[code] if adv else code}}
    if env["chars"]:
        o["chars"] = json.loads(json.dumps(env["chars"]))
    return run35.with_alloc(o, {name: alloc})


def own(r: Any, name: str) -> float | None:
    if r.error or r.total_damage is None:
        return None
    for m in r.raw.get("members", []):
        if m["name"] == name:
            return m["damage"] / E8
    return None


def cmd_presets(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    names = sorted(facts()) if not a.only else a.only.split(",")
    got = jload(PRESETS) or {"presets": {}, "runs": {}}
    todo = [(n, adv) for n in names for adv in (True, False) if f"{n}|{int(adv)}" not in got["presets"]]
    print(f"{len(todo)}개 (니케 × 상성) 남음")
    t0 = time.time()
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        got["evaluator"] = f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"
        for i in range(0, len(todo), a.chunk):
            chunk = todo[i:i + a.chunk]
            n0 = ev.sim_count
            # ① 거르기: 환경마다 E0 + 9종 뒤집기
            jobs = [(n, adv, e) for n, adv in chunk for e in envs(n)]
            flips = [dict(E0)] + [({kk: v for kk, v in E0.items() if kk != k} if E0.get(k) else {**E0, k: 4}) for k in KEYS9]
            reqs = [EvalRequest(e["squad"], boss=None, options=env_options(n, e, adv, al)) for n, adv, e in jobs for al in flips]
            res = ev.evaluate(reqs)
            tops = []
            for j, (n, adv, e) in enumerate(jobs):
                v = [own(r, n) for r in res[j * 10:(j + 1) * 10]]
                if v[0] is None:
                    raise RuntimeError(f"{n} {e['phase']}: {res[j * 10].error}")
                bund = {k: (None if x is None else (v[0] - x if E0.get(k) else x - v[0])) for k, x in zip(KEYS9, v[1:])}
                tt = sorted(KEYS9, key=lambda k: (-(bund[k] if bund[k] is not None else -1e9), KEYS9.index(k)))[:TOP_T]
                tops.append((n, adv, e, v[0], bund, tt, run35.allocs(tt)))
            # ② 상위 5종 위 배분 전부
            reqs = [EvalRequest(e["squad"], boss=None, options=env_options(n, e, adv, al)) for n, adv, e, _, _, _, als in tops for al in als]
            res = iter(ev.evaluate(reqs))
            per: dict[tuple, list] = {}
            for n, adv, e, v0, bund, tt, als in tops:
                vals = [own(next(res), n) for _ in als]
                bi = max(range(len(als)), key=lambda i: -1e18 if vals[i] is None else vals[i])
                per.setdefault((n, adv), []).append({"phase": e["phase"], "squad": e["squad"], "cdr": e["cdr"], "E0": v0,
                                                     "bundle": bund, "top": tt, "best": vals[bi], "alloc": run35.label(als[bi]),
                                                     "errors": sum(x is None for x in vals)})
            for (n, adv), rows in per.items():
                b = max(rows, key=lambda r: r["best"])
                got["presets"][f"{n}|{int(adv)}"] = b["alloc"]
                got["runs"][f"{n}|{int(adv)}"] = rows
            got["sims"] = got.get("sims", 0) + ev.sim_count - n0
            got["seconds"] = round(got.get("seconds", 0) + time.time() - t0, 1)
            t0 = time.time()
            jdump(PRESETS, got)
            print(f"  {min(i + a.chunk, len(todo))}/{len(todo)} · 시뮬 {got['sims']} · {got['seconds']}초", flush=True)
    return 0


def preset_for(name: str, season: int) -> dict[str, int]:
    p = jload(PRESETS)["presets"]
    code = r36().run31.season(season)["code"]
    adv = BEATS[facts()[name]["code"]] == code
    return run35.parse(p[f"{name}|{int(adv)}"])


# ---------------------------------------------------------------- 실험 36 후처리 덱과 비교

def exp36_decks() -> list[dict[str, Any]]:
    out = []
    for f in sorted((EXP36 / "run_log").glob("S*/post/S*-[0-9].json")):
        out.append(jload(f))
    return out


def final_options(d: Mapping[str, Any], per: Mapping[str, Mapping[str, int]]) -> dict[str, Any]:
    sp = r36().control_space(d["season"], d["squad"], per)
    return sp.options(sp.from_labels(d["final_variants"]))


def cmd_check(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    decks = exp36_decks()
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        reqs = []
        for d in decks:
            al = {n: run35.parse(lb) for n, lb in d["alloc"].items()}
            pre = {n: preset_for(n, d["season"]) for n in d["squad"]}
            reqs += [EvalRequest(d["squad"], boss=None, options=final_options(d, al)),
                     EvalRequest(d["squad"], boss=None, options=final_options(d, pre))]
        res = ev.evaluate(reqs)
        rows = []
        for i, d in enumerate(decks):
            r_re, r_v1 = res[2 * i], res[2 * i + 1]
            rows.append({"id": d["id"], "season": d["season"], "final": d["final"],
                         "reproduced": None if r_re.error else r_re.total_damage / E8,
                         "V1": None if r_v1.error else r_v1.total_damage / E8,
                         "preset": {n: run35.label(preset_for(n, d["season"])) for n in d["squad"]}, "alloc": d["alloc"]})
        jdump(OUT / "check.json", {"evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}",
                                   "sims": ev.sim_count, "rows": rows})
    bad = [r for r in rows if r["reproduced"] is None or abs(r["reproduced"] - r["final"]) > 1e-6]
    loss = [1 - r["V1"] / r["final"] for r in rows if r["V1"]]
    print(f"재현 불일치 {len(bad)}/{len(rows)} · V1 손해 중앙 {st.median(loss):.2%} · 최대 {max(loss):.2%}")
    return 0


def post_one(d: Mapping[str, Any], ev: Any) -> dict[str, Any]:
    f = OUT / "post" / f"{d['id']}.json"
    if f.exists():
        return jload(f)
    pre = {n: preset_for(n, d["season"]) for n in d["squad"]}
    sp = r36().control_space(d["season"], d["squad"], pre)
    n0, t0 = ev.sim_count, time.time()
    run = r36()._run(d["id"], d["squad"], sp, sp.empty(), ev, OUT / "post", "P")
    rec = {"id": d["id"], "season": d["season"], "squad": d["squad"], "final36": d["final"], "V2": run.best / E8,
           "variants": list(sp.labels(run.best_sel)), "sims": ev.sim_count - n0, "seconds": round(time.time() - t0, 1)}
    jdump(f, rec)
    return rec


def cmd_post(a: argparse.Namespace) -> int:
    from concurrent.futures import ThreadPoolExecutor
    from nikke_opt.evaluator import make_evaluator
    decks = exp36_decks()
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        with ThreadPoolExecutor(a.workers) as pool:
            for r in pool.map(lambda d: post_one(d, ev), decks):
                print(f"  {r['id']}: V2 {r['V2']:.2f} / 실험 36 {r['final36']:.2f} ({r['V2'] / r['final36'] - 1:+.2%})", flush=True)
    return 0


# ---------------------------------------------------------------- 정리

def cmd_analyze(a: argparse.Namespace) -> int:
    chk = jload(OUT / "check.json")
    posts = [jload(f) for f in sorted((OUT / "post").glob("S*-[0-9].json"))]
    v2 = {p["id"]: p for p in posts}
    seasons = sorted({r["season"] for r in chk["rows"]})
    tab = []
    for s in seasons:
        rs = [r for r in chk["rows"] if r["season"] == s]
        f36 = sum(r["final"] for r in rs)
        v1 = sum(r["V1"] for r in rs)
        v2s = sum(v2[r["id"]]["V2"] for r in rs) if all(r["id"] in v2 for r in rs) else None
        tab.append({"season": s, "final36": f36, "V1": v1, "V2": v2s, "loss_V1": 1 - v1 / f36,
                    "loss_V2": None if v2s is None else 1 - v2s / f36})
    deck_v1 = [1 - r["V1"] / r["final"] for r in chk["rows"]]
    deck_v2 = [1 - v2[r["id"]]["V2"] / r["final"] for r in chk["rows"] if r["id"] in v2]
    pr = jload(PRESETS)
    out = {"presets_sims": pr.get("sims"), "presets_seconds": pr.get("seconds"), "check_sims": chk["sims"],
           "post_sims": sum(p["sims"] for p in posts), "seasons": tab,
           "deck_loss_V1": deck_v1, "deck_loss_V2": deck_v2}
    jdump(HERE / "r0.json", out)

    def q(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))]
    lines = ["| 시즌 | 실험 36 후처리 5덱 합 | V1 프리셋 바꿔 끼우기 | V2 간소화 후처리 | 손해 V1 | 손해 V2 |", "|---|---|---|---|---|---|"]
    for t in tab:
        v2c = "" if t["V2"] is None else f"{t['V2']:.2f}"
        l2c = "" if t["loss_V2"] is None else f"{t['loss_V2']:+.2%}"
        lines.append(f"| S{t['season']} | {t['final36']:.2f} | {t['V1']:.2f} | {v2c} | {t['loss_V1']:+.2%} | {l2c} |")
    for nm, xs in (("V1", deck_v1), ("V2", deck_v2)):
        if xs:
            lines.append(f"\n덱별 손해 {nm}: 중앙 {st.median(xs):+.2%} · 75% {q(xs, .75):+.2%} · 90% {q(xs, .9):+.2%} · 최대 {max(xs):+.2%} · "
                         f"1% 넘는 덱 {sum(x > 0.01 for x in xs)}/{len(xs)}")
    (HERE / "r0.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("facts")
    p.add_argument("--calc-dir", required=True)
    p = sub.add_parser("presets")
    p.add_argument("--only")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--chunk", type=int, default=40)
    p = sub.add_parser("check")
    p.add_argument("--jobs", type=int, default=4)
    p = sub.add_parser("post")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--workers", type=int, default=2)
    sub.add_parser("analyze")
    a = ap.parse_args()
    return {"facts": cmd_facts, "presets": cmd_presets, "check": cmd_check, "post": cmd_post, "analyze": cmd_analyze}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
