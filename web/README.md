# 예측 현황판 사이트 (`web/`)

레포의 탐색 로직이 **얼마나 맞게 예상하는지 사람이 눈으로 확인**하려고 만든 정적 사이트다. 레포 소유자가 보는 용도이며,
지금은 [실험 22](../experiments/22_ranker_check/README.md)(랭커 대조)만 보여 준다.

주소: <https://jgaram.github.io/nikke-opt/> (레포 공개 + Pages 설정 뒤)

## 보여 주는 것

| 칸 | 내용 | 출처(`experiments/22_ranker_check/`) |
|---|---|---|
| 한눈에 | 판단(잠정) · N25 · V_top 중앙 · 한 판 시뮬 수 · 시간 · 99% 도달 평가 수 | `analyze22.judge` + `run_log/precompute_*.json` |
| 시즌별 | 시즌마다 N25 · V_top 점 그래프(랭커끼리 눈금 띠), 시즌 × 보스 표 | `analyze22.season_metrics` |
| 조건 | 시즌 기간 · 보스 속성 → 약점 · 코어 · 니케 풀(직전 표시 시즌 이후 신규) · 애장품 0단계 | `seasons.json` |
| 시뮬 비용 | 평가 수 · 시간 · 수렴 곡선(최선 5덱 합 ÷ 최종) · 단계별 시뮬 수 | `precompute_*.json`(`history`) · `.jsonl.gz`(`phase`) · `meta_*.json` |
| 1순위 5덱 | 덱별 딜 · 배치 순서 · 속성 · 버스트 단계 · 신규 니케 · 랭커 스쿼드와 겹침 · 주력(있으면) | `precompute_*.json`(`final`) · `.jsonl.gz` · `members_*.json` |
| 운용 · 컨트롤(더보기) | 큐브, 탐색에서 고른 컨트롤(실험 22는 없음), 평가기 기본 레이어가 거는 컨트롤 | [`06_control_menu/nikke_info.json`](../experiments/06_control_menu/nikke_info.json)(nikke-calc 23164e4의 `char_defaults` 기준) |
| 2~8순위 | 앞 순위와 같은 덱을 2개 이하만 공유하는 다음 최선 5덱(`run11.extract`) | `precompute_*.json`(`sets`) |
| 유력 대안 | 뼈대가 다른 안 — **실험 22에서는 계산하지 않아 공란** | — |
| 랭커 비교 | 대표 5덱 · 1위 5덱 · 상위 40 스쿼드로 짠 최선 5덱의 시뮬 합, 나란히 보기, 사용 상위 25, 상위 40 스쿼드 표, 대리 모델 니케 가치 | `rankers_S*.json` · `seasons.json` |

- **니케와 속성은 글자 없이 그림으로만** 보여 준다(툴팁도 없음). 니케 = 얼굴, 그 오른쪽 위에 속성 육각형, 왼쪽 아래에 버스트 단계 문양.
  보스는 그림 + 이름. 그림은 [아래](#그림)처럼 nikke-analysis에서 받아 둔 것이다. 화면 낭독기용 대체 글(`alt`)에만 이름이 들어간다.
- 지표(N25 · D4 · V_top · V_r1 · V_pack · 주력 · 더 맞는 보스 · 판단)는 `analyze22.py`를 **그대로 불러 쓴다.** 정의를 여기서 다시 쓰지 않는다.
- 아직 없는 결과 파일은 「계산 전」으로 둔다. 작업 세션이 결과를 main에 올리면 다음 배포에서 채워진다.
- 시뮬은 하지 않는다. 평가기도 필요 없다(`numpy`만).
- 나중 과제: 여러 컨트롤이 겹칠 때 어느 것을 먼저 적용하는지(평가기의 우선순위 로직)도 보여 주기([로드맵](../docs/ROADMAP.md)).

## 만들기 · 로컬에서 보기

```bash
python web/build.py --out _site
```

```bash
python -m http.server -d _site 8000
```

`_site/`는 커밋하지 않는다(`.gitignore`). 테스트: `python -m unittest tests.test_web`.

## 배포

[`.github/workflows/pages.yml`](../.github/workflows/pages.yml)이 main push(`web/` · `experiments/` · 워크플로 변경) 때마다
`web/build.py`로 만들어 GitHub Pages에 올린다. Actions 탭에서 손으로 돌릴 수도 있다(`workflow_dispatch`).

처음 한 번 레포 설정이 필요하다.

1. Settings → General → Danger Zone → Change visibility → **Public**
2. Settings → Pages → Build and deployment → Source: **GitHub Actions**

레포가 비공개인 동안 워크플로는 실패하지 않고 건너뛴다.

## 그림

[Jgaram/nikke-analysis](https://github.com/Jgaram/nikke-analysis)의 그림을 **화면에 나오는 것만** `web/icons/`에 복사해 커밋해 둔다.
빌드는 외부에 기대지 않는다. 어느 커밋에서 받았는지는 `icons.json`의 `source`에 남는다.

| 폴더 | 내용 | nikke-analysis 출처 |
|---|---|---|
| `icons/units/<번호>.webp` | 니케 얼굴 128px | `data/assets/icons/units/` — 이름 → 번호는 `data/processed/roster.csv`(`name_ko` → `unit_id`) |
| `icons/bosses/<그림 이름>.webp` | 시즌 보스 그림 256px | `data/assets/icons/bosses/` — 시즌 → 그림은 `data/processed/soloraid_seasons.csv`(`boss_image`) |
| `icons/elements/<속성>.png` | 속성 육각형(색 있음) | `data/assets/icons/elements/` |
| `icons/bursts/<단계>.png` | 버스트 단계 문양(한 색, 글자색으로 칠함) | `data/assets/icons/bursts/` |
| `icons/icons.json` | 이름 → 얼굴 번호 · 속성(스킬로 더해진 속성 포함) · 버스트, 시즌 → 보스 그림, 받은 커밋 | 위 두 CSV |

새 시즌 · 실험 결과로 처음 나오는 니케가 생기면 `build.py`가 「얼굴 그림 없는 니케」를 알려 주고 `tests.test_web`이 실패한다.
그때 nikke-analysis를 받아 다시 가져온다(안 쓰게 된 얼굴 · 보스 그림은 지운다).

```bash
git clone --depth 1 https://github.com/Jgaram/nikke-analysis ../nikke-analysis
```

```bash
python web/sync_icons.py --analysis ../nikke-analysis
```

게임 이름과 그림의 권리는 SHIFT UP · Level Infinite에 있다(nikke-analysis README 「라이선스」). 사이트 꼬리말에도 적는다.

## 파일

| 파일 | 역할 |
|---|---|
| `build.py` | run_log → `data.json`, 정적 파일 · `icons/` 복사 |
| `sync_icons.py` | nikke-analysis → `icons/`(화면에 나오는 니케 · 시즌만) |
| `index.html` · `style.css` · `app.js` | 화면. 외부 라이브러리 · CDN 없음. 밝게 · 어둡게(시스템 설정 또는 오른쪽 위 버튼) |
