"""실험 32 R3c — B′ 수정 1(README §R3c 사전 등록). B′ 사전 계산 기록(`r3b/`)은 그대로 쓰고 끝 단계만 바꾼다.

    source .cache/evaluators.env && python -I experiments/32_primitive_control/r3c.py end
    source .cache/evaluators.env && python -I experiments/32_primitive_control/r3c.py post
    python -I experiments/32_primitive_control/r3c.py maps
    python -I experiments/32_primitive_control/r3c.py analyze          # → r3c.json · r3c.md

바꾸는 것 둘(결과를 본 진단에서):
  끝 탐침 종류 = R3 4종 ∪ 「단계마다 i번째 후보 전담」(`burst_who<단계>:first=i`, 후보 둘 이상인 단계의 모든 i).
      B′는 1단계 선택지를 한 번도 재지 않았다(4종이 모두 2 · 3단계) — 미란다(1버 전담 규칙)가 든 덱이 지도에서 빠진 원인.
  후처리 = 원시 메뉴 v3 **전체**(버스트 축 포함 — 작은 축만이 아니라), 바탕 P0, 이긴 끝 탐침 선택에서 시작, M3:k2 400.
      B′의 손해는 거의 후처리에서 났다(사전 5덱은 A와 비슷, 후처리 이득 A +3.6~4.6% 대 B′ +1.8~3.3%).
나머지(사전 계산 · 5덱 묶음 이웃 200구성 · 판단 기준 · A 기록)는 R3b와 같다.
"""

from __future__ import annotations

import gzip
import json
import random
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]
import r3  # noqa: E402
import r3b  # noqa: E402
from r3 import r1, M, E8, jdump, jload, MenuConflict  # noqa: E402

r3b.OUT = HERE / "r3c"
r3b.ARM = "Bc"
r3b.NAME = "r3c"


def probes_c(season: int, squad: Sequence[str]) -> list[tuple[str, dict[str, Any]]]:
    """R3 순위 앞 4종(그 덱에 쓸 수 있는 것) + 후보 둘 이상인 단계마다 모든 「i번째 후보 전담」."""
    by = {}
    for (who, ax), vs in r1.prim_variants(squad, v=2).items():
        if ax.startswith("burst_who") or ax == "burst_t":
            for v in vs:
                by[r3.burst_type(v["label"], squad)] = v
    types = [t for t in r3.rank_types() if t in by][:r3.K_PROBE]
    types += [t for t in sorted(by) if t.startswith("burst_who") and ":first=" in t and t not in types]
    base = r1.p_base(season, squad)
    return [(t, r1.prim_apply(base, [by[t]])) for t in types]


def full_variants(squad: Sequence[str]) -> dict:
    """원시 메뉴 v2 전체 + v3 충전 창 톡톡이(차지 UP · 풀차지 전용 아님)."""
    info = r1.nikke_info()
    out = {}
    for (who, ax), vs in r1.prim_variants(squad, v=2).items():
        vs = list(vs)
        if ax == "click" and not info[who]["full_charge_only"]:
            vs.append(r1._v(who, "click", "tapfire@charge4", r1._c(who, {"tap_fire": dict(r3.TAP_FIRE_CHARGE)})))
        out[(who, ax)] = vs
    return out


def full_apply(options: Mapping[str, Any], chosen: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """r1 `prim_apply`(no_burst 한 명만) + r3 `v3_apply`(충전 창 톡톡이 한 명만 · 같은 창 홀드와 엄폐 금지)."""
    if sum("no_burst" in v["patch"].get("operation", {}) for v in chosen) > 1:
        raise MenuConflict("no_burst는 한 명만")
    return r3.v3_apply(options, chosen)


def full_space(s: int, squad: Sequence[str]) -> Any:
    return M.Space(list(squad), variants_fn=full_variants, apply_fn=full_apply, base=r1.p_base(s, squad))


def start_sel(sp: Any, squad: Sequence[str], win: str | None) -> tuple[int, ...]:
    """이긴 끝 탐침 종류 → 메뉴의 같은 선택지(없으면 빈 선택)."""
    sel = list(sp.empty())
    if win:
        for i, v in enumerate(sp.vars):
            if (v["axis"].startswith("burst_who") or v["axis"] == "burst_t") and r3.burst_type(v["label"], squad) == win:
                sel[sp.key_of[i]] = i
                break
        else:
            raise KeyError(win)
    return tuple(sel)


def m3_from(run: Any, start: tuple[int, ...], kick: int = 2, seed: int = 0) -> None:
    """실험 7 `m3`와 같고 시작점만 받는다."""
    sp = run.space
    rng = random.Random(seed)
    M.descend(run, start)
    stale = 0
    while not run.exhausted and stale < 200:
        before = run.used
        s = list(run.best_sel)
        for k in rng.sample(range(sp.K), min(kick, sp.K)):
            s[k] = rng.choice([o for o in sp.opts[k] + [-1] if o != s[k]])
        M.descend(run, tuple(s))
        stale = stale + 1 if run.used == before else 0


def post_one_c(d: Mapping[str, Any], ev: Any, tag: str = "") -> dict[str, Any]:
    f = r3b.sdir(d["season"]) / "post" / f"{d['id']}{tag}.json"
    if f.exists():
        x = jload(f)
        if x.get("base") is None:      # 빈 선택(P0)을 재지 않은 덱 — 진행 표시의 이득은 시작점 대비로
            x["base"] = x.get("start")
        return x
    sp = full_space(d["season"], d["squad"])
    st = start_sel(sp, d["squad"], d["win"])
    log = f.with_suffix(".jsonl")
    log.parent.mkdir(parents=True, exist_ok=True)
    run = M.Run({"id": d["id"], "squad": list(d["squad"])}, sp, ev, method=f"{r3b.ARM}:{r3.SPEC}", budget=r3.BUDGET, out=log)
    t0 = time.time()
    try:
        m3_from(run, st, kick=2, seed=M.job_seed(d["id"] + tag, r3.SPEC))
    finally:
        run.close()
    raw = log.read_bytes()
    with gzip.open(log.with_suffix(".jsonl.gz"), "wb") as g:
        g.write(raw)
    log.unlink()
    errs = sum(1 for ln in raw.decode().splitlines() if json.loads(ln)["error"])
    out = {**d, "arm": r3b.ARM, "tag": tag, "evals": run.used, "errors": errs, "best": run.best / E8,
           "start": None if run.value(st) is None else run.value(st) / E8, "base": run.base_damage / E8 if run.base_damage is not None else (None if run.value(st) is None else run.value(st) / E8),
           "p0": None if run.base_damage is None else run.base_damage / E8,
           "best_variants": list(sp.labels(run.best_sel)), "keys": sp.K, "options": sp.nv, "seconds": round(time.time() - t0, 1)}
    jdump(f, out)
    return out


def cmd_maps_c(a: Any) -> int:
    """지도는 이 프로세스에서 차례로(자식 프로세스가 바꿔 끼운 설정을 못 볼 수 있어서)."""
    for s in [int(x) for x in str(a.season).split(",")]:
        print(r3b._map_job(s), flush=True)
    return 0


r3.probes = probes_c          # r3b.end_probe가 부르는 탐침
r3b.post_one = post_one_c     # r3b.cmd_post가 부르는 후처리
r3b.cmd_maps = cmd_maps_c

if __name__ == "__main__":
    sys.exit(r3b.main())
