/* 서류 미리보기 & 검토 창.
   만든 서류를 탭별로 보여 주고, 칸을 그 자리에서 고치게 합니다. 고친 값은
   서버(/documents/draft/preview)가 같은 서식으로 다시 그려 오른쪽 그림에 반영합니다.
   [PDF 다운로드]는 고친 값 그대로 인쇄 규격(A4) PDF를 받습니다(/documents/draft/review.pdf).

   PDF를 브라우저에서 그리지 않는 이유: 화면의 미리보기, 대화창의 "PDF로 받기",
   Shipment의 정식 서류가 모두 서버의 한 서식(document_form)에서 나옵니다. 여기서만
   다른 라이브러리로 그리면 같은 서류가 두 모양이 됩니다.

   ForwardusDocPreview.open(documents, { previewUrl, pdfUrl })
     documents: [{ kind, title, data, columns, fields, preview, missing, undecided }] */
(function () {
  "use strict";

  const modal = document.querySelector("[data-dp-modal]");
  if (!modal) return;

  const { escapeHtml, postJson, debounce } = window.Forwardus;
  const tabsEl = modal.querySelector("[data-dp-tabs]");
  const editEl = modal.querySelector("[data-dp-edit]");
  const imageEl = modal.querySelector("[data-dp-image]");
  const captionEl = modal.querySelector("[data-dp-caption]");
  const statusEl = modal.querySelector("[data-dp-status]");
  const syncEl = modal.querySelector("[data-dp-sync]");
  const pdfButton = modal.querySelector("[data-dp-pdf]");
  const onePdfButton = modal.querySelector("[data-dp-pdf-one]");
  const printButton = modal.querySelector("[data-dp-print]");

  // 길게 적는 칸은 여러 줄로 받습니다.
  const LONG = new Set(["exporter_address", "consignee_address", "remarks", "shipping_marks",
    "other_references", "payment_terms", "bank_info", "comments", "notify_party",
    "dangerous_goods", "buyer"]);

  let docs = [];
  let current = 0;
  let urls = {};
  let returnFocus = null;
  // 다시 그려야 하는 서류. 다른 탭에서 같은 칸을 고치면 여기에 들어갑니다.
  const stale = new Set();
  let drawVersion = 0;

  function status(message, kind = "") {
    statusEl.textContent = message;
    statusEl.className = `dp_status ${kind}`.trim();
    statusEl.hidden = !message;
  }

  /* ----- 탭 ----- */
  function renderTabs() {
    tabsEl.innerHTML = docs.map((doc, index) => {
      const short = doc.title.split(" (")[0];
      const empty = emptyCount(doc);
      return `<button type="button" role="tab" data-dp-tab="${index}"
          class="${index === current ? "active" : ""}" aria-selected="${index === current}">
          ${escapeHtml(short)}${empty ? ` <span class="dp_badge">빈 칸 ${empty}</span>` : ""}</button>`;
    }).join("");
  }

  tabsEl.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-dp-tab]");
    if (!tab) return;
    show(Number(tab.dataset.dpTab));
  });

  function emptyCount(doc) {
    return doc.fields.filter((field) => !String(doc.data[field.key] || "").trim()).length;
  }

  /* ----- 고치는 칸 ----- */
  function fieldHtml(field, value) {
    const empty = !String(value || "").trim();
    const undecided = String(value || "").startsWith("미정");
    const cls = `dp_field${empty ? " is_empty" : ""}${undecided ? " is_undecided" : ""}`;
    const input = LONG.has(field.key)
      ? `<textarea rows="2" data-field="${escapeHtml(field.key)}">${escapeHtml(value)}</textarea>`
      : `<input type="text" data-field="${escapeHtml(field.key)}" value="${escapeHtml(value)}">`;
    return `<label class="${cls}"><span>${escapeHtml(field.label)}</span>${input}</label>`;
  }

  function itemsHtml(doc) {
    if (!doc.columns.length) return "";
    const head = doc.columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("");
    const rows = (doc.data.items || []).map((row, index) => `<tr>${doc.columns.map((column) =>
      `<td><input type="text" data-item-row="${index}" data-item-key="${escapeHtml(column.key)}"
         value="${escapeHtml(row[column.key] ?? "")}" aria-label="${escapeHtml(column.label)} ${index + 1}"></td>`)
      .join("")}</tr>`).join("");
    return `<div class="dp_items"><b>품목 표</b><div class="dp_table_wrap"><table>
      <thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div></div>`;
  }

  function renderEdit(doc) {
    const undecided = doc.undecided && doc.undecided.length
      ? `<p class="dp_note">회색 <b>미정</b> 칸은 스케줄을 고르면 정해집니다. 받은 B/L에 값이 있으면 지금 적으셔도 됩니다.</p>` : "";
    editEl.innerHTML = undecided
      + `<div class="dp_fields">${doc.fields.map((field) => fieldHtml(field, doc.data[field.key] ?? "")).join("")}</div>`
      + itemsHtml(doc);
  }

  // 같은 칸 이름은 다른 서류에도 넣습니다. 송장과 포장명세서의 수출자가 다르면 세관에서 걸립니다.
  function syncOthers(key, value, rowIndex) {
    if (!syncEl.checked) return;
    docs.forEach((doc, index) => {
      if (index === current) return;
      if (rowIndex === undefined) {
        if (key in doc.data && doc.fields.some((field) => field.key === key)) {
          doc.data[key] = value;
          stale.add(index);
        }
      } else if (doc.columns.some((column) => column.key === key) && doc.data.items?.[rowIndex]) {
        doc.data.items[rowIndex][key] = value;
        stale.add(index);
      }
    });
  }

  editEl.addEventListener("input", (event) => {
    const doc = docs[current];
    const target = event.target;
    if (target.dataset.field) {
      doc.data[target.dataset.field] = target.value;
      syncOthers(target.dataset.field, target.value);
      target.closest(".dp_field").classList.toggle("is_empty", !target.value.trim());
    } else if (target.dataset.itemKey) {
      const row = Number(target.dataset.itemRow);
      doc.data.items[row][target.dataset.itemKey] = target.value;
      syncOthers(target.dataset.itemKey, target.value, row);
    } else {
      return;
    }
    // 곧바로 다른 탭으로 옮겨도, 돌아오면 이 서류를 다시 그립니다.
    stale.add(current);
    status("고친 내용을 미리보기에 반영하는 중…");
    redraw();
  });
  // 칸을 벗어나면 탭의 빈 칸 수를 다시 셉니다. (칠 때마다 탭을 그리면 초점이 흔들립니다)
  editEl.addEventListener("change", renderTabs);

  /* ----- 미리보기 다시 그리기 ----- */
  async function draw(index) {
    const doc = docs[index];
    const version = ++drawVersion;
    const response = await postJson(urls.previewUrl, { kind: doc.kind, data: doc.data }, 30000);
    if (!response.success) {
      if (version === drawVersion) status(response.message || "미리보기를 다시 그리지 못했습니다.", "bad");
      return;
    }
    doc.preview = response.data.preview;
    stale.delete(index);
    if (index === current && version === drawVersion) {
      imageEl.src = doc.preview;
      status("반영했습니다. PDF에도 이 내용 그대로 들어갑니다.", "ok");
    }
  }
  const redraw = debounce(() => draw(current), 600);

  function show(index) {
    current = index;
    const doc = docs[index];
    renderTabs();
    renderEdit(doc);
    imageEl.src = doc.preview;
    imageEl.alt = `${doc.title} 미리보기`;
    captionEl.textContent = doc.title;
    status("");
    if (stale.has(index)) draw(index);
  }

  /* ----- PDF ----- */
  async function fetchPdf(list) {
    const response = await fetch(urls.pdfUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ documents: list.map((doc) => ({ kind: doc.kind, data: doc.data })) }),
    });
    if (!response.ok) {
      let message = "PDF를 만들지 못했습니다. 다시 눌러 주세요.";
      try { message = (await response.json()).message || message; } catch (error) { /* PDF 아님 */ }
      throw new Error(message);
    }
    return response.blob();
  }

  async function withBusy(button, label, work) {
    const before = button.textContent;
    button.disabled = true;
    button.textContent = label;
    try {
      await work();
    } catch (error) {
      status(error.message, "bad");
    }
    button.disabled = false;
    button.textContent = before;
  }

  function save(blob, name) {
    // 서버에 파일을 남기지 않습니다. 받은 그대로 저장창을 띄웁니다.
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }

  pdfButton.addEventListener("click", () => withBusy(pdfButton, "PDF 만드는 중…", async () => {
    const blob = await fetchPdf(docs);
    save(blob, docs.length === 1 ? `${docs[0].kind}_draft.pdf` : "trade_documents_draft.pdf");
    status(`${docs.length}종 서류를 PDF 한 파일(A4 ${docs.length}쪽)로 내려받았습니다.`, "ok");
  }));

  onePdfButton.addEventListener("click", () => withBusy(onePdfButton, "만드는 중…", async () => {
    const doc = docs[current];
    save(await fetchPdf([doc]), `${doc.kind}_draft.pdf`);
    status(`${doc.title.split(" (")[0]}만 PDF로 내려받았습니다.`, "ok");
  }));

  // 인쇄: PDF를 새 창에 열어 브라우저의 인쇄를 씁니다. 창은 누른 순간 먼저 엽니다.
  // (응답을 기다린 뒤 열면 팝업 차단에 걸립니다)
  printButton.addEventListener("click", () => {
    const opened = window.open("", "_blank");
    withBusy(printButton, "준비 중…", async () => {
      let blob;
      try {
        blob = await fetchPdf(docs);
      } catch (error) {
        if (opened) opened.close();   // 빈 창을 남기지 않습니다.
        throw error;
      }
      const url = URL.createObjectURL(blob);
      if (opened) {
        opened.location.href = url;
        status("새 창에서 인쇄(Ctrl+P)해 주세요.", "ok");
      } else {
        save(blob, "trade_documents_draft.pdf");
        status("팝업이 막혀 PDF로 내려받았습니다. 파일을 열어 인쇄해 주세요.", "warn");
      }
    });
  });

  /* ----- 열고 닫기 ----- */
  function open(documents, options = {}) {
    if (!documents || !documents.length) return;
    // 같은 서류 묶음을 다시 열면 고친 값이 그대로 남아 있습니다.
    docs = documents;
    urls = options;
    current = 0;
    stale.clear();
    returnFocus = document.activeElement;
    modal.hidden = false;
    document.body.classList.add("hs_modal_open");
    show(0);
    tabsEl.querySelector("button")?.focus();
  }

  function close() {
    if (modal.hidden) return;
    modal.hidden = true;
    document.body.classList.remove("hs_modal_open");
    if (returnFocus && returnFocus.isConnected) returnFocus.focus();
  }

  modal.addEventListener("click", (event) => {
    if (event.target.closest("[data-dp-close]")) close();
  });
  document.addEventListener("keydown", (event) => {
    if (modal.hidden) return;
    if (event.key === "Escape") { event.stopPropagation(); close(); return; }
    if (event.key !== "Tab") return;
    const focusable = Array.from(modal.querySelectorAll("button, input, textarea, select, a[href]"))
      .filter((el) => !el.disabled && el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }, true);

  window.ForwardusDocPreview = { open, close };
})();
