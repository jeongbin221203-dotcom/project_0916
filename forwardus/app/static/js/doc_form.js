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
  const titleEl = panel.querySelector("[data-doc-title]");
  const leadEl = panel.querySelector("[data-doc-lead]");
  const errorEl = panel.querySelector("[data-doc-error]");
  const resultEl = panel.querySelector("[data-doc-result]");
  const scheduleBox = panel.querySelector("[data-doc-schedules]");

  let chosenSchedule = "";
  let madeShipment = "";

  /* ----- 탭마다 보여 줄 것 ----- */
  const ABOUT = {
    when: ["언제 보내나요",
      "고른 날짜로 스케줄을 찾고, 그 출항일이 상업송장에 인쇄됩니다."],
    plan: ["어디서 어디로 보내나요",
      "출발지·도착지와 스케줄입니다. 선박명과 출항일이 여기서 정해집니다."],
    doc: ["서류에 필요한 것",
      '상업송장과 포장명세서가 요구하는 칸입니다. <i class="doc_must">*</i>는 없으면 서류가 '
      + "안 나오고, 나머지는 비우면 서류에 <b>—</b>로 남습니다."],
    origin: ["원산지증명서",
      "협정마다 서식과 발급 주체가 달라 대신 만들어 드릴 수 없습니다. "
      + "어디서 어떤 서식으로 받는지 알려 드리고, 받으신 PDF를 등록하면 이 건과 맞는지 봅니다."],
  };

  let currentTab = "doc";

  function showDocTab(key) {
    currentTab = key;
    panel.querySelectorAll("[data-doc-tab]").forEach((box) => {
      box.hidden = box.dataset.docTab !== key;
    });
    panel.querySelectorAll("[data-doc-nav]").forEach((button) => {
      const on = button.dataset.docNav === key;
      button.classList.toggle("active", on);
      button.setAttribute("aria-selected", on ? "true" : "false");
    });
    const about = ABOUT[key] || ABOUT.doc;
    titleEl.textContent = about[0];
    leadEl.innerHTML = about[1];
    // form은 서류/일정/운송에서만 씁니다. 원산지는 이 건이 있어야 해서 밖에 있습니다.
    form.hidden = key === "origin";
    if (key === "origin") openOrigin();
  }

  panel.querySelectorAll("[data-doc-nav]").forEach((button) => {
    button.addEventListener("click", () => showDocTab(button.dataset.docNav));
  });

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

    const look = debounce(async () => {
      const query = search.value.trim();
      if (!query) { list.hidden = true; return; }
      const mode = form.elements.transport_mode ? form.elements.transport_mode.value : "SEA";
      const params = new URLSearchParams({ q: query, mode, role });
      const response = await getJson(`${config.locationsUrl}?${params}`);
      const rows = response.success ? response.data.slice(0, 8) : [];
      list.innerHTML = rows.length
        ? rows.map((row) => `<li><button type="button" data-code="${escapeHtml(row.code)}"`
            + ` data-name="${escapeHtml(row.name)}">${escapeHtml(row.name)}`
            + ` <small>${escapeHtml(row.code)} · ${escapeHtml(row.country)}</small></button></li>`).join("")
        : `<li class="empty">찾지 못했습니다. 다른 이름으로 적어 보세요.</li>`;
      list.hidden = false;
    }, 250);

    search.addEventListener("input", () => { hidden.value = ""; invalidateSchedule(); look(); });
    list.addEventListener("mousedown", (event) => {
      const button = event.target.closest("button[data-code]");
      if (!button) return;
      event.preventDefault();
      hidden.value = button.dataset.code;
      search.value = `${button.dataset.name} (${button.dataset.code})`;
      list.hidden = true;
      invalidateSchedule();
      score();
    });
    search.addEventListener("blur", () => setTimeout(() => { list.hidden = true; }, 150));
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
  const LOCAL_KEY = "forwardus:doc-form-draft";

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

  async function restoreDraft() {
    // 시작 화면에서 "적은 내용으로 칸 채우기"로 넘어온 경우가 가장 먼저입니다. (방금 고른 값)
    let stashed = null;
    try {
      const raw = window.sessionStorage.getItem("forwardus:doc-draft");
      if (raw) {
        window.sessionStorage.removeItem("forwardus:doc-draft");
        stashed = JSON.parse(raw);
      }
    } catch (error) { /* 깨졌으면 없는 것으로 봅니다. */ }
    if (stashed) {
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
    if (newest.tab) showDocTab(newest.tab);
    showRestoredNote(newest.savedAt);
  }

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
    scheduleBox.innerHTML = `<p class="muted small">내용이 바뀌었습니다. 스케줄을 다시 찾아 주세요.</p>`;
  }

  panel.querySelector("[data-doc-find-schedule]").addEventListener("click", async () => {
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
        <input type="radio" name="schedule_pick" value="${escapeHtml(item.schedule_id)}">
        <b>${escapeHtml(item.carrier || "-")}${item.vessel ? " · " + escapeHtml(item.vessel) : ""}</b>
        <span>ETD ${escapeHtml(item.etd)} → ETA ${escapeHtml(item.eta)} · ${item.transit_days}일</span>
        <small class="muted">${item.source === "api" ? "실제 스케줄" : "예시 스케줄 (API 키가 없어 추정치입니다)"}</small>
      </label>`).join("");
    scheduleBox.querySelectorAll("input[name=schedule_pick]").forEach((radio) => {
      radio.addEventListener("change", () => { chosenSchedule = radio.value; score(); });
    });
  });

  /* ----- 원산지증명서 ----- */
  const originEmpty = panel.querySelector("[data-origin-empty]");
  const originBody = panel.querySelector("[data-origin-body]");
  const originPick = panel.querySelector("[data-origin-pick]");

  panel.querySelector("[data-origin-goto-doc]")?.addEventListener("click", () => {
    showDocTab("doc");
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

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = !message;
    if (message) errorEl.scrollIntoView({ behavior: "smooth", block: "center" });
  }

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
      showError(response.message);
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
      showDocTab("origin");
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
    score();
    applyCurrency();          // 읽어 온 통화가 금액 라벨에 바로 붙습니다.
    syncWorkDraft("upload");  // 올린 서류·대화에서 읽은 값도 운송 계획으로 이어집니다.
    saveLocal();
  };

  addItem();
  applyMode("SEA");
  drawCalendar();
  showDocTab("doc");
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
        showDocTab("doc");
        uploadResult.scrollIntoView({ behavior: "smooth", block: "start" });
      },
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
