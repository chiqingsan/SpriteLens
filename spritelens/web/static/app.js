/* 小洛探探 SpriteLens — 前端壳（原生 JS，页面渐进迁 Vue）
 *
 * 数据来源：本地服务 REST（初始聚合）+ WebSocket（增量推送）。
 * token 经 URL fragment 下发，存 sessionStorage 后从地址栏清除。
 */
(function () {
  "use strict";

  /* ---------- token 与请求 ---------- */
  var TOKEN_KEY = "spritelens.localToken";
  var QQ_GROUP_NUMBER = "1057031552";

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
  var pendingWrites = new Set();

  function api(path, options) {
    var opts = options || {};
    var headers = { "X-Local-Token": TOKEN };
    if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; }
    var request = fetch(path, {
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
    if (opts.method === "POST") {
      pendingWrites.add(request);
      request.then(function () { pendingWrites.delete(request); }, function () { pendingWrites.delete(request); });
    }
    return request;
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
    confirmOverwrite: function () { return window.confirm("另一窗口已保存了不同的草稿。是否用当前草稿覆盖？取消可保留双方内容。"); },
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

  window.SpriteLensPrepareClose = async function () {
    if (document.activeElement instanceof HTMLElement) { document.activeElement.blur(); }
    document.body.inert = true;
    try {
      await breedingPlanner.flush();
      if (eggBoxPage) { await eggBoxPage.flush(); }
      while (pendingWrites.size) { await Promise.all(Array.from(pendingWrites)); }
      return { ok: true };
    } catch (error) {
      document.body.inert = false;
      return { ok: false, error: error.message };
    }
  };
  window.SpriteLensCancelClose = function () { document.body.inert = false; };

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

  function copyText(text) {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      return navigator.clipboard.writeText(text);
    }
    return Promise.resolve().then(function () {
      var input = document.createElement("textarea");
      input.value = text;
      input.setAttribute("readonly", "");
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.appendChild(input);
      input.select();
      var copied = document.execCommand("copy");
      input.remove();
      if (!copied) { throw new Error("系统剪贴板不可用"); }
    });
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

  /* ---------- 页面状态 ---------- */
  var state = {
    page: "boot",
    capture: null
  };
  var autoRefreshes = Object.create(null);

  /* ---------- 导航 ---------- */
  function switchPage(name, revealGid) {
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
    if (name === "home") { loadHome(true); }
    if (name === "collection-lines") { collectionLines.load(); }
    if (name === "breeder-library") { breederLibrary.load(); }
    if (name === "planner") { breedingPlanner.load(); }
    if (name === "capture") { loadCapture(); }
  }

  document.querySelectorAll(".nav-item").forEach(function (node) {
    node.addEventListener("click", function () { switchPage(node.dataset.page); });
  });

  /* ---------- 顶栏状态 ---------- */
  function renderRole(identity, cached) {
    window.SpriteLensAccountCard.render(identity, cached);
  }

  function setPill(id, text, tone) {
    var node = $(id);
    var className = "status-pill " + (tone || "idle");
    if (node.textContent !== text) { node.textContent = text; }
    if (node.className !== className) { node.className = className; }
  }

  function queueAutoRefresh(key, loader, active) {
    var job = autoRefreshes[key];
    if (!job) { job = autoRefreshes[key] = { pending: false, promise: null }; }
    job.pending = true;
    if (job.promise || !active()) { return; }

    job.pending = false;
    var promise = Promise.resolve(loader());
    job.promise = promise;
    promise.then(function () {
      if (job.promise !== promise) { return; }
      job.promise = null;
      if (job.pending && active()) { queueAutoRefresh(key, loader, active); }
      else if (!active()) { job.pending = false; }
    }, function () {
      if (job.promise !== promise) { return; }
      job.promise = null;
      if (job.pending && active()) { queueAutoRefresh(key, loader, active); }
      else if (!active()) { job.pending = false; }
    });
  }

  function resetAccountViews() {
    collectionLines.resetAccount();
    breederLibrary.resetAccount();
    breedingPlanner.resetAccount();
    if (state.page !== "egg-dex") { window.SpriteLensUI.closeDetail(false, true); }
    petInventory.resetAccount(); petFilters.resetAccount(); state._petsVersion = -1;
    colorsPage.resetAccount();
    eggBoxVersion = -1;
    if (eggBoxPage) { eggBoxPage.resetAccount(); }
    homeVersion = -1;
    if (homePage) { homePage.resetAccount(); }
  }

  function renderState(payload) {
    var observed = accountRequests.observe(payload);
    if (!observed.accepted) { return; }
    if (observed.changed) { resetAccountViews(); }
    var capture = payload.capture || {};
    if (payload.environment) {
      renderEnvBanner(payload.environment);
      state.capture = state.capture || {};
      state.capture.environment = payload.environment;
    }
    if (payload.install) {
      renderInstallProgress(payload.install);
      state.capture = state.capture || {};
      state.capture.install = payload.install;
    }
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
    if ($("capture-message").textContent !== message) { $("capture-message").textContent = message; }

    // 采集按钮保持主色；固定图标与宽度避免状态更新时跳动。
    var toggle = $("btn-toggle");
    if (toggle) {
      var running = !!capture.running;
      if (toggle.dataset.running !== String(running)) {
        toggle.innerHTML = '<svg class="ui-icon" aria-hidden="true"><use href="/static/icons/sprite.svg#' + (running ? 'square' : 'player-play') + '"></use></svg>' + (running ? "停止采集" : "开始采集");
        toggle.classList.toggle("stop-button", running);
        toggle.onclick = running ? doStop : doStart;
        toggle.dataset.running = String(running);
      }
    }
    $("btn-capture-start").disabled = !!capture.running;
    $("btn-capture-stop").disabled = !capture.running;

    // 蛋仓有新数据且当前在蛋仓页 → 自动刷新（版本号变化才触发）
    var homeRefreshNeeded = false;
    if (payload.egg_box_version !== undefined && payload.egg_box_version !== eggBoxVersion) {
      eggBoxVersion = payload.egg_box_version;
      if (state.page === "egg-box") {
        queueAutoRefresh("egg-box-version", function () { return loadEggBoxPage(); }, function () { return state.page === "egg-box"; });
      }
    }
    if (payload.home_version !== undefined && payload.home_version !== homeVersion) {
      homeVersion = payload.home_version;
      homeRefreshNeeded = state.page === "home";
    }

    renderRole(payload.identity, payload.cached_identity);
    if (state.page === "capture") { renderCaptureSummary(payload.capture || {}); }
    var version = payload.pets_version;
    if (version !== undefined && version !== state._petsVersion) {
      state._petsVersion = version;
      var page = state.page;
      var refresh = {
        pets: function () { return loadPets(false); },
        "breeder-library": function () { return breederLibrary.load(); },
        colors: function () { return colorsPage.load(); },
        home: function () { return loadHome(false); },
        "collection-lines": function () { return collectionLines.load(); },
        planner: function () { return breedingPlanner.load(); }
      };
      if (refresh[page]) {
        if (page === "home") { homeRefreshNeeded = true; }
        else { queueAutoRefresh("pets-version-" + page, refresh[page], function () { return state.page === page; }); }
      }
    }
    if (homeRefreshNeeded) {
      queueAutoRefresh("home-version", function () { return loadHome(false); }, function () { return state.page === "home"; });
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
    $("npcap-steps").hidden = !!env.installed;
    $("npcap-manual-link").hidden = !!env.installed;
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
      toggle.dataset.running = String(running);
      toggle.classList.remove("toggle-busy");
      toggle.disabled = false;
      toggle.onclick = running ? doStop : doStart;
    }

    renderInstallProgress(payload.install || {});
    $("c-record").checked = !!payload.recording_requested;
    if ($("c-autostart")) { $("c-autostart").checked = payload.autostart !== false; }
    var automation = payload.automation || {};
    var followingGame = automation.enabled === true;
    var automationStatus = $("c-game-auto-status");
    if (automationStatus) {
      var automationText = followingGame ? "当前状态：跟随启动" : "当前状态：未跟随";
      var automationClass = "status-pill " + (followingGame ? "ok" : "idle");
      if (automationStatus.textContent !== automationText) { automationStatus.textContent = automationText; }
      if (automationStatus.className !== automationClass) { automationStatus.className = automationClass; }
    }
    if ($("btn-game-auto-follow")) { $("btn-game-auto-follow").disabled = followingGame; }
    if ($("btn-game-auto-unfollow")) { $("btn-game-auto-unfollow").disabled = !followingGame; }
    if ($("c-game-auto-guidance")) { $("c-game-auto-guidance").textContent = automation.audit_guidance || ""; }
    $("btn-record-toggle").textContent = payload.recording ? "停止录制" : "开始录制";

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
    var installButton = $("btn-npcap-install");
    if (!install || install.phase === "idle") {
      bar.hidden = true;
      hint.textContent = "";
      installButton.disabled = false;
      installButton.textContent = "一键安装 Npcap";
      return;
    }
    var text = install.message || "";
    var tone = "";
    if (install.phase === "failed") {
      tone = "（失败）";
      bar.hidden = true;
      installButton.disabled = false;
      installButton.textContent = "重试安装 Npcap";
    } else if (install.phase === "completed") {
      tone = "";
      bar.hidden = true;
      installButton.disabled = false;
      installButton.textContent = "重新打开安装流程";
    } else if (install.phase === "checking") {
      bar.hidden = false;
      installButton.disabled = true;
      installButton.textContent = "正在检测 Npcap…";
      bar.classList.add("indeterminate");
      bar.querySelector("i").style.width = "";
    } else {
      bar.hidden = false;
      installButton.disabled = true;
      installButton.textContent = "安装处理中…";
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
    var stats = "原始流 " + (totals.raw_chunks || 0) + " 段 / "
      + (totals.raw_bytes || 0) + " 字节 · 解密成功 " + (totals.decrypt_ok || 0)
      + " · 缺密钥 " + (totals.key_miss || 0) + " · 会话 " + sessions.length
      + (dropped > 0 ? " · 丢弃 " + dropped + " 段" : "")
      + (payload.event_log_name ? " · 事件日志 " + payload.event_log_name : "")
      + (payload.event_log_error ? " · " + payload.event_log_error : "");
    if ($("capture-stats").textContent !== stats) { $("capture-stats").textContent = stats; }
    var sessionSignature = JSON.stringify(sessions.map(function (item) {
      return [item.session_id, !!item.has_key, item.data_frames];
    }));
    var rows = $("session-rows");
    if (rows.dataset.signature === sessionSignature) { return; }
    rows.innerHTML = sessions.length ? sessions.map(function (item) {
      return "<tr><td>" + esc(item.session_id) + "</td>"
        + '<td>' + (item.has_key ? '<svg class="ui-icon" viewBox="0 0 24 24" aria-label="已获取"><use href="/static/icons/sprite.svg#circle-check"></use></svg>' : "—") + "</td>"
        + '<td class="col-gid">' + item.data_frames + "</td></tr>";
    }).join("") : '<tr><td colspan="3" class="muted">暂无会话</td></tr>';
    rows.dataset.signature = sessionSignature;
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
    function setGameAutoFollow(enabled) {
        api("/api/capture/automation", {
          method: "POST", body: { enabled: enabled }
        }).then(function (payload) {
          renderCapture(payload);
          toast(enabled ? "已开启跟随游戏启动" : "已取消跟随游戏启动");
        }).catch(function (err) { toast("自动监听设置失败：" + err.message, true); });
    }
    if ($("btn-game-auto-follow")) {
      $("btn-game-auto-follow").addEventListener("click", function () { setGameAutoFollow(true); });
    }
    if ($("btn-game-auto-unfollow")) {
      $("btn-game-auto-unfollow").addEventListener("click", function () { setGameAutoFollow(false); });
    }
    if ($("btn-copy-qq-group")) {
      $("btn-copy-qq-group").addEventListener("click", function () {
        var button = this;
        button.disabled = true;
        copyText(QQ_GROUP_NUMBER).then(function () {
          toast("QQ群号已复制");
        }).catch(function (err) {
          toast("复制群号失败：" + err.message, true);
        }).then(function () {
          button.disabled = false;
        });
      });
    }
    if ($("btn-join-qq-group")) {
      $("btn-join-qq-group").addEventListener("click", function () {
        var button = this;
        button.disabled = true;
        var copied = true;
        copyText(QQ_GROUP_NUMBER).catch(function () {
          copied = false;
        }).then(function () {
          return api("/api/ui/open-qq-group", { method: "POST" });
        }).then(function () {
          toast(copied ? "群号已复制，已打开 QQ 加群邀请" : "已打开 QQ 加群邀请，请按页面提示操作");
        }).catch(function (err) {
          toast("打开 QQ 加群页失败：" + err.message, true);
        }).then(function () {
          button.disabled = false;
        });
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

    var pendingPayload = null;
    var renderScheduled = false;
    function scheduleRender(payload) {
      pendingPayload = payload;
      if (renderScheduled) { return; }
      renderScheduled = true;
      var render = function () {
        renderScheduled = false;
        var latest = pendingPayload;
        pendingPayload = null;
        if (latest) { renderState(latest); }
      };
      if (typeof window.requestAnimationFrame === "function") { window.requestAnimationFrame(render); }
      else { setTimeout(render, 0); }
    }
    socket.onmessage = function (event) {
      var payload;
      try { payload = JSON.parse(event.data); } catch (e) { return; }
      scheduleRender(payload);
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

  function bindPageLinks() {
    document.getElementById("page-colors").addEventListener("click", function (event) {
      var chip = event.target.closest("[data-mm]");
      if (!chip) { return; }
      petFilters.reset();
      switchPage("pets", String(chip.dataset.mm));
    });
    document.getElementById("page-breeder-library").addEventListener("click", function (event) {
      var chip = event.target.closest("[data-mm]");
      if (!chip) { return; }
      switchPage("pets");
      petFilters.search(String(chip.dataset.mm));
      loadPets();
    });
    // 页面内的跨页入口：接管成 switchPage，Vue 页只声明目标，不自己改路由。
    function bindPageLinkRoot(rootId) {
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
    ["page-handbook", "page-egg-dex", "egg-box-root"].forEach(bindPageLinkRoot);
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

  /* ---------- 炫彩色卡（Vue 页，挂载后由页面自己拉数据） ---------- */
  var colorsPage = (function () {
    var mounted = null;
    return {
      load: function () {
        if (mounted) { mounted.resume(true); return; }
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

  document.addEventListener("preferenceschanged", function (event) { if (petFilters) { petFilters.setShortcuts(event.detail.shortcuts); } });

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
      renderCapture(payload.capture || {});
      renderState(payload.state || {});
      renderFeaturePlaceholders();
      bindPageLinks();
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
