"""실험 6 W4 — 탐색 실행기. (골격: 관리자. 구현: W4)

여섯 조건(common.CONDITIONS)을 조합마다 돌리고 실행 기록(common.Record)을 JSON Lines로 쓴다.
선택지는 `variants_fn`·`apply_fn`으로 받는다 — 기본은 menu.variants · menu.apply, 테스트는 가짜를 넣는다.

    source .cache/evaluators.env && python experiments/06_control_menu/search.py \
        --comps c01,c02 --conditions layer,search_from_layer --out <scratchpad>/run.jsonl
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent.parent)]
from common import Composition, Variant  # noqa: E402

VariantsFn = Callable[[Sequence[str]], Mapping[tuple, list[Variant]]]
ApplyFn = Callable[[Mapping[str, Any], Sequence[Variant]], dict[str, Any]]


def run_condition(comp: Composition, condition: str, evaluator: Any, *, out: Path,
                  variants_fn: VariantsFn | None = None, apply_fn: ApplyFn | None = None,
                  budget: int | None = None, seed: int = 0) -> dict[str, Any]:
    """조합 하나 × 조건 하나를 돌려 기록을 `out`에 덧붙이고 요약을 돌려준다.

    요약: `{"comp_id", "condition", "best_damage", "best_variants": [label...], "evals", "sims"}`.
    - `evaluator`는 `nikke_opt.evaluator`의 Evaluator(`evaluate`·`submit`·`sim_count`). 가짜로 바꿀 수 있어야 한다.
    - `budget`: 이 호출이 쓸 평가 수 상한(None = 수렴까지). 넘기면 그때까지의 최선으로 끝낸다.
    - 재개: `out`에 같은 (comp_id, condition, start)의 기록이 있으면 이어서 진행한다(같은 결과가 나와야 한다).
    """
    raise NotImplementedError("W4")


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError("W4")


if __name__ == "__main__":
    sys.exit(main())
