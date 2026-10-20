/* 小洛探探 SpriteLens — 前端壳（原生 JS，页面渐进迁 Vue）
 *
 * 数据来源：本地服务 REST（初始聚合）+ WebSocket（增量推送）。
 * token 经 URL fragment 下发，存 sessionStorage 后从地址栏清除。
 */
(function () {
  "use strict";

  /* ---------- token 与请求 ---------- */
  var TOKEN_KEY = "spritelens.localToken";

  function readToken() {
    var hash = window.location.hash || "";
    var matched = hash.match(/token=([^&]+)/);
    if (matched) {
      var value = decodeURIComponent(matched[1]);
      try { sessionStorage.setItem(TOKEN_KEY, value); } catch (e) { /* 隐私模式忽略 */ }
      history.replaceState(null, "", window.location.pathname);
      return value;
    }
    try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; }
  }

  var TOKEN = readToken();

  function api(path, options) {
    var opts = options || {};
    var headers = { "X-Local-Token": TOKEN };
    if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; }
    return fetch(path, {
      method: opts.method || "GET",
      headers: headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: opts.signal
    }).then(function (response) {
      if (!response.ok) {
        return response.json().catch(function () { return {}; }).then(function (data) {
          throw new Error(data.message || data.error || ("HTTP " + response.status));
        });
      }
      return response.json();
    });
  }

  // 关窗兜底：普通 fetch 会随 WebView 关闭被丢弃，用 keepalive 让浏览器把请求送出。
  // 不能用 navigator.sendBeacon：它无法携带 X-Local-Token，会被服务端拒绝。
  function flushBeacon(path, body) {
    try {
      fetch(path, { method: "POST", keepalive: true,
        headers: { "X-Local-Token": TOKEN, "Content-Type": "application/json" },
        body: JSON.stringify(body) }).catch(function () {});
      return true;
    } catch (e) { return false; }
  }

  function query(params) {
    var parts = [];
    Object.keys(params).forEach(function (key) {
      var value = params[key];
      if (value === "" || value === null || value === undefined) { return; }
      parts.push(encodeURIComponent(key) + "=" + encodeURIComponent(value));
    });
    return parts.length ? ("?" + parts.join("&")) : "";
  }

  var accountRequests = window.SpriteLensAccountRequests.create(api);
  var petFilters = null;
  var petInventory = null;
  var eggBoxPage = null;
  var eggBoxPageGeneration = 0;
  var eggBoxVersion = -1;
  var homePage = null;
  var homePageGeneration = 0;
  var homeVersion = -1;
  var breederLibrary = window.SpriteLensBreederLibrary.create({
    load: function (params) { return accountRequests.request("breeder-library", "/api/breeder-library" + query(params)); },
    cancel: function () { accountRequests.cancel("breeder-library"); },
    context: function () { return accountRequests.petContext(); },
    openPet: function (gid) { petFilters.reset(); switchPage("pets", gid); }
  });
  var breedingPlanner = window.SpriteLensBreedingPlanner.create({
    request: function (path, body) { return accountRequests.request("planner", "/api/breeding-planner/" + path,
      body === undefined ? {} : { method: "POST", body: body }); },
    cancel: function () { accountRequests.cancel("planner"); },
    // 关窗兜底：见 flushBeacon（keepalive 请求，能带本地令牌头）。
    flush: function (path, body) { return flushBeacon("/api/breeding-planner/" + path, body); },
    context: function () { return accountRequests.petContext(); },
    openPet: function (gid) { petFilters.reset(); switchPage("pets", gid); }
  });
  var collectionLines = window.SpriteLensCollectionLines.create({
    load: function (settings) { return accountRequests.request("collection-lines", "/api/collection-lines" + query({
      goal: settings.goal, sound: settings.sound, full_weight: Number(settings.full_weight),
      colorful: Number(settings.colorful), ignore_missing_male: Number(settings.ignore_missing_male)
    })); },
    cancel: function () { accountRequests.cancel("collection-lines"); },
    uid: function () { return accountRequests.petContext().uid; },
    openPet: function (gid) { petFilters.reset(); switchPage("pets", gid); }
  });
  window.addEventListener("pagehide", function () {
    eggBoxPageGeneration++;
    homePageGeneration++;
    collectionLines.unmount();
    breederLibrary.unmount();
    breedingPlanner.unmount();
    if (eggBoxPage) { eggBoxPage.unmount(); eggBoxPage = null; }
    if (homePage) { homePage.unmount(); homePage = null; }
    if (petInventory) { petInventory.unmount(); }
    if (petFilters) { petFilters.unmount(); }
    eggDex.unmount();
    handbookPage.unmount();
    colorsPage.unmount();
  });

  /* ---------- 小工具 ---------- */
  var $ = function (id) { return document.getElementById(id); };

  function esc(text) {
    return String(text === null || text === undefined ? "" : text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function toast(message, bad) {
    var layer = $("toast-layer");
    var node = document.createElement("div");
    node.className = "toast" + (bad ? " bad" : "");
    node.textContent = message;
    layer.appendChild(node);
    setTimeout(function () { node.remove(); }, 3600);
  }

  window.SpriteLensAccountCard.init({
    api: api,
    notify: toast,
    onState: renderState
  });

  function levelColor(level) {
    if (level >= 60) { return "#d08a1e"; }
    if (level >= 40) { return "#7a5cc4"; }
    if (level >= 20) { return "#2f8fb5"; }
    return "#4c8f7a"; 
  }

  var TYPE_FALLBACK = "#6b8188";

  /* 解码树着色：`名字 [类型] = 值` 与 `└ 文本: ...` 分色（先转义再套 span，避免注入） */
  function colorizeDecoded(text) {
    var safe = esc(text);
    return safe
      .replace(/^([^\[\n=]+) \[([^\]]+)\] = (.*)$/gm,
        '<span class="tok-name">$1</span>[<span class="tok-type">$2</span>] = <span class="tok-value">$3</span>')
      .replace(/^(\s*└ 文本: )(.*)$/gm,
        '<span class="tok-leaf">$1</span><span class="tok-text">$2</span>');
  }

  /* ---------- 页面状态 ---------- */
  var state = {
    page: "overview",
    events: [],
    selectedEventIndex: null,
    capture: null
  };

  /* ---------- 导航 ---------- */
  function switchPage(name, revealGid) {
    if (name === "overview") { return; }
    if (state.page === name) {
      if (name === "handbook" && revealGid) { handbookPage.load(revealGid); }
      if (name === "egg-dex" && revealGid) { eggDex.load(revealGid); }
      return;
    }
    if (name === "pets" || name === "egg-box") { $("page-" + name).classList.add("page-cached"); }
    if (state.page === "egg-box" && name !== "egg-box") { pauseEggBoxPage(); }
    else { accountRequests.cancel(state.page); }
    if (state.page === "home" && name !== "home" && homePage) { homePage.pause(); }
    if (state.page === "collection-lines") { collectionLines.pause(); }
    if (state.page === "planner") { breedingPlanner.pause(); }
    if (state.page === "breeder-library") {
      breederLibrary.pause();
    }
    if (state.page === "pets") {
      petInventory.pause(); petFilters.pause();
    }
    if (state.page === "egg-dex") { eggDex.leave(); }
    if (state.page === "handbook") { handbookPage.leave(); }
    if (state.page === "colors") { colorsPage.leave(); }
    window.SpriteLensUI.closeDetail(false, true);
    state.page = name;
    $("page-title").textContent = document.querySelector('.nav-item[data-page="' + name + '"]').textContent.trim();
    document.querySelectorAll(".page").forEach(function (node) {
      node.classList.toggle("active", node.id === "page-" + name);
    });
    document.querySelectorAll(".nav-item").forEach(function (node) {
      node.classList.toggle("active", node.dataset.page === name);
      if (node.dataset.page === name) { node.setAttribute("aria-current", "page"); }
      else { node.removeAttribute("aria-current"); }
    });
    if (name === "pets") {
      petFilters.activate();
      if (revealGid) { petInventory.reveal(revealGid).catch(function (err) { toast("精灵定位失败：" + err.message, true); }); }
      else { loadPets(false, true); }
    }
    if (name === "handbook") { handbookPage.load(revealGid); }
    if (name === "colors") { colorsPage.load(); }
    if (name === "egg-dex") { eggDex.load(revealGid); }
    if (name === "egg-box") { loadEggBoxPage(true); }
    if (name === "male-matrix") { loadMaleMatrix(); }
    if (name === "home") { loadHome(true); }
    if (name === "collection-lines") { collectionLines.load(); }
    if (name === "breeder-library") { breederLibrary.load(); }
    if (name === "planner") { breedingPlanner.load(); }
    if (name === "flowers") { loadFlowers(); }
    if (name === "events") { loadEvents(); }
    if (name === "capture") { loadCapture(); }
  }

  document.querySelectorAll(".nav-item").forEach(function (node) {
    node.addEventListener("click", function () { switchPage(node.dataset.page); });
  });

  /* ---------- 概览 ---------- */
  function renderOverview(data) {
    var stats = data.stats || {};
    $("ov-total").textContent = stats.total || 0;
    $("ov-maxed").textContent = stats.maxed || 0;
    $("ov-maxlv").textContent = stats.max_level || 0;

    renderTypeDist(stats.types || []);

    var accounts = data.accounts || [];
    $("ov-accounts").innerHTML = accounts.length
      ? accounts.map(function (item) {
          return '<div class="account-row"><b>' + esc(item.name || "未命名")
            + '</b><span>uid ' + esc(item.uid) + '</span></div>';
        }).join("")
      : '<span class="muted">暂无历史账号</span>';

    renderRole(data.identity, data.cached_identity);
    renderOverviewSide(data.identity);
  }

  /* 概览右栏：当前账号 + 采集状态（与角色识别结果、采集快照联动） */
  function renderOverviewSide(identity) {
    if (!$("ov-account")) { return; }
    if (identity) {
      $("ov-account").innerHTML = '<b>' + esc(identity.name || "未知角色") + "</b>"
        + (identity.level ? " · Lv" + identity.level : "")
        + '<span class="muted">（uid ' + identity.uid + "）</span>";
      $("ov-account-hint").textContent = "来自登录时该角色自身信息推送";
    } else {
      $("ov-account").textContent = "尚未识别账号";
      $("ov-account-hint").textContent = "登录游戏进入世界后自动识别";
    }
  }

  function renderOverviewCapture(capture) {
    if (!capture || !$("ov-capture")) { return; }
    var running = !!capture.running;
    $("ov-capture").innerHTML = running
      ? '<b class="positive">采集中</b> · 原始流 ' + (capture.raw_chunks || 0) + " 段 · 解密成功 "
        + (capture.decrypt_ok || 0)
      : '<b>未启动</b>';
    if (capture.last_error) {
      $("ov-capture").innerHTML = '<b class="negative">启动失败</b> · ' + esc(capture.last_error);
      $("ov-capture-hint").textContent = "检查网卡选择与 Npcap 安装状态";
    } else if (running) {
      $("ov-capture-hint").textContent = capture.any_key
        ? "会话密钥已就绪，事件与宠物数据实时入库"
        : "尚未获取会话密钥：若游戏已登录，请退回登录界面重新进入";
    } else {
      $("ov-capture-hint").textContent = "在「采集与设置」页选择网卡并开始采集";
    }
  }

  /* 系别分布：横向条形图（每行 名字 / 条 / 数量），条色取系别主题色 */
  function renderTypeDist(types) {
    if (!types.length) {
      $("ov-types").innerHTML = '<span class="muted">暂无数据</span>';
      return;
    }
    var peak = types.reduce(function (max, item) { return Math.max(max, item.count); }, 1);
    $("ov-types").innerHTML = types.map(function (item) {
      var color = item.color || TYPE_FALLBACK;
      var width = Math.max(4, Math.round((item.count / peak) * 100));
      return '<div class="type-row"><span>' + esc(item.name) + "</span>"
        + '<span class="type-track"><i style="width:' + width + "%;background:" + color + '"></i></span>'
        + "<b>" + item.count + "</b></div>";
    }).join("");
  }

  /* ---------- 顶栏状态 ---------- */
  function renderRole(identity, cached) {
    window.SpriteLensAccountCard.render(identity, cached);
  }

  function setPill(id, text, tone) {
    var node = $(id);
    node.textContent = text;
    node.className = "status-pill " + (tone || "idle");
  }

  function resetAccountViews() {
    collectionLines.resetAccount();
    breederLibrary.resetAccount();
    breedingPlanner.resetAccount();
    if (state.page !== "egg-dex") { window.SpriteLensUI.closeDetail(false, true); }
    petInventory.resetAccount(); petFilters.resetAccount(); state._petsVersion = -1;
    handbookPage.resetAccount();
    colorsPage.resetAccount();
    eggBoxVersion = -1;
    if (eggBoxPage) { eggBoxPage.resetAccount(); }
    homeVersion = -1;
    if (homePage) { homePage.resetAccount(); }
    flowerState.data = { available: false }; flowerState.version = -1; renderFlowers();
    mmState.data = null; mmState.selected = null;
    ["mm-matrix", "bl-male", "bl-female"].forEach(function (id) {
      $(id).innerHTML = "";
    });
    ["mm-count", "bl-male-count", "bl-female-count"].forEach(function (id) {
      $(id).textContent = "等待当前账号数据";
    });
    $("mm-detail").innerHTML = '<div class="empty-hint">请选择当前账号的条目</div>';
  }

  function renderState(payload) {
    var observed = accountRequests.observe(payload);
    if (!observed.accepted) { return; }
    if (observed.changed) { resetAccountViews(); }
    var capture = payload.capture || {};
    setPill("pill-listen", "采集：" + (capture.running ? "进行中" : "未启动"), capture.running ? "ok" : "idle");
    setPill("pill-key", "密钥：" + (capture.any_key ? "已获取" : "未获取"), capture.any_key ? "ok" : "warn");
    setPill("pill-record", "录制：" + (capture.recording ? "开" : "关"), capture.recording ? "ok" : "idle");
    setPill("pill-pets", "精灵：" + (payload.pets_total || 0) + " 只", (payload.pets_total || 0) > 0 ? "ok" : "idle");

    var message = "开始采集后登录游戏，自动同步数据";
    if (capture.last_error) { message = "采集异常，请到「采集与设置」查看"; }
    else if (capture.running) {
      message = capture.any_key
        ? (capture.decrypt_ok ? "正在同步游戏数据" : "连接就绪，等待游戏数据")
        : "等待游戏登录；已登录时请重新进入";
      if (capture.any_key && capture.decrypt_ok && !payload.identity) {
        message = "已收到游戏数据；重新进入游戏可确认本次角色";
      }
    }
    $("capture-message").textContent = message;

    // 采集按钮保持主色；固定图标与宽度避免状态更新时跳动。
    var toggle = $("btn-toggle");
    if (toggle) {
      var running = !!capture.running;
      toggle.innerHTML = '<svg class="ui-icon" aria-hidden="true"><use href="/static/icons/sprite.svg#' + (running ? 'square' : 'player-play') + '"></use></svg>' + (running ? "停止采集" : "开始采集");
      toggle.classList.toggle("stop-button", running);
      toggle.onclick = running ? doStop : doStart;
    }
    $("btn-capture-start").disabled = !!capture.running;
    $("btn-capture-stop").disabled = !capture.running;

    // 蛋仓有新数据且当前在蛋仓页 → 自动刷新（版本号变化才触发）
    if (payload.egg_box_version !== undefined && payload.egg_box_version !== eggBoxVersion) {
      eggBoxVersion = payload.egg_box_version;
      if (state.page === "egg-box") { loadEggBoxPage(); }
    }
    if (payload.home_version !== undefined && payload.home_version !== homeVersion) {
      homeVersion = payload.home_version;
      if (state.page === "home") { loadHome(true); }
    }
    if (payload.flower_version !== undefined && payload.flower_version !== flowerState.version) {
      flowerState.version = payload.flower_version;
      if (state.page === "flowers") { loadFlowers(); }
    }

    renderRole(payload.identity, payload.cached_identity);
    var stats = payload.stats || {};
    $("ov-total").textContent = stats.total || 0;
    $("ov-maxed").textContent = stats.maxed || 0;
    $("ov-maxlv").textContent = stats.max_level || 0;
    if (payload.events_total !== undefined && $("ov-events")) {
      $("ov-events").textContent = payload.events_total || 0;
    }
    renderOverviewSide(payload.identity);
    renderOverviewCapture(payload.capture);

    if (payload.stats && payload.stats.types) {
      renderTypeDist(payload.stats.types || []);
    }

    if (state.page === "capture") { renderCaptureSummary(payload.capture || {}); }
    if (payload.environment) { renderEnvBanner(payload.environment); }
    var version = payload.pets_version;
    if (version !== undefined && version !== state._petsVersion) {
      state._petsVersion = version;
      var refresh = { pets: loadPets, handbook: function () { return handbookPage.load(); }, "male-matrix": loadMaleMatrix,
        "breeder-library": function () { return breederLibrary.load(); }, colors: function () { return colorsPage.load(); } };
      if (refresh[state.page]) { refresh[state.page](false); }
      if (state.page === "home") { loadHome(false); }
      if (state.page === "collection-lines") { collectionLines.load(); }
      if (state.page === "planner") { breedingPlanner.load(); }
    }
  }

  /* ---------- 宠物仓库 ---------- */
  function loadPets(resetPage, restoreWorkspace) {
    return (restoreWorkspace ? petInventory.resume() : petInventory.load(resetPage !== false)).then(function () {
      if (restoreWorkspace && state.page === "pets") {
        petInventory.restoreScroll();
        if (petInventory.selected()) {
          petInventory.openDetail();
        }
      }
    });
  }

  /* ---------- 精灵图鉴（Vue 页，挂载后由页面自己拉数据） ---------- */
  var handbookPage = (function () {
    var mounted = null;
    var generation = 0;
    return {
      load: function (entryId) {
        if (mounted) { mounted.resume(); if (entryId) { mounted.reveal(entryId); } return; }
        var current = ++generation;
        var root = $("page-handbook");
        root.textContent = "正在加载图鉴…";
        return import("/static/vue/entry.js").then(function (page) {
          if (current !== generation) { return; }
          mounted = page.mountHandbook(root, TOKEN, {
            failed: function (message) { toast("图鉴加载失败：" + message, true); }
          });
          if (entryId) { mounted.reveal(entryId); }
        }).catch(function (err) {
          if (current !== generation) { return; }
          root.textContent = "图鉴启动失败，请切页重试：" + err.message;
          toast("图鉴启动失败：" + err.message, true);
        });
      },
      leave: function () { generation++; if (mounted) { mounted.pause(); } },
      resetAccount: function () { if (mounted) { mounted.resetAccount(); } },
      unmount: function () { generation++; if (mounted) { mounted.unmount(); mounted = null; } }
    };
  })();

  /* ---------- 协议流 ---------- */
  function loadEvents() {
    return api("/api/events").then(function (payload) {
      state.events = payload.rows || [];
      $("event-count").textContent = (payload.total || 0) + " 条";
      $("event-empty").hidden = state.events.length > 0;
      $("event-rows").innerHTML = state.events.map(function (row) {
        var cls = row.direction === "s2c" ? "dir-tag s2c" : "dir-tag";
        return '<tr data-index="' + row.index + '" role="button" tabindex="0" aria-label="查看协议事件详情">'
          + "<td>" + esc(row.time) + "</td>"
          + '<td><span class="' + cls + '">' + esc(row.direction) + "</span></td>"
          + "<td>" + esc(row.opcode) + "</td>"
          + "<td>" + esc(row.name) + "</td>"
          + '<td class="col-gid">' + row.payload_len + "B</td></tr>";
      }).join("");
      $("event-rows").querySelectorAll("tr").forEach(function (rowNode) {
        rowNode.addEventListener("click", function () {
          state.selectedEventIndex = Number(rowNode.dataset.index);
          $("event-rows").querySelectorAll("tr").forEach(function (item) {
            item.classList.toggle("active", item === rowNode);
          });
          api("/api/events/detail" + query({ index: state.selectedEventIndex })).then(function (detail) {
            if (state.selectedEventIndex !== Number(rowNode.dataset.index) || state.page !== "events") { return; }
            $("event-detail").innerHTML = '<div class="detail-section"><h3>解码详情</h3>'
              + '<pre class="detail-pre">' + colorizeDecoded(detail.detail) + "</pre></div>";
            if (state.page === "events") { window.SpriteLensUI.openDetail("event-detail", rowNode); }
          }).catch(function () {});
        });
      });
    }).catch(function (err) { toast("事件加载失败：" + err.message, true); });
  }

  /* ---------- 采集与设置 ---------- */
  // 横幅语义：仅在「未装 Npcap」或「RSC 开启」时显示。
  // 环境探测异步进行，WS state 载荷里也带 environment，探测完成后横幅自动刷新。
  function renderEnvBanner(env) {
    env = env || {};
    var rscIssue = !!env.rsc_enabled;
    var needBanner = !env.installed || rscIssue;
    $("npcap-banner").hidden = !needBanner;
    $("npcap-title").textContent = !env.installed ? "未检测到 Npcap 抓包驱动" : "网卡 RSC 未禁用";
    $("npcap-message").textContent = env.message || "";
    // 按钮可见性按问题类型区分（RSC 只能装完 Npcap 后处理）
    $("btn-npcap-install").hidden = !!env.installed;
    $("btn-rsc").hidden = !(env.installed && rscIssue);
  }

  function renderCapture(payload) {
    state.capture = payload;
    renderEnvBanner(payload.environment);

    var toggle = $("btn-toggle");
    if (toggle) {
      var running = !!payload.running;
      toggle.innerHTML = '<svg class="ui-icon" aria-hidden="true"><use href="/static/icons/sprite.svg#' + (running ? 'square' : 'player-play') + '"></use></svg>' + (running ? "停止采集" : "开始采集");
      toggle.classList.toggle("stop-button", running);
      toggle.classList.remove("toggle-busy");
      toggle.disabled = false;
      toggle.onclick = running ? doStop : doStart;
    }

    renderInstallProgress(payload.install || {});
    $("c-record").checked = !!payload.recording_requested;
    if ($("c-autostart")) { $("c-autostart").checked = payload.autostart !== false; }

    var ifaceSelect = $("c-iface");
    if (!ifaceSelect.dataset.value || ifaceSelect.value !== payload.iface) {
      ifaceSelect.dataset.value = payload.iface || "";
    }
    renderCaptureSummary(payload);
  }

  /* 安装/提权流程状态：确定进度画进度条，不确定进度走滑动动画 */
  function renderInstallProgress(install) {
    var bar = $("npcap-progress");
    var hint = $("capture-hint");
    if (!install || install.phase === "idle") {
      bar.hidden = true;
      hint.textContent = "";
      return;
    }
    var text = install.message || "";
    var tone = "";
    if (install.phase === "failed") {
      tone = "（失败）";
      bar.hidden = true;
    } else if (install.phase === "launched") {
      tone = "";
      bar.hidden = true;
    } else {
      bar.hidden = false;
      if (install.progress === null || install.progress === undefined) {
        bar.classList.add("indeterminate");
        bar.querySelector("i").style.width = "";
      } else {
        bar.classList.remove("indeterminate");
        bar.querySelector("i").style.width = Math.round(install.progress * 100) + "%";
      }
    }
    hint.textContent = text + tone;
  }

  function renderCaptureSummary(payload) {
    var totals = payload.totals || {};
    var sessions = payload.sessions || [];
    var dropped = (payload.dropped_chunks || 0) + (payload.dropped_segments || 0)
      + (payload.event_log_dropped || 0);
    $("capture-stats").textContent = "原始流 " + (totals.raw_chunks || 0) + " 段 / "
      + (totals.raw_bytes || 0) + " 字节 · 解密成功 " + (totals.decrypt_ok || 0)
      + " · 缺密钥 " + (totals.key_miss || 0) + " · 会话 " + sessions.length
      + (dropped > 0 ? " · 丢弃 " + dropped + " 段" : "")
      + (payload.event_log_name ? " · 事件日志 " + payload.event_log_name : "");
    $("session-rows").innerHTML = sessions.length ? sessions.map(function (item) {
      return "<tr><td>" + esc(item.session_id) + "</td>"
        + '<td>' + (item.has_key ? '<svg class="ui-icon" viewBox="0 0 24 24" aria-label="已获取"><use href="/static/icons/sprite.svg#circle-check"></use></svg>' : "—") + "</td>"
        + '<td class="col-gid">' + item.data_frames + "</td></tr>";
    }).join("") : '<tr><td colspan="3" class="muted">暂无会话</td></tr>';
  }

  function loadCapture() {
    return api("/api/capture").then(renderCapture).catch(function () {});
  }

  function loadIfaces() {
    return api("/api/capture/ifaces").then(function (payload) {
      var select = $("c-iface");
      var current = state.capture ? state.capture.iface : "";
      select.innerHTML = '<option value="">（默认路由网卡）</option>'
        + (payload.ifaces || []).map(function (item) {
          return '<option value="' + esc(item.name) + '">' + esc(item.description || item.name) + "</option>";
        }).join("");
      select.value = current || "";
    }).catch(function () {});
  }

  function bindCaptureActions() {
    $("btn-capture-start").addEventListener("click", doStart);
    $("btn-capture-stop").addEventListener("click", doStop);
    $("btn-record-toggle").addEventListener("click", function () {
      var enabled = !(state.capture && state.capture.recording);
      api("/api/capture/recording", { method: "POST", body: { enabled: enabled } })
        .then(function (payload) { renderCapture(payload); toast(enabled ? "已开始录制" : "已停止录制"); })
        .catch(function (err) { toast("录制切换失败：" + err.message, true); });
    });
    $("c-iface").addEventListener("change", function () {
      var choice = $("c-iface").value;
      api("/api/capture/iface", { method: "POST", body: { name: choice } })
        .then(function (payload) { renderCapture(payload); toast(choice ? "已选择网卡（下次启动生效）" : "已用默认路由网卡"); })
        .catch(function (err) { toast("网卡设置失败：" + err.message, true); });
    });
    $("c-record").addEventListener("change", function (event) {
      api("/api/capture/recording", { method: "POST", body: { enabled: event.target.checked } })
        .then(function (payload) { renderCapture(payload); })
        .catch(function (err) { toast("设置失败：" + err.message, true); });
    });
    if ($("c-autostart")) {
      $("c-autostart").addEventListener("change", function (event) {
        api("/api/capture/autostart", { method: "POST", body: { enabled: event.target.checked } })
          .then(function (payload) {
            renderCapture(payload);
            toast(event.target.checked ? "已开启「打开即采集」" : "已关闭「打开即采集」");
          })
          .catch(function (err) { toast("设置失败：" + err.message, true); });
      });
    }
    $("btn-key-apply").addEventListener("click", function () {
      var text = $("c-key").value.trim();
      if (!text) { toast("请先粘贴密钥文本", true); return; }
      api("/api/capture/key", { method: "POST", body: { text: text } }).then(function (payload) {
        $("key-message").textContent = payload.message || "";
        toast(payload.message || "密钥已应用");
      }).catch(function (err) {
        $("key-message").textContent = err.message;
        toast("密钥无效：" + err.message, true);
      });
    });
    $("btn-npcap-install").addEventListener("click", function () {
      api("/api/capture/npcap/install", { method: "POST" }).then(function (payload) {
        renderCapture(payload);
        toast("已开始下载 Npcap 安装器");
      }).catch(function (err) { toast("启动安装失败：" + err.message, true); });
    });
    $("btn-rsc").addEventListener("click", function () {
      api("/api/capture/rsc", { method: "POST" }).then(function (payload) {
        renderCapture(payload);
        toast("已发起禁用 RSC（请在 UAC 弹窗中确认）");
      }).catch(function (err) { toast("禁用失败：" + err.message, true); });
    });
    $("btn-recheck").addEventListener("click", function () {
      loadCapture().then(function () { toast("已重新检测"); });
    });
  }

  /* 切换按钮的中间态：启动/停止都耗时（Npcap 开销），禁用+琥珀脉冲过渡 */
  function setToggleBusy(text) {
    var toggle = $("btn-toggle");
    if (!toggle) { return; }
    toggle.textContent = text;
    toggle.classList.remove("stop-button");
    toggle.classList.add("toggle-busy");
    toggle.disabled = true;
    toggle.onclick = null;
  }

  function doStart() {
    setToggleBusy("启动中…");
    api("/api/capture/start", { method: "POST" }).then(function (payload) {
      renderCapture(payload);
      if (payload.last_error) { toast("采集启动失败：" + payload.last_error, true); }
      else { toast("已开始采集"); }
    }).catch(function (err) {
      toast("启动失败：" + err.message, true);
      if (state.capture) { renderCapture(state.capture); }  // 回落到上一状态
    });
  }

  function doStop() {
    setToggleBusy("停止中…");
    api("/api/capture/stop", { method: "POST" }).then(function (payload) {
      renderCapture(payload);
      toast("已停止采集");
    }).catch(function (err) {
      toast("停止失败：" + err.message, true);
      if (state.capture) { renderCapture(state.capture); }
    });
  }

  /* ---------- WebSocket 推送 ---------- */
  function connectPush() {
    var protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    var url = protocol + "//" + window.location.host + "/ws?token=" + encodeURIComponent(TOKEN);
    var socket;
    try { socket = new WebSocket(url); } catch (e) { return; }

    socket.onmessage = function (event) {
      var payload;
      try { payload = JSON.parse(event.data); } catch (e) { return; }
      renderState(payload);
    };
    socket.onclose = function () { setTimeout(connectPush, 1500); };
    socket.onerror = function () { try { socket.close(); } catch (e) {} };
  }

  /* 临时迁移桥：壳只传根节点/token 和挂载生命周期，页面状态归 Vue。F04 删除。 */
  var eggDex = (function () {
    var generation = 0;
    var mounted = null;
    return {
      leave: function () {
        generation++;
        if (mounted) { mounted.pause(); }
      },
      unmount: function () { generation++; if (mounted) { mounted.unmount(); mounted = null; } },
      load: function (entryId) {
        if (mounted) { mounted.resume(); if (entryId) { mounted.reveal(entryId); } return; }
        var current = ++generation;
        var root = $("page-egg-dex");
        root.textContent = "正在加载蛋图鉴…";
        return import("/static/vue/entry.js").then(function (page) {
          if (current !== generation) { return; }
          mounted = page.mount(root, TOKEN);
          if (entryId) { mounted.reveal(entryId); }
        }).catch(function (err) {
          if (current !== generation) { return; }
          root.textContent = "蛋图鉴启动失败，请切页重试：" + err.message;
          toast("蛋图鉴启动失败：" + err.message, true);
        });
      }
    };
  })();

  /* ---------- 待实现页占位 ---------- */
  function renderFeaturePlaceholders() {
    document.querySelectorAll(".feature-page-root").forEach(function (root) {
      var feature = root.dataset.feature || "功能";
      var hint = root.dataset.hint || "协议数据域就绪后开放";
      root.innerHTML = '<div class="feature-placeholder"><strong>' + esc(feature) + '</strong>'
        + '<p>' + esc(hint) + '</p>'
        + '<span class="muted">该页面对标蛋神助手本地功能，随协议帧解析逐批开放</span></div>';
    });
  }

  /* ---------- Vue 蛋仓页迁移桥：账号请求与版本仍由应用壳负责 ---------- */
  function pauseEggBoxPage() {
    eggBoxPageGeneration++;
    if (eggBoxPage) { eggBoxPage.pause(); }
  }

  function loadEggBoxPage(reuse) {
    if (eggBoxPage) { return reuse ? eggBoxPage.resume(eggBoxVersion) : eggBoxPage.load(); }
    var current = ++eggBoxPageGeneration;
    var root = $("egg-box-root");
    root.textContent = "正在加载精灵蛋仓…";
    return import("/static/vue/entry.js").then(function (page) {
      if (current !== eggBoxPageGeneration || state.page !== "egg-box") { return; }
      eggBoxPage = page.mountEggBox(root, {
        load: function () { return accountRequests.request("egg-box", "/api/egg-box"); },
        saveAnnotations: function (value) { return api("/api/egg-box/annotations", { method: "POST", body: value }); },
        saveFavorite: function (value) { return api("/api/egg-box/favorite", { method: "POST", body: value }); },
        cancel: function () { accountRequests.cancel("egg-box"); },
        versionChanged: function (version) { eggBoxVersion = version; }
      });
    }).catch(function (err) {
      if (current !== eggBoxPageGeneration) { return; }
      root.textContent = "精灵蛋仓启动失败，请切页重试：" + err.message;
      toast("精灵蛋仓启动失败：" + err.message, true);
    });
  }

  /* ---------- 种公阵列（性格 × 蛋组覆盖矩阵） ---------- */
  var mmState = { gender: "all", data: null, selected: null };

  function loadMaleMatrix() {
    return accountRequests.request("male-matrix", "/api/male-matrix" + query({ gender: mmState.gender })).then(function (payload) {
      if (!payload) { return; }
      mmState.data = payload;
      renderMaleMatrix();
    }).catch(function (err) { toast("矩阵加载失败：" + err.message, true); });
  }

  var STAT_CN = { hp: "生命", atk: "物攻", spa: "魔攻", def: "物防", spd: "魔防", spe: "速度" };

  function renderMaleMatrix() {
    var payload = mmState.data;
    if (!payload) { return; }
    $("mm-count").textContent = "匹配 " + payload.matched + " / " + payload.total_pets + " 只";
    var groups = payload.groups || [];
    var natures = payload.natures || [];
    var head = '<tr><th class="mm-corner">性格 \ 蛋组</th>' + groups.map(function (g) {
      return '<th>' + esc(g) + "</th>";
    }).join("") + "</tr>";
    var body = natures.map(function (nature) {
      var fix = [nature.positive, nature.negative].filter(Boolean)
        .map(function (k) { return STAT_CN[k] || k; }).join("↑ ↓");
      var cells = groups.map(function (group) {
        var key = nature.name + "|" + group;
        var pets = payload.cells[key];
        var attr = ' data-mmkey="' + encodeURIComponent(key) + '" role="button" tabindex="0" aria-label="查看' + esc(key) + '组合"';
        if (!pets) { return '<td class="mm-cell empty"' + attr + '>—</td>'; }
        var chips = pets.map(function (pet) {
          return petChip(pet, false);
        }).join("");
        return '<td class="mm-cell"' + attr + '>' + chips + "</td>";
      }).join("");
      return '<tr><th class="mm-rowhead"><b>' + esc(nature.name) + "</b>"
        + (fix ? '<small>' + esc(fix) + "</small>" : "") + "</th>" + cells + "</tr>";
    }).join("");
    $("mm-matrix").innerHTML = "<table><thead>" + head + "</thead><tbody>" + body + "</tbody></table>";
    $("mm-empty").hidden = natures.length > 0;
  }

  function renderMaleMatrixDetail(key) {
    var payload = mmState.data;
    if (!payload) { return; }
    var pets = payload.cells[key] || [];
    var panel = $("mm-detail");
    document.querySelectorAll("#mm-matrix .mm-cell").forEach(function (node) {
      node.classList.remove("selected");
    });
    var wanted = encodeURIComponent(key);
    document.querySelectorAll('#mm-matrix td.mm-cell').forEach(function (node) {
      node.classList.toggle("selected", node.dataset.mmkey === wanted);
    });
    var parts = key.split("|");
    var rows = pets.map(function (pet) {
      return '<div class="mm-row"><img src="' + esc(pet.icon_url) + '" alt="" loading="lazy" onerror="this.remove()">'
        + '<b>' + esc(pet.name) + '</b><span class="muted">Lv' + pet.level + '</span>'
        + '<span class="' + (pet.gender === 2 ? "female" : "male") + '-mark">' + '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><use href="/static/icons/sprite.svg#gender-' + (pet.gender === 2 ? 'female' : 'male') + '"></use></svg>' + "</span></div>";
    }).join("");
    panel.innerHTML =
      '<div class="detail-title"><h2>' + esc(parts[0]) + " × " + esc(parts[1]) + "</h2></div>"
      + '<div class="detail-sub">该组合共 ' + pets.length + ' 只（同格取最高等级前 8 只）</div>'
      + (rows || '<div class="empty-hint">空</div>');
  }

  function bindMaleMatrixActions() {
    $("mm-gender").addEventListener("click", function (event) {
      var btn = event.target.closest("[data-gender]");
      if (!btn) { return; }
      mmState.gender = btn.dataset.gender;
      document.querySelectorAll("#mm-gender [data-gender]").forEach(function (node) {
        node.classList.toggle("active", node === btn);
      });
      loadMaleMatrix();
    });
    document.getElementById("page-colors").addEventListener("click", function (event) {
      var chip = event.target.closest("[data-mm]");
      if (!chip) { return; }
      switchPage("pets");
      petFilters.search(String(chip.dataset.mm));
      loadPets();
    });
    document.getElementById("page-breeder-library").addEventListener("click", function (event) {
      var chip = event.target.closest("[data-mm]");
      if (!chip) { return; }
      switchPage("pets");
      petFilters.search(String(chip.dataset.mm));
      loadPets();
    });
    // 页面内的跨页入口：接管成 switchPage，Vue 页只声明目标，不自己改路由。
    function bindPageLinks(rootId) {
      var root = $(rootId);
      if (!root) { return; }
      root.addEventListener("click", function (event) {
        var toPage = event.target.closest("[data-goto-page]");
        if (toPage) { switchPage(String(toPage.dataset.gotoPage), toPage.dataset.catalogId); return; }
        var toPets = event.target.closest("[data-goto-pets]");
        if (!toPets) { return; }
        // 图鉴详情按物种名回背包预筛：名字命中即该物种的全部个体。
        switchPage("pets");
        petFilters.search(String(toPets.dataset.gotoPets));
        loadPets();
      });
    }
    ["page-handbook", "page-egg-dex", "egg-box-root"].forEach(bindPageLinks);
    $("mm-matrix").addEventListener("click", function (event) {
      var chip = event.target.closest("[data-mm]");
      if (chip) {
        // 跳到精灵背包并按 gid 搜索（详情可查）
        switchPage("pets");
        petFilters.search(String(chip.dataset.mm));
        loadPets();
        return;
      }
      var cell = event.target.closest("td.mm-cell");
      if (!cell || !cell.dataset.mmkey) { return; }
      var key = decodeURIComponent(cell.dataset.mmkey);
      mmState.selected = key;
      renderMaleMatrixDetail(key);
    });
  }

  /* ---------- Vue 家园页：账号请求仍由应用壳做 UID/version 校验 ---------- */
  function loadHome(reuse) {
    if (homePage) { return reuse ? homePage.resume(homeVersion) : homePage.load(); }
    var current = ++homePageGeneration;
    var root = $("home-root");
    root.textContent = "正在加载家园页面…";
    return import("/static/vue/entry.js").then(function (page) {
      if (current !== homePageGeneration || state.page !== "home") { return; }
      homePage = page.mountHome(root, {
        load: function () { return accountRequests.request("home", "/api/home"); },
        cancel: function () { accountRequests.cancel("home"); },
        versionChanged: function (version) { homeVersion = version; }
      });
      return homePage.load();
    }).catch(function (err) {
      if (current !== homePageGeneration || state.page !== "home") { return; }
      root.textContent = "家园页面启动失败，请切页重试：" + err.message;
      toast("家园页面启动失败：" + err.message, true);
    });
  }

  /* ---------- 炫彩花种 ---------- */
  var flowerState = { data: null, version: -1 };

  function loadFlowers() {
    return accountRequests.request("flowers", "/api/flowers").then(function (payload) {
      if (!payload) { return; }
      flowerState.data = payload;
      flowerState.version = payload.version || 0;
      renderFlowers();
    }).catch(function (err) { toast("花田加载失败：" + err.message, true); });
  }

  function flowerCard(r) {
    var planted = r.planted_at ? new Date(r.planted_at * 1000).toLocaleDateString() : "—";
    var img = r.icon_url
      ? '<img src="' + esc(r.icon_url) + '" alt="" loading="lazy" onerror="this.remove()">'
      : "";
    return '<div class="fl-card">'
      + '<span class="pc-avatar">' + esc((r.pet_name || "—").slice(0, 1)) + img + "</span>"
      + '<div class="fl-info"><b>' + esc(r.pet_name) + "</b>"
      + '<small>槽位 #' + esc(r.slot_id) + "</small>"
      + '<span class="muted">' + planted + "</span></div></div>";
  }

  function renderFlowers() {
    var payload = flowerState.data;
    if (!payload) { return; }
    if (!payload.available) {
      $("fl-meta").textContent = "等待花田快照（登录或打开花田界面后更新）";
      $("fl-friend-count").textContent = "—";
      $("fl-own").innerHTML = "";
      $("fl-friends").innerHTML = "";
      $("fl-own-empty").hidden = false;
      $("fl-friends-empty").hidden = false;
      return;
    }
    $("fl-meta").textContent = "观察快照 #" + payload.version + " · 我的花 " + (payload.own || []).length + " 朵（完整性未确认）";
    $("fl-own").innerHTML = (payload.own || []).map(flowerCard).join("");
    $("fl-own-empty").hidden = (payload.own || []).length > 0;
    $("fl-friends").innerHTML = (payload.friends || []).map(flowerCard).join("");
    $("fl-friend-count").textContent = (payload.friends || []).length + " 条";
    $("fl-friends-empty").hidden = (payload.friends || []).length > 0;
  }

  /* ---------- 炫彩色卡 ---------- */

  function petChip(pet, withLevel) {
    var mark = '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><use href="/static/icons/sprite.svg#gender-' + (pet.gender === 2 ? "female" : "male") + '"></use></svg>';
    return '<span class="mm-pet" data-mm="' + pet.gid + '"><img src="' + esc(pet.icon_url)
      + '" alt="" loading="lazy" onerror="this.remove()">' + mark + esc(pet.name)
      + (withLevel === false ? "" : '<small>Lv' + pet.level + "</small>") + "</span>" + window.SpriteLensPetPresentation.colorCard(pet.color_card);
  }

  /* ---------- 炫彩色卡（Vue 页，挂载后由页面自己拉数据） ---------- */
  var colorsPage = (function () {
    var mounted = null;
    return {
      load: function () {
        if (mounted) { mounted.resume(); return; }
        var root = $("page-colors");
        root.textContent = "正在加载色卡…";
        return import("/static/vue/entry.js").then(function (page) {
          mounted = page.mountColors(root, TOKEN, {
            failed: function (message) { toast("色卡加载失败：" + message, true); }
          });
        }).catch(function (err) {
          root.textContent = "色卡启动失败，请切页重试：" + err.message;
          toast("色卡启动失败：" + err.message, true);
        });
      },
      leave: function () { if (mounted) { mounted.pause(); } },
      resetAccount: function () { if (mounted) { mounted.resetAccount(); } },
      unmount: function () { if (mounted) { mounted.unmount(); mounted = null; } }
    };
  })();

  var lastImageMode = "portrait";
  document.addEventListener("preferenceschanged", function (event) { if (petFilters) { petFilters.setShortcuts(event.detail.shortcuts); } });
  document.addEventListener("preferenceschanged", function (event) {
    var mode = event.detail.pet_image || "portrait";
    if (mode === lastImageMode) { return; }
    lastImageMode = mode;
    if (!petInventory) { return; }
    petInventory.refreshPresentation();
  });

  /* ---------- 启动（15s 超时 + 自动重试 2 次，与自恢复链协同） ---------- */
  var BOOT_RETRIES = 2;

  function bootAttempt(remaining) {
    var controller = ("AbortController" in window) ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, 15000) : null;
    api("/api/bootstrap", { signal: controller ? controller.signal : undefined }).then(async function (payload) {
      if (!petFilters) {
        var vue = await import("/static/vue/entry.js");
        petFilters = vue.mountPetFilters($("pet-basic-filters"), loadPets, function () { petInventory.invalidate(); }, {
          busy: function () { return petInventory.isBusy(); },
          persist: window.SpriteLensAppearance.shortcuts, notify: toast
        });
      }
      if (!petInventory) {
        var inventoryVue = await import("/static/vue/entry.js");
        petInventory = inventoryVue.mountPetInventory($("pet-list-root"), TOKEN, {
          account: accountRequests.petContext,
          query: petFilters.query,
          imageMode: window.SpriteLensAppearance.imageMode,
          fixed: petFilters.setFixed,
          failed: function (message) { toast("宠物数据加载失败：" + message, true); },
          view: function (view) { window.SpriteLensAppearance.view(view); },
          reset: function () { $("btn-reset-filters").click(); },
          committed: petFilters.sync
        });
      }
      petFilters.updateOptions(payload.pets.options);
      petFilters.setShortcuts(payload.ui_preferences.shortcuts);
      accountRequests.observe(payload.state);
      petInventory.seed(payload.pets);
      if (timer) { clearTimeout(timer); }
      window.SpriteLensAppearance.initialize(payload.ui_preferences, function (changes) {
        return api("/api/ui/preferences", { method: "POST", body: changes });
      }, toast, function () { return api("/api/ui/open-browser", { method: "POST" }); });
      petInventory.setView(payload.ui_preferences.pet_view);
      if (payload.app && payload.app.version) {
        var versionNode = $("app-version");
        if (versionNode) { versionNode.textContent = "v" + payload.app.version + " · 纯本地运行"; }
      }
      renderOverview(payload.overview || {});
      renderCapture(payload.capture || {});
      renderState(payload.state || {});
      renderFeaturePlaceholders();
      bindMaleMatrixActions();
      bindCaptureActions();
      loadIfaces();
      connectPush();
      switchPage("pets");
      if (window.__spritelensBoot) { window.__spritelensBoot.ready(); }
      else { $("startup").hidden = true; $("app").hidden = false; }
    }).catch(function (err) {
      if (timer) { clearTimeout(timer); }
      if (remaining > 0) {
        setTimeout(function () { bootAttempt(remaining - 1); }, 2000);
        if (window.__spritelensBoot) { window.__spritelensBoot.message("连接本地服务失败，正在重试（剩余 " + remaining + " 次）…"); }
        return;
      }
      var reason = err.name === "AbortError" ? "请求超时" : err.message;
      if (window.__spritelensBoot) { window.__spritelensBoot.failed(reason); return; }
      $("startup").innerHTML = "<strong>小洛探探 SpriteLens</strong><p>启动失败：" + esc(reason)
        + "</p><p>请重启程序；若持续失败请查看日志目录。</p>";
    });
  }

  function boot() {
    bootAttempt(BOOT_RETRIES);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
