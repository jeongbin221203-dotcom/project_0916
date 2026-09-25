/* 작성 중인 수출 건 — 서류 작성 ↔ 운송 계획이 같이 쓰는 초안. (모든 화면에 붙습니다)

   save(payload, source)  서류 작성에서 적은 값을 서버(/api/work-draft)에 저장합니다.
                          적을 때마다 부르면 됩니다. 잠깐 멈췄을 때 한 번만 보냅니다.
   planningPrefill()      운송 계획 화면이 칸을 미리 채울 값. 서버 값 + 이 탭에만 둔 값.

   서버에는 정해진 칸만 갑니다(work_draft_service.SHARED_FIELDS). 바이어 주소·이메일·
   이메일·담당자·Notify Party는 이 탭의 sessionStorage에만 두고 서버로 보내지 않습니다.
   바이어 주소는 서버에도 담습니다. 은행 계좌·SWIFT는 어디에도 담지 않습니다. */
(function () {
  "use strict";

  const config = window.FORWARDUS_WORK_DRAFT;
  const PRIVATE_KEY = window.ForwardusStore.key("forwardus:work-private");
  // 서버로 보내지 않고 이 탭에만 두는 칸. 바이어 주소는 2026-09부터 서버에도 담습니다.
  // (같은 바이어에게 다시 보낼 때 주소를 또 적다가 나는 오타가 B/L에 그대로 찍힙니다)
  const PRIVATE_FIELDS = ["buyer_email", "notify_party", "attention", "consignee_city_zip"];
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

  /* ----- 저장하지 못했을 때 알리기 -----
     적는 일은 막지 않습니다. 다만 조용히 버리지는 않습니다.

     예전에는 실패하면 null만 돌려주고 끝이었습니다. 세션이 만료된 채 계속
     적으면 보내는 족족 401로 버려지는데 화면은 멀쩡해 보였습니다. 나중에
     다른 화면에서 "적은 것이 없다"고 나와야 그제서야 압니다. */
  let banner = null;

  function hideBanner() {
    if (banner) banner.hidden = true;
  }

  function showBanner(why) {
    if (!banner) {
      banner = document.createElement("div");
      banner.className = "draft_alert";
      banner.setAttribute("role", "alert");
      banner.innerHTML = '<div><b>임시저장하지 못했습니다.</b>'
        + ' <span data-draft-why></span></div>'
        + '<button type="button" data-draft-retry>다시 시도</button>';
      banner.querySelector("[data-draft-retry]").addEventListener("click", () => {
        hideBanner();
        send();
      });
      document.body.appendChild(banner);
    }
    banner.querySelector("[data-draft-why]").textContent = why;
    banner.hidden = false;
  }

  // 왜 안 됐는지를 사람 말로 옮깁니다. 서버가 이유를 적어 보냈으면 그것을 씁니다.
  async function reason(response) {
    if (response.status === 401) {
      return "로그인이 풀렸습니다. 새 탭에서 로그인한 뒤 [다시 시도]를 누르세요.";
    }
    if (response.status === 403) return "이 건을 저장할 권한이 없습니다.";
    if (response.status >= 500) return `서버가 응답하지 않습니다. (${response.status})`;
    try {
      const body = await response.json();
      if (body && body.message) return body.message;
    } catch (error) { /* 이유를 못 읽으면 아래 기본 문구로 갑니다. */ }
    return `저장할 수 없는 값이 있습니다. (${response.status})`;
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
      if (!response.ok) {
        keepForRetry(body);
        showBanner(await reason(response));
        return null;
      }
      hideBanner();
      return (await response.json()).data;
    } catch (error) {
      keepForRetry(body);
      showBanner("인터넷 연결이 끊긴 것 같습니다.");
      return null;
    }
  }

  // 실패한 내용을 되돌려 둡니다. [다시 시도]가 보낼 것이 있어야 합니다.
  // 기다리는 동안 더 적었으면 그쪽이 최신이므로 덮지 않습니다.
  function keepForRetry(body) {
    if (pending === null) pending = body;
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

  // 서버에 저장해 둔 값. 이 탭에만 둔 비공개 칸(바이어 주소·연락처)을 얹어 돌려줍니다.
  async function load() {
    if (!config) return null;
    await flush();
    const response = await window.Forwardus.getJson(config.url, 10000);
    if (!response.success || !response.data || !response.data.updated_ms) return null;
    const draft = response.data;
    draft.fields = { ...draft.fields, ...readPrivate() };
    return draft;
  }

  // 임시저장 비우기. 서버와 이 탭에 둔 것을 모두 지웁니다.
  async function clear() {
    try {
      window.sessionStorage.removeItem(PRIVATE_KEY);
    } catch (error) { /* 무시 */ }
    if (!config) return;
    clearTimeout(timer);
    pending = null;
    timer = null;
    try {
      await fetch(config.url, { method: "DELETE" });
    } catch (error) { /* 서버가 안 되면 이 탭 것만 지웁니다. */ }
  }

  async function planningPrefill() {
    if (!config) return null;
    await flush();
    const response = await window.Forwardus.getJson(config.planningUrl, 10000);
    if (!response.success || !response.data || !response.data.savedAt) return null;
    const draft = response.data;
    const kept = readPrivate();
    ["buyer_email", "notify_party", "attention", "consignee_city_zip"].forEach((name) => {
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
    // 여기서는 실패해도 알릴 수 없습니다. 화면이 이미 사라지는 중이라 배너를
    // 띄울 자리가 없습니다. 돌아와서 다시 적으면 그때 저장됩니다.
    fetch(config.url, { method: "PUT", body: blob, keepalive: true,
                        headers: { "Content-Type": "application/json" } }).catch(() => {});
    pending = null;
    timer = null;
  });

  window.ForwardusWorkDraft = { save, flush, load, clear, planningPrefill, PRIVATE_FIELDS };
})();
