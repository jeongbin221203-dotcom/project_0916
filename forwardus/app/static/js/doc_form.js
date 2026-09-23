/* 서류 작성 화면(/documents/new)의 서식 칸.
   일정 · 운송 · 서류 · 원산지증명서 네 갈래가 form 하나를 나눠 씁니다.
   한 곳에 적은 값이 다른 곳에서 그대로 쓰이게 하려는 것입니다. */
(function () {
  "use strict";

  const config = window.FORWARDUS_DOC;
  const panel = document.querySelector("[data-doc-panel]");
  if (!config || !panel) return;

  const { escapeHtml, getJson, postJson } = window.Forwardus;

  const form = panel.querySelector("[data-doc-form]");
  const itemsBox = panel.querySelector("[data-doc-items]");
  const itemTemplate = document.querySelector("[data-doc-item-template]");
  const doneEl = panel.querySelector("[data-doc-done]");
  const errorEl = panel.querySelector("[data-doc-error]");
  const resultEl = panel.querySelector("[data-doc-result]");
  const scheduleBox = panel.querySelector("[data-doc-schedules]");

  let chosenSchedule = "";
  let madeShipment = "";

  /* ----- 차례대로 내려가며 채웁니다 -----
     네 갈래를 한 줄로 이어 놓고, 왼쪽 작은 사이드바가 지금 자리를 따라다닙니다.
     누르면 그 자리로 부드럽게 내려가고, 스크롤하면 표시가 저절로 옮겨 갑니다. */
  const sections = Array.from(panel.querySelectorAll("[data-doc-section]"));
  const railItems = Array.from(panel.querySelectorAll("[data-doc-nav]"));
  let originOpened = false;

  function markRail(key) {
    railItems.forEach((item) => {
      const on = item.dataset.docNav === key;
      item.classList.toggle("active", on);
      if (on) item.setAttribute("aria-current", "true");
      else item.removeAttribute("aria-current");
    });
  }

  function goToSection(key) {
    const section = panel.querySelector(`[data-doc-section="${key}"]`);
    if (!section) return;
    if (key === "origin") openOriginOnce();
    markRail(key);
    // 위쪽 고정 머리말에 가리지 않도록 조금 띄워 멈춥니다.
    const top = section.getBoundingClientRect().top + window.scrollY - 84;
    window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
  }

  function openOriginOnce() {
    if (originOpened) return;
    originOpened = true;
    openOrigin();
  }

  railItems.forEach((item) => {
    item.addEventListener("click", (event) => {
      event.preventDefault();
      goToSection(item.dataset.docNav);
    });
  });

  // 지금 보고 있는 갈래를 사이드바에 표시합니다. 화면 위쪽 기준선을 지난 마지막 갈래가 "지금"입니다.
  // 맨 아래까지 내리면 마지막 갈래(원산지증명서)로 둡니다. 마지막 칸이 짧아 기준선에 닿지 않기 때문입니다.
  if (sections.length) {
    markRail("when");
    let spyQueued = false;
    const updateSpy = () => {
      spyQueued = false;
      // 갈래의 머리말이 기준선(위에서 120px)을 지난 것 중 마지막이 "지금 쓰는 곳"입니다.
      const doc = document.documentElement;
      // 더 내려갈 곳이 없으면 마지막 갈래입니다. 마지막 칸은 짧아서 기준선까지 올라오지 못합니다.
      // (문서 전체 높이로 봅니다. body 높이로 재면 중간인데도 끝으로 잘못 봅니다)
      const atBottom = Math.ceil(window.scrollY + window.innerHeight) >= doc.scrollHeight - 2;
      let current = atBottom ? sections[sections.length - 1] : sections[0];
      if (!atBottom) sections.forEach((section) => {
        if (section.getBoundingClientRect().top <= 120) current = section;
      });
      const key = current.dataset.docSection;
      markRail(key);
      if (key === "origin") openOriginOnce();
    };
    // 스크롤이 움직이는 동안 매 프레임 한 번만 다시 잽니다. (타이머로 미루면 표시가 늦게 따라옵니다)
    const queueSpy = () => {
      if (spyQueued) return;
      spyQueued = true;
      requestAnimationFrame(updateSpy);
    };
    window.addEventListener("scroll", queueSpy, { passive: true });
    window.addEventListener("resize", queueSpy);
  }

  /* ----- 고르는 칸 (해상/항공, FCL/LCL) ----- */
  panel.querySelectorAll("[data-doc-choice]").forEach((group) => {
    const hidden = group.querySelector("input");
    group.addEventListener("click", (event) => {
      const button = event.target.closest("button");
      if (!button) return;
      group.querySelectorAll("button").forEach((other) =>
        other.classList.toggle("active", other === button));
      hidden.value = button.dataset.value;
      if (group.dataset.docChoice === "transport_mode") applyMode(hidden.value);
      invalidateSchedule();
      score();
    });
  });

  // 항공에는 FCL/LCL이 없습니다. 고를 수 있게 두면 틀린 값이 들어갑니다.
  function applyMode(mode) {
    panel.querySelectorAll("[data-sea-only]").forEach((el) => { el.hidden = mode !== "SEA"; });
    panel.querySelectorAll("[data-doc-place]").forEach((box) => {
      box.querySelector("[data-place-search]").value = "";
      box.querySelector("[data-doc-input]").value = "";
    });
  }

  /* ----- 출발지·도착지 찾기 ----- */
  function debounce(fn, wait) {
    let timer;
    return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); };
  }

  panel.querySelectorAll("[data-doc-place]").forEach((box) => {
    const role = box.dataset.docPlace;
    const search = box.querySelector("[data-place-search]");
    const hidden = box.querySelector("[data-doc-input]");
    const list = box.querySelector("[data-place-list]");
    const more = box.querySelector("[data-place-more]");

    function showRows(rows, emptyText) {
      list.innerHTML = rows.length
        ? rows.map((row) => `<li><button type="button" data-code="${escapeHtml(row.code)}"`
            + ` data-name="${escapeHtml(row.name)}"${row.code === hidden.value ? ' class="picked"' : ""}>`
            + `${escapeHtml(row.name)}`
            + ` <small>${escapeHtml(row.code)} · ${escapeHtml(row.country)}</small></button></li>`).join("")
        : `<li class="empty">${escapeHtml(emptyText)}</li>`;
      list.hidden = false;
      if (more) more.setAttribute("aria-expanded", "true");
    }

    function hideList() {
      list.hidden = true;
      if (more) more.setAttribute("aria-expanded", "false");
    }

    const look = debounce(async () => {
      const query = search.value.trim();
      if (!query) { hideList(); return; }
      const mode = form.elements.transport_mode ? form.elements.transport_mode.value : "SEA";
      const params = new URLSearchParams({ q: query, mode, role });
      const response = await getJson(`${config.locationsUrl}?${params}`);
      showRows(response.success ? response.data.slice(0, 8) : [], "찾지 못했습니다. 다른 이름으로 적어 보세요.");
    }, 250);

    // ▼ 고른 곳과 같은 나라의 항구·공항을 관련도 순서로 펼칩니다. (고른 것이 맨 위)
    if (more) {
      more.addEventListener("click", async () => {
        if (!list.hidden) { hideList(); return; }
        const mode = form.elements.transport_mode ? form.elements.transport_mode.value : "SEA";
        const params = new URLSearchParams({ mode, role });
        if (hidden.value) params.set("near", hidden.value);
        else params.set("q", search.value.trim());
        list.innerHTML = `<li class="empty">찾는 중입니다…</li>`;
        list.hidden = false;
        const response = await getJson(`${config.locationsUrl}?${params}`);
        showRows(response.success ? response.data.slice(0, 12) : [],
                 "고를 수 있는 곳을 찾지 못했습니다. 이름으로 적어 보세요.");
      });
    }

    search.addEventListener("input", () => { hidden.value = ""; invalidateSchedule(); look(); });
    list.addEventListener("mousedown", (event) => {
      const button = event.target.closest("button[data-code]");
      if (!button) return;
      event.preventDefault();
      hidden.value = button.dataset.code;
      search.value = `${button.dataset.name} (${button.dataset.code})`;
      hideList();
      invalidateSchedule();
      findSchedulesSoon();
      score();
    });
    // ▼로 펼친 목록은 칸 밖을 눌렀을 때만 닫습니다. (칸을 떠나도 목록은 볼 수 있어야 합니다)
    search.addEventListener("blur", () => setTimeout(() => {
      if (!box.contains(document.activeElement)) hideList();
    }, 150));
    document.addEventListener("click", (event) => {
      if (!box.contains(event.target)) hideList();
    });
  });

  /* ----- 일정 달력 -----
     누를 때마다 Seller 발송 예상일 → Buyer 요청 도착일 순서로 잡힙니다. */
  const calBox = panel.querySelector("[data-cal]");
  const departEl = form.elements.requested_departure_date;
  const arriveEl = form.elements.buyer_required_date;
  let viewMonth = new Date();
  viewMonth.setDate(1);

  const iso = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`
    + `-${String(date.getDate()).padStart(2, "0")}`;

  function monthHtml(offset) {
    const base = new Date(viewMonth.getFullYear(), viewMonth.getMonth() + offset, 1);
    const today = iso(new Date());
    const days = new Date(base.getFullYear(), base.getMonth() + 1, 0).getDate();
    let cells = "";
    for (let blank = 0; blank < base.getDay(); blank += 1) cells += "<span></span>";
    for (let day = 1; day <= days; day += 1) {
      const value = iso(new Date(base.getFullYear(), base.getMonth(), day));
      const marks = [
        value < today ? "past" : "",
        value === departEl.value ? "seller" : "",
        value === arriveEl.value ? "buyer" : "",
        (departEl.value && arriveEl.value && value > departEl.value && value < arriveEl.value)
          ? "between" : "",
      ].filter(Boolean).join(" ");
      cells += value < today
        ? `<span class="cal_day past">${day}</span>`
        : `<button type="button" class="cal_day ${marks}" data-day="${value}">${day}</button>`;
    }
    return `<div class="cal_month"><b>${base.getFullYear()}년 ${base.getMonth() + 1}월</b>`
      + `<div class="cal_week">${["일", "월", "화", "수", "목", "금", "토"]
        .map((name) => `<span>${name}</span>`).join("")}</div>`
      + `<div class="cal_days">${cells}</div></div>`;
  }

  function drawCalendar() {
    if (!calBox) return;
    calBox.innerHTML = `<div class="cal_head">
        <button type="button" class="cal_nav" data-cal-move="-1" aria-label="이전 달">‹</button>
        <b>일정 선택</b>
        <button type="button" class="cal_nav" data-cal-move="1" aria-label="다음 달">›</button>
      </div><div class="cal_months">${monthHtml(0)}${monthHtml(1)}</div>`;
    panel.querySelector("[data-cal-seller]").textContent = departEl.value || "미선택";
    panel.querySelector("[data-cal-buyer]").textContent = arriveEl.value || "미선택";
  }

  calBox?.addEventListener("click", (event) => {
    const move = event.target.closest("[data-cal-move]");
    if (move) {
      viewMonth = new Date(viewMonth.getFullYear(),
        viewMonth.getMonth() + Number(move.dataset.calMove), 1);
      drawCalendar();
      return;
    }
    const day = event.target.closest("[data-day]");
    if (!day) return;
    const value = day.dataset.day;
    // 보내는 날이 먼저입니다. 다시 고르면 도착 요청일은 지웁니다.
    if (!departEl.value || value <= departEl.value || arriveEl.value) {
      departEl.value = value;
      arriveEl.value = "";
    } else {
      arriveEl.value = value;
    }
    invalidateSchedule();
    drawCalendar();
    score();
  });

  [departEl, arriveEl].forEach((el) => el.addEventListener("change", () => {
    invalidateSchedule();
    drawCalendar();
  }));

  /* ----- 금액 칸의 통화 표기 -----
     "금액" 대신 "금액 (USD)"처럼 지금 고른 통화를 라벨·자리표시·총액에 붙입니다.
     통화 칸을 바꾸거나, 올린 서류에서 통화를 읽어 오면 곧바로 따라 바뀝니다. */
  const totalBox = panel.querySelector("[data-doc-total]");
  function currencyCode() {
    return ((form.elements.currency && form.elements.currency.value) || "").trim().toUpperCase();
  }
  function moneyNumber(text) {
    const value = Number(String(text || "").replace(/,/g, "").trim());
    return Number.isFinite(value) ? value : null;
  }
  function applyCurrency() {
    const code = currencyCode();
    panel.querySelectorAll("[data-money-unit]").forEach((el) => { el.textContent = code ? ` (${code})` : ""; });
    panel.querySelectorAll("[data-money-input]").forEach((input) => {
      input.placeholder = [code, input.dataset.moneyExample].filter(Boolean).join(" ");
    });
    if (!totalBox) return;
    const amounts = Array.from(itemsBox.querySelectorAll('[name="item_amount"]'))
      .map((input) => moneyNumber(input.value)).filter((value) => value !== null && value > 0);
    totalBox.hidden = !amounts.length;
    const total = amounts.reduce((sum, value) => sum + value, 0);
    totalBox.querySelector("[data-doc-total-value]").textContent =
      total.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  if (form.elements.currency) form.elements.currency.addEventListener("change", applyCurrency);
  itemsBox.addEventListener("input", (event) => {
    if (event.target.name === "item_amount") applyCurrency();
  });

  /* ----- 품목 ----- */
  function addItem() {
    const row = itemTemplate.content.cloneNode(true).querySelector(".doc_item");
    itemsBox.appendChild(row);
    renumber();
    addHsButton(row);
    row.addEventListener("input", () => { invalidateSchedule(); score(); });
    row.addEventListener("change", score);
    applyCurrency();
    return row;
  }

  /* ----- 품목의 HS부호를 간편 검색 창으로 찾기 -----
     이 줄의 품명으로 바로 찾고, 고르면 이 줄의 HS부호 칸에 넣습니다.
     도착지를 골라 두었으면 그 나라 관세로 비교합니다. */
  function destinationCountry() {
    const port = (form.elements.destination_code?.value || "").trim();
    return port.slice(0, 2) || (form.elements.buyer_country?.value || "").trim();
  }

  function addHsButton(row) {
    const field = row.querySelector('[data-doc-field="hs_code"]');
    if (!field || !window.ForwardusHsModal) return;
    const hsInput = field.querySelector("[data-doc-input]");
    const hint = document.createElement("small");
    hint.className = "doc_hint";
    hint.hidden = true;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "link_button doc_hs_find";
    button.textContent = "🔎 HS CODE 간편 검색";
    field.append(button, hint);

    button.addEventListener("click", (event) => {
      event.preventDefault();   // label 안에 있어 칸으로 초점이 튀지 않게 합니다.
      const name = row.querySelector('[name="item_product_description"]')?.value.trim() || "";
      const no = row.querySelector("[data-item-no]").textContent;
      window.ForwardusHsModal.open({
        query: hsInput.value.trim().length === 10 ? hsInput.value.trim() : name,
        country: destinationCountry(),
        target: {
          label: `품목 ${no} HS부호 칸`,
          apply(code, item, { warning }) {
            hsInput.value = code;
            hsInput.dispatchEvent(new Event("input", { bubbles: true }));
            hsInput.classList.add("is_prefilled");
            hint.textContent = warning || `${item.name || item.name_en || ""} · 간편 검색에서 골랐습니다.`;
            hint.hidden = false;
            hsInput.focus();
          },
        },
      });
    });
  }

  function renumber() {
    itemsBox.querySelectorAll(".doc_item").forEach((row, index) => {
      row.querySelector("[data-item-no]").textContent = String(index + 1);
      // 품목이 하나뿐이면 지울 수 없게 둡니다. 서류에는 품목이 있어야 합니다.
      row.querySelector("[data-doc-remove-item]").hidden = itemsBox.children.length < 2;
    });
  }

  itemsBox.addEventListener("click", (event) => {
    if (!event.target.closest("[data-doc-remove-item]")) return;
    event.target.closest(".doc_item").remove();
    renumber();
    invalidateSchedule();
    score();
  });
  panel.querySelector("[data-doc-add-item]").addEventListener("click", () => addItem());

  function itemValues() {
    return Array.from(itemsBox.querySelectorAll(".doc_item")).map((row) => {
      const item = {};
      row.querySelectorAll("[data-doc-input]").forEach((input) => {
        item[input.name.replace(/^item_/, "")] = input.value.trim();
      });
      return item;
    });
  }

  /* ----- 운송 계획으로 이어 쓰기 -----
     여기서 적은 값(송하인·수하인·POL/POD·품목·중량·치수·Incoterms·통화·금액)을
     "작성 중인 수출 건"으로 저장합니다. 운송 계획 화면이 열리면 이 값으로 칸이 미리 찹니다.
     (work_draft.js · /api/work-draft. 바이어 주소·연락처는 이 탭에만 둡니다) */
  function sharedValues() {
    const fields = {};
    form.querySelectorAll("[data-doc-input]").forEach((input) => {
      if (input.closest("template") || input.name.startsWith("item_") || !input.name) return;
      fields[input.name] = input.value.trim();
    });
    ["origin", "destination"].forEach((role) => {
      const search = panel.querySelector(`[data-doc-place="${role}"] [data-place-search]`);
      if (search && search.value.trim()) fields[`${role}_name`] = search.value.trim();
    });
    return { fields, items: itemValues() };
  }
  function syncWorkDraft(source = "document") {
    if (window.ForwardusWorkDraft) window.ForwardusWorkDraft.save(sharedValues(), source);
  }
  form.addEventListener("input", () => syncWorkDraft());
  form.addEventListener("change", () => syncWorkDraft());

  /* ----- 얼마나 찼는지 ----- */
  function score() {
    let done = 0;
    panel.querySelectorAll(".doc_field").forEach((field) => {
      if (field.closest(".doc_item") || field.closest("template")) return;
      if (!field.querySelector(".doc_must") || field.hidden) return;
      const input = field.querySelector("[data-doc-input]");
      if (input && input.value.trim()) done += 1;
    });
    const firstItem = itemsBox.querySelector(".doc_item");
    if (firstItem) {
      done += Array.from(firstItem.querySelectorAll(".doc_field"))
        .filter((field) => field.querySelector(".doc_must"))
        .filter((field) => field.querySelector("[data-doc-input]").value.trim()).length;
    }
    if (chosenSchedule) done += 1;
    doneEl.textContent = String(done);
  }
  form.addEventListener("input", score);
  form.addEventListener("change", score);

  /* ----- 스케줄 ----- */
  // 항로나 화물, 날짜가 바뀌면 앞서 고른 스케줄은 더 이상 그 건의 것이 아닙니다.
  function invalidateSchedule() {
    if (!chosenSchedule) return;
    chosenSchedule = "";
    scheduleBox.innerHTML = `<p class="muted small">내용이 바뀌었습니다. 스케줄을 다시 찾는 중입니다…</p>`;
    findSchedulesSoon();
  }

  // 날짜·출발지·도착지가 모두 차면 저절로 찾습니다. 화물 치수는 없어도 일정은 나옵니다.
  function routeReady() {
    const f = form.elements;
    return Boolean(f.requested_departure_date && f.requested_departure_date.value
      && f.origin_code && f.origin_code.value && f.destination_code && f.destination_code.value);
  }

  const findSchedulesSoon = debounce(() => { if (routeReady() && !chosenSchedule) findSchedules(); }, 400);

  async function findSchedules() {
    // 스케줄 조회는 운송 계획 화면과 같은 창구를 씁니다. 그쪽은 품목을
    // cargo.items로 받고 견적명을 요구합니다. 견적명은 조회에 쓰이지 않고,
    // 저장되는 이름은 서버가 도착지와 품명으로 따로 짓습니다.
    const payload = {
      ...planPayload(), project_name: "스케줄 조회", cargo: { items: itemValues() },
    };
    scheduleBox.innerHTML = `<p class="muted small">찾는 중입니다…</p>`;
    const response = await postJson(config.schedulesUrl, payload);
    if (!response.success) {
      scheduleBox.innerHTML = `<p class="doc_error_line">${escapeHtml(response.message)}</p>`;
      return;
    }
    const items = response.data.items.slice(0, 5);
    if (!items.length) {
      scheduleBox.innerHTML = `<p class="muted small">이 항로에 맞는 스케줄을 찾지 못했습니다.</p>`;
      return;
    }
    scheduleBox.innerHTML = items.map((item) => `
      <label class="doc_schedule">
        <span class="doc_schedule_info">
          <b>${escapeHtml(item.carrier || "-")}${item.vessel ? " · " + escapeHtml(item.vessel) : ""}</b>
          <span>ETD ${escapeHtml(item.etd)} → ETA ${escapeHtml(item.eta)} · ${item.transit_days}일</span>
          <small class="muted">${item.source === "api" ? "실제 스케줄" : "예시 스케줄 (API 키가 없어 추정치입니다)"}</small>
        </span>
        <input type="radio" name="schedule_pick" value="${escapeHtml(item.schedule_id)}">
      </label>`).join("");
    scheduleBox.querySelectorAll("input[name=schedule_pick]").forEach((radio) => {
      radio.addEventListener("change", () => { chosenSchedule = radio.value; score(); });
    });
  }

  panel.querySelector("[data-doc-find-schedule]").addEventListener("click", findSchedules);
  form.addEventListener("change", findSchedulesSoon);

  /* ----- 원산지증명서 ----- */
  const originEmpty = panel.querySelector("[data-origin-empty]");
  const originBody = panel.querySelector("[data-origin-body]");
  const originPick = panel.querySelector("[data-origin-pick]");

  panel.querySelector("[data-origin-goto-doc]")?.addEventListener("click", () => {
    goToSection("doc");
  });
  originPick?.addEventListener("change", () => {
    if (originPick.value) loadOrigin(originPick.value);
  });

  function openOrigin() {
    // 방금 만든 건이 있으면 그것부터 보여 줍니다.
    if (madeShipment) loadOrigin(madeShipment);
  }

  async function loadOrigin(shipmentId) {
    originEmpty.hidden = true;
    originBody.hidden = false;
    originBody.innerHTML = `<p class="muted small">불러오는 중입니다…</p>`;
    const response = await getJson(config.originUrl.replace("__ID__", shipmentId));
    if (!response.success) {
      originBody.innerHTML = `<p class="doc_error_line">${escapeHtml(response.message)}</p>`;
      return;
    }
    originBody.innerHTML = originHtml(response.data);
  }

  function originHtml(data) {
    const links = (data.apply_links || []).map((row) =>
      `<a class="button small" href="${escapeHtml(row.url)}" target="_blank" rel="noopener">`
      + `${escapeHtml(row.label)} ↗</a>`).join("");

    const agreements = data.available && data.agreements.length
      ? `<div class="origin_list">${data.agreements.map((row) => `
          <div class="origin_row">
            <b>${escapeHtml(row.agreement)}</b>
            <span class="origin_rate">${escapeHtml(row.rate || "-")}</span>
            <small class="muted">${escapeHtml((row.certificate && row.certificate.how) || row.about || "")}</small>
          </div>`).join("")}</div>`
      : `<p class="doc_note">${escapeHtml(data.reason || "적용할 협정을 찾지 못했습니다.")}</p>`;

    const uploads = (data.uploads || []).length
      ? `<div class="origin_list">${data.uploads.map((row) => `
          <div class="origin_row">
            <b>${escapeHtml(row.filename)}</b>
            <span class="origin_rate">${escapeHtml(row.status_label)}</span>
            <small class="muted">${escapeHtml(row.agreement)} ${escapeHtml(row.summary)}</small>
          </div>`).join("")}</div>`
      : `<p class="muted small">아직 등록한 증명서가 없습니다.</p>`;

    return `
      <section class="doc_group">
        <h3><span aria-hidden="true">🏅</span> ${escapeHtml(data.shipment_id)}에 쓸 수 있는 협정</h3>
        <p class="doc_note">${escapeHtml(data.note || "")}</p>
        ${agreements}
      </section>
      <section class="doc_group">
        <h3><span aria-hidden="true">🏛</span> 신청 창구</h3>
        <p class="doc_note">기관발급은 세관 또는 상공회의소에서 받습니다.</p>
        <div class="origin_links">${links}</div>
      </section>
      <section class="doc_group">
        <h3><span aria-hidden="true">📎</span> 발급받은 증명서 등록</h3>
        <p class="doc_note">올리면 이 건의 품명·HS부호·수출자와 맞는지 대조합니다.</p>
        ${uploads}
        <form class="origin_upload" method="post" enctype="multipart/form-data"
              action="${escapeHtml(data.upload_url)}">
          <input type="hidden" name="requirement_key" value="origin">
          <input class="text_input" type="text" name="agreement" maxlength="120"
                 placeholder="어느 협정으로 받았나요 (예: 한·EU FTA)">
          <input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg,.txt,.docx" required>
          <button class="button primary" type="submit">등록하고 확인</button>
        </form>
      </section>`;
  }

  /* ----- 보내기 ----- */
  function planPayload() {
    const payload = { items: itemValues(), schedule_id: chosenSchedule };
    form.querySelectorAll("[data-doc-input]").forEach((input) => {
      if (input.closest(".doc_item") || input.closest("template")) return;
      payload[input.name] = input.value.trim();
    });
    return payload;
  }

  /* ----- 못 채운 칸 알려 주기 -----
     서버가 "무엇이 비었는지"(field)를 함께 돌려줍니다. 그 칸을 빨갛게 칠하고 그 자리로 올라갑니다.
     칸을 채우기 시작하면 표시는 곧바로 지웁니다. */
  function clearInvalid() {
    panel.querySelectorAll(".is_invalid").forEach((el) => el.classList.remove("is_invalid"));
  }

  // 서버가 쓰는 이름과 화면의 칸을 잇습니다. 화면에 같은 이름의 칸이 없는 것만 적습니다.
  const FIELD_FALLBACK = {
    items: "[data-doc-items]", amount: "[data-doc-items]",
    schedule_id: "[data-doc-schedules]", payload: "[data-doc-items]",
  };

  function fieldBox(field) {
    if (!field) return null;
    const input = form.querySelector(`[name="${field}"]:not([type=hidden])`)
      || form.querySelector(`[name="${field}"]`);
    if (input) {
      return input.closest(".doc_field, .doc_place, .doc_group, .doc_item") || input;
    }
    const spot = panel.querySelector(`[data-doc-field="${field}"]`)
      || (FIELD_FALLBACK[field] && panel.querySelector(FIELD_FALLBACK[field]));
    return spot ? (spot.closest(".doc_group") || spot) : null;
  }

  // 아직 비어 있는 필수 칸을 모두 빨갛게 칠합니다. 한 번에 어디를 채워야 하는지 보입니다.
  function markEmptyRequired() {
    let first = null;
    form.querySelectorAll(".doc_field").forEach((box) => {
      if (!box.querySelector(".doc_must")) return;
      const input = box.querySelector("[data-doc-input]");
      if (!input || input.value.trim()) return;
      box.classList.add("is_invalid");
      if (!first) first = box;
    });
    return first;
  }

  function showError(message, field) {
    clearInvalid();
    errorEl.textContent = message;
    errorEl.hidden = !message;
    if (!message) return;
    const target = fieldBox(field) || markEmptyRequired();
    if (target) {
      target.classList.add("is_invalid");
      markEmptyRequired();
      const top = target.getBoundingClientRect().top + window.scrollY - 140;
      window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
      const input = target.matches("input, select, textarea")
        ? target : target.querySelector("input, select, textarea, button");
      if (input) setTimeout(() => input.focus({ preventScroll: true }), 350);
    } else {
      errorEl.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  // 다시 적기 시작하면 빨간 표시를 지웁니다. 고친 칸이 계속 빨갛게 남으면 헷갈립니다.
  form.addEventListener("input", (event) => {
    const box = event.target.closest(".is_invalid");
    if (box) box.classList.remove("is_invalid");
    if (!form.querySelector(".is_invalid")) { errorEl.hidden = true; }
  });
  form.addEventListener("change", (event) => {
    const box = event.target.closest(".is_invalid");
    if (box) box.classList.remove("is_invalid");
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const button = panel.querySelector("[data-doc-submit]");
    button.disabled = true;
    button.textContent = "만드는 중입니다…";

    const response = await postJson(config.startUrl, planPayload(), 60000);
    button.disabled = false;
    button.textContent = "서류 만들기";

    if (!response.success) {
      showError(response.message, response.field);
      return;
    }
    madeShipment = response.data.shipment_id;
    showResult(response.data);
  });

  function showResult(data) {
    // 만들고 나서도 비어 있는 칸은 숨기지 않습니다. 서류에 —로 남을 자리입니다.
    const empty = data.still_empty.length
      ? `<div class="doc_empty"><b>아직 비어 있는 칸 ${data.still_empty.length}개</b>
           <p class="muted small">서류에 —로 남습니다. 아래 "서류 보고 고치기"에서 채울 수 있습니다.</p>
           <ul>${data.still_empty.map((row) =>
             `<li>${escapeHtml(row.doc)} · ${escapeHtml(row.label)}</li>`).join("")}</ul></div>`
      : `<p class="doc_all_set">서식의 칸이 모두 찼습니다.</p>`;
    resultEl.innerHTML = `
      <h3>${escapeHtml(data.shipment_id)} 서류를 만들었습니다</h3>
      <p class="muted">${escapeHtml(data.project_name)} · ETD ${escapeHtml(data.etd)}
        → ETA ${escapeHtml(data.eta)} · 송장 금액 ${escapeHtml(String(data.invoice_value))}
        ${escapeHtml(data.currency)}</p>
      ${empty}
      <div class="doc_after">
        <a class="button primary" href="${escapeHtml(data.url)}">서류 보고 고치기 →</a>
        <button type="button" class="button" data-go-origin>원산지증명서 보기</button>
      </div>`;
    resultEl.hidden = false;
    resultEl.querySelector("[data-go-origin]").addEventListener("click", () => {
      goToSection("origin");
    });
    resultEl.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // 읽어 온 값으로 채운 칸은 표시해 둡니다. 사람이 고치면 표시를 지웁니다.
  // 조용히 채우면 맞는지 보지 않고 넘어갑니다.
  function markPrefilled(input) {
    input.classList.add("is_prefilled");
    input.addEventListener("input", () => input.classList.remove("is_prefilled"), { once: true });
  }

  /* ----- 대화창에서 읽어 준 값으로 칸 채우기 ----- */
  // 사람이 적은 글을 AI가 읽어 준 것입니다. 칸에 넣기만 하고 만들지는
  // 않습니다. 맞는지 보고 누르는 것은 사람이 합니다.
  window.FORWARDUS_DOC_FILL = function fill(draft) {
    const fields = draft.fields || {};

    Object.entries(fields).forEach(([name, value]) => {
      if (name.endsWith("_name") && form.elements[`${name.replace("_name", "_code")}`]) return;
      const input = form.elements[name];
      if (!input || !value) return;
      if (input.type === "hidden" && input.closest("[data-doc-choice]")) {
        // 이미 그 값이면 누르지 않습니다. 운송 모드를 다시 누르면 적어 둔 출발·도착지가 지워집니다.
        if (input.value === value) return;
        // 고르는 칸은 단추를 눌러 줘야 표시도 같이 바뀝니다.
        const button = input.closest("[data-doc-choice]")
          .querySelector(`button[data-value="${value}"]`);
        if (button) button.click();
        return;
      }
      input.value = value;
      markPrefilled(input);
    });

    // 항구는 코드가 값이고 보이는 칸은 따로입니다.
    ["origin", "destination"].forEach((role) => {
      const shown = fields[`${role}_name`];
      if (shown) {
        const search = panel.querySelector(`[data-doc-place="${role}"] [data-place-search]`);
        search.value = shown;
        markPrefilled(search);
      }
    });

    // 품목은 읽어 온 개수만큼 줄을 다시 만듭니다.
    const items = draft.items || [];
    if (items.length) {
      itemsBox.innerHTML = "";
      items.forEach((item) => {
        const row = addItem();
        row.querySelectorAll("[data-doc-input]").forEach((input) => {
          const key = input.name.replace(/^item_/, "");
          if (item[key]) { input.value = item[key]; markPrefilled(input); }
        });
      });
    }

    invalidateSchedule();
    drawCalendar();
    score();
    applyCurrency();          // 읽어 온 통화가 금액 라벨에 바로 붙습니다.
    syncWorkDraft("upload");  // 올린 서류·대화에서 읽은 값도 운송 계획으로 이어집니다.
  };

  addItem();
  applyMode("SEA");
  drawCalendar();
  markRail("when");
  score();

  /* ----- B/L·Offer Sheet 올려서 칸 채우기 ----- */
  const uploadZone = document.querySelector("[data-doc-upload]");
  const uploadResult = document.querySelector("[data-doc-upload-result]");
  if (uploadZone && window.ForwardusDocUpload && config.extractUrl) {
    window.ForwardusDocUpload.mount(uploadZone, {
      url: config.extractUrl,
      onStart() { uploadResult.hidden = true; },
      onResult(data) {
        // 이 화면에서 바로 채웁니다. 만들기는 여전히 사람이 누릅니다.
        window.FORWARDUS_DOC_FILL(data.form);
        if (window.ForwardusHsModal) window.ForwardusHsModal.remember(data.hs_queries || []);
        uploadResult.innerHTML = window.ForwardusDocUpload.resultHtml(data)
          + `<p class="muted small">노란 칸이 서류에서 읽어 온 값입니다. 맞는지 보고 고친 뒤
             <b>서류 만들기</b>를 눌러 주세요.</p>`;
        uploadResult.hidden = false;
        uploadResult.scrollIntoView({ behavior: "smooth", block: "start" });
      },
    });
  }

  // 시작 화면에서 "적은 내용으로 칸 채우기"를 누르고 넘어온 경우.
  // 한 번만 집어 가고 지웁니다. 새로고침 때마다 되살아나면 방금 고친 값을 덮습니다.
  try {
    const stashed = window.sessionStorage.getItem("forwardus:doc-draft");
    if (stashed) {
      window.sessionStorage.removeItem("forwardus:doc-draft");
      window.FORWARDUS_DOC_FILL(JSON.parse(stashed));
    }
  } catch (error) {
    /* 저장 공간이 없거나 내용이 깨졌으면 빈 칸으로 시작합니다. */
  }
})();
