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
  // 대화창 검토 창에서 견적명을 붙여 저장해 둔 초안. 여기서 서류를 만들면
  // 그 초안이 이 Shipment로 승격됩니다. (document_draft_service.promote)
  let carriedDraftId = null;

  /* ----- 차례대로 내려가며 채웁니다 -----
     네 갈래를 한 줄로 이어 놓고, 왼쪽 작은 사이드바가 지금 자리를 따라다닙니다.
     누르면 그 자리로 부드럽게 내려가고, 스크롤하면 표시가 저절로 옮겨 갑니다. */
  const sections = Array.from(panel.querySelectorAll("[data-doc-section]"));
  const railItems = Array.from(panel.querySelectorAll("[data-doc-nav]"));
  let originOpened = false;

  // 지금 보고 있는 갈래. 임시저장에 함께 남겨, 다시 들어오면 그 자리로 돌아갑니다.
  let currentTab = "when";

  function markRail(key) {
    currentTab = key;
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
      placeCountry[box.dataset.docPlace] = "";
    });
  }

  /* ----- 출발지·도착지 찾기 ----- */
  function debounce(fn, wait) {
    let timer;
    return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); };
  }

  // 고른 항구의 나라 이름. 견적명(도착국가_품목_날짜)에 씁니다.
  const placeCountry = { origin: "", destination: "" };

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

    search.addEventListener("input", () => {
      hidden.value = "";
      if (role === "destination") placeCountry.destination = "";
      invalidateSchedule();
      look();
    });
    list.addEventListener("mousedown", (event) => {
      const button = event.target.closest("button[data-code]");
      if (!button) return;
      event.preventDefault();
      hidden.value = button.dataset.code;
      search.value = `${button.dataset.name} (${button.dataset.code})`;
      // 도착 국가는 "미국_의류_20260923"처럼 지을 이름에 씁니다. 골라 둘 때 받아 둡니다.
      placeCountry[role] = button.dataset.country || "";
      hideList();
      invalidateSchedule();
      suggestName();
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
  // 화면에 칸이 없지만 운송 계획으로 넘겨야 하는 값. (올린 L/C에서 읽은 선적 마감 조건)
  const carried = {};
  const CARRIED_KEYS = ["lc_latest_shipment_date", "lc_expiry_date", "lc_presentation_days"];

  function sharedValues() {
    const fields = { ...carried };
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

  /* ----- 임시저장 · 불러오기 -----
     다른 화면에 다녀와도 적던 내용이 남아 있어야 합니다. 두 곳에 둡니다.

       이 탭(sessionStorage)  바이어 주소·연락처까지 그대로. 탭을 닫으면 사라집니다.
       서버(/api/work-draft)  다른 기기·다른 탭에서도 이어 쓰는 값. 비공개 칸은 빼고 저장합니다.

     돌아왔을 때는 둘 중 나중에 저장된 것을 씁니다. */
  const LOCAL_KEY = window.ForwardusStore.key("forwardus:doc-form-draft");
  // 시작 화면에서 넘어온 초안. 같은 회원 것만 집습니다. (home.js에서 넣습니다)
  const DOC_DRAFT_KEY = window.ForwardusStore.key("forwardus:doc-draft");

  function saveLocal() {
    const draft = { ...sharedValues(), savedAt: Date.now(), lc: { ...carried }, tab: currentTab };
    try {
      window.sessionStorage.setItem(LOCAL_KEY, JSON.stringify(draft));
    } catch (error) { /* 저장 공간을 못 쓰면 서버 쪽만 남습니다. */ }
  }

  function readLocal() {
    try {
      const draft = JSON.parse(window.sessionStorage.getItem(LOCAL_KEY) || "null");
      return draft && draft.savedAt ? draft : null;
    } catch (error) {
      return null;
    }
  }

  function forgetLocal() {
    try {
      window.sessionStorage.removeItem(LOCAL_KEY);
    } catch (error) { /* 무시 */ }
  }

  const saveSoon = debounce(() => { syncWorkDraft(); saveLocal(); }, 400);
  form.addEventListener("input", saveSoon);
  form.addEventListener("change", saveSoon);

  // 값을 조용히 되돌립니다. (노란 표시를 붙이지 않습니다. 사람이 직접 적은 값이니까요)
  function applyDraft(draft) {
    const fields = draft.fields || {};
    // 운송 모드를 먼저 고릅니다. 나중에 누르면 적어 둔 출발·도착지가 지워집니다.
    ["transport_mode", "sea_mode"].forEach((name) => {
      const input = form.elements[name];
      if (!input || !fields[name] || input.value === fields[name]) return;
      const button = input.closest("[data-doc-choice]")
        .querySelector(`button[data-value="${fields[name]}"]`);
      if (button) button.click();
    });
    // 출발지·도착지의 "보이는 이름"은 칸이 아니라 검색 칸에 넣습니다. (아래에서 따로)
    const SHOWN_PLACES = ["origin_name", "destination_name"];
    Object.entries(fields).forEach(([name, value]) => {
      if (!value || SHOWN_PLACES.includes(name) || ["transport_mode", "sea_mode"].includes(name)) return;
      const input = form.elements[name];
      if (input && !input.closest("[data-doc-choice]")) input.value = value;
    });
    ["origin", "destination"].forEach((role) => {
      const shown = fields[`${role}_name`];
      const box = panel.querySelector(`[data-doc-place="${role}"]`);
      if (shown && box) box.querySelector("[data-place-search]").value = shown;
    });
    Object.assign(carried, draft.lc || {});
    const items = draft.items || [];
    if (items.length) {
      itemsBox.innerHTML = "";
      items.forEach((item) => {
        const row = addItem();
        row.querySelectorAll("[data-doc-input]").forEach((input) => {
          const key = input.name.replace(/^item_/, "");
          if (item[key]) input.value = item[key];
        });
      });
    }
    applyCurrency();
    invalidateSchedule();
    drawCalendar();
    score();
  }

  function showRestoredNote(savedAt) {
    const note = document.createElement("div");
    note.className = "flash flash_success doc_restored";
    note.setAttribute("role", "status");
    const when = savedAt
      ? new Date(savedAt).toLocaleString("ko-KR", { month: "long", day: "numeric",
                                                   hour: "2-digit", minute: "2-digit" })
      : "";
    note.innerHTML = `📝 적던 내용을 불러왔습니다.${when ? ` <b>${escapeHtml(when)}</b> 저장분입니다.` : ""}`
      + ` <button type="button" class="link_button" data-doc-clear>비우고 새로 시작</button>`;
    panel.prepend(note);
    note.querySelector("[data-doc-clear]").addEventListener("click", async () => {
      forgetLocal();
      if (window.ForwardusWorkDraft) await window.ForwardusWorkDraft.clear();
      window.location.reload();
    });
  }

  /* ----- 새 파일을 읽는 동안 ----- */
  function clearForm() {
    panel.querySelectorAll(".doc_restored").forEach((note) => note.remove());
    form.reset();
    itemsBox.innerHTML = "";
    addItem();
    Object.keys(carried).forEach((key) => { delete carried[key]; });
    chosenSchedule = "";
    forgetLocal();
    if (window.ForwardusWorkDraft) window.ForwardusWorkDraft.clear();
    applyMode(form.elements.transport_mode ? form.elements.transport_mode.value : "SEA");
    applyCurrency();
    invalidateSchedule();
    score();
  }

  function showReading(file) {
    hideReading();
    const note = document.createElement("div");
    note.className = "doc_reading";
    note.setAttribute("role", "status");
    note.innerHTML = `<span class="doc_reading_spin" aria-hidden="true"></span>
      <span><b>${escapeHtml(file && file.name ? file.name : "올린 서류")}을(를) 읽고 있습니다…</b>
      <small>그림으로 된 서류는 30초쯤 걸립니다. 앞서 적어 두신 내용은 지우고 이 파일 기준으로 채웁니다.</small></span>`;
    panel.prepend(note);
    note.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function hideReading() {
    panel.querySelectorAll(".doc_reading").forEach((note) => note.remove());
  }

  async function restoreDraft() {
    // 시작 화면에서 "적은 내용으로 칸 채우기"로 넘어온 경우가 가장 먼저입니다. (방금 고른 값)
    let stashed = null;
    try {
      const raw = window.sessionStorage.getItem(DOC_DRAFT_KEY);
      if (raw) {
        window.sessionStorage.removeItem(DOC_DRAFT_KEY);
        stashed = JSON.parse(raw);
      }
    } catch (error) { /* 깨졌으면 없는 것으로 봅니다. */ }
    if (stashed) {
      // 대화창에서 이름 붙여 저장해 둔 초안이면, 여기서 만든 Shipment에 이어 붙입니다.
      carriedDraftId = stashed.draftId || null;
      window.FORWARDUS_DOC_FILL(stashed);
      saveLocal();
      return;
    }

    const local = readLocal();
    let server = null;
    if (window.ForwardusWorkDraft) server = await window.ForwardusWorkDraft.load();
    // 나중에 저장된 것을 씁니다. (서버는 다른 탭·기기에서 적었을 수 있습니다)
    const newest = !local ? server
      : (!server || (server.updated_ms || 0) <= local.savedAt ? local
        : { ...server, savedAt: server.updated_ms, lc: local.lc, tab: local.tab,
            fields: { ...local.fields, ...server.fields },
            items: (server.items && server.items.length) ? server.items : local.items });
    if (!newest || (!Object.keys(newest.fields || {}).length && !(newest.items || []).length)) return;
    applyDraft(newest);
    // 보던 갈래로 돌아갑니다. (탭이 아니라 그 구역으로 스크롤합니다)
    if (newest.tab) goToSection(newest.tab);
    showRestoredNote(newest.savedAt);
  }

  /* ----- Consignee ↔ Buyer 자동 보완 -----
     실무에서 물건을 받는 곳과 대금을 내는 곳은 대개 같습니다. 같을 때 한쪽을
     비워 두면 송장에 —가 찍히는데, 세관과 은행은 그 빈칸을 "다른 곳인데 안
     적었다"로 읽습니다. 한쪽만 적혀 있으면 나머지를 채워 둡니다.

     채워 넣은 값은 노란 표시(is_prefilled)를 달아 둡니다. 사람이 그 칸에 직접
     적기 시작하면 표시가 지워지고, 적은 값이 그대로 남습니다.
     (같은 규칙이 서버에도 있습니다 — processors/document_defaults.pair_parties) */
  const SAME_AS_CONSIGNEE = "SAME AS CONSIGNEE";
  const consigneeEl = form.elements.buyer_name;      // 상업송장 ④Consignee
  const invoiceBuyerEl = form.elements.buyer;        // 상업송장 ⑨Buyer

  // 사람이 적은 값인지, 우리가 채워 넣은 값인지 봅니다.
  function isAuto(input) {
    return !!input && input.dataset.autoFilled === input.value.trim();
  }

  function setAuto(input, value) {
    input.value = value;
    input.dataset.autoFilled = value;
    // 알림을 먼저 보내고 표시를 답니다. markPrefilled는 다음 input 한 번에 표시를
    // 지우므로, 순서를 바꾸면 우리가 보낸 알림에 표시가 바로 지워집니다.
    input.dispatchEvent(new Event("input", { bubbles: true }));
    markPrefilled(input);
  }

  function clearAuto(input) {
    if (!isAuto(input)) return;
    input.value = "";
    delete input.dataset.autoFilled;
    input.classList.remove("is_prefilled");
  }

  function pairParties() {
    if (!consigneeEl || !invoiceBuyerEl) return;
    const consignee = consigneeEl.value.trim();
    const buyer = invoiceBuyerEl.value.trim();

    // Buyer를 지웠는데 Consignee가 그걸 보고 채운 값이면 같이 걷어 냅니다.
    // 그러지 않으면 지운 상호가 Consignee에 남고, 거기서 다시 Buyer가 채워집니다.
    if (!buyer && isAuto(consigneeEl)) { clearAuto(consigneeEl); return; }

    if (consignee && (!buyer || isAuto(invoiceBuyerEl))) {
      // Consignee만 적혔습니다. Buyer 칸에 "SAME AS CONSIGNEE"라고 적어 둡니다.
      if (buyer !== SAME_AS_CONSIGNEE) setAuto(invoiceBuyerEl, SAME_AS_CONSIGNEE);
      return;
    }
    // Buyer만 적혔습니다. Consignee 칸에는 문구가 아니라 상호를 그대로 옮깁니다.
    // 이 값은 대시보드 목록의 Buyer 이름으로도 저장돼, 문구가 들어가면 목록에서
    // 어느 건인지 알 수 없게 됩니다. Buyer가 "SAME AS CONSIGNEE" 문구뿐이면
    // 받는 곳을 모르는 상태라 그대로 비워 두고 필수 칸으로 다시 묻습니다.
    if (!consignee && buyer && !isAuto(invoiceBuyerEl)
        && buyer.toUpperCase() !== SAME_AS_CONSIGNEE) {
      setAuto(consigneeEl, buyer.slice(0, 200));
      return;
    }
    // Consignee를 지웠으면 그걸 보고 채운 Buyer 문구도 걷어 냅니다.
    if (!consignee && isAuto(invoiceBuyerEl)) clearAuto(invoiceBuyerEl);
  }

  [consigneeEl, invoiceBuyerEl].forEach((input) => {
    if (!input) return;
    // 적는 동안에는 건드리지 않습니다. 칸을 벗어날 때 한 번만 봅니다.
    input.addEventListener("blur", pairParties);
    // 사람이 직접 적기 시작하면 "우리가 채운 값"이라는 표시를 뗍니다.
    input.addEventListener("input", () => {
      if (input.dataset.autoFilled && input.value.trim() !== input.dataset.autoFilled) {
        delete input.dataset.autoFilled;
      }
    });
  });

  /* ----- 견적명 자동 제안 -----
     대시보드 목록에서 이 건을 부르는 이름입니다. 비워 두면 서버가
     "도착국가_대표품목_날짜"로 짓습니다. 무엇으로 저장될지 미리 보여 줍니다.
     (이름 짓는 규칙은 서버 한 곳 — /documents/suggest-name) */
  const nameEl = form.elements.project_name;
  const nameStep = panel.querySelector("[data-doc-name-step]");
  const nameHintEl = panel.querySelector("[data-doc-name-suggest]");
  const nameValueEl = panel.querySelector("[data-doc-name-value]");
  let suggestedName = "";

  async function askName() {
    if (!config.suggestNameUrl) return "";
    const first = itemValues()[0] || {};
    const response = await postJson(config.suggestNameUrl, {
      destination_code: form.elements.destination_code ? form.elements.destination_code.value : "",
      buyer_country: form.elements.buyer_country ? form.elements.buyer_country.value : "",
      requested_departure_date: departEl.value,
      // 나라 이름은 도착지를 고를 때 받아 둔 것을 씁니다. 코드만으로는 "미국"이 안 나옵니다.
      destination_country_name: placeCountry.destination,
      items: [{ product_description: first.product_description || "" }],
    });
    return response.success ? (response.data.project_name || "") : "";
  }

  const suggestName = debounce(async () => {
    if (!nameEl || !nameHintEl) return;
    suggestedName = await askName();
    nameValueEl.textContent = suggestedName;
    nameEl.placeholder = suggestedName || "예: 2026-10 멕시코 화장품 1차 오퍼";
    // 적어 둔 이름이 있으면 제안을 내밀지 않습니다. 고른 이름이 맞습니다.
    nameHintEl.hidden = !suggestedName || !!nameEl.value.trim();
  }, 500);

  panel.querySelector("[data-doc-name-use]")?.addEventListener("click", () => {
    if (!suggestedName) return;
    nameEl.value = suggestedName;
    nameHintEl.hidden = true;
    nameEl.dispatchEvent(new Event("input", { bubbles: true }));
    nameEl.focus();
  });

  nameEl?.addEventListener("input", () => {
    if (nameHintEl) nameHintEl.hidden = !suggestedName || !!nameEl.value.trim();
  });

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
  // 도착지·품목·날짜가 바뀌면 지어 둘 견적명도 달라집니다.
  form.addEventListener("change", (event) => {
    if (!nameStep) return;
    const name = event.target.name || "";
    if (name === "project_name") return;
    if (name === "item_product_description" || name === "buyer_country"
        || name === "requested_departure_date" || name === "destination_code") suggestName();
  });

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
      ...planPayload(), draft_id: undefined,
      project_name: "스케줄 조회", cargo: { items: itemValues() },
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
    originBody.innerHTML = `<p class="muted small">필요한 서류를 찾고 있습니다…
      <small>(관세청 요건 · 도착국 인증 · 협정)</small></p>`;
    // 두 가지를 함께 그립니다. 필요한 서류 목록(새로 만든 것)과 협정 안내(예전 것).
    const [docs, origin] = await Promise.all([
      getJson(config.requiredDocsUrl.replace("__ID__", shipmentId)),
      getJson(config.originUrl.replace("__ID__", shipmentId)),
    ]);
    if (!docs.success && !origin.success) {
      originBody.innerHTML = `<p class="doc_error_line">${escapeHtml(docs.message || origin.message)}</p>`;
      return;
    }
    originBody.innerHTML = (docs.success ? requiredDocsHtml(docs.data) : "")
      + (origin.success ? originHtml(origin.data) : "");
  }

  /* ----- 기타 필수 서류 -----
     HS부호와 도착국으로 찾은 서류를 한 목록으로 보여 줍니다. 어디서 찾은 것인지
     (관세청·규칙·협정·도착국·AI) 함께 적습니다. AI가 찾은 것은 그렇다고 밝혀,
     사람이 한 번 더 확인하고 쓰게 합니다. */
  const DOC_SOURCE = {
    customs: { label: "관세청 세관장확인", tone: "must" },
    rule: { label: "수출요건", tone: "must" },
    fta: { label: "FTA 특혜관세", tone: "" },
    country: { label: "도착국 인증", tone: "" },
    ai: { label: "AI가 찾음 · 확인 필요", tone: "ai" },
  };

  function requiredDocRow(row, uploadUrl) {
    const source = DOC_SOURCE[row.source] || { label: "", tone: "" };
    const files = (row.uploads || []).map((file) =>
      `<span class="rq_file">📎 ${escapeHtml(file.filename)}`
      + `<small>${escapeHtml(file.status_label || "")}</small></span>`).join("");
    const papers = (row.documents || []).length
      ? `<ul class="rq_papers">${row.documents.map((name) =>
          `<li>${escapeHtml(name)}</li>`).join("")}</ul>` : "";
    return `
      <div class="rq_row${row.uploaded ? " is_done" : ""}">
        <div class="rq_head">
          <b>${escapeHtml(row.title)}</b>
          <span class="rq_tag ${source.tone}">${escapeHtml(source.label)}</span>
          ${row.uploaded ? '<span class="rq_tag done">올림</span>' : ""}
        </div>
        ${row.why ? `<p class="rq_why">${escapeHtml(row.why)}</p>` : ""}
        ${row.agency ? `<p class="rq_agency">발급·신청: ${escapeHtml(row.agency)}</p>` : ""}
        ${papers}
        ${files ? `<div class="rq_files">${files}</div>` : ""}
        <form class="rq_upload" method="post" enctype="multipart/form-data" action="${escapeHtml(uploadUrl)}">
          <input type="hidden" name="requirement_key" value="${escapeHtml(row.key)}">
          <input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg,.txt,.docx" required>
          <button class="button small primary" type="submit">올리기</button>
        </form>
      </div>`;
  }

  function requiredDocsHtml(data) {
    const rows = (data.documents || []);
    const list = rows.length
      ? rows.map((row) => requiredDocRow(row, data.upload_url)).join("")
      : `<p class="doc_note">HS부호와 도착국으로는 따로 받아야 할 서류가 잡히지 않았습니다.
         품목에 따라 달라지니 바이어가 요구하는 서류도 함께 확인해 주세요.</p>`;
    const others = (data.others || []).length
      ? `<p class="muted small">그 밖에 올려 두신 파일: `
        + data.others.map((row) => escapeHtml(row.filename)).join(", ") + "</p>" : "";
    const ai = data.ai_available
      ? (data.ai_used ? "" : "<small class=\"muted\">AI가 더 찾은 것은 없습니다.</small>")
      : "<small class=\"muted\">AI 키가 없어 우리 자료로만 찾았습니다.</small>";
    return `
      <section class="doc_group">
        <h3><span aria-hidden="true">📎</span> ${escapeHtml(data.destination || "")} 보낼 때 필요한 서류
          <span class="rq_count">${data.ready}/${data.total}</span></h3>
        <p class="doc_note">${escapeHtml(data.note || "")} ${ai}</p>
        <div class="rq_list">${list}</div>
        ${others}
        <p class="muted small"><a href="${escapeHtml(data.filing_url)}">관세사에게 넘길 자료 보기 →</a></p>
      </section>`;
  }

  /* ----- 협정 안내 (원산지증명서) -----
     기타 필수 서류 목록에도 원산지증명서 한 줄이 나옵니다. 여기서는 그 한 줄로는
     모자란 것 — 이 건에 쓸 수 있는 협정과 세율, 신청 창구 — 을 펼쳐 보여 줍니다. */
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
        <h3><span aria-hidden="true">🏛</span> 원산지증명서 신청 창구</h3>
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
    const payload = { items: itemValues(), schedule_id: chosenSchedule,
                      draft_id: carriedDraftId };
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
    // 칸에서 초점을 떼지 않고 바로 누른 경우까지 챙깁니다.
    pairParties();
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
    // 올린 L/C에서 읽은 선적 마감 조건. 화면에 칸은 없지만 운송 계획으로 넘깁니다.
    CARRIED_KEYS.forEach((key) => {
      if (draft.lc && draft.lc[key]) carried[key] = String(draft.lc[key]);
    });

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
    pairParties();            // 올린 B/L에 한쪽만 있어도 나머지가 채워집니다.
    score();
    applyCurrency();          // 읽어 온 통화가 금액 라벨에 바로 붙습니다.
    suggestName();            // 읽어 온 도착지·품목으로 견적명을 다시 제안합니다.
    syncWorkDraft("upload");  // 올린 서류·대화에서 읽은 값도 운송 계획으로 이어집니다.
    saveLocal();
  };

  addItem();
  applyMode("SEA");
  drawCalendar();
  markRail("when");
  score();
  suggestName();

  /* ----- B/L·Offer Sheet 올려서 칸 채우기 ----- */
  const uploadZone = document.querySelector("[data-doc-upload]");
  const uploadResult = document.querySelector("[data-doc-upload-result]");
  if (uploadZone && window.ForwardusDocUpload && config.extractUrl) {
    window.ForwardusDocUpload.mount(uploadZone, {
      url: config.extractUrl,
      onStart(file) {
        uploadResult.hidden = true;
        // 새로 올린 파일이 기준입니다. 앞서 적어 둔 값이 섞이면 어느 서류의 값인지 알 수 없습니다.
        clearForm();
        showReading(file);
      },
      onError() { hideReading(); },
      onResult(data) {
        hideReading();
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

  /* ----- 이미 만든 건에서 가져오기 -----
     같은 바이어에게 두 번째로 보내는 일이 흔합니다. 그때마다 주소·품목·조건을
     처음부터 다시 적게 하면 오타가 납니다.

     고르면 올린 서류와 같이 칸을 비우고 다시 채웁니다. 앞서 적어 둔 값이 섞이면
     어느 건의 값인지 알 수 없습니다. 채우기만 하고 만들지는 않습니다. */
  const sourcePick = document.querySelector("[data-doc-source]");
  const sourceStatus = document.querySelector("[data-doc-source-status]");
  if (sourcePick && config.sourceUrl) {
    sourcePick.addEventListener("change", async () => {
      const picked = sourcePick.value;
      sourceStatus.textContent = "";
      if (!picked) return;
      const [kind, id] = picked.split(/:(.*)/s);
      const label = sourcePick.options[sourcePick.selectedIndex].textContent.trim();
      sourceStatus.textContent = "가져오는 중입니다…";
      const response = await getJson(
        config.sourceUrl.replace("__KIND__", encodeURIComponent(kind))
                        .replace("__ID__", encodeURIComponent(id)));
      if (!response.success) {
        sourceStatus.textContent = response.message || "가져오지 못했습니다.";
        sourcePick.value = "";
        return;
      }
      clearForm();
      window.FORWARDUS_DOC_FILL(response.data);
      sourceStatus.textContent = `${label}에서 가져왔습니다. 노란 칸이 가져온 값입니다.`;
    });
  }

  // 화면을 떠나는 순간에는 기다리지 않고 바로 저장합니다.
  // (적자마자 홈으로 누르면 0.4초를 기다리던 마지막 입력이 사라집니다)
  window.addEventListener("pagehide", saveLocal);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") saveLocal();
  });

  // 적던 내용 되살리기. 칸·품목·달력이 모두 준비된 뒤에 부릅니다.
  restoreDraft();
})();
