/* 왼쪽 사이드바. 모든 화면에 붙습니다. (base.html → _sidebar.html)
   원래 시작 화면(home.js)에만 있던 것을 옮겼습니다. 접힘/펼침 상태는 localStorage에
   남아서 화면을 옮겨도 그대로입니다. */
(function () {
  "use strict";

  if (!document.querySelector(".home_rail")) return;

  // 드로어가 덮을 수 있는 가운데 내용. 시작 화면은 대화 칸, 다른 화면은 본문입니다.
  function content() {
    return document.querySelector("[data-home-center]") || document.querySelector(".app_stage > main");
  }

  /* ----- 왼쪽 사이드바: 아이콘 레일 ↔ 펼침 드로어 -----
     기본은 접힘(아이콘만 있는 60px 레일)입니다. 맨 위 ☰를 누르면 드로어가 164px로
     미끄러져 나오며 가운데를 밀지 않고 덮습니다. 상태는 isSidebarExpanded(boolean)로 두고
     localStorage에 기억해 새로고침·화면 이동 뒤에도 그대로입니다.
     (그리기 전에 base.html 머리의 짧은 스크립트가 같은 값을 먼저 붙입니다) */
  const RAIL_KEY = "isSidebarExpanded";
  const railToggle = document.querySelector("[data-rail-toggle]");
  const railInner = document.querySelector(".rail_inner");
  let isSidebarExpanded = document.documentElement.classList.contains("rail_expanded");

  function setSidebarExpanded(expanded, { save = true } = {}) {
    isSidebarExpanded = expanded;
    document.documentElement.classList.toggle("rail_expanded", expanded);
    if (railToggle) {
      const label = expanded ? "사이드바 닫기" : "사이드바 열기";
      railToggle.setAttribute("aria-expanded", expanded ? "true" : "false");
      railToggle.setAttribute("aria-label", label);
      railToggle.dataset.tip = label;
    }
    if (save) {
      try {
        window.localStorage.setItem(RAIL_KEY, expanded ? "true" : "false");
      } catch (error) { /* 저장 공간을 못 쓰면 이 화면에서만 바뀝니다. */ }
    }
  }

  // 드로어가 가운데 내용을 실제로 덮고 있는지. (넓은 화면에서는 가운데가 멀어 덮지 않습니다)
  function drawerCovers(target) {
    if (!railInner || !target) return false;
    return railInner.getBoundingClientRect().right > target.getBoundingClientRect().left;
  }

  if (railToggle) {
    setSidebarExpanded(isSidebarExpanded, { save: false });
    railToggle.addEventListener("click", () => setSidebarExpanded(!isSidebarExpanded));
    // 드로어가 내용을 덮고 있을 때만, 바깥을 누르면 닫습니다. 덮지 않으면 열어 둔 채 씁니다.
    document.addEventListener("click", (event) => {
      if (!isSidebarExpanded || railInner.contains(event.target)) return;
      if (event.target.closest("[data-fx-modal], [data-hs-modal], [data-dp-modal]")) return;
      if (drawerCovers(content())) setSidebarExpanded(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && isSidebarExpanded && drawerCovers(content())
          && !document.querySelector(".fx_modal:not([hidden]), .hs_modal:not([hidden]), .dp_modal:not([hidden])")) {
        setSidebarExpanded(false);
        railToggle.focus();
      }
    });
  }

  /* ----- 왼쪽 줄에서 옆으로 펼치는 것들 ----- */
  // 내용이 있는 항목(최근 Shipment)은 좁은 줄에 넣을 수 없어 옆으로 펼칩니다.
  // (환율은 옆으로 펼치지 않고 환율 센터 창을 엽니다. fx_center.js)
  const flyouts = Array.from(document.querySelectorAll("[data-rail-flyout]"));

  /* 판은 fixed라 자리를 여기서 잡아 줍니다. (왜 fixed인지는 shell.css 참고 —
     레일 안쪽 판이 overflow-x: hidden이라 absolute로는 잘려 안 보였습니다) */
  const EDGE = 8;        // 화면 가장자리에서 띄우는 간격
  const LEAST = 180;     // 이보다 낮아지면 목록이 한 줄도 안 보입니다

  function place(box) {
    const flyout = box.querySelector(".rail_flyout");
    const rect = box.querySelector("button").getBoundingClientRect();
    const wide = window.innerWidth > 860;
    // 자연스러운 높이를 먼저 잽니다. 앞서 걸어 둔 한도가 남아 있으면 잘못 잽니다.
    flyout.style.maxHeight = "";
    const width = flyout.offsetWidth || 310;
    const height = flyout.offsetHeight || 0;
    let left = wide ? rect.right + 10 : rect.right - width;
    let top = wide ? rect.top : rect.bottom + EDGE;
    // 아래로 다 못 들어가면 **위로 더 올려** 자리를 넓게 씁니다. 단추 높이에
    // 맞춰 두면 목록이 길 때 화면 아래에서 잘린 채로만 보입니다.
    if (wide && height > window.innerHeight - top - EDGE) top = EDGE;
    // 화면 밖으로 나가지 않게 안으로 당깁니다.
    left = Math.max(EDGE, Math.min(left, window.innerWidth - width - EDGE));
    top = Math.max(EDGE, Math.min(top, window.innerHeight - height - EDGE));
    flyout.style.left = `${left}px`;
    flyout.style.top = `${top}px`;
    // **남은 자리**만큼만 높이를 줍니다. 화면 높이(100vh)로 잡아 두었더니,
    // 판이 화면 가운데쯤에서 시작할 때 아래가 잘리고 굴릴 수도 없었습니다.
    // 최근 Shipment가 세 건째부터 안 보였습니다. (2026-09-26)
    flyout.style.maxHeight = `${Math.max(LEAST, window.innerHeight - top - EDGE)}px`;
  }

  function setFlyout(box, open) {
    const flyout = box.querySelector(".rail_flyout");
    flyout.hidden = !open;
    if (open) place(box);
    box.querySelector("button").setAttribute("aria-expanded", open ? "true" : "false");
  }

  flyouts.forEach((box) => {
    box.querySelector("button").addEventListener("click", (event) => {
      event.stopPropagation();
      const opening = box.querySelector(".rail_flyout").hidden;
      flyouts.forEach((other) => setFlyout(other, other === box && opening));
    });
  });
  // 바깥을 누르거나 Esc를 누르면 닫습니다.
  document.addEventListener("click", (event) => {
    flyouts.forEach((box) => { if (!box.contains(event.target)) setFlyout(box, false); });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") flyouts.forEach((box) => setFlyout(box, false));
  });
  // 화면이 바뀌면 열려 있는 판의 자리를 다시 잡습니다. fixed라 따라오지 않습니다.
  const replace = () => flyouts.forEach((box) => {
    if (!box.querySelector(".rail_flyout").hidden) place(box);
  });
  window.addEventListener("resize", replace);
  window.addEventListener("scroll", replace, { passive: true });
})();
