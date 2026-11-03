# 현황판 사이트 (`web/`)

레포의 탐색 로직이 시즌마다 **어떤 5덱 구성을 내놓는지 사람이 눈으로 확인**하려고 만든 정적 사이트다. 레포 소유자가 보는 용도이며,
지금은 [실험 36](../experiments/36_season_refresh/README.md)(최근 10시즌 S33~S42 현황판 다시 계산 — 지금 평가기 nikke-calc-rs `8bc51a2`,
실험 32 · 35에서 정한 절차, 코어 없음 최선 5덱의 컨트롤 · 장비 옵션 · 큐브 후처리)을 보여 준다.
그 전에는 [실험 31](../experiments/31_recent_seasons/README.md)(같은 10시즌, 옛 평가기 · 후처리 없음)을 보였다 — 그 화면은 `cfa2356`(실험 36으로 바꾸기 전 main)의 `web/`에 있다.
2026-11-01 사용자 결정으로 실험 22(랭커 대조 8시즌) 화면을 실험 31로 바꿨다. 실험 22 화면은 `c5531e1`(바꾸기 직전 main)의 `web/`에 있다.

주소: <https://jgaram.github.io/nikke-opt/> (레포 공개 + Pages 설정 뒤)

## 보여 주는 것

출처는 따로 적지 않으면 결과 폴더 `experiments/36_season_refresh/`, 시즌 자료 `seasons.json`은 계속 `experiments/31_recent_seasons/seasons.json`이다.

| 칸 | 내용 | 출처 |
|---|---|---|
| 한눈에 | 진행(완료 시즌 / 10) · 탐색 판(A) · 시뮬 합(이 실험에서 새로 돈 수, 나머지는 실험 32 기록 옮김) · 후처리 끝난 시즌 수와 5덱 합 사전 → 최종 오른 비율(시즌 중앙) · 97% 이상 큰 분류 수 · N25 · V_top(시즌 중앙). 시즌 10개 표(보스 · 기간 · 속성 → 약점 · 풀 · 애장품 끔 · 큰 분류 비율 · 세부 분류 수 · 랭커 대표 5덱과 가장 가까운 큰 분류 · **후처리 5덱 합**(최종 · 오른 비율 · 사전, 코어 30 보기에서는 「코어 없음만」)) | `seasons.json` · `analysis.json` · `run_log/S??/post.json` |
| 시즌 조건 | 보스 그림 · 기간 · 속성 → 약점 · 풀 · 새 니케 · 애장품 끔 · 날짜 경계로 뺀 니케 · 애장품 | `seasons.json` |
| 큰 분류 | 대표끼리 J ≤ 0.2인 5덱(A = 최선). 앞 3개는 상자, 나머지는 더보기. 상자마다 대표 5×5 격자(얼굴 아래 니케별 딜) · 다른 대표와의 J · 바꿀 니케 수 · 랭커 대표와의 J | `analysis.json` · `run_log/S??/members.json` |
| 세부 분류 | 대표에서 덱 1~2개만 바꾼 5덱(J ≥ 0.5, 최선의 97% 이상). 3개 + 더보기 20개. 줄 = 바뀐 덱 · 빠짐 → 들어옴 · 덱 사이 옮김 · 최선 대비 · J, 펴면 5덱 격자(바뀐 덱 칠함) | `analysis.json` |
| **후처리 뒤 최선 5덱**(코어 없음만) | 5덱 합 단계(사전 → 컨트롤 + 큐브 → 옵션 일괄 → 옵션 탐색 → 최종)와 5덱 격자. 줄 머리 = 최종 값 · 사전 대비 오른 비율 · 사전 값, 얼굴 아래 = 그 니케의 장비 옵션 12줄 배분(「우4 공4 크확2 크뎀2」, 우 = 우월 코드 대미지)과 기본(렐릭 베어)이 아닌 큐브의 짧은 이름. 줄 아래를 펴면 덱의 단계별 값과 최종 컨트롤 · 큐브 선택지(니케 얼굴 + 축 + 값). 큰 분류 A와 같은 5덱인지 적는다. post.json이 없으면 「계산 중」(끝난 덱 수만). 코어 30 보기에서는 「코어 없음만」 | `run_log/S??/post.json`(없으면 `analysis.json` 줄의 `post`) · `run_log/S??/post/S??-?.json`(끝난 덱 수) |
| 그 시즌 랭커 | N25 · D4 · V_top · V_r1 · V_pack(우리 A 기준), 랭커 대표 5덱 · 1위 5덱 격자(우리 A에 없는 니케는 점선)와 큰 분류마다의 J, 사용 상위 25(✓ = A에도 있음), 우리만 · 랭커만, 상위 40 스쿼드 | `seasons.json` · `run_log/S??/rankers.json` · `analysis.json` |
| 시뮬 비용 | 부분별(사전 계산 시드 둘 · 끝 탐침 · 코어 30 재평가 · 덱별 니케 딜 · 랭커 덱 · 후처리) 평가 수 · 시뮬 · 시간, 옮겨 쓴 부분(새 시뮬 0) · 건너뛴 부분, 평가기 | `run_log/S??/part_*.json` |

- **값의 기준이 둘이다.** 지도 · 분류 · 랭커 대조 · 니케별 딜은 사전 계산 값(장비 옵션 8줄 · Lv10 기본 스펙, 기본 레이어),
  후처리는 12줄 · Lv11 옵션 + 컨트롤 + 큐브다(실험 36 README §절차). 후처리 칸 머리에 이 안내를 한 줄 적는다. 코어 30은 후처리하지 않는다.
- 보스 조건은 위쪽 단추로 **코어 없음 · 코어 30px**를 바꾼다(한눈에 표와 시즌 상세가 함께 바뀐다). 주소 `#S40-core30`.
- **니케와 속성은 글자 없이 그림으로만** 보여 준다. 니케 = 얼굴, 그 오른쪽 위에 속성 육각형, 왼쪽 아래에 버스트 단계 문양, 오른쪽 아래 `N` = 직전 시즌 뒤 새 니케.
  후처리 선택지 라벨(`민트:reload:C0.1_dry`, `squad:camera:아니스 : 스타`, `squad:tactic:버충=민트`, `목단:cube:렐릭 어설트 큐브`)도 니케 부분은 얼굴로 바꿔 보인다.
- 분류 · 지표는 `run36.py analyze`(= run31 analyze 모양 + `procedure`)가 만든 `analysis.json`을, 후처리 값은 `post.json`을 **그대로 옮긴다.** 정의를 여기서 다시 쓰지 않는다.
  화면용으로 더하는 것은 세부 분류 새 덱의 자리 맞춤(바뀐 덱 번호 ↔ 새 덱, 겹침 최대) · 덱 사이 옮긴 니케,
  후처리 덱의 니케별 배분 · 큐브(최종 선택지에 큐브가 없으면 기본 큐브) · 선택지 라벨 펼치기 · 큰 분류 A와 같은 5덱인지뿐이다.
- 아직 없는 결과는 「계산 전」, 부분 기록만 있으면 「실행 중」, 후처리는 post.json이 생길 때까지 「계산 중」으로 둔다. analyze를 돌려 `analysis.json`이 main에 올라오면 다음 배포에서 채워진다.
- 시뮬은 하지 않는다. 평가기 · numpy도 필요 없다(실험 모듈을 불러오지 않는다).

## 만들기 · 로컬에서 보기

```bash
python web/build.py --out _site
```

```bash
python -m http.server -d _site 8000
```

- `_site/`는 커밋하지 않는다(`.gitignore`). 테스트: `python -m unittest tests.test_web`(실험 36 모양 기록을 임시 폴더에 지어 결과 · 후처리가 있는 경우도 시험한다).
- 다른 폴더의 결과로 미리 보기: `python web/build.py --out _site --exp <analysis.json · run_log가 있는 폴더>`(시즌 자료는 늘 실험 31의 `seasons.json`).

## 배포

[`.github/workflows/pages.yml`](../.github/workflows/pages.yml)이 main push(`web/` · `experiments/` · 워크플로 변경) 때마다
`web/build.py`로 만들어 GitHub Pages에 올린다. Actions 탭에서 손으로 돌릴 수도 있다(`workflow_dispatch`).

처음 한 번 레포 설정이 필요하다.

1. Settings → General → Danger Zone → Change visibility → **Public**
2. Settings → Pages → Build and deployment → Source: **GitHub Actions**

레포가 비공개인 동안 워크플로는 실패하지 않고 건너뛴다.

## 그림

[Jgaram/nikke-analysis](https://github.com/Jgaram/nikke-analysis)의 그림을 `web/icons/`에 복사해 커밋해 둔다. 빌드는 외부에 기대지 않는다.
받는 것은 **화면에 나오는 시즌의 보스 그림과, 10시즌 풀 전원(174명)의 얼굴**이다 — 실험 결과가 들어와 새 니케가 화면에 나와도 다시 받지 않게.
어느 커밋에서 받았는지는 `icons.json`의 `source`에 남는다.

| 폴더 | 내용 | nikke-analysis 출처 |
|---|---|---|
| `icons/units/<번호>.webp` | 니케 얼굴 128px | `data/assets/icons/units/` — 이름 → 번호는 `data/processed/roster.csv`(`name_ko` → `unit_id`) |
| `icons/bosses/<그림 이름>.webp` | 시즌 보스 그림 256px | `data/assets/icons/bosses/` — 시즌 → 그림은 `data/processed/soloraid_seasons.csv`(`boss_image`) |
| `icons/elements/<속성>.png` | 속성 육각형(색 있음) | `data/assets/icons/elements/` |
| `icons/bursts/<단계>.png` | 버스트 단계 문양(한 색, 글자색으로 칠함) | `data/assets/icons/bursts/` |
| `icons/icons.json` | 이름 → 얼굴 번호 · 속성(스킬로 더해진 속성 포함) · 버스트, 시즌 → 보스 그림, 받은 커밋 | 위 두 CSV |

시즌이 바뀌어 그림 없는 니케가 생기면 `build.py`가 「얼굴 그림 없는 니케」를 알려 주고 `tests.test_web`이 실패한다.
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
| `build.py` | `seasons.json`(실험 31) · `analysis.json` · run_log(`part_*` · `members` · `rankers` · `post`)(실험 36) → `data.json`, 정적 파일 · `icons/` 복사 |
| `sync_icons.py` | nikke-analysis → `icons/`(화면에 나오는 시즌 · 10시즌 풀 니케) |
| `index.html` · `style.css` · `app.js` | 화면. 외부 라이브러리 · CDN 없음. 밝게 · 어둡게(시스템 설정 또는 오른쪽 위 버튼) |
