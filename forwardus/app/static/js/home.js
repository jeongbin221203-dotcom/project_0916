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
  // 서류 작성 화면으로 넘기는 초안. 회원마다 따로 둡니다. (base.js ForwardusStore)
  const DOC_DRAFT_KEY = window.ForwardusStore.key("forwardus:doc-draft");

  const input = stage.querySelector("[data-home-input]");
  const chipsBox = stage.querySelector("[data-home-chips]");
  const sendButton = stage.querySelector(".home_send");
  const hintEl = document.querySelector("[data-home-hint]");
  const logEl = document.querySelector("[data-home-log]");
  const centerEl = document.querySelector("[data-home-center]");
  const uploadInput = window.ForwardusDocUpload && config.attachUrl
    ? stage.querySelector("[data-home-upload]") : null;
  const plusButton = stage.querySelector("[data-home-plus]");
  const attachTray = stage.querySelector("[data-home-attach]");

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
    if (centerEl.classList.contains("talking")) return;
    centerEl.classList.add("talking");
    document.body.classList.add("home_talking");
    syncComposerSpace();
  }

  /* ----- 아래에 붙은 적는 칸만큼 대화 아래를 비워 두기 -----
     적는 칸 덩어리(탭 줄 + 적는 칸)는 화면 아래에 고정됩니다. 높이가 늘 같지 않아서
     (파일 칩, 여러 줄 입력) 실제 높이를 재어 CSS 변수로 넘깁니다. 고정값을 두면
     덩어리가 커질 때 마지막 답의 출처·각주가 그 뒤로 가려집니다. (home.css의 --composer_h) */
  const composerEl = document.querySelector("[data-home-composer]");
  let composerHeight = 0;

  function atBottom() {
    const doc = document.documentElement;
    return window.innerHeight + window.scrollY >= doc.scrollHeight - 48;
  }

  function syncComposerSpace() {
    if (!composerEl || !centerEl.classList.contains("talking")) return;
    const height = Math.ceil(composerEl.getBoundingClientRect().height);
    if (height === composerHeight) return;
    // 맨 아래를 보고 있었으면 덩어리가 커져도 계속 맨 아래가 보이게 따라 내립니다.
    const follow = composerHeight && atBottom();
    composerHeight = height;
    document.documentElement.style.setProperty("--composer_h", `${height}px`);
    if (follow) window.scrollTo(0, document.documentElement.scrollHeight);
  }

  if (composerEl && "ResizeObserver" in window) {
    new ResizeObserver(syncComposerSpace).observe(composerEl);
  }
  window.addEventListener("resize", syncComposerSpace);

  /* ----- 무엇에 대해 이야기할지 ----- */
  function showAction(action, { greet = false } = {}) {
    current = action;
    setPlaceholder();
    hintEl.innerHTML = action.hint;
    // 칸을 채우는 단추는 성격이 달라 맨 앞에 따로 둡니다.
    // (서류 올리기는 칩이 아니라 적는 칸 왼쪽 아래 + 단추, HS CODE 조회는 탭 줄 오른쪽 끝입니다)
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
    // 탭을 옮기면 예시 줄을 늘 처음부터 보여 줍니다. 앞 탭에서 오른쪽으로 밀어 둔
    // 자리가 남아 있으면, 새 탭의 첫 예시가 왼쪽으로 잘린 채 시작합니다.
    chipsBox.scrollLeft = 0;
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

    /* 앞 탭의 인사말을 지우면 그 높이만큼 아래 글이 위로 딸려 올라갑니다.
       읽던 자리가 사라지는 것처럼 보입니다. 지우기 전후의 문서 높이를 재어
       그 차이만큼 스크롤을 되돌려, 보던 자리가 그대로 있게 합니다. */
    const keepTop = window.scrollY;
    const heightBefore = document.documentElement.scrollHeight;

    logEl.querySelectorAll("[data-greeting]").forEach((row) => row.remove());
    // 탭만 바꾼 것은 답이 아닙니다. 보던 자리를 그대로 두고 인사만 아래에 답니다.
    say("bot", action.opener, { pin: false }).dataset.greeting = action.key;
    chat.replaceGreeting({ text: action.opener, mode: action.key }, SOURCE);

    const shift = document.documentElement.scrollHeight - heightBefore;
    if (shift) window.scrollTo({ top: Math.max(0, keepTop + shift), behavior: "instant" });
  }

  // 탭을 고릅니다. 서류를 올리면 사람이 누르지 않아도 서류 작성으로 넘어갑니다(greet 없이).
  function selectMode(key, { greet = true } = {}) {
    document.querySelectorAll("[data-home-action]").forEach((other) => {
      const on = other.dataset.homeAction === key;
      other.classList.toggle("active", on);
      other.setAttribute("aria-selected", on ? "true" : "false");
    });
    const picked = config.actions.find((a) => a.key === key);
    showAction(picked || config.actions[0], { greet });
  }

  document.querySelectorAll("[data-home-action]").forEach((button) => {
    button.addEventListener("click", () => {
      selectMode(button.dataset.homeAction);
      input.focus();
    });
  });

  // 탭 줄 오른쪽 끝의 HS CODE 조회. 모드를 바꾸지 않고 간편 검색 창만 띄웁니다.
  // 상담이나 올린 서류에서 알게 된 품명이 있으면 그걸로 바로 찾습니다. (hs_modal.js가 기억)
  const hsOpen = document.querySelector("[data-home-hs-open]");
  if (hsOpen && window.ForwardusHsModal) {
    hsOpen.addEventListener("click", () => window.ForwardusHsModal.open({ query: guessHsQuery() }));
  } else if (hsOpen) {
    hsOpen.hidden = true;
  }

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
      // 값이 비어 있는 표준 서식 PDF를 바로 내려받습니다.
      const link = document.createElement("a");
      link.href = config.blankUrl.replace("__KIND__", encodeURIComponent(file.dataset.homeFile));
      link.download = "";
      document.body.appendChild(link);
      link.click();
      link.remove();
      say("note", `**${file.textContent.replace("(PDF)", "").trim()}** 빈 서식을 내려받았습니다. `
        + "값을 채운 서류가 필요하시면 아래에 적어 보내 주세요.");
      return;
    }

    const chip = event.target.closest("[data-home-chip]");
    if (!chip) return;
    flash(chip);
    // 누르면 바로 보냅니다. 적는 칸에 넣어 두고 한 번 더 누르게 하지 않습니다.
    input.value = chip.textContent;
    resize();
    if (sendButton.disabled) {           // 앞 질문에 답하는 중이면 넣어만 둡니다.
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
      return;
    }
    stage.requestSubmit ? stage.requestSubmit()
      : stage.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
  });

  /* ----- 적은 글로 서류 초안 채우기 ----- */
  let lastFilled = 0;          // 방금 몇 칸을 채웠는지. 빈 칸으로 다시 눌렀을 때 씁니다.

  async function fillDocDraft() {
    const text = input.value.trim();
    if (text.length < 5) {
      // 채우고 나면 적는 칸을 비웁니다. 그래서 다시 누르면 빈 칸입니다. 그때
      // "적어 주세요"라고만 하면 방금 한 일이 취소된 줄 압니다.
      if (lastFilled) {
        say("note", `방금 적어 주신 내용으로 **칸 ${lastFilled}개**를 채워 두었습니다. `
          + "위의 **서류 작성 화면에서 확인하기**를 눌러 보세요.\n\n"
          + "더 적으실 것이 있으면 아래에 적고 다시 눌러 주세요. 적은 것만 덧붙입니다.");
        return;
      }
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
      window.sessionStorage.setItem(DOC_DRAFT_KEY,
                                    JSON.stringify(response.data.form));
    } catch (error) {
      /* 저장 공간이 없으면 링크만 드립니다. */
    }

    // 무엇을 채웠고 무엇이 비었는지 말해 줍니다. 조용히 채우면 확인을 안 합니다.
    const rows = response.data.filled || [];
    const filled = rows.length;
    lastFilled = filled;
    // 무엇이 어떤 값으로 들어갔는지 그대로 보여 줍니다. 개수만 알려 주면
    // 사람은 "정말 들어갔나" 싶어 다시 누르고, 빈 칸이라 또 되묻게 됩니다.
    const what = rows.length
      ? "\n\n" + rows.map((row) => `- ${row.label}: **${row.value}**`).join("\n")
      : "";
    const notes = response.data.notes.length
      ? "\n\n확인해 주세요\n" + response.data.notes.map((note) => `- ${note}`).join("\n")
      : "";
    // 화면을 대신 넘기지 않습니다. 넘기면 이 안내가 가려져서, 무엇이 확인이
    // 필요한 값인지 모른 채 그대로 서류가 만들어집니다.
    say("bot", `칸 ${filled}개를 채웠습니다.` + what + notes);
    record("assistant", `칸 ${filled}개를 채웠습니다.` + what + notes, "note");
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

  // 📄·🔎로 시작하는 링크는 "ForwardUs 액션 버튼"입니다. 글 속 링크가 아니라 단추로 보이게 합니다.
  function actionClass(label) {
    return /^\s*(📄|🔎|📑|📦)/u.test(label) ? ' class="answer_action"' : "";
  }

  function inline(escaped) {
    return escaped
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      // {{ }}로 감싼 것은 빨갛게. 꼭 있어야 하는 칸과 운송 계획에서
      // 정해지는 칸을 눈에 띄게 하려는 표시입니다.
      .replace(/\{\{(.+?)\}\}/g, '<em class="need">$1</em>')
      // [글](주소). 주소는 http(s)만 받습니다. javascript: 같은 것이
      // 들어오면 링크로 만들지 않고 글자 그대로 둡니다.
      .replace(/\[([^\]]+)\]\((https?:&#x2F;&#x2F;[^)\s]+|https?:\/\/[^)\s]+)\)/g,
        (whole, label, url) => {
          const clean = url.replace(/&#x2F;/g, "/");
          return `<a href="${clean}" target="_blank" rel="noopener">${label}</a>`;
        })
      // [글](/documents/new) 같은 우리 화면 주소. "/"로 시작하는 것만 받고
      // "//"(다른 사이트로 가는 주소)는 막습니다. 같은 탭에서 엽니다.
      .replace(/\[([^\]]+)\]\(((?:&#x2F;|\/)(?!&#x2F;|\/)[^)\s]*)\)/g,
        (whole, label, url) => `<a href="${url.replace(/&#x2F;/g, "/")}"${actionClass(label)}>${label}</a>`)
      // [HS CODE 조회](#hs:립스틱). 화면을 옮기지 않고 간편 검색 창을 띄웁니다. (hs_modal.js)
      // 품명은 이미 escape된 글자라 속성에 그대로 넣어도 됩니다.
      .replace(/\[([^\]]+)\]\(#hs(?::([^)]*))?\)/g, (whole, label, query = "") =>
        `<a href="#hs" class="hs_link${actionClass(label) ? " answer_action" : ""}" data-hs-open`
        + ` data-hs-query="${query.trim()}">${label}</a>`)
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function renderAnswer(text) {
    // escapeHtml을 먼저 한 번만 겁니다. 이후로는 우리가 넣는 태그만 살아 있습니다.
    return escapeHtml(text).split(/\n{2,}/).map((block) => {
      const lines = block.split("\n").filter((line) => line.trim());
      if (!lines.length) return "";
      // | 표 | — 데이터 브리핑의 국가별 수출액 비교. 제목 줄 앞에 설명 줄이 붙어 와도 표로 그립니다.
      const tableAt = lines.findIndex((line, i) => /^\s*\|/.test(line)
        && lines[i + 1] && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1]));
      if (tableAt >= 0) {
        const before = lines.slice(0, tableAt);
        const rows = [];
        let end = tableAt;
        while (end < lines.length && /^\s*\|/.test(lines[end])) rows.push(lines[end++]);
        const cells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "")
          .split("|").map((cell) => cell.trim());
        const head = cells(rows[0]);
        // 둘째 줄(|:---:|---:|)이 칸 정렬입니다. K-stat 표처럼 순위·코드는 가운데, 금액은 오른쪽.
        const aligns = cells(rows[1]).map((cell) => (/^:-+:$/.test(cell) ? "center"
          : /^-+:$/.test(cell) ? "right" : /^:-+$/.test(cell) ? "left" : ""));
        // 정렬을 안 적었으면 금액·증감률 칸은 오른쪽으로 맞춥니다. 자릿수를 눈으로 견주기 쉽습니다.
        const numeric = (text) => /^[+\-−]?\d[\d,]*(\.\d+)?\s*(%|달러|억|만|천불)?$/.test(text)
          || (/^[+\-−]?[\d,.]+/.test(text) && /(달러|%|억|만)/.test(text));
        const cellClass = (text, i) => {
          const names = [];
          if (aligns[i]) names.push(`al_${aligns[i]}`);
          else if (numeric(text)) names.push("num");
          // 증감률은 오르면 파랑, 내리면 빨강. 표를 훑을 때 방향이 먼저 보이게 합니다.
          if (/^\+\d[\d,.]*%$/.test(text)) names.push("up");
          else if (/^[-−]\d[\d,.]*%$/.test(text)) names.push("down");
          return names.length ? ` class="${names.join(" ")}"` : "";
        };
        const body = rows.slice(2).map((line) => {
          const row = cells(line);
          // 합계 줄은 굵게. (**합계**처럼 적어 옵니다)
          const total = row.some((cell) => /^\*\*(합계|총계|계)\*\*$/.test(cell));
          return `<tr${total ? ' class="total"' : ""}>${row.map((cell, i) =>
            `<td${cellClass(cell, i)}>${inline(cell)}</td>`).join("")}</tr>`;
        }).join("");
        const table = `<div class="answer_table_wrap"><table class="answer_table"><thead><tr>${
          head.map((cell, i) => `<th${aligns[i] ? ` class="al_${aligns[i]}"` : ""}>${inline(cell)}</th>`)
            .join("")}</tr></thead><tbody>${body}</tbody></table></div>`;
        const after = lines.slice(end);
        return (before.length ? `<p>${before.map(inline).join("<br>")}</p>` : "")
          + table + (after.length ? `<p>${after.map(inline).join("<br>")}</p>` : "");
      }
      // 한 덩어리가 전부 목록이면 목록으로, 아니면 문단으로 그립니다.
      if (lines.every((line) => /^\s*(?:[-*•]|\d+\.)\s+/.test(line))) {
        const items = lines.map((line) =>
          `<li>${inline(line.replace(/^\s*(?:[-*•]|\d+\.)\s+/, ""))}</li>`).join("");
        return /^\s*\d+\./.test(lines[0]) ? `<ol>${items}</ol>` : `<ul>${items}</ul>`;
      }
      // "> " 인용. escape 뒤라 ">"는 "&gt;"로 들어옵니다.
      if (lines.every((line) => /^\s*&gt;\s?/.test(line))) {
        return `<blockquote>${lines.map((line) =>
          inline(line.replace(/^\s*&gt;\s?/, ""))).join("<br>")}</blockquote>`;
      }
      if (lines.length === 1 && /^#{1,4}\s+/.test(lines[0])) {
        return `<h4>${inline(lines[0].replace(/^#{1,4}\s+/, ""))}</h4>`;
      }
      return `<p>${lines.map(inline).join("<br>")}</p>`;
    }).join("");
  }

  function say(kind, text, { restoring = false, pin = true } = {}) {
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
    if (restoring) return row;
    if (kind === "me") {
      lastQuestion = row;
      pinToTop(row);
    } else if (kind !== "bot wait" && pin) {
      // 답(또는 안내)이 붙은 뒤 다시 한 번 붙여 줍니다. 이 그림 프레임은 지금 한 묶음의
      // 일이 끝난 뒤 돕니다. 그래서 답 아래의 출처·링크까지 다 그려진 다음에 잽니다.
      requestAnimationFrame(pinQuestion);
    }
    return row;
  }

  /* ----- 물어본 말을 화면 맨 위에 붙이기 -----
     답이 오기 전에는 아래에 내용이 없어 아무리 끌어올려도 질문이 화면 가운데나
     아래에 남습니다. (브라우저는 문서 끝보다 더 내려가지 못합니다) 그래서
     1) 모자란 만큼 대화 아래에 임시 여백을 두고
     2) 답이 온 뒤 한 번 더 붙여 줍니다. 여백은 그때 다시 계산해 줄어듭니다. */
  let lastQuestion = null;

  function headRoom() {
    // 위쪽 머리글이 화면에 붙어 있으면 그 아래부터가 "맨 위"입니다.
    const header = document.querySelector(".app_header, header");
    if (!header) return 12;
    const fixed = ["sticky", "fixed"].includes(getComputedStyle(header).position);
    return (fixed ? Math.ceil(header.getBoundingClientRect().height) : 0) + 12;
  }

  function pinToTop(row) {
    if (!row || !logEl) return;
    const target = Math.max(0, window.scrollY + row.getBoundingClientRect().top - headRoom());
    const short = target + window.innerHeight - document.documentElement.scrollHeight;
    // 남는 여백은 늘 다시 계산합니다. 답이 길어지면 여백이 사라집니다.
    logEl.style.paddingBottom = short > 0 ? `${Math.ceil(short)}px` : "";
    window.scrollTo({ top: target, behavior: "smooth" });
  }

  function pinQuestion() {
    if (lastQuestion && lastQuestion.isConnected) pinToTop(lastQuestion);
  }

  async function askSupport(question) {
    // 앞 대화에는 고래 상담창에서 나눈 말도 들어 있습니다.
    const history = chat.history();
    say("me", question);
    record("user", question);
    const waiting = say("bot wait", "답을 찾고 있습니다…");
    sendButton.disabled = true;

    // 수출 실적·결제 통계를 물으면 서버가 관세청·무역보험공사 API를 부른 뒤 답합니다.
    // 몇 번 왕복하므로 기본 20초로는 모자랍니다.
    const slow = setTimeout(() => {
      waiting.textContent = "관세청·무역보험공사 데이터를 조회해 분석하고 있습니다…";
    }, 4000);
    const response = await postJson(config.chatUrl, { question, history }, 120000);
    clearTimeout(slow);
    sendButton.disabled = false;
    waiting.remove();

    if (!response.success) {
      say("bad", response.message);
      return;
    }
    const answer = response.data.answer;
    const row = say("bot", answer);
    record("assistant", answer);
    // 어떤 공공데이터로 답했는지 답 아래에 남깁니다. 숫자의 근거를 사람이 볼 수 있어야 합니다.
    if ((response.data.sources || []).length) {
      const note = document.createElement("p");
      note.className = "answer_sources";
      note.textContent = `📊 실데이터 조회: ${response.data.sources.join(" · ")} (공공데이터포털)`;
      // 조회 기간·HS 범위·등급의 성격. AI가 본문에서 빠뜨려도 여기엔 늘 남습니다.
      (response.data.basis || []).forEach((line) => {
        const item = document.createElement("small");
        item.textContent = line;
        note.appendChild(item);
      });
      row.appendChild(note);
    }
    // 인코텀즈처럼 눌러 봐야 아는 것은 글 대신 표를 답 안에 답니다.
    // 화면을 옮기지 않고 이 자리에서 조건을 바꿔 가며 볼 수 있습니다.
    if (response.data.widget === "incoterms" && window.ForwardusIncotermWidget) {
      window.ForwardusIncotermWidget.attach(row, guessIncoterm(question));
    }
    appendLinks(row, response.data.links);
    // 치수와 수량을 적어 주셨으면 CBM·운임톤과 LCL/FCL을 바로 알려 드립니다.
    // 이건 계산이라 AI를 기다리지 않습니다. (숫자를 지어내면 안 되는 자리입니다)
    if (response.data.assumed_route) appendRoute(row, response.data.assumed_route);
    if (response.data.cargo) appendCargo(row, response.data.cargo);
    // 대화에 적은 화물 정보를 담아 두었으면 한 줄 알립니다. 어디에 쓰이는지까지.
    if ((response.data.captured || []).length) {
      const note = document.createElement("p");
      note.className = "answer_kept";
      note.textContent = `📌 ${response.data.captured.join(" · ")}을(를) 담아 두었습니다. `
        + "서류 작성·운송 계획 화면에서 그대로 씁니다.";
      row.appendChild(note);
    }
    rememberHsQueries(answer);
  }

  // "FOB랑 CIF는 어떻게 다른가요?"처럼 조건을 집어 물었으면 그 조건을 먼저 펴 줍니다.
  const INCOTERM_CODES = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"];

  function guessIncoterm(question) {
    const upper = String(question || "").toUpperCase();
    return INCOTERM_CODES.find((code) => upper.includes(code)) || "";
  }

  /* ----- 어느 구간 기준인지 밝히기 -----
     이번 말에 출발·도착지가 없으면 앞서 알려 주신 구간으로 답합니다. 그 사실을
     밝히지 않으면, 엉뚱한 구간의 기간과 운임을 그대로 믿게 됩니다. */
  function appendRoute(row, route) {
    const note = document.createElement("p");
    note.className = "answer_route";
    note.innerHTML = `📍 <b>${escapeHtml(route.origin)} → ${escapeHtml(route.destination)}</b>`
      + " 기준으로 답했습니다. 다른 구간이면 알려 주세요.";
    row.prepend(note);
  }

  /* ----- 적어 주신 화물의 CBM·LCL/FCL -----
     "수건 300박스, 한 박스 40x61x70cm에 50kg"이라고 적으면 사람은 그 다음에 꼭
     "몇 CBM인가요, LCL인가요 FCL인가요"를 묻습니다. 계산이라 우리가 바로 답합니다. */
  function appendCargo(row, cargo) {
    const box = document.createElement("div");
    box.className = "answer_cargo";
    const containers = cargo.containers
      ? ` · ${cargo.containers}대 (${escapeHtml(cargo.container_type)})` : "";
    box.innerHTML = `
      <p class="answer_cargo_head">📦 적어 주신 화물로 계산하면
        <b>${cargo.total_cbm} CBM</b> · 운임톤 <b>${cargo.revenue_ton} R/T</b>
        → <b class="cargo_mode">${escapeHtml(cargo.mode)}</b>${containers}</p>
      <p class="answer_cargo_why">${escapeHtml(cargo.reason)}</p>
      <p class="answer_cargo_detail">한 포장 ${cargo.per_package_cbm} CBM
        · 총 중량 ${cargo.total_weight_kg.toLocaleString()} kg
        <a href="/planning/new">운송 예상 견적에서 운임 보기 →</a></p>`;
    row.appendChild(box);
  }

  /* ----- 답 아래의 관련 링크 -----
     화면(서류 작성·관세청 조회…)과 기관 창구(식약처·검역본부…)를 함께 답니다.
     주소는 서버가 들고 있는 표에서만 옵니다. AI가 만든 주소는 쓰지 않습니다. */
  function appendLinks(row, links) {
    if (!row || !(links || []).length) return;
    const box = document.createElement("p");
    box.className = "answer_links";
    box.innerHTML = `<span>관련 자료</span>` + links.map((link) => {
      const outside = /^https?:/.test(link.url);
      const attrs = outside ? ` target="_blank" rel="noopener"` : "";
      return `<a class="answer_link${outside ? " is_outside" : ""}" href="${escapeHtml(link.url)}"${attrs}`
        + ` title="${escapeHtml(link.note || "")}">${escapeHtml(link.label)}${outside ? " ↗" : ""}</a>`;
    }).join("");
    row.appendChild(box);
  }

  /* ----- HS CODE 간편 검색 -----
     상담 답변에 [HS CODE 조회](#hs:품명)이 있으면 그 품명을 기억해 둡니다.
     "HS CODE 조회" 단추를 누르면 그 품명으로 바로 찾습니다. */
  function rememberHsQueries(answer) {
    if (!window.ForwardusHsModal) return;
    const found = Array.from(String(answer).matchAll(/\]\(#hs:([^)]+)\)/g), (m) => m[1].trim());
    // 마지막에 나온 것이 지금 이야기하는 품목일 가능성이 큽니다.
    window.ForwardusHsModal.remember(found.reverse());
  }

  // 적는 칸에 뭔가 적혀 있으면 그것부터, 없으면 기억해 둔 품명(hs_modal.js가 고릅니다).
  function guessHsQuery() {
    const text = input.value.trim();
    return text.length >= 2 && text.length <= 60 && !text.includes("\n") ? text : "";
  }

  /* ----- 파일 붙이기 (세 탭 공통) -----
     + 로 고르거나 끌어다 놓으면 바로 보내지 않고 적는 칸 위에 칩으로 보여 줍니다.
     "이거 기반으로 인보이스 써줘"처럼 할 말을 함께 적어 보내면 서버(/api/attach)가
     1) 어떤 서류인지 알아보고 2) 서류를 만들어 달라는 말이면 서류 작성 흐름을 시작합니다.
     그 말을 무역 상담 탭에서 했으면 탭을 서류 작성으로 옮깁니다. */
  let attached = null;       // { file, url } — 칩에 보이는 파일
  let lastDoc = null;        // 마지막으로 읽은 서류. 나중에 "이걸로 서류 만들어줘"라고 해도 씁니다.

  function setPlaceholder() {
    input.placeholder = attached
      ? "이 서류로 무엇을 할까요? (예: 이거 기반으로 인보이스 써줘 / 이 B/L에서 확인할 것은?)"
      : current.placeholder;
  }

  function formatSize(bytes) {
    return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)}MB`
      : `${Math.max(1, Math.round(bytes / 1024))}KB`;
  }

  function isImage(file) {
    return /^image\//.test(file.type) || /\.(png|jpe?g|webp)$/i.test(file.name);
  }

  // 파일 칩. 그림이면 썸네일, PDF면 문서 표시. 보낸 말에도 같은 모양으로 남깁니다.
  function fileChipHtml(file, url, { removable = false } = {}) {
    const thumb = url
      ? `<img class="attach_thumb" src="${url}" alt="">`
      : `<span class="attach_thumb is_pdf" aria-hidden="true">PDF</span>`;
    const remove = removable
      ? `<button type="button" class="attach_remove" data-attach-remove aria-label="첨부 삭제">×</button>` : "";
    return `<span class="attach_chip">${thumb}<span class="attach_meta">`
      + `<b title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</b>`
      + `<small>${escapeHtml(formatSize(file.size))}</small></span>${remove}</span>`;
  }

  function attach(file) {
    const reason = window.ForwardusDocUpload.problem(file);
    if (reason) { say("bad", reason); return; }
    clearAttachment();
    attached = { file, url: isImage(file) ? URL.createObjectURL(file) : "" };
    attachTray.innerHTML = fileChipHtml(file, attached.url, { removable: true });
    attachTray.hidden = false;
    setPlaceholder();
    resize();
    input.focus();
  }

  // keepUrl: 보낸 말의 칩이 같은 썸네일을 쓰므로 그때는 풀지 않습니다.
  function clearAttachment({ keepUrl = false } = {}) {
    if (attached && attached.url && !keepUrl) URL.revokeObjectURL(attached.url);
    attached = null;
    attachTray.innerHTML = "";
    attachTray.hidden = true;
    if (uploadInput) uploadInput.value = "";
    setPlaceholder();
  }

  function sayMine(text, file, url) {
    const row = say("me", "");
    row.innerHTML = fileChipHtml(file, url)
      + (text ? `<span class="me_text">${escapeHtml(text)}</span>` : "");
    return row;
  }

  function busy(on) {
    sendButton.disabled = on;
    if (plusButton) plusButton.disabled = on;
    sendButton.classList.toggle("working", on);
  }

  // 탭을 사람이 누르지 않아도 옮깁니다. 옮겼다는 것을 반드시 말합니다. 조용히 바뀌면 헷갈립니다.
  function goDocuments(reason) {
    if (current.key === "documents") return;
    const from = current.label;
    selectMode("documents", { greet: false });
    const tab = document.querySelector('[data-home-action="documents"]');
    if (tab) flash(tab);
    say("note", `${reason ? reason + " " : ""}[${from}] → [서류 작성] 탭으로 옮겨 이어서 진행합니다.`);
  }

  async function sendAttachment(text) {
    const { file, url } = attached;
    clearAttachment({ keepUrl: true });
    sayMine(text, file, url);
    const waiting = say("bot wait", "첨부하신 서류가 어떤 서류인지 살펴보고 있습니다… "
      + "그림으로 된 서류는 30초쯤 걸립니다.");
    busy(true);

    const body = new FormData();
    body.append("file", file, file.name);
    body.append("message", text);
    body.append("mode", current.key);
    body.append("history", JSON.stringify(chat.history().slice(-8)));
    const response = await window.Forwardus.postForm(config.attachUrl, body, 180000);
    busy(false);
    waiting.remove();

    if (!response.success) {
      say("bad", response.message || "서류를 읽지 못했습니다.");
      return;
    }
    const data = response.data;
    lastDoc = data.document;
    // 서류 작성 화면으로 넘어가도 이어 쓸 수 있게 놓아 둡니다. (HS 간편 검색 품명도)
    window.ForwardusDocUpload.stash(data.document);
    say("bot", data.recognized);
    const card = say("bot", "");
    card.innerHTML = window.ForwardusDocUpload.resultHtml(data.document);

    if (data.route === "documents") {
      goDocuments(text ? "서류 작성을 요청하셔서" : "");
      beginPipeline(data.pipeline, data.document.document_label);
      return;
    }
    if (data.answer) {
      say("bot", data.answer);
      record("user", data.question || text || file.name);
      record("assistant", data.answer);
      rememberHsQueries(data.answer);
    } else if (data.answer_error) {
      say("bad", data.answer_error);
    }
    offerMake(data.document);
  }

  // 상담 탭에서 올렸으면 서류로 만들지 묻는 단추를 둡니다. 말로 "서류 만들어줘"라고 해도 됩니다.
  function offerMake(documentData) {
    const row = say("bot", "");
    row.innerHTML = `<div class="draft_actions">
        <button type="button" class="button primary" data-offer-make>📄 이 서류로 서류 만들기</button>
        <span class="muted small">"이거 기반으로 인보이스 써줘"처럼 말씀하셔도 됩니다.</span></div>`;
    row.querySelector("[data-offer-make]").addEventListener("click", (event) => {
      event.currentTarget.disabled = true;
      goDocuments("");
      startPipeline(documentData, []);
    });
  }

  /* ----- 올린 서류로 서류 만들기 -----
     읽은 값 → 빠진 필수 정보 묻기 → 채팅으로 받아 합치기 → 고른 서류만 만들기 → 검토 창.
     무엇이 필수이고 무엇이 빠졌는지는 서버(document_pipeline_service)가 정합니다.
     초안은 브라우저가 들고 다닙니다. 서버는 상태를 갖지 않습니다. */
  let pipe = null;
  // 검토 창에서 견적명을 저장하면 받는 초안 번호. 같은 건을 다시 저장하면
  // 새 줄이 아니라 이 줄을 고칩니다. 나중에 Shipment로 승격할 때도 씁니다.
  let savedDraftId = null;

  const pipelineUrl = (step) => config.pipelineUrl.replace("__STEP__", step);

  function beginPipeline(state, label) {
    // 새 서류를 올리면 앞의 고르기 칸은 치웁니다. 두 개가 남으면 어느 것이 지금 것인지 헷갈립니다.
    if (pipe && pipe.card) pipe.card.remove();
    pipe = { ...state, card: null, label };
    savedDraftId = null;        // 새 건입니다. 앞 건의 초안을 덮어쓰지 않습니다.
    syncWorkDraft("upload");
    say("bot", pipe.reply);
    renderPickCard();
  }

  // 대화로 모은 초안도 "작성 중인 수출 건"에 저장해 운송 계획이 이어 씁니다. (work_draft.js)
  function syncWorkDraft(source) {
    if (pipe && pipe.draft && window.ForwardusWorkDraft) window.ForwardusWorkDraft.save(pipe.draft, source);
    stashForDocForm();
  }

  // 파일에서 읽은 값 + 채팅으로 적어 주신 값을 합친 그대로, 서류 작성 화면이
  // 집어 갈 수 있게 놓아 둡니다. 그 화면은 칸 이름이 곧 서식의 칸 이름이라
  // 초안의 키를 그대로 꽂으면 됩니다. (doc_form.js FORWARDUS_DOC_FILL)
  // 탭을 새로 열면 사라지는 것이 맞습니다 — 아직 확정이 아닙니다.
  function stashForDocForm() {
    if (!pipe || !pipe.draft) return;
    const fields = { ...pipe.draft };
    delete fields.items;
    try {
      window.sessionStorage.setItem(DOC_DRAFT_KEY,
        // draftId: 그 화면에서 서류를 만들면 이 초안이 Shipment로 승격됩니다.
        JSON.stringify({ fields, items: pipe.draft.items || [], draftId: savedDraftId }));
    } catch (error) {
      /* 저장 공간이 없으면 화면을 옮길 때 다시 적으셔야 합니다. */
    }
  }

  async function startPipeline(extracted, kinds) {
    const response = await postJson(pipelineUrl("start"), {
      form: extracted.form, document_label: extracted.document_label, kinds }, 30000);
    if (!response.success) { say("bad", response.message); return; }
    beginPipeline(response.data, extracted.document_label);
  }

  // 앞서 올린 서류가 있을 때 상담·운송 탭에서 적은 말. 서류를 만들어 달라는 말이면
  // 서류 작성 탭으로 옮겨 그 서류로 시작합니다. 아니면 평소처럼 상담으로 답합니다.
  async function routeWithLastDoc(text) {
    const response = await postJson(pipelineUrl("intent"), { message: text }, 10000);
    if (!response.success || !response.data.make) {
      if (current.key === "documents") askAgent(text); else askSupport(text);
      return;
    }
    const kinds = response.data.kinds;
    say("me", text);
    goDocuments("서류 작성을 요청하셔서");
    if (pipe) {
      // 이미 진행 중이면 처음부터 다시 읽지 않습니다. 채팅으로 채운 값이 남아야 합니다.
      // 짚어 말한 서류가 있으면 고르기만 그 서류로 바꿉니다.
      if (kinds.length) pipe.kinds = kinds;
      if (pipe.card) { pipe.card.remove(); pipe.card = null; }
      say("bot", "진행 중이던 서류 작성을 이어 갑니다. 아래에서 만들 서류를 확인해 주세요.");
      renderPickCard();
      return;
    }
    say("bot", `앞서 올려 주신 **${lastDoc.document_label}**을(를) 바탕으로 진행합니다.`);
    startPipeline(lastDoc, kinds);
  }

  async function mergePipe(message) {
    say("me", message);
    const waiting = say("bot wait", "적어 주신 내용을 기존 서류 값과 합치는 중입니다…");
    sendButton.disabled = true;
    const response = await postJson(pipelineUrl("merge"),
      // asked: 방금 물어본 목록. 사람이 번호로 답하면 서버가 이 순서로 읽습니다.
      // awaiting: 바로 앞에서 견적명을 물었으면, 이 말은 그 답입니다.
      { draft: pipe.draft, kinds: pickedKinds(), message,
        awaiting: pipe.awaiting_name ? "project_name" : "",
        asked: (pipe.missing || []).map((row) => row.key) }, 60000);
    sendButton.disabled = false;
    waiting.remove();
    if (!response.success) { say("bad", response.message); return; }
    Object.assign(pipe, response.data);
    syncWorkDraft("chat");
    say("bot", pipe.reply);
    (pipe.notes || []).forEach((note) => say("bad", note));
    renderPickCard();
  }

  function pickedKinds() {
    if (!pipe || !pipe.card) return pipe ? pipe.kinds : [];
    return Array.from(pipe.card.querySelectorAll("input[data-pick-kind]:checked"),
      (box) => box.value);
  }

  // 고른 서류에 필요한데 아직 빠진 것. 체크를 바꿀 때마다 서버에 묻지 않고 거릅니다.
  // (만들 때 서버가 다시 봅니다)
  function missingFor(kinds) {
    return (pipe.missing_all || []).filter((row) => row.kinds.some((kind) => kinds.includes(kind)));
  }

  // 만들 서류 고르기. 하나만 두고 대화가 이어질 때마다 맨 아래로 옮겨 다시 그립니다.
  function renderPickCard() {
    const kinds = pipe.card ? pickedKinds() : pipe.kinds;
    const card = pipe.card || say("bot", "");
    card.classList.add("pick_card_row");
    card.innerHTML = `
      <div class="pick_card">
        <p class="pick_title"><b>만들 서류를 고르세요</b>
          <small>기본은 가장 자주 쓰는 상업송장·포장명세서입니다</small></p>
        <div class="pick_list">${pipe.options.map((option) => `
          <label class="pick_opt">
            <input type="checkbox" data-pick-kind value="${escapeHtml(option.kind)}"
                   ${kinds.includes(option.kind) ? "checked" : ""}>
            <span><b>${escapeHtml(option.label)}</b><small>${escapeHtml(option.about)}</small></span>
          </label>`).join("")}</div>
        <p class="pick_need" data-pick-need></p>
        <label class="pick_name">
          <span><b>견적명 · 문서명</b>
            <small>대시보드 목록에서 이 건을 부를 이름입니다. 서류에는 찍히지 않습니다.</small></span>
          <input type="text" maxlength="200" data-pick-name
                 value="${escapeHtml(pipe.project_name || "")}"
                 placeholder="${escapeHtml(pipe.project_name_suggestion
                   || "예: 2026-10 멕시코 화장품 1차 오퍼")}">
          ${pipe.project_name_suggestion ? `<small class="pick_name_hint">비워 두면
            <b>${escapeHtml(pipe.project_name_suggestion)}</b>(으)로 저장됩니다.
            <button type="button" class="link_button" data-pick-name-use>이 이름 쓰기</button></small>` : ""}
        </label>
        <div class="draft_actions">
          <button type="button" class="button primary" data-pick-make>선택한 서류 생성하기</button>
          <a class="button" href="${escapeHtml(config.docFormUrl)}" data-pick-edit>서류 작성 화면에서 직접 편집</a>
          <button type="button" class="link_button" data-pick-reset>올린 서류 없이 대화로 새로 만들기</button>
        </div>
      </div>`;
    logEl.appendChild(card);
    pipe.card = card;
    updatePickNeed();
    card.querySelectorAll("input[data-pick-kind]").forEach((box) =>
      box.addEventListener("change", updatePickNeed));
    card.querySelector("[data-pick-make]").addEventListener("click", generatePipe);
    // 넘어가기 직전에 지금 값으로 다시 놓아 둡니다. 방금 고친 견적명까지 따라갑니다.
    card.querySelector("[data-pick-edit]").addEventListener("click", stashForDocForm);
    // 적은 이름은 초안에 담아 둡니다. 대화가 이어져 카드를 다시 그려도 남습니다.
    const nameInput = card.querySelector("[data-pick-name]");
    nameInput.addEventListener("input", () => {
      pipe.project_name = nameInput.value.trim();
      pipe.draft.project_name = pipe.project_name;
      // 운송 계획 화면이 이 이름으로 시작하도록 초안에 실어 둡니다. (work_draft.js가 잠깐 뒤 보냅니다)
      syncWorkDraft("chat");
    });
    card.querySelector("[data-pick-name-use]")?.addEventListener("click", () => {
      nameInput.value = pipe.project_name_suggestion || "";
      nameInput.dispatchEvent(new Event("input", { bubbles: true }));
      nameInput.focus();
    });
    // 이 흐름을 끝냅니다. 이후 서류 작성 모드의 말은 예전처럼 대화로 서류를 만드는 창구로 갑니다.
    card.querySelector("[data-pick-reset]").addEventListener("click", () => {
      card.remove();
      pipe = null;
      lastDoc = null;
      say("bot", "올린 서류 흐름을 닫았습니다. 어떤 서류가 필요하신지 말씀해 주세요. "
        + '(예: "패킹리스트만 만들어줘")');
      input.focus();
    });
    card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function updatePickNeed() {
    const kinds = pickedKinds();
    const need = pipe.card.querySelector("[data-pick-need]");
    const make = pipe.card.querySelector("[data-pick-make]");
    const rows = missingFor(kinds);
    if (!kinds.length) {
      need.className = "pick_need bad";
      need.textContent = "만들 서류를 하나 이상 골라 주세요.";
    } else if (rows.length) {
      need.className = "pick_need warn";
      need.innerHTML = `고르신 서류에 아직 필요한 정보 <b>${rows.length}개</b> · `
        + rows.map((row) => escapeHtml(row.label)).join(", ")
        + "<br><small>채팅창에 적어 주시면 기존 값과 합쳐 이어서 진행합니다.</small>";
    } else {
      need.className = "pick_need ok";
      need.textContent = "필요한 정보가 모두 있습니다. 바로 만들 수 있습니다.";
    }
    // 빠진 채로 강행하지 않습니다. 빈 칸이 찍힌 송장은 세관·은행에서 되돌아옵니다.
    make.disabled = !kinds.length || rows.length > 0;
  }

  async function generatePipe() {
    const kinds = pickedKinds();
    // 안 적고 넘어가면 제안한 이름을 그대로 씁니다. 이름 없는 건이 목록에 쌓이지 않게.
    pipe.draft.project_name = pipe.project_name || pipe.project_name_suggestion || "";
    const make = pipe.card.querySelector("[data-pick-make]");
    make.disabled = true;
    make.textContent = "만드는 중…";
    const waiting = say("bot wait", "고르신 서류를 서식에 맞춰 그리는 중입니다…");
    const response = await postJson(pipelineUrl("generate"), { draft: pipe.draft, kinds }, 90000);
    waiting.remove();
    make.textContent = "선택한 서류 생성하기";
    if (!response.success) { say("bad", response.message); updatePickNeed(); return; }
    const data = response.data;
    if (data.stage !== "made") {
      // 서버가 보기에 아직 빠진 것이 있습니다. 다시 묻고 고르기를 이어 갑니다.
      Object.assign(pipe, data);
      say("bot", data.reply);
      renderPickCard();
      return;
    }
    pipe.kinds = kinds;
    // 서버가 이름을 자동으로 붙였을 수 있습니다. 들고 있는 초안을 그 값으로 맞춥니다.
    pipe.draft = data.draft || pipe.draft;
    pipe.project_name = data.project_name || pipe.project_name;
    pipe.awaiting_name = false;
    syncWorkDraft("chat");
    say("bot", data.reply);
    showMade(data.documents);
    updatePickNeed();
  }

  // 만든 서류. 썸네일과 검토 창 여는 단추를 대화에 남깁니다. 닫아도 다시 열 수 있습니다.
  function showMade(documents) {
    const row = say("bot", "");
    row.innerHTML = `
      <div class="made_docs">${documents.map((doc) => `
        <figure class="made_doc"><img src="${doc.preview}" alt="${escapeHtml(doc.title)} 초안">
          <figcaption>${escapeHtml(doc.title.split(" (")[0])}</figcaption></figure>`).join("")}</div>
      <div class="draft_actions">
        <button type="button" class="button primary" data-open-review>📑 미리보기 &amp; 검토 · PDF 다운로드</button>
      </div>`;
    const openReview = () => openPreview(documents);
    row.querySelector("[data-open-review]").addEventListener("click", openReview);
    row.querySelectorAll(".made_doc").forEach((figure) => figure.addEventListener("click", openReview));
    openReview();
  }

  // 검토 창에서 견적명을 고치면 여기로 돌아옵니다. 대화·초안·서류 작성 화면이
  // 모두 같은 이름을 쓰도록 들고 있는 값을 맞춰 둡니다.
  function adoptQuoteTitle(saved) {
    if (!saved || !saved.quote_title) return;
    savedDraftId = saved.id || savedDraftId;
    if (pipe) {
      pipe.project_name = saved.quote_title;
      pipe.awaiting_name = false;
      if (pipe.draft) pipe.draft.project_name = saved.quote_title;
      if (pipe.card) renderPickCard();
      syncWorkDraft("chat");
    } else if (docDraft) {
      docDraft.project_name = saved.quote_title;
    }
  }

  function openPreview(documents) {
    if (!window.ForwardusDocPreview) return;
    const draft = (pipe && pipe.draft) || docDraft || {};
    window.ForwardusDocPreview.open(documents, {
      previewUrl: config.previewUrl, pdfUrl: config.reviewPdfUrl,
      // 견적명을 Shipment 없이 저장할 창구. 스케줄을 아직 안 골랐어도 남습니다.
      saveDraftUrl: config.saveDraftUrl,
      draftId: savedDraftId,
      source: pipe ? (pipe.source || "chat") : "chat",
      // 내려받는 파일 이름에 씁니다. 여러 건을 받아도 어느 건인지 알아봅니다.
      projectName: (pipe && pipe.project_name) || draft.project_name || "",
      suggestedName: (pipe && pipe.project_name_suggestion) || "",
      // 나중에 스케줄을 골라 Shipment로 승격할 때 쓸 초안입니다.
      getDraft: () => ({ ...draft, project_name: undefined }),
      onSaved: adoptQuoteTitle,
    });
  }

  if (uploadInput && plusButton && attachTray) {
    plusButton.addEventListener("click", () => uploadInput.click());
    uploadInput.addEventListener("change", () => {
      if (uploadInput.files.length) attach(uploadInput.files[0]);
    });
    attachTray.addEventListener("click", (event) => {
      if (!event.target.closest("[data-attach-remove]")) return;
      clearAttachment();
      input.focus();
    });
    // 적는 칸 덩어리에 끌어다 놓아도 됩니다. 어느 모드에서든 받습니다. (붙이기만 하고 보내지 않습니다)
    ["dragenter", "dragover"].forEach((type) => stage.addEventListener(type, (event) => {
      if (!event.dataTransfer || !Array.from(event.dataTransfer.types).includes("Files")) return;
      event.preventDefault();
      stage.classList.add("is_over");
    }));
    ["dragleave", "dragend"].forEach((type) => stage.addEventListener(type, (event) => {
      if (!stage.contains(event.relatedTarget)) stage.classList.remove("is_over");
    }));
    stage.addEventListener("drop", (event) => {
      if (!event.dataTransfer || !event.dataTransfer.files.length) return;
      event.preventDefault();
      stage.classList.remove("is_over");
      attach(event.dataTransfer.files[0]);
    });
  } else if (plusButton) {
    // 서류를 읽을 수 없는 화면(잠김 등)에서는 + 를 보이지 않습니다. 눌러도 아무 일이 없으면 안 됩니다.
    plusButton.hidden = true;
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
        window.sessionStorage.setItem(DOC_DRAFT_KEY,
          JSON.stringify({ fields, items: docDraft.items || [] }));
      } catch (error) {
        /* 저장 공간이 없으면 링크만 드립니다. */
      }
      data.documents.forEach(showDraft);
      showNextStep(data.documents);
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
  function showNextStep(documents) {
    const row = say("bot", "");
    // 대화로 만든 초안도 같은 검토 창에서 고치고 PDF로 받습니다.
    const review = documents && documents.length && documents[0].fields
      ? `<button type="button" class="button" data-open-review>📑 미리보기 &amp; 검토</button>` : "";
    row.innerHTML = `
      <div class="draft_actions">
        ${review}
        <a class="button primary" href="${escapeHtml(config.docFormUrl)}">
          운송 일정 넣고 정식 서류 만들기 →</a>
      </div>`;
    row.querySelector("[data-open-review]")?.addEventListener("click", () => openPreview(documents));
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

  // 다른 스크립트가 같은 대화창에 말을 붙일 수 있게 엽니다.
  window.ForwardusHome = { say, renderAnswer, startTalking };

  /* ----- 보내기 ----- */
  stage.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (sendButton.disabled) return;
    // 파일을 붙였으면 말이 없어도 보냅니다. 어떤 서류인지부터 알려 드립니다.
    if (!text && !attached) {
      input.focus();
      return;
    }
    input.value = "";
    resize();
    if (attached) { sendAttachment(text); return; }
    // 서류 작성에서는 서류를 만드는 창구로, 나머지는 상담으로 보냅니다.
    // 올린 서류로 만들고 있는 중이면, 적은 말은 빠진 정보로 보고 기존 값과 합칩니다.
    if (current.key === "documents" && pipe) mergePipe(text);
    else if (lastDoc) routeWithLastDoc(text);
    else if (current.key === "documents") askAgent(text);
    else askSupport(text);
  });

  // 왼쪽 사이드바(접힘·펼침, 최근 Shipment)는 모든 화면이 같이 씁니다. → sidebar.js

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
