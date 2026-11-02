"""실험 33 Q1 직접 확인 보충 — 리틀 머메이드 본인 딜의 조합 메커니즘(사용자 2026-11-02: 「자체 대미지 메커니즘에 조합 관련이 있다」).

    source .cache/evaluators.env && python experiments/33_role_vectors/breakdown33.py   → run_log/breakdown.json

스킬 자료(계산기 `parsed_skills.json`)에서 리틀 머메이드 본인 딜 중 조합을 타는 것:
- 「거품 난사」 — 스쿼드가 탄 500발을 쓸 때마다 무작위 적에게 10연속 딜(탄을 많이 쓰는 동료가 많을수록 자주).
- 「버블 웨이브」 — 풀버스트 중 매초 4연속 딜(풀버스트 횟수 · 길이를 따른다). 「버블 오더 4」(스쿼드 탄 400발마다 버스트 게이지)도 여기에 닿는다.

틀: 리틀 머메이드(1단계) + 2단계 하나 + 3단계 딜러 셋. 3단계 딜러를 무기 하나로 맞춘 판(MG · SG · RL · SR)과 2단계 {크라운(MG), 아르카나 : 포츈 메이트(SG)}.
속성 전격(우코 아님). 같은 틀에 목단(1단계 버퍼, 이런 스킬 없음)을 넣은 판을 대조로 둔다 — 동료 버프 · 딜 차이 같은 일반 효과를 가른다.
본인 딜은 평가기 어댑터로, 출처별 딜은 평가기 CLI `--view breakdown`(같은 요청 줄)으로 받는다. 계산기 코드는 읽지 않는다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run33 as R  # noqa: E402

LM, MOKDAN = "리틀 머메이드", "목단"
ELEMENT = "전격"
B2S = ("크라운", "아르카나 : 포츈 메이트")
DEALERS = {
    "MG": ("라피 : 레드 후드", "미하라 : 본딩 체인", "신데렐라 : 크리스탈 웨이브"),
    "SG": ("드레이크 : 그레이트 빌런", "퀸(마코토)", "슈가"),
    "RL": ("네온 : 비전 아이", "신데렐라", "레이븐"),
    "SR": ("리버렐리오", "스노우 화이트 : 헤비암즈", "맥스웰"),
}
SKILLS = ("일반공격", "버블 웨이브", "거품 난사")
OUT = R.LOG / "breakdown.json"
ROW = re.compile(r"^\s{4}(\S.*?)\s+([\d,]+)\s+(\d+)\s+[\d.]+%\s*$")


def plan() -> list[dict[str, Any]]:
    out = []
    for b2 in B2S:
        for w, ds in DEALERS.items():
            for b1 in (LM, MOKDAN):
                out.append({"b1": b1, "b2": b2, "dealers": w, "squad": [b1, b2, *ds]})
    return out


def parse_breakdown(text: str) -> dict[str, dict[str, int]]:
    """`--view breakdown` 출력(사이클별 표)을 스킬마다 딜 · 히트 합으로."""
    tot: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        m = ROW.match(line)
        if not m or m.group(1) in ("스킬명", "합계"):
            continue
        t = tot.setdefault(m.group(1), {"damage": 0, "hits": 0})
        t["damage"] += int(m.group(2).replace(",", ""))
        t["hits"] += int(m.group(3))
    return tot


def main() -> int:
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    p = plan()
    reqs = [EvalRequest(tuple(x["squad"]), boss=None, options=R.R30.options(ELEMENT)) for x in p]
    t0 = time.time()
    with make_evaluator() as ev:
        sims0 = ev.sim_count
        res = ev.evaluate(reqs)
        sims = ev.sim_count - sims0
        version = ev.version
    cli = 0
    for x, q, r in zip(p, reqs, res):
        if r.error:
            raise RuntimeError(f"평가 실패: {x['squad']} {r.error}")
        mem = R.member_vec(x["squad"], r.raw.get("members"))
        x.update(total=r.total_damage, own=mem[0])
        if x["b1"] == LM:
            o = subprocess.run([os.environ["NIKKE_SIM_BIN"], "--request", json.dumps(q.to_line(), ensure_ascii=False),
                                "--view", "breakdown", "--char", LM], capture_output=True, text=True, check=True)
            cli += 1
            x["breakdown"] = parse_breakdown(o.stdout)
            got = sum(v["damage"] for v in x["breakdown"].values())
            if abs(got - x["own"]) > 0.01 * x["own"]:
                raise RuntimeError(f"출처별 합 {got} ≠ 본인 딜 {x['own']}: {x['squad']}")
    out = {"evaluator": version, "element": ELEMENT, "sims_adapter": sims, "sims_cli": cli,
           "seconds": round(time.time() - t0, 1), "rows": p}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for x in p:
        b = x.get("breakdown", {})
        print(x["b2"], x["dealers"], x["b1"], f"본인 {x['own'] / 1e8:.2f}억 · 팀 {x['total'] / 1e8:.1f}억",
              " · ".join(f"{k} {b[k]['damage'] / 1e8:.2f}억/{b[k]['hits']}타" for k in SKILLS if k in b))
    print(json.dumps({k: out[k] for k in ("sims_adapter", "sims_cli", "seconds")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
