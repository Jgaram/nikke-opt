"""실험 13 — 시드 기록 합치기 실행기 (README §후보).

    python experiments/13_seed_merge/run13.py merge --out <dir>
        → precompute_U4.json · precompute_U2w.json(계정 검증 판) · merges.json(관찰: U2 6쌍 · U3 4셋 · E2 · E3)
    source .cache/evaluators.env && python experiments/13_seed_merge/run13.py search --set val --out <dir> --pre <dir>
        --methods U4,U2w [--budgets 800,2000] [--only v1,v2] [--workers 4]
    python experiments/13_seed_merge/run13.py collect --runs <dir> --out <dir> --name val

- 기록 출처: s0 = 실험 11 `precompute_PB15.jsonl.gz`, s1~s3 = 실험 12 `precompute_PB15s<k>.jsonl.gz`. 새 사전 계산은 없다.
- 합친 판은 실험 11 `extract`(8벌 · 계수) 그대로, 계정 탐색은 실험 12 `cmd_search`(= 실험 11 `run_account`) 그대로다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

HERE = Path(__file__).resolve().parent
EXP11_LOG = HERE.parent / "11_wide_precompute" / "run_log"
EXP12 = HERE.parent / "12_precompute_seeds"
EXP12_LOG = EXP12 / "run_log"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R12 = sys.modules.get("run12") or _load("run12", EXP12 / "run12.py")
R11, R10, R9, S4 = R12.R11, R12.R10, R12.R9, R12.S4

SEEDS = (0, 1, 2, 3)
VALIDATE = ("U4", "U2w")
BUDGETS = (800, 2000)
TARGET = 195.0


def seed_method(k: int) -> str:
    """시드 → 그 시드 하나짜리 사전 계산의 기호(계정 실행 기록의 method)."""
    return "PB15" if k == 0 else f"PB15s{k}"


def src_paths(k: int) -> tuple[Path, Path]:
    d = EXP11_LOG if k == 0 else EXP12_LOG
    m = seed_method(k)
    return d / f"precompute_{m}.json", d / f"precompute_{m}.jsonl.gz"


def load_sources(seeds: Sequence[int] = SEEDS) -> dict[int, tuple[dict[str, Any], list[dict[str, Any]]]]:
    out = {}
    for k in seeds:
        pj, pr = src_paths(k)
        out[k] = (json.loads(pj.read_text(encoding="utf-8")), R11.load_records(pr))
    return out


def combo_name(kind: str, seeds: Sequence[int]) -> str:
    return f"{kind}-" + "".join(f"s{k}" for k in seeds)


def merged_book(srcs: Mapping[int, tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]], seeds: Sequence[int],
                part: int = 1) -> tuple[Any, dict[frozenset, list[int]], dict[int, int]]:
    """고른 시드들 기록(각 앞 1/part)의 합. → (Book, 구성 → 든 시드들, 시드 → 쓴 평가 수)."""
    book = S4.Book()
    where: dict[frozenset, list[int]] = {}
    used: dict[int, int] = {}
    for k in seeds:
        recs = srcs[k][1]
        n = len(recs) // part
        used[k] = n
        for r in recs[:n]:
            if r.get("total_damage") is None:
                continue
            sq = tuple(r["squad"])
            book.add(sq, r["total_damage"] / R10.E8)
            lst = where.setdefault(frozenset(sq), [])
            if k not in lst:
                lst.append(k)
    return book, where, used


def merge(srcs: Mapping[int, tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]], seeds: Sequence[int],
          part: int = 1, full: bool = False, name: str | None = None) -> dict[str, Any]:
    """합친 판. full이면 8벌 · 계수까지(계정 검증용), 아니면 최선 5덱만(관찰용)."""
    kind = ("U" if part == 1 else "E") + str(len(seeds))
    book, where, used = merged_book(srcs, seeds, part)
    v = R9.pack_vals(book.best)
    final = R10.pack_dict(v)
    evals = sum(used.values())
    sims = round(sum(srcs[k][0]["sims"] * used[k] / max(srcs[k][0]["evals"], 1) for k in seeds))
    secs = round(sum(srcs[k][0]["seconds"] * used[k] / max(srcs[k][0]["evals"], 1) for k in seeds), 1)
    out: dict[str, Any] = {
        "name": name or combo_name(kind, seeds), "kind": kind, "seeds": list(seeds), "part": part, "pool": 177,
        "evals": evals, "sims": sims, "seconds": secs, "comps": len(book.best), "final": final,
        "core": R12.core_together(final), "ge195": final["total"] >= TARGET - 1e-9,
        "squad_seeds": [where[frozenset(sq)] for _, sq in v[1]],
        "single": {seed_method(k): srcs[k][0]["final"]["total"] for k in seeds},
        "pick": pick_best(srcs, seeds)}
    if full:
        acct = R12.pre_account(0)
        sess = type("Merged", (), {"book": book})()
        out.update(R11.extract(sess, acct, R11.fit_big))
        out["stages"] = [{"what": f"{seed_method(k)} 기록 앞 {used[k]}평가(재사용)", "evals": used[k],
                          "sims": round(srcs[k][0]["sims"] * used[k] / max(srcs[k][0]["evals"], 1))} for k in seeds]
    return out


def pick_best(srcs: Mapping[int, tuple[Mapping[str, Any], Any]], seeds: Sequence[int]) -> str:
    """고르기: 그 시드들 중 사전 계산 최종 값이 가장 높은 시드(동률이면 앞 시드)."""
    k = max(seeds, key=lambda s: (srcs[s][0]["final"]["total"], -s))
    return seed_method(k)


def worst_pair(obs: Sequence[Mapping[str, Any]]) -> list[int]:
    """U2 6쌍 중 합친 최선 5덱 값이 가장 낮은 쌍(동률이면 이름 순)."""
    pairs = [o for o in obs if o["kind"] == "U2"]
    return min(pairs, key=lambda o: (o["final"]["total"], o["name"]))["seeds"]


def observe(srcs: Mapping[int, Any], seeds: Sequence[int] = SEEDS) -> list[dict[str, Any]]:
    out = []
    for r, part in ((2, 1), (3, 1), (2, 2), (3, 3)):
        for c in combinations(seeds, r):
            out.append(merge(srcs, c, part))
    return out


def cmd_merge(args: argparse.Namespace) -> int:
    args.out.mkdir(parents=True, exist_ok=True)
    srcs = load_sources()
    obs = observe(srcs)
    for o in obs:
        print(json.dumps({k: o[k] for k in ("name", "evals", "comps", "core", "ge195")} | {"pack": round(o["final"]["total"], 2)},
                         ensure_ascii=False), flush=True)
    wp = worst_pair(obs)
    full = {"U4": merge(srcs, SEEDS, full=True, name="U4"), "U2w": merge(srcs, wp, full=True, name="U2w")}
    for nm, d in full.items():
        (args.out / f"precompute_{nm}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"pre": nm, "seeds": d["seeds"], "pick": d["pick"], "pack": round(d["final"]["total"], 2),
                          "core": d["core"], "sets": [round(t, 1) for t in d["set_totals"]]}, ensure_ascii=False), flush=True)
    (args.out / "merges.json").write_text(json.dumps(obs, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


def load_pre(method: str, pre_dir: Path) -> dict[str, Any] | None:
    if method in VALIDATE:
        return json.loads((pre_dir / f"precompute_{method}.json").read_text(encoding="utf-8"))
    raise ValueError(f"실험 13에서 새로 검증하는 판은 {VALIDATE}뿐이다: {method}")


def cmd_search(args: argparse.Namespace) -> int:
    R12.load_pre = load_pre
    return R12.cmd_search(args)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    m.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("search")
    s.add_argument("--set", choices=("dev", "val"), required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--pre", type=Path)
    s.add_argument("--methods", required=True)
    s.add_argument("--budgets", default=",".join(map(str, BUDGETS)))
    s.add_argument("--only")
    s.add_argument("--workers", type=int, default=4)
    c = sub.add_parser("collect")
    c.add_argument("--runs", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--name", required=True)
    args = ap.parse_args(argv)
    return {"merge": cmd_merge, "search": cmd_search, "collect": R10.cmd_collect}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
