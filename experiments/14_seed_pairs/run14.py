"""실험 14 — 시드 2개 합치기를 새 시드로 확인하는 실행기 (README §후보).

    source .cache/evaluators.env && python experiments/14_seed_pairs/run14.py precompute --which PB15s4 --out <dir>
        (실험 12 `PB15s<k>` 그대로, 쉼표로 여럿)
    python experiments/14_seed_pairs/run14.py merge --pre <dir> --out <dir>
        → precompute_U2a.json(s4·s5) · precompute_U2b.json(s6·s7) · precompute_U4n.json(s4~s7) · merges.json(관찰)
    source .cache/evaluators.env && python experiments/14_seed_pairs/run14.py search --set val --out <dir> --pre <dir>
        --methods U2a,U2b [--budgets 800,2000] [--only v1,v2] [--workers 2]
    python experiments/14_seed_pairs/run14.py collect --runs <dir> --out <dir> --name val
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

HERE = Path(__file__).resolve().parent
EXP13 = HERE.parent / "13_seed_merge"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


U13 = sys.modules.get("run13") or _load("run13", EXP13 / "run13.py")
R12, R11, R10 = U13.R12, U13.R11, U13.R10

SEEDS = (4, 5, 6, 7)
FULL = {"U2a": (4, 5), "U2b": (6, 7), "U4n": (4, 5, 6, 7)}   # 미리 정한 쌍 · 조건부 4개
BUDGETS = (800, 2000)


def load_sources(pre_dir: Path, seeds: Sequence[int] = SEEDS) -> dict[int, tuple[dict[str, Any], list[dict[str, Any]]]]:
    out = {}
    for k in seeds:
        m = U13.seed_method(k)
        out[k] = (json.loads((pre_dir / f"precompute_{m}.json").read_text(encoding="utf-8")),
                  R11.load_records(pre_dir / f"precompute_{m}.jsonl.gz"))
    return out


def cmd_precompute(args: argparse.Namespace) -> int:
    for nm in args.which.split(","):
        kind, seed, cut = R12.parse_name(nm)
        if kind != "PB15" or cut or seed not in SEEDS:
            raise ValueError(f"실험 14 사전 계산은 PB15s4~s7뿐이다: {nm}")
    return R12.cmd_precompute(args)


def cmd_merge(args: argparse.Namespace) -> int:
    args.out.mkdir(parents=True, exist_ok=True)
    srcs = load_sources(args.pre)
    obs = U13.observe(srcs, SEEDS)
    for o in obs:
        print(json.dumps({k: o[k] for k in ("name", "evals", "comps", "core", "ge195")} | {"pack": round(o["final"]["total"], 2)},
                         ensure_ascii=False), flush=True)
    for nm, seeds in FULL.items():
        d = U13.merge(srcs, seeds, full=True, name=nm)
        (args.out / f"precompute_{nm}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"pre": nm, "seeds": d["seeds"], "pick": d["pick"], "pack": round(d["final"]["total"], 2),
                          "core": d["core"], "sets": [round(t, 1) for t in d["set_totals"]]}, ensure_ascii=False), flush=True)
    (args.out / "merges.json").write_text(json.dumps(obs, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


def load_pre(method: str, pre_dir: Path) -> dict[str, Any] | None:
    if method in FULL:
        return json.loads((pre_dir / f"precompute_{method}.json").read_text(encoding="utf-8"))
    raise ValueError(f"실험 14에서 새로 검증하는 판은 {tuple(FULL)}뿐이다: {method}")


def cmd_search(args: argparse.Namespace) -> int:
    R12.load_pre = load_pre
    return R12.cmd_search(args)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("precompute")
    p.add_argument("--which", required=True)
    p.add_argument("--out", type=Path, required=True)
    m = sub.add_parser("merge")
    m.add_argument("--pre", type=Path, required=True)
    m.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("search")
    s.add_argument("--set", choices=("dev", "val"), required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--pre", type=Path)
    s.add_argument("--methods", required=True)
    s.add_argument("--budgets", default=",".join(map(str, BUDGETS)))
    s.add_argument("--only")
    s.add_argument("--workers", type=int, default=2)
    c = sub.add_parser("collect")
    c.add_argument("--runs", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--name", required=True)
    args = ap.parse_args(argv)
    return {"precompute": cmd_precompute, "merge": cmd_merge, "search": cmd_search, "collect": R10.cmd_collect}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
