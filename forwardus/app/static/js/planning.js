/* Shipment Planning: wizard (planning/new) and Reverse Schedule Planner (planning/index). */
(function () {
  "use strict";

  const { escapeHtml, postJson, getJson, formatNumber, toIsoDate, plainNumber,
        setupNumberInput } = window.Forwardus;

  /* ---------- Shared: segmented toggles ---------- */
  function bindToggle(group, onChange) {
    group.querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", () => {
        group.querySelectorAll("button").forEach((b) => {
          b.classList.toggle("active", b === button);
          b.setAttribute("aria-pressed", b === button ? "true" : "false");
        });
        onChange(button.dataset.value);
      });
    });
  }

  /* ---------- Reverse Schedule Planner ---------- */
  const reverseForm = document.querySelector("[data-reverse-form]");
  if (reverseForm) {
    let reverseMode = "SEA";
    bindToggle(reverseForm.querySelector("[data-toggle=transport_mode]"), (value) => { reverseMode = value; });
    const resultBox = document.querySelector("[data-reverse-result]");
    const errorBox = reverseForm.querySelector("[data-form-error]");

    reverseForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      errorBox.hidden = true;
      const response = await postJson(reverseForm.dataset.url, {
        buyer_required_date: reverseForm.buyer_required_date.value,
        transport_mode: reverseMode,
        transit_days: plainNumber(reverseForm.transit_days.value),
      });
      if (!response.success) {
        errorBox.textContent = response.message;
        errorBox.hidden = false;
        return;
      }
      const plan = response.data;
      const steps = plan.steps.map((step) => `
        <li class="${step.date ? "milestone" : "duration"}">
          <span>${escapeHtml(step.label)}</span>
          <b>${step.date ? escapeHtml(step.date) : `${step.days}일`}</b>
        </li>`).join("");
      const warnings = plan.warnings.map((w) => `<div class="flash flash_error">${escapeHtml(w)}</div>`).join("");
      resultBox.innerHTML = `
        <div class="row_between"><h2>역산 결과</h2><span class="badge source_calculated">Data Source: Calculated</span></div>
        ${warnings}
        <dl class="kpi_row">
          <div><dt>Recommended ETA</dt><dd>${plan.recommended_eta}</dd></div>
          <div><dt>Recommended ETD</dt><dd>${plan.recommended_etd}</dd></div>
          <div class="highlight"><dt>Cargo Ready Date</dt><dd>${plan.cargo_ready_date}</dd></div>
        </dl>
        <ol class="reverse_steps">${steps}</ol>`;
    });
  }

  /* ---------- Planning wizard ---------- */
  const form = document.getElementById("planning_form");
  if (!form) return;

  const urls = window.FORWARDUS_URLS;
  const state = {
    step: 1,
    transport_mode: "SEA",
    sea_mode: "FCL",
    departure_date: null,
    origin: null,
    destination: null,
    metrics: null,
    schedules: [],
    schedule_id: null,
    sort: "recommended",
  };

  // 예상 일정 조회를 묶어서 보내기 위한 타이머. (선언 순서 문제를 피해 위쪽에 둡니다)
  let departureCheckTimer;

  // 관세청 고시 환율. 운임을 원화로 함께 보여주는 데 씁니다.
  let krwRates = null;
  let rateBasis = "";
  async function loadRates() {
    const response = await getJson(urls.exchangeRate);
    if (!response.success) return;
    krwRates = response.data;
    rateBasis = response.basis || "";
    // 이미 그려 둔 금액이 있으면 환율이 도착한 뒤 기준을 덧붙입니다.
    document.querySelectorAll("[data-rate-basis]").forEach((el) => { el.textContent = rateBasis; });
  }
  loadRates();

  function inKrw(amount, currency = "USD") {
    const rate = krwRates ? krwRates[currency] : null;
    if (!rate || !amount) return "";
    return `약 ₩${formatNumber(Math.round(amount * rate), 0)}`;
  }

  const errorBox = document.querySelector("[data-form-error]");

  /* ----- 입력값 임시 저장: 다른 메뉴에 다녀와도 내용이 남습니다 ----- */
  // 탭을 새로 열면 빈 화면에서 시작하고, 메뉴를 오갈 때만 입력이 유지되도록
  // sessionStorage를 씁니다. (브라우저를 닫으면 사라집니다)
  const DRAFT_KEY = "forwardus:planning-draft";
  const draftStore = window.sessionStorage;

  const DRAFT_FIELDS = [
    "project_name", "buyer_required_date", "product_description", "hs_code", "package_type",
    "quantity", "length_cm", "width_cm", "height_cm", "weight_per_package_kg", "net_weight_kg",
    "currency", "invoice_value", "exporter_name", "exporter_address", "notify_party",
    "buyer_name", "buyer_country", "buyer_address", "buyer_email",
  ];

  function saveDraft() {
    const fields = {};
    DRAFT_FIELDS.forEach((name) => {
      const input = form.elements[name];
      if (input) fields[name] = input.value;
    });
    const incoterm = form.querySelector("input[name=incoterms]:checked");
    const draft = {
      savedAt: Date.now(),
      step: state.step,
      transport_mode: state.transport_mode,
      sea_mode: state.sea_mode,
      departure_date: state.departure_date,
      cargo_dg: dgValues(mainDgBox),
      cargo_lines: extraCargoLines(),
      origin: state.origin,
      destination: state.destination,
      schedule_id: state.schedule_id,
      sort: state.sort,
      incoterms: incoterm ? incoterm.value : "",
      country: (form.querySelector("[data-country-filter]") || {}).value || "",
      fields,
    };
    try {
      draftStore.setItem(DRAFT_KEY, JSON.stringify(draft));
    } catch (error) {
      /* 저장 공간이 없으면 그냥 넘어갑니다. */
    }
  }

  function clearDraft() {
    try {
      draftStore.removeItem(DRAFT_KEY);
    } catch (error) { /* 무시 */ }
  }

  function loadDraft() {
    try {
      return JSON.parse(draftStore.getItem(DRAFT_KEY) || "null");
    } catch (error) {
      return null;
    }
  }

  const saveDraftSoon = (() => {
    let timer;
    return () => { clearTimeout(timer); timer = setTimeout(saveDraft, 400); };
  })();

  form.addEventListener("input", saveDraftSoon);
  form.addEventListener("change", saveDraftSoon);
  window.addEventListener("beforeunload", saveDraft);
  const FIELD_STEP = {
    project_name: 1, transport_mode: 1, sea_mode: 1, origin_code: 1, destination_code: 1,
    requested_departure_date: 1, buyer_required_date: 1,
    incoterms: 2,
    product_description: 3, hs_code: 3, package_type: 3, quantity: 3, length_cm: 3, width_cm: 3,
    height_cm: 3, weight_per_package_kg: 3, net_weight_kg: 3, invoice_value: 3, currency: 3,
    schedule_id: 4,
    exporter_name: 5, buyer_name: 5,
  };

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = !message;
    if (message) errorBox.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function goToStep(step) {
    state.step = step;
    form.querySelectorAll("[data-step]").forEach((section) => {
      section.hidden = Number(section.dataset.step) !== step;
    });
    document.querySelectorAll("[data-step-tab]").forEach((tab) => {
      const n = Number(tab.dataset.stepTab);
      tab.classList.toggle("active", n === step);
      tab.classList.toggle("done", n < 5 && !validateStep(n));
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  /* ----- Calendar ----- */
  const calendarEl = document.querySelector("[data-calendar]");
  const selectedDateEl = document.querySelector("[data-selected-date]");
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  let viewMonth = new Date(today.getFullYear(), today.getMonth(), 1);

  const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
  // 달력을 누를 때마다 출발 예정일 -> Buyer 요청일 -> 출발 예정일 … 순으로 채웁니다.
  let pickTarget = "departure";

  function monthHtml(base, offset) {
    const year = base.getFullYear();
    const month = base.getMonth() + offset;
    const first = new Date(year, month, 1);
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const buyerDate = form.elements.buyer_required_date.value;

    const departure = state.departure_date;
    let cells = "";
    for (let i = 0; i < first.getDay(); i += 1) cells += "<span></span>";
    for (let day = 1; day <= daysInMonth; day += 1) {
      const date = new Date(year, month, day);
      const iso = toIsoDate(date);
      const classes = [];
      if (departure === iso) classes.push("selected");
      if (buyerDate === iso) classes.push("buyer");
      if (date.getTime() === today.getTime()) classes.push("today");
      // 출발일과 요청일 사이는 여유 등급에 따라 색을 달리합니다.
      if (departure && buyerDate && iso > departure && iso < buyerDate) {
        classes.push("in_range");
      }
      // 출발일은 요청일보다 뒤로, 요청일은 출발일보다 앞으로 갈 수 없습니다.
      // Buyer 요청일을 고를 때만 출발일 이전 날짜를 막습니다.
      const blocked = pickTarget === "buyer" && departure && iso < departure;
      if (blocked) classes.push("blocked");
      cells += `<button type="button" data-date="${iso}" ${date < today || blocked ? "disabled" : ""}`
        + ` class="${classes.join(" ")}">${day}</button>`;
    }
    return `<div class="cal_month">
      <div class="cal_title">${first.getFullYear()}년 ${first.getMonth() + 1}월</div>
      <div class="cal_week">${WEEKDAYS.map((d) => `<span>${d}</span>`).join("")}</div>
      <div class="cal_grid">${cells}</div>
    </div>`;
  }

  function renderCalendar() {
    const canGoBack = viewMonth > new Date(today.getFullYear(), today.getMonth(), 1);
    calendarEl.innerHTML = `
      <div class="cal_head">
        <button type="button" data-cal-prev ${canGoBack ? "" : "disabled"} aria-label="이전 달">‹</button>
        <b>일정 선택</b>
        <button type="button" data-cal-next aria-label="다음 달">›</button>
      </div>
      <div class="cal_months">${monthHtml(viewMonth, 0)}${monthHtml(viewMonth, 1)}</div>
      <p class="cal_legend">
        <span class="legend_departure">Seller 예상일</span>
        <span class="legend_buyer">Buyer 요청 도착일</span>
        <span class="legend_range">예상 운송 기간</span>
      </p>
      <p class="cal_hint">다음 선택: <b>${pickTarget === "departure" ? "Seller 예상일" : "Buyer 요청 도착일"}</b>
        · 날짜를 누를 때마다 Seller 예상일 → Buyer 요청일 순서로 지정되고,
        Seller 예상일을 다시 고르면 Buyer 요청일은 지워집니다.</p>`;
  }

  calendarEl.addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target || target.disabled) return;
    if (target.hasAttribute("data-cal-prev")) viewMonth.setMonth(viewMonth.getMonth() - 1);
    else if (target.hasAttribute("data-cal-next")) viewMonth.setMonth(viewMonth.getMonth() + 1);
    else if (target.dataset.date) {
      const iso = target.dataset.date;
      const buyerInput = form.elements.buyer_required_date;
      if (pickTarget === "departure") {
        // 새 일정을 고르는 것이므로 Buyer 요청일을 비워 선택 상태를 분명히 합니다.
        state.departure_date = iso;
        buyerInput.value = "";
        pickTarget = "buyer";
      } else {
        if (state.departure_date && iso < state.departure_date) {
          showError("Buyer 요청 도착일은 Seller 예상일보다 빠를 수 없습니다.");
          return;
        }
        buyerInput.value = iso;
        pickTarget = "departure";
      }
      showError("");
      updateSelectedDates();
      invalidateSchedules();
      saveDraftSoon();
      return;
    }
    renderCalendar();
  });
  renderCalendar();

  /* ----- 포장 유형: 해상·항공에 맞는 것만 보여줍니다 ----- */
  function applyPackageTypes(mode) {
    const select = form.elements.package_type;
    const note = document.querySelector("[data-package-note]");
    if (!select) return;

    let firstUsable = null;
    Array.from(select.options).forEach((option) => {
      const usable = (option.dataset.modes || "").split(",").includes(mode);
      option.hidden = !usable;
      option.disabled = !usable;
      if (usable && !firstUsable) firstUsable = option.value;
    });
    // 고른 포장이 그 운송수단에 없으면 첫 번째 것으로 바꿉니다.
    const current = select.selectedOptions[0];
    if ((!current || current.disabled) && firstUsable) select.value = firstUsable;
    if (note) note.textContent = select.selectedOptions[0]?.dataset.note || "";
  }

  /* ----- Transport mode toggles ----- */
  function applyMode() {
    const isAir = state.transport_mode === "AIR";
    document.querySelectorAll("[data-air-only]").forEach((el) => { el.hidden = !isAir; });
    document.querySelectorAll("[data-sea-only]").forEach((el) => { el.hidden = isAir; });
    document.querySelectorAll("[data-kind-label]").forEach((el) => { el.textContent = isAir ? "공항" : "항구"; });
    // 해상 전용 조건도 고를 수는 있게 두고, 고른 운송수단과 맞지 않으면
    // 아이콘으로만 알려줍니다. (막아 두면 왜 못 고르는지 알기 어렵습니다)
    document.querySelectorAll("[data-sea-only-term]").forEach((card) => {
      card.classList.toggle("mismatch", isAir);
    });
    applyPackageTypes(isAir ? "AIR" : "SEA");
    // 같은 위험물이라도 해상과 항공의 규정이 달라 안내를 다시 그립니다.
    refreshAllDgGuides();
    document.querySelectorAll("[data-metric-sea]").forEach((el) => { el.hidden = isAir; });
    document.querySelectorAll("[data-metric-fcl]").forEach((el) => { el.hidden = isAir || state.sea_mode !== "FCL"; });
    document.querySelectorAll("[data-metric-air]").forEach((el) => { el.hidden = !isAir; });
  }

  bindToggle(form.querySelector("[data-toggle=transport_mode]"), (value) => {
    if (value === state.transport_mode) return;
    state.transport_mode = value;
    // Ports and airports differ, so the chosen locations no longer apply.
    ["origin", "destination"].forEach((role) => {
      state[role] = null;
      form.querySelector(`[data-autocomplete=${role}] [data-ac-input]`).value = "";
    });
    applyMode();
    refreshCountryOptions();
    invalidateSchedules();
    saveDraftSoon();
    updateSelectedDates();
    refreshOutlook();
  });
  bindToggle(form.querySelector("[data-toggle=sea_mode]"), (value) => {
    state.sea_mode = value;
    applyMode();
    invalidateSchedules();
    saveDraftSoon();
    refreshOutlook();   // FCL/LCL에 따라 소요일과 안내가 달라집니다.
  });
  applyMode();

  /* ----- Autocomplete ----- */
  function debounce(fn, wait) {
    let timer;
    return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); };
  }

  function setupAutocomplete(container, fetchItems, renderItem, onSelect, options = {}) {
    const input = container.querySelector("[data-ac-input]");
    const list = container.querySelector("[data-ac-list]");
    let items = [];

    let overrideQuery = null;

    const search = debounce(async () => {
      list.innerHTML = `<li class="empty">검색 중…</li>`;
      list.hidden = false;
      const query = overrideQuery === null ? input.value.trim() : overrideQuery;
      overrideQuery = null;
      items = await fetchItems(query);
      if (!items.length) {
        const message = options.emptyMessage
          ? options.emptyMessage()
          : `검색 결과가 없습니다. 목록에 없으면 "직접 입력"을 사용하세요.`;
        list.innerHTML = `<li class="empty">${escapeHtml(message)}</li>`;
        return;
      }
      let html = "";
      if (options.groupBy) {
        // 같은 그룹을 한 번만 표시합니다. 서버가 보내는 순서가 섞여 있어도
        // 머리글이 중복되지 않도록 그룹별로 모아서 그립니다.
        const groups = new Map();
        items.forEach((item, index) => {
          const value = options.groupBy(item);
          if (!groups.has(value)) groups.set(value, []);
          groups.get(value).push({ item, index });
        });
        groups.forEach((entries, value) => {
          const other = value === "환승 필요" || value === "환적 필요"
            || value === "정기 항로 확인 필요";
          const GROUP_NOTES = {
            "환승 필요": "고른 출발 공항에서 직항편이 없어 환승이 필요합니다",
            "환적 필요": "한국에서 직기항 선박이 없어 환적항을 거칩니다",
            "정기 항로 확인 필요": "정기 항로 기록이 없어 선사에 확인이 필요합니다",
          };
          const note = GROUP_NOTES[value];
          html += `<li class="ac_group${other ? " ac_group_other" : ""}">${escapeHtml(value)}`
            + (note ? `<small>${escapeHtml(note)}</small>` : "")
            + `</li>`;
          entries.forEach(({ item, index }) => {
            html += `<li role="option" data-index="${index}">${renderItem(item)}</li>`;
          });
        });
      } else {
        items.forEach((item, index) => {
          html += `<li role="option" data-index="${index}">${renderItem(item)}</li>`;
        });
      }
      list.innerHTML = html;
      // 목록을 그린 뒤 덧붙일 것이 있으면 (예: HS 후보별 협정) 이어서 채웁니다.
      if (options.afterRender) options.afterRender(items, list);
    }, 200);

    input.addEventListener("input", () => { onSelect(null, input); search(); });
    // 이미 고른 항구가 있어도 다시 누르면 전체 목록을 보여줍니다.
    input.addEventListener("focus", () => {
      input.select();
      overrideQuery = "";
      search();
    });
    input.addEventListener("blur", () => setTimeout(() => { list.hidden = true; }, 150));
    list.addEventListener("mousedown", (event) => {
      const li = event.target.closest("li[data-index]");
      if (!li) return;
      onSelect(items[Number(li.dataset.index)], input);
      list.hidden = true;
    });
    return {
      search,
      showAll() {
        overrideQuery = "";
        search();
      },
      // 목록이 열려 있을 때만 다시 그립니다. 닫혀 있는데 다시 검색하면
      // 이미 고른 값("로테르담항 (NLRTM)")으로 검색해 빈 목록이 떠 버립니다.
      refresh() {
        if (!list.hidden) search();
      },
    };
  }

  /* ----- Destination country filter and direct input ----- */
  const countryCache = {};

  async function loadCountries(mode) {
    if (!countryCache[mode]) {
      const response = await getJson(`${urls.countries}?${new URLSearchParams({ mode, role: "destination" })}`);
      countryCache[mode] = response.success ? response.data : [];
    }
    return countryCache[mode];
  }

  function countryOption(c) {
    return `<option value="${escapeHtml(c.code)}">${escapeHtml(c.name)} (${c.count.toLocaleString("ko-KR")})</option>`;
  }

  // 운임 구간(region)을 대륙 이름으로 묶어 보여줍니다.
  const CONTINENTS = [
    ["asia", "아시아"],
    ["middle_east", "중동"],
    ["europe", "유럽"],
    ["americas", "북미·중미"],
    ["south_america", "남미"],
    ["africa", "아프리카"],
    ["oceania", "오세아니아"],
  ];

  async function refreshCountryOptions() {
    const countries = await loadCountries(state.transport_mode);
    const place = state.transport_mode === "AIR" ? "공항" : "항만";
    // 한국 교역액 상위 국가를 맨 위에, 나머지는 대륙별로 가나다순 정렬합니다.
    const top = countries.filter((c) => c.trade_rank).sort((a, b) => a.trade_rank - b.trade_rank);
    let optionsHtml = top.length
      ? `<optgroup label="주요 무역국">${top.map(countryOption).join("")}</optgroup>`
      : "";
    CONTINENTS.forEach(([region, label]) => {
      const group = countries
        .filter((c) => c.region === region)
        .sort((a, b) => a.name.localeCompare(b.name, "ko"));
      if (group.length) {
        optionsHtml += `<optgroup label="${label} (${group.length}개국)">`
          + group.map(countryOption).join("") + "</optgroup>";
      }
    });
    const other = countries.filter((c) => !CONTINENTS.some(([region]) => region === c.region));
    if (other.length) {
      optionsHtml += `<optgroup label="기타">`
        + other.sort((a, b) => a.name.localeCompare(b.name, "ko")).map(countryOption).join("")
        + "</optgroup>";
    }
    const filter = form.querySelector("[data-country-filter]");
    if (filter) {
      const current = filter.value;
      filter.innerHTML = `<option value="">국가 전체 (주요 ${place}만 표시)</option>${optionsHtml}`;
      filter.value = current;
    }
    const customCountry = form.querySelector("[data-autocomplete=destination] [data-custom-country]");
    if (customCountry) customCountry.innerHTML = `<option value="">국가 선택</option>${optionsHtml}`;
  }

  function setupCustomInput(role) {
    const container = form.querySelector(`[data-autocomplete=${role}]`);
    const box = container.querySelector("[data-custom]");
    const input = container.querySelector("[data-ac-input]");
    const codeInput = box.querySelector("[data-custom-code]");
    const nameInput = box.querySelector("[data-custom-name]");
    const suggestList = box.querySelector("[data-custom-list]");
    const countrySelect = box.querySelector("[data-custom-country]");

    // 이름을 입력하면 실제 UN/LOCODE 후보를 보여줍니다.
    let suggestions = [];
    const suggest = debounce(async () => {
      const query = nameInput.value.trim();
      if (!query) {
        suggestList.hidden = true;
        return;
      }
      const params = new URLSearchParams({ q: query, role, mode: state.transport_mode });
      if (countrySelect && countrySelect.value) params.set("country", countrySelect.value);
      const response = await getJson(`${urls.unlocode}?${params}`);
      suggestions = response.success ? response.data : [];
      suggestList.innerHTML = suggestions.length
        ? suggestions.map((item, index) => `<li role="option" data-index="${index}">`
          + `<span class="ac_title"><b>${escapeHtml(item.name)}</b>`
          + (item.major && item.kind !== "airport" ? `<em class="ac_note">주요 항구</em>` : "")
          + (item.direct_from_korea ? `<em class="ac_note direct">직항</em>` : "")
          + `</span><span class="mono">${escapeHtml(item.code)}</span>`
          + `<small>${escapeHtml(item.name_en)}</small></li>`).join("")
        : `<li class="empty">${state.transport_mode === "AIR"
            ? "공항을 찾지 못했습니다. 공항 이름(예: 대구)이나 IATA 코드(예: TAE)를 입력해보세요."
            : "UN/LOCODE에서 찾지 못했습니다. 나라 이름(예: 베트남)이나 항구 이름을 입력해보세요."}</li>`;
      suggestList.hidden = false;
    }, 200);

    nameInput.addEventListener("input", suggest);
    nameInput.addEventListener("focus", suggest);
    nameInput.addEventListener("blur", () => setTimeout(() => { suggestList.hidden = true; }, 150));
    suggestList.addEventListener("mousedown", (event) => {
      const li = event.target.closest("li[data-index]");
      if (!li) return;
      const item = suggestions[Number(li.dataset.index)];
      codeInput.value = item.code;
      nameInput.value = item.name;
      if (countrySelect) countrySelect.value = item.country_code;
      suggestList.hidden = true;
    });
    if (countrySelect) countrySelect.addEventListener("change", suggest);

    container.querySelector("[data-custom-toggle]").addEventListener("click", () => {
      box.hidden = !box.hidden;
      if (!box.hidden) nameInput.focus();
    });

    container.querySelector("[data-custom-apply]").addEventListener("click", () => {
      const code = codeInput.value.trim().toUpperCase();
      const name = nameInput.value.trim();
      const countryCode = countrySelect ? countrySelect.value : "KR";
      if (!name) {
        showError("직접 입력하려면 항구·공항 이름을 입력해주세요.");
        return;
      }
      if (!countryCode) {
        showError("직접 입력하려면 국가를 선택해주세요.");
        return;
      }
      showError("");
      // 코드는 선택 사항입니다. 비우면 서버가 이름을 기준으로 임시 코드를 부여합니다.
      state[role] = { code, name, country_code: countryCode, custom: true };
      input.value = code ? `${name} (${code})` : name;
      box.hidden = true;
      invalidateSchedules();
      refreshOutlook();
    });
  }

  const locationSearch = {};
  ["origin", "destination"].forEach((role) => {
    const container = form.querySelector(`[data-autocomplete=${role}]`);
    const countryFilter = container.querySelector("[data-country-filter]");
    locationSearch[role] = setupAutocomplete(
      container,
      async (q) => {
        const params = new URLSearchParams({ q, mode: state.transport_mode, role });
        if (countryFilter && countryFilter.value) params.set("country", countryFilter.value);
        // 출발 공항을 알면 그 공항 기준으로 직항 여부를 판정합니다.
        if (role === "destination" && state.origin) params.set("origin", state.origin.code);
        const response = await getJson(`${urls.locations}?${params}`);
        return response.success ? response.data : [];
      },
      (item) => {
        const size = item.kind === "airport"
          ? ""
          : ({ L: "대형항", M: "중형항", S: "소형항", V: "소규모" }[item.harbor_size] || "");
        const note = item.note ? `<em class="ac_note">${escapeHtml(item.note)}</em>` : "";
        // 직항·직기항은 "한국에서 그곳까지 갈아타지 않고 가는 편이 있는가"이므로
        // 도착지에만 붙입니다.
        const direct = role !== "destination" ? ""
          : item.kind === "airport"
            ? (item.direct_from_korea ? `<em class="ac_note direct">직항</em>` : "")
            : (item.sea_direct ? `<em class="ac_note direct">직기항</em>` : "");
        const cargo = item.korean_air_cargo
          ? `<em class="ac_note cargo">KE 화물</em>`
          : (item.cargo_hub ? `<em class="ac_note cargo">화물 거점</em>` : "");
        // 다른 국내 공항에서는 직항이 있으면 그것부터 알려줍니다.
        const alternatives = item.kind === "airport" && !item.direct_from_korea
          ? (item.direct_from || []) : [];
        const viaLabel = item.gateway_only ? "국제선 없음 · 대체 공항"
          : (item.kind === "port" ? "환적" : "경유");
        const viaList = item.kind === "port" ? item.sea_transfer_via : item.transfer_via;
        const via = alternatives.length
          ? `<small class="ac_via">${alternatives.map(escapeHtml).join(" · ")} 출발은 직항</small>`
          : (viaList || []).length
            ? `<small class="ac_via">${viaLabel}: ${viaList
                .map(([code, name]) => `${escapeHtml(name)}(${escapeHtml(code)})`).join(" · ")}</small>`
            : "";
        return `<span class="ac_title"><b>${escapeHtml(item.name)}</b>${note}${cargo}${direct}</span>`
          + `<span class="mono">${escapeHtml(item.code)}</span>`
          + `<small>${escapeHtml(item.name_en)} · ${escapeHtml(item.country)}${size ? ` · ${size}` : ""}</small>`
          + via;
      },
      (item, input) => {
        state[role] = item;
        if (item) input.value = `${item.name} (${item.code})`;
        if (role === "origin") {
          // 출발지가 바뀌면 도착지의 직항 표시가 달라집니다.
          locationSearch.destination?.refresh();
        }
        invalidateSchedules();
        saveDraftSoon();
        updateSelectedDates();
        refreshOutlook();
        refreshTariff();
        refreshAllDgGuides();   // 도착국이 바뀌면 위험물 안내 문구도 바뀝니다.
      },
      {
        // 국내는 국가관리 -> 지방관리 순, 해외는 국가별로 묶고,
        // 규모가 작은 항구는 맨 아래 "기타 항구"로 모읍니다.
        groupBy: (item) => {
          if (role === "destination" && state.transport_mode === "AIR") {
            // 고른 출발 공항에서 직항이 있는 곳을 위로, 환승이 필요한 곳을 아래로.
            const from = state.origin ? `${state.origin.code} 출발 ` : "";
            if (!item.direct_from_korea) return "환승 필요";
            return item.cargo_hub ? `${from}직항 · 항공화물 거점` : `${from}직항 노선`;
          }
          if (role === "destination" && state.transport_mode === "SEA") {
            // 한국에서 직기항 선박이 있는 항구를 위로, 환적이 필요한 항구를 아래로.
            if (item.sea_direct) return "한국 직기항 노선";
            return item.sea_direct === false ? "환적 필요" : "정기 항로 확인 필요";
          }
          if (role === "destination") return item.country;
          if (item.port_class === "national") return "국가관리 무역항";
          if (item.port_class === "local") return "지방관리 무역항";
          return state.transport_mode === "AIR" ? "주요 공항" : "주요 항구";
        },
      },
    );
    setupCustomInput(role);
    if (countryFilter) {
      countryFilter.addEventListener("change", () => {
        container.querySelector("[data-ac-input]").focus();
        locationSearch[role].showAll();
      });
    }
  });
  refreshCountryOptions();

  async function restoreDraft() {
    const draft = loadDraft();
    if (!draft) return;

    DRAFT_FIELDS.forEach((name) => {
      const input = form.elements[name];
      if (input && draft.fields && draft.fields[name] !== undefined) input.value = draft.fields[name];
    });
    if (draft.incoterms) {
      const radio = form.querySelector(`input[name=incoterms][value="${draft.incoterms}"]`);
      if (radio) radio.checked = true;
    }
    if (draft.transport_mode && draft.transport_mode !== state.transport_mode) {
      const button = form.querySelector(`[data-toggle=transport_mode] [data-value=${draft.transport_mode}]`);
      if (button) button.click();
    }
    if (draft.sea_mode && draft.sea_mode !== state.sea_mode) {
      const button = form.querySelector(`[data-toggle=sea_mode] [data-value=${draft.sea_mode}]`);
      if (button) button.click();
    }
    ["origin", "destination"].forEach((role) => {
      const item = draft[role];
      if (!item) return;
      state[role] = item;
      form.querySelector(`[data-autocomplete=${role}] [data-ac-input]`).value = `${item.name} (${item.code})`;
    });
    setDgValues(mainDgBox, draft.cargo_dg);
    (draft.cargo_lines || []).forEach((line) => addCargoLine(line));
    if (draft.departure_date) {
      state.departure_date = draft.departure_date;
      const [year, month] = draft.departure_date.split("-").map(Number);
      viewMonth = new Date(year, month - 1, 1);
    }
    updateSelectedDates();
    refreshOutlook();
    refreshTariff();
    const filter = form.querySelector("[data-country-filter]");
    if (filter && draft.country) filter.value = draft.country;
    state.sort = draft.sort || state.sort;
    state.schedule_id = draft.schedule_id || null;

    recalc();
    if (draft.step && draft.step > 1) await openStep(draft.step);
  }

  updateSelectedDates();   // 임시저장이 없을 때도 날짜 표시를 채웁니다.

  /* ----- 도착국에 적용되는 협정·세율 ----- */
  async function refreshTariff() {
    const box = document.querySelector("[data-tariff]");
    if (!box) return;
    const hs = form.elements.hs_code.value.trim();
    const country = state.destination ? state.destination.country_code : "";
    if (!hs || !country) {
      box.hidden = true;
      return;
    }
    const response = await getJson(`${urls.tariff}?${new URLSearchParams({ hs, country })}`);
    const data = response.success ? response.data : null;
    if (!data) {
      box.hidden = true;
      return;
    }

    const rate = (value) => (value === "" || value === undefined ? "-" : `${value}%`);
    const period = (row) => (row.start_date
      ? `${row.start_date.slice(0, 4)}-${row.start_date.slice(4, 6)}-${row.start_date.slice(6)} 적용` : "");

    let html = `<p class="tariff_head"><b>${escapeHtml(data.country)}</b>에 수출할 때 쓸 수 있는 협정`
      + (data.hs_code ? ` <span class="mono">${escapeHtml(data.hs_code)}</span>` : "") + `</p>`;

    if (data.agreements && data.agreements.length) {
      html += data.agreements.map((row) => `
        <div class="tariff_row">
          <span class="tariff_name">${escapeHtml(row.agreement)}</span>
          <span class="tariff_rate">${escapeHtml(rate(row.rate))}</span>
          <span class="tariff_period">${escapeHtml(period(row))}</span>
          <span class="tariff_about">${escapeHtml(row.about || "")}</span>
          <span class="tariff_proof">${escapeHtml(row.proof)}</span>
          ${row.steps && row.steps.where ? `<span class="tariff_where">어디서: ${escapeHtml(row.steps.where)}</span>` : ""}
        </div>`).join("");
    }
    if (!data.agreements || !data.agreements.length) {
      html += `<p class="tariff_plain">${escapeHtml(data.country)}와(과) 이 품목에 적용할 협정세율이 없습니다.`
        + ` 일반 세율이 적용됩니다.</p>`;
    }
    if (data.general && data.general.length) {
      html += `<p class="tariff_plain">참고 · `
        + data.general.map((row) => `${escapeHtml(row.name)} ${escapeHtml(rate(row.rate))}`).join(" / ")
        + `</p>`;
    }
    if (data.hs6_note) html += `<p class="tariff_note">${escapeHtml(data.hs6_note)}</p>`;
    if (data.note) html += `<p class="tariff_note">${escapeHtml(data.note)}</p>`;
    if (!data.available && data.message) {
      html += `<p class="tariff_plain">${escapeHtml(data.message)}</p>`;
    }
    html += `<div class="dest" data-dest-tariff><p class="tariff_note">도착국 관세율표를 조회하는 중…</p></div>`;
    box.innerHTML = html;
    box.hidden = false;
    refreshDestinationTariff(hs, country, box.querySelector("[data-dest-tariff]"));
  }

  /* ----- 도착국이 실제로 매기는 관세와 그 나라의 세분 부호 ----- */
  let destinationRequest = 0;
  async function refreshDestinationTariff(hs, country, slot) {
    const token = ++destinationRequest;
    const response = await getJson(`${urls.destinationTariff}?${new URLSearchParams({ hs, country })}`);
    if (token !== destinationRequest || !slot.isConnected) return;   // 그 사이 다른 품목을 골랐습니다.
    const data = response.success ? response.data : null;
    if (!data || !data.available) {
      slot.innerHTML = `<p class="tariff_note">${escapeHtml((data && data.message) || "도착국 관세율 자료를 받지 못했습니다.")}</p>`;
      return;
    }

    const pct = (value) => (value === null || value === undefined || value === "" ? "" : `${value}%`);
    const cell = (value) => (value ? escapeHtml(value) : "—");
    // 세분 부호가 하나뿐이면 최소·최대가 세율과 같아 굳이 적지 않습니다.
    const spread = (row) => (row.lines > 1 && row.min !== row.max
      ? `${pct(row.min)}~${pct(row.max)} · 세분 ${row.lines}줄 · ` : "");

    let html = `<p class="tariff_head">${escapeHtml(data.country)}에서 이 물품에 매기는 관세`
      + ` <span class="mono">HS ${escapeHtml(data.hs6)}</span></p>`;

    if (data.rates.length) {
      html += `<div class="dest_rates">` + data.rates.map((row) => (row.rate === null
        ? `<span class="dest_rate"><b>${escapeHtml(row.label)}</b> <i>${escapeHtml(row.note || "")}</i></span>`
        : `<span class="dest_rate"><b>${escapeHtml(row.label)}</b> <strong>${escapeHtml(pct(row.rate))}</strong>`
          + ` <i>${escapeHtml(spread(row))}${escapeHtml(String(row.year))}년 기준</i></span>`
      )).join("") + `</div>`;
    }
    if (data.advice) {
      html += `<p class="dest_advice ${escapeHtml(data.advice.kind)}">${escapeHtml(data.advice.text)}</p>`;
    }
    html += `<p class="tariff_note">${escapeHtml(data.rate_note)}</p>`;

    if (data.national) {
      const n = data.national;
      html += `<p class="dest_sub">${escapeHtml(n.label)} <small>${escapeHtml(n.digits)}${n.edition ? ` · ${escapeHtml(n.edition)} 기준` : ""}</small></p>`;
      html += `<div class="dest_table_wrap"><table class="dest_table"><thead><tr><th>부호</th><th>품목</th>`
        + n.columns.map((c) => `<th>${escapeHtml(c.label)}</th>`).join("") + `</tr></thead><tbody>`
        + n.lines.map((line) => `<tr><td class="mono">${cell(line.code)}</td>`
          + `<td style="padding-left:${8 + (line.indent || 0) * 10}px">${escapeHtml(line.description)}</td>`
          + n.columns.map((c) => `<td>${cell(line[c.key])}</td>`).join("") + `</tr>`).join("")
        + `</tbody></table></div>`;
    }
    html += `<p class="tariff_note">${escapeHtml(data.national_note)}</p>`
      + `<a class="dest_link" href="${escapeHtml(data.link.url)}" target="_blank" rel="noopener noreferrer">`
      + `${escapeHtml(data.link.label)} 열기 <span aria-hidden="true">↗</span>`
      + `<small>새 창에서 열립니다</small></a>`;
    slot.innerHTML = html;
  }

  let lastHsQuery = "";
  setupAutocomplete(
    form.querySelector("[data-autocomplete=hs_code]"),
    async (q) => {
      // 아무것도 입력하지 않았으면 위에 적은 품명으로 찾아봅니다.
      const query = q.trim() || form.elements.product_description.value.trim();
      lastHsQuery = query;
      if (!query) return [];
      const response = await getJson(`${urls.hsCodes}?${new URLSearchParams({ q: query })}`);
      if (!response.success) return [];
      // 관세청 조회인지 예시 목록인지 함께 표시합니다.
      return response.data.map((item) => ({ ...item, source: response.source }));
    },
    (item) => {
      const sub = [item.name_en, item.weight_unit ? `중량단위 ${item.weight_unit}` : "",
        item.source === "api" ? "관세청 HS부호" : "예시 목록"].filter(Boolean).join(" · ");
      return `<span class="mono">${escapeHtml(item.code)}</span>`
        + ` <b>${escapeHtml(item.name || item.name_en)}</b><small>${escapeHtml(sub)}</small>`;
    },
    (item, input) => {
      if (!item) return;
      input.value = item.code;
      refreshTariff();     // 고른 품목의 협정세율을 아래에 보여줍니다.
    },
    {
      // 도착국을 골랐으면 후보마다 그 나라에 쓸 수 있는 협정을 한 줄씩 붙입니다.
      // 어느 부호를 골라야 유리한지 목록에서 바로 비교할 수 있습니다.
      afterRender: async (items, list) => {
        if (!state.destination || !items.length) return;
        const codes = items.map((item) => item.code.replace(/[.\-\s]/g, "")).filter(Boolean);
        const response = await getJson(`${urls.tariffSummary}?${new URLSearchParams({
          hs: codes.join(","), country: state.destination.country_code })}`);
        if (!response.success) return;
        list.querySelectorAll("li[data-index]").forEach((li) => {
          const item = items[Number(li.dataset.index)];
          const summary = item && response.data[item.code.replace(/[.\-\s]/g, "")];
          if (!summary) return;
          li.insertAdjacentHTML("beforeend",
            `<small class="ac_tariff ${escapeHtml(summary.status)}">`
            + `${escapeHtml(state.destination.country)} · ${escapeHtml(summary.text)}</small>`);
        });
      },
      emptyMessage: () => {
        const digits = lastHsQuery.replace(/[.\-\s]/g, "");
        if (/^\d+$/.test(digits) && digits.length !== 10) {
          return "HS부호는 10자리를 모두 입력해야 조회됩니다. 품명으로 찾아보세요.";
        }
        if (!lastHsQuery) return "품명(예: 립스틱, 샴푸) 또는 HS부호 10자리를 입력하세요.";
        return `"${lastHsQuery}"로 찾은 품목이 없습니다. 더 일반적인 낱말로 찾아보세요.`;
      },
    },
  );

  /* ----- Cargo calculation ----- */
  const calcMessage = document.querySelector("[data-calc-message]");

  /* ----- 추가 품목 ----- */
  const cargoLinesBox = document.querySelector("[data-cargo-lines]");
  const LINE_FIELDS = ["quantity", "length_cm", "width_cm", "height_cm", "weight_per_package_kg"];

  function packageOptions() {
    // 운송수단에 맞는 포장만 고를 수 있게 첫 품목의 목록을 그대로 씁니다.
    return Array.from(form.elements.package_type.options)
      .filter((option) => !option.disabled)
      .map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.textContent.trim())}</option>`)
      .join("");
  }

  /* ----- 위험물(Dangerous Goods) ----- */
  // 첫 품목과 추가 품목이 똑같은 상자를 씁니다.
  const DG_CLASSES = window.FORWARDUS_DG_CLASSES || [];

  function dgBoxHtml() {
    const options = DG_CLASSES
      .map((c) => `<option value="${escapeHtml(c.code)}">${escapeHtml(c.label)}</option>`).join("");
    const groups = Object.entries(window.FORWARDUS_PACKING_GROUPS || {})
      .map(([code, label]) => `<option value="${escapeHtml(code)}">${escapeHtml(label)}</option>`).join("");
    return `
      <label class="dg_check">
        <input type="checkbox" data-dg="is_dangerous">
        <span>위험물(Dangerous Goods)입니다</span>
        <small>인화성·가스·배터리·화학품 등은 부킹과 서류가 달라집니다.</small>
      </label>
      <div class="dg_fields" data-dg-fields hidden>
        <label class="field">
          <span class="field_label">UN 번호</span>
          <input class="text_input" type="text" data-dg="un_number" maxlength="6" placeholder="예: UN1263" autocomplete="off">
          <small class="field_hint">MSDS 14번 항목(운송 정보)에 적혀 있습니다.</small>
        </label>
        <label class="field">
          <span class="field_label">위험물 등급 (UN Class)</span>
          <select data-dg="dg_class"><option value="">등급 선택</option>${options}</select>
          <small class="field_hint" data-dg-examples></small>
        </label>
        <label class="field span2">
          <span class="field_label">정식운송품명 (Proper Shipping Name)</span>
          <input class="text_input" type="text" data-dg="proper_shipping_name" maxlength="200"
                 placeholder="예: PAINT" autocomplete="off">
          <small class="field_hint">위험물 신고서와 포장 라벨에 이 이름을 그대로 씁니다.
            상품명이 아니라 MSDS에 적힌 공식 품명입니다.</small>
        </label>
        <label class="field">
          <span class="field_label">포장등급 (Packing Group) <small class="muted">(선택)</small></span>
          <select data-dg="packing_group">
            <option value="">해당 없음</option>${groups}
          </select>
          <small class="field_hint">위험도입니다. 등급에 따라 쓸 수 있는 용기가 달라집니다.</small>
        </label>
      </div>
      <p class="dg_warn" data-dg-warn hidden></p>
      <div class="dg_guide" data-dg-guide hidden></div>`;
  }

  async function renderDgGuide(box) {
    const guideBox = box.querySelector("[data-dg-guide]");
    const dgClass = box.querySelector('[data-dg="dg_class"]').value;
    const on = box.querySelector('[data-dg="is_dangerous"]').checked;
    if (!on || !dgClass) {
      guideBox.hidden = true;
      return;
    }
    const country = state.destination ? state.destination.country_code : "";
    const response = await getJson(`${urls.dangerousGoods}?${new URLSearchParams({
      dg_class: dgClass, mode: state.transport_mode, country })}`);
    const data = response.success ? response.data : null;
    if (!data || !data.available) {
      guideBox.hidden = true;
      return;
    }
    guideBox.innerHTML = `
      <p class="dg_head"><b>${escapeHtml(data.label)}</b>
        <span class="dg_status ${escapeHtml(data.status)}">${escapeHtml(data.status_label)}</span></p>
      <p class="dg_line"><b>이런 품목입니다</b> ${escapeHtml(data.examples)}</p>
      <p class="dg_line"><b>적용 규정</b> ${escapeHtml(data.rule)} · ${escapeHtml(data.mode_note)}</p>
      <p class="dg_sub">보내는 방법</p>
      <ol class="dg_steps">${data.steps.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ol>
      <p class="dg_line">${escapeHtml(data.destination_note)}</p>
      <p class="dg_refs">${data.references.map((r) =>
        `<a href="${escapeHtml(r.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(r.label)} ↗</a>`
      ).join("")}</p>`;
    guideBox.hidden = false;
  }

  function wireDgBox(box) {
    const toggle = box.querySelector('[data-dg="is_dangerous"]');
    const fields = box.querySelector("[data-dg-fields]");
    const select = box.querySelector('[data-dg="dg_class"]');
    const examples = box.querySelector("[data-dg-examples]");

    const sync = () => {
      fields.hidden = !toggle.checked;
      const info = DG_CLASSES.find((c) => c.code === select.value);
      examples.textContent = info ? `예: ${info.examples}` : "";
      if (!toggle.checked) showDgWarning(box, "");
      renderDgGuide(box);
      // 위험물 표시를 바꾸면 계산도 다시 돌려야 합니다. 체크를 풀었는데
      // 예전 경고가 계산 패널에 남아 있던 문제를 여기서 막습니다.
      recalc();
      invalidateSchedules();
      saveDraftSoon();
    };
    toggle.addEventListener("change", sync);
    select.addEventListener("change", sync);
    box.querySelectorAll('[data-dg="un_number"], [data-dg="proper_shipping_name"]')
      .forEach((input) => input.addEventListener("input", () => { recalc(); saveDraftSoon(); }));
    box.querySelector('[data-dg="packing_group"]').addEventListener("change", saveDraftSoon);
    box.refreshDg = sync;
    return box;
  }

  const DG_FIELDS = ["un_number", "dg_class", "proper_shipping_name", "packing_group"];

  function showDgWarning(box, message) {
    const warn = box && box.querySelector("[data-dg-warn]");
    if (!warn) return;
    warn.textContent = message || "";
    warn.hidden = !message;
  }

  function dgValues(box) {
    if (!box) return { is_dangerous: false };
    const values = { is_dangerous: box.querySelector('[data-dg="is_dangerous"]').checked };
    DG_FIELDS.forEach((key) => { values[key] = box.querySelector(`[data-dg="${key}"]`).value.trim(); });
    return values;
  }

  function setDgValues(box, values = {}) {
    if (!box || !values) return;
    box.querySelector('[data-dg="is_dangerous"]').checked = Boolean(values.is_dangerous);
    DG_FIELDS.forEach((key) => { box.querySelector(`[data-dg="${key}"]`).value = values[key] || ""; });
    box.refreshDg();
  }

  // 위험물 칸이 덜 채워졌다는 안내를 해당 품목의 상자에 붙입니다.
  // 서버가 돌려주는 line_no는 실제로 보낸 품목 순서라, 보낸 순서 그대로 맞춥니다.
  function applyDgWarnings(warnings, boxes) {
    const all = [mainDgBox, ...cargoLinesBox.querySelectorAll("[data-dg-box]")];
    all.forEach((box) => showDgWarning(box, ""));
    (warnings || []).forEach((warning) => showDgWarning(boxes[warning.line_no - 1], warning.message));
  }

  const mainDgBox = document.querySelector("[data-dg-main]");
  if (mainDgBox) {
    mainDgBox.className = "field span2 dg_box";
    mainDgBox.innerHTML = dgBoxHtml();
    wireDgBox(mainDgBox);
  }

  // 운송수단이나 도착지가 바뀌면 열려 있는 안내를 모두 다시 그립니다.
  function refreshAllDgGuides() {
    document.querySelectorAll("[data-dg-guide]").forEach((guide) => {
      const box = guide.closest(".dg_box");
      if (box && !guide.hidden) renderDgGuide(box);
    });
  }

  /* ----- 추가 품목: 첫 품목과 같은 양식 ----- */
  // 화면에 보이는 칸 = data-line 이름. 첫 품목의 name과 같게 맞춥니다.
  const LINE_LAYOUT = [
    ["product_description", "품명 (Product Description)", "text", "span2"],
    ["hs_code", "HS CODE", "text", "span2"],
    ["package_type", "포장 유형", "select", ""],
    ["quantity", "수량 (Quantity)", "number", "", { step: 1, min: 1, mode: "numeric" }],
    ["length_cm", "가로 Length (cm)", "number", "", { step: 1, min: 0 }],
    ["width_cm", "세로 Width (cm)", "number", "", { step: 1, min: 0 }],
    ["height_cm", "높이 Height (cm)", "number", "", { step: 1, min: 0 }],
    ["weight_per_package_kg", "포장당 총중량 (kg)", "number", "", { step: 10, min: 0 }],
  ];

  function lineFieldHtml([key, label, kind, span, opts = {}]) {
    const inner = kind === "select"
      ? `<select data-line="${key}">${packageOptions()}</select>`
      : `<input class="text_input" type="text" data-line="${key}" autocomplete="off"`
        + (kind === "number"
          ? ` inputmode="${opts.mode || "decimal"}" data-number data-step="${opts.step}" data-min="${opts.min}"`
          : ` maxlength="300"`) + `>`;
    return `<label class="field ${span}"><span class="field_label">${escapeHtml(label)}</span>${inner}</label>`;
  }

  function addCargoLine(values = {}) {
    const row = document.createElement("div");
    row.className = "cargo_item";
    const number = cargoLinesBox.querySelectorAll(".cargo_item").length + 2;
    row.innerHTML = `
      <div class="cargo_item_head">
        <b>품목 ${number}</b>
        <button type="button" class="link_button danger" data-remove-cargo>삭제</button>
      </div>
      <div class="form_grid">
        ${LINE_LAYOUT.map(lineFieldHtml).join("")}
        <div class="field span2 dg_box" data-dg-box>${dgBoxHtml()}</div>
      </div>`;
    cargoLinesBox.appendChild(row);
    row.querySelectorAll("[data-line]").forEach((input) => {
      if (values[input.dataset.line] !== undefined) input.value = values[input.dataset.line];
      if (input.dataset.number !== undefined) setupNumberInput(input);
      input.addEventListener("input", () => { recalc(); invalidateSchedules(); saveDraftSoon(); });
      input.addEventListener("change", () => { recalc(); invalidateSchedules(); saveDraftSoon(); });
    });
    const dgBox = wireDgBox(row.querySelector("[data-dg-box]"));
    setDgValues(dgBox, values);
    return row;
  }

  function renumberCargoLines() {
    cargoLinesBox.querySelectorAll(".cargo_item").forEach((row, index) => {
      row.querySelector(".cargo_item_head b").textContent = `품목 ${index + 2}`;
    });
  }

  function extraCargoEntries() {
    return Array.from(cargoLinesBox.querySelectorAll(".cargo_item")).map((row) => {
      const box = row.querySelector("[data-dg-box]");
      const item = { ...dgValues(box) };
      row.querySelectorAll("[data-line]").forEach((input) => {
        item[input.dataset.line] = input.dataset.number === undefined
          ? input.value : plainNumber(input.value);
      });
      return { item, box };
    }).filter(({ item }) => LINE_FIELDS.every((key) => item[key] !== ""));
  }

  function extraCargoLines() {
    return extraCargoEntries().map(({ item }) => item);
  }

  document.querySelector("[data-add-cargo]")?.addEventListener("click", () => addCargoLine());
  cargoLinesBox?.addEventListener("click", (event) => {
    if (!event.target.closest("[data-remove-cargo]")) return;
    event.target.closest(".cargo_item").remove();
    renumberCargoLines();
    recalc();
    invalidateSchedules();
    saveDraftSoon();
  });

  // 보낸 품목과 그 위험물 상자를 짝지어 둡니다. 경고를 제자리에 붙이는 데 씁니다.
  let lastCargoBoxes = [];

  function cargoPayload() {
    const f = form.elements;
    const first = {
      ...dgValues(mainDgBox),
      product_description: f.product_description.value,
      hs_code: f.hs_code.value,
      package_type: f.package_type.value,
      quantity: plainNumber(f.quantity.value),
      length_cm: plainNumber(f.length_cm.value),
      width_cm: plainNumber(f.width_cm.value),
      height_cm: plainNumber(f.height_cm.value),
      weight_per_package_kg: plainNumber(f.weight_per_package_kg.value),
      net_weight_kg: plainNumber(f.net_weight_kg.value),
    };
    const extras = extraCargoEntries();
    lastCargoBoxes = [mainDgBox, ...extras.map(({ box }) => box)];
    return { items: [first, ...extras.map(({ item }) => item)] };
  }

  function renderMetrics(metrics) {
    const set = (key, text) => { document.querySelector(`[data-metric=${key}]`).textContent = text; };
    if (!metrics) {
      ["total_cbm", "total_weight_kg", "revenue_ton", "container", "volume_weight_kg", "chargeable_weight_kg"].forEach((k) => set(k, "-"));
      return;
    }
    set("total_cbm", `${formatNumber(metrics.total_cbm, 3)} CBM`);
    set("total_weight_kg", `${formatNumber(metrics.total_weight_kg, 1)} kg`);
    set("revenue_ton", `${formatNumber(metrics.revenue_ton, 3)} R/T`);
    set("container", `${metrics.container_quantity} × ${metrics.container_type}`);
    set("volume_weight_kg", `${formatNumber(metrics.volume_weight_kg, 1)} kg`);
    set("chargeable_weight_kg", `${formatNumber(metrics.chargeable_weight_kg, 1)} kg`);
  }

  const recalc = debounce(async () => {
    const payload = cargoPayload();
    const filled = LINE_FIELDS.every((k) => payload.items[0][k] !== "");
    if (!filled) {
      state.metrics = null;
      renderMetrics(null);
      calcMessage.textContent = "치수·수량·중량을 입력하면 계산됩니다.";
      return;
    }
    const boxes = lastCargoBoxes;
    const response = await postJson(urls.cargo, payload);
    state.metrics = response.success ? response.data : null;
    renderMetrics(state.metrics);
    // 위험물 칸이 덜 채워진 것은 계산 오류가 아닙니다. 계산값은 그대로 보여주고
    // 경고만 해당 품목의 위험물 상자에 붙입니다.
    applyDgWarnings(response.success ? response.data.dg_warnings : [], boxes);
    calcMessage.textContent = response.success ? "서버에서 계산된 값입니다." : response.message;
  }, 250);

  form.querySelectorAll("[data-calc]").forEach((input) => input.addEventListener("input", () => { recalc(); invalidateSchedules(); }));
  form.elements.package_type.addEventListener("change", () => {
    const note = document.querySelector("[data-package-note]");
    if (note) note.textContent = form.elements.package_type.selectedOptions[0]?.dataset.note || "";
    invalidateSchedules();
  });

  /* ----- Schedules ----- */
  const scheduleList = document.querySelector("[data-schedule-list]");
  const scheduleMeta = document.querySelector("[data-schedule-meta]");

  function invalidateSchedules() {
    state.schedules = [];
    state.schedule_id = null;
  }

  function customPayload(role) {
    const item = state[role];
    return item && item.custom ? { name: item.name, country_code: item.country_code } : null;
  }

  function routePayload() {
    return {
      project_name: form.elements.project_name.value,
      transport_mode: state.transport_mode,
      sea_mode: state.transport_mode === "SEA" ? state.sea_mode : null,
      origin_code: state.origin ? state.origin.code : "",
      destination_code: state.destination ? state.destination.code : "",
      origin_custom: customPayload("origin"),
      destination_custom: customPayload("destination"),
      requested_departure_date: state.departure_date,
      buyer_required_date: form.elements.buyer_required_date.value,
    };
  }

  function renderSchedules() {
    if (!state.schedules.length) {
      scheduleList.innerHTML = `<p class="muted">조건에 맞는 스케줄이 없습니다.</p>`;
      return;
    }
    scheduleList.innerHTML = state.schedules.map((s) => {
      const deadline = s.deadline
        ? (s.deadline.on_time
          ? `<span class="badge ok">납기 여유 ${s.deadline.margin_days}일</span>`
          : `<span class="badge warn">납기 ${Math.abs(s.deadline.margin_days)}일 초과 위험</span>`)
        : "";
      return `
        <label class="schedule_card ${state.schedule_id === s.schedule_id ? "selected" : ""}">
          <input type="radio" name="schedule_id" value="${escapeHtml(s.schedule_id)}" ${state.schedule_id === s.schedule_id ? "checked" : ""}>
          <div class="schedule_main">
            <div class="row_between wrap">
              <b>${escapeHtml(s.carrier)} <small class="muted">${escapeHtml(s.vessel_or_flight)} · ${escapeHtml(s.service)}</small></b>
              <span class="badge source_${escapeHtml(s.source)}">Data Source: ${s.source === "mock" ? "Mock" : "API"}</span>
            </div>
            <div class="schedule_route">
              <div><small title="Estimated Time of Departure">ETD <i>출항 예정</i></small><b>${s.etd}</b></div>
              <div class="line"><span>${s.transit_days}일 · ${s.direct ? "직항" : "환적"}</span></div>
              <div><small title="Estimated Time of Arrival">ETA <i>도착 예정</i></small><b>${s.eta}</b></div>
            </div>
            <div class="row_between wrap">
              <span class="muted small">${s.reliability ? `정시율 ${s.reliability}% · ` : ""}${escapeHtml(s.freight_basis)}${
                s.transship_port ? ` · ${escapeHtml(s.transship_port)} 환적` : ""}${
                s.cargo_cutoff ? ` · 화물 마감 ${escapeHtml(s.cargo_cutoff)}` : ""}</span>
              ${deadline}
            </div>
          </div>
          <div class="schedule_price"><small>Freight <i>운임</i></small>
            <b>USD ${formatNumber(s.freight_usd, 0)}</b>
            <em>${escapeHtml(inKrw(s.freight_usd))}</em>
            ${s.freight_source === "estimate" ? `<em class="est">추정 운임</em>` : ""}</div>
        </label>`;
    }).join("");
  }

  scheduleList.addEventListener("change", (event) => {
    if (event.target.name === "schedule_id") {
      state.schedule_id = event.target.value;
      renderSchedules();
      saveDraftSoon();
    }
  });

  async function loadSchedules() {
    scheduleList.innerHTML = `<p class="muted">스케줄을 조회하고 있습니다…</p>`;
    const response = await postJson(urls.schedules, { ...routePayload(), cargo: cargoPayload(), sort: state.sort });
    if (!response.success) {
      scheduleList.innerHTML = "";
      handleServerError(response);
      return false;
    }
    state.schedules = response.data.items;
    if (!state.schedules.some((s) => s.schedule_id === state.schedule_id)) state.schedule_id = null;
    // 예시 스케줄이면 "무슨 키가 없어서인지"까지 서버가 적어 보냅니다.
    scheduleMeta.textContent = `${state.origin.name} → ${state.destination.name} · ${state.departure_date} 이후 출발 · ${state.schedules.length}건`
      + (response.data.note ? ` · ${response.data.note}` : "");
    renderSchedules();
    return true;
  }

  bindToggle(document.querySelector("[data-sort]"), (value) => { state.sort = value; loadSchedules(); });

  /* ----- Step validation ----- */
  function validateStep(step) {
    const f = form.elements;
    if (step === 1) {
      if (!f.project_name.value.trim()) return "견적명을 입력해주세요.";
      if (!state.departure_date) return "캘린더에서 출발 희망일을 선택해주세요.";
      if (!state.origin) return "출발지를 목록에서 선택해주세요.";
      if (!state.destination) return "도착지를 목록에서 선택해주세요.";
    }
    if (step === 2 && !form.querySelector("input[name=incoterms]:checked")) return "Incoterms를 선택해주세요.";
    if (step === 3) {
      if (!f.product_description.value.trim()) return "품명을 입력해주세요.";
      if (!state.metrics) return "화물 치수·수량·중량을 올바르게 입력해주세요.";
      if (!plainNumber(f.invoice_value.value)) return "Invoice Value를 입력해주세요.";
    }
    if (step === 4 && !state.schedule_id) return "스케줄을 선택해주세요.";
    return "";
  }

  function handleServerError(response) {
    const step = FIELD_STEP[response.field];
    if (step && step !== state.step) goToStep(step);
    showError(response.message || "요청을 처리하지 못했습니다.");
  }

  function renderSummary() {
    const f = form.elements;
    const schedule = state.schedules.find((s) => s.schedule_id === state.schedule_id);
    const incoterm = form.querySelector("input[name=incoterms]:checked");
    const m = state.metrics;
    const missing = "— 미입력";
    const rows = [
      ["Route", state.origin && state.destination
        ? `${state.origin.name} (${state.origin.code}) → ${state.destination.name} (${state.destination.code})` : missing],
      ["Mode", state.transport_mode === "AIR" ? "AIR" : `SEA · ${state.sea_mode}`],
      ["Incoterms", incoterm ? incoterm.value : missing],
      ["Cargo", m
        ? `${f.product_description.value || "(품명 없음)"} · ${f.quantity.value} pkg · ${formatNumber(m.total_cbm, 3)} CBM · ${formatNumber(m.total_weight_kg, 1)} kg`
        : missing],
      ["Invoice", plainNumber(f.invoice_value.value)
        ? `${f.currency.value} ${formatNumber(Number(plainNumber(f.invoice_value.value)), 2)}` : missing],
      ["Schedule", schedule ? `${schedule.carrier} ${schedule.vessel_or_flight} · ETD ${schedule.etd} → ETA ${schedule.eta}` : missing],
      // 운임 출처(선사 API인지 예시인지)는 금액이 아니라 환율 기준과 구분해 따로 적습니다.
      ["Freight", schedule
        ? `USD ${formatNumber(schedule.freight_usd, 0)} ${inKrw(schedule.freight_usd)}`.trim()
        : missing],
    ];
    document.querySelector("[data-summary]").innerHTML = rows
      .map(([k, v]) => `<div><dt>${k}</dt><dd class="${v === missing ? "missing" : ""}">${escapeHtml(v)}`
        + (k === "Freight" && v !== missing
          ? `<small class="rate_basis" data-rate-basis>${escapeHtml(rateBasis)}</small>` : "")
        + `</dd></div>`).join("");
  }

  /* ----- Free navigation: any step can be opened at any time; validation happens on submit ----- */
  async function openStep(step) {
    showError("");
    goToStep(step);
    if (step === 4 && !state.schedules.length) {
      const blocker = [1, 3].map(validateStep).find(Boolean);
      if (blocker) {
        scheduleMeta.textContent = "";
        scheduleList.innerHTML = `<p class="muted">스케줄을 조회하려면 Route·Cargo 정보가 필요합니다: ${escapeHtml(blocker)}</p>`;
      } else {
        await loadSchedules();
      }
    }
    if (step === 5) renderSummary();
  }

  form.addEventListener("click", (event) => {
    if (event.target.matches("[data-prev]")) openStep(state.step - 1);
    if (event.target.matches("[data-next]")) openStep(state.step + 1);
  });

  document.querySelectorAll("[data-step-tab]").forEach((tab) => {
    tab.addEventListener("click", () => openStep(Number(tab.dataset.stepTab)));
  });

  const LEVEL_TEXT = {
    ok: "여유 있음",
    caution: "여유 적음",
    tight: "일정 촉박",
    late: "납기 초과",
    none: "Buyer 요청일을 입력하면 여유를 계산합니다",
  };

  // FCL / LCL을 고르면 무엇이 달라지는지 달력 아래에 함께 적습니다.
  function modeDiff(diff) {
    if (!diff) return "";
    const steps = diff.extra_steps.length
      ? `<p class="diff_gap">LCL에만 드는 작업: ${diff.extra_steps.map(escapeHtml).join(" · ")}`
        + ` <b>— FCL보다 ${escapeHtml(diff.gap_days)} 더 걸립니다</b></p>`
      : "";
    return `<div class="outlook_diff">`
      + `<p class="diff_head"><b>${escapeHtml(diff.selected)}</b> 선택 시</p>`
      + `<ul>${diff.facts.map((fact) => `<li>${escapeHtml(fact)}</li>`).join("")}</ul>`
      + steps
      + `</div>`;
  }

  async function refreshOutlook() {
    const box = document.querySelector("[data-outlook]");
    if (!box) return;
    if (!state.departure_date || !state.destination) {
      box.hidden = true;
      return;
    }
    const response = await postJson(urls.scheduleOutlook, {
      origin_code: state.origin ? state.origin.code : "",
      transport_mode: state.transport_mode,
      sea_mode: state.sea_mode,
      destination_code: state.destination.code,
      requested_departure_date: state.departure_date,
      buyer_required_date: form.elements.buyer_required_date.value,
    });
    const data = response.success ? response.data : null;
    if (!data || !data.available) {
      box.hidden = true;
      return;
    }

    const days = (mode) => (mode.min_days === mode.max_days
      ? `${mode.min_days}일` : `${mode.min_days}~${mode.max_days}일`);
    const margin = (mode) => {
      if (mode.margin_worst === null || mode.margin_worst === undefined) return "";
      if (mode.margin_worst < 0) return `${Math.abs(mode.margin_worst)}일 부족`;
      return mode.margin_worst === mode.margin_best
        ? `여유 ${mode.margin_worst}일`
        : `여유 ${mode.margin_worst}~${mode.margin_best}일`;
    };
    const icon = { SEA: "🚢", AIR: "✈️" };
    const km = (value) => `${formatNumber(value)}km`;
    // 출발일과 같은 해면 연도를 빼서 한 줄에 들어가게 합니다.
    const short = (iso) => (iso.slice(0, 4) === data.departure_date.slice(0, 4) ? iso.slice(5) : iso);
    const eta = (mode) => (mode.eta_slowest === mode.eta_fastest
      ? `도착 ${short(mode.eta_fastest)}`
      : `도착 ${short(mode.eta_fastest)}~${short(mode.eta_slowest)}`);
    // 항구를 골랐는데 항공을 보여줄 때처럼, 실제로 계산한 구간을 함께 적습니다.
    const legOf = (mode) => (mode.mode === "SEA" ? data.sea_route : data.air_route);
    const detail = (mode) => {
      const leg = legOf(mode) || {};
      const parts = [];
      if (leg.origin) parts.push(`${leg.origin} → ${leg.destination} ${km(leg.distance_km)}`);
      if (mode.note) parts.push(mode.note);
      return parts.join(" · ");
    };

    box.innerHTML = `<p class="outlook_head">${escapeHtml(state.origin ? state.origin.name : "출발지")}`
      + ` → ${escapeHtml(data.destination)} 예상 일정`
      + ` <em>실제 항로 기준</em></p>`
      + data.modes.map((mode) => `
        <div class="outlook_row level_${mode.level}${mode.selected ? " is_selected" : ""}">
          ${mode.selected ? `<span class="outlook_pick">선택</span>` : ""}
          <span class="outlook_mode">${icon[mode.mode]} ${escapeHtml(mode.label)}</span>
          <span class="outlook_days">${days(mode)}</span>
          <span class="outlook_eta">${eta(mode)}</span>
          <span class="outlook_margin">${escapeHtml(margin(mode))}
            <b>${escapeHtml(LEVEL_TEXT[mode.level] || "")}</b></span>
          <span class="outlook_note">${escapeHtml(detail(mode))}</span>
        </div>`).join("")
      + modeDiff(data.sea_mode_diff);
    box.hidden = false;
  }

  function checkDeparture() {
    clearTimeout(departureCheckTimer);
    departureCheckTimer = setTimeout(refreshOutlook, 250);
  }

  function updateSelectedDates() {
    const buyerDate = form.elements.buyer_required_date.value;
    selectedDateEl.innerHTML =
      `<span class="date_item departure"><i></i>Seller 예상일 ${state.departure_date || "미선택"}</span>`
      + `<span class="date_item buyer"><i></i>Buyer 요청일 ${buyerDate || "미선택"}</span>`;
    // 달력과 표시가 항상 같은 값을 보여주도록 여기서 한 번에 다시 그립니다.
    renderCalendar();
    checkDeparture();
  }

  // 날짜 칸을 직접 고쳐도 달력이 바로 다시 그려지도록 input 이벤트도 받습니다.
  form.elements.buyer_required_date.addEventListener("input", updateSelectedDates);

  form.elements.buyer_required_date.addEventListener("change", () => {
    const value = form.elements.buyer_required_date.value;
    if (value && state.departure_date && value < state.departure_date) {
      showError("Buyer 요청 도착일은 Seller 예상일보다 빠를 수 없습니다.");
      form.elements.buyer_required_date.value = "";
      updateSelectedDates();
      return;
    }
    showError("");
    if (value) {
      // 요청일이 보이도록 달력을 그 달로 옮깁니다. (해당 월이 오른쪽에 오도록)
      const [year, month] = value.split("-").map(Number);
      const target = new Date(year, month - 2, 1);
      const earliest = new Date(today.getFullYear(), today.getMonth(), 1);
      viewMonth = target < earliest ? earliest : target;
    }
    updateSelectedDates();
    invalidateSchedules();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    for (const step of [1, 2, 3, 4]) {
      const message = validateStep(step);
      if (message) {
        await openStep(step);
        showError(message);
        return;
      }
    }

    const f = form.elements;
    const submit = form.querySelector("[data-submit]");
    const label = submit.textContent;
    submit.disabled = true;
    submit.textContent = "생성 중…";
    let response;
    try {
      response = await postJson(urls.create, {
        ...routePayload(),
        incoterms: form.querySelector("input[name=incoterms]:checked").value,
        currency: f.currency.value,
        invoice_value: plainNumber(f.invoice_value.value),
        cargo: cargoPayload(),
        schedule_id: state.schedule_id,
        exporter_name: f.exporter_name.value,
        exporter_address: f.exporter_address.value,
        notify_party: f.notify_party.value,
        buyer: {
          name: f.buyer_name.value,
          country: f.buyer_country.value,
          address: f.buyer_address.value,
          contact_email: f.buyer_email.value,
        },
      });
    } catch (error) {
      response = { success: false, message: `요청 중 오류가 발생했습니다: ${error.message}` };
    } finally {
      submit.disabled = false;
      submit.textContent = label;
    }
    if (response.success) {
      clearDraft();
      window.location.href = response.data.url;
    } else {
      handleServerError(response);
    }
  });

  // 복원은 recalc·openStep까지 모두 선언된 뒤에 실행해야 합니다.
  restoreDraft();
})();
