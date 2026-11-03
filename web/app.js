/* nikke-opt 현황판(실험 36 · 최근 10시즌 현황판 다시 계산) — data.json(web/build.py가 만든다)을 읽어 그린다. 외부 라이브러리 없음. */
'use strict';
(() => {
  const BOSSES = ['nocore', 'core30'];
  const BOSS_LABEL = { nocore: '코어 없음', core30: '코어 30px' };
  const EL_KO = { Electric: '전격', Fire: '작열', Iron: '철갑', Water: '수냉', Wind: '풍압' };
  const ARM_KO = { A: 'A — 시드 2개 합치기 · 레이어 켬', B: 'B — 시드 2개 합치기', W: 'W — 넓게 찾기' };
  // 후처리 선택지(실험 6 메뉴 축 · 값) — 화면용 이름. 모르는 값은 그대로 보인다
  const AXIS_KO = { click: '좌클릭', reload: '장전컨', cover: '엄폐컨', cancel: '탄충 취소', burst: '버스트', camera: '카메라', tactic: '택틱', cube: '큐브' };
  const VALUE_KO = { auto: '자동', tap: '톡톡이', hold_own_fb: '풀버스트 홀드', 'hold_own_fb+tap': '풀버스트 홀드 + 톡톡이',
    hold_judge: '풀버스트 후 홀드 판정', on: '켬', off: '끔', pattern_off: '패턴 끔' };
  const POST_STEPS = [['pre', '사전 계산'], ['ctrl', '컨트롤 + 큐브'], ['E0', '옵션 일괄(우코 · 공 · 장탄 4줄씩)'], ['O', '옵션 탐색'], ['C2', '컨트롤 + 큐브 다시'], ['final', '최종']];
  // 버스트 단계 → nikke-analysis 버스트 문양(파일 · 가로 · 세로 px, 세로 13 기준)
  const BURST_GLYPH = { 1: ['i', 6, 13], 2: ['ii', 11, 13], 3: ['iii', 14, 13], A: ['i-ii-iii', 14, 13] };
  const FACE_BADGE = { lg: { el: 17, burst: 10 }, md: { el: 14, burst: 8 } };   // 얼굴 크기별 속성 · 버스트 표시 크기(sm은 없음)

  let D = null;
  const state = { season: null, boss: 'nocore' };

  // ------------------------------------------------------------ DOM
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === 'class') e.setAttribute('class', v);
        else if (k === 'text') e.textContent = v;
        else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
        else e.setAttribute(k, v === true ? '' : v);
      }
    }
    for (const c of kids.flat(Infinity)) {
      if (c == null || c === false) continue;
      e.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return e;
  }
  const $ = (s) => document.querySelector(s);

  // ------------------------------------------------------------ 숫자
  const nf1 = new Intl.NumberFormat('ko-KR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const nf0 = new Intl.NumberFormat('ko-KR');
  const eok = (v) => (v == null ? '—' : `${nf1.format(v)}억`);
  const pct = (v, d = 1) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`);
  const int = (v) => (v == null ? '—' : nf0.format(Math.round(v)));
  const jf = (v) => (v == null ? '—' : v.toFixed(2));
  const dur = (s) => {
    if (s == null) return '—';
    const m = Math.round(s / 60);
    return m < 60 ? `${m}분` : `${Math.floor(m / 60)}시간 ${m % 60}분`;
  };
  const gain = (a, b) => (a && b != null ? `${b >= a ? '+' : '−'}${Math.abs((b / a - 1) * 100).toFixed(1)}%` : '—');
  const day = (iso) => (iso ? iso.slice(0, 10) : '—');
  const md = (iso) => (iso ? iso.slice(5, 10) : '—');
  const median = (xs) => {
    const a = xs.filter((x) => x != null).sort((p, q) => p - q);
    if (!a.length) return null;
    const m = a.length >> 1;
    return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
  };

  // ------------------------------------------------------------ 데이터 접근
  const seasonOf = (s) => D.seasons.find((x) => x.season === s);
  const nk = (n) => D.nikke[n] || {};
  const runOf = (S, b = state.boss) => S.by_boss[b];
  const doneRuns = (b = state.boss) => D.seasons.map((S) => runOf(S, b)).filter((r) => r.status === 'done');
  const clsLetter = (c) => (c.name || '').slice(0, 1);

  // ------------------------------------------------------------ 그림(니케 · 속성은 글자 없이 그림으로만)
  function elIcon(code, size = 16) {
    if (!code) return null;
    return h('img', { class: 'el', src: `icons/elements/${code.toLowerCase()}.png`, alt: EL_KO[code] || code,
      width: size, height: Math.round((size * 73) / 63), decoding: 'async' });
  }
  function burstGlyph(b, height) {
    const g = BURST_GLYPH[b];
    if (!g) return null;
    const url = `url("icons/bursts/${g[0]}.png")`;
    const w = Math.round((g[1] * height) / g[2]);
    return h('span', { class: 'glyph', role: 'img', 'aria-label': b === 'A' ? '버스트 전 단계' : `버스트 ${b}단계`,
      style: `width:${w}px;height:${height}px;-webkit-mask-image:${url};mask-image:${url}` });
  }
  function missingFace(n) {
    return h('span', { class: 'face-img face-missing', role: 'img', 'aria-label': n, text: '?' });
  }
  // 니케 얼굴. size: lg(덱) · md(목록) · sm(표 · 줄 안). lg · md는 오른쪽 위에 속성, 왼쪽 아래에 버스트 단계를 붙인다.
  function face(n, size = 'md', o = {}) {
    const info = nk(n);
    const cls = ['face', `f-${size}`, o.diff && 'diff', o.dim && 'dim'].filter(Boolean).join(' ');
    const img = info.img
      ? h('img', { class: 'face-img', src: info.img, alt: n, loading: 'lazy', decoding: 'async',
        onerror: (e) => e.target.replaceWith(missingFace(n)) })
      : missingFace(n);
    const badge = FACE_BADGE[size];
    return h('span', { class: cls }, img,
      badge && info.el && info.el.length ? h('span', { class: 'els' }, info.el.map((e) => elIcon(e, badge.el))) : null,
      badge && info.b ? h('span', { class: 'bst' }, burstGlyph(info.b, badge.burst)) : null,
      o.check ? h('span', { class: 'chk', 'aria-label': '우리 최선(A)에도 있음', text: '✓' }) : null,
      o.isNew ? h('span', { class: 'nw', 'aria-label': '새 니케', text: 'N' }) : null);
  }
  function faces(list, size = 'sm', o = {}) {
    return h('ul', { class: `faces faces-${size}` }, (list || []).map((n) => h('li', null, face(n, size, {
      dim: o.dimSet ? o.dimSet.has(n) : false, check: o.checkSet ? o.checkSet.has(n) : false,
    }))));
  }
  function bossImg(S, cls = 'boss-thumb') {
    return S.boss_img ? h('img', { class: cls, src: S.boss_img, alt: S.boss_name, decoding: 'async' }) : null;
  }
  // 보스 속성 → 약점, 그림으로
  function elPair(S, size = 16) {
    return h('span', { class: 'el-pair' }, elIcon(S.element, size), h('span', { class: 'arrow', 'aria-label': '약점', text: '→' }), elIcon(S.weak, size));
  }
  function badge(name, sm) {
    const l = (name || '').slice(0, 1);
    return h('span', { class: `cls-badge${sm ? ' sm' : ''} c-${'ABC'.includes(l) ? l : 'X'}`, text: name });
  }

  // ------------------------------------------------------------ 공통 조각
  function tile(label, value, note) {
    return h('div', { class: 'tile' }, h('div', { class: 'label', text: label }),
      h('div', { class: 'value' }, value), note ? h('div', { class: 'note' }, note) : null);
  }
  function tableWrap(t) { return h('div', { class: 'tbl-wrap' }, t); }
  function card(id, title, sub, ...kids) {
    return h('section', { class: 'card', id }, h('h3', { text: title }), sub ? h('p', { class: 'sub' }, sub) : null, ...kids);
  }
  function lazyDetails(cls, summary, fill, open) {
    const d = h('details', { class: cls, open: open || null }, summary, h('div', { class: 'lazy' }));
    const go = () => { if (d.open && !d.dataset.filled) { d.dataset.filled = '1'; d.lastChild.replaceChildren(...fill()); } };
    d.addEventListener('toggle', go);
    if (open) requestAnimationFrame(go);
    return d;
  }
  // 5덱 격자: 행 = 덱(1~5), 열 = 배치 순서. 5덱 묶음 하나가 격자 하나다.
  // o: title · note · size(lg = 큰 얼굴 + 니케별 딜, md = 작은 얼굴) · otherSet(없으면 점선) · newSet · hl(바뀐 덱 번호 Set, 1부터)
  //    lab(d, i) = 줄 머리 대신 · under(d, n) = 얼굴 아래(니케별 딜) 대신 · after(d, i) = 줄 아래에 붙일 것 · cls = 격자에 더할 class
  function fiveGrid(set, o = {}) {
    const size = o.size || 'lg';
    const head = h('figcaption', { class: 'fg-head' },
      o.badge ? badge(o.badge) : null,
      h('span', { class: 'fg-title', text: o.title }),
      h('span', { class: 'fg-total', text: set ? eok(set.total) : '—' }),
      o.note ? h('span', { class: 'fg-note' }, o.note) : null);
    if (!set) {
      return h('figure', { class: `fgrid fg-${size}` }, head, h('div', { class: 'empty', text: o.empty || '계산 전' }));
    }
    const rows = set.decks.map((d, i) => {
      const dmg = Object.fromEntries((d.members || []).map(([n, v]) => [n, v]));
      const chg = !!(o.hl && o.hl.has(i + 1));
      const row = h('div', { class: `fg-row${chg ? ' chg' : ''}`, role: 'row' },
        h('div', { class: 'fg-lab', role: 'rowheader' }, o.lab ? o.lab(d, i) : [
          h('span', { class: 'fg-no', text: `${i + 1}` }),
          h('span', { class: 'fg-val', text: eok(d.value) }),
          chg ? h('span', { class: 'fg-chg', text: '바뀜' }) : null]),
        d.order.map((n) => h('div', { class: 'fg-cell', role: 'cell' },
          face(n, size, { diff: !!(o.otherSet && !o.otherSet.has(n)), isNew: !!(o.newSet && o.newSet.has(n)) }),
          o.under ? o.under(d, n)
            : size === 'lg' && d.members ? h('span', { class: 'dmg', text: dmg[n] == null ? '' : eok(dmg[n]) }) : null)));
      return o.after ? h('div', { class: 'fg-group', role: 'rowgroup' }, row, o.after(d, i)) : row;
    });
    return h('figure', { class: `fgrid fg-${size}${o.ours ? ' ours' : ''}${o.cls ? ` ${o.cls}` : ''}` }, head,
      h('div', { class: 'fg-body', role: 'table', 'aria-label': `${o.title} 5덱` }, rows));
  }
  function bossSeg(onPick) {
    return h('div', { class: 'seg', role: 'group', 'aria-label': '보스 조건' }, BOSSES.map((b) => h('button', {
      type: 'button', 'aria-pressed': String(b === state.boss), onclick: () => onPick(b),
    }, BOSS_LABEL[b])));
  }

  // ------------------------------------------------------------ 머리 · 꼬리
  function renderTheme() {
    const btn = $('#theme');
    const names = { auto: '자동', light: '밝게', dark: '어둡게' };
    let mode = 'auto';
    try { mode = localStorage.getItem('nikke-opt-theme') || 'auto'; } catch (e) { /* 저장소 없음 */ }
    const apply = () => {
      if (mode === 'auto') document.documentElement.removeAttribute('data-theme');
      else document.documentElement.setAttribute('data-theme', mode);
      btn.textContent = `테마: ${names[mode]}`;
    };
    apply();
    btn.addEventListener('click', () => {
      mode = mode === 'auto' ? 'light' : mode === 'light' ? 'dark' : 'auto';
      try { localStorage.setItem('nikke-opt-theme', mode); } catch (e) { /* 저장소 없음 */ }
      apply();
    });
  }
  function renderFoot() {
    const src = D.source || {};
    const E = D.experiment;
    $('#foot').replaceChildren(
      h('p', null, '데이터: ', src.short ? h('a', { href: `${D.repo}/commit/${src.commit}`, text: src.short }) : '—',
        ` (${day(src.date)}) · 사이트 빌드 ${D.built_at.replace('T', ' ').replace('+00:00', ' UTC')}`),
      h('p', null, `평가기: ${E.evaluator || '—'} · 시즌 · 랭커 자료: `,
        h('a', { href: E.ranker_repo, text: 'Jgaram/nikke-analysis' }), E.analysis_repo_commit ? ` ${E.analysis_repo_commit}` : '',
        '의 enikk 원자료(시즌마다 6개 서버 상위 50명 × 5덱) · 출시일 · 애장품 날짜'),
      h('p', null, '실험 문서: ', h('a', { href: E.readme, text: `실험 ${E.id} README` }), ' · 앞선 계산(옛 평가기): ',
        h('a', { href: E.exp31_readme, text: '실험 31' }), ' · 절차: ', h('a', { href: E.exp30_readme, text: '실험 30' }),
        ' · ', h('a', { href: E.exp32_readme, text: '실험 32' }), '(판) · ', h('a', { href: E.exp35_readme, text: '실험 35' }),
        '(장비 옵션 후처리) · 분류 정의: ', h('a', { href: E.exp28_readme, text: '실험 28' }),
        ' · 코드: ', h('a', { href: D.repo, text: 'Jgaram/nikke-opt' }), ' · 이 페이지는 main에 결과가 올라올 때마다 GitHub Actions가 다시 만듭니다.'),
      iconCredit(),
    );
  }
  function iconCredit() {
    const s = (D.icons && D.icons.source) || {};
    const at = s.repo && s.commit ? h('a', { href: `${s.repo}/tree/${s.commit}/data/assets/icons`, text: `Jgaram/nikke-analysis ${s.commit.slice(0, 7)}` }) : 'Jgaram/nikke-analysis';
    return h('p', null, '니케 얼굴 · 속성 · 버스트 · 보스 그림: ', at,
      '(blablalink · enikk에서 받은 것). 게임 이름 · 그림의 권리는 SHIFT UP · Level Infinite에 있습니다.');
  }

  // ------------------------------------------------------------ 한눈에
  function renderSummary(root) {
    root.append(h('section', { id: 'summary' }, h('h2', { text: '한눈에' }), h('div', { id: 'summary-body' })));
    renderSummaryBody();
  }
  function renderSummaryBody() {
    const P = D.progress;
    const runs = doneRuns();
    const arm = D.experiment.arm;
    const pending = P.done === 0;
    const posts = D.seasons.map((S) => S.post).filter((p) => p.status === 'done' && p.total);
    const tiles = h('div', { class: 'tiles' },
      tile('진행', h('span', null, `${P.done}`, h('small', { text: ` / ${P.total} 시즌` })),
        P.started > P.done ? `실행 중 ${P.started - P.done}시즌` : pending ? '실행 전' : null),
      tile('탐색 판', arm ? arm : '—', arm ? ARM_KO[arm] || arm : '결과 전'),
      tile('시뮬', int(P.sims), P.sims_new < P.sims ? `10시즌 합 · 이 실험에서 새로 ${int(P.sims_new)}(나머지는 실험 32 기록 옮김)` : '10시즌 합(부분별 기록)'),
      tile('후처리', h('span', null, `${P.post}`, h('small', { text: ` / ${P.total} 시즌` })),
        posts.length ? `5덱 합 사전 → 최종 시즌 중앙 ${gain(1, median(posts.map((p) => p.total.final / p.total.pre)))} · 코어 없음` : '계산 중 · 코어 없음 최선 5덱'),
      tile('97% 이상 큰 분류', runs.length ? `${median(runs.map((r) => r.n97))}개` : '—', `시즌 중앙 · ${BOSS_LABEL[state.boss]}`),
      tile('N25', runs.length ? `${median(runs.map((r) => r.metrics.N25))}` : '—', '우리 A 25명 중 랭커 상위 25명 · 시즌 중앙'),
      ratioTiles());
    $('#summary-body').replaceChildren(
      h('p', { class: 'sub' }, '시즌마다 그 시즌의 ', h('b', { text: '니케 풀 · 보스 속성 · 그때 있던 애장품' }),
        '만 주고(랭커 정보 없이) 찾은 5덱을 ', h('b', { text: '큰 분류' }), '(덱 나누기가 크게 다른 안)와 ',
        h('b', { text: '세부 분류' }), '(덱 1~2개만 바꾼 안)로 나눠, 그 시즌 랭커 덱과 나란히 봅니다. 코어 없음 최선 5덱은 ',
        h('b', { text: '컨트롤 · 장비 옵션 · 큐브까지 후처리' }), '한 값도 봅니다. 줄을 누르면 시즌 상세로 갑니다.'),
      tiles,
      h('div', { class: 'picker' }, bossSeg((b) => { state.boss = b; renderSummaryBody(); selectSeason(state.season, b); })),
      overviewTable());
  }
  function ratioTiles() {
    const ok = D.seasons.filter((S) => runOf(S).status === 'done');
    return RPOST_SETS.map(([k, lab]) => {
      const rs = ok.map((S) => rankerRatio(S, runOf(S), k)).filter((r) => r.v != null);
      const post = rs.length > 0 && rs.every((r) => r.post);
      const mixed = !post && rs.some((r) => r.post);
      return tile(`${lab.replace(' 5덱', '')} ÷ 우리 A`, rs.length ? pct(median(rs.map((r) => r.v))) : '—',
        rs.length ? `${rs.length}시즌 중앙 · ${post ? '후처리 뒤끼리' : mixed ? '후처리 뒤 · 사전 섞임' : '사전 값끼리'}` : '계산 전');
    });
  }
  function overviewTable() {
    const head = h('tr', null, ['시즌', '기간', '속성 → 약점', '풀', '애장품 끔', '큰 분류 ≥97%', 'A · B · C (최선 대비)', '세부 분류 A · B · C', 'N25', '랭커 ÷ 우리 A', '랭커 대표 ≈', '후처리 5덱 합'].map((t, i) =>
      h('th', { class: i >= 3 && i !== 6 && i !== 10 ? 'r' : null, text: t })));
    const rows = D.seasons.map((S) => {
      const R = runOf(S);
      const done = R.status === 'done';
      const cl = done ? R.classes.slice(0, 3) : [];
      const near = done && R.classes.length ? nearest(R.metrics.J_top) : null;
      return h('tr', { class: `clickable${S.season === state.season ? ' sel' : ''}`, 'data-s': S.season,
        onclick: () => { selectSeason(S.season, state.boss); $('#detail').scrollIntoView({ behavior: 'smooth' }); } },
      h('td', null, h('div', { class: 'boss-cell' }, bossImg(S), h('div', null, h('b', { text: `S${S.season}` }), h('div', { class: 'small muted', text: S.boss_name })))),
      h('td', { class: 'small nowrap', text: `${day(S.start)} ~ ${md(S.end)}` }),
      h('td', null, elPair(S)),
      h('td', { class: 'r' }, `${S.pool}`, S.new.length ? h('span', { class: 'muted small', text: ` +${S.new.length}` }) : null),
      h('td', { class: 'r', text: S.favorite0.length ? `${S.favorite0.length}명` : '—' }),
      done ? h('td', { class: 'r', text: `${R.n97}` }) : h('td', { class: 'r muted', text: S.parts && Object.keys(S.parts).length ? '실행 중' : '계산 전' }),
      h('td', { class: 'small nowrap' }, done ? cl.map((c, i) => [i ? ' · ' : '', badge(c.name, true), ` ${pct(c.ratio)}`]) : ''),
      h('td', { class: 'r', text: done ? cl.map((c) => `${int(c.subs_count)}${c.capped ? '+' : ''}`).join(' · ') : '' }),
      h('td', { class: 'r', text: done ? `${R.metrics.N25}` : '' }),
      ratioCell(S, R, done),
      h('td', { class: 'small nowrap' }, near ? [badge(near[0], true), ` J ${jf(near[1])}`] : ''),
      postCell(S));
    });
    return h('div', { class: 'card', id: 'overview' }, h('h3', { text: `시즌 10개 · ${BOSS_LABEL[state.boss]}` }),
      h('p', { class: 'sub small' }, '큰 분류 ≥97% = 최선의 97% 이상인 큰 분류 수. 세부 분류 400+ = 400개에서 자름. ',
        'N25 = 우리 A 25명 중 그 시즌 랭커 사용 상위 25명. 랭커 ÷ 우리 A = 랭커 대표 · 1위 · 스쿼드로 짠 최선 5덱의 계산 합 ÷ 우리 A — 코어 없음은 둘 다 같은 후처리 뒤, 코어 30은 사전 값끼리. 랭커 대표 ≈ = 랭커 대표 5덱과 J가 가장 큰 큰 분류. ',
        '후처리 5덱 합 = 코어 없음 최선 5덱의 사전 계산 → 컨트롤 · 장비 옵션 · 큐브 후처리 뒤.'),
      tableWrap(h('table', { class: 'wide' }, h('thead', null, head), h('tbody', null, rows))));
  }
  function ratioCell(S, R, done) {
    if (!done) return h('td', { class: 'r' });
    const post = postBoth(S);
    const line = (k, lab) => {
      const r = rankerRatio(S, R, k);
      return h('div', null, `${lab} ${pct(r.v)}${post && !r.post ? '(사전)' : ''}`);
    };
    return h('td', { class: 'r small nowrap' }, line('top', '대표'), line('r1', '1위'), line('pack', '최선'),
      h('div', { class: 'muted', text: post ? '후처리 뒤' : '사전' }));
  }
  const nearest = (jmap) => Object.entries(jmap || {}).sort((a, b) => b[1] - a[1])[0] || null;
  function postCell(S) {
    const p = S.post;
    if (state.boss !== 'nocore') return h('td', { class: 'r small muted', text: '코어 없음만' });
    if (p.status !== 'done' || !p.total) return h('td', { class: 'r small muted', text: p.decks_done ? `계산 중 ${p.decks_done}/5` : '계산 중' });
    return h('td', { class: 'r' }, h('div', null, h('b', { text: eok(p.total.final) }), h('span', { class: 'gain', text: ` ${gain(p.total.pre, p.total.final)}` })),
      h('div', { class: 'small muted', text: `사전 ${nf1.format(p.total.pre)}` }));
  }

  // ------------------------------------------------------------ 시즌 상세
  function renderDetailShell(root) {
    root.append(h('section', { id: 'detail' }, h('h2', { text: '시즌 상세' }), h('div', { id: 'picker' }), h('div', { id: 'season-body' })));
  }
  function selectSeason(s, b) {
    if (!seasonOf(s)) s = D.seasons[D.seasons.length - 1].season;
    state.season = s;
    if (b) state.boss = b;
    try { history.replaceState(null, '', `#S${s}-${state.boss}`); } catch (e) { /* file:// 등 */ }
    renderPicker();
    renderDetail();
    const t = document.querySelector('#overview tbody');
    if (t) for (const tr of t.children) tr.classList.toggle('sel', Number(tr.dataset.s) === s);
  }
  function renderPicker() {
    const chips = h('div', { class: 'chips', role: 'group', 'aria-label': '시즌' }, D.seasons.map((S) => h('button', {
      class: 'chip-btn season-chip', type: 'button', 'aria-pressed': String(S.season === state.season),
      onclick: () => selectSeason(S.season, state.boss),
    }, bossImg(S, 'chip-boss'), `S${S.season}`, runOf(S).status === 'done' ? null : h('span', { class: 'st', text: '·' }))));
    $('#picker').replaceChildren(h('div', { class: 'picker' }, chips,
      bossSeg((b) => { selectSeason(state.season, b); renderSummaryBody(); })));
  }
  function renderDetail() {
    const S = seasonOf(state.season);
    const R = runOf(S);
    $('#season-body').replaceChildren(seasonHero(S), classesCard(S, R), postCard(S), rankerCard(S, R), costCard(S));
  }

  function seasonHero(S) {
    const facts = [
      h('span', { class: 'fact' }, elPair(S, 18), h('span', { class: 'muted small', text: `${EL_KO[S.element]} 보스 · 약점 ${EL_KO[S.weak]}` })),
      h('span', { class: 'fact' }, h('span', { class: 'muted', text: '풀' }), h('b', { text: `${S.pool}명` })),
      h('span', { class: 'fact' }, h('span', { class: 'muted', text: '랭커' }), `${int(S.rankers.players)}명 × 5덱`),
    ];
    const rows = [];
    if (S.new.length) rows.push(h('div', { class: 'cond' }, h('span', { class: 'cond-k', text: '새 니케(직전 시즌 뒤)' }), faces(S.new, 'md')));
    rows.push(h('div', { class: 'cond' }, h('span', { class: 'cond-k', text: '애장품 끔(그때 없던 애장품)' }),
      S.favorite0.length ? faces(S.favorite0, 'md') : h('span', { class: 'muted small', text: '없음 — 풀의 애장품이 모두 나와 있던 시즌' })));
    if (S.excluded_nikke.length || S.excluded_treasure.length) {
      rows.push(h('div', { class: 'cond' }, h('span', { class: 'cond-k', text: '날짜 경계로 뺀 것' }),
        h('div', null,
          S.excluded_nikke.length ? h('div', { class: 'cond-line' }, h('span', { class: 'small muted', text: '니케 ' }), faces(S.excluded_nikke, 'md')) : null,
          S.excluded_treasure.length ? h('div', { class: 'cond-line' }, h('span', { class: 'small muted', text: '애장품 ' }), faces(S.excluded_treasure, 'md')) : null,
          h('p', { class: 'small muted', text: '시즌이 끝나는 날 점검 뒤에 들어온 것(실험 22 규칙은 그 시즌에 넣었다). 그 시즌 랭커 사용 0회.' }))));
    }
    return h('div', { class: 'card season-hero' },
      h('div', { class: 'boss-hero' }, bossImg(S, 'boss-img'),
        h('div', { class: 'boss-text' },
          h('p', { class: 'eyebrow', text: `S${S.season} · ${day(S.start)} ~ ${day(S.end)}` }),
          h('h3', { class: 'boss-name', text: S.boss_name }),
          h('div', { class: 'boss-facts' }, facts))),
      h('div', { class: 'conds' }, rows));
  }

  // 큰 분류: 앞 D.show.classes개는 펼친 상자, 나머지는 더보기
  function classesCard(S, R) {
    const sub = h('span', null, h('b', { text: '큰 분류' }), ' = 대표끼리 쌍 자카드 J ≤ 0.2(덱 나누기가 크게 다른 5덱), A = 최선. ',
      h('b', { text: '세부 분류' }), ' = 대표에서 덱 1~2개만 바꾼 5덱(대표와 J ≥ 0.5, 최선의 97% 이상). 값은 사전 계산 값(평가기 기본 레이어 180초 딜, 장비 옵션 8줄 · Lv10 기본 스펙)입니다.');
    if (R.status !== 'done') {
      return card('classes', `큰 분류 · ${BOSS_LABEL[state.boss]}`, sub,
        h('div', { class: 'empty', text: Object.keys(S.parts || {}).length ? '실행 중 — 끝나면 채워집니다.' : '계산 전' }));
    }
    const show = D.show.classes;
    const head = h('p', { class: 'small muted' }, `최선(A) ${eok(R.best)} · 큰 분류 ${R.classes.length}개(최선의 95% 이상) 중 97% 이상 ${R.n97}개 · 기록 구성 ${int(R.comps)}개`,
      R.map_exact ? '' : ' · 고르기 제한 시간에 걸린 대표가 있어 정확해가 아닐 수 있음');
    const boxes = R.classes.slice(0, show).map((c, i) => classBox(S, R, c, i === 0));
    const rest = R.classes.slice(show);
    const more = rest.length ? lazyDetails('more', h('summary', { text: `더보기 — 큰 분류 ${rest.length}개 더` }), () => rest.map((c) => classBox(S, R, c, false))) : null;
    return card('classes', `큰 분류 · ${BOSS_LABEL[state.boss]}`, sub, head, boxes, more);
  }
  const subsCount = (c) => (c.capped ? `${int(c.subs_count)}개 이상` : `${int(c.subs_count)}개`);
  function classBox(S, R, c, open) {
    const vs = Object.entries(c.vs || {}).slice(0, 4).map(([o, v]) => h('span', { class: 'cls-j' }, badge(o, true), ` J ${jf(v.J)} · ${v.moves}명`));
    const jt = (R.metrics.J_top || {})[c.name];
    const sum = h('summary', { class: 'cls-sum' },
      badge(c.name),
      h('span', { class: 'cls-ratio', text: pct(c.ratio) }),
      h('span', { class: 'cls-total', text: eok(c.total) }),
      h('span', { class: 'cls-vs' }, vs),
      jt != null ? h('span', { class: 'cls-note', text: `랭커 대표와 J ${jf(jt)}` }) : null,
      h('span', { class: 'cls-subs', text: `세부 분류 ${subsCount(c)}` }));
    return lazyDetails('cls', sum, () => classInner(S, R, c), open);
  }
  function classInner(S, R, c) {
    const show = D.show.subs;
    const subs = c.subs || [];
    const repSet = new Set(c.decks.flatMap((d) => d.order));
    const newSet = new Set(S.new);
    const out = [h('div', { class: 'rep-grid' }, fiveGrid({ total: c.total, decks: c.decks }, {
      title: `대표 5덱`, badge: c.name, size: 'lg', ours: c.name === 'A', newSet,
      note: `최선 대비 ${pct(c.ratio)}${c.exact === false ? ' · 고르기 제한 시간에 걸림' : ''}`,
    }))];
    out.push(h('h4', { class: 'subs-h' }, `세부 분류 ${subsCount(c)}`,
      c.subs_count ? h('span', { class: 'muted small', text: ` · 덱 하나만 바뀐 것 ${int(c.subs_1deck)}개` }) : null));
    if (!subs.length) {
      out.push(h('p', { class: 'small muted', text: '최선의 97% 이상이면서 이 대표에서 덱 1~2개만 바꾼 5덱이 기록에 없습니다.' }));
      return out;
    }
    out.push(h('p', { class: 'small muted face-key', text: '줄을 누르면 5덱이 펼쳐집니다. 칠한 줄 = 바뀐 덱 · 점선 테두리 = 대표에 없던 니케 · 오른쪽 J = 이 대표 · 다른 큰 분류와의 J.' }));
    out.push(h('div', { class: 'subs' }, subs.slice(0, show).map((s, i) => subItem(R, c, s, i + 1, repSet))));
    const more = subs.slice(show);
    if (more.length) {
      out.push(lazyDetails('more', h('summary', { text: `더보기 — ${more.length}개 더 (합 순)` }), () => [
        h('div', { class: 'subs' }, more.map((s, i) => subItem(R, c, s, show + i + 1, repSet))),
        c.more_left ? h('p', { class: 'small muted more-left', text: `외 ${int(c.more_left)}개${c.capped ? ' 이상(400개에서 자름)' : ''}` }) : null]));
    } else if (c.more_left) {
      out.push(h('p', { class: 'small muted', text: `외 ${int(c.more_left)}개` }));
    }
    return out;
  }
  // 세부 분류 한 줄: 바뀐 덱 · 빠짐 → 들어옴(덱 사이 옮김) · 최선 대비 · J. 펴면 5덱 격자
  function subItem(R, c, s, rank, repSet) {
    const change = [];
    if (s.out.length || s.in.length) {
      change.push(h('span', { class: 'swap' }, faces(s.out, 'sm'), h('span', { class: 'arrow', 'aria-label': '대신', text: '→' }), faces(s.in, 'sm')));
    }
    const inSet = new Set(s.in);
    const mv = (s.moved || []).filter(([n]) => !inSet.has(n));
    if (mv.length) {
      change.push(h('span', { class: 'moved' }, mv.map(([n, a, b]) => h('span', { class: 'mv' }, face(n, 'sm'),
        h('span', { class: 'mv-d', 'aria-label': `${a}덱에서 ${b}덱으로`, text: `${a}→${b}` })))));
    }
    const other = Object.entries(s.J_other || {}).filter(([, j]) => j >= 0.2).map(([o, j]) => h('span', { class: 'sj' }, badge(o, true), ` ${jf(j)}`));
    const sum = h('summary', { class: 'sub-sum' },
      h('span', { class: 'sub-no', text: `${rank}` }),
      h('span', { class: 'sub-decks' }, s.changed.map((n) => h('span', { class: 'tag deck-tag', text: `${n}덱` }))),
      h('span', { class: 'sub-change' }, change),
      h('span', { class: 'sub-nums' },
        h('b', { class: 'sub-ratio', text: pct(s.total / R.best) }),
        h('span', { class: 'sj' }, badge(c.name, true), ` ${jf(s.J)}`),
        other));
    return lazyDetails('sub-item', sum, () => {
      const decks = c.decks.map((x) => ({ order: x.order, value: x.value }));
      for (const sl of s.slots) decks[sl.no - 1] = { order: sl.order, value: sl.value };
      return [fiveGrid({ total: s.total, decks }, {
        title: `${c.name} 세부 분류 ${rank}`, size: 'md', hl: new Set(s.changed), otherSet: repSet,
        note: `최선 대비 ${pct(s.total / R.best)} · 대표 ${c.name}와 J ${jf(s.J)} · 옮기거나 바꿀 니케 ${s.moves}명`,
      })];
    });
  }

  // 후처리 뒤 최선 5덱(코어 없음만): 줄 머리 = 최종 값 · 사전 대비 · 사전 값, 얼굴 아래 = 장비 옵션 배분 · 큐브, 줄 아래를 펴면 선택지 · 단계별 값
  const BASIS = '값의 기준이 다릅니다 — 지도 · 분류 · 랭커 대조는 사전 계산 값(장비 옵션 8줄 · Lv10), 후처리는 12줄 · Lv11 옵션 + 컨트롤 + 큐브입니다.';
  function valueKo(v) {
    if (VALUE_KO[v]) return VALUE_KO[v];
    let m = /^delay([\d.]+)$/.exec(v);
    if (m) return `딜레이 ${m[1]}초`;
    m = /^wait([\d.]+)$/.exec(v);
    if (m) return `자기 쿨 대기 ${m[1]}초`;
    return v.startsWith('pattern=') ? `패턴 ${v.slice(8)}` : v;
  }
  function gearTag(g) {
    if (!g) return null;
    return h('span', { class: 'gear' },
      h('span', { class: 'alloc', title: g.alloc ? `장비 옵션 ${g.alloc}` : null }, (g.alloc_short || []).map((t) => h('span', { text: t }))),
      g.cube_short ? h('span', { class: 'cube-tag', title: g.cube, text: g.cube_short }) : null);
  }
  function postMore(d) {
    const cubes = d.order.filter((n) => d.gear[n] && d.gear[n].cube_short);
    const n = d.choices.length + cubes.length;
    return lazyDetails('post-more', h('summary', { text: n ? `최종 선택지 ${n}개 · 단계별 값` : '단계별 값 · 바꾼 선택지 없음' }), () => {
      const won = d.C2 != null && d.O != null && d.C2 > d.O ? 'C2' : 'O';     // 최종 = 옵션 탐색 · 컨트롤 다시 중 높은 것
      const path = h('ol', { class: 'post-path' }, POST_STEPS.filter(([k]) => d[k] != null).map(([k, lab]) =>
        h('li', { class: k === 'final' ? 'fin' : k === won ? 'won' : null }, h('span', { class: 'muted', text: lab }), ' ', h('b', { text: eok(d[k]) }))));
      const list = h('ul', { class: 'choice-list' },
        d.choices.map((c) => h('li', null, c.who ? face(c.who, 'sm') : h('span', { class: 'tag', text: '스쿼드' }),
          h('span', { class: 'ax', text: AXIS_KO[c.axis] || c.axis }), c.value ? h('span', { class: 'tag', text: valueKo(c.value) }) : null,
          c.target ? face(c.target, 'sm') : null)),
        cubes.map((x) => h('li', null, face(x, 'sm'), h('span', { class: 'ax', text: '큐브' }), h('span', { class: 'tag', text: d.gear[x].cube }))));
      return [path, n ? list : h('p', { class: 'small muted', text: '컨트롤 · 큐브는 기본 레이어 그대로(바꾼 선택 없음).' })];
    });
  }
  function postGrid(set, title, S, o = {}) {
    return fiveGrid(set, {
      title, size: 'lg', cls: 'fg-post', newSet: new Set(S.new), ...o,
      lab: (d, i) => [h('span', { class: 'fg-no', text: `${i + 1}` }), h('span', { class: 'fg-val', text: eok(d.final) }),
        h('span', { class: 'gain', text: gain(d.pre, d.final) }), h('span', { class: 'fg-pre', text: `사전 ${d.pre == null ? '—' : nf1.format(d.pre)}` })],
      under: (d, n) => gearTag(d.gear[n]),
      after: (d) => [postMore(d), timelineMore(d, S)],
    });
  }

  // ------------------------------------------------------------ 컨트롤 타임라인(trace36.py · nikke_opt/timeline.py)
  // 후처리 최종 선택지로 한 번 더 돈 전투의 키 입력. 줄 = 입력(풀버스트 · 버스트 Ⅰ Ⅱ Ⅲ · 카메라 · 마우스 · Shift · Space), 색 = 배치 자리(카메라 키 Z~B)
  const CAM_KEYS = ['Z', 'X', 'C', 'V', 'B'];
  const CTRL_KO = { tap: '좌클릭 톡톡이', hold: '좌클릭 홀드', cover: 'Shift 엄폐', all: 'Space 전체 엄폐' };
  const WHY_KO = { '엄폐 시작(장전컨)': '장전컨(엄폐로 재장전)', '엄폐 시작(버스트 엄폐컨)': '버스트 엄폐컨', always: '상시', burst_charge: '버충(게이지 채우기)', own_full_burst: '자기 풀버스트 동안' };
  const TL_ZOOM = 8;   // 크게 보기: 1초 = 8px
  const SVGNS = 'http://www.w3.org/2000/svg';
  const traceCache = {};
  function traceSeason(s) {
    if (!traceCache[s]) {
      traceCache[s] = fetch(`traces/S${String(s).padStart(2, '0')}.json`).then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
    }
    return traceCache[s];
  }
  function sv(tag, attrs, ...kids) {
    const e = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v != null) e.setAttribute(k, v);
    for (const c of kids.flat(Infinity)) if (c != null) e.append(c.nodeType ? c : document.createTextNode(String(c)));
    return e;
  }
  const secs = (t) => `${t.toFixed(t < 10 ? 2 : 1)}초`;
  function timelineMore(d, S) {
    if (!d.trace) return null;
    return lazyDetails('post-more tl-more', h('summary', { text: '컨트롤 타임라인 — 언제 무슨 키를 누르나' }), () => {
      const box = h('div', { class: 'tl' }, h('div', { class: 'small muted', text: '불러오는 중…' }));
      traceSeason(S.season).then((all) => {
        const tl = all[d.id];
        if (!tl) { box.replaceChildren(h('div', { class: 'empty', text: '이 덱의 타임라인을 찾지 못했습니다.' })); return; }
        const v = timelineView(tl);
        box.replaceChildren(...v.nodes);
        v.draw();
      });
      return [box];
    });
  }
  function timelineView(tl) {
    const sq = tl.squad;
    const dur = tl.dur || 180;
    const clicks = tl.c.filter((c) => c[3] === 'tap' || c[3] === 'hold');
    const covers = tl.c.filter((c) => c[3] === 'cover');
    const alls = tl.c.filter((c) => c[3] === 'all');
    const AXIS = 16;
    const lanes = [['fb', '풀버스트', 12], ['b1', 1, 24], ['b2', 2, 24], ['b3', 3, 24], ['cam', '카메라', 32],
      ['click', '마우스', 24], ['cover', 'Shift', 24]];
    if (alls.length) lanes.push(['all', 'Space', 24]);
    const top = {};
    let y = AXIS;
    for (const [k, , hgt] of lanes) { top[k] = y; y += hgt; }
    const H = y + 2;
    const H_OF = Object.fromEntries(lanes.map(([k, , hgt]) => [k, hgt]));
    const color = (i) => (i >= 0 && i < 5 ? `var(--s${i + 1})` : 'var(--axis)');

    const keys = h('div', { class: 'tl-keys' }, h('span', { class: 'muted', text: '배치 · 카메라 키' }),
      sq.map((n, i) => h('span', { class: 'tl-key-item', style: `--sc:${color(i)}` }, h('kbd', { text: CAM_KEYS[i] }), face(n, 'sm'))));
    const nSwitch = Math.max(0, tl.cam.length - 1);
    const summary = h('p', { class: 'small tl-sum' },
      `풀버스트 ${tl.fb.length}회 · 버스트 ${tl.b.length}번 · 카메라 전환 ${nSwitch}번 · 좌클릭 ${clicks.length}구간 · Shift 엄폐 ${covers.length}번`
      + (alls.length ? ` · Space ${alls.length}번` : ' · Space 안 씀'));
    let mode = null;   // 처음 그릴 때 정한다: 좁아서 전체 보기의 1초가 2.5px보다 작으면 크게 보기
    const seg = h('div', { class: 'seg tl-zoom', role: 'group', 'aria-label': '타임라인 크기' });
    const labels = h('div', { class: 'tl-labels', 'aria-hidden': 'true' }, h('div', { class: 'tl-lab', style: `height:${AXIS}px` }),
      lanes.map(([k, lab, hgt]) => h('div', { class: 'tl-lab', style: `height:${hgt}px` },
        typeof lab === 'number' ? [lab === 1 ? h('span', { class: 'tl-lab-name', text: '버스트' }) : null, burstGlyph(String(lab), 11)] : lab)));
    const scroll = h('div', { class: 'tl-scroll' });
    const info = h('div', { class: 'tl-info', 'aria-live': 'polite' }, h('span', { class: 'muted', text: '그림의 표시를 누르면 시각 · 니케 · 조작이 나옵니다.' }));
    const marks = [];   // 누르면 보일 설명(인덱스 = data-i)
    const note = h('p', { class: 'small muted' },
      '후처리 최종 선택지로 한 번 더 돈 전투입니다(총딜이 기록 값과 같음). 음영 = 풀버스트. 버스트 = 그 단계를 누른 니케(Ⅰ · Ⅱ · Ⅲ 줄). ',
      '카메라 = 그 시각에 보고 있는 니케 — 색이 바뀌는 곳이 키 입력(Z~B = 배치 1~5번). 엄폐 · 클릭은 보고 있는 니케에만 걸려 카메라가 그 니케로 옮겨 갑니다. ',
      '마우스 = 좌클릭(채움 = 홀드, 빗금 = 톡톡이). Shift = 엄폐(장전컨은 엄폐로 재장전을 거는 짧은 엄폐).');

    function pick(i, el) {
      scroll.querySelectorAll('.tl-on').forEach((x) => x.classList.remove('tl-on'));
      if (el) el.classList.add('tl-on');
      info.replaceChildren(...marks[i]());
    }
    function draw() {
      const avail = Math.max(120, scroll.clientWidth - 2);
      if (!mode) mode = avail / dur < 2.5 ? 'zoom' : 'fit';
      const px = mode === 'fit' ? avail / dur : TL_ZOOM;
      const W = Math.round(dur * px);
      const X = (t) => Math.max(0, Math.min(W, t * px));
      marks.length = 0;
      const uid = `tl${Math.random().toString(36).slice(2, 8)}`;
      const g = [];
      const defs = sv('defs', null,
        sv('clipPath', { id: `${uid}c`, clipPathUnits: 'objectBoundingBox' }, sv('rect', { width: 1, height: 1, rx: 0.22 })),
        sv('pattern', { id: `${uid}h`, width: 5, height: 5, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' },
          sv('rect', { width: 2.2, height: 5, class: 'tl-hatch' })));
      // 축 · 눈금 · 풀버스트 음영
      const step = [10, 30, 60].find((x) => px * x >= 44) || 90;
      for (let t = 0; t <= dur + 1e-9; t += step) {
        g.push(sv('line', { x1: X(t), x2: X(t), y1: AXIS - 3, y2: H, class: 'tl-grid' }));
        if (t > 0 && X(dur) - X(t) < 40 && t < dur - 1e-9) continue;   // 끝 눈금 글자와 겹치면 생략
        g.push(sv('text', { x: Math.min(W - 2, X(t) + 2), y: AXIS - 5, class: 'tl-tick', 'text-anchor': t >= dur - 1e-9 ? 'end' : 'start' }, `${t}초`));
      }
      if (dur % step > 1e-6) {
        g.push(sv('text', { x: W - 2, y: AXIS - 5, class: 'tl-tick', 'text-anchor': 'end' }, `${dur}초`));
      }
      tl.fb.forEach(([t0, t1]) => g.push(sv('rect', { x: X(t0), y: AXIS, width: Math.max(1, X(t1) - X(t0)), height: H - AXIS, class: 'tl-fbband' })));
      for (const [k] of lanes.slice(1)) g.push(sv('line', { x1: 0, x2: W, y1: top[k], y2: top[k], class: 'tl-lane' }));
      const hit = (x, w, yy, hh, i) => sv('rect', { x: x + w / 2 - Math.max(w, 12) / 2, y: yy, width: Math.max(w, 12), height: hh, class: 'tl-hit', 'data-i': i });
      const faceAt = (n, x, yy, sz, slot) => {
        const img = nk(n).img;
        return [img ? sv('image', { href: img, x, y: yy, width: sz, height: sz, 'clip-path': `url(#${uid}c)`, preserveAspectRatio: 'xMidYMid slice' }) : null,
          sv('rect', { x, y: yy, width: sz, height: sz, rx: sz * 0.22, class: 'tl-ring', style: `stroke:${color(slot)}` })];
      };
      // 풀버스트 줄
      tl.fb.forEach(([t0, t1]) => {
        const i = marks.push(() => [h('b', { text: `${secs(t0)} ~ ${secs(t1)}` }), ` 풀버스트 ${(t1 - t0).toFixed(1)}초`]) - 1;
        const x = X(t0); const w = Math.max(2, X(t1) - x);
        g.push(sv('rect', { x, y: top.fb + 3, width: w, height: H_OF.fb - 6, rx: 2, class: 'tl-fb' }), hit(x, w, top.fb, H_OF.fb, i));
      });
      // 버스트 Ⅰ Ⅱ Ⅲ — 누른 니케 얼굴(키 글자 대신)
      tl.b.forEach(([t, st, slot, re]) => {
        const k = `b${st}`;
        if (top[k] == null) return;
        const n = sq[slot];
        const sz = mode === 'fit' ? Math.min(H_OF[k] - 4, Math.round(px * 11)) : H_OF[k] - 4;   // 전체 보기에서 사이클끼리 덜 겹치게
        const dot = sz < 14;                                                                     // 얼굴이 너무 작으면 자리 색 점
        const x = Math.max(0, Math.min(W - sz, X(t) - sz / 2));
        const i = marks.push(() => [h('b', { text: secs(t) }), ` 버스트 ${st}단계${re ? '(재진입)' : ''} · `, n ? face(n, 'sm') : '스쿼드 밖']) - 1;
        const yy = top[k] + (H_OF[k] - sz) / 2;
        g.push(sv('g', { class: `tl-burst${re ? ' tl-re' : ''}` }, n && !dot ? faceAt(n, x, yy, sz, slot)
          : sv('circle', { cx: X(t), cy: top[k] + H_OF[k] / 2, r: 4.5, class: 'tl-dot', style: `fill:${color(n ? slot : -1)}` })),
        hit(dot ? X(t) - 4.5 : x, dot ? 9 : sz, top[k], H_OF[k], i));
      });
      // 카메라 — 구간 = 보고 있는 니케, 바뀐 곳 = 키 입력(위에 키 글자, 겹치면 생략)
      // 구간 사이 경계선 없음. 아주 짧은 구간(장전컨 1프레임 등)은 3px로 넓혀 긴 구간 위에 그린다
      let lastKey = -1e9;
      const camLong = []; const camShort = [];
      tl.cam.forEach(([t0, slot], j) => {
        const t1 = j + 1 < tl.cam.length ? tl.cam[j + 1][0] : dur;
        const x0 = X(t0); const x1 = X(t1);
        const short = x1 - x0 < 4;
        const w = short ? Math.max(3, x1 - x0) : x1 - x0;   // 이웃 구간과 틈 없이 붙인다(색으로 구분)
        const x = short ? Math.min(W - 3, x0) : x0;
        const yy = top.cam + 11; const hh = H_OF.cam - 13;
        const n = sq[slot];
        const i = marks.push(() => [h('b', { text: `${secs(t0)} ~ ${secs(t1)}` }), ' 카메라 ', n ? face(n, 'sm') : '아무도 안 봄',
          n ? h('kbd', { class: 'tl-kbd', text: CAM_KEYS[slot] }) : null, j ? ' (이 시각에 키 입력)' : ' (전투 시작 카메라)']) - 1;
        const out = short ? camShort : camLong;
        out.push(sv('rect', { x, y: yy, width: w, height: hh, class: 'tl-cam', style: `fill:${color(slot)}` }));
        if (n && !short && w >= hh + 4) out.push(...faceAt(n, x0 + 2, yy + 1, hh - 2, slot));
        if (j && slot >= 0 && x0 - lastKey >= 11) {
          out.push(sv('text', { x: x0, y: top.cam + 9, class: 'tl-keytxt', 'text-anchor': 'middle' }, CAM_KEYS[slot]));
          lastKey = x0;
        }
        out.push(hit(x, w, top.cam, H_OF.cam, i));
      });
      g.push(...camLong, ...camShort);
      // 마우스 · Shift · Space — 조작 구간(누른 니케 색, 너무 짧아도 3px)
      const spans = (rows, k) => rows.forEach(([t0, t1, slot, kind, why]) => {
        const n = sq[slot];
        const x = X(t0); const w = Math.max(3, X(t1) - x);
        const yy = top[k] + 3; const hh = H_OF[k] - 6;
        const i = marks.push(() => [h('b', { text: `${secs(t0)} ~ ${secs(t1)}` }), ` ${CTRL_KO[kind] || kind} · `, n ? face(n, 'sm') : '—',
          why ? h('span', { class: 'muted', text: ` · ${WHY_KO[why] || why}` }) : null]) - 1;
        g.push(sv('rect', { x, y: yy, width: w, height: hh, rx: 2, class: 'tl-seg', style: `fill:${color(slot)}` }));
        if (kind === 'tap') g.push(sv('rect', { x, y: yy, width: w, height: hh, rx: 2, fill: `url(#${uid}h)` }));
        if (n && w >= hh + 4) g.push(...faceAt(n, x + 2, yy + 1, hh - 2, slot));
        g.push(hit(x, w, top[k], H_OF[k], i));
      });
      spans(clicks, 'click');
      spans(covers, 'cover');
      for (const [k, rows] of [['click', clicks], ['cover', covers]]) {
        if (!rows.length) g.push(sv('text', { x: 6, y: top[k] + H_OF[k] / 2 + 4, class: 'tl-tick' }, '안 씀'));
      }
      if (alls.length) spans(alls, 'all');
      const svg = sv('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img',
        'aria-label': `컨트롤 타임라인 ${dur}초: ${summary.textContent}` }, defs, g);
      svg.addEventListener('click', (e) => {
        const t = e.target.closest('[data-i]');
        if (t) pick(Number(t.getAttribute('data-i')), t);
      });
      scroll.replaceChildren(svg);
      seg.replaceChildren(...[['fit', '전체 보기'], ['zoom', '크게 보기']].map(([m, lab]) => h('button', {
        type: 'button', 'aria-pressed': String(m === mode), onclick: () => { mode = m; draw(); } }, lab)));
    }
    let rz = 0;
    window.addEventListener('resize', () => {
      if (mode !== 'fit' || !scroll.isConnected) return;
      cancelAnimationFrame(rz);
      rz = requestAnimationFrame(draw);
    });
    return { nodes: [keys, summary, h('div', { class: 'tl-bar' }, seg), h('div', { class: 'tl-chart' }, labels, scroll), info, note], draw };
  }
  // 같은 후처리를 한 랭커 두 묶음(rpost36.py): 대표 5덱 · 랭커 스쿼드로 짠 최선 5덱. 값 = 최종 합 · 우리 A 최종 대비
  const RPOST_SETS = [['top', '랭커 대표 5덱', '상위 300명이 5덱을 그대로 가장 많이 쓴 묶음'],
    ['r1', '랭커 1위 5덱', '그 시즌 1위가 쓴 5덱'],
    ['pack', '랭커 스쿼드로 짠 최선 5덱', '랭커 덱(대표 · 1위 · 상위 40 스쿼드)을 사전 값으로 겹치지 않게 묶은 합 최대']];
  // 랭커 묶음 ÷ 우리 A: 코어 없음이고 랭커 후처리가 끝났으면 후처리 뒤끼리, 아니면 사전 값끼리(지표 V_top · V_r1 · V_pack)
  const PRE_KEY = { top: 'V_top', r1: 'V_r1', pack: 'V_pack' };
  function postBoth(S) {
    return state.boss === 'nocore' && S.rpost && S.rpost.status === 'done' && S.post.status === 'done' && S.post.total;
  }
  function rankerRatio(S, R, k) {
    if (postBoth(S)) {
      const x = S.rpost.sets[k];
      if (x) return { v: x.total.final / S.post.total.final, post: true };
    }
    const m = R && R.status === 'done' ? R.metrics || {} : {};
    return { v: m[PRE_KEY[k]], post: false };
  }
  function rankerPost(S, T) {
    const RP = S.rpost || {};
    const head = h('h4', { text: '같은 후처리를 한 랭커 덱과 비교' });
    if (RP.status !== 'done') return h('div', { class: 'post-cmp' }, head, h('div', { class: 'empty', text: '랭커 덱 후처리: 계산 전 — 끝나면 채워집니다.' }));
    const tiles = h('div', { class: 'tiles post-steps' }, tile('우리 A', eok(T.final), `사전 ${eok(T.pre)}`),
      RPOST_SETS.map(([k, lab]) => {
        const x = RP.sets[k];
        return tile(lab, x ? eok(x.total.final) : '—',
          x ? `우리 A 대비 ${pct(x.total.final / T.final)} · 사전 ${eok(x.total.pre)}(우리 A 대비 ${pct(x.total.pre / T.pre)})` : '지원하지 않는 니케가 있어 계산하지 않음');
      }));
    return h('div', { class: 'post-cmp' }, head,
      h('p', { class: 'small muted', text: '랭커 덱에도 우리 A와 똑같이 ① 컨트롤 + 큐브 → ② 장비 옵션 12줄 → ③ 컨트롤 + 큐브 다시(각 400평가)를 했습니다. '
        + '랭커의 실전 육성 · 컨트롤이 아니라 「같은 조건으로 다듬었을 때」의 값입니다. 덱별 배분 · 큐브는 아래 「그 시즌 랭커」 칸.' }), tiles);
  }
  function postCard(S) {
    const title = '후처리 뒤 최선 5덱';
    if (state.boss !== 'nocore') {
      return card('post', title, null, h('div', { class: 'empty' }, '코어 없음만 — 코어 30은 지도만 만들고 후처리하지 않았습니다. ',
        h('button', { class: 'link-btn', type: 'button', onclick: () => { selectSeason(state.season, 'nocore'); renderSummaryBody(); } }, '코어 없음 보기')));
    }
    const P = S.post;
    const sub = h('span', null, h('b', { text: BASIS }), ' 코어 없음 사전 계산 최선 5덱마다 ① 컨트롤 + 큐브 → ② 장비 옵션 12줄 배분 → ',
      '③ ②의 배분 위에서 컨트롤 + 큐브 다시(각 400평가). 최종 = ② · ③ 중 높은 것.');
    if (P.status !== 'done') {
      return card('post', title, sub, h('div', { class: 'empty', text: P.decks_done ? `계산 중 — 5덱 중 ${P.decks_done}덱 끝남. 다 끝나면 채워집니다.` : '계산 중' }));
    }
    const T = P.total || {};
    const steps = h('div', { class: 'tiles post-steps' }, [['pre', '사전 계산'], ['ctrl', '컨트롤 + 큐브'], ['E0', '옵션 일괄'], ['O', '옵션 탐색'], ['final', '최종']].map(([k, lab]) =>
      tile(lab, eok(T[k]), k === 'pre' ? '5덱 합' : `사전 대비 ${gain(T.pre, T[k])}`)));
    const same = P.same_as_A === true ? ' · 큰 분류 A와 같은 5덱' : P.same_as_A === false ? ' · 큰 분류 A와 다른 5덱' : '';
    const grid = postGrid({ total: T.final, decks: P.decks }, '후처리 뒤 5덱', S, {
      ours: true, note: `사전 ${eok(T.pre)} → 최종 ${eok(T.final)} (${gain(T.pre, T.final)})${same}` });
    return card('post', title, sub, steps, h('div', { class: 'rep-grid' }, grid), rankerPost(S, T),
      h('p', { class: 'small muted face-key', text: '줄 머리 = 최종 값 · 사전 대비 · 사전 값. 얼굴 아래 = 장비 옵션 12줄 배분(우 = 우월 코드 대미지, 공 = 공격력, '
        + '장탄 = 최대 장탄 수, 크확 · 크뎀 = 크리티컬 확률 · 대미지, 차속 · 차뎀 = 차지 속도 · 대미지, 숫자 = 줄 수)과 기본(렐릭 베어)이 아닌 큐브. '
        + '줄 아래를 펴면 최종 컨트롤 · 큐브 선택지와 단계별 값.' }));
  }

  // 랭커: 대표 5덱 · 1위 5덱 격자(값은 같은 보스 조건으로 우리가 시뮬) + 지표 + 사용 상위 25
  function rankerCard(S, R) {
    const K = S.rankers;
    const A = R.status === 'done' && R.classes.length ? R.classes[0] : null;
    const aSet = A ? new Set(A.decks.flatMap((d) => d.order)) : null;
    const M = R.metrics || {};
    const jline = (jm) => (jm ? h('div', { class: 'jline small' }, '큰 분류와 J: ', Object.entries(jm).map(([o, j], i) => [i ? ' · ' : '', badge(o, true), ` ${jf(j)}`])) : null);
    const ratio = (set) => (A && set.total != null ? ` · 우리 A 대비 ${pct(set.total / A.total)}` : '');
    const sets = R.ranker_sets;
    const post = postBoth(S);
    const what = { top: `300명 중 ${K.top_five_count}명이 5덱을 그대로 씀`, r1: `${K.rank1_server} 서버 · 실전 ${eok(K.rank1_damage / 1e8)}(우리 계산과 크기 비교 불가)`,
      pack: '랭커 덱을 사전 값으로 겹치지 않게 묶은 합 최대' };
    const preSet = { top: sets.top_five, r1: sets.rank1 };
    const J = { top: M.J_top, r1: M.J_r1 };
    let grids;
    if (post) {
      const T = S.post.total;
      const aPost = new Set(S.post.decks.flatMap((d) => d.order));
      grids = h('div', { class: 'sets cmp' }, RPOST_SETS.map(([k, lab]) => {
        const x = S.rpost.sets[k];
        if (!x) {
          return h('div', null, fiveGrid(preSet[k] || null, { title: `${lab}(사전 값)`, size: 'lg', otherSet: aPost,
            empty: '계산 안 함', note: `${what[k]} · 지원하지 않는 니케가 있어 후처리하지 않음` }), jline(J[k]));
        }
        return h('div', null, postGrid({ total: x.total.final, decks: x.decks }, lab, S, { otherSet: aPost,
          note: `${what[k]} · 우리 A 대비 ${pct(x.total.final / T.final)}(후처리 뒤끼리) · 사전 ${eok(x.total.pre)}(${pct(x.total.pre / T.pre)})` }), jline(J[k]));
      }));
    } else {
      grids = h('div', { class: 'sets cmp' },
        h('div', null, fiveGrid(sets.top_five, { title: '랭커 대표 5덱', size: 'lg', otherSet: aSet,
          note: `${what.top}${ratio(sets.top_five)}${K.evaluated ? '' : ' · 값은 평가 전'}` }), jline(M.J_top)),
        h('div', null, fiveGrid(sets.rank1, { title: '랭커 1위 5덱', size: 'lg', otherSet: aSet,
          note: `${what.r1}${ratio(sets.rank1)}${K.evaluated ? '' : ' · 값은 평가 전'}` }), jline(M.J_r1)));
    }
    const rt = (k, lab) => {
      const r = rankerRatio(S, R, k);
      const pre = r.post && M[PRE_KEY[k]] != null ? ` · 사전 ${pct(M[PRE_KEY[k]])}` : '';
      return tile(`${lab} ÷ 우리 A`, pct(r.v), `${r.post ? '후처리 뒤끼리' : '사전 값끼리'}${pre}`);
    };
    const tiles = A ? h('div', { class: 'tiles' },
      tile('N25', `${M.N25}`, '우리 A 25명 중 랭커 사용 상위 25명'),
      tile('D4', `${M.D4}`, '우리 A 덱 중 랭커 상위 40 스쿼드와 4명 이상 같은 덱'),
      rt('top', '랭커 대표'), rt('r1', '랭커 1위'), rt('pack', '랭커 스쿼드 최선')) : null;
    const top = K.units.map(([n]) => n);
    const usage = h('div', null, h('h4', { text: '랭커 사용 상위 25' }),
      h('p', { class: 'small muted', text: aSet ? '✓ = 우리 A에도 있음. 격자의 점선 테두리 = 우리 A에 없는 니케.' : '우리 쪽은 계산 전입니다.' }),
      faces(top, 'md', { checkSet: aSet }),
      A ? h('div', { class: 'who' },
        h('div', null, h('h4', { text: `우리 A에만(${M.ours_only.length})` }), faces(M.ours_only, 'md')),
        h('div', null, h('h4', { text: `랭커 상위 25에만(${M.rankers_only.length})` }), faces(M.rankers_only, 'md'))) : null);
    const sq = h('details', null, h('summary', { text: `랭커 상위 40 스쿼드(가장 흔한 배치 순서, 서로 다른 스쿼드 ${int(K.distinct_squads)}개 중)` }),
      h('div', { class: 'inner' }, tableWrap(h('table', { class: 'mid' },
        h('thead', null, h('tr', null, ['#', '스쿼드', '쓴 덱 수', BOSS_LABEL[state.boss]].map((t, i) => h('th', { class: i >= 2 ? 'r' : null, text: t })))),
        h('tbody', null, K.squads.map((q, i) => h('tr', null, h('td', { class: 'small muted', text: `${i + 1}` }),
          h('td', null, faces(q.order, 'sm', { checkSet: aSet })), h('td', { class: 'r', text: int(q.count) }),
          h('td', { class: 'r', text: eok(q.values[state.boss]) }))))))));
    const sub = postBoth(S)
      ? h('span', null, h('b', { text: '랭커 덱 값 = 우리 A와 같은 후처리(① 컨트롤 + 큐브 → ② 장비 옵션 12줄 → ③ 컨트롤 + 큐브 다시) 뒤의 우리 계산값입니다.' }),
        ' 우리 A 대비 %도 후처리 뒤끼리입니다. 줄 머리의 「사전」 = 후처리 전 값. 랭커의 실전 육성 · 컨트롤과는 다릅니다. 아래 상위 40 스쿼드 표는 사전 값입니다.')
      : h('span', null, h('b', { text: '랭커 덱 값 = 같은 보스 조건 · 기본 스펙 · 기본 레이어로 우리가 계산한 사전 값입니다.' }),
        ` 우리 A 대비 %도 사전 값끼리입니다(${state.boss === 'nocore' ? '랭커 덱 후처리 계산 전' : '코어 30은 후처리하지 않음'}). 랭커의 실전 육성 · 컨트롤과는 다릅니다.`);
    return card('rankers', `그 시즌 랭커 · ${BOSS_LABEL[state.boss]}`, sub, tiles, grids, usage, sq);
  }

  function costCard(S) {
    const P = S.parts || {};
    const names = { B_s0: '사전 계산 시드 0', B_s1: '사전 계산 시드 1', end: '끝 탐침', core30: '코어 30(재평가 + 이어 찾기)',
      members: '덱별 니케 딜', rankers: '랭커 덱', post: '후처리(코어 없음 최선 5덱)', rpost: '랭커 덱 후처리(대표 · 스쿼드 최선)',
      trace: '컨트롤 타임라인(후처리 덱마다 1번 다시)' };
    const keys = Object.keys(names).filter((k) => P[k]);
    if (!keys.length) return card('cost', '시뮬 비용', null, h('div', { class: 'empty', text: '계산 전' }));
    const note = (x) => {
      const m = /experiments\/(\d+)_/.exec(x.copied_from || '');
      return x.copied_from ? `${m ? `실험 ${Number(m[1])}` : '앞 실험'} 기록 옮김(새 시뮬 0)` : x.skipped ? `건너뜀(판 ${x.skipped})` : '';
    };
    const sub = [`이 시즌 시뮬 ${int(S.sims_total)}회(부분별 기록 합)`,
      S.sims_new < S.sims_total ? `이 실험에서 새로 ${int(S.sims_new)}회` : null,
      S.arm ? `판 ${ARM_KO[S.arm] || S.arm}` : null,
      S.evaluators && S.evaluators.length ? `평가기 ${S.evaluators.join(' · ')}` : null].filter(Boolean).join(' · ');
    return card('cost', '시뮬 비용', sub,
      tableWrap(h('table', { class: 'plain' },
        h('thead', null, h('tr', null, ['부분', '평가', '시뮬', '시간', ''].map((t, i) => h('th', { class: i && i < 4 ? 'r' : null, text: t })))),
        h('tbody', null, keys.map((k) => h('tr', null, h('td', { text: names[k] }), h('td', { class: 'r', text: int(P[k].evals ?? P[k].requests) }),
          h('td', { class: 'r', text: int(P[k].sims) }), h('td', { class: 'r', text: dur(P[k].seconds) }),
          h('td', { class: 'small muted', text: note(P[k]) })))))));
  }

  // ------------------------------------------------------------ 읽는 법
  function renderAbout(root) {
    root.append(h('section', { id: 'about' }, h('h2', { text: '읽는 법' }), h('div', { class: 'card' },
      h('dl', { class: 'kv' },
        h('dt', { text: '조건' }), h('dd', null, '시즌마다 그 시즌 끝까지 나온 니케 전원 보유 · 기본 스펙(상). 그때 없던 애장품은 0단계(나머지 3단계). 보스 = 평가기 기본 적(방어력 31784, 패턴 · 파츠 없음) + 시즌 보스 속성. 180초 · 기대값 · 버스트 게이지 실누적.'),
        h('dt', { text: '날짜 경계' }), h('dd', null, '출시일 · 애장품 날짜가 날짜만 있으면 그날 점검 뒤로 봅니다. 시즌은 점검 날 04:59에 끝나므로 그날 들어온 니케 · 애장품은 그 시즌에 없습니다.'),
        h('dt', { text: '탐색' }), h('dd', null, '실험 31 B 판 그대로(실험 30 절차): 시드 2개(예산 12,500씩, 실제 약 11,000에서 끝남) 기록 합치기, 레이어 켬(실험 32 판정으로 판 A 유지). 랭커 정보는 쓰지 않습니다. S36 · S39 · S41 · S42의 사전 계산은 같은 평가기 · 같은 절차인 실험 32 R3 A 기록을 옮겨 씁니다.'),
        h('dt', { text: '사전 계산 값' }), h('dd', null, '평가기 기본 레이어(렐릭 베어 큐브, 니케별 기본 컨트롤), 장비 옵션 = 계산기 기본 스펙(8줄 · Lv10). 지도 · 큰 분류 · 세부 분류 · 랭커 대조 · 니케별 딜은 모두 이 값입니다.'),
        h('dt', { text: '후처리' }), h('dd', null, '코어 없음 최선 5덱마다 ① 컨트롤 + 큐브(실험 6 메뉴 + 평가기가 지원하는 큐브 전부 Lv15, 400평가) → ② 장비 옵션 12줄 · Lv11 배분 찾기(실험 35, 400) → ③ ②의 배분 위에서 컨트롤 + 큐브를 ①의 선택부터 다시(400). 최종 = ② · ③ 중 높은 것. 값의 기준이 사전 계산과 달라 따로 보입니다. 코어 30은 후처리하지 않습니다.'),
        h('dt', { text: '코어 30px' }), h('dd', null, '처음부터 따로 찾지 않고, 코어 없음 기록에서 고른 2,000개(큰 분류 대표 덱 + 대표 5덱의 덱 자리마다 바꿔 넣을 구성)를 코어 30으로 다시 평가한 뒤 그 위에서 2,000평가를 이어 찾습니다. 그 값으로 같은 분류를 만듭니다(실험 30 확인: 따로 찾은 최선 대비 S40 99.98% · S34 100.0%).'),
        h('dt', { text: 'J(쌍 자카드)' }), h('dd', null, '두 5덱에서 같은 덱에 묶인 니케 쌍이 얼마나 겹치는지(0~1). 덱 하나 통째 교체 0.67, 1명 교체 0.85, 맞교환 3번 0.35. 바꿀 니케 수 = 한쪽을 다른 쪽으로 만들 때 옮기거나 바꿀 니케 수.'),
        h('dt', { text: '큰 분류' }), h('dd', null, 'A = 기록의 최선 5덱. 다음 = 앞 대표 모두와 J ≤ 0.2인 겹치지 않는 5덱 중 합 최대. 최선의 95% 아래로 내려가면 멈춥니다(최대 10개).'),
        h('dt', { text: '세부 분류' }), h('dd', null, '대표에서 덱 1~2개만 바뀌고(나머지 그대로) 대표와 J ≥ 0.5, 합이 최선의 97% 이상인 5덱. 바뀐 덱이 서로 다른 것부터 3개를 보이고 나머지는 합 순 더보기(20개까지).'),
        h('dt', { text: '그림' }), h('dd', null, '니케 = 얼굴, 오른쪽 위 = 속성, 왼쪽 아래 = 버스트 단계, 오른쪽 아래 N = 직전 시즌 뒤 새 니케. 격자 숫자 = 덱 값, 얼굴 아래 = 니케별 딜(후처리 격자는 장비 옵션 배분 · 큐브).'),
        h('dt', { text: '한계' }), h('dd', null, '시뮬 안의 값입니다. 보스 패턴 · 파츠 · 실제 코어, 그 시점 밸런스 · 랭커 육성은 반영하지 않았습니다. 평가기 데이터 · 스킬은 지금 기준입니다(애장품만 그때로 껐습니다). 실험 31과는 평가기가 달라 값을 그대로 견주지 않습니다.')))));
  }

  // ------------------------------------------------------------ 시작
  function initialSelection() {
    const m = /^#S(\d+)-(nocore|core30)$/.exec(location.hash);
    if (m) return [Number(m[1]), m[2], true];
    return [D.seasons[D.seasons.length - 1].season, 'nocore', false];
  }
  async function main() {
    renderTheme();
    const app = $('#app');
    try {
      const r = await fetch('data.json', { cache: 'no-cache' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      D = await r.json();
    } catch (e) {
      app.replaceChildren(h('p', { class: 'loading', text: `data.json을 읽지 못했습니다: ${e.message}` }));
      return;
    }
    const [s, b, scroll] = initialSelection();
    state.season = s;
    state.boss = b;
    app.replaceChildren();
    renderSummary(app);
    renderDetailShell(app);
    renderAbout(app);
    renderFoot();
    selectSeason(s, b);
    if (scroll) requestAnimationFrame(() => document.getElementById('detail').scrollIntoView());
  }
  main();
})();
