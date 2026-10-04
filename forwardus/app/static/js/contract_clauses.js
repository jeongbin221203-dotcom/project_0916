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

  // weak — 적혀 있으나 미정·부정·불리·무력인 필수·이익조항 (2026-10-02)
  const MARK = { must: "필수", gain: "이익", toxic: "독소", weak: "보완" };
  const TONE = { must: "cc_must", gain: "cc_gain", toxic: "cc_toxic", weak: "cc_weak" };

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
          ${item.status === "weak" ? `<span class="cc_weak_tag">적혀 있으나 부족</span>` : ""}
        </label>
        ${item.status === "weak" && item.reason ? `<p class="cc_reason">${rich(item.reason)}</p>` : ""}
        ${item.evidence ? `<blockquote class="cc_evidence">근거 — “${esc(item.evidence)}”</blockquote>` : ""}
        ${item.maybe ? `<blockquote class="cc_evidence cc_maybe">규칙은 못 찾았지만 이 문장일 수 있습니다 — “${esc(item.maybe)}”</blockquote>` : ""}
        <p class="cc_why">${rich(item.why)}</p>
        <p class="cc_risk">${rich(item.risk)}</p>
        ${item.text_ko ? (group === "toxic"
          // 독소의 text_ko 는 '찾는 법'(탐지 낱말)이라 일반 이용자에겐 어렵습니다 — 접어 둡니다.
          ? `<details class="cc_more"><summary>계약서에서 이렇게 보입니다</summary><p class="cc_how">${rich(item.text_ko)}</p></details>`
          : `<p class="cc_how">${rich(item.text_ko)}</p>`) : ""}
        ${item.fix ? `<p class="cc_fix">고치는 법 — ${rich(item.fix)}</p>` : ""}
      </li>`;
  }

  /* 규칙이 주제째 놓친 조항 — 주제 분류기가 고른 것. 판정이 아니라 "직접 보세요"입니다. */
  function checkBlock(items) {
    if (!items || !items.length) return "";
    return `
      <section class="cc_group">
        <h4>⚪ 규칙이 판정하지 못한 조항 (직접 확인) <span class="cc_count">${items.length}</span></h4>
        <ul class="cc_list">${items.map((item) => `
          <li class="cc_row">
            <span class="cc_tag cc_check">확인</span> <b>${esc(item.title)}</b> 조항으로 보입니다
            ${item.label ? `<span class="cc_stance cc_${esc(item.stance || "unclear")}">${esc(item.label)}</span>` : ""}
            ${item.why ? `<p class="cc_why">수출자 입장 — ${esc(item.why)}</p>` : ""}
            <blockquote class="cc_evidence">“${esc(item.sentence)}”</blockquote>
          </li>`).join("")}</ul>
      </section>`;
  }

  function groupBlock(title, items, group, folded) {
    if (!items || !items.length) return "";
    return `
      <section class="cc_group">
        <h4>${esc(title)} <span class="cc_count">${items.length}</span></h4>
        ${group === "toxic" ? toxicLists(items, folded) : `<ul class="cc_list">${items.map((item) => row(item, group)).join("")}</ul>`}
      </section>`;
  }

  // 독소조항은 위험 종류 8묶음(① 대금 … ⑧ 제재)으로 나눕니다. 서버가 묶음 순서로
  // 보내므로 바뀌는 자리마다 소제목만 끼웁니다. (2026-10-03)
  // 올리기 전 점검표에서는 묶음을 **접어** 둡니다 — 55개를 펼치면 휴대폰에서 고를 수
  // 있는 첫 칸이 16,000px 아래였습니다(사용성 점검 2026-10-04).
  function toxicLists(items, folded) {
    const parts = [];
    items.forEach((item) => {
      const label = item.group_label || "";
      const last = parts[parts.length - 1];
      if (!last || last.label !== label) parts.push({ label, items: [] });
      parts[parts.length - 1].items.push(item);
    });
    return parts.map((part) => `
        <details class="cc_fold" ${folded ? "" : "open"}>
          <summary class="cc_sub">${esc(part.label || "기타")} <span class="cc_count">${part.items.length}</span></summary>
          <ul class="cc_list">${part.items.map((item) => row(item, "toxic")).join("")}</ul>
        </details>`).join("");
  }

  /* 판정에서 '있다'고 본 필수조항 — 다 갖춘 계약서에도 그 말이 있어야 안심합니다. */
  function okBlock(items) {
    if (!items || !items.length) return "";
    return `
      <section class="cc_group">
        <details class="cc_fold">
          <summary><h4 class="cc_inline">✅ 확인된 필수조항 <span class="cc_count">${items.length}</span></h4></summary>
          <ul class="cc_list">${items.map((item) => `
            <li class="cc_row"><span class="cc_tag cc_must">필수</span> <b>${esc(item.title)}</b>
              ${item.evidence ? `<blockquote class="cc_evidence">근거 — “${esc(item.evidence)}”</blockquote>` : ""}</li>`).join("")}</ul>
        </details>
      </section>`;
  }

  function mount(host, options) {
    const config = options || {};
    let incoterms = config.incoterms || "";
    // 도착국(ISO 2자리). 있으면 그 나라에 흔한 독소조항이 앞으로 옵니다.
    let country = config.country || "";
    // 홈 화면 창은 건이 없어 인코텀즈·도착국을 모릅니다 — 고르게 합니다. 그러지 않으면
    // CIF 건인데 보험이 필수로 안 나오고, 도착국 경고도 안 나왔습니다(사용성 점검 2026-10-04).
    const TERMS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"];
    const dealFields = config.askDeal ? `
          <div class="cc_deal">
            <label>인코텀즈
              <select data-cc-terms><option value="">모름</option>${TERMS.map((t) => `<option>${t}</option>`).join("")}</select>
            </label>
            <label>도착국 (영문 2자리, 예: US · CN · AE)
              <input data-cc-country maxlength="2" autocomplete="off" placeholder="모름">
            </label>
          </div>` : "";
    host.innerHTML = `
      <div class="cc_panel" data-cc-panel>
        <div class="cc_intro">
          <p class="cc_lead">서류가 다 맞아도 <b>돈을 떼이거나 물리는 자리는 계약서</b>입니다.
            이 건에 필요한 조항을 짚어 드리고, 계약서를 올리시면 빠진 것과 위험한 것을 찾습니다.</p>
          <p class="cc_note" data-cc-note></p>
        </div>
        <form class="cc_upload" data-cc-form>${dealFields}
          <label class="cc_file">
            <span>계약서 파일 (PDF · Word · 사진 · 텍스트, 20MB까지)</span>
            <input type="file" name="file" accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp">
          </label>
          <details class="cc_paste">
            <summary>파일 대신 본문 붙여 넣기</summary>
            <textarea name="text" rows="5" placeholder="계약서 본문을 붙여 넣으세요"></textarea>
          </details>
          <div class="cc_actions">
            <button class="button primary" type="submit" data-cc-submit>읽고 판정하기</button>
            <button class="button ghost" type="button" data-cc-export="docx" disabled>Word로 받기</button>
            <button class="button ghost" type="button" data-cc-export="txt" disabled>텍스트로 받기</button>
          </div>
          <p class="cc_hint" data-cc-hint>아래 목록에서 넣을 조항을 체크하면 문안을 Word·텍스트로 받을 수 있습니다.</p>
          <p class="cc_status" data-cc-status role="status"></p>
        </form>
        <div class="cc_body" data-cc-body></div>
      </div>`;

    const body = host.querySelector("[data-cc-body]");
    const note = host.querySelector("[data-cc-note]");
    const status = host.querySelector("[data-cc-status]");
    const form = host.querySelector("[data-cc-form]");
    // .md 는 Windows 에서 열 프로그램이 없어 Word·평문 둘로 냅니다. (2026-10-03)
    const exportBtns = Array.from(host.querySelectorAll("[data-cc-export]"));
    const EXPORT_LABEL = { docx: "Word로 받기", txt: "텍스트로 받기" };

    const hint = host.querySelector("[data-cc-hint]");
    const submitBtn = host.querySelector("[data-cc-submit]");
    const paste = host.querySelector(".cc_paste");
    let judged = false;   // 판정 결과가 떠 있는가 — 인코텀즈를 바꿔도 결과를 지우지 않습니다.

    function picked() {
      return Array.from(host.querySelectorAll("[data-cc-pick]:checked")).map((input) => input.value);
    }

    function refreshExport() {
      const count = picked().length;
      exportBtns.forEach((btn) => {
        const label = EXPORT_LABEL[btn.dataset.ccExport];
        btn.disabled = count === 0;
        btn.textContent = count ? `고른 조항 ${count}개 ${label}` : label;
      });
      // 단추가 왜 막혀 있는지 알려 줍니다(사용성 점검 2026-10-04).
      hint.hidden = count > 0;
    }

    host.addEventListener("change", (event) => {
      if (event.target.matches("[data-cc-pick]")) refreshExport();
    });

    function draw(groups, found) {
      // 다시 그려도 **고른 조항은 그대로** — 판정하기를 누르면 다 풀렸습니다.
      const keep = new Set(picked());
      const side = groups.side ? `<p class="cc_side">우리 쪽(매도인·수출자)을 <b>${esc(groups.side.label)} — ${esc(groups.side.name)}</b>,
            상대(매수인)를 <b>${esc(groups.side.other_label)} — ${esc(groups.side.other_name)}</b> 로 읽었습니다.
            반대라면 판정도 반대가 됩니다.</p>` : "";
      body.innerHTML = side + (found
        // 판정 뒤: 위험한 것부터, 직접 확인할 것은 독소 바로 아래, 다 갖춘 필수는 접어서.
        ? groupBlock("🔴 지우거나 고쳐야 할 조항", groups.toxic, "toxic", false)
          + checkBlock(groups.check)
          + groupBlock("🟡 적혀 있으나 제 구실을 못 하는 조항", groups.weak, "weak")
          + groupBlock("🟠 빠진 필수조항", groups.must, "must")
          + okBlock(groups.ok)
          + groupBlock("🔵 챙기면 이로운 조항 (이익)", groups.gain, "gain")
        // 올리기 전: 고를 수 있는 필수·이익을 위로, 독소 55개는 묶음째 접어서.
        : groupBlock("🟠 있어야 할 조항 (필수)", groups.must, "must")
          + groupBlock("🔵 챙기면 이로운 조항 (이익)", groups.gain, "gain")
          + groupBlock("🔴 조심할 조항 (독소) — 묶음을 눌러 펼치세요", groups.toxic, "toxic", true));
      host.querySelectorAll("[data-cc-pick]").forEach((input) => {
        input.checked = keep.has(input.value);
      });
      refreshExport();
    }

    async function load() {
      status.textContent = "조항을 불러오는 중입니다…";
      const answer = await window.Forwardus.getJson(
        `${config.clausesUrl}?incoterms=${encodeURIComponent(incoterms)}`
        + (country ? `&country=${encodeURIComponent(country)}` : ""));
      status.textContent = "";
      if (!answer.success) { status.textContent = answer.message || "불러오지 못했습니다."; return; }
      note.textContent = `※ ${answer.data.note}`;
      draw(answer.data.groups, false);
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(form);
      data.set("incoterms", incoterms);
      if (country) data.set("country", country);
      const file = data.get("file");
      const text = String(data.get("text") || "").trim();
      if ((!file || !file.name) && !text) {
        status.textContent = "계약서 파일을 고르거나 본문을 붙여 넣어 주세요.";
        return;
      }
      // 파일과 붙여 넣은 글이 함께 있으면 서버는 파일을 읽습니다 — 말없이 버리지 않게 알립니다.
      const both = file && file.name && text;
      status.textContent = "읽는 중입니다… (올린 파일은 저장하지 않습니다)";
      // 판정 중에는 다시 누르지 못하게 — 긴 계약서는 몇 초씩 걸립니다.
      submitBtn.disabled = true;
      form.setAttribute("aria-busy", "true");
      let answer;
      try {
        const response = await fetch(config.reviewUrl, { method: "POST", body: data });
        answer = await response.json();
      } catch (error) {
        answer = { success: false, message: "읽지 못했습니다. 잠시 뒤 다시 해 주세요." };
      } finally {
        submitBtn.disabled = false;
        form.removeAttribute("aria-busy");
      }
      if (!answer.success) {
        // 앞서 본 계약서의 결과가 남아 있으면 새 파일의 결과처럼 보입니다 — 비웁니다.
        body.innerHTML = "";
        judged = false;
        refreshExport();
        status.textContent = answer.message || "읽지 못했습니다.";
        return;
      }
      const result = answer.data;
      status.textContent =
        (both ? "파일을 읽었습니다(붙여 넣은 글은 쓰지 않았습니다). " : "")
        + (result.truncated
          ? `계약서가 길어 앞 ${result.checked.toLocaleString()}자만 봤습니다 — 뒷부분은 나눠 올려 주세요. `
          : `${result.checked.toLocaleString()}자를 읽었습니다. `)
        + `독소 ${result.toxic.length}개 · 직접 확인 ${(result.check || []).length}개 · `
        + `보완 ${(result.weak || []).length}개 · 빠진 필수 ${result.missing.length}개.`;
      draw({ toxic: result.toxic, weak: result.weak || [], must: result.missing,
             gain: result.gain, side: result.our_side, check: result.check || [],
             ok: result.ok_must || [] }, true);
      judged = true;
      if (paste) paste.open = false;
      // 결과로 갑니다 — 휴대폰에서 결과가 첫 화면 아래라 안 보였습니다.
      body.scrollIntoView({ behavior: "smooth", block: "start" });
    });

    async function download(format) {
      const keys = picked();
      if (!keys.length) return;
      try {
        const response = await fetch(config.exportUrl, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ keys, format }),
        });
        if (!response.ok) {
          // 서버가 왜 못 만들었는지 적어 보내면 그 말을 그대로 보여 줍니다.
          let message = "문안을 만들지 못했습니다.";
          try { message = (await response.json()).message || message; } catch (error) { /* 글이 아님 */ }
          status.textContent = message;
          return;
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        const today = new Date().toISOString().slice(0, 10).replace(/-/g, "");
        link.href = url;
        // 날짜를 붙여, 여러 번 받아도 (1)·(2) 가 붙지 않고 언제 받은 것인지 알 수 있게.
        link.download = `계약서-조항-문안-${today}.${format}`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        status.textContent = `조항 ${keys.length}개 문안을 내려받았습니다.`;
      } catch (error) {
        status.textContent = "문안을 받지 못했습니다. 연결을 확인하고 다시 눌러 주세요.";
      }
    }

    exportBtns.forEach((btn) => {
      btn.addEventListener("click", () => download(btn.dataset.ccExport));
    });

    // 인코텀즈·도착국을 바꾸면 점검표를 다시 받습니다(판정 결과가 있으면 그대로 둡니다 —
    // 다음 '판정하기'부터 새 값으로 봅니다).
    const termsInput = host.querySelector("[data-cc-terms]");
    const countryInput = host.querySelector("[data-cc-country]");
    if (termsInput) {
      termsInput.addEventListener("change", () => { incoterms = termsInput.value; if (!judged) load(); });
    }
    if (countryInput) {
      countryInput.addEventListener("change", () => {
        const code = countryInput.value.trim().toUpperCase();
        countryInput.value = code;
        country = /^[A-Z]{2}$/.test(code) ? code : "";
        if (!judged) load();
      });
    }

    load();
  }

  window.ForwardusContractClauses = { mount };
})();
