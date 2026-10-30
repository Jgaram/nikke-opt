"""실험 8 — 후보 목록 · 공동 탐색(J) · 장전컨 기본값 1차 순위(S2) 실행기 (README §기준 순위와 후처리).

    python experiments/08_control_postproc/run8.py candidates            # → candidates.json (평가기 불필요)
    source .cache/evaluators.env && python experiments/08_control_postproc/run8.py joint --out <dir> [--ids k001,k002] [--threads 8]
    source .cache/evaluators.env && python experiments/08_control_postproc/run8.py reload --runs <dir> --out <dir2>

- `joint`: 후보마다 실험 7 `methods.run_job(comp, "M3:k2", budget=200)` → `<dir>/<id>.jsonl`(실험 7 기법 기록 형식,
  step 0 = 기본 레이어)과 끝나면 `<id>.done`(요약). 이미 끝난 후보는 건너뛴다.
- `reload`: 계열(A · B)마다 다른 계열 후보의 J 최선에서 니케별 장전컨 최빈 선택을 배우고(`reload_defaults`),
  후보마다 기본 레이어 + 그 기본값을 1회 평가한다 → `<dir2>/reload_tables.json` · `<dir2>/reload_eval.jsonl`.
  기본값이 모두 「바꾸지 않음」인 후보는 기본 레이어 값(J 기록 step 0)을 그대로 쓴다(시뮬 없음, `reused: true`).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

HERE = Path(__file__).resolve().parent
EXP6 = HERE.parent / "06_control_menu"
EXP7 = HERE.parent / "07_control_search"
sys.path[:0] = [str(EXP7), str(EXP6), str(HERE.parent.parent)]
import methods as M  # noqa: E402
import select_comps as sc  # noqa: E402

CANDIDATES = HERE / "candidates.json"
METHOD = "M3:k2"
BUDGET = 200
NONE = "none"  # 「바꾸지 않음」


# ---------------------------------------------------------------- 후보

def fold_of(base: int) -> str:
    """랭커 구성 순번(덱 수 순) → 계열. 번갈아 나눈다."""
    return "A" if base % 2 == 0 else "B"


def build_candidates() -> list[dict[str, Any]]:
    out = []
    for c in sc.candidates():
        out.append({"id": c["id"], "squad": list(c["squad"]), "skeleton": c["skeleton"], "source": c["source"],
                    "base": c["base"], "fold": fold_of(c["base"]),
                    "kind": "ranker" if c["source"].startswith("ranker") else "swap"})
    return out


def load_candidates(path: Path = CANDIDATES) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 장전컨 기본값

def reload_choice(best_variants: Iterable[str], nikke: str) -> str:
    """J 최선 label 목록에서 그 니케의 장전컨 선택 이름(없으면 NONE)."""
    tag = f"{nikke}:reload:"
    for lb in best_variants:
        if lb.startswith(tag):
            return lb[len(tag):]
    return NONE


def reload_defaults(summaries: Sequence[Mapping[str, Any]], cands: Mapping[str, Mapping[str, Any]],
                    exclude_fold: str) -> dict[str, dict[str, Any]]:
    """`exclude_fold`가 아닌 후보들의 J 최선에서 니케 → {choice, count, n}. 최빈값, 동률은 NONE 먼저, 그다음 이름 순."""
    seen: dict[str, Counter] = defaultdict(Counter)
    for s in summaries:
        c = cands[s["comp_id"]]
        if c["fold"] == exclude_fold or s.get("best_damage") is None:
            continue
        for m in c["squad"]:
            seen[m][reload_choice(s["best_variants"], m)] += 1
    out = {}
    for m, cnt in sorted(seen.items()):
        top = max(cnt.values())
        tied = sorted(k for k, v in cnt.items() if v == top)
        pick = NONE if NONE in tied else tied[0]
        out[m] = {"choice": pick, "count": top, "n": sum(cnt.values())}
    return out


def default_labels(squad: Sequence[str], table: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return sorted(f"{m}:reload:{table[m]['choice']}" for m in squad
                  if m in table and table[m]["choice"] != NONE)


# ---------------------------------------------------------------- 실행

def read_done(d: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.done"))]


def cmd_joint(args: argparse.Namespace) -> int:
    cands = load_candidates(args.candidates)
    if args.ids != "all":
        want = set(args.ids.split(","))
        cands = [c for c in cands if c["id"] in want]
    args.out.mkdir(parents=True, exist_ok=True)
    todo = [c for c in cands if not (args.out / f"{c['id']}.done").exists()]
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    t0 = time.time()

    def work(c):
        comp = {"id": c["id"], "squad": c["squad"]}
        summ = M.run_job(comp, METHOD, ev, budget=args.budget, out=args.out / f"{c['id']}.jsonl")
        (args.out / f"{c['id']}.done").write_text(json.dumps(summ, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({**summ, "t": round(time.time() - t0), "sims": ev.sim_count}, ensure_ascii=False), flush=True)

    with ev:
        with ThreadPoolExecutor(max_workers=args.threads) as pool:
            for f in [pool.submit(work, c) for c in todo]:
                f.result()
    print(f"후보 {len(todo)}개 · 시뮬 {ev.sim_count}회 · 캐시 {ev.cache_hits}회 · {time.time() - t0:.0f}초 · "
          f"평가기 {ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}", file=sys.stderr)
    return 0


def first_damage(path: Path) -> int | None:
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["step"] == 0:
                return r["total_damage"]
    return None


def cmd_reload(args: argparse.Namespace) -> int:
    cands = {c["id"]: c for c in load_candidates(args.candidates)}
    summ = read_done(args.runs)
    missing = sorted(set(cands) - {s["comp_id"] for s in summ})
    if missing:
        print(f"J가 끝나지 않은 후보 {len(missing)}개: {missing[:5]}…", file=sys.stderr)
        return 1
    tables = {f: reload_defaults(summ, cands, exclude_fold=f) for f in ("A", "B")}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "reload_tables.json").write_text(json.dumps(tables, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    jobs, rows = [], []
    for cid, c in sorted(cands.items()):
        labels = default_labels(c["squad"], tables[c["fold"]])
        if not labels:
            rows.append({"comp_id": cid, "fold": c["fold"], "variants": [], "total_damage":
                         first_damage(args.runs / f"{cid}.jsonl"), "error": None, "reused": True})
            continue
        space = M.Space(c["squad"])
        sel = space.from_labels(labels)
        opts = space.options(sel) if sel is not None else None
        if opts is None:
            rows.append({"comp_id": cid, "fold": c["fold"], "variants": labels, "total_damage": None,
                         "error": {"message": "조립 불가 또는 선택지 없음"}, "reused": False})
            continue
        jobs.append((cid, c, labels, EvalRequest(tuple(c["squad"]), boss=None, options=opts)))
    t0 = time.time()
    with make_evaluator() as ev:
        res = ev.evaluate([j[3] for j in jobs])
        for (cid, c, labels, _), r in zip(jobs, res):
            rows.append({"comp_id": cid, "fold": c["fold"], "variants": labels,
                         "total_damage": None if r.error else r.total_damage, "error": r.error, "reused": False,
                         "cached": r.cached})
        sims = ev.sim_count
    rows.sort(key=lambda r: r["comp_id"])
    with open(args.out / "reload_eval.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"S2 평가 {len(jobs)}개 · 재사용 {len(rows) - len(jobs)}개 · 시뮬 {sims}회 · {time.time() - t0:.0f}초",
          file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--candidates", type=Path, default=CANDIDATES)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("candidates", help="후보 목록 → candidates.json")
    j = sub.add_parser("joint", help="후보마다 M3:k2 200평가")
    j.add_argument("--out", type=Path, required=True)
    j.add_argument("--ids", default="all")
    j.add_argument("--threads", type=int, default=8)
    j.add_argument("--budget", type=int, default=BUDGET)
    r = sub.add_parser("reload", help="장전컨 기본값 학습(교차 적합) · S2 평가")
    r.add_argument("--runs", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "candidates":
        cands = build_candidates()
        args.candidates.write_text(json.dumps(cands, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        n = Counter(c["fold"] for c in cands)
        print(f"후보 {len(cands)}개 · 계열 A {n['A']} · B {n['B']}", file=sys.stderr)
        return 0
    return cmd_joint(args) if args.cmd == "joint" else cmd_reload(args)


if __name__ == "__main__":
    sys.exit(main())
