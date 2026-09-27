/* 관세청 표준품명이 HS 찾기 결과에 제대로 그려지는지 봅니다.
 *
 * 왜 이 테스트가 있나
 *   HS 찾기를 띄우는 화면이 다섯입니다 — 운송 계획 [3. Cargo] · HS 간편 검색 창 ·
 *   서류 작성 · 서류 올리기 · 첫 화면. 그런데 **줄을 그리는 코드는 하나**입니다
 *   (hs_search.js 의 renderHsItem). 다섯이 모두 그것을 받으므로, 이 함수만
 *   지키면 다섯 화면이 함께 지켜집니다.
 *
 *   그리고 형제 품명은 길어질 수 있습니다. 목록이 화면을 밀어내지 않게
 *   상자 안에서만 스크롤해야 합니다. (2026-09-27 사용자 결정)
 */

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.join(__dirname, "..");
const JS = fs.readFileSync(path.join(ROOT, "app/static/js/hs_search.js"), "utf8");
const CSS = fs.readFileSync(path.join(ROOT, "app/static/css/base.css"), "utf8");
const BASE_HTML = fs.readFileSync(path.join(ROOT, "app/templates/base.html"), "utf8");

/** renderHsItem 만 꺼내 씁니다. 브라우저 없이 문자열만 봅니다. */
function renderer() {
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => (
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
  const infoTip = (label, notes) => `<span class="info_tip">${escapeHtml(label)}` +
    `${(notes || []).filter(Boolean).map((n) => escapeHtml(String(n))).join(" / ")}</span>`;
  const body = JS.slice(JS.indexOf("function renderHsItem"), JS.indexOf("function hsEmptyMessage"));
  // eslint-disable-next-line no-new-func
  return new Function("escapeHtml", "infoTip", `${body}; return renderHsItem;`)(escapeHtml, infoTip);
}

const MAIN = {
  code: "0703.20-9000",
  name: "마늘(기타)",
  name_en: "Garlic",
  path: ["07", "0703", "0703.20"],
  std_name: "신선마늘(육쪽)",
  std_name_en: "Fresh Garlic",
  std_kind: "표준품명",
  std_base_date: "2026-01-01",
  std_siblings: [{name: "신선마늘(다쪽)", name_en: "Fresh Garlic(Multi)"}],
  relevance: {match: "high", reason: "관세청 표준품명과 글자까지 같습니다"},
};

test("1순위는 표준품명을 굵게 보여 주고 '신고용 정식 품명'이라 밝힌다", () => {
  const html = renderer()(MAIN);
  assert.ok(html.includes("신선마늘(육쪽)"), "표준품명이 제목에 없습니다");
  assert.ok(/<b class="hs_name">[^<]*신선마늘\(육쪽\)/.test(html), "표준품명이 제목 자리가 아닙니다");
  assert.ok(html.includes("신고용 정식 품명"), "정식 품명임을 밝히지 않습니다");
  assert.ok(html.includes("hs_std_main"), "표준품명 배지가 없습니다");
  // 품목표의 계층형 이름도 함께 보여 줘야 합니다. 어느 호인지 알 수 있게.
  assert.ok(html.includes("마늘(기타)"), "품목표 이름이 빠졌습니다");
});

test("형제 품명은 2번부터 번호를 달고 나온다", () => {
  const html = renderer()({...MAIN, std_siblings: [
    {name: "신선마늘(다쪽)", name_en: ""}, {name: "냉동다진마늘", name_en: ""}]});
  assert.ok(html.includes("hs_sibs"), "형제 상자가 없습니다");
  assert.ok(html.includes("신선마늘(다쪽)") && html.includes("냉동다진마늘"));
  // 1순위가 본 줄이므로 형제는 2번부터입니다.
  assert.ok(html.includes(">2</span>") && html.includes(">3</span>"), "번호가 2부터가 아닙니다");
  assert.ok(html.includes("어느 쪽인지 확인"), "무엇을 하라는 말이 없습니다");
});

test("형제가 없으면 빈 상자를 만들지 않는다", () => {
  const html = renderer()({...MAIN, std_siblings: []});
  assert.ok(!html.includes("hs_sibs"), "형제가 없는데 상자를 만듭니다");
});

test("다른 호는 '부호가 다릅니다'라고 밝힌다", () => {
  const html = renderer()({...MAIN, std_kind: "다른 호", std_name: "깐마늘(육쪽)"});
  assert.ok(html.includes("hs_std_other"), "다른 호 배지가 없습니다");
  assert.ok(html.includes("부호가 다릅니다"), "부호가 다르다는 말이 없습니다");
});

test("표준품명이 없는 줄은 예전처럼 그려진다", () => {
  const html = renderer()({code: "1212.21-1010", name: "건조한 것", name_en: "Dried",
                           path: ["12", "1212", "1212.21"], relevance: {match: "unknown"}});
  assert.ok(html.includes("건조한 것"));
  assert.ok(!html.includes("hs_std"), "표준품명이 없는데 배지를 답니다");
  assert.ok(html.includes("hs_path"), "분류 경로가 빠졌습니다");
});

test("형제 목록은 상자 안에서만 스크롤한다", () => {
  const block = CSS.slice(CSS.indexOf(".hs_sibs_list {"));
  const rule = block.slice(0, block.indexOf("}"));
  assert.ok(/max-height:\s*\d+px/.test(rule), "높이 한도가 없어 화면을 밀어냅니다");
  assert.ok(/overflow-y:\s*auto/.test(rule), "스크롤이 안 됩니다");
  // 막대를 숨기면 아래 더 있다는 것을 알 수가 없습니다.
  assert.ok(/scrollbar-width:\s*thin/.test(rule), "스크롤 막대를 보여 주지 않습니다");
  assert.ok(CSS.includes(".hs_sibs_list::-webkit-scrollbar"), "웹킷 막대 규칙이 없습니다");
});

test("모든 화면이 같은 렌더러와 같은 CSS를 받는다", () => {
  // base.html 이 모든 화면에 붙입니다. 하나라도 빠지면 그 화면만 예전 모양입니다.
  assert.ok(BASE_HTML.includes("js/hs_search.js"), "hs_search.js 가 모든 화면에 없습니다");
  assert.ok(BASE_HTML.includes("css/base.css"), "base.css 가 모든 화면에 없습니다");
  assert.ok(BASE_HTML.includes("data-hs-modal"), "HS 찾기 창이 모든 화면에 없습니다");

  // 자기만의 HS 줄 렌더러를 만든 곳이 있으면 이 기능이 그 화면에서만 빠집니다.
  const dir = path.join(ROOT, "app/static/js");
  const others = fs.readdirSync(dir).filter((f) => f.endsWith(".js") && f !== "hs_search.js");
  for (const file of others) {
    const text = fs.readFileSync(path.join(dir, file), "utf8");
    assert.ok(!text.includes('class="hs_candidate'),
      `${file} 이 HS 줄을 따로 그립니다. renderHsItem 을 쓰게 바꾸세요`);
  }
});
