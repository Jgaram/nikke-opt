"""실험 7 — 검증 조합 16개 선정 → val_compositions.json · val_selection.md.

실험 6 `select_comps.py`의 규칙(후보 생성 · 기본 레이어 평가 · 틀별 3등분 · 씨앗 · 탐욕 · 수리)을 그대로 쓰고
규모만 16개로 줄인다. 실험 6의 32개(개발용)와 같은 구성(순서 무시)은 후보에서 뺀다. 시드는 새로 정한다.
기법을 돌리기 전에 한 번 고르고 고정한다(README §자료 나누기).

    source .cache/evaluators.env && python experiments/07_control_search/select_val.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP6 = HERE.parent / "06_control_menu"
sys.path[:0] = [str(EXP6), str(HERE.parent.parent)]
import common  # noqa: E402
import select_comps as sc  # noqa: E402

SEED = 20261030
MIN_APPEAR = 1  # 실험 6은 3. 16개 규모에서 3은 풀리지 않고(수리가 조합을 모두 뺀다) 2는 프리카가 빠진다 — 검증 조합은 기법 성능용이라 1
QUOTA = {"1-1-3": 5, "1-2-2": 4, "2-1-2": 4, "redhood": 3}  # 실험 6 할당(9·8·7·6)을 16개로 줄인 것
OUT_JSON = HERE / "val_compositions.json"
OUT_MD = HERE / "val_selection.md"


def configure(min_appear: int = MIN_APPEAR) -> None:
    sc.QUOTA = dict(QUOTA)
    sc.MIN_APPEAR = min_appear
    sc.TARGET_N, sc.MIN_N, sc.MAX_N = 16, 15, 17


def main() -> int:
    configure(int(sys.argv[1]) if len(sys.argv) > 1 else MIN_APPEAR)
    dev = {frozenset(c["squad"]) for c in common.load_compositions(EXP6 / "compositions.json")}
    allc = sc.candidates()
    cands = [c for c in allc if frozenset(c["squad"]) not in dev]
    from nikke_opt.evaluator import make_evaluator
    with make_evaluator(budget=1000) as ev:
        evals = sc.evaluate(cands, ev)
        sims = ev.sim_count
    sel, log = sc.select(cands, {i: e["damage"] for i, e in evals.items()}, seed=SEED)
    comps = sc.to_compositions(sel)
    for c in comps:
        c["id"] = "v" + c["id"][1:]
    OUT_JSON.write_text(json.dumps(comps, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    cnt = Counter(m for c in comps for m in c["squad"])
    lines = [
        "# 실험 7 검증 조합 선정",
        "",
        f"[`select_val.py`](select_val.py)가 실험 6 [`select_comps.py`](../06_control_menu/select_comps.py)의 규칙을 그대로 쓰고 "
        f"규모만 바꿔 골랐다: 최소 등장 {sc.MIN_APPEAR}회(실험 6은 3회 — 16개 규모에서 3은 수리가 조합을 모두 빼고, 2는 레이어 대상 프리카가 빠진다. 검증 조합은 기법 성능을 재는 용도다), 할당 {', '.join(f'{k} {v}' for k, v in QUOTA.items())}(합 16, 범위 15~17), 시드 `{SEED}`, "
        f"실험 6 개발 조합 32개와 같은 구성 제외. 기법을 돌리기 전에 골라 고정했다.",
        "",
        f"- 후보 {len(allc)}개 중 개발 조합과 같은 구성 {len(allc) - len(cands)}개 제외 → {len(cands)}개, "
        f"평가 오류 없음 {log['evaluated_ok']}개, 상·중 구간 {log['eligible']}개",
        f"- 평가 {len(evals)}회(기본 레이어 + `accumulate` 1회씩), 이번 실행의 새 시뮬 {sims}회(나머지는 캐시 — 2026-10-29 첫 실행은 316회). 평가기 {ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}",
        f"- 규칙 점검: {'통과' if not log['violations'] else '; '.join(log['violations'])}",
        f"- 수리: {'; '.join(log['repair']) or '없음'}",
        "",
        "| id | 틀 | 배치 순서 | 기본 레이어 딜(억) | 태그 |",
        "|---|---|---|---:|---|",
    ]
    for c in comps:
        lines.append(f"| {c['id']} | {c['skeleton']} | {' · '.join(c['squad'])} | {c['default_damage'] / 1e8:.1f} | "
                     f"{' '.join(c['tags'])} |")
    lines += ["", "니케별 등장 조합 수: " + " · ".join(f"{m} {n}" for m, n in sorted(cnt.items(), key=lambda x: (-x[1], x[0]))), ""]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"조합 {len(comps)}개 · 시뮬 {sims} · 점검 {log['violations'] or '통과'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
