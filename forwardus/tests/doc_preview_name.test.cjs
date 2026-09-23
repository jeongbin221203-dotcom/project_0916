// 서류 미리보기 & 검토 창의 견적명 칸.
// 서버 쪽(Shipment 없이 저장·승격)은 tests/test_document_draft.py에서 봅니다.
// Run with: node --test tests/doc_preview_name.test.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../app/static/js/doc_preview.js'), 'utf8');
const markup = fs.readFileSync(path.join(__dirname, '../app/templates/home/index.html'), 'utf8');

test('모달에 견적명 칸과 저장 단추가 있다', () => {
  // 사진 속 [서류 미리보기 & 검토] 창의 제목 바로 아래입니다.
  const start = markup.indexOf('data-dp-modal');
  const modal = markup.slice(start, markup.indexOf('{% block scripts %}', start));
  assert.ok(modal.includes('data-dp-name'), '견적명 인풋');
  assert.ok(modal.includes('data-dp-name-save'), '저장 단추');
  assert.ok(modal.includes('aria-label="견적명 · 문서명"'), '읽어 주는 이름');
  // 탭 줄(dp_bar)보다 위에 있어야 "최상단"입니다.
  assert.ok(modal.indexOf('data-dp-name') < modal.indexOf('dp_bar'));
});

test('이름은 칸을 벗어날 때·저장 단추·PDF·닫기에서 저장된다', () => {
  // 넷 중 하나라도 빠지면 적어 둔 이름이 조용히 사라집니다.
  assert.match(source, /nameBox\?\.addEventListener\("blur"[^]*?saveName\(\)/);
  assert.match(source, /nameSaveButton\?\.addEventListener\("click"[^]*?saveName\(true\)/);
  assert.match(source, /pdfButton\.addEventListener[^]*?await saveName\(true\)/);
  assert.match(source, /function close\(\)[^]*?saveName\(\)/);
});

test('저장할 창구가 없으면 이름 칸을 숨긴다', () => {
  // 초안을 남길 수 없는 화면에서 빈 칸만 내밀면 적어도 사라집니다.
  assert.match(source, /const usable = !!urls\.saveDraftUrl;\s*\n\s*nameWrap\.hidden = !usable;/);
});

test('저장한 이름은 내려받는 파일 이름에도 붙는다', () => {
  assert.ok(source.includes('urls.projectName = savedName;'));
});

test('바깥에서 지금 이름과 초안 번호를 볼 수 있다', () => {
  // 서류 작성 화면으로 넘기거나 Shipment로 승격할 때 씁니다.
  assert.ok(source.includes('quoteTitle: () => currentName()'));
  assert.ok(source.includes('draftId: () => draftId'));
});

test('대화창이 검토 창에 저장 창구와 초안을 넘긴다', () => {
  const home = fs.readFileSync(path.join(__dirname, '../app/static/js/home.js'), 'utf8');
  assert.ok(home.includes('saveDraftUrl: config.saveDraftUrl'));
  assert.ok(home.includes('getDraft:'), '승격에 쓸 초안');
  assert.ok(home.includes('onSaved: adoptQuoteTitle'), '고친 이름을 대화 쪽에도 반영');
  // 서류 작성 화면이 이어받아 Shipment로 승격할 수 있게 번호도 같이 둡니다.
  assert.ok(home.includes('draftId: savedDraftId'));
  const form = fs.readFileSync(path.join(__dirname, '../app/static/js/doc_form.js'), 'utf8');
  assert.ok(form.includes('carriedDraftId = parsed.draftId'));
  assert.ok(form.includes('draft_id: carriedDraftId'));
});
