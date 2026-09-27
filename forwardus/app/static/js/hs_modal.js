/* HS CODE 간편 검색 창.
   어느 화면에서나 [data-hs-open]을 누르거나 ForwardusHsModal.open()을 부르면 뜹니다.
   Cargo 화면으로 옮겨 가지 않고도 같은 검색을 쓰게 하려는 자리입니다.

   검색은 hs_search.js와 base.js의 setupAutocomplete를 그대로 씁니다. 조회 창구,
   AI 품명 해석·적합도, 건수·관세 비교, 그리는 모양이 Cargo 화면과 같습니다.

   고르면 두 가지 중 하나입니다.
   - 작업 중인 칸(target)이 있으면 그 칸에 넣습니다. (서류 작성의 품목 HS부호 칸 등)
   - 없으면 클립보드에 복사합니다. (상담 중에 찾아보는 경우) */
(function () {
  "use strict";

  const config = window.FORWARDUS_HS_MODAL;
  const modal = document.querySelector("[data-hs-modal]");
  if (!config || !modal || !window.ForwardusHs) return;

  const { escapeHtml, getJson, setupAutocomplete } = window.Forwardus;
  const { fetchHsCodes, renderHsItem, HS_AUTOCOMPLETE_OPTIONS } = window.ForwardusHs;

  const box = modal.querySelector("[data-hs-ac]");
  const input = box.querySelector("[data-ac-input]");
  const list = box.querySelector("[data-ac-list]");
  const orderEl = modal.querySelector("[data-hs-order]");
  const countryEl = modal.querySelector("[data-hs-country]");
  const chipsEl = modal.querySelector("[data-hs-chips]");
  const targetEl = modal.querySelector("[data-hs-target]");
  const statusEl = modal.querySelector("[data-hs-status]");

  // 올린 서류·상담에서 알게 된 품명.
  //
  // 그 회원이 찾아본 기록이라 회원마다 따로 두고, 다시 로그인하면 그대로
  // 있게 합니다. 그래서 탭과 함께 사라지는 sessionStorage가 아니라
  // localStorage에 둡니다. 로그아웃해도 지우지 않습니다. (base.js ForwardusStore)
  //
  // 로그인하지 않은 손님은 그대로 sessionStorage입니다. 누구 것인지 가릴 수
  // 없어서, 오래 남기면 다음에 이 컴퓨터를 쓰는 손님에게 넘어갑니다.
  const STORE_KEY = window.ForwardusStore.key("forwardus:hs-queries");
  const store = window.ForwardusStore.scope === "guest"
    ? window.sessionStorage : window.localStorage;
  const MAX_REMEMBERED = 8;

  let target = null;
  let returnFocus = null;
  let countries = null;

  const controller = setupAutocomplete(
    box,
    (q) => fetchHsCodes(q, "", { url: config.hsCodesUrl, country: countryEl.value,
                                 order: orderEl.value }),
    renderHsItem,
    (item) => { if (item) pick(item); },
    // 칸을 누를 때마다 다시 찾으면 AI 비교를 또 돌립니다. 적힌 말은 그대로 둡니다.
    { ...HS_AUTOCOMPLETE_OPTIONS, focusShowsAll: false },
  );

  function research() {
    if (input.value.trim()) controller.search();
  }
  orderEl.addEventListener("change", research);
  countryEl.addEventListener("change", research);

  /* ----- 기억해 둔 품명 ----- */
  function remembered() {
    try {
      const rows = JSON.parse(store.getItem(STORE_KEY) || "[]");
      return Array.isArray(rows) ? rows.filter((row) => typeof row === "string") : [];
    } catch (error) {
      return [];
    }
  }

  // 새로 알게 된 것이 앞에 옵니다. 같은 품명은 한 번만 둡니다.
  function remember(queries) {
    const fresh = (Array.isArray(queries) ? queries : [queries])
      .map((row) => String(row || "").trim()).filter((row) => row.length >= 2);
    if (!fresh.length) return;
    const merged = [...new Set([...fresh, ...remembered()])].slice(0, MAX_REMEMBERED);
    try {
      store.setItem(STORE_KEY, JSON.stringify(merged));
    } catch (error) {
      /* 저장 공간이 없으면 이번에만 씁니다. */
    }
  }

  function renderChips(queries) {
    const current = input.value.trim();
    chipsEl.innerHTML = queries.filter((row) => row !== current).slice(0, 5)
      .map((row) => `<button type="button" class="hs_chip">${escapeHtml(row)}</button>`).join("");
  }

  chipsEl.addEventListener("click", (event) => {
    const chip = event.target.closest(".hs_chip");
    if (!chip) return;
    input.value = chip.textContent;
    renderChips(remembered());
    controller.search();
    input.focus();
  });

  /* ----- 도착국 (관세 비교 기준) ----- */
  async function loadCountries() {
    if (countries) return;
    const response = await getJson(`${config.countriesUrl}?${new URLSearchParams({
      mode: "SEA", role: "destination" })}`);
    countries = response.success ? response.data : [];
    // 교역 상위국을 위에, 나머지는 가나다순. (운송 계획의 도착지 거르기와 같은 순서)
    const top = countries.filter((c) => c.trade_rank).sort((a, b) => a.trade_rank - b.trade_rank);
    const rest = countries.filter((c) => !c.trade_rank)
      .sort((a, b) => a.name.localeCompare(b.name, "ko"));
    const option = (c) => `<option value="${escapeHtml(c.code)}">${escapeHtml(c.name)}</option>`;
    countryEl.insertAdjacentHTML("beforeend",
      (top.length ? `<optgroup label="주요 무역국">${top.map(option).join("")}</optgroup>` : "")
      + (rest.length ? `<optgroup label="그 밖의 나라">${rest.map(option).join("")}</optgroup>` : ""));
  }

  function setCountry(code) {
    const value = String(code || "").trim().toUpperCase();
    if (value && Array.from(countryEl.options).some((option) => option.value === value)) {
      countryEl.value = value;
    }
  }

  /* ----- 고르기 ----- */
  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (error) {
      // http 주소나 권한이 없으면 clipboard API가 막힙니다. 예전 방식으로 한 번 더 해 봅니다.
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      let done = false;
      try { done = document.execCommand("copy"); } catch (ignored) { done = false; }
      area.remove();
      return done;
    }
  }

  function status(message, kind = "") {
    statusEl.textContent = message;
    statusEl.className = `hs_modal_status ${kind}`.trim();
    statusEl.hidden = !message;
  }

  async function pick(item) {
    const code = String(item.code || "").replace(/\D/g, "");
    // 6자리는 국제 공통 부분까지입니다. 수출신고에는 10자리가 있어야 합니다.
    const partial = item.partial || code.length !== 10;
    const warn = partial ? " 앞 6자리까지만 확인된 부호라 신고 전에 10자리를 확인해야 합니다." : "";

    if (target) {
      // 넣은 칸 쪽이 눈에 띄게 알려 줍니다. 6자리인지도 함께 넘깁니다.
      const chosen = target;
      close();
      chosen.apply(code, item, { partial, warning: warn.trim() });
      return;
    }
    const copied = await copy(code);
    status(copied ? `HS부호 ${code}를 복사했습니다. 붙여넣기(Ctrl+V)로 쓰세요.${warn}`
                  : `복사하지 못했습니다. HS부호는 ${code}입니다.${warn}`, partial ? "warn" : "ok");
    // 목록은 그대로 둡니다. 다른 후보와 견주어 보는 일이 많습니다.
    list.hidden = false;
  }

  /* ----- 열고 닫기 ----- */
  // opts: { query, queries, country, target: { label, apply(code, item, { partial, warning }) } }
  async function open(opts = {}) {
    returnFocus = document.activeElement;
    target = opts.target && typeof opts.target.apply === "function" ? opts.target : null;
    if (opts.queries) remember(opts.queries);
    if (opts.query) remember(opts.query);

    targetEl.hidden = false;
    targetEl.textContent = target
      ? `후보를 누르면 ${target.label}에 바로 넣습니다.`
      : "후보를 누르면 HS부호를 클립보드에 복사합니다.";
    status("");
    const known = remembered();
    input.value = String(opts.query || known[0] || "").trim();
    renderChips(known);
    list.hidden = true;

    modal.hidden = false;
    document.body.classList.add("hs_modal_open");
    input.focus();

    await loadCountries();
    setCountry(opts.country);
    // 품명이 이미 있으면 누르지 않아도 바로 찾습니다.
    if (input.value.length >= 2) controller.search();
  }

  function close() {
    if (modal.hidden) return;
    modal.hidden = true;
    target = null;
    document.body.classList.remove("hs_modal_open");
    if (returnFocus && returnFocus.isConnected) returnFocus.focus();
  }

  modal.addEventListener("click", (event) => {
    if (event.target.closest("[data-hs-close]")) close();
  });

  document.addEventListener("keydown", (event) => {
    if (modal.hidden) return;
    if (event.key === "Escape") {
      event.stopPropagation();
      close();
      return;
    }
    // 창이 떠 있는 동안 Tab이 뒤쪽 화면으로 빠져나가지 않게 합니다.
    if (event.key === "Tab") {
      const focusable = Array.from(modal.querySelectorAll(
        "button, input, select, a[href], [tabindex]:not([tabindex='-1'])"))
        .filter((el) => !el.disabled && el.offsetParent !== null);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  }, true);

  // 상담 답변의 [HS CODE 조회](#hs:립스틱) 링크나 화면의 단추. 페이지를 옮기지 않고 창을 띄웁니다.
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-hs-open]");
    if (!trigger || modal.contains(trigger)) return;
    event.preventDefault();
    // data-hs-fill="#선택자" 를 주면 고른 후보를 그 칸에 바로 넣습니다.
    // 단추만으로는 함수를 넘길 수 없어, 선택자로 받아 여기서 target을 만듭니다.
    // (이게 없으면 "클립보드에 복사"로 떨어져, 찾아 놓고 손으로 옮겨 적어야 합니다)
    const fill = trigger.dataset.hsFill
      ? document.querySelector(trigger.dataset.hsFill) : null;
    const target = fill ? {
      label: trigger.dataset.hsFillLabel || "HS부호 칸",
      apply(code) {
        fill.value = code;
        fill.dispatchEvent(new Event("input", { bubbles: true }));
        fill.dispatchEvent(new Event("change", { bubbles: true }));
        fill.focus();
      },
    } : null;
    open({ query: trigger.dataset.hsQuery || "",
           country: trigger.dataset.hsCountry || "",
           target });
  });

  window.ForwardusHsModal = { open, close, remember, remembered };
})();
