/* Shipment Planning: wizard (planning/new). */
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
    // 올린 L/C에서 읽은 선적 마감 조건. (서류 작성에서 넘어옵니다 · work_draft.js)
    lc: null,
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
  const DRAFT_KEY = window.ForwardusStore.key("forwardus:planning-draft");
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
      lc: state.lc,
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
    errorBox.classList.remove("is_confirm");
    if (message) errorBox.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  // 막는 것이 아니라 한 번 더 확인받는 안내. 같은 자리에 다른 색으로 보여줍니다.
  function showConfirm(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
    errorBox.classList.add("is_confirm");
    errorBox.scrollIntoView({ behavior: "smooth", block: "center" });
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

  /* 달을 넘길 때 두 달이 한 번에 툭 바뀌면 어디가 바뀐 건지 눈이 못 따라갑니다.
     넘어간 방향으로 살짝 밀어 주면 "다음 달로 갔다"는 것이 보입니다.
     움직임을 줄여 달라고 설정한 분께는 그냥 바뀝니다. (prefers-reduced-motion) */
  function renderCalendar(slide = "") {
    const canGoBack = viewMonth > new Date(today.getFullYear(), today.getMonth(), 1);
    calendarEl.innerHTML = `
      <div class="cal_head">
        <button type="button" data-cal-prev ${canGoBack ? "" : "disabled"} aria-label="이전 달">‹</button>
        <b>일정 선택</b>
        <button type="button" data-cal-next aria-label="다음 달">›</button>
      </div>
      <div class="cal_months">${monthHtml(viewMonth, 0)}${monthHtml(viewMonth, 1)}</div>
      <p class="cal_legend">
        <span class="legend_departure">Seller 발송 예상일</span>
        <span class="legend_buyer">Buyer 요청 도착일</span>
        <span class="legend_range">예상 운송 기간</span>
      </p>
      <p class="cal_hint">다음 선택: <b>${pickTarget === "departure" ? "Seller 발송 예상일" : "Buyer 요청 도착일"}</b>
        · 날짜를 누를 때마다 Seller 발송 예상일 → Buyer 요청일 순서로 지정되고,
        Seller 발송 예상일을 다시 고르면 Buyer 요청일은 지워집니다.</p>`;
    if (slide) {
      const months = calendarEl.querySelector(".cal_months");
      if (months) months.classList.add(`cal_${slide}`);
    }
  }

  calendarEl.addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target || target.disabled) return;
    let slide = "";
    if (target.hasAttribute("data-cal-prev")) {
      viewMonth.setMonth(viewMonth.getMonth() - 1);
      slide = "back";                       // 지난 달 → 오른쪽에서 들어옵니다
    } else if (target.hasAttribute("data-cal-next")) {
      viewMonth.setMonth(viewMonth.getMonth() + 1);
      slide = "forward";                    // 다음 달 → 왼쪽에서 들어옵니다
    } else if (target.dataset.date) {
      const iso = target.dataset.date;
      const buyerInput = form.elements.buyer_required_date;
      if (pickTarget === "departure") {
        // 새 일정을 고르는 것이므로 Buyer 요청일을 비워 선택 상태를 분명히 합니다.
        state.departure_date = iso;
        buyerInput.value = "";
        pickTarget = "buyer";
      } else {
        if (state.departure_date && iso < state.departure_date) {
          showError("Buyer 요청 도착일은 Seller 발송 예상일보다 빠를 수 없습니다.");
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
    renderCalendar(slide);
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
    // 항공에서는 LCL·FCL 권고가 뜻이 없어 숨깁니다.
    if (state.metrics) renderSeaAdvice(state.metrics.sea_mode_advice);
  });
  bindToggle(form.querySelector("[data-toggle=sea_mode]"), (value) => {
    state.sea_mode = value;
    applyMode();
    invalidateSchedules();
    saveDraftSoon();
    refreshOutlook();   // FCL/LCL에 따라 소요일과 안내가 달라집니다.
    // 권고가 지금 고른 방식과 같은지 다시 봅니다. (같으면 "바꾸기"를 띄우지 않습니다)
    if (state.metrics) renderSeaAdvice(state.metrics.sea_mode_advice);
  });
  applyMode();

  /* ----- Autocomplete ----- */
  // HS CODE 간편 검색 창도 같은 것을 쓰도록 base.js로 옮겼습니다.
  const { debounce, setupAutocomplete } = window.Forwardus;

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

  /* 적어 둔 것이 있다고 **알리기만** 합니다. 채우는 것은 누를 때입니다.
     화면은 늘 빈 칸으로 시작합니다. 들어오자마자 지난 값이 차 있으면, 새 건을
     내려던 사람이 그게 언제 적은 것인지도 모른 채 그 위에 덧씁니다.
     (2026-09-26 사용자 결정) */
  async function restoreDraft() {
    const draft = loadDraft();
    if (!draft) return;
    const note = document.createElement("div");
    note.className = "flash prefill_note";
    note.setAttribute("role", "status");
    const when = draft.savedAt
      ? new Date(draft.savedAt).toLocaleString("ko-KR", { month: "long", day: "numeric",
                                                         hour: "2-digit", minute: "2-digit" })
      : "";
    // 서류 작성에서 넘어온 값이면 어디서 온 것인지 밝힙니다.
    const from = draft.source ? `${SOURCE_LABELS[draft.source] || "서류 작성"}에서 적은 내용이 있습니다.`
      : "적어 두신 견적이 있습니다.";
    note.innerHTML = `📦 ${from}${when ? ` <b>${when}</b> 저장분입니다.` : ""}`
      + ` <button type="button" class="button small primary" data-plan-load>불러오기</button>`
      + ` <button type="button" class="link_button" data-plan-clear>지우기</button>`;
    form.prepend(note);
    note.querySelector("[data-plan-load]").addEventListener("click", async () => {
      await applyDraftValues(draft);
      note.className = "flash flash_success prefill_note";
      note.textContent = when ? `📦 ${when} 저장분을 불러왔습니다.` : "📦 적어 두신 견적을 불러왔습니다.";
    });
    note.querySelector("[data-plan-clear]").addEventListener("click", async () => {
      try { draftStore.removeItem(DRAFT_KEY); } catch (error) { /* 무시 */ }
      if (window.ForwardusWorkDraft) await window.ForwardusWorkDraft.clear();
      note.className = "flash prefill_note";
      note.textContent = "📦 적어 둔 견적을 지웠습니다.";
    });
  }

  async function applyDraftValues(draft) {
    DRAFT_FIELDS.forEach((name) => {
      const input = form.elements[name];
      if (input && draft.fields && draft.fields[name] !== undefined) input.value = draft.fields[name];
    });
    if (draft.incoterms) {
      const radio = form.querySelector(`input[name=incoterms][value="${draft.incoterms}"]`);
      if (radio) radio.checked = true;
      syncIncotermCards();
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
    state.lc = draft.lc || null;
    if (state.lc) showLcNote();
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

  /* ----- 도착국에 적용되는 협정·세율 (품목마다 따로) ----- */
  // 품목마다 HS부호가 다르면 세율도 다릅니다. 품목별로 한 덩어리씩 보여줍니다.
  function tariffTargets() {
    const targets = [{
      no: 1,
      name: form.elements.product_description.value.trim(),
      hs: form.elements.hs_code.value.trim(),
    }];
    document.querySelectorAll("[data-cargo-lines] .cargo_item").forEach((row, index) => {
      targets.push({
        no: index + 2,
        name: (row.querySelector('[data-line="product_description"]')?.value || "").trim(),
        hs: (row.querySelector('[data-line="hs_code"]')?.value || "").trim(),
      });
    });
    return targets.filter((target) => target.hs);
  }

  // 품목별 관세 안내는 그 품목 바로 아래에 붙입니다.
  // 첫 품목은 HS부호 칸 아래, 추가 품목은 그 품목 상자 안입니다.
  function tariffSlotFor(no) {
    if (no === 1) return document.querySelector("[data-tariff]");
    const row = document.querySelectorAll("[data-cargo-lines] .cargo_item")[no - 2];
    return row ? row.querySelector("[data-line-tariff]") : null;
  }

  async function refreshTariff() {
    const country = state.destination ? state.destination.country_code : "";
    const targets = tariffTargets();
    const wanted = new Map(targets.map((target) => [target.no, target]));

    // 모든 칸을 먼저 비웁니다. 품목을 지우거나 HS부호를 지운 자리가 남지 않게 합니다.
    const slots = [document.querySelector("[data-tariff]"),
                   ...document.querySelectorAll("[data-cargo-lines] [data-line-tariff]")];
    slots.forEach((slot, index) => {
      if (!slot) return;
      if (!country || !wanted.has(index + 1)) {
        slot.hidden = true;
        slot.innerHTML = "";
      }
    });
    if (!country || !targets.length) return;

    await Promise.all(targets.map((target) => {
      const slot = tariffSlotFor(target.no);
      if (!slot) return null;
      slot.hidden = false;
      slot.innerHTML = `<p class="tariff_note">협정세율을 조회하는 중…</p>`;
      return renderTariffFor(target.hs, country, slot);
    }));
  }

  // ⓘ 설명은 간편 검색 창과 같이 쓰려고 hs_search.js로 옮겼습니다.
  const { infoTip } = window.ForwardusHs;

  async function renderTariffFor(hs, country, slot) {
    if (!slot) return;
    const response = await getJson(`${urls.tariff}?${new URLSearchParams({ hs, country })}`);
    if (!slot.isConnected) return;
    const data = response.success ? response.data : null;
    if (!data) {
      slot.innerHTML = `<p class="tariff_note">협정세율을 받지 못했습니다.</p>`;
      return;
    }

    const rate = (value) => (value === "" || value === undefined ? "-" : `${value}%`);
    const period = (row) => (row.start_date
      ? `${row.start_date.slice(0, 4)}-${row.start_date.slice(4, 6)}-${row.start_date.slice(6)} 적용` : "");

    // 제목 옆 ?에는 HS 6자리·세율 기준 같은 공통 안내를 넣습니다.
    let html = `<details class="tariff_reference"><summary>한국 수입 기준 세율 · 참고</summary><p class="tariff_head"><span><b>${escapeHtml(data.country)}</b> 관련 협정`
      + (data.hs_code ? ` <span class="mono">${escapeHtml(data.hs_code)}</span>` : "") + `</span>`
      + infoTip("협정세율 안내", [data.hs6_note, data.note], { start: true }) + `</p>`;

    if (data.agreements && data.agreements.length) {
      // 한 줄에는 협정명·세율·적용일만. 협정 설명·증명서·발급처는 ?에 넣습니다.
      html += data.agreements.map((row) => `
        <div class="tariff_row">
          <span class="tariff_name">${escapeHtml(row.agreement)}</span>
          <span class="tariff_rate">${escapeHtml(rate(row.rate))}</span>
          <span class="tariff_period">${escapeHtml(period(row))}</span>
          ${infoTip(row.agreement, [row.about, row.proof && `원산지증명: ${row.proof}`,
            row.steps && row.steps.where && `발급처: ${row.steps.where}`])}
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
    // 위 숫자를 도착국 관세로 오해하지 않게 이 한 줄은 늘 보입니다. (자세한 설명은 제목 옆 ?)
    if (data.note) {
      html += `<p class="tariff_note">위 세율은 한국 수입 기준입니다. ${escapeHtml(data.country)}이(가) 매기는 관세는 아래를 보세요.</p>`;
    }
    if (!data.available && data.message) {
      html += `<p class="tariff_plain">${escapeHtml(data.message)}</p>`;
    }
    html += `</details><div class="dest" data-dest-tariff><p class="tariff_note">도착국 관세율표를 조회하는 중…</p></div>`;
    slot.innerHTML = html;
    refreshDestinationTariff(hs, country, slot.querySelector("[data-dest-tariff]"));
  }

  /* ----- 도착국이 실제로 매기는 관세와 그 나라의 세분 부호 ----- */
  // 품목이 여러 개면 동시에 조회하므로 순번은 칸마다 따로 셉니다.
  // (하나로 세면 나중 응답이 먼저 온 품목의 결과를 지웁니다)
  const destinationTokens = new WeakMap();
  async function refreshDestinationTariff(hs, country, slot) {
    if (!slot) return;
    const token = (destinationTokens.get(slot) || 0) + 1;
    destinationTokens.set(slot, token);
    const response = await getJson(`${urls.destinationTariff}?${new URLSearchParams({ hs, country })}`);
    if (destinationTokens.get(slot) !== token || !slot.isConnected) return;
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

    // 세율 출처·세분 부호 안내는 제목 옆 ?로 옮깁니다. 화면에는 세율과 조언만 둡니다.
    let html = `<p class="tariff_head"><span>${escapeHtml(data.country)}에서 이 물품에 매기는 관세`
      + ` <span class="mono">HS ${escapeHtml(data.hs6)}</span></span>`
      + infoTip("도착국 관세 안내", [data.rate_note, data.national_note], { start: true }) + `</p>`;

    if (data.rates.length) {
      html += `<div class="dest_rates">` + data.rates.map(row =>
        `<span class="dest_rate"><b>${escapeHtml(row.label)}${row.rate != null ? " · HS6 평균" : ""}</b>`
        + `<strong>${row.rate == null ? "자료 없음" : escapeHtml(pct(row.rate))}</strong>`
        + infoTip(row.label, [row.note, row.rate != null && `${spread(row)}${row.year}년 기준`, data.rate_note]) + `</span>`
      ).join("") + `</div>`;
    }
    if (data.advice) {
      html += `<p class="dest_advice ${escapeHtml(data.advice.kind)}">${escapeHtml(data.advice.text)}</p>`;
    }
    if (data.national) {
      const n = data.national;
      // Preserve parent conditions with each excerpt; HSK suffixes cannot select foreign lines.
      let context = [];
      const leaves = [];
      const depthOf = line => {
        if (country !== "JP") return Number(line.indent || 0);
        if (/\d{4}\.\d{2}-\d{3}/.test(line.code || "")) return 10;
        const description = line.description.trimStart();
        if (/^\d+\s/.test(description)) return 1;
        if (/^\(\d+\)/.test(description)) return 2;
        const dashes = description.match(/^[-–]+/);
        return dashes ? dashes[0].length + 2 : (/^["“]/.test(description) ? 3 : 0);
      };
      n.lines.forEach((line, index) => {
        const depth = depthOf(line);
        context = context.filter(parent => parent.depth < depth);
        const next = n.lines[index + 1];
        const detailed = (line.code || "").replace(/\D/g, "").length > 6;
        if (detailed && (!next || depthOf(next) <= depth)) {
          leaves.push({...line, context: [...context]});
        }
        context.push({depth, description: line.description});
      });
      const rows = leaves.length ? leaves : n.lines;
      const table = selected => `<div class="dest_table_wrap"><table class="dest_table"><thead><tr><th>부호 / 품목</th>`
        + n.columns.map(c => `<th>${escapeHtml(c.label)}</th>`).join("") + `</tr></thead><tbody>`
        + selected.map(line => `<tr><td><b class="mono">${cell(line.code)}</b>`
          + `<span class="tariff_excerpt">${escapeHtml(line.description)}</span>`
          + infoTip("품목 원문·상위 조건", [...(line.context || []).map(parent => parent.description), line.description]) + `</td>`
          + n.columns.map(c => `<td>${cell(line[c.key])}</td>`).join("") + `</tr>`).join("") + `</tbody></table></div>`;
      html += `<p class="dest_sub">${escapeHtml(n.label)}`
        + infoTip("관세율표 기준", [n.edition && `${n.edition} 기준`, data.national_note]) + `</p>`
        + `<p class="tariff_note">HS ${escapeHtml(data.hs6)} 내 ${rows.length}개 세부 품목 · 적용 품목을 확인하세요.</p>`;
      if (rows.length) {
        html += `<label class="national_picker">세부 품목<select data-national-line aria-label="관세율표 세부 품목">`
          + `<option value="">일부 미리보기 (${Math.min(3, rows.length)}개)</option>`
          + rows.map((line, i) => `<option value="${i}">${escapeHtml(line.code)} · ${escapeHtml(line.description)}</option>`).join("")
          + `</select></label><div data-national-excerpt>${table(rows.slice(0, 3))}</div>`;
      } else {
        html += `<p class="tariff_note">세부 품목 자료가 없습니다. 공식 원문에서 확인하세요.</p>`;
      }
      // Attach after the HTML has been inserted below.
      slot._nationalExcerpt = {rows, table};
    }
    html += `<a class="dest_link"href="${escapeHtml(data.link.url)}" target="_blank" rel="noopener noreferrer">`
      + `${escapeHtml(data.link.label)} 열기 <span aria-hidden="true">↗</span>`
      + `<small>새 창에서 열립니다</small></a>`;
    slot.innerHTML = html;
    slot.querySelector("[data-national-line]")?.addEventListener("change", event => {
      const {rows, table} = slot._nationalExcerpt;
      const value = event.target.value;
      slot.querySelector("[data-national-excerpt]").innerHTML = table(value === "" ? rows.slice(0, 3) : [rows[Number(value)]]);
    });
  }

  /* ----- HS부호 찾기 (첫 품목과 추가 품목이 같은 방식을 씁니다) ----- */
  const hsOrder = form.querySelector("[data-hs-order]");
  const hsControllers = [];

  // 품명(한글·영문)이나 HS부호로 관세청에서 찾습니다.
  // 조회·그리기는 hs_search.js에 있습니다. HS CODE 간편 검색 창과 같은 것을 씁니다.
  const { renderHsItem, hsSearchedAsRow, hsEmptyMessage, HS_AUTOCOMPLETE_OPTIONS } = window.ForwardusHs;
  const fetchHsCodes = (query, fallback) => window.ForwardusHs.fetchHsCodes(query, fallback, {
    url: urls.hsCodes, country: state.destination?.country_code || "",
    order: hsOrder?.value || "frequency" });

  const hsSearch = setupAutocomplete(
    form.querySelector("[data-autocomplete=hs_code]"),
    (q) => fetchHsCodes(q, form.elements.product_description.value),
    renderHsItem,
    (item, input) => {
      if (!item) return;
      input.value = item.code;
      refreshTariff();     // 고른 품목의 협정세율을 아래에 보여줍니다.
    },
    // 간편 검색 창과 같은 설정입니다. (hs_search.js)
    HS_AUTOCOMPLETE_OPTIONS,
  );
  hsControllers.push(hsSearch);
  hsOrder?.addEventListener("change", () => {
    hsSearch.showAll();
    hsControllers.slice(1).forEach((controller) => controller.refresh());
  });

  // 품명을 한글로 적으면 HS부호 후보를 바로 띄웁니다. (고르는 것은 사람이 합니다)
  const suggestHsFromName = debounce(() => {
    if (form.elements.hs_code.value.trim()) return;   // 이미 고른 부호가 있으면 두십니다.
    if (form.elements.product_description.value.trim().length < 2) return;
    hsSearch.showAll();
  }, 600);
  form.elements.product_description.addEventListener("input", suggestHsFromName);

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
        <div class="field autocomplete" data-un-search>
          <span class="field_label">UN 번호</span>
          <input class="text_input" type="text" data-dg="un_number" data-ac-input maxlength="60"
                 placeholder="번호 또는 물품 이름 (예: UN1263, 페인트, 배터리)" autocomplete="off">
          <ul class="ac_list" data-ac-list hidden></ul>
          <small class="field_hint">MSDS 14번 항목(운송 정보)에 적혀 있습니다.
            <button type="button" class="link_button" data-un-help>어떻게 찾나요?</button></small>
        </div>
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
      <div class="dg_help" data-un-help-box hidden></div>
      <div class="dg_guide" data-dg-guide hidden></div>
      <div class="handling_option cold">
        <label class="dg_check">
          <input type="checkbox" data-handling-toggle="temperature_requirement" aria-label="냉동·냉장 화물">
          <span>냉동·냉장이 필요한 화물입니다</span>
        </label>
        <label class="handling_detail" data-handling-panel="temperature_requirement" hidden>
          <span>보관 조건</span>
          <select data-handling="temperature_requirement" aria-label="화물 보관 조건">
            <option value="unspecified">협의 필요</option>
            <option value="chilled">냉장 (Chilled)</option>
            <option value="frozen">냉동 (Frozen)</option>
          </select>
          <small>설정 온도와 냉장 장비는 운송사와 확인하세요.</small>
        </label>
      </div>
      <div class="handling_option special">
        <label class="dg_check">
          <input type="checkbox" data-handling-toggle="special_container_type" aria-label="특수 컨테이너 필요">
          <span>특수 컨테이너가 필요한 화물입니다</span>
        </label>
        <label class="handling_detail" data-handling-panel="special_container_type" hidden>
          <span>컨테이너 종류</span>
          <select data-handling="special_container_type" aria-label="필요한 특수 컨테이너 종류">
            <option value="unspecified">협의 필요</option>
            <option value="open_top">오픈탑 (Open Top)</option>
            <option value="flat_rack">플랫랙 (Flat Rack)</option>
            <option value="tank">탱크 (Tank)</option>
            <option value="other">기타 특수 장비</option>
          </select>
          <small>특수 장비의 적재 가능 여부·수량·운임은 별도 확인이 필요합니다.</small>
        </label>
      </div>`;
  }

  /* ----- UN번호 찾기 ----- */
  let unLookupHelp = null;

  function wireUnSearch(box) {
    const container = box.querySelector("[data-un-search]");
    const input = container.querySelector("[data-ac-input]");

    setupAutocomplete(
      container,
      async (query) => {
        const response = await getJson(`${urls.unNumbers}?${new URLSearchParams({ q: query })}`);
        if (!response.success) return [];
        unLookupHelp = response.data;
        return response.data.items;
      },
      (item) => `<span class="ac_title"><b>${escapeHtml(item.un_number)}</b>`
        + `<span class="muted">${escapeHtml(item.class_label)}</span></span>`
        + `<small>${escapeHtml(item.korean_name)} · ${escapeHtml(item.proper_shipping_name)}</small>`,
      (item) => {
        if (!item) return;
        // 고르면 등급과 정식운송품명까지 한 번에 채웁니다.
        input.value = item.un_number;
        box.querySelector('[data-dg="dg_class"]').value = item.dg_class;
        box.querySelector('[data-dg="proper_shipping_name"]').value = item.proper_shipping_name;
        box.refreshDg();
      },
      { emptyMessage: () => "목록에 없습니다. MSDS에 적힌 번호를 그대로 입력하세요." },
    );

    const helpBox = box.querySelector("[data-un-help-box]");
    box.querySelector("[data-un-help]").addEventListener("click", async () => {
      if (!helpBox.hidden) { helpBox.hidden = true; return; }
      if (!unLookupHelp) {
        const response = await getJson(`${urls.unNumbers}?q=`);
        unLookupHelp = response.success ? response.data : null;
      }
      if (!unLookupHelp) return;
      helpBox.innerHTML = `<p class="dg_sub">UN번호 찾는 방법</p>`
        + unLookupHelp.steps.map((s) => `<p class="dg_line"><b>${escapeHtml(s.title)}</b><br>`
          + `${escapeHtml(s.body)}`
          + (s.link ? ` <a href="${escapeHtml(s.link.url)}" target="_blank" rel="noopener noreferrer">`
            + `${escapeHtml(s.link.label)} ↗</a>` : "") + `</p>`).join("")
        + `<p class="tariff_note">${escapeHtml(unLookupHelp.note)}</p>`;
      helpBox.hidden = false;
    });
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
      box.querySelectorAll("[data-handling-toggle]").forEach(input => {
        box.querySelector(`[data-handling-panel="${input.dataset.handlingToggle}"]`).hidden = !input.checked;
      });
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
    box.querySelectorAll("[data-handling-toggle], [data-handling]")
      .forEach(input => input.addEventListener("change", sync));
    select.addEventListener("change", sync);
    box.querySelectorAll('[data-dg="un_number"], [data-dg="proper_shipping_name"]')
      .forEach((input) => input.addEventListener("input", () => { recalc(); saveDraftSoon(); }));
    box.querySelector('[data-dg="packing_group"]').addEventListener("change", saveDraftSoon);
    box.refreshDg = sync;
    wireUnSearch(box);
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
    box.querySelectorAll("[data-handling-toggle]").forEach(input => {
      const key = input.dataset.handlingToggle;
      values[key] = input.checked ? box.querySelector(`[data-handling="${key}"]`).value : "";
    });
    return values;
  }

  function setDgValues(box, values = {}) {
    if (!box || !values) return;
    box.querySelector('[data-dg="is_dangerous"]').checked = Boolean(values.is_dangerous);
    DG_FIELDS.forEach((key) => { box.querySelector(`[data-dg="${key}"]`).value = values[key] || ""; });
    box.querySelectorAll("[data-handling-toggle]").forEach(input => {
      const key = input.dataset.handlingToggle;
      input.checked = Boolean(values[key]);
      box.querySelector(`[data-handling="${key}"]`).value = values[key] || "unspecified";
    });
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
    ["hs_code", "HS CODE", "hs", "span2"],
    ["package_type", "포장 유형", "select", ""],
    ["quantity", "수량 (Quantity)", "number", "", { step: 1, min: 1, mode: "numeric" }],
    ["length_cm", "가로 Length (cm)", "number", "", { step: 1, min: 0 }],
    ["width_cm", "세로 Width (cm)", "number", "", { step: 1, min: 0 }],
    ["height_cm", "높이 Height (cm)", "number", "", { step: 1, min: 0 }],
    ["weight_per_package_kg", "포장당 총중량 (kg)", "number", "", { step: 10, min: 0 }],
    ["net_weight_kg", "총 순중량 Net Weight (kg)", "number", "", { step: 10, min: 0 }],
    ["amount", "금액 Amount", "number", "", { step: 100, min: 0 }],
  ];

  function lineFieldHtml([key, label, kind, span, opts = {}]) {
    if (kind === "hs") {
      // 첫 품목과 똑같이 관세청 HS부호 검색을 붙입니다.
      return `<div class="field autocomplete ${span}" data-line-hs>`
        + `<span class="field_label">${escapeHtml(label)}</span>`
        + `<input class="text_input" type="text" data-line="${key}" data-ac-input autocomplete="off"`
        + ` placeholder="품명 또는 HS부호 10자리">`
        + `<ul class="ac_list" data-ac-list hidden></ul></div>`;
    }
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
        ${LINE_LAYOUT.map((field) => lineFieldHtml(field)
          // 관세 안내는 HS부호 바로 아래에 붙습니다. 첫 품목과 자리를 맞춥니다.
          + (field[0] === "hs_code" ? `<div class="tariff span2" data-line-tariff hidden></div>` : "")
        ).join("")}
        <div class="field span2 dg_box" data-dg-box>${dgBoxHtml()}</div>
      </div>`;
    cargoLinesBox.appendChild(row);
    row.querySelectorAll("[data-line]").forEach((input) => {
      if (values[input.dataset.line] !== undefined) input.value = values[input.dataset.line];
      if (input.dataset.number !== undefined) setupNumberInput(input);
      const changed = () => {
        recalc();
        invalidateSchedules();
        saveDraftSoon();
        // 품목마다 HS부호가 다르면 도착국 세율도 다릅니다.
        if (input.dataset.line === "hs_code" || input.dataset.line === "product_description") {
          refreshTariff();
        }
      };
      input.addEventListener("input", changed);
      input.addEventListener("change", changed);
    });
    // 이 줄의 품명을 기준으로 HS부호를 찾습니다.
    const nameInput = row.querySelector('[data-line="product_description"]');
    const hsBox = row.querySelector("[data-line-hs]");
    const hsRow = setupAutocomplete(
      hsBox,
      (q) => fetchHsCodes(q, nameInput.value),
      renderHsItem,
      (item, input) => { if (item) { input.value = item.code; refreshTariff(); } },
      { emptyMessage: hsEmptyMessage, leadRow: hsSearchedAsRow, delayMs: 650, keepOpen: true,
        loadingMessage: "AI 품명 해석·후보 적합도·건수·관세를 비교 중…" },
    );
    hsControllers.push(hsRow);
    const suggest = debounce(() => {
      if (hsBox.querySelector("[data-ac-input]").value.trim()) return;
      if (nameInput.value.trim().length >= 2) hsRow.showAll();
    }, 600);
    nameInput.addEventListener("input", suggest);

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
    refreshTariff();
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
      amount: plainNumber(f.amount.value),
    };
    const extras = extraCargoEntries();
    lastCargoBoxes = [mainDgBox, ...extras.map(({ box }) => box)];
    return { items: [first, ...extras.map(({ item }) => item)] };
  }

  const currencyCode = () => form.elements.currency.value || "USD";
  const calcLinesBox = document.querySelector("[data-calc-lines]");
  const calcTotalTitle = document.querySelector("[data-calc-total-title]");

  // 품목이 둘 이상이면 품목별 CBM·중량을 따로 보여주고 아래에 합계를 둡니다.
  function renderMetricLines(metrics) {
    const lines = (metrics && metrics.lines) || [];
    const show = lines.length > 1;
    calcLinesBox.hidden = !show;
    calcTotalTitle.hidden = !show;
    if (!show) { calcLinesBox.innerHTML = ""; return; }
    calcLinesBox.innerHTML = lines.map((line, index) => `
      <div class="calc_line">
        <p class="calc_line_title">품목 ${index + 1}${line.product_description
          ? ` <small>${escapeHtml(line.product_description)}</small>` : ""}</p>
        <dl>
          <div><dt>CBM</dt><dd>${formatNumber(line.total_cbm, 3)} CBM</dd></div>
          <div><dt>중량</dt><dd>${formatNumber(line.total_weight_kg, 1)} kg</dd></div>
          ${line.amount === null || line.amount === undefined ? "" :
            `<div><dt>금액</dt><dd>${currencyCode()} ${formatNumber(line.amount, 2)}</dd></div>`}
        </dl>
      </div>`).join("");
  }

  function renderMetrics(metrics) {
    const set = (key, text) => { document.querySelector(`[data-metric=${key}]`).textContent = text; };
    renderMetricLines(metrics);
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
    renderSeaAdvice(metrics.sea_mode_advice);
    syncInvoiceValue(metrics.amount);
  }

  /* ----- 이 짐이면 LCL인가 FCL인가 -----
     기준은 서버(processors/sea_mode_advisor)가 정합니다. 여기서는 보여 주고,
     누르면 [해상 운송 방식]을 그 값으로 바꿔 줍니다. 항공을 고른 동안에는 뜻이 없어 숨깁니다. */
  const seaAdviceBox = document.querySelector("[data-sea-advice]");

  function renderSeaAdvice(advice) {
    if (!seaAdviceBox) return;
    if (!advice || !advice.mode || state.transport_mode === "AIR") {
      seaAdviceBox.hidden = true;
      seaAdviceBox.innerHTML = "";
      return;
    }
    const same = advice.mode === state.sea_mode;
    const notes = (advice.notes || []).map((note) => `<small>${escapeHtml(note)}</small>`).join("");
    seaAdviceBox.className = `sea_advice ${advice.confidence === "clear" ? "is_clear" : "is_close"}`;
    seaAdviceBox.innerHTML = `<b>${escapeHtml(advice.mode)} ${advice.confidence === "clear" ? "권장" : "쪽 (경계 구간)"}</b>`
      + ` <span>${escapeHtml(advice.reason)}</span>`
      + (same ? `<em class="sea_advice_same">지금 고른 방식과 같습니다</em>`
              : ` <button type="button" class="link_button" data-sea-apply="${escapeHtml(advice.mode)}">`
                + `${escapeHtml(advice.mode)}로 바꾸기</button>`)
      + notes;
    seaAdviceBox.hidden = false;
  }

  seaAdviceBox?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-sea-apply]");
    if (!button) return;
    const target = form.querySelector(`[data-toggle=sea_mode] [data-value=${button.dataset.seaApply}]`);
    if (target) target.click();
    renderSeaAdvice(state.metrics ? state.metrics.sea_mode_advice : null);
  });

  // 품목별 금액을 모두 적었으면 Invoice Value를 그 합으로 맞춥니다.
  // 한 건이라도 비어 있으면 손대지 않아 직접 적은 값이 남습니다.
  const invoiceAutoTag = document.querySelector("[data-invoice-auto]");
  function syncInvoiceValue(amount) {
    const box = form.elements.invoice_value;
    if (amount === null || amount === undefined) {
      box.readOnly = false;
      if (invoiceAutoTag) invoiceAutoTag.hidden = true;
      return;
    }
    box.value = formatNumber(amount, 2);
    box.readOnly = true;
    if (invoiceAutoTag) invoiceAutoTag.hidden = false;
  }

  /* 값은 다 찼는데 **앞뒤가 안 맞는** 화물을 알려 줍니다.

     서버는 이런 말을 만들어 보내고 있었습니다.
       "1CBM당 19,200kg이니 금만큼 무겁습니다. 포장당 중량 칸에 전체 중량을
        적지 않았는지 확인해주세요"
     그런데 화면 어디에도 붙지 않아 **아무도 못 봤습니다.** 포장당 중량 칸에
     전체 중량을 적으면 운임 기준이 100배 틀립니다. 계산은 멀쩡히 되고 숫자도
     그럴듯해서, 견적을 받고 나서야 압니다. (2026-09-26) */
  const cargoWarnBox = document.querySelector("[data-calc-warnings]");

  function showCargoWarnings(warnings) {
    if (!cargoWarnBox) return;
    const rows = (warnings || []).filter((row) => row && row.message);
    cargoWarnBox.hidden = !rows.length;
    cargoWarnBox.innerHTML = rows.map((row) =>
      `<li><b>품목 ${row.line_no}</b> ${escapeHtml(row.message)}</li>`).join("");
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
    showCargoWarnings(response.success ? response.data.warnings : []);
    calcMessage.textContent = response.success ? "서버에서 계산된 값입니다." : response.message;
  }, 250);

  /* 치수·수량·중량이 바뀌면 부피가 달라져 운임과 컨테이너 수가 달라집니다.
     그래서 스케줄을 다시 찾습니다.

     **금액은 아닙니다.** 송장 금액은 배가 언제 뜨는지와 아무 상관이 없는데,
     금액 칸에 글자 하나만 쳐도 고른 스케줄이 지워졌습니다. 서류 작성 화면에서
     같은 일로 "골라도 골라도 다시 고르라고 한다"는 신고를 받았습니다.
     (2026-09-26) */
  const CALC_NOT_SCHEDULE = new Set(["amount", "unit_price"]);
  form.querySelectorAll("[data-calc]").forEach((input) => input.addEventListener("input", () => {
    recalc();
    if (!CALC_NOT_SCHEDULE.has(input.name || input.dataset.line || "")) invalidateSchedules();
  }));
  form.elements.hs_code.addEventListener("change", () => refreshTariff());
  form.elements.package_type.addEventListener("change", () => {
    const note = document.querySelector("[data-package-note]");
    if (note) note.textContent = form.elements.package_type.selectedOptions[0]?.dataset.note || "";
    // 포장 유형은 부피·중량 계산에만 쓰입니다. 배가 언제 뜨는지와는 무관하므로
    // 고른 스케줄을 지우지 않습니다. (2026-09-26)
  });

  /* ----- Schedules ----- */
  const scheduleList = document.querySelector("[data-schedule-list]");
  const scheduleMeta = document.querySelector("[data-schedule-meta]");
  const scheduleNote = document.querySelector("[data-schedule-note]");

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

  /* ----- 신용장(L/C) 선적 마감 -----
     L/C는 "이 날까지 배에 실어야" 대금을 받습니다. 마감을 넘겨 출항하는 배를 고르면
     서류가 은행에서 거절됩니다. 마감은 서버가 계산합니다. (processors/lc_schedule.py) */
  function showLcNote() {
    if (!state.lc || document.querySelector(".lc_note")) return;
    const lc = state.lc;
    const note = document.createElement("div");
    note.className = `flash lc_note ${lc.feasible ? "flash_success" : "flash_error"}`;
    note.setAttribute("role", "status");
    note.innerHTML = `📑 <b>L/C 선적 마감 ${escapeHtml(lc.deadline)}</b>`
      + ` · 권장 선적일 ${escapeHtml(lc.recommended_etd)}`
      + (lc.eta_from ? ` · 도착 예상 ${escapeHtml(lc.eta_from)}~${escapeHtml(lc.eta_to)}` : "")
      + ` · 서류 제시 ${escapeHtml(lc.presentation_by)}까지`
      + `<small>${escapeHtml((lc.notes || [])[0] || "")}</small>`;
    form.prepend(note);
  }

  // 이 배로 실으면 L/C 마감을 지킬 수 있는지. (ETD = 선적일로 봅니다)
  function lcBadge(etd) {
    if (!state.lc || !state.lc.deadline || !etd) return "";
    const left = Math.round((new Date(state.lc.deadline) - new Date(etd)) / 86400000);
    if (left < 0) return `<span class="badge bad">L/C 마감 ${Math.abs(left)}일 초과</span>`;
    if (left <= 2) return `<span class="badge warn">L/C 마감 ${left}일 전</span>`;
    return `<span class="badge ok">L/C 마감 ${left}일 전</span>`;
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
              ${lcBadge(s.etd)}${deadline}
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

  // 스케줄 카드를 두 번 누르면 그 스케줄로 고르고 다음 단계로 넘어갑니다.
  scheduleList.addEventListener("dblclick", (event) => {
    const card = event.target.closest(".schedule_card");
    if (!card) return;
    const radio = card.querySelector('input[name="schedule_id"]');
    if (!radio) return;
    if (state.schedule_id !== radio.value) {
      state.schedule_id = radio.value;
      renderSchedules();
      saveDraftSoon();
    }
    openStep(state.step + 1);
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
    scheduleMeta.textContent = `${state.origin.name} → ${state.destination.name} · ${state.departure_date} 이후 출발 · ${state.schedules.length}건`;
    // 예시 스케줄을 보여 주는 중이면 지나치기 쉬운 회색 글 대신 경고 상자로 알립니다.
    scheduleNote.hidden = !response.data.note;
    scheduleNote.textContent = response.data.note || "";
    renderSchedules();
    return true;
  }

  bindToggle(document.querySelector("[data-sort]"), (value) => { state.sort = value; loadSchedules(); });

  /* ----- Incoterms: 칸 선택 · 물음표 설명 팝업 ----- */
  // 두 동작을 따로 둡니다. 칸을 누르면 선택만(selectedIncoterm = radio 값),
  // 물음표를 누르면 설명만(helpIncoterm) 엽니다. 설명을 열고 닫아도 선택은 그대로입니다.
  // 선택값은 기존 radio(name=incoterms)에 담아 임시 저장·요약·Shipment 생성이 그대로 읽습니다.
  const INCOTERM_REQUIRED = "인코텀즈를 선택해 주세요.";
  const incotermData = window.FORWARDUS_INCOTERMS || { terms: [], steps: [] };
  const incotermByCode = Object.fromEntries(incotermData.terms.map((term) => [term.code, term]));
  const incotermModal = document.querySelector("[data-incoterm-modal]");
  let helpIncoterm = null;
  let helpButton = null;

  function checkedIncoterm() {
    return form.querySelector("input[name=incoterms]:checked");
  }

  // 화면의 강조는 CSS(:checked + 칸)가 맡고, 읽어 주는 프로그램용 상태만 맞춥니다.
  // 흐름 그림의 비용·위험 색칠도 같은 때에 다시 그립니다(선택·임시 저장 복원 모두 여기를 지납니다).
  function syncIncotermCards() {
    const current = checkedIncoterm();
    document.querySelectorAll("[data-incoterm-pick]").forEach((button) => {
      button.setAttribute("aria-pressed", current && current.value === button.dataset.incotermPick ? "true" : "false");
    });
    renderFlowHighlight(current ? incotermByCode[current.value] : null);
  }

  /* 흐름 그림 색칠은 인코텀즈 화면(/lookup/incoterms)과 같은 코드를 씁니다.
     규칙(C조건은 비용과 위험의 끝이 다름)이 두 군데에 따로 적히면 한쪽만 고쳐집니다. */
  function renderFlowHighlight(term) {
    window.ForwardusIncotermFlow.render(document, term, incotermData.steps.length);
  }

  function selectIncoterm(code) {
    const radio = form.querySelector(`input[name=incoterms][value="${code}"]`);
    // 이미 고른 조건을 다시 눌러도 해제하지 않습니다.
    if (radio && !radio.checked) {
      radio.checked = true;
      radio.dispatchEvent(new Event("change", { bubbles: true }));
    }
    syncIncotermCards();
    if (errorBox.textContent === INCOTERM_REQUIRED) showError("");
  }

  document.querySelectorAll("[data-incoterm-pick]").forEach((button) => {
    button.addEventListener("click", () => selectIncoterm(button.dataset.incotermPick));
  });

  function renderIncotermHelp(term) {
    const mode = term.sea_only ? "해상·내수로 전용" : "모든 운송수단";
    incotermModal.querySelector("[data-modal-title]").textContent = `${term.code} · ${term.name}`;
    incotermModal.querySelector("[data-modal-sub]").textContent = `${term.label} · ${mode}`;
    incotermModal.querySelector("[data-modal-body]").innerHTML = `
      <p>${escapeHtml(term.detail)}</p>
      <dl class="tip_facts">
        <div><dt>판매자 주요 비용</dt><dd>${escapeHtml(term.seller_cost)}</dd></div>
        <div><dt>Buyer 주요 비용</dt><dd>${escapeHtml(term.buyer_cost)}</dd></div>
        <div><dt>위험 이전</dt><dd>${escapeHtml(term.risk)}</dd></div>
      </dl>
      <p class="incoterm_caution"><i>헷갈리기 쉬운 점</i>${escapeHtml(term.caution)}</p>`;
  }

  function openIncotermHelp(button) {
    const term = incotermByCode[button.dataset.incotermHelp];
    if (!incotermModal || !term) return;
    helpIncoterm = term.code;
    helpButton = button;
    renderIncotermHelp(term);
    if (!incotermModal.open) {
      incotermModal.showModal();
      document.documentElement.classList.add("modal_open");
    }
    incotermModal.querySelector("[data-modal-body]").scrollTop = 0;
    incotermModal.querySelector(".incoterm_modal_close").focus();
  }

  document.querySelectorAll("[data-incoterm-help]").forEach((button) => {
    button.addEventListener("click", (event) => {
      // 칸의 선택 동작이 함께 돌지 않게 합니다.
      event.stopPropagation();
      openIncotermHelp(button);
    });
  });

  if (incotermModal) {
    incotermModal.addEventListener("click", (event) => {
      // X 단추, 또는 팝업 바깥(어두운 배경)을 누르면 닫습니다.
      if (event.target.closest("[data-modal-close]") || event.target === incotermModal) incotermModal.close();
    });
    // Esc는 브라우저가 dialog를 닫아 줍니다. 어떤 길로 닫히든 여기서 마무리하고 물음표로 초점을 돌려줍니다.
    incotermModal.addEventListener("close", () => {
      document.documentElement.classList.remove("modal_open");
      helpIncoterm = null;
      if (helpButton) helpButton.focus();
    });
    // 팝업이 열린 동안 Tab 초점이 팝업 안에서만 돕니다.
    incotermModal.addEventListener("keydown", (event) => {
      if (event.key !== "Tab") return;
      const focusables = Array.from(incotermModal.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'))
        .filter((el) => !el.disabled && el.offsetParent !== null);
      if (!focusables.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
  }

  /* ----- Step validation ----- */
  // 스케줄 조회에 실제로 필요한 것만 봅니다. 견적명은 견적에 붙이는 이름일 뿐이라
  // 운항 정보를 보는 데는 필요하지 않습니다.
  function scheduleBlocker() {
    if (!state.origin) return { message: "출발지를 목록에서 선택해주세요.", step: 1 };
    if (!state.destination) return { message: "도착지를 목록에서 선택해주세요.", step: 1 };
    if (!state.departure_date) return { message: "캘린더에서 출발 희망일을 선택해주세요.", step: 1 };
    if (!state.metrics) return { message: "화물 치수·수량·중량을 입력해주세요.", step: 3 };
    return null;
  }

  function validateStep(step) {
    const f = form.elements;
    if (step === 1) {
      if (!f.project_name.value.trim()) return "견적명을 입력해주세요.";
      if (!state.departure_date) return "캘린더에서 출발 희망일을 선택해주세요.";
      if (!state.origin) return "출발지를 목록에서 선택해주세요.";
      if (!state.destination) return "도착지를 목록에서 선택해주세요.";
    }
    if (step === 2 && !checkedIncoterm()) return INCOTERM_REQUIRED;
    if (step === 3) {
      if (!f.product_description.value.trim()) return "품명을 입력해주세요.";
      if (!state.metrics) return "화물 치수·수량·중량을 올바르게 입력해주세요.";
      if (!plainNumber(f.invoice_value.value)) return "Invoice Value를 입력해주세요.";
    }
    if (step === 4 && !state.schedule_id) return "스케줄을 선택해주세요.";
    return "";
  }

  // 막는 오류가 아니라 "한 번 더 확인"인 것들. 다시 누르면 그대로 진행합니다.
  const CONFIRMABLE = { INCOTERMS_CONFIRM: "incoterms_confirmed" };
  const confirmed = {};

  function handleServerError(response) {
    const step = FIELD_STEP[response.field];
    if (step && step !== state.step) goToStep(step);
    const flag = CONFIRMABLE[response.error_code];
    if (flag) {
      confirmed[flag] = true;
      showConfirm(response.message);
      return;
    }
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
      const blocker = scheduleBlocker();
      if (blocker) {
        scheduleMeta.textContent = "";
        const where = blocker.step === 1 ? "1 Route" : "3 Cargo";
        scheduleList.innerHTML = `<p class="muted">${escapeHtml(blocker.message)}`
          + ` <button type="button" class="link_button" data-goto-step="${blocker.step}">${where} 단계로 이동</button></p>`;
      } else {
        await loadSchedules();
      }
    }
    if (step === 5) renderSummary();
  }

  form.addEventListener("click", (event) => {
    if (event.target.matches("[data-prev]")) openStep(state.step - 1);
    if (event.target.matches("[data-next]")) {
      // Incoterms 단계는 조건을 골라야 넘어갑니다. 그림 팝업을 봤는지는 따지지 않습니다.
      if (state.step === 2 && !checkedIncoterm()) {
        showError(INCOTERM_REQUIRED);
        const first = document.querySelector("[data-incoterm-pick]");
        if (first) first.focus({ preventScroll: true });
        return;
      }
      openStep(state.step + 1);
    }
    const goto = event.target.closest("[data-goto-step]");
    if (goto) openStep(Number(goto.dataset.gotoStep));
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
      + ` <em title="거리는 실제 바닷길·대권거리로 구했습니다. 직기항·직항 여부는 운항 기록에서 모은 연결 자료로 판정한 것이고, 나가는 편 기준입니다. 어느 선사·항공사가 그 구간에 정기편을 넣는지는 따로 확인해야 합니다.">항로망 거리 기반 추정 · 출발 기준</em></p>`
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
      `<span class="date_item departure"><i></i>Seller 발송 예상일 ${state.departure_date || "미선택"}</span>`
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
      showError("Buyer 요청 도착일은 Seller 발송 예상일보다 빠를 수 없습니다.");
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
        ...confirmed,
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

  /* ----- 5단계: Buyer 국가 검색과 Notify Party ----- */
  // Buyer 국가는 나라 이름을 몰라도 고를 수 있게 검색을 붙입니다.
  const buyerCountryBox = document.querySelector("[data-buyer-country]");
  if (buyerCountryBox) {
    setupAutocomplete(
      buyerCountryBox,
      async (q) => {
        const list = await loadCountries(state.transport_mode);
        const query = q.trim().toLowerCase();
        if (!query) return list.slice(0, 30);
        return list.filter((c) => c.name.includes(q.trim())
          || (c.name_en || "").toLowerCase().includes(query)
          || c.code.toLowerCase() === query).slice(0, 30);
      },
      (c) => `<span class="ac_title"><b>${escapeHtml(c.name)}</b>`
        + `<small>${escapeHtml(c.name_en || "")} · ${escapeHtml(c.code)}</small></span>`,
      (item, input) => { if (item) input.value = item.name; saveDraftSoon(); },
      { emptyMessage: () => "그 이름의 나라를 찾지 못했습니다. 직접 적어도 됩니다." },
    );
  }

  // Notify Party는 대개 Buyer와 같습니다. 체크돼 있으면 Buyer 이름을 그대로 씁니다.
  const notifySame = document.querySelector("[data-notify-same]");
  function syncNotifyParty() {
    if (!notifySame) return;
    const box = form.elements.notify_party;
    if (notifySame.checked) {
      box.value = form.elements.buyer_name.value.trim() || "SAME AS CONSIGNEE";
      box.readOnly = true;
      box.classList.add("is_locked");
    } else {
      box.readOnly = false;
      box.classList.remove("is_locked");
    }
  }
  if (notifySame) {
    notifySame.addEventListener("change", () => { syncNotifyParty(); saveDraftSoon(); });
    form.elements.buyer_name.addEventListener("input", syncNotifyParty);
    // 불러온 초안에 Buyer와 다른 값이 들어 있으면 체크를 풀어 둡니다.
    const restored = form.elements.notify_party.value.trim();
    if (restored && restored !== "SAME AS CONSIGNEE"
        && restored !== form.elements.buyer_name.value.trim()) {
      notifySame.checked = false;
    }
    syncNotifyParty();
  }

  /* ----- 서류 작성에서 적은 값으로 미리 채우기 -----
     서류 작성(직접 입력 · 올린 B/L·오퍼시트 · 대화)에서 적은 송하인·수하인·POL/POD·품목·
     수량·중량·치수·Incoterms·통화·금액을 이 화면의 칸에 채웁니다. (/api/work-draft/planning)
     이 화면에서 그 뒤에 고친 것이 있으면 그것이 더 새것이라 덮지 않습니다. */
  const SOURCE_LABELS = { document: "서류 작성 화면", upload: "올린 서류", chat: "대화" };

  // (SOURCE_LABELS는 restoreDraft의 안내 한 줄이 씁니다. 예전에는 여기서 따로
  //  "미리 채웠습니다" 줄을 띄웠는데, 이제 채우는 것은 사람이 누를 때입니다.)

  async function adoptWorkDraft() {
    if (!window.ForwardusWorkDraft) return;
    const shared = await window.ForwardusWorkDraft.planningPrefill();
    if (!shared) return;
    const local = loadDraft();
    if (local && (local.savedAt || 0) >= shared.savedAt) return;
    // 서류에 없는 칸(위험물·고른 스케줄 전 단계 등)은 이 화면에서 적어 둔 것을 남깁니다.
    // 견적명은 서류 작성 화면에서 적었으면 그대로 이어집니다. (SHARED_FIELDS)
    const merged = {
      ...(local || {}),
      ...shared,
      step: 1,
      schedule_id: null,
      transport_mode: shared.transport_mode || (local && local.transport_mode),
      sea_mode: shared.sea_mode || (local && local.sea_mode),
      departure_date: shared.departure_date || (local && local.departure_date) || null,
      origin: shared.origin || (local && local.origin) || null,
      destination: shared.destination || (local && local.destination) || null,
      incoterms: shared.incoterms || (local && local.incoterms) || "",
      fields: { ...((local && local.fields) || {}), ...shared.fields },
      cargo_lines: shared.cargo_lines || [],
    };
    try {
      draftStore.setItem(DRAFT_KEY, JSON.stringify(merged));
    } catch (error) {
      return;
    }
    // 여기서는 **저장만** 합니다. 알리고 채우는 것은 restoreDraft의 한 줄이
    // 맡습니다. 두 줄이 겹쳐 뜨면 어느 쪽을 눌러야 하는지 알 수 없습니다.
  }

  // 복원은 recalc·openStep까지 모두 선언된 뒤에 실행해야 합니다.
  adoptWorkDraft().finally(() => {
    restoreDraft();
    syncNotifyParty();
  });
})();
