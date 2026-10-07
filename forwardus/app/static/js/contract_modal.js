/* 계약서 조항 점검 창 열고 닫기. 어느 화면에서나 [data-contract-open]이면 뜹니다.
   (HS CODE 창과 같은 틀·같은 클래스를 씁니다. 창마다 모양이 다르면 같은 것인지 알 수 없습니다) */
(function () {
  "use strict";

  const modal = document.querySelector("[data-contract-modal]");
  const host = modal && modal.querySelector("[data-contract-panel]");
  const config = window.FORWARDUS_CONTRACT;
  if (!modal || !host || !config) return;

  let mounted = false;
  let returnTo = null;

  function open() {
    returnTo = document.activeElement;
    modal.hidden = false;
    document.body.classList.add("hs_modal_open");
    // 처음 열 때 한 번만 그립니다. 다시 열어도 앞서 본 결과가 남아 있습니다.
    if (!mounted && window.ForwardusContractClauses) {
      window.ForwardusContractClauses.mount(host, {
        // 인코텀즈·도착국을 넘기지 않으면 창 안에서 고르게 합니다(사용성 점검 2026-10-04).
        incoterms: config.incoterms || "",
        country: config.country || "",
        askDeal: !config.incoterms,
        clausesUrl: config.clausesUrl,
        reviewUrl: config.reviewUrl,
        exportUrl: config.exportUrl,
      });
      mounted = true;
    }
    // 키보드·화면낭독기 사용자를 창 안으로 데려갑니다. 첫 [data-contract-close] 는 초점을
    // 못 받는 배경이라, 닫기 **단추**를 집어야 합니다(사용성 2회차 — 초점이 안 옮겨졌습니다).
    const first = modal.querySelector("button[data-contract-close]");
    if (first) first.focus();
  }

  function close() {
    modal.hidden = true;
    document.body.classList.remove("hs_modal_open");
    // 주소의 #contract-check 를 지웁니다 — 남아 있으면 같은 링크를 다시 눌러도 열리지 않고,
    // 새로고침하면 매번 열렸습니다(사용성 2회차).
    if (location.hash === "#contract-check") {
      history.replaceState(null, "", location.pathname + location.search);
    }
    if (returnTo && returnTo.focus) returnTo.focus();
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-contract-open]")) { event.preventDefault(); open(); }
    else if (event.target.closest("[data-contract-close]")) close();
    else if (event.target.closest('a[href$="#contract-check"]')) { event.preventDefault(); open(); }
  });
  // 접힌 <details> 안의 것은 초점을 못 받습니다. 그것을 마지막 항목으로 잡아 Shift+Tab 이
  // 멈추고 Tab 이 창 밖으로 나갔습니다(사용성 3회차). 접힌 묶음의 <summary> 는 받습니다.
  function folded(el) {
    const from = el.tagName === "SUMMARY" ? el.parentElement.parentElement : el;
    return Boolean(from && from.closest("details:not([open])"));
  }
  document.addEventListener("keydown", (event) => {
    if (modal.hidden) return;
    // preventDefault — 아래에 깔린 상담 창이 같은 Esc 로 닫히지 않게(support_chat.js).
    if (event.key === "Escape") { event.preventDefault(); close(); return; }
    // Tab 이 창 밖으로 나가지 않게 가둡니다.
    if (event.key === "Tab") {
      const items = Array.from(modal.querySelectorAll(
        "button, [href], input, select, textarea, summary, [tabindex]:not([tabindex='-1'])"))
        .filter((el) => !el.disabled && el.offsetParent !== null && !folded(el));
      if (!items.length) return;
      const firstItem = items[0];
      const lastItem = items[items.length - 1];
      if (event.shiftKey && document.activeElement === firstItem) { event.preventDefault(); lastItem.focus(); }
      else if (!event.shiftKey && document.activeElement === lastItem) { event.preventDefault(); firstItem.focus(); }
    }
  });
  // 상담 답변의 "조항 문안 받기" 링크(/#contract-check)로 오면 창을 엽니다. 전에는
  // 링크가 없는 주소(/documents)라 404 였습니다.
  function openFromHash() {
    if (location.hash === "#contract-check") open();
  }
  window.addEventListener("hashchange", openFromHash);
  openFromHash();
})();
