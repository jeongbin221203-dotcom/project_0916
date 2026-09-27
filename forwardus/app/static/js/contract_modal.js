/* 계약서 조항 점검 창 열고 닫기. 어느 화면에서나 [data-contract-open]이면 뜹니다.
   (HS CODE 창과 같은 틀·같은 클래스를 씁니다. 창마다 모양이 다르면 같은 것인지 알 수 없습니다) */
(function () {
  "use strict";

  const modal = document.querySelector("[data-contract-modal]");
  const host = modal && modal.querySelector("[data-contract-panel]");
  const config = window.FORWARDUS_CONTRACT;
  if (!modal || !host || !config) return;

  let mounted = false;

  function open() {
    modal.hidden = false;
    document.body.classList.add("hs_modal_open");
    // 처음 열 때 한 번만 그립니다. 다시 열어도 앞서 본 결과가 남아 있습니다.
    if (!mounted && window.ForwardusContractClauses) {
      window.ForwardusContractClauses.mount(host, {
        incoterms: (window.FORWARDUS_CONTRACT.incoterms || ""),
        clausesUrl: config.clausesUrl,
        reviewUrl: config.reviewUrl,
        exportUrl: config.exportUrl,
      });
      mounted = true;
    }
  }

  function close() {
    modal.hidden = true;
    document.body.classList.remove("hs_modal_open");
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-contract-open]")) { event.preventDefault(); open(); }
    else if (event.target.closest("[data-contract-close]")) close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) close();
  });
})();
