// 상업송장 ④Consignee ↔ ⑨Buyer 자동 보완. 화면 쪽 규칙입니다.
// 서버 쪽 같은 규칙은 tests/test_document_start.py에서 봅니다.
// Run with: node --test tests/doc_parties.test.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../app/static/js/doc_form.js'), 'utf8');
// 자동 보완 규칙만 떼어 냅니다. (칸을 벗어날 때 부르는 부분은 화면이 붙입니다)
const rules = source.slice(source.indexOf('  const SAME_AS_CONSIGNEE'),
                           source.indexOf('  [consigneeEl, invoiceBuyerEl].forEach'));

function input(value = '') {
  return {value, dataset: {}, classList: {add() {}, remove() {}},
          dispatchEvent() {}, addEventListener() {}};
}

function context(consignee = '', buyer = '') {
  const elements = {buyer_name: input(consignee), buyer: input(buyer)};
  const ctx = vm.createContext({form: {elements}, markPrefilled() {}, Event: class {}});
  vm.runInContext(rules, ctx);
  return {ctx, elements};
}

function pair(consignee, buyer) {
  const {ctx, elements} = context(consignee, buyer);
  ctx.pairParties();
  return [elements.buyer_name.value, elements.buyer.value];
}

test('Consignee만 적으면 Buyer 칸이 SAME AS CONSIGNEE가 된다', () => {
  assert.deepEqual(pair('ABC Beauty Inc.', ''), ['ABC Beauty Inc.', 'SAME AS CONSIGNEE']);
});

test('Buyer만 적으면 Consignee 칸에 그 상호가 그대로 들어간다', () => {
  // 목록에 문구가 줄줄이 뜨지 않게, "SAME AS BUYER"가 아니라 상호를 옮깁니다.
  assert.deepEqual(pair('', 'ABC Trading Ltd.'), ['ABC Trading Ltd.', 'ABC Trading Ltd.']);
});

test('SAME AS BUYER는 어느 칸에도 넣지 않는다', () => {
  // Buyer 칸에 문구만 있고 받는 곳을 모르는 상태입니다. 문구를 상호 자리에 옮기면
  // 받는 곳 이름이 "SAME AS CONSIGNEE"인 서류가 나갑니다. 비워 두고 다시 묻습니다.
  assert.deepEqual(pair('', 'SAME AS CONSIGNEE'), ['', 'SAME AS CONSIGNEE']);
  const source = fs.readFileSync(path.join(__dirname, '../app/static/js/doc_form.js'), 'utf8');
  assert.ok(!source.includes('SAME AS BUYER'));
});

test('둘 다 적혀 있으면 적은 대로 둔다', () => {
  assert.deepEqual(pair('ABC Beauty Inc.', 'ABC Trading Ltd.'),
                   ['ABC Beauty Inc.', 'ABC Trading Ltd.']);
});

test('둘 다 비어 있으면 아무것도 넣지 않는다', () => {
  assert.deepEqual(pair('', ''), ['', '']);
});

test('사람이 적은 값은 덮지 않는다', () => {
  const {ctx, elements} = context('ABC Beauty Inc.', '');
  ctx.pairParties();                       // Buyer = SAME AS CONSIGNEE
  elements.buyer.value = 'ABC Trading Ltd.';
  delete elements.buyer.dataset.autoFilled;  // 사람이 적기 시작하면 표시가 떨어집니다.
  ctx.pairParties();
  assert.equal(elements.buyer.value, 'ABC Trading Ltd.');
});

test('Consignee를 지우면 채워 둔 Buyer 문구도 걷어 낸다', () => {
  const {ctx, elements} = context('ABC Beauty Inc.', '');
  ctx.pairParties();
  elements.buyer_name.value = '';
  ctx.pairParties();
  assert.equal(elements.buyer.value, '');
});

test('Buyer를 지우면 그걸 보고 채운 Consignee도 걷어 낸다', () => {
  const {ctx, elements} = context('', 'ABC Trading Ltd.');
  ctx.pairParties();                       // Consignee = ABC Trading Ltd.
  elements.buyer.value = '';
  ctx.pairParties();
  assert.equal(elements.buyer_name.value, '');
});
