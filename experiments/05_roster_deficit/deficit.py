"""사전 실험 5 — 로스터 결손. 핵심 니케가 없거나 육성이 고르지 않은 계정에서
「랭커 구성 옮기기 + 대체」(기준선)와 시뮬 탐색의 차이를 잰다.

시나리오 (풀 = 실험 2의 60명, 보스 S40):

- 미보유 — 풀에서 몇 명을 뺀다. 남은 니케는 전원 기본 스펙이라 실험 2·4의 결과를 그대로 쓴다.
  · 무작위 3명 ×2 · 무작위 6명 ×2 (S40 랭커 사용률 95% 이상 21명 중에서)
  · 상징적 2개: 라피 : 레드 후드 없음 / 1덱 축(아니스 : 스타 · 브리드 : 사일런트 트랙) 없음
- 육성 불균형 — 전원 보유, 니케마다 육성 등급(상·중·하)이 다르다. nikke-calc의 육성 프로필
  (`profiles/<이름>.json`, `--profile`)로 넘긴다. 상 = 기본 스펙 그대로.
  · 무작위 — 풀 전원에 상 50% · 중 30% · 하 20%
  · 핵심 6명 하 — 「무작위 6명 A」와 같은 6명을 하로, 나머지는 상 (미보유와 직접 비교)

기준선 — 랭커 300명 각자의 5덱을 내 로스터로 옮긴다. 없는 니케 자리는 같은 버스트 단계에서
S40 랭커 사용률이 높은 순으로, 그 5덱이 안 쓰는 보유 니케로 채운다(없으면 단계 무관).
옮긴 스쿼드를 전부 시뮬하고 5덱 합이 가장 높은 랭커가 기준선이다. 육성 불균형은 빠진 니케가
없으니 랭커 5덱 그대로다.

탐색 — 기준선이 평가한 스쿼드만으로 출발한다(실험 2의 무작위 결과는 쓰지 않는다). 실험 4의 축소판:
라운드마다 지금까지의 결과로 「니케 + 짝」 릿지를 학습하고,
① 최선 5덱 고치기(다른 덱이 안 쓰는 니케로 교체 · 덱 간 맞교환, 예상 이득 순) 70%
② 상위 구성의 한 명 교체 이웃(같은 단계, 예측 점수 순) 30%
를 돌린다. 마지막 100회는 최선 5덱과 상위 구성의 배치 순서 다듬기다.

평가 수는 요청한 서로 다른 스쿼드 수다 — 실험 2·4 결과·캐시로 채워도 센다(실험 4와 같다).
기준선 평가 수와 탐색 평가 수는 따로 센다.

사용: NIKKE_CALC_DIR=... python deficit.py [--only 이름,...] [--budget 800]
      → log.jsonl(시나리오별 평가 전부), summary.json, results.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
EXP2 = HERE.parent / "02_score_distribution"
EXP4 = HERE.parent / "04_improvement_margin"
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(EXP2))
sys.path.insert(0, str(EXP4))
from nikke_opt.evaluator import EvalRequest, NikkeCalcEvaluator  # noqa: E402
from run import BOSS, distinct_orders  # noqa: E402
from search import Book, fit, neighbors, pack, pack_moves  # noqa: E402

E8 = 1e8
SEED = 20261007
CORE_USE = 0.95        # 무작위 미보유를 뽑는 「핵심」 = S40 랭커 사용률 이 이상
ROUND = 100            # 탐색 한 라운드 평가 수 (곡선의 눈금)
PACK_SHARE = 0.7       # 라운드 중 5덱 고치기 몫, 나머지는 이웃
ORDER_RESERVE = 100    # 마지막 배치 순서 다듬기 몫
PARENTS, PER_PARENT = 40, 8
CHECKPOINTS = (100, 300, 800)

# 육성 등급 → 프로필 항목. 상은 빈 항목 = 기본 스펙(레이어 포함) 그대로다.
# 기본 스펙: 스킬 10/10/10, 오버로드 레벨 10 — 우월코드 4줄 88.6 · 공격력 2줄 22.22, 소장품 SR15.
# 최대 장탄은 니케별 레이어가 일부러 정한 값이 있어(프리바티 0 등) 건드리지 않는다.
TIERS = {
    "상": {},
    "중": {"skill_levels": {"1": 7, "2": 7, "3": 7},
          "equip_skills": {"atk_pct": 11.11, "element_bonus": 44.3}},
    "하": {"skill_levels": {"1": 4, "2": 4, "3": 4},
          "equip_skills": {"atk_pct": 0, "element_bonus": 0}, "collection_stage": "없음"},
}


def scenarios(pool: dict) -> list[dict]:
    core = sorted(n for n, v in pool.items() if v["s40_use"] >= CORE_USE)
    out = []
    picks = {}
    for k, tag in ((3, "A"), (3, "B"), (6, "A"), (6, "B")):
        rng = random.Random(f"{SEED}-{k}-{tag}")
        picks[(k, tag)] = sorted(rng.sample(core, k))
        out.append({"name": f"미보유 무작위 {k}명 {tag}", "missing": picks[(k, tag)], "tiers": {}})
    out.append({"name": "미보유 레드 후드", "missing": ["라피 : 레드 후드"], "tiers": {}})
    out.append({"name": "미보유 1덱 축", "missing": ["아니스 : 스타", "브리드 : 사일런트 트랙"], "tiers": {}})
    rng = random.Random(f"{SEED}-tiers")
    out.append({"name": "육성 무작위", "missing": [],
                "tiers": {n: rng.choices(["상", "중", "하"], [0.5, 0.3, 0.2])[0] for n in sorted(pool)}})
    out.append({"name": "육성 핵심 6명 하", "missing": [], "tiers": {n: "하" for n in picks[(6, "A")]}})
    return out


def write_profile(calc_dir: Path, sc: dict, pool: dict) -> str | None:
    """시나리오의 육성 프로필을 nikke-calc `profiles/`에 쓰고 이름을 돌려준다(전원 상이면 None).

    평가기 캐시는 프로필 *이름*으로 키를 잡으므로 이름에 내용 해시를 넣는다.
    """
    if not any(t != "상" for t in sc["tiers"].values()):
        return None
    chars = {n: TIERS[sc["tiers"].get(n, "상")] for n in sorted(pool) if n not in sc["missing"]}
    blob = json.dumps(chars, ensure_ascii=False, sort_keys=True)
    name = f"nikkeopt-exp5-{hashlib.sha256(blob.encode()).hexdigest()[:10]}"
    d = calc_dir / "profiles"
    d.mkdir(exist_ok=True)
    data = {"_meta": {"name": name, "note": f"nikke-opt 실험 5 가상 육성 — {sc['name']}"}, "chars": chars}
    (d / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return name


def transplant(decks: list[tuple], owned: dict) -> list[tuple]:
    """랭커 5덱을 내 로스터로. 없는 니케 → 같은 단계·사용률 높은 순으로 5덱이 안 쓰는 보유 니케."""
    used = {n for d in decks for n in d if n in owned}
    out = []
    for d in decks:
        nd = []
        for n in d:
            if n not in owned:
                cands = [m for m in owned if m not in used and owned[m]["burst"] == BURST_OF[n]]
                cands = cands or [m for m in owned if m not in used]
                n = max(cands, key=lambda m: (owned[m]["s40_use"], owned[m]["prior"], m))
                used.add(n)
            nd.append(n)
        out.append(tuple(nd))
    return out


BURST_OF: dict[str, str] = {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="돌릴 시나리오 이름(콤마)")
    ap.add_argument("--budget", type=int, default=800)
    ap.add_argument("--jobs", type=int)
    args = ap.parse_args()

    full_pool = json.loads((EXP2 / "pool.json").read_text(encoding="utf-8"))["pool"]
    BURST_OF.update({n: v["burst"] for n, v in full_pool.items()})
    rk = json.loads((EXP2 / "ranker_squads.json").read_text(encoding="utf-8"))
    rk_sq = [tuple(s["squad"]) for s in rk["squads"]]

    # 기본 스펙 결과 (실험 2·4) — 전원 상인 스쿼드는 다시 돌리지 않는다
    known: dict[tuple, float] = {}
    for path in (EXP2 / "results.jsonl", EXP4 / "log.jsonl"):
        for s in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(s)
            if r["error"] is None:
                known[tuple(r["squad"])] = r["total_damage"] / E8

    ev = NikkeCalcEvaluator(jobs=args.jobs)
    summary_path = HERE / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if args.only and summary_path.exists() else {}
    summary.setdefault("scenarios", {})
    summary.update({"boss": BOSS, "evaluator": ev.version, "budget": args.budget,
                    "known_default_spec": len(known)})
    todo = scenarios(full_pool)
    if args.only:
        want = set(args.only.split(","))
        todo = [sc for sc in todo if sc["name"] in want]
    log = open(HERE / "log.jsonl", "a" if args.only else "w", encoding="utf-8")

    for sc in todo:
        name = sc["name"]
        owned = {n: v for n, v in full_pool.items() if n not in sc["missing"]}
        names = sorted(owned)
        profile = write_profile(ev.calc_dir, sc, full_pool)
        tier = {n: sc["tiers"].get(n, "상") for n in owned}
        opts = {"profile": profile} if profile else {}
        book = Book()
        counts = {"known": 0, "sim_or_cache": 0}
        sims0 = ev.sim_count
        print(f"\n== {name} — 미보유 {sc['missing']} · 하 {sum(t == '하' for t in tier.values())}"
              f" · 중 {sum(t == '중' for t in tier.values())} · 프로필 {profile}", file=sys.stderr, flush=True)

        if profile:  # 상 = 기본 스펙이라는 전제를 확인한다 (예산 밖)
            plain = [sq for sq in known if all(tier.get(n) == "상" for n in sq)][:3]
            for sq, r in zip(plain, ev.evaluate([EvalRequest(sq, boss=BOSS, options=opts) for sq in plain])):
                if r.error or abs(r.total_damage / E8 - known[sq]) > 1e-6:
                    raise RuntimeError(f"상 등급이 기본 스펙과 다르다: {sq} {r.total_damage} vs {known[sq]}")

        def run(squads: list[tuple], phase: str) -> None:
            squads = [sq for sq in dict.fromkeys(squads) if sq not in book.seen]
            ask = []
            for sq in squads:
                if sq in known and all(tier[n] == "상" for n in sq):
                    book.add(sq, known[sq])
                    counts["known"] += 1
                    log.write(json.dumps({"scenario": name, "phase": phase, "squad": list(sq),
                                          "dmg": known[sq], "src": "known"}, ensure_ascii=False) + "\n")
                else:
                    ask.append(sq)
            for i in range(0, len(ask), 40):
                part = ask[i:i + 40]
                for sq, r in zip(part, ev.evaluate([EvalRequest(sq, boss=BOSS, options=opts) for sq in part])):
                    if r.error is None:
                        book.add(sq, r.total_damage / E8)
                    counts["sim_or_cache"] += 1
                    log.write(json.dumps({"scenario": name, "phase": phase, "squad": list(sq),
                                          "dmg": None if r.error else r.total_damage / E8,
                                          "src": "cache" if r.cached else "sim", "error": r.error},
                                         ensure_ascii=False) + "\n")
                log.flush()
                print(f"  {phase}: {min(i + 40, len(ask))}/{len(ask)} · 시뮬 누적 {ev.sim_count}",
                      file=sys.stderr, flush=True)

        # ── 기준선 ──
        players = [transplant([rk_sq[i] for i in p["squads"]], owned) for p in rk["players"]]
        run([d for decks in players for d in decks], "기준선")
        base_n = len(book.seen)
        sums = [sum(book.seen[d] for d in decks) for decks in players]
        best_i = int(np.argmax(sums))
        base_pack = pack(book)

        # ── 탐색 ──
        evals = 0
        history = [{"평가": 0, "최선 5덱": base_pack[0]}]
        main_budget = args.budget - ORDER_RESERVE
        while evals < main_budget:
            n = min(ROUND, main_budget - evals)
            score = fit(book, names)
            decks = [sq for _, sq in pack(book)[1]]
            pick, seen = [], set()

            def take(sqs: list[tuple]) -> bool:
                new = [s for s in sqs if s not in book.seen and frozenset(s) not in book.best
                       and frozenset(s) not in seen]
                if not new:
                    return True
                if len(pick) + len(new) > n:
                    return False
                pick.extend(new)
                seen.update(frozenset(s) for s in new)
                return True

            for _, new in pack_moves(decks, owned, score):
                if len(pick) >= int(n * PACK_SHARE):
                    break
                take(new)
            parents = sorted(book.best.values(), reverse=True)[:PARENTS]
            cands = []
            for _, sq in parents:
                lst = [(score(frozenset(nb)), nb) for nb in neighbors(sq, owned)
                       if frozenset(nb) not in book.best]
                cands += sorted(lst, reverse=True)[:PER_PARENT]
            for _, nb in sorted(cands, reverse=True):
                if len(pick) >= n:
                    break
                take([nb])
            if not pick:
                break
            run(pick, f"탐색 {evals // ROUND + 1}")
            evals += len(pick)
            history.append({"평가": evals, "최선 5덱": pack(book)[0]})

        best = pack(book)
        tops = [sq for _, sq in best[1]] + [sq for _, sq in sorted(book.best.values(), reverse=True)[:20]]
        orders = [p for sq in dict.fromkeys(tops) for p in distinct_orders(sq, BURST_OF) if p not in book.seen]
        orders = list(dict.fromkeys(orders))[:args.budget - evals]
        run(orders, "순서")
        evals += len(orders)
        final = pack(book)
        history.append({"평가": evals, "최선 5덱": final[0]})

        def at(budget: int) -> float:
            return max(h["최선 5덱"] for h in history if h["평가"] <= budget)

        res = {
            "missing": sc["missing"], "tiers": {k: v for k, v in tier.items() if v != "상"}, "profile": profile,
            "baseline_evals": base_n, "search_evals": evals, "sims": ev.sim_count - sims0, "counts": counts,
            "baseline_best": {"total": sums[best_i], "player": rk["players"][best_i]["player"],
                              "squads": [[book.seen[d], list(d)] for d in players[best_i]]},
            "baseline_median": float(np.median(sums)),
            "baseline_repack": {"total": base_pack[0], "squads": [[d, list(s)] for d, s in base_pack[1]]},
            "history": history,
            "at": {str(b): at(b) for b in CHECKPOINTS if b <= args.budget},
            "final": {"total": final[0], "squads": [[d, list(s)] for d, s in final[1]]},
        }
        summary["scenarios"][name] = res
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  → 기준선 {sums[best_i]:.1f} · 재조립 {base_pack[0]:.1f} · 탐색 {final[0]:.1f}"
              f" ({final[0] / sums[best_i] - 1:+.1%})", file=sys.stderr, flush=True)
    log.close()
    report(summary)


def report(summary: dict) -> None:
    lines = [f"# 실험 5 결과 — 로스터 결손 (평가기 {summary['evaluator']['commit'][:7]}, {summary['boss']},"
             f" 탐색 예산 {summary['budget']}회)\n",
             "| 시나리오 | 기준선 평가 | 기준선 (최고 랭커) | 랭커 중앙 | 옮긴 스쿼드 재조립 | "
             + " | ".join(f"탐색 {b}" for b in CHECKPOINTS) + " | 최고 랭커 대비 |",
             "|---|---|---|---|---|" + "---|" * len(CHECKPOINTS) + "---|"]
    for name, r in summary["scenarios"].items():
        b = r["baseline_best"]["total"]
        cells = [f"{r['at'][str(c)]:.1f}" if str(c) in r["at"] else "—" for c in CHECKPOINTS]
        lines.append(f"| {name} | {r['baseline_evals']} | {b:.1f} | {r['baseline_median']:.1f} | "
                     f"{r['baseline_repack']['total']:.1f} | " + " | ".join(cells)
                     + f" | {r['final']['total'] / b - 1:+.1%} |")
    for name, r in summary["scenarios"].items():
        lines.append(f"\n## {name}\n")
        if r["missing"]:
            lines.append(f"미보유: {', '.join(r['missing'])}\n")
        if r["tiers"]:
            by = {t: sorted(n for n, v in r["tiers"].items() if v == t) for t in ("중", "하")}
            lines.append("육성: " + " · ".join(f"{t} {len(v)}명 ({', '.join(v)})" for t, v in by.items() if v) + "\n")
        lines.append(f"평가: 기준선 {r['baseline_evals']} + 탐색 {r['search_evals']}"
                     f" (실제 시뮬 {r['sims']}, 실험 2·4 결과 재사용 {r['counts']['known']})\n")
        lines.append(f"기준선 — 랭커 {r['baseline_best']['player']}의 5덱 옮기기 ({r['baseline_best']['total']:.1f}억):\n")
        lines += [f"- {d:.1f}억 — {' → '.join(sq)}" for d, sq in r["baseline_best"]["squads"]]
        lines.append(f"\n탐색 후 최선 ({r['final']['total']:.1f}억):\n")
        lines += [f"- {d:.1f}억 — {' → '.join(sq)}" for d, sq in r["final"]["squads"]]
    (HERE / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
