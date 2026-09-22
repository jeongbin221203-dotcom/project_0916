/* 시작 화면. 대화가 중심이고, 칸을 채우는 화면은 사이드바에 있습니다.
   적는 칸 위의 세 단추가 무엇에 대해 이야기할지를 정합니다. */
(function () {
  "use strict";

  const config = window.FORWARDUS_HOME;
  const stage = document.querySelector("[data-home-form]");
  if (!config || !stage) return;

  const { escapeHtml, getJson, postJson } = window.Forwardus;
  // 고래 상담창과 같은 대화를 나눠 씁니다. 다른 화면에 갔다 와도 이어집니다.
  const chat = window.ForwardusChat;
  const SOURCE = "home";

  const input = stage.querySelector("[data-home-input]");
  const chipsBox = stage.querySelector("[data-home-chips]");
  const sendButton = stage.querySelector(".home_send");
  const hintEl = document.querySelector("[data-home-hint]");
  const logEl = document.querySelector("[data-home-log]");
  const centerEl = document.querySelector("[data-home-center]");

  let current = config.actions[0];

  // 나눈 말을 대화 한 줄기에 적습니다. 고래 상담창에도 같이 보입니다.
  function record(role, text, kind = "", extra = null) {
    return chat.append({ role, text, kind, extra, mode: current.key }, SOURCE);
  }

  // 한 번 묻고 나면 인사를 접고 적는 칸을 화면 아래에 붙입니다.
  // 답이 쌓이는 동안에도 다시 묻는 자리가 늘 같은 곳에 있어야 합니다.
  // 대화하는 동안에는 고래 상담창을 숨깁니다. 같은 대화가 가운데에 크게
  // 떠 있어 두 벌로 보일 이유가 없습니다. 첫 화면으로 돌아오면 다시 보입니다.
  function startTalking() {
    centerEl.classList.add("talking");
    document.body.classList.add("home_talking");
  }

  /* ----- 무엇에 대해 이야기할지 ----- */
  function showAction(action, { greet = false } = {}) {
    current = action;
    input.placeholder = action.placeholder;
    hintEl.innerHTML = action.hint;
    // 칸을 채우는 단추는 성격이 달라 맨 앞에 따로 둡니다.
    const fill = action.fill_label
      ? `<button type="button" class="chip_fill" data-home-fill>${escapeHtml(action.fill_label)}</button>`
      : "";
    // 빈 서식 PDF를 받는 칩. 대화를 시작하는 칩과 성격이 달라 모양도 다릅니다.
    const files = (action.downloads || [])
      .map((row) => `<button type="button" class="chip_file"`
        + ` data-home-file="${escapeHtml(row.kind)}">${escapeHtml(row.label)}</button>`)
      .join("");
    chipsBox.innerHTML = fill + (action.examples || [])
      .map((text) => `<button type="button" data-home-chip>${escapeHtml(text)}</button>`)
      .join("") + files;
    if (logEl.children.length) logEl.hidden = false;

    // 사람이 무엇부터 적어야 할지 모르는 것이 가장 흔한 막힘입니다.
    // 단추를 누르면 우리가 먼저 말을 겁니다.
    if (greet && action.opener) greetFor(action);
    resize();
  }

  // 인사는 지금 고른 탭의 것 하나만 보입니다. 다른 탭으로 넘어가면 앞 탭의
  // 인사를 지우고 새 인사를 맨 아래에 둡니다. 적은 말이 있든 없든 같습니다.
  function greetFor(action) {
    const last = logEl.lastElementChild;
    // 같은 탭을 다시 눌렀고 그 인사가 아직 맨 아래에 있으면 그대로 둡니다.
    if (last && last.dataset.greeting === action.key) return;
    logEl.querySelectorAll("[data-greeting]").forEach((row) => row.remove());
    say("bot", action.opener).dataset.greeting = action.key;
    chat.replaceGreeting({ text: action.opener, mode: action.key }, SOURCE);
  }

  document.querySelectorAll("[data-home-action]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-home-action]").forEach((other) => {
        const on = other === button;
        other.classList.toggle("active", on);
        other.setAttribute("aria-selected", on ? "true" : "false");
      });
      const picked = config.actions.find((a) => a.key === button.dataset.homeAction);
      showAction(picked || config.actions[0], { greet: true });
      input.focus();
    });
  });

  // 눌렀다는 것이 보여야 합니다. 값은 적는 칸으로 들어가는데 단추 쪽에
  // 아무 변화가 없으면, 눌린 건지 아닌지 몰라 또 누르게 됩니다.
  function flash(button) {
    button.classList.add("just_used");
    setTimeout(() => button.classList.remove("just_used"), 700);
  }

  chipsBox.addEventListener("click", (event) => {
    const fill = event.target.closest("[data-home-fill]");
    if (fill) { flash(fill); fillDocDraft(); return; }

    const file = event.target.closest("[data-home-file]");
    if (file) {
      flash(file);
      // 빈 서식 파일은 아직 안 붙였습니다. 없는 것을 있는 척하지 않습니다.
      say("bot", "빈 서식 PDF는 아직 준비 중입니다.\n\n"
        + `지금은 **${file.textContent.replace("(PDF)", "")}**를 대화로 만들어 `
        + "PDF로 받으실 수 있습니다. 아래에 적어 보내 주세요.");
      input.value = file.textContent.replace("(PDF)", "").trim() + " 만들어줘";
      resize();
      input.focus();
      return;
    }

    const chip = event.target.closest("[data-home-chip]");
    if (!chip) return;
    flash(chip);
    input.value = chip.textContent;
    resize();
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  });

  /* ----- 적은 글로 서류 초안 채우기 ----- */
  async function fillDocDraft() {
    const text = input.value.trim();
    if (text.length < 5) {
      say("bad", "보내실 화물을 적어 주세요. 어디서 어디로, 무엇을 몇 개 보내는지요.");
      return;
    }
    const button = chipsBox.querySelector("[data-home-fill]");
    const label = button.textContent;
    button.disabled = true;
    button.textContent = "읽는 중…";
    const waiting = say("bot wait", "적으신 내용을 읽고 있습니다…");

    const response = await postJson(config.intakeUrl, { text }, 60000);
    button.disabled = false;
    button.textContent = label;
    waiting.remove();

    if (!response.success) {
      say("bad", response.message);
      return;
    }
    // 서류 작성 화면이 집어 갈 수 있게 놓아 둡니다. 탭을 새로 열면
    // 사라지는 것이 맞습니다 — 확정은 그 화면에서 사람이 합니다.
    try {
      window.sessionStorage.setItem("forwardus:doc-draft",
                                    JSON.stringify(response.data.form));
    } catch (error) {
      /* 저장 공간이 없으면 링크만 드립니다. */
    }

    // 무엇을 채웠고 무엇이 비었는지 말해 줍니다. 조용히 채우면 확인을 안 합니다.
    const filled = response.data.filled.length;
    const notes = response.data.notes.length
      ? "\n\n확인해 주세요\n" + response.data.notes.map((note) => `- ${note}`).join("\n")
      : "";
    // 화면을 대신 넘기지 않습니다. 넘기면 이 안내가 가려져서, 무엇이 확인이
    // 필요한 값인지 모른 채 그대로 서류가 만들어집니다.
    say("bot", `칸 ${filled}개를 채웠습니다.` + notes);
    record("assistant", `칸 ${filled}개를 채웠습니다.` + notes, "note");
    const link = say("bot", "");
    link.innerHTML = `<a class="button primary" href="${escapeHtml(config.docFormUrl)}">`
      + "서류 작성 화면에서 확인하기 →</a>";
    input.value = "";
    resize();
  }

  /* ----- 적는 칸이 내용만큼 늘어나게 ----- */
  function resize() {
    input.style.height = "auto";
    input.style.height = `${input.scrollHeight}px`;
  }
  input.addEventListener("input", resize);

  // Enter로 보내고, Shift+Enter로 줄을 바꿉니다.
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      stage.requestSubmit();
    }
  });

  /* ----- 답변 그리기 -----
     서식을 살리는 방법은 고래 상담창과 같아야 해서 chat_store.js에 둡니다. */
  const renderAnswer = (text) => chat.render(text);

  function say(kind, text, { restoring = false } = {}) {
    const row = document.createElement("div");
    row.className = `home_msg ${kind}`;
    if (kind === "bot") {
      row.innerHTML = renderAnswer(text);
    } else {
      row.textContent = text;
    }
    logEl.hidden = false;
    logEl.appendChild(row);
    startTalking();

    // 물어본 말은 위로 올려 붙입니다. 답이 그 아래로 이어서 나오니
    // 눈이 한 자리에 머뭅니다. 매번 맨 아래로 끌어내리면 글이 길 때
    // 답의 끝부터 보이게 되어 읽을 자리를 찾느라 화면이 튑니다.
    if (kind === "me" && !restoring) {
      row.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    return row;
  }

  async function askSupport(question) {
    // 앞 대화에는 고래 상담창에서 나눈 말도 들어 있습니다.
    const history = chat.history();
    say("me", question);
    record("user", question);
    const waiting = say("bot wait", "답을 찾고 있습니다…");
    sendButton.disabled = true;

    const response = await postJson(config.chatUrl, { question, history });
    sendButton.disabled = false;
    waiting.remove();

    if (!response.success) {
      say("bad", response.message);
      return;
    }
    const answer = response.data.answer;
    say("bot", answer);
    record("assistant", answer);
  }

  /* ----- 서류 만들기 -----
     "패킹리스트만 만들어줘" 같은 말을 받으면, 그 서식이 요구하는 칸만
     되묻고 채워지는 대로 초안을 그려 보여 줍니다. */
  // 모은 값은 대화와 함께 기억합니다. 다른 화면에 갔다 와도 이어서 채웁니다.
  let docDraft = chat.get("docDraft") || {};

  async function askAgent(message) {
    say("me", message);
    record("user", message);
    const waiting = say("bot wait", "보고 있습니다…");
    sendButton.disabled = true;
    sendButton.classList.add("working");

    const response = await postJson(config.agentUrl, { message, draft: docDraft }, 90000);
    sendButton.disabled = false;
    sendButton.classList.remove("working");
    waiting.remove();

    if (!response.success) {
      say("bad", response.message);
      return;
    }
    const data = response.data;
    docDraft = data.draft || docDraft;
    chat.set("docDraft", docDraft);
    say("bot", data.reply);
    record("assistant", data.reply);
    if (data.fields) {
      showFields(data.fields);
      record("assistant", "서류에 들어갈 칸 목록을 보여 드렸습니다. "
        + "시작 화면의 **서류 작성** 탭에서 칸을 눌러 채울 수 있습니다.", "note",
        { fields: data.fields });
    }

    // AI가 확인 못 한 값이 있으면 같이 알려 줍니다. 조용히 넘어가면
    // 틀린 값이 그대로 서류가 됩니다.
    (data.notes || []).forEach((note) => {
      say("bad", note);
      record("assistant", note, "warn");
    });

    if (data.documents) {
      // 적으신 내용을 임시로 둡니다. 운송 일정을 넣는 화면이 이걸 집어 가
      // 출항일·선박명까지 채운 정식 서류로 만듭니다.
      // 탭을 새로 열면 사라지는 것이 맞습니다 — 아직 확정이 아닙니다.
      try {
        const fields = { ...docDraft };
        delete fields.items;
        delete fields.kind;
        window.sessionStorage.setItem("forwardus:doc-draft",
          JSON.stringify({ fields, items: docDraft.items || [] }));
      } catch (error) {
        /* 저장 공간이 없으면 링크만 드립니다. */
      }
      data.documents.forEach(showDraft);
      showNextStep();
      // 초안 그림은 커서 대화에 담지 않습니다. 무엇을 만들었는지만 적어 둡니다.
      record("assistant", data.documents.map((doc) => `📄 **${doc.title}** 초안을 만들었습니다.`)
        .join("\n") + "\n\n운송 일정을 넣으면 정식 서류로 만들 수 있습니다.", "note",
        { nextStep: true });
    }
  }

  // 칸 목록을 세 열로 보여 줍니다. 구분 · 서식의 영문 칸 이름 · 기재 내용.
  // 영문 칸 이름을 같이 두면 종이 서식과 화면을 나란히 놓고 볼 수 있습니다.
  function showFields(fields) {
    const row = say("bot", "");
    let lastGroup = "";
    const body = fields.map((field) => {
      const group = field.group === lastGroup ? "" : field.group;
      lastGroup = field.group;
      const must = field.required ? '<i class="need">*</i>' : "";
      const plan = field.from_planning
        ? '<b class="need">운송 계획에서 작성합니다</b><br>' : "";
      const done = field.value
        ? `<span class="field_done">적으신 것: ${escapeHtml(field.value)}</span>` : "";
      // 품목은 한 줄로 못 받아서 틀을 넣지 않습니다.
      const pick = field.field === "items" ? "" : ` data-pick="${escapeHtml(field.en)}"`;
      return `<tr${group ? ' class="group_top"' : ""}${pick}>
          <th>${escapeHtml(group)}</th>
          <td class="field_en">${escapeHtml(field.en)}${must}
            <small>${escapeHtml(field.ko)}</small></td>
          <td>${plan}${escapeHtml(field.note)}${done}</td>
        </tr>`;
    }).join("");
    row.innerHTML = `
      <div class="field_head">
        <p class="muted small">줄을 누르면 아래 적는 칸에 <b>칸 이름:</b> 이 들어갑니다.
          그 뒤에 값을 적어 보내 주세요.</p>
        <button type="button" class="button small" data-pick-all>빈 칸 전부 넣기</button>
      </div>
      <table class="field_table">
        <thead><tr><th>구분</th><th>주요 필드명 (영문)</th><th>기재 내용 및 주의사항</th></tr></thead>
        <tbody>${body}</tbody>
      </table>`;

    row.addEventListener("click", (event) => {
      if (event.target.closest("[data-pick-all]")) {
        // 아직 안 적은 칸만 넣습니다. 이미 적은 것을 또 물으면 지웁니다.
        addTemplate(fields.filter((f) => f.field !== "items" && !f.value), true);
        return;
      }
      const line = event.target.closest("[data-pick]");
      if (line) addTemplate([{ en: line.dataset.pick, group: "" }]);
    });
  }

  // 이 줄 아래는 지금 안 적어도 됩니다. 운송 일정을 넣으면 그때 채워지고,
  // 만든 서류에서 고칠 수도 있습니다. 한 번에 다 적으라고 하면 부담이 큽니다.
  const LATER_LINE = "----------하단은 운송계획 입력 후 뒤에서 수정 가능합니다----------";

  // 적는 칸에 "칸 이름: " 줄을 붙입니다. 이미 있는 줄은 다시 넣지 않습니다.
  function addTemplate(rows, withDivider = false) {
    const have = new Set(input.value.split("\n")
      .map((line) => line.split(":")[0].trim().toLowerCase()));
    const fresh = rows.filter((row) => !have.has(row.en.toLowerCase()));
    if (!fresh.length) { input.focus(); return; }

    const lines = [];
    let dividerDone = false;
    fresh.forEach((row) => {
      // 보내는 쪽·받는 쪽이 먼저고, 나머지는 구분선 아래로 내립니다.
      if (withDivider && !dividerDone && row.group !== "기본 정보") {
        dividerDone = true;
        if (lines.length) lines.push(LATER_LINE);
      }
      lines.push(`${row.en}: `);
    });

    const before = input.value.replace(/\s+$/, "");
    input.value = (before ? before + "\n" : "") + lines.join("\n");
    resize();
    input.focus();
    // 마지막 줄 끝으로 커서를 보냅니다. 바로 이어 적을 수 있게.
    input.setSelectionRange(input.value.length, input.value.length);
  }

  function showDraft(doc) {
    const row = say("bot", "");
    row.innerHTML = `
      <p class="draft_name">${escapeHtml(doc.title)}</p>
      <figure class="draft_sheet">
        <img src="${doc.preview}" alt="${escapeHtml(doc.title)} 초안">
      </figure>
      <div class="draft_actions">
        <button type="button" class="button primary" data-draft-pdf>PDF로 받기</button>
      </div>`;
    row.querySelector("[data-draft-pdf]").addEventListener("click", (event) =>
      downloadPdf(event.currentTarget, doc));
  }

  // 다음에 할 일을 한 번만 보여 줍니다. 서류마다 붙이면 같은 단추가 겹칩니다.
  function showNextStep() {
    const row = say("bot", "");
    row.innerHTML = `
      <div class="draft_actions">
        <a class="button primary" href="${escapeHtml(config.docFormUrl)}">
          운송 일정 넣고 정식 서류 만들기 →</a>
      </div>`;
  }

  async function downloadPdf(button, data) {
    button.disabled = true;
    const label = button.textContent;
    button.textContent = "만드는 중…";
    try {
      const response = await fetch(data.file_url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ draft: docDraft }),
      });
      if (!response.ok) throw new Error(String(response.status));
      // 서버에 파일을 남기지 않습니다. 받은 그대로 저장창을 띄웁니다.
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = (data.kind || "document") + "_draft.pdf";
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      say("bad", "PDF를 만들지 못했습니다. 다시 눌러 주세요.");
    }
    button.disabled = false;
    button.textContent = label;
  }

  // 오퍼시트 올리기(offer_sheet.js)가 같은 대화창에 말을 붙일 수 있게 엽니다.
  window.ForwardusHome = { say, renderAnswer, startTalking };

  /* ----- 보내기 ----- */
  stage.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) {
      input.focus();
      return;
    }
    input.value = "";
    resize();
    // 서류 작성에서는 서류를 만드는 창구로, 나머지는 상담으로 보냅니다.
    if (current.key === "documents") askAgent(text);
    else askSupport(text);
  });

  /* ----- 환율 계산기 -----
     송장 금액이 달러인데 원화로 얼마인지는 늘 궁금합니다.
     환율은 펼칠 때 한 번만 받아 둡니다. */
  function setupExchange() {
    const box = document.querySelector("[data-rail-fx]");
    if (!box) return () => {};

    const amountEl = box.querySelector("[data-fx-amount]");
    const fromEl = box.querySelector("[data-fx-from]");
    const toEl = box.querySelector("[data-fx-to]");
    const resultEl = box.querySelector("[data-fx-result]");
    const basisEl = box.querySelector("[data-fx-basis]");
    let rates = null;

    function calculate() {
      const amount = Number(String(amountEl.value).replace(/,/g, ""));
      const from = rates && rates[fromEl.value];
      const to = rates && rates[toEl.value];
      if (!from || !to || !Number.isFinite(amount)) { resultEl.textContent = "—"; return; }
      // rates는 "그 통화 1단위가 몇 원인지"입니다. 원을 거쳐 환산합니다.
      resultEl.textContent = ((amount * from) / to).toLocaleString("ko-KR", {
        maximumFractionDigits: toEl.value === "KRW" ? 0 : 2,
      });
    }

    [amountEl, fromEl, toEl].forEach((el) => {
      el.addEventListener("input", calculate);
      el.addEventListener("change", calculate);
    });
    box.querySelector("[data-fx-swap]").addEventListener("click", () => {
      [fromEl.value, toEl.value] = [toEl.value, fromEl.value];
      calculate();
    });

    return async function load() {
      if (rates) return;
      const response = await getJson(config.ratesUrl);
      if (!response.success) {
        basisEl.textContent = "환율을 받지 못했습니다. 잠시 뒤에 다시 열어 주세요.";
        basisEl.classList.add("is_mock");
        return;
      }
      rates = response.data;
      fillCurrencies();
      // 무슨 환율로 계산했는지 함께 보여 줍니다. 관세청이 멈추면 임시 환율로
      // 떨어지는데, 그걸 모르고 쓰면 금액이 틀립니다.
      basisEl.textContent = response.basis;
      basisEl.classList.toggle("is_mock", response.source !== "api");
      calculate();
    };

    // 고를 수 있는 통화는 실제로 환율을 받은 것뿐입니다. 없는 통화를
    // 목록에 두면 골랐을 때 계산이 안 됩니다.
    function fillCurrencies() {
      const major = ["USD", "KRW", "EUR", "JPY", "CNY"];
      const codes = Object.keys(rates).sort((a, b) => {
        const rank = (code) => (major.indexOf(code) + 1 || 99);
        return rank(a) - rank(b) || a.localeCompare(b);
      });
      [fromEl, toEl].forEach((select) => {
        const keep = select.value;
        select.innerHTML = codes.map((code) => `<option value="${code}">${code}</option>`).join("");
        select.value = codes.includes(keep) ? keep : codes[0];
      });
    }
  }

  const loadRates = setupExchange();

  /* ----- 왼쪽 줄에서 옆으로 펼치는 것들 ----- */
  // 내용이 있는 항목(최근 Shipment, 환율)은 좁은 줄에 넣을 수 없어 옆으로 펼칩니다.
  const flyouts = Array.from(document.querySelectorAll("[data-rail-flyout]"));

  function setFlyout(box, open) {
    box.querySelector(".rail_flyout").hidden = !open;
    box.querySelector("button").setAttribute("aria-expanded", open ? "true" : "false");
  }

  flyouts.forEach((box) => {
    box.querySelector("button").addEventListener("click", (event) => {
      event.stopPropagation();
      const opening = box.querySelector(".rail_flyout").hidden;
      flyouts.forEach((other) => setFlyout(other, other === box && opening));
      if (opening && box.dataset.railFx !== undefined) loadRates();
    });
  });
  // 바깥을 누르거나 Esc를 누르면 닫습니다.
  document.addEventListener("click", (event) => {
    flyouts.forEach((box) => { if (!box.contains(event.target)) setFlyout(box, false); });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") flyouts.forEach((box) => setFlyout(box, false));
  });

  /* ----- 나눈 대화 다시 그리기 -----
     다른 화면에 갔다 오거나 고래 상담창에서 말을 걸었어도 여기서 이어집니다. */
  function showStored(message, { restoring = false } = {}) {
    if (message.role === "user") {
      say("me", message.text, { restoring });
      return;
    }
    if (message.kind === "warn") { say("bad", message.text); return; }
    if (message.kind === "greeting") { say("bot", message.text).dataset.greeting = message.mode; return; }
    if (message.extra && message.extra.fields) { showFields(message.extra.fields); return; }
    say("bot", message.text);
    if (message.extra && message.extra.nextStep) showNextStep();
  }

  function restore() {
    const messages = chat.messages();
    if (!messages.length) return;
    // 마지막으로 이야기하던 탭을 다시 골라 둡니다.
    const lastMode = [...messages].reverse().map((m) => m.mode)
      .find((mode) => config.actions.some((a) => a.key === mode));
    if (lastMode) {
      current = config.actions.find((a) => a.key === lastMode);
      document.querySelectorAll("[data-home-action]").forEach((button) => {
        const on = button.dataset.homeAction === lastMode;
        button.classList.toggle("active", on);
        button.setAttribute("aria-selected", on ? "true" : "false");
      });
    }
    messages.forEach((message) => showStored(message, { restoring: true }));
    // 마지막 말이 보이게 내려 둡니다.
    logEl.lastElementChild.scrollIntoView({ block: "end" });
  }

  chat.subscribe((event) => {
    if (event.source === SOURCE) return;
    if (event.type === "clear") {
      // 고래 상담창에서 새 대화를 시작했습니다. 여기도 처음으로 돌립니다.
      logEl.innerHTML = "";
      logEl.hidden = true;
      centerEl.classList.remove("talking");
      document.body.classList.remove("home_talking");
      docDraft = {};
      return;
    }
    if (event.type !== "append") return;
    showStored(event.message);
  });

  restore();
  showAction(current);
})();
