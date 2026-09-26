// 고른 스케줄이 **없어지지 않는지** 봅니다.
//
// 사용자 신고(2026-09-26): 스케줄을 골라도 골라도 "스케줄을 고르세요"가 다시 떴습니다.
// 원인이 둘이었습니다.
//   ① 품목 칸에 글자 하나만 쳐도 invalidateSchedule() 이 돌아 선택이 지워졌습니다.
//      화면 안내는 "품목은 나중에 적어도 됩니다"인데 그대로 하면 선택이 날아갔습니다.
//   ② 목록을 innerHTML 로 다시 그리면 체크가 사라졌습니다. 같은 스케줄이 목록에
//      그대로 있는데도 아무것도 안 고른 것처럼 보였습니다.
//
// 서버 쪽(schedule_id 없이 저장하면 막는지)은 tests/test_docs_planning_flow.py 에서 봅니다.
// Run with: node --test tests/doc_schedule_keep.test.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../app/static/js/doc_form.js'), 'utf8');

test('품목 칸을 적어도 고른 스케줄을 지우지 않는다', () => {
  // addItem() 안에서 품목 줄에 붙이는 input 처리기
  const at = source.indexOf('function addItem()');
  assert.ok(at > 0, 'addItem 을 찾지 못했습니다');
  const body = source.slice(at, source.indexOf('\n  }', at));
  const line = body.split('\n').find((row) => row.includes('addEventListener("input"'));
  assert.ok(line, '품목 줄의 input 처리기를 찾지 못했습니다');
  assert.ok(!line.includes('invalidateSchedule'),
    '품목을 적는다고 스케줄을 지우면 안 됩니다: ' + line.trim());
});

test('품목 한 줄을 지워도 고른 스케줄을 지우지 않는다', () => {
  const at = source.indexOf('data-doc-remove-item');
  const body = source.slice(at, at + 400);
  assert.ok(!body.includes('invalidateSchedule'),
    '품목 줄을 지운다고 배가 다른 날 뜨지는 않습니다');
});

test('항로·날짜·운송수단이 바뀌면 고른 스케줄을 지운다', () => {
  // 이건 **지워야** 맞습니다. 다른 항로의 배를 그대로 들고 가면 안 됩니다.
  for (const anchor of ['data-doc-choice', 'arriveEl.addEventListener', 'role === "destination"']) {
    const at = source.indexOf(anchor);
    if (at < 0) continue;
    assert.ok(source.slice(Math.max(0, at - 600), at + 900).includes('invalidateSchedule'),
      anchor + ' 근처에서 스케줄을 지워야 합니다');
  }
});

test('목록을 다시 그려도 고른 스케줄이 그대로 체크된다', () => {
  const at = source.indexOf('name="schedule_pick"');
  const body = source.slice(at, at + 1800);
  assert.ok(body.includes('radio.checked = true'),
    '다시 그릴 때 고른 것을 되살려야 합니다');
  assert.ok(body.includes('chosenSchedule && radio.value === chosenSchedule'),
    '같은 schedule_id 일 때만 되살려야 합니다');
});

test('고른 스케줄이 새 목록에 없으면 그렇다고 말해 준다', () => {
  const at = source.indexOf('name="schedule_pick"');
  const body = source.slice(at, at + 1800);
  assert.ok(body.includes('chosenSchedule = ""'),
    '목록에 없으면 선택을 비워야 합니다');
  assert.ok(body.includes('다시 골라주세요'),
    '조용히 비우면 고른 줄 알고 넘어가다 저장에서 막힙니다');
});
