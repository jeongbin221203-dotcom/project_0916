// 카테고리 필터
const chips = document.querySelectorAll('.chip');
const cards = document.querySelectorAll('#cardGrid .card');
const voicePick = document.getElementById('voicePick');
const grid = document.getElementById('cardGrid');

// 특정 필터에서만 보이는 카드(data-only)는 처음 화면에서 숨김
cards.forEach((card) => {
  if (card.dataset.only) card.classList.add('hidden');
});

chips.forEach((chip) => {
  chip.addEventListener('click', () => {
    chips.forEach((c) => c.classList.remove('active'));
    chip.classList.add('active');
    const filter = chip.dataset.filter;
    cards.forEach((card) => {
      const { cat, only } = card.dataset;
      let show = filter === 'all' || cat === filter;
      if (only && only !== filter) show = false;
      card.classList.toggle('hidden', !show);
    });
    voicePick.hidden = filter !== 'voice';
    grid.dataset.filter = filter;
  });
});

// 다크 모드
const root = document.documentElement;
const toggle = document.getElementById('themeToggle');

function applyTheme(theme) {
  root.dataset.theme = theme;
  try { localStorage.setItem('theme', theme); } catch (e) {}
}

let saved = null;
try { saved = localStorage.getItem('theme'); } catch (e) {}
if (saved) {
  root.dataset.theme = saved;
} else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
  root.dataset.theme = 'dark';
}

toggle.addEventListener('click', () => {
  applyTheme(root.dataset.theme === 'dark' ? 'light' : 'dark');
});

// 서비스 카드에 로고(사이트 아이콘) 추가
document.querySelectorAll('a.card.mini').forEach((card) => {
  const title = card.querySelector('h3');
  const name = title.firstChild.textContent;
  const host = new URL(card.href).hostname;

  const brand = document.createElement('span');
  brand.className = 'brand';

  const img = document.createElement('img');
  img.className = 'logo-img';
  img.alt = '';
  img.loading = 'lazy';
  img.src = 'https://www.google.com/s2/favicons?domain=' + host + '&sz=64';
  img.addEventListener('error', () => {
    const letter = document.createElement('span');
    letter.className = 'logo-img logo-letter';
    letter.textContent = name.trim()[0];
    img.replaceWith(letter);
  });

  brand.append(img, name);
  title.firstChild.replaceWith(brand);
});

// 표·흐름의 분야 링크: 서비스 목록의 해당 필터로 이동
document.querySelectorAll('[data-goto]').forEach((link) => {
  link.addEventListener('click', (e) => {
    e.preventDefault();
    const chip = document.querySelector('.chip[data-filter="' + link.dataset.goto + '"]');
    if (chip) chip.click();
    document.getElementById('types').scrollIntoView({ behavior: 'smooth' });
  });
});

// 요청 예시 복사
document.querySelectorAll('.copy-btn').forEach((btn) => {
  btn.addEventListener('click', async () => {
    const text = btn.parentElement.querySelector('.prompt-text').textContent;
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = '복사됨 ✓';
    } catch (e) {
      btn.textContent = '직접 선택해 복사하세요';
    }
    setTimeout(() => { btn.textContent = '복사'; }, 1800);
  });
});

// 비교표: 분야 이름에 마우스를 올리면 추천 AI 표시
const TABLE_RECS = {
  '텍스트 생성': [['ChatGPT', 'https://chatgpt.com', '가장 널리 쓰이는 대화형 AI'], ['Claude', 'https://claude.ai', '긴 글·문서 작업에 강함'], ['Perplexity', 'https://perplexity.ai', '출처를 보여주는 검색형 AI']],
  '이미지 생성': [['Gemini', 'https://gemini.google.com', '구글 계정으로 바로 사용'], ['Midjourney', 'https://midjourney.com', '예술적 결과물로 유명'], ['Adobe Firefly', 'https://firefly.adobe.com', '어도비 도구와 연동']],
  '영상 생성': [['Kling AI', 'https://klingai.com', '무료 일일 크레딧 넉넉'], ['Runway', 'https://runwayml.com', '영상 생성·편집 전문'], ['Luma Dream Machine', 'https://lumalabs.ai/dream-machine', '카드 없이 시작']],
  '음악 생성': [['Suno', 'https://suno.com', '가사 포함 노래 생성'], ['Udio', 'https://udio.com', '고품질 노래 생성'], ['Stable Audio', 'https://stableaudio.com', '짧은 트랙·효과음']],
  '음성 합성': [['ElevenLabs', 'https://elevenlabs.io', '감정 표현·보이스 클로닝'], ['타입캐스트', 'https://typecast.ai/kr', '한국어 감정 표현'], ['Fish Audio', 'https://fish.audio', '클로닝 자연스러움']],
  '시각화': [['Napkin AI', 'https://napkin.ai', '글을 도식으로 변환'], ['Julius AI', 'https://julius.ai', '대화로 데이터 분석'], ['Datawrapper', 'https://datawrapper.de', '깔끔한 차트·지도']],
  '자동화': [['Zapier', 'https://zapier.com', '카드 없이 쉬운 시작'], ['Make', 'https://make.com', '무료 한도 넉넉'], ['n8n', 'https://n8n.io', '오픈소스·직접 설치']],
  '코드 생성': [['GitHub Copilot', 'https://github.com/features/copilot', '가장 쉽게 시작하는 코딩 AI'], ['Cursor', 'https://cursor.com', 'AI 중심 코드 편집기'], ['Windsurf', 'https://windsurf.com', '무료 플랜이 쓸 만함']],
  '컴퓨터 비전': [['Google Cloud Vision', 'https://cloud.google.com/vision', '이미지 태그·OCR, 월 1,000건 무료'], ['Roboflow', 'https://roboflow.com', '직접 학습하는 맞춤 탐지'], ['Ultralytics YOLO', 'https://ultralytics.com', '오픈소스 객체 탐지']],
  '예측·추천': [['Amazon Personalize', 'https://aws.amazon.com/personalize', '추천 시스템 서비스'], ['Prophet', 'https://facebook.github.io/prophet', '메타의 무료 예측 라이브러리'], ['Google Vertex AI', 'https://cloud.google.com/vertex-ai', '예측 모델 구축·배포']],
  '로보틱스': [['NVIDIA Isaac', 'https://developer.nvidia.com/isaac', '로봇 시뮬레이션·AI 모델'], ['ROS 2', 'https://www.ros.org', '로봇 소프트웨어 표준 틀'], ['Gazebo', 'https://gazebosim.org', '무료 오픈소스 로봇 시뮬레이터']],
  '음성 인식': [['클로바노트', 'https://clovanote.naver.com', '한국어 회의·강의 기록'], ['Otter.ai', 'https://otter.ai', '회의 자동 기록·요약'], ['Whisper', 'https://openai.com/index/whisper', '오픈소스 음성 인식']],
};

const floatTip = document.createElement('div');
floatTip.className = 'float-tip';
floatTip.setAttribute('role', 'tooltip');
document.body.appendChild(floatTip);
let tipTimer = null;

function showTip(row) {
  clearTimeout(tipTimer);
  const link = row.querySelector('td:first-child a');
  const recs = TABLE_RECS[link.textContent.trim()];
  floatTip.textContent = '';
  const title = document.createElement('b');
  title.textContent = '추천 AI';
  floatTip.appendChild(title);
  if (recs) {
    recs.forEach(([n, url, why], i) => {
      const a = document.createElement('a');
      a.className = 'rec-link' + (i === 0 ? ' top' : '');
      a.href = url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = (i === 0 ? '★ ' : '') + n + ' ↗';
      const small = document.createElement('small');
      small.textContent = why;
      a.appendChild(small);
      floatTip.appendChild(a);
    });
  } else {
    const p = document.createElement('p');
    p.className = 'tip-note';
    p.textContent = '이 분야는 서비스 목록 없이 소개 카드로만 정리했습니다.';
    floatTip.appendChild(p);
  }
  const more = document.createElement('a');
  more.className = 'more';
  more.href = '#types';
  more.textContent = '서비스 목록 보기 →';
  more.addEventListener('click', (e) => { e.preventDefault(); link.click(); hideTip(); });
  floatTip.appendChild(more);

  floatTip.classList.add('show');
  // 줄의 오른쪽(뒤쪽) 끝에 맞춰, 줄 바로 아래에 붙여서 표시
  const r = row.getBoundingClientRect();
  const w = floatTip.offsetWidth;
  const h = floatTip.offsetHeight;
  const left = Math.min(Math.max(8, r.right - w - 12), window.innerWidth - w - 8);
  let top = r.bottom - 2;
  if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h + 2);
  floatTip.style.left = left + 'px';
  floatTip.style.top = top + 'px';
}

function hideTip() {
  tipTimer = setTimeout(() => floatTip.classList.remove('show'), 200);
}

document.querySelectorAll('.table-wrap tbody tr').forEach((row) => {
  row.addEventListener('mouseenter', () => showTip(row));
  row.addEventListener('mouseleave', hideTip);
  const link = row.querySelector('td:first-child a');
  link.addEventListener('focus', () => showTip(row));
  link.addEventListener('blur', hideTip);
});
floatTip.addEventListener('mouseenter', () => clearTimeout(tipTimer));
floatTip.addEventListener('mouseleave', hideTip);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') floatTip.classList.remove('show'); });
window.addEventListener('scroll', () => floatTip.classList.remove('show'), { passive: true });
