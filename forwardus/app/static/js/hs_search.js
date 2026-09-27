/* HS부호 찾기. 운송 계획 [3. Cargo]와 HS CODE 간편 검색 창이 같이 씁니다.
   planning.js 안에 있던 것을 그대로 옮겼습니다. 조회 창구(/planning/api/hs-codes),
   AI 품명 해석·적합도, 건수·관세 비교, 그리는 모양이 두 곳에서 똑같아야 합니다.
   바뀌는 것은 "어느 나라 기준으로, 어떤 순서로"뿐이라 그것만 밖에서 받습니다. */
(function () {
  "use strict";

  const { escapeHtml, getJson } = window.Forwardus;

  // AI 해석·적합도·통계·관세를 한 번에 비교해 오래 걸립니다. 20초로 끊으면 결과를 못 봅니다.
  const HS_TIMEOUT_MS = 120000;

  // 품명(한글·영문)이나 HS부호로 관세청에서 찾습니다.
  // where = { url, country, order } — Cargo 화면은 도착지와 정렬 칸에서, 간편 검색 창은 창의 칸에서.
  async function fetchHsCodes(query, fallback, where) {
    const text = (query || "").trim() || (fallback || "").trim();
    if (text.length < 2) return Object.assign([], { hsMeta: { query: text } });
    const response = await getJson(`${where.url}?${new URLSearchParams({ q: text,
      country: where.country || "", order: where.order || "frequency" })}`, HS_TIMEOUT_MS);
    const items = response.success ? response.data.map((item) => ({ ...item, source: response.source })) : [];
    return Object.assign(items, { hsMeta: { ...response, query: text,
      error: response.success ? "" : (response.message || "관세청 조회에 실패했습니다.") } });
  }

  // ? 아이콘. 마우스를 올리거나 키보드·탭으로 고르면 자세한 설명이 뜹니다.
  // 화면에는 핵심만 두고, 긴 설명은 여기로 옮깁니다. lines는 빈 값을 건너뜁니다.
  function infoTip(title, lines, { start = false } = {}) {
    const body = lines.filter(Boolean).map((line) => `<p>${escapeHtml(line)}</p>`).join("");
    if (!body) return "";
    return `<span class="info_tip${start ? " start" : ""}" tabindex="0" role="button" aria-label="${escapeHtml(title)} 자세히">`
      + `<i aria-hidden="true">i</i><span class="info_tip_body" role="tooltip">`
      + `<b>${escapeHtml(title)}</b>${body}</span></span>`;
  }

  const tipPopup = document.createElement("div");
  tipPopup.className = "cargo_tip_popup";
  tipPopup.id = "cargo-detail-tip";
  tipPopup.setAttribute("role", "tooltip");
  tipPopup.hidden = true;
  document.body.append(tipPopup);
  let tipOwner = null;
  let tipTimer;
  function hideTip() {
    tipPopup.hidden = true;
    tipOwner?.removeAttribute("aria-describedby");
    tipOwner = null;
  }
  function showTip(owner) {
    clearTimeout(tipTimer);
    if (tipOwner !== owner) hideTip();
    tipOwner = owner;
    tipPopup.innerHTML = owner.querySelector(".info_tip_body").innerHTML;
    tipPopup.hidden = false;
    owner.setAttribute("aria-describedby", tipPopup.id);
    const box = owner.getBoundingClientRect();
    tipPopup.style.left = `${Math.max(8, Math.min(box.right - tipPopup.offsetWidth, innerWidth - tipPopup.offsetWidth - 8))}px`;
    tipPopup.style.top = `${Math.max(8, Math.min(box.bottom + 6, innerHeight - tipPopup.offsetHeight - 8))}px`;
  }
  document.addEventListener("pointerover", event => {
    const owner = event.target.closest(".info_tip");
    if (owner) showTip(owner);
    else if (tipPopup.contains(event.target)) clearTimeout(tipTimer);
  });
  document.addEventListener("pointerout", event => {
    if (event.target.closest(".info_tip") || tipPopup.contains(event.target)) {
      clearTimeout(tipTimer);
      tipTimer = setTimeout(hideTip, 180);
    }
  });
  document.addEventListener("focusin", event => {
    const owner = event.target.closest(".info_tip");
    if (owner) showTip(owner); else hideTip();
  });
  document.addEventListener("click", event => {
    const owner = event.target.closest(".info_tip");
    if (owner) showTip(owner); else if (!tipPopup.contains(event.target)) hideTip();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") hideTip();
    if (["Enter", " "].includes(event.key) && event.target.closest(".info_tip")) {
      event.preventDefault(); showTip(event.target.closest(".info_tip"));
    }
  });
  document.addEventListener("scroll", event => { if (!tipPopup.contains(event.target)) hideTip(); }, true);
  window.addEventListener("resize", hideTip);

  // 영문·오타를 다른 낱말로 바꿔 찾았으면 목록 맨 위에 그 사실을 적습니다.
  function hsSearchedAsRow(items) {
    const m = items.hsMeta || {};
    const analysis = m.ai_analysis;
    const notes = [m.searched_as && `확장 검색: ${m.searched_as}`, analysis?.summary,
      analysis?.missing_details?.length && `추가 확인: ${analysis.missing_details.join(" / ")}`,
      m.offline_note, m.ai_review?.message, m.ranking?.label,
      m.ranking?.mixed_years && "기준연도가 달라 관세 순위를 비교하지 않았습니다.",
      m.navigation_summary?.note, m.ranking?.tariff_note];
    return `<li class="ac_group hs_summary"><span>후보 ${items.length}개 · 적합도 우선</span>`
      + infoTip("검색·비교 기준", notes)
      + `<small>초록 높음 · 노랑 조건 확인 · 빨강 낮음 · 회색 미확인</small>`
      + (m.offline_note ? `<small>내부 품목표 기준</small>` : "")
      + (m.partial_note ? `<small>HS 6자리만 조회됨 · 신고용 부호 확인 필요</small>` : "") + `</li>`;
  }

  function renderHsItem(item) {
    const relevance = item.relevance || {};
    const match = ["high", "medium", "low"].includes(relevance.match) ? relevance.match : "unknown";
    const labels = {high: "적합도 높음", medium: "조건 확인", low: "관련성 낮음", unknown: "미확인"};
    const nav = item.navigation;
    const tax = item.tariff;
    const path = item.path?.slice(1).join(" · ");
    const notes = [relevance.reason,
      relevance.missing_details?.length && `확인할 정보: ${relevance.missing_details.join(" / ")}`,
      path && `분류: ${path}`, item.name_en,
      item.base_date ? `관세청 품목표 · ${item.base_date} 기준` : (item.source === "api" ? "관세청 HS부호" : "예시 목록"),
      nav?.available && `조회 품목란 ${Number(nav.count).toLocaleString()}건` ,
      nav?.available && nav.share != null && `비교 후보 내 ${nav.share.toFixed(1)}% (적합 확률 아님)`,
      nav?.names?.length && `신고 품명 예: ${nav.names.map(row => row.name).join(" · ")}`,
      nav && !nav.available && nav.message,
      tax?.available && `${tax.country} · ${tax.label} · ${tax.year}년 · 범위 ${tax.min ?? "—"}~${tax.max ?? "—"}%`,
      tax && !tax.available && tax.message];
    return `<div class="hs_candidate match_${match}"><div class="hs_candidate_head">`
      + `<span class="mono">${escapeHtml(item.code)}</span><span class="hs_match">${item.partial ? "6자리 · 확인 필요" : labels[match]}</span>`
      + infoTip("분류 근거·통계", notes) + `</div>`
      + `<b class="hs_name">${escapeHtml(item.name || item.name_en || "품목명 미확인")}</b>`
      + (path ? `<span class="hs_path">${escapeHtml(path)}</span>` : "")
      + `<div class="hs_metrics">${item.priority ? `${item.priority}순위` : ""}`
      + (tax?.available ? ` · ${escapeHtml(tax.country)} MFN 평균 ${escapeHtml(String(tax.rate))}%` : "")
      + (relevance.missing_details?.length ? ` · ${escapeHtml(relevance.missing_details[0])}` : "") + `</div></div>`;
  }

  function hsEmptyMessage(items) {
    const {query: lastHsQuery = "", error: lastHsError, ai_analysis: lastHsAnalysis} = items.hsMeta || {};
    if (lastHsError) return lastHsError;
    if (lastHsAnalysis?.missing_details?.length) return `후보를 찾으려면 확인이 필요합니다: ${lastHsAnalysis.missing_details.join(" / ")}`;
    if (lastHsQuery.length === 1) return "품명을 두 글자 이상 입력하세요.";
    const digits = lastHsQuery.replace(/[.\-\s]/g, "");
    if (/^\d+$/.test(digits) && digits.length !== 10) {
      return "HS부호는 10자리를 모두 입력해야 조회됩니다. 품명으로 찾아보세요.";
    }
    if (!lastHsQuery) return "품명(예: 립스틱, 샴푸) 또는 HS부호 10자리를 입력하세요.";
    return `"${lastHsQuery}" 검색 결과가 없습니다.`
      + " 한글·영문 모두 됩니다. 더 일반적인 낱말로 적어보세요. (예: 가죽 가방 → 가방)";
  }

  // Cargo 화면 첫 품목의 HS 칸과 같은 설정. 간편 검색 창도 이것을 씁니다.
  const HS_AUTOCOMPLETE_OPTIONS = {
    leadRow: hsSearchedAsRow,
    keepOpen: true,
    delayMs: 650,
    loadingMessage: "AI 품명 해석·후보 적합도·건수·관세를 비교 중…",
    emptyMessage: hsEmptyMessage,
  };

  window.ForwardusHs = { fetchHsCodes, hsSearchedAsRow, renderHsItem, hsEmptyMessage, infoTip,
                         HS_AUTOCOMPLETE_OPTIONS };
})();
