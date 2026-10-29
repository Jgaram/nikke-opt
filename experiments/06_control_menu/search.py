"""실험 6 W4 — 탐색 실행기. (골격: 관리자. 구현: W4)

여섯 조건(common.CONDITIONS)을 조합마다 돌리고 실행 기록(common.Record)을 JSON Lines로 쓴다.
선택지는 `variants_fn`·`apply_fn`으로 받는다 — 기본은 menu.variants · menu.apply, 테스트는 가짜를 넣는다.

    source .cache/evaluators.env && python experiments/06_control_menu/search.py \
        --comps c01,c02 --conditions layer,search_from_layer --out <scratchpad>/run.jsonl

조건별 동작 (README §비교 조건과 탐색)
- `auto` · `layer` · `fixed_layer`: 출발 options로 한 번 평가한다. 출발점 이름은 `auto` · `layer` · `layer`.
- `search_from_layer` · `search_from_auto`: 그 출발점에서 좌표 하강(`_descend`).
- `reference`: 무작위 출발점 `reference_starts`개(이름 `random:<seed+i>`, 키마다 선택지 하나 또는 「바꾸지 않음」을
  고르게 뽑는다, 바탕은 layer)에서 좌표 하강한 뒤, 추가 반복으로 그때까지의 최선에서 키 `KICK_KEYS`개를
  무작위로 바꿔(킥) 다시 하강하기를 `reference_kicks`번 한다(이름 `kick:<seed+i>`).

좌표 하강
- 키 = `variants_fn(squad)`의 (니케, 축), 그 순서대로 돈다. 한 키에서는 그 키의 선택지 전부 + (현재 선택이 있으면)
  「바꾸지 않음」으로 되돌리기를 후보로 하고, 아직 평가하지 않은 후보를 `submit`으로 한 번에 넣는다.
- 후보 중 현재 값보다 엄격히 큰 최선으로 바꾼다. 동률은 현재를 유지하고, 후보끼리 동률이면 앞 순서가 이긴다.
- 연속으로 모든 키를 한 번씩(직전에 바꾼 키는 빼고) 돌 동안 개선이 없으면 끝난다 — 바꾼 키를 다시 보는 것은
  같은 후보 집합이라 결과가 같다.
- 같은 출발점 안에서 이미 평가한 선택 집합은 다시 보내지 않는다(기록도 한 번). 출발점이 다르면 다시 평가하고
  기록한다 — 시뮬은 평가기 캐시가 막는다.
- 평가 오류(`error`)인 선택 집합은 기록하고 후보에서 뺀다. 출발점이 오류면 오류 아닌 첫 후보가 개선이다.
- 조립할 수 없는 선택 집합(`apply_fn`이 `menu.MenuConflict`를 냄)은 시뮬 없이 후보에서 뺀다. 기록에 쓰지 않고
  예산·step에도 세지 않는다(요약의 `conflicts`에 개수만) — step이 실제 평가 순번으로 남고, 충돌 여부는
  menu로 언제든 다시 계산되므로 재개 때 재생할 것도 없다. 무작위·킥 출발점이 조립 불가면 같은 난수 흐름에서
  다시 뽑는다(`DRAW_TRIES`번 안에 못 찾으면 빈 선택 = layer).

예산 · 기록 · 재개
- `budget`은 (조합, 조건) 하나가 쓸 평가 수(기록 줄 수) 상한이다. 재개 때 재생한 줄도 센다 — 그래서 같은 예산이면
  끊겼다 이어도 같은 지점에서 끝난다. 남은 예산보다 후보가 많으면 앞에서부터 남은 만큼만 넣고 끝낸다.
  평가기의 시뮬 예산(`BudgetExceeded`)에 걸려도 그때까지의 최선으로 끝낸다.
- `step`은 (조합, 조건, 출발점) 안의 평가 순번(0 = 출발점)이다. 한 키의 후보는 후보 순서대로 번호를 받는다.
  수렴 곡선(README §잴 것 4)은 step 순으로 누적 최선을 보면 된다.
- 재개: `out`에 같은 (comp_id, condition, start)의 기록이 있으면, 같은 경로를 다시 밟으면서 기록에 있는 선택 집합은
  평가하지 않고 기록 값을 쓴다(줄을 다시 쓰지 않는다). 기록의 요청이 지금 만든 요청과 다르면 ValueError
  (선택지 정의가 바뀐 것 — 다른 `out`에 새로 돌린다).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent.parent)]
import common  # noqa: E402
from common import Composition, Variant  # noqa: E402
from menu import MenuConflict  # noqa: E402
from nikke_opt.evaluator import BudgetExceeded, EvalRequest  # noqa: E402

VariantsFn = Callable[[Sequence[str]], Mapping[tuple, list[Variant]]]
ApplyFn = Callable[[Mapping[str, Any], Sequence[Variant]], dict[str, Any]]

DRAW_TRIES = 100        # 무작위·킥 출발점이 조립 불가일 때 다시 뽑는 최대 횟수
KICK_KEYS = 2           # 킥 한 번에 무작위로 바꾸는 키 수
DEFAULT_REFERENCE_STARTS = 5
DEFAULT_REFERENCE_KICKS = 0
SINGLE = {  # 한 번 평가하는 조건 → (출발점 이름, options)
    "auto": ("auto", common.START_OPTIONS["auto"]),
    "layer": ("layer", common.START_OPTIONS["layer"]),
    "fixed_layer": ("layer", common.deep_merge(common.START_OPTIONS["layer"], common.FIXED_GAUGE)),
}
DESCENT = {"search_from_layer": "layer", "search_from_auto": "auto"}


class _Run:
    """(조합, 조건) 하나의 실행 상태 — 예산, 재생할 기록, 기록 쓰기."""

    def __init__(self, comp: Composition, condition: str, evaluator: Any, out: Path,
                 apply_fn: ApplyFn, budget: int | None):
        self.comp, self.condition, self.ev, self.out = comp, condition, evaluator, out
        self.apply_fn, self.budget = apply_fn, budget
        self.used = 0        # 이 (조합, 조건)에서 쓴 평가 수(재생 포함)
        self.new = 0         # 이번 호출에서 새로 평가한 수
        self.replayed = 0
        self.conflicts = 0   # 조립 불가로 건너뛴 선택 집합 수(기록·예산 밖)
        self.steps: dict[str, int] = {}  # 출발점 → 다음 step
        self.exhausted = False
        self.prior: dict[tuple[str, tuple[str, ...]], common.Record] = {}
        if out.exists():
            for rec in common.read_records([out]):
                if rec.get("comp_id") == comp["id"] and rec.get("condition") == condition:
                    self.prior[(rec["start"], tuple(rec["variants"]))] = rec

    def request(self, base: Mapping[str, Any], chosen: Sequence[Variant]) -> EvalRequest:
        opts = self.apply_fn(base, list(chosen)) if chosen else dict(base)
        return EvalRequest(tuple(self.comp["squad"]), boss=common.BOSS, options=opts)

    def conflict(self, base: Mapping[str, Any], chosen: Sequence[Variant]) -> str | None:
        """조립할 수 없는 선택 집합(menu.MenuConflict)이면 그 이유, 아니면 None."""
        try:
            self.request(base, chosen)
        except MenuConflict as e:
            return str(e) or type(e).__name__
        return None

    def evaluate(self, start: str, base: Mapping[str, Any], sets: list[list[Variant]]) -> list[common.Record | None]:
        """선택 집합들을 평가(또는 재생)해 `sets`와 같은 순서로 기록을 돌려준다. 조립 불가(MenuConflict)는 None —
        시뮬도 기록도 없고 예산에도 세지 않는다. 예산이 모자라면 앞에서부터 되는 만큼만 하고 `exhausted`를
        세운다(돌려준 목록은 `sets`보다 짧을 수 있다). 부른 쪽은 결과를 반영한 뒤 끝낸다."""
        left = None if self.budget is None else max(0, self.budget - self.used)
        reqs: list[EvalRequest | None] = []
        short = False
        for s in sets:
            try:
                req = self.request(base, s)
            except MenuConflict:
                self.conflicts += 1
                reqs.append(None)
                continue
            if left is not None and left == 0:
                short = True
                break
            reqs.append(req)
            if left is not None:
                left -= 1
        labels = [tuple(sorted(v["label"] for v in s)) for s in sets[:len(reqs)]]
        olds = [self.prior.get((start, lb)) if req is not None else None for req, lb in zip(reqs, labels)]
        for old, req in zip(olds, reqs):
            if old is not None and old["request"] != req.to_line():
                raise ValueError(f"{self.comp['id']} {self.condition} {start} {list(old['variants'])}: "
                                 "기록의 요청이 지금 요청과 다르다 — 선택지 정의가 바뀌었으면 다른 out에 돌린다")
        todo = [i for i, (req, old) in enumerate(zip(reqs, olds)) if req is not None and old is None]
        try:
            futs: dict[int, Future] = dict(zip(todo, self.ev.submit([reqs[i] for i in todo]))) if todo else {}
        except BudgetExceeded:
            self.exhausted = True
            return []
        recs: list[common.Record | None] = []
        for i, (req, lb, old) in enumerate(zip(reqs, labels, olds)):
            if req is None:
                recs.append(None)
                continue
            step = self.steps.get(start, 0)
            self.steps[start] = step + 1
            self.used += 1
            if old is not None:
                recs.append(old)
                self.replayed += 1
                continue
            res = futs[i].result()
            rec: common.Record = {
                "comp_id": self.comp["id"], "condition": self.condition, "start": start,
                "step": step, "variants": list(lb), "request": req.to_line(),
                "total_damage": None if res.error else res.total_damage,
                "control_detail": res.raw.get("control_detail"), "cached": res.cached,
                "error": res.error, "evaluator": self.ev.version, "sim_count": self.ev.sim_count,
            }
            common.append_record(self.out, rec)
            self.new += 1
            recs.append(rec)
        self.exhausted |= short
        return recs


def _better(a: int | None, b: int | None) -> bool:
    """a가 b보다 엄격히 좋은가. None(오류·미평가)은 무엇보다 나쁘다."""
    return a is not None and (b is None or a > b)


def _descend(run: _Run, start: str, base: Mapping[str, Any], menu: Mapping[tuple, list[Variant]],
             init: Mapping[tuple, Variant]) -> tuple[int | None, dict[tuple, Variant], dict]:
    """출발 선택 `init`에서 좌표 하강. (최선 딜, 최선 선택, 출발점 요약)을 돌려준다. 예산이 다하면 그때까지의 최선."""
    keys = list(menu)
    cur: dict[tuple, Variant] = dict(init)
    seen: dict[tuple[str, ...], int | None] = {}  # 이 출발점에서 평가한 선택 집합 → 딜(오류면 None)
    best: int | None = None
    passes = 0

    def chosen(sel: Mapping[tuple, Variant]) -> list[Variant]:
        return [sel[k] for k in keys if k in sel]

    def tag(sel: Mapping[tuple, Variant]) -> tuple[str, ...]:
        return tuple(sorted(v["label"] for v in sel.values()))

    def summary() -> dict:
        return {"start": start, "best_damage": best, "best_variants": list(tag(cur)),
                "evals": run.steps.get(start, 0), "passes": passes}

    recs = run.evaluate(start, base, [chosen(cur)])
    if not recs:
        return None, cur, summary()
    seen[tag(cur)] = best = recs[0] and recs[0]["total_damage"]
    idle, i = 0, 0  # idle: 직전 개선 뒤 개선 없이 지나간 키 수
    limit = len(keys)
    while keys and idle < limit and not run.exhausted:
        if i == 0:
            passes += 1
        k = keys[i]
        cands: list[dict[tuple, Variant]] = []
        for v in menu[k]:
            if cur.get(k) is None or cur[k]["label"] != v["label"]:
                cands.append({**cur, k: v})
        if k in cur:  # 「바꾸지 않음」으로 되돌리기
            cands.append({kk: vv for kk, vv in cur.items() if kk != k})
        fresh, uniq = [], set()
        for c in cands:
            t = tag(c)
            if t not in seen and t not in uniq:
                fresh.append(c)
                uniq.add(t)
        if fresh:
            for c, r in zip(fresh, run.evaluate(start, base, [chosen(c) for c in fresh])):
                seen[tag(c)] = r and r["total_damage"]  # 조립 불가(None)는 다시 시도하지 않는다
        pick = None
        for c in cands:  # 후보 순서대로 — 동률이면 앞이 이긴다
            if _better(seen.get(tag(c)), best if pick is None else seen[tag(pick)]):
                pick = c
        if pick is not None:
            cur, best = pick, seen[tag(pick)]
            idle, limit = 0, len(keys) - 1
        else:
            idle += 1
        i = (i + 1) % len(keys)
    return best, cur, summary()


def _random_selection(menu: Mapping[tuple, list[Variant]], rng: random.Random) -> dict[tuple, Variant]:
    sel = {}
    for k, vs in menu.items():
        j = rng.randrange(len(vs) + 1)  # len(vs) = 바꾸지 않음
        if j < len(vs):
            sel[k] = vs[j]
    return sel


def _kick(menu: Mapping[tuple, list[Variant]], sel: Mapping[tuple, Variant], rng: random.Random) -> dict[tuple, Variant]:
    """키 KICK_KEYS개를 지금과 다른 선택(또는 바꾸지 않음)으로 무작위로 바꾼다."""
    out = dict(sel)
    for k in rng.sample(list(menu), min(KICK_KEYS, len(menu))):
        opts: list[Variant | None] = [v for v in menu[k] if k not in sel or v["label"] != sel[k]["label"]]
        if k in sel:
            opts.append(None)
        pick = rng.choice(opts)
        if pick is None:
            out.pop(k, None)
        else:
            out[k] = pick
    return out


def _draw(run: _Run, base: Mapping[str, Any], menu: Mapping[tuple, list[Variant]],
          gen: Callable[[], dict[tuple, Variant]]) -> dict[tuple, Variant]:
    """조립할 수 있는 출발 선택이 나올 때까지 같은 난수 흐름에서 다시 뽑는다(최대 DRAW_TRIES번, 다 실패하면 빈 선택)."""
    for _ in range(DRAW_TRIES):
        sel = gen()
        if run.conflict(base, [sel[k] for k in menu if k in sel]) is None:
            return sel
    return {}


def run_condition(comp: Composition, condition: str, evaluator: Any, *, out: Path,
                  variants_fn: VariantsFn | None = None, apply_fn: ApplyFn | None = None,
                  budget: int | None = None, seed: int = 0,
                  reference_starts: int = DEFAULT_REFERENCE_STARTS,
                  reference_kicks: int = DEFAULT_REFERENCE_KICKS) -> dict[str, Any]:
    """조합 하나 × 조건 하나를 돌려 기록을 `out`에 덧붙이고 요약을 돌려준다.

    요약: `{"comp_id", "condition", "best_damage", "best_variants": [label...], "evals", "sims"}`.
    - `evaluator`는 `nikke_opt.evaluator`의 Evaluator(`evaluate`·`submit`·`sim_count`). 가짜로 바꿀 수 있어야 한다.
    - `budget`: 이 호출이 쓸 평가 수 상한(None = 수렴까지). 넘기면 그때까지의 최선으로 끝낸다.
    - 재개: `out`에 같은 (comp_id, condition, start)의 기록이 있으면 이어서 진행한다(같은 결과가 나와야 한다).

    더 붙는 칸: `new_evals`(이번에 새로 평가) · `replayed`(기록에서 재생) · `conflicts`(조립 불가로 건너뜀) ·
    `exhausted`(예산으로 끝남) ·
    `best_start` · `starts`(출발점별 요약). `evals`는 재생 포함 이 (조합, 조건)의 평가 수, `sims`는 이 호출 동안
    평가기 `sim_count`의 증가분이다. `seed` · `reference_*`는 reference 조건에만 쓴다.
    """
    if condition not in common.CONDITIONS:
        raise ValueError(f"조건은 {common.CONDITIONS} 중 하나: {condition!r}")
    out = Path(out)
    if apply_fn is None or (variants_fn is None and condition not in SINGLE):
        import menu as _menu
        apply_fn = apply_fn or _menu.apply
        variants_fn = variants_fn or _menu.variants
    sims0 = evaluator.sim_count
    run = _Run(comp, condition, evaluator, out, apply_fn, budget)
    starts: list[dict] = []
    best: int | None = None
    best_sel: dict[tuple, Variant] = {}
    best_start: str | None = None

    def take(dmg: int | None, sel: dict[tuple, Variant], summ: dict) -> None:
        nonlocal best, best_sel, best_start
        starts.append(summ)
        if _better(dmg, best):
            best, best_sel, best_start = dmg, sel, summ["start"]

    if condition in SINGLE:
        name, base = SINGLE[condition]
        take(*_descend(run, name, base, {}, {}))
    else:
        menu = dict(variants_fn(comp["squad"]))
        if condition in DESCENT:
            name = DESCENT[condition]
            take(*_descend(run, name, common.START_OPTIONS[name], menu, {}))
        else:  # reference
            base = common.START_OPTIONS["layer"]
            for i in range(reference_starts):
                if run.exhausted:
                    break
                s = seed + i
                rng = random.Random(s)
                take(*_descend(run, f"random:{s}", base, menu,
                               _draw(run, base, menu, lambda: _random_selection(menu, rng))))
            for i in range(reference_kicks):
                if run.exhausted or best is None:
                    break
                s = seed + i
                rng = random.Random(f"kick:{s}")
                take(*_descend(run, f"kick:{s}", base, menu,
                               _draw(run, base, menu, lambda: _kick(menu, best_sel, rng))))

    return {"comp_id": comp["id"], "condition": condition, "best_damage": best,
            "best_variants": sorted(v["label"] for v in best_sel.values()), "evals": run.used,
            "sims": evaluator.sim_count - sims0, "new_evals": run.new, "replayed": run.replayed, "conflicts": run.conflicts,
            "exhausted": run.exhausted, "best_start": best_start, "starts": starts}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="실험 6 탐색 실행기 — 조합 × 조건을 돌려 실행 기록을 쓴다")
    ap.add_argument("--comps", required=True, help="조합 id 콤마 목록 또는 all")
    ap.add_argument("--conditions", default=",".join(common.CONDITIONS),
                    help=f"조건 콤마 목록 (기본: 전부 {','.join(common.CONDITIONS)})")
    ap.add_argument("--out", required=True, type=Path, help="실행 기록 JSON Lines (있으면 이어서 진행)")
    ap.add_argument("--compositions", type=Path, default=common.COMPOSITIONS, help="조합 목록 JSON")
    ap.add_argument("--budget", type=int, help="(조합, 조건)마다 평가 수 상한 (기본: 수렴까지)")
    ap.add_argument("--seed", type=int, default=0, help="reference 무작위 출발점의 첫 시드")
    ap.add_argument("--reference-starts", type=int, default=DEFAULT_REFERENCE_STARTS,
                    help=f"reference 무작위 출발점 수 (기본 {DEFAULT_REFERENCE_STARTS})")
    ap.add_argument("--reference-kicks", type=int, default=DEFAULT_REFERENCE_KICKS,
                    help=f"reference 추가 반복 — 최선에서 키 {KICK_KEYS}개를 흔들어 다시 하강하는 횟수"
                         f" (기본 {DEFAULT_REFERENCE_KICKS})")
    ap.add_argument("--jobs", type=int, help="평가기 병렬 수 (기본: CPU 수)")
    ap.add_argument("--evaluator", default="auto", help="auto · rust · python")
    ap.add_argument("--no-cache", action="store_true", help="평가 캐시를 쓰지 않는다")
    args = ap.parse_args(argv)

    comps = common.load_compositions(args.compositions)
    if args.comps != "all":
        want = [c.strip() for c in args.comps.split(",") if c.strip()]
        by_id = {c["id"]: c for c in comps}
        missing = [c for c in want if c not in by_id]
        if missing:
            ap.error(f"없는 조합 id: {missing}")
        comps = [by_id[c] for c in want]
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    bad = [c for c in conditions if c not in common.CONDITIONS]
    if bad:
        ap.error(f"없는 조건: {bad} (가능: {common.CONDITIONS})")

    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator(args.evaluator, jobs=args.jobs, cache=not args.no_cache)
    with ev:
        for comp in comps:
            for cond in conditions:
                s = run_condition(comp, cond, ev, out=args.out, budget=args.budget, seed=args.seed,
                                  reference_starts=args.reference_starts, reference_kicks=args.reference_kicks)
                print(json.dumps({k: v for k, v in s.items() if k != "starts"}, ensure_ascii=False), flush=True)
    print(f"시뮬 {ev.sim_count}회 · 캐시 적중 {ev.cache_hits}회 · 평가기 {ev.version.get('repo')}"
          f" {str(ev.version.get('commit'))[:7]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
