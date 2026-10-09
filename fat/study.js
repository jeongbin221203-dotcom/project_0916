(function () {
  var CIR = ["①", "②", "③", "④"];

  function qHtml(q, n) {
    var src = q[0];
    var tag = "";
    if (src === "필수예제") tag = '<span class="src">(필수 예제)</span> ';
    else if (src && src !== "-") tag = '<span class="src">(' + src + ')</span> ';
    var h = '<div class="q"><p><b>Q' + n + '.</b> ' + tag + q[1] + '</p>';
    for (var i = 0; i < q[2].length; i++) {
      h += '<div class="opt">' + CIR[i] + ' ' + q[2][i] + '</div>';
    }
    h += '<details><summary>정답 · 해설 보기</summary><div><b>정답 ' + q[3] + '</b>' + (q[4] ? ' — ' + q[4] : '') + '</div></details></div>';
    return h;
  }

  function groupsHtml(groups, continuous) {
    var counter = 0;
    return groups.map(function (g) {
      var inner = g[1].map(function (q, i) {
        counter++;
        return qHtml(q, continuous ? counter : i + 1);
      }).join("");
      return '<details><summary>' + g[0] + ' <small>(' + g[1].length + '문제)</small></summary><div>' + inner + '</div></details>';
    }).join("");
  }

  function theoryHtml(list) {
    return list.map(function (t, i) {
      return '<details' + (i === 0 ? ' open' : '') + '><summary>' + t[0] + '</summary><div>' + t[1] + '</div></details>';
    }).join("");
  }

  function toolbar() {
    return '<div class="tools"><button type="button" class="btn" data-act="open">정답 모두 펼치기</button> <button type="button" class="btn" data-act="close">정답 모두 접기</button></div>';
  }

  function build(el, theory, basic, main, mainTitle) {
    if (!el) return;
    var total = 0;
    main.forEach(function (g) { total += g[1].length; });
    var basicCount = 0;
    basic.forEach(function (g) { basicCount += g[1].length; });
    el.innerHTML =
      '<h4>' + mainTitle.split(' ')[0] + ' 이론 정리</h4>' + theoryHtml(theory) +
      '<h4>단원별 기출문제 풀어보기 <small>(' + basicCount + '문제)</small></h4>' + toolbar() + '<div class="qset">' + groupsHtml(basic, false) + '</div>' +
      '<h4>' + mainTitle + ' <small>(' + total + '문제)</small></h4>' + toolbar() + '<div class="qset">' + groupsHtml(main, true) + '</div>' +
      '<p class="source">참고: 『2025년 전산세무2급 핵심요약 교재』 © 전산회계다윤(고다윤). 개인 학습용으로 정리함.</p>';

    el.addEventListener("click", function (e) {
      var act = e.target.getAttribute && e.target.getAttribute("data-act");
      if (!act) return;
      var set = e.target.parentNode.nextElementSibling;
      Array.prototype.forEach.call(set.querySelectorAll(".q details"), function (d) { d.open = act === "open"; });
      if (act === "open") {
        Array.prototype.forEach.call(set.querySelectorAll(":scope > details"), function (d) { d.open = true; });
      }
    });
  }

  var PAST_PAGES = {73:[6,7],74:[4,5],75:[5,6],76:[5,6],77:[4,6],78:[5,6],79:[4,6],80:[4,6],81:[4,5],82:[5,7],83:[5,7],84:[4,7],85:[3,6],86:[4,6],87:[5,6],88:[4,7],89:[5,6],90:[4,5],91:[5,7],92:[4,7]};
  function sheet(prefix, n, count) {
    var h = "";
    for (var i = 1; i <= count; i++) {
      h += '<img loading="lazy" src="past/' + prefix + n + '_' + i + '.jpg" alt="제' + n + '회 ' + (prefix === "q" ? "시험지" : "정답·해설지") + ' ' + i + '쪽" style="display:block;width:100%;max-width:760px;margin:8px auto;border:1px solid #bbb;background:#fff">';
    }
    return h;
  }
  function pastGroupsHtml(groups) {
    return groups.map(function (g) {
      var n = parseInt(g[0].replace(/\D/g, ""), 10);
      var pg = PAST_PAGES[n];
      var inner = g[1].map(function (q, i) { return qHtml(q, i + 1); }).join("");
      var raw = pg ? '<details class="rawsheet"><summary>시험지 원본 그대로 보기 (인쇄 화면)</summary><div>' + sheet("q", n, pg[0]) + '</div></details>' +
        '<details class="rawsheet"><summary>정답·해설지 원본 그대로 보기</summary><div>' + sheet("a", n, pg[1]) + '</div></details>' : "";
      return '<details><summary>' + g[0] + ' <small>(' + g[1].length + '문제)</small></summary><div>' + raw + inner + '</div></details>';
    }).join("");
  }

  function buildMock(box, groups) {
    var KEY = "fat1.mock";
    var saved = {};
    try { saved = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
    function num(g) { return parseInt(g[0].replace(/\D/g, ""), 10); }
    var opts = groups.map(function (g) {
      var n = num(g);
      return '<option value="' + n + '">' + g[0] + (saved[n] != null ? " (최근 " + saved[n] + "점)" : "") + '</option>';
    }).join("");
    box.innerHTML = '<div class="tools"><select id="mockSel">' + opts + '</select> <button type="button" class="btn" id="mockStart">실전 풀이 시작</button> <span id="mockTime" style="margin-left:8px"></span></div><div id="mockArea"></div>';
    var timer = null, sec = 0, cur = null;
    function stop() { if (timer) { clearInterval(timer); timer = null; } }
    function tick() { sec++; var m = Math.floor(sec / 60), r = sec % 60; box.querySelector("#mockTime").textContent = "경과 " + (m < 10 ? "0" : "") + m + ":" + (r < 10 ? "0" : "") + r + " / 이론 권장 15분"; }
    box.querySelector("#mockStart").addEventListener("click", function () {
      var n = parseInt(box.querySelector("#mockSel").value, 10);
      cur = groups.filter(function (g) { return num(g) === n; })[0];
      stop(); sec = 0; tick(); timer = setInterval(tick, 1000);
      var h = '<h5>' + cur[0] + ' 실무이론평가 (문항당 3점)</h5>';
      cur[1].forEach(function (q, i) {
        h += '<div class="q" data-i="' + i + '"><p><b>[' + (i + 1) + ']</b> ' + q[1] + '</p>';
        q[2].forEach(function (o, k) {
          h += '<label class="opt" style="display:block;cursor:pointer"><input type="radio" name="m' + i + '" value="' + CIR[k] + '"> ' + CIR[k] + ' ' + o + '</label>';
        });
        h += '<div class="mres"></div></div>';
      });
      h += '<p><button type="button" class="btn" id="mockSubmit">제출·채점</button></p><div id="mockScore"></div>';
      box.querySelector("#mockArea").innerHTML = h;
      box.querySelector("#mockSubmit").addEventListener("click", function () {
        stop();
        var ok = 0, un = 0;
        Array.prototype.forEach.call(box.querySelectorAll("#mockArea .q"), function (el) {
          var i = parseInt(el.getAttribute("data-i"), 10), q = cur[1][i];
          var sel = el.querySelector("input:checked");
          var res = el.querySelector(".mres");
          if (!sel) { un++; res.innerHTML = '<b style="color:#c60">미응답</b> — 정답 ' + q[3] + '<br>' + q[4]; }
          else if (sel.value === q[3]) { ok++; res.innerHTML = '<b style="color:#080">정답 ✔</b><br>' + q[4]; }
          else { res.innerHTML = '<b style="color:#c00">오답 ✘</b> (내 답 ' + sel.value + ' / 정답 ' + q[3] + ')<br>' + q[4]; }
        });
        var score = ok * 3;
        box.querySelector("#mockScore").innerHTML = '<b>' + ok + ' / ' + cur[1].length + ' 정답 · ' + score + '점 (30점 만점)</b>' + (un ? ' · 미응답 ' + un : '') + ' · 소요 ' + Math.floor(sec / 60) + '분 ' + (sec % 60) + '초';
        saved[num(cur)] = score;
        try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (e) {}
      });
    });
  }

  function buildPast(el, groups) {
    if (!el) return;
    var total = 0;
    groups.forEach(function (g) { total += g[1].length; });
    el.insertAdjacentHTML("beforeend",
      '<h4>이론 기출문제 <small>(제' + groups[groups.length - 1][0].replace(/\D/g, "") + '회~제' + groups[0][0].replace(/\D/g, "") + '회 · ' + total + '문제)</small></h4>' +
      '<div id="mockBox" class="card"><h5>실전 모의시험</h5></div>' +
      toolbar() + '<div class="qset">' + pastGroupsHtml(groups) + '</div>' +
      '<p class="source">문제·해설: 한국공인회계사회 FAT 1급 기출(실무이론평가). 그림이 있는 문제는 글로 옮겨 적었습니다. 개인 학습용.</p>');
    buildMock(el.querySelector("#mockBox"), groups);
    el.addEventListener("click", function (e) {
      var act = e.target.getAttribute && e.target.getAttribute("data-act");
      if (!act) return;
      var set = e.target.parentNode.nextElementSibling;
      Array.prototype.forEach.call(set.querySelectorAll(".q details"), function (d) { d.open = act === "open"; });
      if (act === "open") {
        Array.prototype.forEach.call(set.querySelectorAll(":scope > details"), function (d) { d.open = true; });
      }
    });
  }

  // 실기: 합격률 60% 미만 회차(+최신 92회) 따라하기, 하루 2회차
  var PRACTICE = [[[92, 19, "61.61"], [91, 21, "45.61"]], [[90, 18, "56.7"], [88, 20, "57.28"]], [[86, 20, "53.39"], [85, 20, "59.53"]], [[83, 19, "57.28"], [80, 19, "54.49"]], [[77, 18, "49.55"], [75, 20, "58.02"]]];
  function buildPractice() {
    var no = 0;
    PRACTICE.forEach(function (day, di) {
      var el = document.getElementById("praBody" + (di + 1));
      if (!el) return;
      var h = '<p class="source">원본 인쇄 화면 그대로입니다. 문제(자료설명·수행과제)를 먼저 읽고 프로그램에 직접 입력해 본 뒤, 같은 쪽 아래의 <b>수행과제 풀이</b>와 맞춰 보세요. 마지막 쪽들은 평가문제와 정답입니다.</p>';
      day.forEach(function (e) {
        no++;
        h += '<details' + (e[0] === day[0][0] ? ' open' : '') + '><summary>따라하기 ' + no + '회 · 제' + e[0] + '회 <small>(FAT 1급 합격률 ' + e[2] + '% · ' + e[1] + '쪽)</small></summary><div>';
        for (var i = 1; i <= e[1]; i++) {
          h += '<img loading="lazy" src="past/pr' + e[0] + '_' + i + '.jpg" alt="제' + e[0] + '회 실무 ' + i + '쪽" style="display:block;width:100%;max-width:760px;margin:8px auto;border:1px solid #bbb;background:#fff">';
        }
        h += '</div></details>';
      });
      el.innerHTML = h;
    });
  }
  function buildPracticeTopics(el) {
    var P = (window.STUDY || {}).practice;
    if (!el || !P) return;
    function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
    function ans(s) { return esc(s).replace(/⟦/g, '<b class="ans">').replace(/⟧/g, "</b>"); }
    function flow(lines) {
      var out = [];
      lines.forEach(function (l) {
        if (!out.length || /^(\d+\.\s|\d+\)|[①-⑨]|[-•◦·∙*]\s?|\[|\()/.test(l)) out.push(l); else out[out.length - 1] += " " + l;
      });
      return out;
    }
    function pre(lines) { return '<pre class="vsol">' + esc(lines.join("\n")) + "</pre>"; }
    function item(it) {
      var n = it[0], h = '<details><summary>제' + n + '회 · ' + esc(it[1]) + "</summary><div>";
      if (it[2].length) h += '<p><b>자료설명</b></p>' + pre(flow(it[2]));
      if (it[3].length) h += '<p><b>수행과제</b></p>' + pre(flow(it[3]));
      if (it[4].length) h += '<p><b>수행과제 풀이</b></p>' + pre(it[4]);
      h += '<details class="rawsheet"><summary>원본 화면 보기 (자료·풀이 화면 포함)</summary><div>';
      it[5].forEach(function (k) {
        h += '<img loading="lazy" src="past/pr' + n + '_' + k + '.jpg" alt="제' + n + '회 실무 ' + k + '쪽" style="display:block;width:100%;max-width:760px;margin:8px auto;border:1px solid #bbb;background:#fff">';
      });
      return h + "</div></details></div></details>";
    }
    var h = '<h4>실무 유형별 따라하기 <small>(제75~91회 PDF 정리, 92회는 따라하기 1회)</small></h4>' +
      '<p class="source">출제범위 항목별로 회차를 모았습니다. 자료설명과 수행과제를 읽고 직접 입력한 뒤 풀이와 맞춰 보세요. 풀이 화면(프로그램 캡처)은 "원본 화면 보기"에서 볼 수 있습니다.</p>';
    P.groups.forEach(function (g) {
      var cnt = 0;
      g[2].forEach(function (s) { cnt += s[1].length; });
      h += '<details><summary>' + esc(g[0]) + ' <small>(' + cnt + '건)</small></summary><div><p class="source">' + esc(g[1]) + '</p>';
      g[2].forEach(function (s) {
        if (s[0]) h += '<h5>' + esc(s[0]) + ' <small>(' + s[1].length + '건)</small></h5>';
        s[1].forEach(function (it) { h += item(it); });
      });
      h += "</div></details>";
    });
    h += '<details><summary>자료조회 <small>(평가문제 정답 포함)</small></summary><div><p class="source">부가세 조회, 자금정보 조회, 재무제표·장부 조회 문제입니다. 노란 표시가 정답입니다. 객관식은 옳지 않은 것을 고르는 유형이 많습니다.</p>';
    P.eval.forEach(function (g) {
      h += '<h5>' + esc(g[0]) + ' <small>(' + g[1].length + '문제)</small></h5>';
      g[1].forEach(function (q) {
        h += '<div class="q"><p><b>제' + q[0] + '회 ' + q[1] + '번</b> <span class="src">[' + esc(q[2]) + ']</span></p><pre class="vsol">' + ans(q[3].join("\n")) + "</pre></div>";
      });
    });
    h += '<h5>회계정보분석 <small>(회차별)</small></h5>';
    P.ana.forEach(function (a) {
      h += '<details><summary>제' + a[0] + '회</summary><div><pre class="vsol">' + esc(a[1].join("\n")) + "</pre></div></details>";
    });
    h += "</div></details>";
    var d = document.createElement("div");
    d.id = "practiceTopics";
    d.innerHTML = h;
    el.insertBefore(d, el.firstChild);
  }
  // 이론 정리 항목 제목에 출제 빈도 별표 표시 (제73~92회 이론 200문제 기준)
  function addStars(root, map) {
    if (!root) return;
    var first = null;
    Array.prototype.forEach.call(root.querySelectorAll(":scope > details > summary"), function (s) {
      var m = s.textContent.match(/^(\d+)\./);
      if (!m || !map[m[1]]) return;
      var span = document.createElement("span");
      span.className = "stars";
      span.textContent = " " + new Array(map[m[1]] + 1).join("★");
      s.appendChild(span);
      if (!first) first = s.parentNode;
    });
    if (first) {
      var p = document.createElement("p");
      p.className = "source";
      p.textContent = "★★★ 자주 출제 · ★★ 보통 · ★ 드묾 (제73~92회 이론 기출 기준)";
      root.insertBefore(p, first);
    }
  }
  var S = window.STUDY || {};
  function buildVat(el) {
    if (!el || !S.vatTheory) return;
    var n = 0;
    S.vatQ.forEach(function (g) { n += g[1].length; });
    var d = document.createElement('div');
    d.id = 'vatSection';
    d.innerHTML =
      '<h4>부가가치세 · 기출 60문제 빈출 정리</h4>' + theoryHtml(S.vatTheory) +
      '<h4>부가가치세 필수 문제 <small>(' + n + '문제)</small></h4>' + toolbar() + '<div class="qset">' + groupsHtml(S.vatQ, true) + '</div>';
    el.insertBefore(d, el.firstChild);
    el.addEventListener("click", function (e) {
      var act = e.target.getAttribute && e.target.getAttribute("data-act");
      if (!act) return;
      var set = e.target.parentNode.nextElementSibling;
      Array.prototype.forEach.call(set.querySelectorAll(".q details"), function (d2) { d2.open = act === "open"; });
    });
  }

  build(document.getElementById("finBody"), S.finTheory || [], S.finBasic || [], S.fin60 || [], "재무회계 60제");
  // 원가회계는 FAT 1급 출제범위가 아니라 화면에서 숨김 (cost-*.js 파일은 보관)
  buildVat(document.getElementById("vatBody"));
  addStars(document.getElementById("finBody"), { 1: 3, 2: 3, 3: 3, 4: 1, 5: 2, 6: 1, 7: 1, 8: 1, 9: 3, 10: 1, 11: 2 });
  addStars(document.getElementById("vatSection"), { 1: 2, 2: 3, 3: 3, 4: 3, 5: 2, 6: 3, 7: 3 });
  buildPractice();
  buildPracticeTopics(document.getElementById("praBody1"));
  buildPast(document.getElementById("pastBody"), S.pastExam || []);
})();
