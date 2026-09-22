/* 오퍼시트 올리기. 시작 화면의 📎 단추와 적는 칸에 끌어다 놓기.

   흐름
     1. 파일을 보냅니다. 서버가 읽고(사진이면 계좌번호를 먼저 지우고) 확인합니다.
     2. 읽은 값을 표로 보여 주고 사람이 확인·입력합니다.
        확인됨 / 확인 필요 / 직접 입력 세 가지로 나눠 보여 줍니다.
     3. "확인했어요"를 누르면 서버가 다시 검증하고 초안 세 장을 그립니다.

   은행 정보와 바이어 주소·연락처는 이 파일의 변수(메모리)에만 둡니다.
   서버에 저장하지 않고, 브라우저 저장소(sessionStorage)에도 넣지 않습니다.
   미리보기(가려서)와 PDF(그대로)를 만들 때만 서버를 지나갑니다. */
(function () {
  "use strict";

  const config = window.FORWARDUS_HOME;
  const home = window.ForwardusHome;
  const fileInput = document.querySelector("[data-offer-file]");
  const composer = document.querySelector("[data-home-form]");
  if (!config || !home || !fileInput || !config.offerUrl) return;

  const { escapeHtml, postJson } = window.Forwardus;
  const READ_TIMEOUT_MS = 180000;
  const PRIVATE_KEYS = ["bank_info", "buyer_address", "buyer_contact"];
  const STATUS = {
    ok: { label: "확인됨", css: "ok" },
    check: { label: "확인 필요", css: "check" },
    missing: { label: "직접 입력", css: "missing" },
  };

  // 지금 다루는 오퍼시트. 새 파일을 올리면 통째로 바뀝니다.
  let token = "";
  let privateValues = {};
  let draft = {};

  /* ----- 1. 올리기 ----- */
  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) upload(fileInput.files[0]);
    fileInput.value = "";          // 같은 파일을 다시 골라도 다시 올라가게
  });

  // 적는 칸에 파일을 끌어다 놓아도 올립니다.
  ["dragover", "dragenter"].forEach((name) => composer.addEventListener(name, (event) => {
    if (!event.dataTransfer || !Array.from(event.dataTransfer.types).includes("Files")) return;
    event.preventDefault();
    composer.classList.add("dropping");
  }));
  ["dragleave", "drop"].forEach((name) => composer.addEventListener(name, () =>
    composer.classList.remove("dropping")));
  composer.addEventListener("drop", (event) => {
    const file = event.dataTransfer && event.dataTransfer.files[0];
    if (!file) return;
    event.preventDefault();
    upload(file);
  });

  async function upload(file) {
    home.say("me", `📎 ${file.name}`);
    const picture = /\.(png|jpe?g)$/i.test(file.name);
    const waiting = home.say("bot wait", picture
      ? "사진 속 계좌번호를 먼저 지운 뒤 오퍼시트를 읽고 있습니다…"
      : "오퍼시트를 읽고 있습니다…");

    const body = new FormData();
    body.append("file", file);
    const response = await sendForm(config.offerUrl, body);
    waiting.remove();
    if (!response.success) {
      home.say("bad", response.message || "파일을 읽지 못했습니다. 서류 작성 화면에서 직접 입력해 주세요.");
      return;
    }

    const data = response.data;
    token = data.token;
    privateValues = { ...(data.private || {}) };
    draft = data.draft || {};
    showSource(data.source || {});
    (data.notes || []).forEach((note) => home.say("bad", note));
    showConfirm(data);
    if ((data.documents || []).length) {
      home.say("bot", "지금까지 **확실한 값만으로** 그린 초안입니다. 빨간 글씨 칸은 아래 표에서 "
        + "확인하시거나, 운송 계획·서류 작성에서 입력하면 채워집니다.");
      data.documents.forEach(showDocument);
    }
  }

  // 파일은 JSON이 아니라 FormData로 보냅니다. 읽는 데 오래 걸려 기다리는 시간을 넉넉히 둡니다.
  async function sendForm(url, body) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), READ_TIMEOUT_MS);
    try {
      const response = await fetch(url, { method: "POST", body, signal: controller.signal,
                                          headers: { Accept: "application/json" } });
      return await response.json();
    } catch (error) {
      return { success: false, message: error.name === "AbortError"
        ? "읽는 데 너무 오래 걸립니다. 잠시 뒤 다시 올려 주세요."
        : "서버와 통신하지 못했습니다. 다시 올려 주세요." };
    } finally {
      clearTimeout(timer);
    }
  }

  /* ----- AI에 무엇이 갔는지 ----- */
  function showSource(source) {
    const row = home.say("bot", "");
    const pictures = (source.sent_images || []).map((src, index) =>
      `<figure class="offer_sent"><img src="${src}" alt="AI에 보낸 그림 ${index + 1}쪽">`
      + `<figcaption>AI에 보낸 그림 ${index + 1}쪽</figcaption></figure>`).join("");
    row.innerHTML = `<p class="offer_notice">🔒 ${escapeHtml(source.notice || "")}</p>`
      + (pictures ? `<div class="offer_sent_row">${pictures}</div>` : "");
  }

  /* ----- 2. 확인 표 ----- */
  function statusChip(status) {
    const info = STATUS[status] || STATUS.missing;
    return `<span class="offer_chip ${info.css}">${info.label}</span>`;
  }

  function fieldRow(field) {
    const id = `offer_${field.key}`;
    let control;
    if (field.private) {
      // 은행·바이어 주소·연락처는 화면에서도 가립니다. 적은 글자가 보이지 않습니다.
      const has = Boolean(privateValues[field.key]);
      control = `<input id="${id}" type="password" autocomplete="new-password" data-lpignore="true"
          data-offer-private="${field.key}" placeholder="${has ? "읽은 값을 가려 두었습니다" : "직접 입력"}">
        <small class="muted">${has ? "읽은 값이 있습니다. 고칠 때만 새로 적으세요. " : ""}`
        + "화면에는 가리고 PDF에만 넣습니다. 서버에 저장하지 않습니다.</small>";
    } else {
      control = `<input id="${id}" type="text" data-offer-field="${field.key}"
          value="${escapeHtml(field.value || "")}"
          placeholder="${field.status === "missing" ? "직접 입력" : ""}">`;
    }
    const note = field.note ? `<small class="offer_note">${escapeHtml(field.note)}</small>` : "";
    return `<tr class="st_${field.status}">
        <th><label for="${id}">${escapeHtml(field.label)}</label></th>
        <td>${control}${note}</td>
        <td>${statusChip(field.status)}</td>
      </tr>`;
  }

  function unitOptions(units, picked) {
    const options = Object.entries(units || {}).map(([code, name]) =>
      `<option value="${escapeHtml(code)}"${code === picked ? " selected" : ""}>`
      + `${escapeHtml(code)} · ${escapeHtml(name)}</option>`).join("");
    return `<option value=""${picked ? "" : " selected"}>단위 고르기</option>${options}`;
  }

  function itemRow(item, units) {
    const line = item.line || {};
    const read = item.read || {};
    // 확인된 줄은 검증기가 읽은 값을, 아닌 줄은 서류에서 읽은 글자를 그대로 보여 줍니다.
    const priced = line.unit_quantity !== undefined;
    const value = (key, fallback) => escapeHtml(String(priced ? (line[key] ?? "") : (fallback ?? "")));
    const problems = (item.problems || []).map((text) =>
      `<small class="offer_note">${escapeHtml(text)}</small>`).join("");
    return `<tr class="st_${item.status}" data-offer-item
        data-hs="${escapeHtml(line.hs_code || "")}" data-package="${escapeHtml(line.package_type || "")}">
        <td><input type="text" data-k="product_description"
             value="${escapeHtml(line.product_description || read.description || "")}"></td>
        <td><input type="text" inputmode="decimal" data-k="unit_quantity"
             value="${value("unit_quantity", read.quantity)}"></td>
        <td><select data-k="price_unit">${unitOptions(units, line.price_unit || read.unit_code)}</select></td>
        <td><input type="text" inputmode="decimal" data-k="unit_price"
             value="${value("unit_price", read.unit_price)}"></td>
        <td><input type="text" inputmode="decimal" data-k="amount"
             value="${value("amount", read.amount)}"></td>
        <td><input type="text" inputmode="numeric" data-k="units_per_package"
             value="${value("units_per_package", read.pieces_per_package)}"
             placeholder="선택"></td>
        <td>${statusChip(item.status)}${problems}</td>
      </tr>`;
  }

  function showConfirm(data) {
    const fields = data.fields || [];
    const items = data.items || [];
    const counts = { ok: 0, check: 0, missing: 0 };
    fields.concat(items).forEach((row) => { counts[row.status] = (counts[row.status] || 0) + 1; });
    const totals = data.totals || {};
    const totalLine = totals.stated != null
      ? `서류 총액 ${Number(totals.stated).toLocaleString()} · 품목 합 `
        + `${totals.lines_sum != null ? Number(totals.lines_sum).toLocaleString() : "—"}`
        + (totals.match ? " (맞음)" : " (확인 필요)")
      : "서류 총액을 읽지 못했습니다";

    const row = home.say("bot", "");
    row.classList.add("offer_box");
    row.innerHTML = `
      <p><b>읽은 값을 확인해 주세요.</b> 확인됨 ${counts.ok} · 확인 필요 ${counts.check} ·
        직접 입력 ${counts.missing}. <b>확실한 값만 서류에 넣습니다.</b></p>
      <table class="offer_table">
        <thead><tr><th>칸</th><th>값</th><th>상태</th></tr></thead>
        <tbody>${fields.map(fieldRow).join("")}</tbody>
      </table>
      <p class="muted small">품목 · ${escapeHtml(totalLine)}. 수량 × 단가가 금액과 정확히 맞아야 받습니다.
        단가는 오퍼시트에 적힌 단위 그대로(예: 2,000 PCS × 3.20) 서류에 찍습니다.</p>
      <div class="offer_items_scroll">
        <table class="offer_table offer_items">
          <thead><tr><th>품명</th><th>수량</th><th>단위</th><th>단가</th><th>금액</th>
            <th>포장당 수량</th><th>상태</th></tr></thead>
          <tbody>${items.map((item) => itemRow(item, data.price_units)).join("")}</tbody>
        </table>
      </div>
      <div class="draft_actions">
        <button type="button" class="button primary" data-offer-confirm>확인했어요 · 초안 만들기</button>
      </div>`;
    row.querySelector("[data-offer-confirm]").addEventListener("click", (event) =>
      confirm(event.currentTarget, row));
  }

  /* ----- 3. 확인하고 다시 그리기 ----- */
  function collect(box) {
    const values = {};
    box.querySelectorAll("[data-offer-field]").forEach((field) => {
      values[field.dataset.offerField] = field.value.trim();
    });
    // 새로 적은 은행·주소만 바꿉니다. 비워 두면 읽은 값을 그대로 씁니다.
    box.querySelectorAll("[data-offer-private]").forEach((field) => {
      if (field.value.trim()) privateValues[field.dataset.offerPrivate] = field.value.trim();
    });
    const items = Array.from(box.querySelectorAll("[data-offer-item]")).map((line) => {
      const item = { hs_code: line.dataset.hs, package_type: line.dataset.package || "carton" };
      line.querySelectorAll("[data-k]").forEach((cell) => {
        if (cell.value.trim()) item[cell.dataset.k] = cell.value.trim();
      });
      return item;
    }).filter((item) => item.product_description);
    return { values, items };
  }

  async function confirm(button, box) {
    const { values, items } = collect(box);
    button.disabled = true;
    button.textContent = "확인하는 중…";
    const waiting = home.say("bot wait", "적으신 값을 다시 확인하고 초안을 그리고 있습니다…");
    const response = await postJson(config.offerConfirmUrl,
      { token, values, items, private: privateValues }, 120000);
    waiting.remove();
    button.disabled = false;
    button.textContent = "다시 확인하기";

    if (!response.success) {
      home.say("bad", response.message);
      return;
    }
    const data = response.data;
    token = data.token;
    draft = data.draft || {};
    (data.notes || []).forEach((note) => home.say("bad", note));
    if (!(data.documents || []).length) {
      home.say("bad", "확인된 품목이 없어 초안을 그리지 못했습니다. 품목의 수량·단위·단가·금액을 "
        + "확인해 주세요.");
      return;
    }
    home.say("bot", "초안입니다. 은행 정보와 바이어 정보는 화면에서 가렸고 PDF에는 들어갑니다. "
      + "빨간 글씨 칸은 운송 계획·서류 작성에서 입력하면 채워집니다.");
    data.documents.forEach(showDocument);
    showNext();
  }

  function showDocument(doc) {
    const row = home.say("bot", "");
    if (!doc.preview) {
      row.innerHTML = `<p class="draft_name">${escapeHtml(doc.title)}</p>`
        + `<p class="offer_note">${escapeHtml(doc.error || "그리지 못했습니다.")}</p>`;
      return;
    }
    row.innerHTML = `
      <p class="draft_name">${escapeHtml(doc.title)}</p>
      <figure class="draft_sheet"><img src="${doc.preview}" alt="${escapeHtml(doc.title)} 초안"></figure>
      <div class="draft_actions">
        <button type="button" class="button primary" data-offer-pdf>PDF로 받기</button>
      </div>`;
    row.querySelector("[data-offer-pdf]").addEventListener("click", (event) =>
      downloadPdf(event.currentTarget, doc));
  }

  // PDF에는 가린 값(은행·바이어 주소)이 들어가야 합니다. 이때만 같이 보냅니다.
  async function downloadPdf(button, doc) {
    const label = button.textContent;
    button.disabled = true;
    button.textContent = "만드는 중…";
    try {
      const response = await fetch(doc.file_url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ draft, private: privateValues }),
      });
      if (!response.ok) throw new Error(String(response.status));
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `${doc.kind}_draft.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      home.say("bad", "PDF를 만들지 못했습니다. 다시 눌러 주세요.");
    }
    button.disabled = false;
    button.textContent = label;
  }

  // 운송 계획·서류 작성으로 이어 갑니다. 은행·주소는 넘기지 않습니다(그 화면에서 다시 적습니다).
  function showNext() {
    try {
      const fields = { ...draft };
      delete fields.items;
      PRIVATE_KEYS.forEach((key) => delete fields[key]);
      window.sessionStorage.setItem("forwardus:doc-draft",
        JSON.stringify({ fields, items: draft.items || [] }));
    } catch (error) {
      /* 저장 공간이 없으면 링크만 드립니다. 서버에 임시 저장한 값은 그대로 있습니다. */
    }
    const row = home.say("bot", "");
    row.innerHTML = `
      <div class="draft_actions">
        <a class="button primary" href="${escapeHtml(config.docFormUrl)}">서류 작성에서 이어 쓰기 →</a>
        <a class="button" href="${escapeHtml(config.planningUrl)}">운송 계획 잡기 →</a>
      </div>`;
  }
})();
