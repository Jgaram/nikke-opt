"""실험 43 — 구조 규칙 없는 탐색(실험 42 판 R) + 카메라 다듬기를 검증 시즌 S23~S32에서 지금 절차(실험 39 base)와 비교. README.

    source .cache/evaluators.env && python -I experiments/43_rulefree_verify/run43.py run --part B_s0 --jobs 3   # B_s1은 다른 프로세스로 동시에
    source .cache/evaluators.env && python -I experiments/43_rulefree_verify/run43.py order                       # base · R 카메라 다듬기
    python -I experiments/43_rulefree_verify/run43.py analyze                                                     # 시뮬 0 → analysis.json · results.md

- 실행 · 다듬기는 실험 42 `run42.py`의 `run` · `order`를 그대로 쓴다. 기록 위치만 이 실험(`NIKKE43_LOG` 또는 `run_log/`)으로 바꾼다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXPS = HERE.parent
ROOT = EXPS.parent
sys.path.insert(0, str(ROOT))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R42 = sys.modules.get("run42") or _load("run42", EXPS / "42_bundle_search" / "run42.py")
LOG = Path(os.environ.get("NIKKE43_LOG") or HERE / "run_log")
R42.LOG = LOG                    # run42의 vdir · order 기록 경로가 이 실험을 가리키게
ARM = "R"
CAM_MIN = 0.001                  # 판단 3: 카메라 다듬기 채택 후보(시즌 중앙)
jload, jdump, med, pct = R42.jload, R42.jdump, R42.med, R42.pct


def r39() -> Any:
    return R42.r39()


def cmd_run(a: argparse.Namespace) -> int:
    seasons = ",".join(str(s) for s in r39().SEASONS) if a.season is None else a.season
    return R42.cmd_run(argparse.Namespace(arm=ARM, season=seasons, part=a.part, jobs=a.jobs))


def cmd_order(a: argparse.Namespace) -> int:
    return R42.cmd_order(argparse.Namespace(arm=f"base,{ARM}", jobs=a.jobs))


def season_row(s: int) -> dict[str, Any] | None:
    R39 = r39()
    book_of = R42.R41.R30.book_of
    recs = {arm: {k: R42.verify_recs(arm, s, k) for k in R39.SEEDS} for arm in ("base", ARM)}
    if any(not v for d in recs.values() for v in d.values()):
        return None
    summ = {arm: R39.summarize(s, book_of([r for k in R39.SEEDS for r in d[k]])) for arm, d in recs.items()}
    seed = {arm: {k: R39.summarize(s, book_of(d[k]))["pack"] for k in R39.SEEDS} for arm, d in recs.items()}
    order = {arm: jload(LOG / "order" / arm / f"S{s:02d}.json") for arm in ("base", ARM)}
    parts = [jload(R42.vdir(ARM, s) / f"part_B_s{k}.json") or {} for k in R39.SEEDS]
    b0, r0 = summ["base"]["pack"], summ[ARM]["pack"]
    row: dict[str, Any] = {
        "season": s, "pool": len(R42.run31.account(s, 0).names),
        "base_pre": b0, "R_pre": r0, "r_pre": r0 / b0 - 1,
        "seed": seed, "seed_r": {k: seed[ARM][k] / seed["base"][k] - 1 for k in R39.SEEDS},
        "G": {arm: v["G"] for arm, v in summ.items()}, "visit": {arm: v["visit"] for arm, v in summ.items()},
        "outside_rule_requests": sum(p.get("outside_rule_requests", 0) for p in parts),
        "final_outside_rule_seeds": [p.get("final_outside_rule") for p in parts],
        "evals": sum(p.get("evals", 0) for p in parts), "sims": sum(p.get("sims", 0) for p in parts),
        "wall": sum(p.get("wall", 0) for p in parts), "search_seconds": sum(p.get("seconds", 0) for p in parts),
        "evaluator": sorted({p.get("evaluator") for p in parts if p.get("evaluator")}),
    }
    if all(order.values()):
        ba, ra = order["base"]["after_camera"], order[ARM]["after_camera"]
        row.update(base_after=ba, R_after=ra, r_after=ra / ba - 1, package=ra / b0 - 1,
                   cam_gain={arm: o["gain"] for arm, o in order.items()},
                   cam_camera_part={arm: o["gain_camera"] for arm, o in order.items()},
                   order_sims={arm: o["sims"] for arm, o in order.items()},
                   R_final=order[ARM]["final"],
                   R_final_outside_rule=sum(not R42.P41.passes(sorted(q)) for _, q in order[ARM]["final"]))
    return row


def verdict_of(rs: Sequence[float], n: int) -> dict[str, Any]:
    R39 = r39()
    return {"median": med(rs), "drops": sum(x < R39.DROP for x in rs), "seasons": len(rs),
            "verdict": R39.verdict(rs) if len(rs) == n else f"진행 중 {len(rs)}/{n}"}


def analyze() -> dict[str, Any]:
    R39 = r39()
    rows = [r for s in R39.SEASONS if (r := season_row(s)) is not None]
    n = len(R39.SEASONS)
    out: dict[str, Any] = {"seasons": list(R39.SEASONS), "rows": rows, "judge": {}}
    after = [r["r_after"] for r in rows if "r_after" in r]
    if after:
        out["judge"]["1"] = verdict_of(after, n) | {"read": None}
        v = out["judge"]["1"]["verdict"]
        out["judge"]["1"]["read"] = {"좋음": "규칙 빼기 채택 후보", "비김": "규칙 빼기 채택 후보(손해 없음)", "나쁨": "규칙 유지"}.get(v, v)
    if rows:
        out["judge"]["2"] = verdict_of([r["r_pre"] for r in rows], n)
    cams = [r for r in rows if "cam_gain" in r]
    if cams:
        g = {arm: med([r["cam_gain"][arm] for r in cams]) for arm in ("base", ARM)}
        out["judge"]["3"] = {"gain_median": g, "adopt": len(cams) == n and all(x >= CAM_MIN for x in g.values())}
        out["package_median"] = med([r["package"] for r in cams])
    if rows:
        out["seed_r_median"] = med([x for r in rows for x in r["seed_r"].values()])
        out["seed_noise_base"] = med([abs(r["seed"]["base"][1] / r["seed"]["base"][0] - 1) for r in rows])
        out["seed_noise_R"] = med([abs(r["seed"][ARM][1] / r["seed"][ARM][0] - 1) for r in rows])
        out["G_median"] = {arm: med([r["G"][arm] for r in rows]) for arm in ("base", ARM)}
        out["visit_median"] = {arm: med([r["visit"][arm] for r in rows]) for arm in ("base", ARM)}
    return out


def write_md(an: Mapping[str, Any]) -> str:
    L = ["# 실험 43 결과 표", "", "`run43.py analyze`가 만든다. 값 = 두 시드 기록을 합쳐 묶은 코어 없음 최선 5덱 합(억, 사전 값). r = R ÷ base − 1.", "",
         "| 시즌 | 풀 | base 전 | R 전 | r 전 | base 다듬은 뒤 | R 다듬은 뒤 | **r 뒤** | 카메라 이득 base · R | 규칙 밖 덱(R 최종 5덱) | G base · R |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in an["rows"]:
        aft = "r_after" in r
        L.append(f"| S{r['season']} | {r['pool']} | {r['base_pre']:.1f} | {r['R_pre']:.1f} | {pct(r['r_pre'])} | "
                 + (f"{r['base_after']:.1f} | {r['R_after']:.1f} | **{pct(r['r_after'])}** | {pct(r['cam_gain']['base'])} · {pct(r['cam_gain'][ARM])} | {r['R_final_outside_rule']} | "
                    if aft else "— | — | — | — | — | ")
                 + f"{pct(r['G']['base'])} · {pct(r['G'][ARM])} |")
    L.append("")
    for k, v in an["judge"].items():
        L.append(f"- 판단 {k}: `{json.dumps(v, ensure_ascii=False)}`")
    for k in ("package_median", "seed_r_median", "seed_noise_base", "seed_noise_R"):
        if k in an:
            L.append(f"- {k}: {pct(an[k])}")
    return "\n".join(L) + "\n"


def cmd_analyze(a: argparse.Namespace) -> int:
    an = analyze()
    jdump(HERE / "analysis.json", an)
    md = write_md(an)
    (HERE / "results.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--season", default=None, help="쉼표로 여럿(기본 S23~S32 전부)")
    r.add_argument("--part", default="B_s0,B_s1")
    r.add_argument("--jobs", type=int, default=4)
    o = sub.add_parser("order")
    o.add_argument("--jobs", type=int, default=4)
    sub.add_parser("analyze")
    a = p.parse_args(argv)
    return {"run": cmd_run, "order": cmd_order, "analyze": cmd_analyze}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
