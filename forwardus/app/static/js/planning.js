/* Shipment Planning: wizard (planning/new) and Reverse Schedule Planner (planning/index). */
(function () {
  "use strict";

  const { escapeHtml, postJson, getJson, formatNumber, toIsoDate } = window.Forwardus;

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
        transit_days: reverseForm.transit_days.value,
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

  const errorBox = document.querySelector("[data-form-error]");
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

  function renderCalendar() {
    const year = viewMonth.getFullYear();
    const month = viewMonth.getMonth();
    const firstWeekday = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const canGoBack = viewMonth > new Date(today.getFullYear(), today.getMonth(), 1);
    let cells = "";
    for (let i = 0; i < firstWeekday; i += 1) cells += "<span></span>";
    for (let day = 1; day <= daysInMonth; day += 1) {
      const date = new Date(year, month, day);
      const iso = toIsoDate(date);
      const disabled = date < today;
      const selected = state.departure_date === iso;
      cells += `<button type="button" data-date="${iso}" ${disabled ? "disabled" : ""}
        class="${selected ? "selected" : ""} ${date.getTime() === today.getTime() ? "today" : ""}">${day}</button>`;
    }
    calendarEl.innerHTML = `
      <div class="cal_head">
        <button type="button" data-cal-prev ${canGoBack ? "" : "disabled"} aria-label="이전 달">‹</button>
        <b>${year}년 ${month + 1}월</b>
        <button type="button" data-cal-next aria-label="다음 달">›</button>
      </div>
      <div class="cal_week">${["일", "월", "화", "수", "목", "금", "토"].map((d) => `<span>${d}</span>`).join("")}</div>
      <div class="cal_grid">${cells}</div>`;
  }

  calendarEl.addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target || target.disabled) return;
    if (target.hasAttribute("data-cal-prev")) viewMonth.setMonth(viewMonth.getMonth() - 1);
    else if (target.hasAttribute("data-cal-next")) viewMonth.setMonth(viewMonth.getMonth() + 1);
    else if (target.dataset.date) {
      state.departure_date = target.dataset.date;
      selectedDateEl.textContent = state.departure_date;
      invalidateSchedules();
    }
    renderCalendar();
  });
  renderCalendar();

  /* ----- Transport mode toggles ----- */
  function applyMode() {
    const isAir = state.transport_mode === "AIR";
    document.querySelectorAll("[data-sea-only]").forEach((el) => { el.hidden = isAir; });
    document.querySelectorAll("[data-kind-label]").forEach((el) => { el.textContent = isAir ? "공항" : "항구"; });
    document.querySelectorAll("[data-sea-only-term]").forEach((card) => {
      const input = card.querySelector("input");
      input.disabled = isAir;
      card.classList.toggle("disabled", isAir);
      if (isAir && input.checked) input.checked = false;
    });
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
  });
  bindToggle(form.querySelector("[data-toggle=sea_mode]"), (value) => {
    state.sea_mode = value;
    applyMode();
    invalidateSchedules();
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

    const search = debounce(async () => {
      list.innerHTML = `<li class="empty">검색 중…</li>`;
      list.hidden = false;
      items = await fetchItems(input.value.trim());
      if (!items.length) {
        list.innerHTML = `<li class="empty">검색 결과가 없습니다. 목록에 없으면 "직접 입력"을 사용하세요.</li>`;
        return;
      }
      let html = "";
      let group = null;
      items.forEach((item, index) => {
        if (options.groupBy) {
          const value = options.groupBy(item);
          if (value !== group) {
            group = value;
            const other = value === "기타 항구";
            html += `<li class="ac_group${other ? " ac_group_other" : ""}">${escapeHtml(value)}`
              + (other ? `<small>규모가 작거나 분류 정보가 없는 항구</small>` : "")
              + `</li>`;
          }
        }
        html += `<li role="option" data-index="${index}">${renderItem(item)}</li>`;
      });
      list.innerHTML = html;
    }, 200);

    input.addEventListener("input", () => { onSelect(null, input); search(); });
    input.addEventListener("focus", search);
    input.addEventListener("blur", () => setTimeout(() => { list.hidden = true; }, 150));
    list.addEventListener("mousedown", (event) => {
      const li = event.target.closest("li[data-index]");
      if (!li) return;
      onSelect(items[Number(li.dataset.index)], input);
      list.hidden = true;
    });
    return { search };
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

  async function refreshCountryOptions() {
    const countries = await loadCountries(state.transport_mode);
    // 한국 교역액 상위 국가를 맨 위 그룹으로 먼저 보여줍니다.
    const top = countries.filter((c) => c.trade_rank).sort((a, b) => a.trade_rank - b.trade_rank);
    const optionsHtml = (top.length
      ? `<optgroup label="주요 무역국">${top.map(countryOption).join("")}</optgroup>`
        + `<optgroup label="전체 국가 (가나다순)">${countries.map(countryOption).join("")}</optgroup>`
      : countries.map(countryOption).join(""));
    const filter = form.querySelector("[data-country-filter]");
    if (filter) {
      const current = filter.value;
      filter.innerHTML = `<option value="">국가 전체 (주요 항만 표시)</option>${optionsHtml}`;
      filter.value = current;
    }
    const customCountry = form.querySelector("[data-autocomplete=destination] [data-custom-country]");
    if (customCountry) customCountry.innerHTML = `<option value="">국가 선택</option>${optionsHtml}`;
  }

  function setupCustomInput(role) {
    const container = form.querySelector(`[data-autocomplete=${role}]`);
    const box = container.querySelector("[data-custom]");
    const input = container.querySelector("[data-ac-input]");

    container.querySelector("[data-custom-toggle]").addEventListener("click", () => {
      box.hidden = !box.hidden;
      if (!box.hidden) box.querySelector("[data-custom-code]").focus();
    });

    container.querySelector("[data-custom-apply]").addEventListener("click", () => {
      const code = box.querySelector("[data-custom-code]").value.trim().toUpperCase();
      const name = box.querySelector("[data-custom-name]").value.trim();
      const countrySelect = box.querySelector("[data-custom-country]");
      const countryCode = countrySelect ? countrySelect.value : "KR";
      if (!code || !name || !countryCode) {
        showError("직접 입력하려면 코드, 이름, 국가를 모두 채워주세요.");
        return;
      }
      showError("");
      state[role] = { code, name, country_code: countryCode, custom: true };
      input.value = `${name} (${code})`;
      box.hidden = true;
      invalidateSchedules();
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
        const response = await getJson(`${urls.locations}?${params}`);
        return response.success ? response.data : [];
      },
      (item) => {
        const size = { L: "대형항", M: "중형항", S: "소형항", V: "소규모" }[item.harbor_size] || "";
        return `<b>${escapeHtml(item.name)}</b> <span class="mono">${escapeHtml(item.code)}</span>`
          + `<small>${escapeHtml(item.name_en)} · ${escapeHtml(item.country)}${size ? ` · ${size}` : ""}</small>`;
      },
      (item, input) => {
        state[role] = item;
        if (item) input.value = `${item.name} (${item.code})`;
        invalidateSchedules();
      },
      {
        // 주요 수출입 항구를 먼저 보여주고, 나머지는 맨 아래 "기타 항구"로 모읍니다.
        groupBy: (item) => (item.major
          ? (role === "destination" ? item.country : "주요 항구")
          : "기타 항구"),
      },
    );
    setupCustomInput(role);
    if (countryFilter) {
      countryFilter.addEventListener("change", () => {
        container.querySelector("[data-ac-input]").focus();
        locationSearch[role].search();
      });
    }
  });
  refreshCountryOptions();

  setupAutocomplete(
    form.querySelector("[data-autocomplete=hs_code]"),
    async (q) => {
      const response = await getJson(`${urls.hsCodes}?${new URLSearchParams({ q })}`);
      return response.success ? response.data : [];
    },
    (item) => `<span class="mono">${escapeHtml(item.code)}</span> <b>${escapeHtml(item.name)}</b><small>${escapeHtml(item.name_en)} · Mock</small>`,
    (item, input) => { if (item) input.value = item.code; },
  );

  /* ----- Cargo calculation ----- */
  const calcMessage = document.querySelector("[data-calc-message]");

  function cargoPayload() {
    const f = form.elements;
    return {
      product_description: f.product_description.value,
      hs_code: f.hs_code.value,
      package_type: f.package_type.value,
      quantity: f.quantity.value,
      length_cm: f.length_cm.value,
      width_cm: f.width_cm.value,
      height_cm: f.height_cm.value,
      weight_per_package_kg: f.weight_per_package_kg.value,
      net_weight_kg: f.net_weight_kg.value,
    };
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
    const filled = ["quantity", "length_cm", "width_cm", "height_cm", "weight_per_package_kg"].every((k) => payload[k] !== "");
    if (!filled) {
      state.metrics = null;
      renderMetrics(null);
      calcMessage.textContent = "치수·수량·중량을 입력하면 계산됩니다.";
      return;
    }
    const response = await postJson(urls.cargo, payload);
    state.metrics = response.success ? response.data : null;
    renderMetrics(state.metrics);
    calcMessage.textContent = response.success ? "서버에서 계산된 값입니다." : response.message;
  }, 250);

  form.querySelectorAll("[data-calc]").forEach((input) => input.addEventListener("input", () => { recalc(); invalidateSchedules(); }));

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
              <div><small>ETD</small><b>${s.etd}</b></div>
              <div class="line"><span>${s.transit_days}일 · ${s.direct ? "Direct" : "Transshipment"}</span></div>
              <div><small>ETA</small><b>${s.eta}</b></div>
            </div>
            <div class="row_between wrap">
              <span class="muted small">정시율 ${s.reliability}% · ${escapeHtml(s.freight_basis)}</span>
              ${deadline}
            </div>
          </div>
          <div class="schedule_price"><small>Freight</small><b>USD ${formatNumber(s.freight_usd, 0)}</b></div>
        </label>`;
    }).join("");
  }

  scheduleList.addEventListener("change", (event) => {
    if (event.target.name === "schedule_id") {
      state.schedule_id = event.target.value;
      renderSchedules();
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
    scheduleMeta.textContent = `${state.origin.name} → ${state.destination.name} · ${state.departure_date} 이후 출발 · ${state.schedules.length}건`
      + (response.data.source === "mock" ? " · 실제 선사 API가 연결되지 않아 Mock 스케줄을 표시합니다." : "");
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
      if (!f.invoice_value.value) return "Invoice Value를 입력해주세요.";
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
      ["Invoice", f.invoice_value.value ? `${f.currency.value} ${formatNumber(Number(f.invoice_value.value), 2)}` : missing],
      ["Schedule", schedule ? `${schedule.carrier} ${schedule.vessel_or_flight} · ETD ${schedule.etd} → ETA ${schedule.eta}` : missing],
      ["Freight", schedule ? `USD ${formatNumber(schedule.freight_usd, 0)} (${schedule.source})` : missing],
    ];
    document.querySelector("[data-summary]").innerHTML = rows
      .map(([k, v]) => `<div><dt>${k}</dt><dd class="${v === missing ? "missing" : ""}">${escapeHtml(v)}</dd></div>`).join("");
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

  form.elements.buyer_required_date.addEventListener("change", invalidateSchedules);

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
        invoice_value: f.invoice_value.value,
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
      window.location.href = response.data.url;
    } else {
      handleServerError(response);
    }
  });
})();
