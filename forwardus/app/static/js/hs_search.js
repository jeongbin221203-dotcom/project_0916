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

  // 영문·오타를 다른 낱말로 바꿔 찾았으면 목록 맨 위에 그 사실을 적습니다.
  function hsSearchedAsRow(items) {
    const meta = items.hsMeta || {};
    const {query: lastHsQuery, searched_as: lastHsSearchedAs, ai_analysis: lastHsAnalysis,
      ranking: lastHsRanking, ai_review: lastHsReview, navigation_summary: lastHsNavigation,
      partial_note: lastHsPartial, offline_note: lastHsOffline} = meta;
    let html = "";
    // 관세청이 멈춰 공개 품목표(기준일 있음)로 찾았으면 맨 위에 밝힙니다.
    if (lastHsOffline) {
      html += `<li class="ac_group ac_group_other"><b>내부 품목표로 찾았습니다</b>`
        + `<small>${escapeHtml(lastHsOffline)}</small></li>`;
    }
    if (lastHsSearchedAs) {
      html += `<li class="ac_group">"${escapeHtml(lastHsQuery)}"를 `
        + `<b>${escapeHtml(lastHsSearchedAs)}</b>로 넓혀 검색했습니다`
        + `<small>검색어 후보입니다. 성분·용도에 맞는 품목을 선택하세요.</small></li>`;
    }
    if (lastHsAnalysis?.available) {
      html += `<li class="ac_group"><b>AI 품명 해석</b><small>${escapeHtml(lastHsAnalysis.summary)}</small>`
        + `<small>${escapeHtml([lastHsAnalysis.use && `용도: ${lastHsAnalysis.use}`,
          lastHsAnalysis.material && `재질: ${lastHsAnalysis.material}`,
          lastHsAnalysis.form && `형태: ${lastHsAnalysis.form}`].filter(Boolean).join(" · "))}</small>`
        + (lastHsAnalysis.missing_details?.length
          ? `<small>추가 확인: ${escapeHtml(lastHsAnalysis.missing_details.join(" / "))}</small>` : "") + `</li>`;
    } else if (lastHsAnalysis?.message) {
      html += `<li class="ac_group"><small>${escapeHtml(lastHsAnalysis.message)}</small></li>`;
    }
    if (lastHsReview && !lastHsReview.available && lastHsReview.message) {
      html += `<li class="ac_group"><small>적합도 미확인: ${escapeHtml(lastHsReview.message)}</small></li>`;
    }
    if (lastHsRanking) {
      html += `<li class="ac_group"><b>정렬: ${escapeHtml(lastHsRanking.label)}</b>`
        + (lastHsRanking.mixed_years ? `<small>세율 기준연도가 달라 관세로 순서를 비교하지 않았습니다.</small>` : "") + `</li>`;
    }
    if (lastHsNavigation) {
      html += `<li class="ac_group"><details><summary>통계·관세 비교 기준 · ${lastHsNavigation.compared}개 후보</summary>`
        + `<small>${escapeHtml(lastHsNavigation.note)}</small>`
        + `<small>${escapeHtml(lastHsRanking?.tariff_note || "")}</small></details></li>`;
    }
    // 관세청이 아닌 곳에서 찾으면 6자리까지만 나옵니다. 신고에 그대로 못 씁니다.
    if (lastHsPartial) {
      html += `<li class="ac_group ac_group_other"><b>앞 6자리만 찾았습니다</b>`
        + `<small>${escapeHtml(lastHsPartial)}</small></li>`;
    }
    return html;
  }

  function renderHsItem(item) {
    if (item.partial) {
      return `<span class="ac_title"><b class="mono">${escapeHtml(item.code)}</b>`
        + `<span class="badge warn">6자리</span></span>`
        + `<small>${escapeHtml(item.name_en || item.name || "")}`
        + (item.from ? ` · ${escapeHtml(item.from)}` : "") + `</small>`;
    }
    // 내부 품목표에서 온 행은 기준일을 붙입니다. (AI 부호 확인에 쓴 행도 여기 해당)
    const origin = item.base_date ? `관세청 품목표 · ${item.base_date} 기준`
      : (item.source === "api" ? "관세청 HS부호" : "예시 목록");
    const sub = [item.name_en, item.weight_unit ? `중량단위 ${item.weight_unit}` : "", origin]
      .filter(Boolean).join(" · ");
    // "기타"만으로는 무슨 물건인지 모릅니다. 상위 분류를 함께 보여 줍니다.
    const pathLine = item.path?.length > 1
      ? `<small>분류: ${escapeHtml(item.path.slice(1).join(" › "))}</small>` : "";
    let stats = "";
    const nav = item.navigation;
    if (nav && nav.available) {
      stats = `<small class="hs_stats"><b>조회 품목란 ${Number(nav.count).toLocaleString()}건</b>`;
      if (nav.share !== null) stats += ` · 비교 후보 내 ${nav.share.toFixed(1)}%`
        + (nav.gap_pp > 0 ? ` · 최다 후보와 ${nav.gap_pp.toFixed(1)}%p 차이` : " · 최다 건수");
      stats += `</small><small>신고 품명 예: ` + nav.names.map((row) =>
        `${escapeHtml(row.name)} (${Number(row.count).toLocaleString()}건)`).join(" · ") + `</small>`;
    } else if (nav) {
      stats = `<small>통계 확인 불가: ${escapeHtml(nav.message)}</small>`;
    }
    const tax = item.tariff;
    if (tax?.available) {
      stats += `<small class="hs_stats">${escapeHtml(tax.country)} · ${escapeHtml(tax.label)} `
        + `<b>${escapeHtml(String(tax.rate))}%</b> · ${escapeHtml(String(tax.year))}년`
        + (tax.min != null && tax.max != null ? ` · 범위 ${tax.min}~${tax.max}%` : "") + `</small>`;
    } else if (tax) {
      stats += `<small>관세 미확인: ${escapeHtml(tax.message)}</small>`;
    }
    const relevance = item.relevance;
    const reason = relevance ? `<small><b>${escapeHtml(item.relevance_label)}</b> · ${escapeHtml(relevance.reason)}</small>`
      + (relevance.missing_details?.length ? `<small>확인할 정보: ${escapeHtml(relevance.missing_details.join(" / "))}</small>` : "") : "";
    return (item.priority ? `<span class="badge">${item.priority}순위</span> ` : "")
      + `<span class="mono">${escapeHtml(item.code)}</span>`
      + ` <b>${escapeHtml(item.name || item.name_en)}</b>${pathLine}${reason}<small>${escapeHtml(sub)}</small>${stats}`;
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

  window.ForwardusHs = { fetchHsCodes, hsSearchedAsRow, renderHsItem, hsEmptyMessage,
                         HS_AUTOCOMPLETE_OPTIONS };
})();
