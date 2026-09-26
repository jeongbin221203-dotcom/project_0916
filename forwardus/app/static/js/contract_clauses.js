/* 계약서 조항 점검 칸 — 무역 상담과 서류 수정 두 화면이 함께 씁니다.

   하는 일
     1. 이 건에 걸리는 조항을 필수·이익·독소로 나눠 보여 줍니다
     2. 계약서 파일을 올리거나 본문을 붙여 넣으면 판정합니다
        (빠진 필수조항 · 들어 있는 독소조항)
     3. 고른 조항의 문안을 파일로 내려받습니다

   지키는 것
     - 올린 파일은 서버에 남기지 않습니다. 읽고 판정만 합니다.
     - 독소조항은 **고르는 것이 아니라 빼는 것**이라 내보내기에서 뺍니다.
       (문안이 아니라 "이런 문장을 지우세요"가 필요한 자리입니다)
     - 어떤 답에도 "법률 자문이 아니다"를 함께 답니다. */
(function () {
  "use strict";

  const MARK = { must: "필수", gain: "이익", toxic: "독소" };
  const TONE = { must: "cc_must", gain: "cc_gain", toxic: "cc_toxic" };

  function esc(text) {
    return window.Forwardus ? window.Forwardus.escapeHtml(text) : String(text == null ? "" : text);
  }

  /* 굵게(**…**)만 살려 둡니다. 조항 설명이 그 표시를 씁니다. */
  function rich(text) {
    return esc(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  }

  function row(item, group) {
    const pickable = group !== "toxic";
    return `
      <li class="cc_row ${item.present ? "is_found" : ""}">
        <label class="cc_head">
          ${pickable ? `<input type="checkbox" data-cc-pick value="${esc(item.key)}">` : ""}
          <span class="cc_tag ${TONE[group]}">${MARK[group]}</span>
          <b>${esc(item.title)}</b>
          ${item.present ? `<span class="cc_found">${group === "toxic" ? "들어 있음" : "있음"}</span>` : ""}
        </label>
        <p class="cc_why">${rich(item.why)}</p>
        <p class="cc_risk">${rich(item.risk)}</p>
        ${item.text_ko ? `<p class="cc_how">${rich(item.text_ko)}</p>` : ""}
        ${item.fix ? `<p class="cc_fix">고치는 법 — ${rich(item.fix)}</p>` : ""}
      </li>`;
  }

  function groupBlock(title, items, group) {
    if (!items || !items.length) return "";
    return `
      <section class="cc_group">
        <h4>${esc(title)} <span class="cc_count">${items.length}</span></h4>
        <ul class="cc_list">${items.map((item) => row(item, group)).join("")}</ul>
      </section>`;
  }

  function mount(host, options) {
    const config = options || {};
    const incoterms = config.incoterms || "";
    host.innerHTML = `
      <div class="cc_panel" data-cc-panel>
        <div class="cc_intro">
          <p class="cc_lead">서류가 다 맞아도 <b>돈을 떼이거나 물리는 자리는 계약서</b>입니다.
            이 건에 필요한 조항을 짚어 드리고, 계약서를 올리시면 빠진 것과 위험한 것을 찾습니다.</p>
          <p class="cc_note" data-cc-note></p>
        </div>
        <form class="cc_upload" data-cc-form>
          <label class="cc_file">
            <span>계약서 파일 (PDF · 사진 · 텍스트)</span>
            <input type="file" name="file" accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.webp">
          </label>
          <details class="cc_paste">
            <summary>파일 대신 본문 붙여 넣기</summary>
            <textarea name="text" rows="5" placeholder="계약서 본문을 붙여 넣으세요"></textarea>
          </details>
          <div class="cc_actions">
            <button class="button primary" type="submit">읽고 판정하기</button>
            <button class="button ghost" type="button" data-cc-export disabled>고른 조항 문안 받기</button>
          </div>
          <p class="cc_status" data-cc-status role="status"></p>
        </form>
        <div class="cc_body" data-cc-body></div>
      </div>`;

    const body = host.querySelector("[data-cc-body]");
    const note = host.querySelector("[data-cc-note]");
    const status = host.querySelector("[data-cc-status]");
    const form = host.querySelector("[data-cc-form]");
    const exportBtn = host.querySelector("[data-cc-export]");

    function refreshExport() {
      const picked = host.querySelectorAll("[data-cc-pick]:checked").length;
      exportBtn.disabled = picked === 0;
      exportBtn.textContent = picked ? `고른 조항 ${picked}개 문안 받기` : "고른 조항 문안 받기";
    }

    host.addEventListener("change", (event) => {
      if (event.target.matches("[data-cc-pick]")) refreshExport();
    });

    function draw(groups, found) {
      body.innerHTML =
        groupBlock(found ? "🔴 지우거나 고쳐야 할 조항" : "🔴 조심할 조항 (독소)",
                   groups.toxic, "toxic")
        + groupBlock(found ? "🟠 빠진 필수조항" : "🟠 있어야 할 조항 (필수)",
                     groups.must, "must")
        + groupBlock("🔵 챙기면 이로운 조항 (이익)", groups.gain, "gain");
      refreshExport();
    }

    async function load() {
      status.textContent = "조항을 불러오는 중입니다…";
      const answer = await window.Forwardus.getJson(
        `${config.clausesUrl}?incoterms=${encodeURIComponent(incoterms)}`);
      status.textContent = "";
      if (!answer.success) { status.textContent = answer.message || "불러오지 못했습니다."; return; }
      note.textContent = `※ ${answer.data.note}`;
      draw(answer.data.groups, false);
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(form);
      data.set("incoterms", incoterms);
      const file = data.get("file");
      const text = String(data.get("text") || "").trim();
      if ((!file || !file.name) && !text) {
        status.textContent = "계약서 파일을 고르거나 본문을 붙여 넣어 주세요.";
        return;
      }
      status.textContent = "읽는 중입니다… (올린 파일은 저장하지 않습니다)";
      let answer;
      try {
        const response = await fetch(config.reviewUrl, { method: "POST", body: data });
        answer = await response.json();
      } catch (error) {
        status.textContent = "읽지 못했습니다. 잠시 뒤 다시 해 주세요.";
        return;
      }
      if (!answer.success) { status.textContent = answer.message || "읽지 못했습니다."; return; }
      const result = answer.data;
      status.textContent =
        `${result.checked.toLocaleString()}자를 읽었습니다. `
        + `독소 ${result.toxic.length}개 · 빠진 필수 ${result.missing.length}개.`;
      draw({ toxic: result.toxic, must: result.missing, gain: result.gain }, true);
    });

    exportBtn.addEventListener("click", async () => {
      const keys = Array.from(host.querySelectorAll("[data-cc-pick]:checked"))
        .map((input) => input.value);
      if (!keys.length) return;
      const response = await fetch(config.exportUrl, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keys }),
      });
      if (!response.ok) { status.textContent = "문안을 만들지 못했습니다."; return; }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "contract-clauses.md";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      status.textContent = `조항 ${keys.length}개 문안을 내려받았습니다.`;
    });

    load();
  }

  window.ForwardusContractClauses = { mount };
})();
