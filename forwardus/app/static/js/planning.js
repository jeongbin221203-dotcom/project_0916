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

  /* ----- 입력값 임시 저장: 다른 메뉴에 다녀와도 내용이 남습니다 ----- */
  const DRAFT_KEY = "forwardus:planning-draft";
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
      origin: state.origin,
      destination: state.destination,
      schedule_id: state.schedule_id,
      sort: state.sort,
      incoterms: incoterm ? incoterm.value : "",
      country: (form.querySelector("[data-country-filter]") || {}).value || "",
      fields,
    };
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    } catch (error) {
      /* 저장 공간이 없으면 그냥 넘어갑니다. */
    }
  }

  function clearDraft() {
    try {
      localStorage.removeItem(DRAFT_KEY);
    } catch (error) { /* 무시 */ }
  }

  function loadDraft() {
    try {
      return JSON.parse(localStorage.getItem(DRAFT_KEY) || "null");
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

  /* ----- Transport mode toggles ----- */
  function applyMode() {
    const isAir = state.transport_mode === "AIR";
    document.querySelectorAll("[data-air-only]").forEach((el) => { el.hidden = !isAir; });
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
    saveDraftSoon();
    updateSelectedDates();
    refreshOutlook();
  });
  bindToggle(form.querySelector("[data-toggle=sea_mode]"), (value) => {
    state.sea_mode = value;
    applyMode();
    invalidateSchedules();
    saveDraftSoon();
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
        list.innerHTML = `<li class="empty">검색 결과가 없습니다. 목록에 없으면 "직접 입력"을 사용하세요.</li>`;
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
          const other = value === "환승 필요";
          const GROUP_NOTES = {
            "환승 필요": "국내 공항발 직항편이 없어 환승이 필요합니다",
            "항공화물 거점 (직항)": "화물기 취항지 또는 화물 처리 거점입니다",
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
        const response = await getJson(`${urls.locations}?${params}`);
        return response.success ? response.data : [];
      },
      (item) => {
        const size = item.kind === "airport"
          ? ""
          : ({ L: "대형항", M: "중형항", S: "소형항", V: "소규모" }[item.harbor_size] || "");
        const note = item.note ? `<em class="ac_note">${escapeHtml(item.note)}</em>` : "";
        const direct = item.kind === "airport" && item.direct_from_korea
          ? `<em class="ac_note direct">직항</em>` : "";
        const cargo = item.korean_air_cargo
          ? `<em class="ac_note cargo">KE 화물</em>`
          : (item.cargo_hub ? `<em class="ac_note cargo">화물 거점</em>` : "");
        const viaLabel = item.gateway_only ? "국제선 없음 · 대체 공항" : "경유";
        const via = (item.transfer_via || []).length
          ? `<small class="ac_via">${viaLabel}: ${item.transfer_via
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
        invalidateSchedules();
        saveDraftSoon();
        updateSelectedDates();
        refreshOutlook();
      },
      {
        // 국내는 국가관리 -> 지방관리 순, 해외는 국가별로 묶고,
        // 규모가 작은 항구는 맨 아래 "기타 항구"로 모읍니다.
        groupBy: (item) => {
          if (state.transport_mode === "AIR" && role === "destination") {
            // 화물 노선이 있는 거점 -> 여객 직항 -> 환승 순으로 나눕니다.
            if (item.cargo_hub && item.direct_from_korea) return "항공화물 거점 (직항)";
            return item.direct_from_korea ? "여객 직항 노선" : "환승 필요";
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
    if (draft.departure_date) {
      state.departure_date = draft.departure_date;
      const [year, month] = draft.departure_date.split("-").map(Number);
      viewMonth = new Date(year, month - 1, 1);
    }
    updateSelectedDates();
    refreshOutlook();
    const filter = form.querySelector("[data-country-filter]");
    if (filter && draft.country) filter.value = draft.country;
    state.sort = draft.sort || state.sort;
    state.schedule_id = draft.schedule_id || null;

    recalc();
    if (draft.step && draft.step > 1) await openStep(draft.step);
  }

  updateSelectedDates();   // 임시저장이 없을 때도 날짜 표시를 채웁니다.
  restoreDraft();

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

  // 함수 선언으로 두어 초기화 순서와 관계없이 호출할 수 있게 합니다.
  let departureCheckTimer;

  const LEVEL_TEXT = {
    ok: "여유 있음",
    caution: "여유 적음",
    tight: "일정 촉박",
    late: "납기 초과",
    none: "Buyer 요청일을 입력하면 여유를 계산합니다",
  };

  async function refreshOutlook() {
    const box = document.querySelector("[data-outlook]");
    if (!box) return;
    if (!state.departure_date || !state.destination) {
      box.hidden = true;
      return;
    }
    const response = await postJson(urls.scheduleOutlook, {
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

    box.innerHTML = `<p class="outlook_head">${escapeHtml(state.origin ? state.origin.name : "출발지")}`
      + ` → ${escapeHtml(data.destination)} 예상 일정 <em>Data Source: Mock</em></p>`
      + data.modes.map((mode) => `
        <div class="outlook_row level_${mode.level}">
          <span class="outlook_mode">${icon[mode.mode]} ${escapeHtml(mode.label)}</span>
          <span class="outlook_days">${days(mode)}</span>
          <span class="outlook_eta">도착 ${mode.eta_fastest}${
            mode.eta_slowest !== mode.eta_fastest ? ` ~ ${mode.eta_slowest}` : ""}</span>
          <span class="outlook_margin">${escapeHtml(margin(mode))}</span>
          <span class="outlook_level">${escapeHtml(LEVEL_TEXT[mode.level] || "")}</span>
        </div>`).join("");
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
      clearDraft();
      window.location.href = response.data.url;
    } else {
      handleServerError(response);
    }
  });
})();
