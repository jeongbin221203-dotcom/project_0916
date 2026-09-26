/* 실시간 환율 센터. 사이드바 [💱 환율]로 여는 창입니다.

   탭 1 시세표   모든 통화의 매매기준율·전일 대비·받을 때(TTB)·보낼 때(TTS). 검색으로 거릅니다.
   탭 2 계산기   From ↔ To 어떤 통화끼리도. 적용 환율(매매기준율 / 받을 때 / 보낼 때)을 고릅니다.

   환율은 서버(/planning/api/fx-board, fx_board_client)가 줍니다. 모든 금액은 "그 통화
   unit개당 원화"라 원화를 거쳐 환산합니다. 송금 환율을 받는 곳이 주지 않으면(spread=estimate)
   지어내지 않고 "매매기준율 ± 스프레드" 추정으로 계산하며, 그렇다고 화면에 밝힙니다. */
(function () {
  "use strict";

  // 환율 창은 사이드바와 함께 모든 화면에 붙습니다. 주소는 base.html이 FORWARDUS_FX로 넘깁니다.
  const config = window.FORWARDUS_FX || window.FORWARDUS_HOME;
  const modal = document.querySelector("[data-fx-modal]");
  const openers = document.querySelectorAll("[data-fx-open]");
  if (!config || !config.fxBoardUrl || !modal || !openers.length) return;

  const { escapeHtml, getJson } = window.Forwardus;
  const $ = (selector) => modal.querySelector(selector);
  const metaEl = $("[data-fx-meta]");
  const rowsEl = $("[data-fx-rows]");
  const noteEl = $("[data-fx-note]");
  const searchEl = $("[data-fx-search]");
  const amountEl = $("[data-fx-amount]");
  const fromEl = $("[data-fx-from]");
  const toEl = $("[data-fx-to]");
  const spreadBox = $("[data-fx-spread-box]");
  const spreadEl = $("[data-fx-spread]");
  const resultEl = $("[data-fx-result]");
  const appliedEl = $("[data-fx-applied]");

  let board = null;          // 서버가 준 시세표
  let byCode = {};           // code → row (KRW 포함)
  let loading = null;
  let lastFocus = null;

  /* ----- 숫자 ----- */
  const decimals = (code) => (code === "KRW" || code === "JPY" || code === "IDR" || code === "VND" ? 0 : 2);

  function money(value, code) {
    if (value === null || value === undefined || !Number.isFinite(value)) return "—";
    const digits = decimals(code);
    return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function rate(value) {
    if (value === null || value === undefined) return "—";
    return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function parseAmount(text) {
    const value = Number(String(text).replace(/,/g, "").trim());
    return Number.isFinite(value) ? value : NaN;
  }

  /* ----- 적용 환율 -----
     "그 통화 1단위가 몇 원인지"를 적용 환율에 맞춰 돌려줍니다. 원화는 늘 1.
     받을 때(TTB)는 은행이 외화를 사 주는 값, 보낼 때(TTS)는 은행이 외화를 파는 값입니다. */
  function spreadPct() {
    const value = Number(spreadEl.value);
    return Number.isFinite(value) && value >= 0 ? Math.min(value, 10) : board.default_spread_pct;
  }

  function perOne(code, mode) {
    if (code === "KRW") return { value: 1, estimated: false };
    const row = byCode[code];
    if (!row) return null;
    let value = row.deal;
    let estimated = false;
    if (mode === "ttb" || mode === "tts") {
      if (row[mode]) {
        value = row[mode];
      } else {
        const pct = spreadPct() / 100;
        value = row.deal * (mode === "ttb" ? 1 - pct : 1 + pct);
        estimated = true;
      }
    }
    return { value: value / row.unit, estimated };
  }

  function mode() {
    return modal.querySelector("[data-fx-mode]:checked").value;
  }

  const MODE_LABEL = { deal: "매매기준율", ttb: "전신환 매입률(TTB)", tts: "전신환 매도율(TTS)" };

  function calculate() {
    if (!board) return;
    const amount = parseAmount(amountEl.value);
    const from = perOne(fromEl.value, mode());
    const to = perOne(toEl.value, mode());
    const needsSpread = mode() !== "deal" && board.spread === "estimate";
    spreadBox.hidden = !needsSpread;
    if (!from || !to || Number.isNaN(amount)) {
      resultEl.textContent = "—";
      appliedEl.textContent = Number.isNaN(amount) ? "금액을 숫자로 적어 주세요." : "";
      return;
    }
    const result = (amount * from.value) / to.value;
    // 적은 금액은 적은 그대로 보여 줍니다. (1,234.5원을 1,235원으로 바꿔 보이면 다른 금액이 됩니다)
    const typed = amount.toLocaleString("en-US", { maximumFractionDigits: 4 });
    resultEl.innerHTML = `${escapeHtml(typed)} <small>${escapeHtml(fromEl.value)}</small>`
      + ` = <b>${escapeHtml(money(result, toEl.value))}</b> <small>${escapeHtml(toEl.value)}</small>`;

    // 무엇으로 계산했는지 반드시 밝힙니다. 모르고 쓰면 송금액이 틀립니다.
    const foreign = fromEl.value !== "KRW" ? fromEl.value : toEl.value;
    const used = foreign === "KRW" ? null : perOne(foreign, mode());
    const row = byCode[foreign];
    let line = `적용: ${MODE_LABEL[mode()]}`;
    if (used && row) {
      line += ` · ${row.unit} ${foreign} = ${rate(used.value * row.unit)}원`;
      if (used.estimated) line += ` (추정: 매매기준율 ${mode() === "ttb" ? "−" : "+"}${spreadPct()}% · 은행 고시 아님)`;
    }
    if (fromEl.value !== "KRW" && toEl.value !== "KRW") line += " · 원화를 거친 교차 환산";
    appliedEl.textContent = line;
  }

  /* ----- 시세표 ----- */
  function changeCell(row) {
    if (row.change === null || row.change === undefined) return '<td class="num muted">—</td>';
    const dir = row.change > 0 ? "up" : row.change < 0 ? "down" : "";
    const arrow = row.change > 0 ? "▲" : row.change < 0 ? "▼" : "−";
    return `<td class="num ${dir}">${arrow} ${escapeHtml(rate(Math.abs(row.change)))}`
      + `<small>${row.change_pct > 0 ? "+" : ""}${escapeHtml(String(row.change_pct))}%</small></td>`;
  }

  function sendCell(row, key) {
    if (row[key]) return `<td class="num">${escapeHtml(rate(row[key]))}</td>`;
    // 받는 곳이 송금 환율을 주지 않으면 추정치를 흐리게 보여 줍니다.
    const pct = board.default_spread_pct / 100;
    const value = row.deal * (key === "ttb" ? 1 - pct : 1 + pct);
    return `<td class="num est" title="추정: 매매기준율 ${key === "ttb" ? "−" : "+"}${board.default_spread_pct}%">`
      + `${escapeHtml(rate(value))}<small>추정</small></td>`;
  }

  function renderRows() {
    const words = searchEl.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const rows = board.rows.filter((row) => {
      const text = `${row.code} ${row.cur_unit} ${row.name} ${row.name_en}`.toLowerCase();
      return words.every((word) => text.includes(word));
    });
    rowsEl.innerHTML = rows.length ? rows.map((row) => `
      <tr data-fx-code="${escapeHtml(row.code)}" tabindex="0" title="계산기에서 ${escapeHtml(row.code)}로 계산">
        <td><b>${escapeHtml(row.cur_unit)}</b></td>
        <td>${escapeHtml(row.name)}${row.name_en && row.name_en !== row.name
          ? `<small>${escapeHtml(row.name_en)}</small>` : ""}</td>
        <td class="num strong">${escapeHtml(rate(row.deal))}</td>
        ${changeCell(row)}${sendCell(row, "ttb")}${sendCell(row, "tts")}
      </tr>`).join("")
      : `<tr><td colspan="6" class="fx_empty">'${escapeHtml(searchEl.value)}'에 맞는 통화가 없습니다.</td></tr>`;
  }

  function fillSelects() {
    const options = [{ code: "KRW", name: "대한민국 원" }, ...board.rows].map((row) =>
      `<option value="${escapeHtml(row.code)}">${escapeHtml(row.code)} · ${escapeHtml(row.name)}</option>`).join("");
    [fromEl, toEl].forEach((select) => {
      const keep = select.value;
      select.innerHTML = options;
      if (keep && byCode[keep]) select.value = keep;
    });
    if (!fromEl.value || fromEl.value === toEl.value) { fromEl.value = "USD"; toEl.value = "KRW"; }
  }

  async function load() {
    if (board) return;
    if (!loading) loading = getJson(config.fxBoardUrl, 30000);
    const response = await loading;
    loading = null;
    if (!response.success || !response.data || !response.data.rows) {
      metaEl.textContent = "환율을 받지 못했습니다. 잠시 뒤 다시 열어 주세요.";
      metaEl.classList.add("is_bad");
      return;
    }
    board = response.data;
    byCode = { KRW: { code: "KRW", unit: 1, deal: 1, name: "대한민국 원" } };
    board.rows.forEach((row) => { byCode[row.code] = row; });
    spreadEl.value = board.default_spread_pct;
    metaEl.textContent = `${board.source_label} · 기준 ${board.as_of || "—"}`
      + (board.prev_date ? ` · 전일 대비는 ${board.prev_date} 기준` : "")
      + ` · ${board.rows.length}개 통화`;
    metaEl.classList.toggle("is_bad", response.source === "mock");
    noteEl.textContent = board.note;
    renderRows();
    fillSelects();
    calculate();
  }

  /* ----- 탭 ----- */
  function showTab(name) {
    modal.querySelectorAll("[data-fx-tab]").forEach((tab) => {
      const on = tab.dataset.fxTab === name;
      tab.classList.toggle("active", on);
      tab.setAttribute("aria-selected", on ? "true" : "false");
    });
    modal.querySelectorAll("[data-fx-panel]").forEach((panel) => {
      panel.hidden = panel.dataset.fxPanel !== name;
    });
    (name === "board" ? searchEl : amountEl).focus();
  }

  /* ----- 열고 닫기 ----- */
  function open() {
    lastFocus = document.activeElement;
    modal.hidden = false;
    document.body.classList.add("fx_modal_open");
    showTab(modal.querySelector("[data-fx-tab].active").dataset.fxTab);
    load();
  }

  function close() {
    modal.hidden = true;
    document.body.classList.remove("fx_modal_open");
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  openers.forEach((button) => button.addEventListener("click", open));
  modal.querySelectorAll("[data-fx-close]").forEach((el) => el.addEventListener("click", close));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) close();
  });
  modal.querySelectorAll("[data-fx-tab]").forEach((tab) =>
    tab.addEventListener("click", () => showTab(tab.dataset.fxTab)));

  searchEl.addEventListener("input", () => { if (board) renderRows(); });

  // 시세표의 줄을 누르면 그 통화로 계산기를 엽니다. (원화로 얼마인지가 가장 흔한 질문)
  function pickRow(target) {
    const row = target.closest("[data-fx-code]");
    if (!row) return;
    fromEl.value = row.dataset.fxCode;
    toEl.value = "KRW";
    calculate();
    showTab("calc");
  }
  rowsEl.addEventListener("click", (event) => pickRow(event.target));
  rowsEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") pickRow(event.target);
  });

  // 금액은 적는 대로 세 자리마다 쉼표를 넣습니다. 커서가 튀지 않게 뒤에서부터 자리를 셉니다.
  amountEl.addEventListener("input", () => {
    const raw = amountEl.value;
    const fromEnd = raw.length - amountEl.selectionStart;
    const clean = raw.replace(/[^\d.]/g, "").replace(/(\..*)\./g, "$1");
    const [whole, fraction] = clean.split(".");
    const grouped = (whole || "").replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    amountEl.value = fraction !== undefined ? `${grouped || "0"}.${fraction.slice(0, 4)}` : grouped;
    const caret = Math.max(0, amountEl.value.length - fromEnd);
    amountEl.setSelectionRange(caret, caret);
    calculate();
  });
  [fromEl, toEl, spreadEl].forEach((el) => {
    el.addEventListener("change", calculate);
    el.addEventListener("input", calculate);
  });
  modal.querySelectorAll("[data-fx-mode]").forEach((radio) => radio.addEventListener("change", calculate));
  $("[data-fx-swap]").addEventListener("click", () => {
    [fromEl.value, toEl.value] = [toEl.value, fromEl.value];
    calculate();
  });

  window.ForwardusFx = { open, close, perOne: (code, how) => perOne(code, how || "deal") };
})();
