"""실험 33 Q1 직접 확인 — 확인 4 · 5가 「아님」일 때 README §Q1에 등록한 「그 니케가 든 덱 몇 개를 직접 비교」(시뮬 수십).

    source .cache/evaluators.env && python experiments/33_role_vectors/inspect33.py
        → run_log/inspect.json · inspect.md 표는 README 결과 절에 옮긴다

문턱 · 지문 정의는 바꾸지 않는다. 여기 숫자는 「평가기와 실전 감의 차이」인지 「지문이 놓친 것」인지 가리는 데만 쓴다.

- A 브리드 : 사일런트 트랙 + 토브: 기준 덱 R 0 · 2 · 3의 1단계 칸에 {토브, 원래 니케(아니스 : 스타), 버퍼가 1단계 중앙인 니케},
  2단계 칸에 {브리드, 아르카나 : 포츈 메이트(같은 SG), 타키나(SR — SG 아닌 대조)}. 속성 풍압(브리드 우코) · 전격.
  등록한 tove_lift는 토브를 원래 1단계 니케 자리에 넣어 재므로, R 덱 대부분(19개 중 15개)에서 「토브 대 아니스 : 스타」다.
- B 리틀 머메이드: 기준 덱 R 0 · 3의 1단계 칸에 {리틀 머메이드, 목단(1단계 버퍼 · 본인 딜이 비슷한 대조)},
  2단계 칸에 무기가 다른 2단계 니케 여러 명. 속성 전격(둘 다 우코 아님). 동료 무기에 따라 본인 딜이 얼마나 흔들리는지 비교한다.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run33 as R  # noqa: E402

TOVE, BREAD = R.TOVE, R.BREAD
A_DECKS = (0, 2, 3)
A_X = (BREAD, "아르카나 : 포츈 메이트", "타키나")
A_ELEMENTS = ("풍압", "전격")
LM, MOKDAN = "리틀 머메이드", "목단"
B_DECKS = (0, 3)
B_SWAPS = ("크라운", "마스트 : 로망틱 메이드", "나유타", "아르카나 : 포츈 메이트", BREAD, "타키나", "민트", "그레이브")
B_ELEMENT = "전격"
OUT = R.LOG / "inspect.json"


def median_b1(fp: Mapping[str, Mapping[str, Any]], stages: Mapping[str, str]) -> str:
    """1단계 니케(시험용 · 토브 · 아니스 : 스타 제외) 중 buffer가 중앙인 니케."""
    xs = sorted((fp[n]["buffer"], n) for n, s in stages.items()
                if s == "1" and n in fp and not n.startswith(R.TEST_PREFIX) and n not in (TOVE, "아니스 : 스타"))
    return xs[len(xs) // 2][1]


def plan_a(refs: Mapping[str, Any], stages: Mapping[str, str], b1s: Sequence[str]) -> list[dict[str, Any]]:
    out = []
    for i in A_DECKS:
        d = refs["R"][i]
        j1, j2 = R.slot_of(d, i, "1", stages), R.slot_of(d, i, "2", stages)
        for b1 in b1s:
            for x in A_X:
                sq = list(d)
                sq[j1], sq[j2] = b1, x
                if len(set(sq)) < 5:
                    continue
                for el in A_ELEMENTS:
                    out.append({"part": "A", "deck": i, "b1": b1, "x": x, "element": el, "squad": sq})
    return out


def plan_b(refs: Mapping[str, Any], stages: Mapping[str, str]) -> list[dict[str, Any]]:
    out = []
    for i in B_DECKS:
        d = refs["R"][i]
        j1, j2 = R.slot_of(d, i, "1", stages), R.slot_of(d, i, "2", stages)
        for b1 in (LM, MOKDAN):
            for m in (d[j2],) + B_SWAPS:
                sq = list(d)
                sq[j1], sq[j2] = b1, m
                if len(set(sq)) < 5 or (m != d[j2] and m in d):
                    continue
                out.append({"part": "B", "deck": i, "b1": b1, "mate": m, "element": B_ELEMENT, "squad": sq})
    return out


def own(r: Mapping[str, Any], x: str) -> float:
    return r["members"][r["squad"].index(x)]


def summarize_a(recs: Sequence[Mapping[str, Any]], b1s: Sequence[str]) -> dict[str, Any]:
    """X 본인 딜(억) · 팀 몫, 토브 대 다른 1단계의 본인 딜 비."""
    out: dict[str, Any] = {}
    for x in A_X:
        for el in A_ELEMENTS:
            rows = {}
            for b1 in b1s:
                rs = [r for r in recs if r["x"] == x and r["element"] == el and r["b1"] == b1]
                rows[b1] = {"own": statistics.median(own(r, x) / 1e8 for r in rs),
                            "share": statistics.median(own(r, x) / r["total_damage"] for r in rs),
                            "total": statistics.median(r["total_damage"] / 1e8 for r in rs), "n": len(rs)}
            lift = {b1: statistics.median(own(t, x) / own(o, x) for t in recs for o in recs
                                          if t["x"] == o["x"] == x and t["element"] == o["element"] == el
                                          and t["deck"] == o["deck"] and t["b1"] == TOVE and o["b1"] == b1)
                    for b1 in b1s if b1 != TOVE}
            out[f"{x} · {el}"] = {"by_b1": rows, "tove_over": lift}
    return out


def summarize_b(recs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """동료(2단계 칸) 교체에 따른 본인 딜의 흔들림: 최대/최소 · 사분위 범위/중앙."""
    out: dict[str, Any] = {}
    for i in B_DECKS:
        for b1 in (LM, MOKDAN):
            rs = [r for r in recs if r["deck"] == i and r["b1"] == b1]
            v = {r["mate"]: own(r, b1) / 1e8 for r in rs}
            q = statistics.quantiles(list(v.values()), n=4)
            out[f"덱 {i} · {b1}"] = {"own_by_mate": v, "max_over_min": max(v.values()) / min(v.values()),
                                     "iqr_over_med": (q[2] - q[0]) / statistics.median(v.values())}
    return out


def main() -> int:
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    refs = json.loads(R.REFS.read_text(encoding="utf-8"))
    stages = R.roster()
    q1 = json.loads((R.LOG / "q1.json").read_text(encoding="utf-8"))
    mid = median_b1(q1["fp"]["R"], stages)
    b1s = (TOVE, refs["R"][0][0], mid)
    plan = plan_a(refs, stages, b1s) + plan_b(refs, stages)
    t0 = time.time()
    with make_evaluator() as ev:
        sims0 = ev.sim_count
        res = ev.evaluate([EvalRequest(p["squad"], boss=None, options=R.R30.options(p["element"])) for p in plan])
        sims = ev.sim_count - sims0
        version = ev.version
    recs = [dict(p, total_damage=r.total_damage, members=R.member_vec(p["squad"], r.raw.get("members")), error=r.error)
            for p, r in zip(plan, res)]
    bad = [r for r in recs if r["error"] or r["members"] is None]
    if bad:
        raise RuntimeError(f"평가 실패 {len(bad)}건: {bad[0]}")
    out = {"evaluator": version, "median_b1": mid, "requests": len(plan), "sims": sims, "seconds": round(time.time() - t0, 1),
           "A": summarize_a([r for r in recs if r["part"] == "A"], b1s), "B": summarize_b([r for r in recs if r["part"] == "B"]),
           "records": recs}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k not in ("records", "evaluator")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
