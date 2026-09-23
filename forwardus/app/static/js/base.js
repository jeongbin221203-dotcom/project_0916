/* 브라우저에 남기는 값의 자리 — 회원마다 따로 둡니다.
 *
 * 한 탭에서 A가 로그아웃하고 B가 로그인하면, A가 적어 둔 바이어 주소·이메일이
 * B의 서류 칸에 그대로 채워지곤 했습니다. sessionStorage는 탭이 살아 있는 한
 * 남고, 로그아웃은 키를 지우지 않았기 때문입니다.
 *
 * 그래서 두 가지를 같이 합니다.
 *   1. 키마다 "누구 것인지"를 붙입니다. 남의 것은 애초에 읽히지 않습니다.
 *   2. 로그아웃할 때 그 회원 것을 지웁니다. 탭을 살려 둔 채 계정만 바꿔도
 *      거래처 정보가 넘어가지 않습니다.
 *
 * 이 파일은 base.html에서 다른 스크립트보다 먼저 읽힙니다. 아래 모두가 씁니다.
 * (work_draft · doc_form · planning · doc_upload · home · hs_modal · chat_store)
 */
(function () {
  "use strict";

  const SCOPE = window.FORWARDUS_SCOPE || "guest";

  // 로그아웃하면 지웁니다. 거래처 정보가 들어 있습니다.
  // (여기 적는 것은 접두사입니다. 실제 키에는 뒤에 :스코프가 붙습니다.)
  const PRIVATE = [
    "forwardus:work-private",     // 바이어 주소·이메일·Notify Party
    "forwardus:doc-form-draft",   // 서류 작성 폼에 적던 값 전체
    "forwardus:planning-draft",   // 운송 계획에 적던 값
    "forwardus:doc-draft",        // 화면 사이로 넘기는 서류 초안
  ];
  // forwardus:hs-queries 는 일부러 남깁니다. 그 회원이 찾아본 품명이라,
  // 다시 로그인하면 그대로 있는 편이 낫습니다. (hs_modal.js)

  function key(base) {
    return `${base}:${SCOPE}`;
  }

  function drop(store, name) {
    try { store.removeItem(name); } catch (error) { /* 못 지워도 막지 않습니다. */ }
  }

  function clearPrivate() {
    [window.sessionStorage, window.localStorage].forEach((store) => {
      PRIVATE.forEach((base) => drop(store, key(base)));
    });
  }

  // 스코프가 없던 시절의 키를 치웁니다. 이제 아무도 읽지 않는데 거래처 정보가
  // 담긴 채 브라우저에 남습니다. 읽는 쪽이 이미 새 키를 보므로 지워도 잃는 것이
  // 없습니다.
  function dropLegacy() {
    [window.sessionStorage, window.localStorage].forEach((store) => {
      PRIVATE.concat(["forwardus:hs-queries"]).forEach((base) => drop(store, base));
    });
  }

  window.ForwardusStore = { scope: SCOPE, key, clearPrivate };
  dropLegacy();

  // 로그아웃하면 그 회원이 적어 둔 것을 지웁니다.
  // 같은 컴퓨터를 다른 사람이 쓸 수 있습니다.
  document.addEventListener("submit", (event) => {
    if (event.target.closest && event.target.closest(".nav_logout")) clearPrivate();
  });
})();

/* Shared helpers and global UI behavior. */
(function () {
  "use strict";

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }

  const REQUEST_TIMEOUT_MS = 20000;

  // timeoutMs를 주면 그만큼 기다립니다. AI가 끼는 조회(HS 후보 비교, 서류 읽기)는
  // 20초를 넘기는 일이 흔합니다. 예전에는 부르는 쪽이 넘긴 값을 버리고 늘 20초에 끊었습니다.
  async function requestJson(url, options, timeoutMs = REQUEST_TIMEOUT_MS) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs || REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      try {
        return await response.json();
      } catch (error) {
        return {
          success: false,
          error_code: "INVALID_RESPONSE",
          message: `서버 응답을 해석하지 못했습니다 (HTTP ${response.status}). 다른 서버가 같은 포트를 쓰고 있지 않은지 확인하세요.`,
        };
      }
    } catch (error) {
      const timedOut = error.name === "AbortError";
      return {
        success: false,
        error_code: timedOut ? "TIMEOUT" : "NETWORK_ERROR",
        message: timedOut ? "서버 응답 시간이 초과되었습니다." : "서버와 통신하지 못했습니다. 서버가 실행 중인지 확인하세요.",
      };
    } finally {
      clearTimeout(timer);
    }
  }

  const getJson = (url, timeoutMs) => requestJson(url, { headers: { Accept: "application/json" } },
    timeoutMs);
  const postJson = (url, body, timeoutMs) => requestJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  }, timeoutMs);
  // 파일 올리기. Content-Type은 브라우저가 경계값까지 붙여 정하게 둡니다.
  const postForm = (url, formData, timeoutMs) => requestJson(url, {
    method: "POST", headers: { Accept: "application/json" }, body: formData,
  }, timeoutMs);

  function formatNumber(value, digits = 0) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
    return Number(value).toLocaleString("ko-KR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function toIsoDate(date) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }

  /* ----- 숫자 입력칸: 천 단위 쉼표 ----- */
  // 화면에는 1,000처럼 보여주고 서버에는 쉼표를 뗀 값을 보냅니다.
  function plainNumber(value) {
    return String(value ?? "").replace(/,/g, "").trim();
  }

  function groupDigits(value) {
    const text = plainNumber(value);
    if (!text || !/^-?\d*\.?\d*$/.test(text)) return text;
    const [whole, fraction] = text.split(".");
    const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return fraction === undefined ? grouped : `${grouped}.${fraction}`;
  }

  function setupNumberInput(input) {
    const step = Number(input.dataset.step || 1);
    const min = input.dataset.min === undefined ? null : Number(input.dataset.min);
    const max = input.dataset.max === undefined ? null : Number(input.dataset.max);

    const format = () => {
      // 커서가 뒤에서 몇 번째인지 기억했다가 쉼표를 넣은 뒤 같은 자리로 돌려놓습니다.
      const fromEnd = input.value.length - (input.selectionStart ?? input.value.length);
      input.value = groupDigits(input.value);
      const caret = Math.max(0, input.value.length - fromEnd);
      try { input.setSelectionRange(caret, caret); } catch (error) { /* 무시 */ }
    };

    input.addEventListener("input", format);
    input.addEventListener("blur", () => { input.value = groupDigits(input.value); });
    // 위아래 화살표로 값을 올리고 내립니다. (숫자 입력칸의 화살표 대신)
    input.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
      event.preventDefault();
      const current = Number(plainNumber(input.value)) || 0;
      let next = current + (event.key === "ArrowUp" ? step : -step);
      if (min !== null) next = Math.max(min, next);
      if (max !== null) next = Math.min(max, next);
      input.value = groupDigits(String(Math.round(next * 1000) / 1000));
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    input.value = groupDigits(input.value);
  }

  document.querySelectorAll("input[data-number]").forEach(setupNumberInput);

  // 우리 코드는 숫자 입력칸에 hidden을 붙이지 않습니다. 그런데도 붙는다면 브라우저
  // 확장 프로그램 등 바깥 스크립트가 한 것이므로 곧바로 되돌리고 콘솔에 남깁니다.
  const unhide = new MutationObserver((records) => {
    records.forEach((record) => {
      const input = record.target;
      if (input.matches && input.matches("input[data-number]") && input.hidden) {
        input.hidden = false;
        console.warn(`[FORWARDUS] 외부 스크립트가 입력칸(${input.name || input.dataset.line})을 숨겨 다시 보이게 했습니다.`
          + " 확장 프로그램을 끄거나 시크릿 창에서 확인해 주세요.");
      }
    });
  });
  unhide.observe(document.body, { attributes: true, attributeFilter: ["hidden"], subtree: true });

  /* ----- Autocomplete -----
     운송 계획(planning.js)에만 있던 것을 그대로 옮겼습니다. HS CODE 간편 검색 창도
     같은 것을 써야 Cargo 화면과 똑같이 동작합니다. 한쪽만 고치면 둘이 갈라집니다. */
  function debounce(fn, wait) {
    let timer;
    return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); };
  }

  function setupAutocomplete(container, fetchItems, renderItem, onSelect, options = {}) {
    const input = container.querySelector("[data-ac-input]");
    const list = container.querySelector("[data-ac-list]");
    let items = [];
    let searchVersion = 0;

    let overrideQuery = null;

    const search = debounce(async () => {
      const version = ++searchVersion;
      list.innerHTML = `<li class="empty">${escapeHtml(options.loadingMessage || "검색 중…")}</li>`;
      list.hidden = false;
      const query = overrideQuery === null ? input.value.trim() : overrideQuery;
      overrideQuery = null;
      const fetched = await fetchItems(query);
      if (version !== searchVersion) return;
      items = fetched;
      if (!items.length) {
        const message = options.emptyMessage
          ? options.emptyMessage(items)
          : `검색 결과가 없습니다. 목록에 없으면 "직접 입력"을 사용하세요.`;
        list.innerHTML = `<li class="empty">${escapeHtml(message)}</li>`;
        return;
      }
      let html = "";
      if (options.groupBy) {
        // 같은 그룹을 한 번만 표시합니다. 서버가 보내는 순서가 섞여 있어도
        // 머리글이 중복되지 않도록 그룹별로 모아서 그립니다.
        const groups = new Map();
        items.forEach((item, index) => {
          const value = options.groupBy(item);
          if (!groups.has(value)) groups.set(value, []);
          groups.get(value).push({ item, index });
        });
        groups.forEach((entries, value) => {
          const other = value === "환승 필요" || value === "환적 필요"
            || value === "정기 항로 확인 필요";
          const GROUP_NOTES = {
            "환승 필요": "고른 출발 공항에서 직항편이 없어 환승이 필요합니다",
            "환적 필요": "한국에서 직기항 선박이 없어 환적항을 거칩니다",
            "정기 항로 확인 필요": "정기 항로 기록이 없어 선사에 확인이 필요합니다",
          };
          const note = GROUP_NOTES[value];
          html += `<li class="ac_group${other ? " ac_group_other" : ""}">${escapeHtml(value)}`
            + (note ? `<small>${escapeHtml(note)}</small>` : "")
            + `</li>`;
          entries.forEach(({ item, index }) => {
            html += `<li role="option" tabindex="0" data-index="${index}">${renderItem(item)}</li>`;
          });
        });
      } else {
        items.forEach((item, index) => {
          html += `<li role="option" tabindex="0" data-index="${index}">${renderItem(item)}</li>`;
        });
      }
      // 목록 맨 위에 덧붙일 안내가 있으면 함께 그립니다. (예: 영문을 한글로 바꿔 찾음)
      if (options.leadRow) html = options.leadRow(items) + html;
      list.innerHTML = html;
      // 목록을 그린 뒤 덧붙일 것이 있으면 (예: HS 후보별 협정) 이어서 채웁니다.
      if (options.afterRender) options.afterRender(items, list);
    }, options.delayMs || 200);

    input.addEventListener("input", () => { ++searchVersion; onSelect(null, input); search(); });
    // 이미 고른 항구가 있어도 다시 누르면 전체 목록을 보여줍니다.
    // (간편 검색 창처럼 적힌 말 그대로 다시 찾아야 하는 자리는 focusShowsAll: false)
    input.addEventListener("focus", () => {
      if (options.focusShowsAll === false) return;
      input.select();
      overrideQuery = "";
      search();
    });
    input.addEventListener("blur", () => { if (!options.keepOpen) setTimeout(() => { list.hidden = true; }, 150); });
    list.addEventListener("mousedown", (event) => {
      // 후보 안의 ⓘ(근거 보기)를 눌렀을 때는 그 후보를 고르지 않습니다.
      if (event.target.closest(".info_tip")) return;
      const li = event.target.closest("li[data-index]");
      if (!li) return;
      onSelect(items[Number(li.dataset.index)], input);
      list.hidden = true;
    });
    // 키보드로도 고릅니다. Tab으로 후보에 가서 Enter·스페이스.
    list.addEventListener("keydown", (event) => {
      if (event.target.closest(".info_tip") || !["Enter", " "].includes(event.key)) return;
      const li = event.target.closest("li[data-index]");
      if (!li) return;
      event.preventDefault();
      onSelect(items[Number(li.dataset.index)], input);
      list.hidden = true;
    });
    return {
      search,
      showAll() {
        ++searchVersion;
        overrideQuery = "";
        search();
      },
      // 목록이 열려 있을 때만 다시 그립니다. 닫혀 있는데 다시 검색하면
      // 이미 고른 값("로테르담항 (NLRTM)")으로 검색해 빈 목록이 떠 버립니다.
      refresh() {
        if (!list.hidden) { ++searchVersion; search(); }
      },
    };
  }

  window.Forwardus = { escapeHtml, getJson, postJson, postForm, formatNumber, toIsoDate,
                       plainNumber, groupDigits, setupNumberInput, debounce, setupAutocomplete };

  const toggle = document.querySelector("[data-nav-toggle]");
  const nav = document.querySelector("[data-nav]");
  if (toggle && nav) {
    toggle.addEventListener("click", () => {
      const open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // 로그인한 사람의 이름을 누르면 '내 Dashboard' · 로그아웃 메뉴가 열립니다.
  const userMenu = document.querySelector("[data-user-menu]");
  if (userMenu) {
    const userToggle = userMenu.querySelector("[data-user-menu-toggle]");
    const userPanel = userMenu.querySelector("[data-user-menu-panel]");
    const setUserMenu = (open) => {
      userPanel.hidden = !open;
      userToggle.setAttribute("aria-expanded", open ? "true" : "false");
    };
    userToggle.addEventListener("click", () => setUserMenu(userPanel.hidden));
    // 커서를 올리면 바로 펼칩니다. 누르거나 키보드로 여는 길도 그대로 둡니다.
    userMenu.addEventListener("pointerenter", (event) => {
      if (event.pointerType === "mouse") setUserMenu(true);
    });
    userMenu.addEventListener("pointerleave", (event) => {
      if (event.pointerType === "mouse" && !userMenu.contains(document.activeElement)) setUserMenu(false);
    });
    document.addEventListener("click", (event) => {
      if (!userMenu.contains(event.target)) setUserMenu(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !userPanel.hidden) {
        setUserMenu(false);
        userToggle.focus();
      }
    });
  }

  // 날짜 칸은 어디를 눌러도 달력이 열리게 합니다. (기본 동작은 달력 아이콘만)
  document.querySelectorAll('input[type="date"]').forEach((input) => {
    const open = () => {
      if (typeof input.showPicker === "function") {
        try {
          input.showPicker();
        } catch (error) {
          /* 브라우저가 막으면 기본 동작을 씁니다. */
        }
      }
    };
    input.addEventListener("click", open);
    input.addEventListener("focus", open);
  });

  /* ----- 홈 버튼은 "처음부터 다시" ----- */
  // 입력하던 내용과 나누던 대화는 탭 세션에 임시 저장됩니다(메뉴를 오가도 유지).
  // 홈 버튼(로고 · 왼쪽 줄의 홈 등)을 누르면 그 내용을 지우고 첫 화면으로
  // 돌아갑니다. 대화가 남아 있으면 홈을 눌러도 대화 화면이 다시 떠서 첫
  // 화면으로 못 돌아갑니다.
  //
  // 새로고침(F5)은 건드리지 않습니다.
  //
  // 예전에는 새로고침도 "처음부터 다시"로 보고 초안을 지운 뒤 홈으로
  // 보냈습니다. 그런데 새로고침은 화면이 이상할 때 사람이 가장 먼저 누르는
  // 것입니다. 고쳐 보려고 누른 사람이 적던 것을 통째로 잃고 첫 화면에 서
  // 있게 됩니다. planning.js가 beforeunload로 저장해 둔 초안까지 같은 키라
  // 함께 지워졌습니다. 새로고침 뒤에는 보던 화면과 적던 값이 그대로 있어야
  // 합니다.
  const DRAFT_KEY = window.ForwardusStore.key("forwardus:planning-draft");
  const CHAT_PREFIX = "forwardus:chat:";
  function clearDraft() {
    [window.sessionStorage, window.localStorage].forEach((store) => {
      try {
        store.removeItem(DRAFT_KEY);
        // 시작 화면 탭과 고래 상담창이 나눠 쓰는 대화 (chat_store.js)
        Object.keys(store).filter((key) => key.startsWith(CHAT_PREFIX))
          .forEach((key) => store.removeItem(key));
      } catch (error) { /* 무시 */ }
    });
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest && event.target.closest("[data-home-reset]")) clearDraft();
  });

  document.querySelectorAll(".flash_stack .flash").forEach((el) => {
    setTimeout(() => el.classList.add("fade"), 6000);
  });
})();
