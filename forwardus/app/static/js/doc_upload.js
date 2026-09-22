/* 무역 서류 올리기. 시작 화면과 서류 작성 화면이 같이 씁니다.
   B/L·Offer Sheet·견적서·Packing List를 올리면 서버(/documents/extract)가 AI로 읽어
   서류 작성 칸 이름으로 옮긴 초안을 돌려줍니다. 칸에 넣는 것은 부르는 쪽이 합니다.

   - upload(file, url)   파일 하나를 보내고 결과를 받습니다
   - mount(zone, opts)   끌어다 놓기 · 파일 고르기 칸을 붙입니다
   - resultHtml(data)    무엇을 읽었고 무엇이 비었는지 보여 줄 덩어리
   - stash(data)         다른 화면(서류 작성)이 집어 가도록 놓아 둡니다 */
(function () {
  "use strict";

  const { escapeHtml, postForm } = window.Forwardus;

  const ACCEPT = [".pdf", ".png", ".jpg", ".jpeg", ".webp"];
  const MAX_BYTES = 10 * 1024 * 1024;
  // 그림을 읽는 AI 호출은 30초를 넘기기도 합니다. 서버는 90초에 끊습니다.
  const TIMEOUT_MS = 120000;
  const DRAFT_KEY = "forwardus:doc-draft";

  // 보내기 전에 걸러 냅니다. 서버도 같은 것을 다시 봅니다.
  function problem(file) {
    if (!file) return "올릴 파일을 골라 주세요.";
    const name = (file.name || "").toLowerCase();
    if (!ACCEPT.some((suffix) => name.endsWith(suffix))) {
      return "PDF 또는 이미지(PNG·JPG·WEBP) 파일만 올릴 수 있습니다.";
    }
    if (!file.size) return "빈 파일입니다. 내용이 있는 파일을 올려 주세요.";
    if (file.size > MAX_BYTES) return "파일은 10MB까지 올릴 수 있습니다.";
    return "";
  }

  async function upload(file, url) {
    const reason = problem(file);
    if (reason) return { success: false, message: reason };
    const body = new FormData();
    body.append("file", file, file.name);
    return postForm(url, body, TIMEOUT_MS);
  }

  function stash(data) {
    try {
      window.sessionStorage.setItem(DRAFT_KEY, JSON.stringify(data.form));
    } catch (error) {
      /* 저장 공간이 없으면 이 화면에서만 씁니다. */
    }
    if (window.ForwardusHsModal) window.ForwardusHsModal.remember(data.hs_queries || []);
  }

  function resultHtml(data) {
    const summary = (data.summary || []).map((row) =>
      `<div><dt>${escapeHtml(row.label)}</dt><dd>${escapeHtml(row.value)}</dd></div>`).join("");
    const notes = (data.notes || []).length
      ? `<div class="upload_notes"><b>확인해 주세요</b><ul>${data.notes.map((note) =>
          `<li>${escapeHtml(note)}</li>`).join("")}</ul></div>` : "";
    const missing = (data.missing || []).length
      ? `<p class="upload_missing"><b>아직 비어 있는 필수 칸 ${data.missing.length}개</b> · `
        + `${data.missing.map(escapeHtml).join(", ")}</p>`
      : `<p class="upload_missing ok">필수 칸이 모두 찼습니다. 스케줄만 고르면 됩니다.</p>`;
    // HS부호가 없는 품목은 그 자리에서 찾을 수 있게 합니다.
    const hs = (data.hs_queries || []).length
      ? `<div class="upload_hs"><span>HS부호가 없는 품목</span>${data.hs_queries.map((query) =>
          `<button type="button" class="hs_chip" data-hs-open data-hs-query="${escapeHtml(query)}">`
          + `🔎 ${escapeHtml(query)}</button>`).join("")}</div>` : "";
    return `
      <div class="upload_result">
        <p class="upload_title"><b>${escapeHtml(data.document_label || "서류")}</b>에서 칸 `
          + `${Number(data.filled || 0)}개를 읽었습니다.</p>
        ${summary ? `<dl class="upload_summary">${summary}</dl>` : ""}
        ${missing}${notes}${hs}
      </div>`;
  }

  // opts: { url, onStart(file), onResult(data), onError(message) }
  function mount(zone, opts) {
    zone.classList.add("doc_drop");
    zone.innerHTML = `
      <input type="file" accept="${ACCEPT.join(",")}" hidden data-drop-input>
      <span class="doc_drop_icon" aria-hidden="true">📎</span>
      <div class="doc_drop_text">
        <b>B/L · Offer Sheet · 견적서 · Packing List를 여기에 끌어다 놓으세요</b>
        <small>PDF·PNG·JPG · 10MB까지. AI가 읽어 아래 칸을 채웁니다. 올린 파일은 서버에 남기지 않습니다.</small>
      </div>
      <button type="button" class="button small" data-drop-pick>파일 선택</button>
      <p class="doc_drop_status" data-drop-status role="status" hidden></p>`;
    const fileInput = zone.querySelector("[data-drop-input]");
    const pickButton = zone.querySelector("[data-drop-pick]");
    const statusEl = zone.querySelector("[data-drop-status]");
    let busy = false;

    function status(message, kind = "") {
      statusEl.textContent = message;
      statusEl.className = `doc_drop_status ${kind}`.trim();
      statusEl.hidden = !message;
    }

    async function send(files) {
      if (busy || !files || !files.length) return;
      const file = files[0];
      const reason = problem(file);
      if (reason) { status(reason, "bad"); if (opts.onError) opts.onError(reason); return; }

      busy = true;
      zone.classList.add("is_busy");
      pickButton.disabled = true;
      status(`${file.name}을(를) 읽고 있습니다… 그림으로 된 서류는 30초쯤 걸립니다.`
        + (files.length > 1 ? " (여러 개를 놓으셔서 첫 파일만 읽습니다)" : ""));
      if (opts.onStart) opts.onStart(file);

      const response = await upload(file, opts.url);
      busy = false;
      zone.classList.remove("is_busy");
      pickButton.disabled = false;
      fileInput.value = "";

      if (!response.success) {
        status(response.message || "서류를 읽지 못했습니다.", "bad");
        if (opts.onError) opts.onError(response.message);
        return;
      }
      status(`${file.name} · ${response.data.document_label}을(를) 읽었습니다.`, "ok");
      opts.onResult(response.data, file);
    }

    pickButton.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => send(fileInput.files));
    ["dragenter", "dragover"].forEach((type) => zone.addEventListener(type, (event) => {
      event.preventDefault();
      zone.classList.add("is_over");
    }));
    ["dragleave", "dragend"].forEach((type) => zone.addEventListener(type, (event) => {
      if (!zone.contains(event.relatedTarget)) zone.classList.remove("is_over");
    }));
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      zone.classList.remove("is_over");
      send(event.dataTransfer && event.dataTransfer.files);
    });
    return { send };
  }

  window.ForwardusDocUpload = { upload, mount, resultHtml, stash, problem, ACCEPT };
})();
