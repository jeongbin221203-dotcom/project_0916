// Run with: node --test tests/cargo_display.test.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/js/planning.js'), 'utf8');
// HS 후보 그리기와 ⓘ 설명은 간편 검색 창과 같이 쓰려고 hs_search.js로 옮겼습니다.
const hsSource = fs.readFileSync(path.join(__dirname, '../app/static/js/hs_search.js'), 'utf8');
function section(start, end, text = source) { return text.slice(text.indexOf(start), text.indexOf(end, text.indexOf(start))); }
function context(data = {}) {
  const ctx = vm.createContext({URLSearchParams, urls: {destinationTariff: '/tariff'},
    getJson: async () => ({success: true, data}),
    escapeHtml: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;')});
  vm.runInContext(section('  function infoTip(', '  const tipPopup', hsSource), ctx);
  vm.runInContext(section('  const destinationTokens', '  /* ----- HS부호'), ctx);
  vm.runInContext(section('  function renderHsItem(', '  function hsEmptyMessage(', hsSource), ctx);
  return ctx;
}
test('relevance uses categorical colors, escapes API text and keeps evidence in details', () => {
  const ctx = context();
  for (const match of ['high', 'medium', 'low', 'unknown']) {
    const html = ctx.renderHsItem({code: '2106.90-9099', name: '<script>', relevance: {match, reason: 'Evidence'}});
    assert.ok(html.includes(`match_${match}`));
    assert.ok(html.includes('&lt;script>'));
    assert.ok(!html.includes('<script>'));
    assert.match(html, /info_tip_body[^]*Evidence/);
  }
  assert.match(ctx.renderHsItem({relevance: {match: 'unexpected'}}), /match_unknown/);
});
test('national preview is bounded, selection keeps original rate and parent conditions', async () => {
  const data = {available: true, country: 'Japan', hs6: '2106.90', rates: [], link: {url: 'https://example.com', label: 'Source'},
    national: {label: 'Tariff', columns: [{key: 'wto', label: 'WTO'}], lines: [
      {code: '2106.90', description: 'Parent condition'},
      {code: '2106.90', description: '1 Preparations containing milk'},
      {code: '2106.90', description: '(1) Of a milk fat content limit'},
      ...Array.from({length: 8}, (_, i) => ({code: `2106.90-${111+i}`, description: `Product ${i}`, wto: `${i}% + 799 yen/kg`}))]}};
  const ctx = context(data);
  let handler;
  const excerpt = {innerHTML: ''};
  const slot = {isConnected: true, querySelector: selector => selector === '[data-national-line]'
    ? {addEventListener: (name, fn) => {handler = fn;}} : excerpt};
  await ctx.refreshDestinationTariff('2106909099', 'JP', slot);
  assert.equal((slot.innerHTML.match(/<tbody>[^]*?<\/tbody>/)[0].match(/<tr>/g) || []).length, 3);
  assert.ok(slot.innerHTML.includes('Parent condition'));
  handler({target: {value: '7'}});
  assert.equal((excerpt.innerHTML.match(/<tr>/g) || []).length, 2); // header + selected row
  assert.ok(excerpt.innerHTML.includes('2106.90-118'));
  assert.ok(excerpt.innerHTML.includes('7% + 799 yen/kg'));
  assert.ok(excerpt.innerHTML.includes('Parent condition'));
  assert.ok(excerpt.innerHTML.includes('1 Preparations containing milk'));
  assert.ok(excerpt.innerHTML.includes('(1) Of a milk fat content limit'));
  assert.ok(!excerpt.innerHTML.includes('Product 0'));
});

test('US and UK excerpts retain indented parent conditions and omit heading rows', async () => {
  for (const country of ['US', 'GB']) {
    const data = {available: true, country, hs6: '3304.99', rates: [], link: {url: 'https://example.com', label: 'Source'},
      national: {label: 'Tariff', columns: [], lines: [
        {code: '3304.99', indent: 0, description: 'Parent'},
        {code: '3304.99.10', indent: 1, description: 'Condition'},
        {code: '3304.99.1000', indent: 2, description: 'Leaf'}]}};
    const slot = {isConnected: true, querySelector: () => ({addEventListener() {}})};
    await context(data).refreshDestinationTariff('3304991000', country, slot);
    assert.equal(slot._nationalExcerpt.rows.length, 1);
    assert.ok(slot.innerHTML.includes('Parent'));
    assert.ok(slot.innerHTML.includes('Condition'));
    assert.ok(slot.innerHTML.includes('Leaf'));
  }
});

test('handling selections restore from drafts and unchecking clears submitted values', () => {
  const ctx = vm.createContext({});
  vm.runInContext('const DG_FIELDS = ["un_number", "dg_class", "proper_shipping_name", "packing_group"];'
    + section('  function dgValues(', '  // 위험물 칸이 덜'), ctx);
  const fields = {};
  for (const name of ['is_dangerous', 'un_number', 'dg_class', 'proper_shipping_name', 'packing_group']) {
    fields[`[data-dg="${name}"]`] = {value: '', checked: false};
  }
  const toggles = ['temperature_requirement', 'special_container_type'].map(key => {
    fields[`[data-handling="${key}"]`] = {value: 'unspecified'};
    return {dataset: {handlingToggle: key}, checked: false};
  });
  const box = {querySelector: key => fields[key], querySelectorAll: () => toggles, refreshDg() {}};
  ctx.setDgValues(box, {temperature_requirement: 'frozen', special_container_type: 'flat_rack'});
  assert.equal(ctx.dgValues(box).temperature_requirement, 'frozen');
  assert.equal(ctx.dgValues(box).special_container_type, 'flat_rack');
  assert.equal(ctx.dgValues(box).is_dangerous, false);
  toggles.forEach(toggle => {toggle.checked = false;});
  assert.equal(ctx.dgValues(box).temperature_requirement, '');
  assert.equal(ctx.dgValues(box).special_container_type, '');
  ctx.setDgValues(box, {});
  assert.equal(fields['[data-handling="temperature_requirement"]'].value, 'unspecified');
});
