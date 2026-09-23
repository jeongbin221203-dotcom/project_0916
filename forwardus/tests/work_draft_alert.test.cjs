// 임시저장이 실패했을 때 조용히 버리지 않고 이유를 알리는지 봅니다.
// 서버 쪽 임시저장은 tests/test_docs_planning_flow.py에서 봅니다.
// Run with: node --test tests/work_draft_alert.test.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../app/static/js/work_draft.js'), 'utf8');
// 실패를 알리는 부분만 떼어 냅니다. (적을 때마다 부르는 save/flush는 화면이 붙입니다)
const rules = source.slice(source.indexOf('  let banner = null;'),
                           source.indexOf('  function save('));

// 배너는 화면에 붙기 전까지 만들어지지 않습니다. 만들어지면 여기에 담깁니다.
function fakeDocument(box) {
  function node() {
    const parts = {};
    return {
      hidden: false, className: '', innerHTML: '',
      setAttribute() {},
      querySelector(selector) {
        if (!parts[selector]) {
          parts[selector] = {textContent: '', addEventListener(name, fn) { this.click = fn; }};
        }
        return parts[selector];
      },
    };
  }
  return {createElement: () => { box.el = node(); return box.el; },
          body: {appendChild() { box.attached = true; }}};
}

function context(fetchImpl) {
  const box = {el: null, attached: false};
  const ctx = vm.createContext({
    config: {url: '/api/work-draft'},
    pending: null,
    timer: null,
    fetch: fetchImpl,
    document: fakeDocument(box),
  });
  vm.runInContext(rules, ctx);
  return {ctx, box, why: () => box.el && box.el.querySelector('[data-draft-why]').textContent};
}

function reply(status, body) {
  return async () => ({ok: status < 400, status, json: async () => body});
}

test('세션이 만료되면 조용히 버리지 않고 이유를 알린다', async () => {
  const {ctx, box, why} = context(reply(401, {message: '로그인이 필요합니다.'}));
  ctx.pending = {source: 'document', fields: {buyer_name: 'ABC'}, items: []};

  assert.equal(await ctx.send(), null);
  assert.ok(box.attached, '배너가 화면에 붙어야 합니다.');
  assert.equal(box.el.hidden, false);
  assert.match(why(), /로그인이 풀렸습니다/);
  // 적은 내용이 남아 있어야 [다시 시도]가 보낼 것이 있습니다.
  assert.deepEqual(ctx.pending.fields, {buyer_name: 'ABC'});
});

test('서버가 죽으면 상태 번호까지 알린다', async () => {
  const {ctx, why} = context(reply(503, null));
  ctx.pending = {fields: {}, items: []};
  await ctx.send();
  assert.match(why(), /서버가 응답하지 않습니다\. \(503\)/);
});

test('서버가 이유를 적어 보내면 그 말을 그대로 쓴다', async () => {
  const {ctx, why} = context(reply(400, {message: '품목이 너무 많습니다.'}));
  ctx.pending = {fields: {}, items: []};
  await ctx.send();
  assert.equal(why(), '품목이 너무 많습니다.');
});

test('연결이 끊기면 연결 문제라고 알린다', async () => {
  const {ctx, why} = context(async () => { throw new TypeError('Failed to fetch'); });
  ctx.pending = {fields: {}, items: []};
  await ctx.send();
  assert.match(why(), /인터넷 연결/);
});

test('다시 저장되면 배너가 사라진다', async () => {
  const {ctx, box} = context(reply(401, {}));
  ctx.pending = {fields: {a: '1'}, items: []};
  await ctx.send();
  assert.equal(box.el.hidden, false);

  ctx.fetch = reply(200, {data: {ok: true}});
  await ctx.send();                       // 되돌려 둔 내용을 다시 보냅니다.
  assert.equal(box.el.hidden, true);
});

test('기다리는 동안 더 적었으면 그쪽이 최신이라 덮지 않는다', async () => {
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  const {ctx} = context(async () => { await held; return {ok: false, status: 500, json: async () => null}; });

  ctx.pending = {fields: {buyer_name: '옛것'}, items: []};
  const sending = ctx.send();
  ctx.pending = {fields: {buyer_name: '새것'}, items: []};   // 보내는 동안 더 적었습니다.
  release();
  await sending;

  assert.equal(ctx.pending.fields.buyer_name, '새것');
});
