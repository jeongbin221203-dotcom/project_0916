/* 작성 중인 수출 건 — 서류 작성 ↔ 운송 계획이 같이 쓰는 초안. (모든 화면에 붙습니다)

   save(payload, source)  서류 작성에서 적은 값을 서버(/api/work-draft)에 저장합니다.
                          적을 때마다 부르면 됩니다. 잠깐 멈췄을 때 한 번만 보냅니다.
   planningPrefill()      운송 계획 화면이 칸을 미리 채울 값. 서버 값 + 이 탭에만 둔 값.

   서버에는 정해진 칸만 갑니다(work_draft_service.SHARED_FIELDS). 바이어 주소·이메일·
   담당자·Notify Party는 이 탭의 sessionStorage에만 두고 서버로 보내지 않습니다. */
(function () {
  "use strict";

  const config = window.FORWARDUS_WORK_DRAFT;
  const PRIVATE_KEY = "forwardus:work-private";
  const PRIVATE_FIELDS = ["buyer_address", "buyer_email", "notify_party", "attention",
                          "consignee_city_zip"];
  const DELAY_MS = 700;
  let timer = null;
  let pending = null;

  function readPrivate() {
    try {
      return JSON.parse(window.sessionStorage.getItem(PRIVATE_KEY) || "{}") || {};
    } catch (error) {
      return {};
    }
  }

  function keepPrivate(fields) {
    const kept = readPrivate();
    PRIVATE_FIELDS.forEach((name) => {
      if (fields && fields[name]) kept[name] = String(fields[name]);
    });
    try {
      window.sessionStorage.setItem(PRIVATE_KEY, JSON.stringify(kept));
    } catch (error) { /* 저장 공간을 못 쓰면 서버 값만 이어 씁니다. */ }
  }

  // 서버로 보낼 것에서 비공개 칸을 뺍니다. (서버도 한 번 더 거릅니다)
  function withoutPrivate(fields) {
    const copy = { ...(fields || {}) };
    PRIVATE_FIELDS.forEach((name) => { delete copy[name]; });
    return copy;
  }

  async function send() {
    const body = pending;
    pending = null;
    timer = null;
    if (!body || !config) return null;
    try {
      const response = await fetch(config.url, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      return response.ok ? (await response.json()).data : null;
    } catch (error) {
      return null;           // 저장이 안 돼도 적는 일은 막지 않습니다.
    }
  }

  function save(payload, source = "document") {
    if (!config || !payload) return;
    const fields = payload.fields || payload;
    keepPrivate(fields);
    pending = { source, fields: withoutPrivate(fields), items: payload.items || [] };
    clearTimeout(timer);
    timer = setTimeout(send, DELAY_MS);
  }

  function flush() {
    if (!timer) return Promise.resolve(null);
    clearTimeout(timer);
    return send();
  }

  async function planningPrefill() {
    if (!config) return null;
    await flush();
    const response = await window.Forwardus.getJson(config.planningUrl, 10000);
    if (!response.success || !response.data || !response.data.savedAt) return null;
    const draft = response.data;
    const kept = readPrivate();
    ["buyer_address", "buyer_email", "notify_party"].forEach((name) => {
      if (kept[name] && !draft.fields[name]) draft.fields[name] = kept[name];
    });
    return draft;
  }

  // 화면을 떠나기 직전에 적어 둔 것이 있으면 바로 보냅니다. (운송 계획으로 넘어갈 때)
  window.addEventListener("pagehide", () => {
    if (!timer || !pending || !config) return;
    clearTimeout(timer);
    const blob = new Blob([JSON.stringify(pending)], { type: "application/json" });
    // sendBeacon은 POST만 됩니다. 같은 내용을 PUT으로 보내기 위해 keepalive fetch를 씁니다.
    fetch(config.url, { method: "PUT", body: blob, keepalive: true,
                        headers: { "Content-Type": "application/json" } }).catch(() => {});
    pending = null;
    timer = null;
  });

  window.ForwardusWorkDraft = { save, flush, planningPrefill, PRIVATE_FIELDS };
})();
