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
  window.addEventListener("pagehide", function () {
    eggBoxPageGeneration++;
    if (eggBoxPage) { eggBoxPage.unmount(); eggBoxPage = null; }
    if (petInventory) { petInventory.unmount(); }
    if (petFilters) { petFilters.unmount(); }
    eggDex.unmount();
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

  function levelColor(level) {
    if (level >= 60) { return "#d08a1e"; }
    if (level >= 40) { return "#7a5cc4"; }
    if (level >= 20) { return "#2f8fb5"; }
    return "#4c8f7a"; 
  }

  var TYPE_FALLBACK = "#6b8188";

  function badgeStyle(color) {
    // 游戏色不变；按WCAG相对亮度选择白/黑字，任意主题下均可读。
    var rgb = /^#[0-9a-f]{6}$/i.test(color) ? color.slice(1).match(/../g).map(function (part) {
      var value = parseInt(part, 16) / 255;
      return value <= .04045 ? value / 12.92 : Math.pow((value + .055) / 1.055, 2.4);
    }) : [0, 0, 0];
    var luminance = rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
    return "background:" + color + ";color:" + (luminance > .179 ? "#000000" : "#ffffff");
  }

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
    hb: { search: "", type: "", mode: "all" },
    hbData: null,
    hbSpecies: [],
    hbSelected: null,
    hbTypeBuilt: false,
    hbLimit: 120,
    capture: null
  };

  /* ---------- 导航 ---------- */
  function switchPage(name) {
    if (state.page === name) { return; }
    if (name === "pets" || name === "egg-box") { $("page-" + name).classList.add("page-cached"); }
    if (state.page === "egg-box" && name !== "egg-box") { pauseEggBoxPage(); }
    else { accountRequests.cancel(state.page); }
    if (state.page === "breeder-library") {
      accountRequests.cancel("breeder-male"); accountRequests.cancel("breeder-female");
    }
    if (state.page === "pets") {
      petInventory.pause(); petFilters.pause();
    }
    if (state.page === "egg-dex") { eggDex.leave(); }
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
    if (name === "pets") { petFilters.activate(); loadPets(false, true); }
    if (name === "handbook") { loadHandbook(false, true); }
    if (name === "egg-dex") { eggDex.load(); }
    if (name === "egg-box") { loadEggBoxPage(true); }
    if (name === "male-matrix") { loadMaleMatrix(); }
    if (name === "home") { loadHome(); }
    if (name === "breeder-library") { loadBreederLibrary(); }
    if (name === "flowers") { loadFlowers(); }
    if (name === "colors") { loadColors(); }
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
    if (state.page !== "egg-dex") { window.SpriteLensUI.closeDetail(false, true); }
    petInventory.resetAccount(); petFilters.resetAccount(); state._petsVersion = -1;
    state.hbData = null; state.hbSpecies = []; state.hbSelected = null;
    eggBoxVersion = -1;
    if (eggBoxPage) { eggBoxPage.resetAccount(); }
    homeState.data = { available: false }; homeState.version = -1; renderHome();
    flowerState.data = { available: false }; flowerState.version = -1; renderFlowers();
    mmState.data = null; mmState.selected = null;
    ["hb-grid", "mm-matrix", "bl-male", "bl-female", "cl-matrix", "cl-seasonal", "cl-unknown"].forEach(function (id) {
      $(id).innerHTML = "";
    });
    ["hb-count", "mm-count", "bl-male-count", "bl-female-count", "cl-meta", "cl-seasonal-count", "cl-unknown-count"].forEach(function (id) {
      $(id).textContent = "等待当前账号数据";
    });
    ["hb-detail", "mm-detail"].forEach(function (id) {
      $(id).innerHTML = '<div class="empty-hint">请选择当前账号的条目</div>';
    });
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
    if (payload.home_version !== undefined && payload.home_version !== homeState.version) {
      homeState.version = payload.home_version;
      if (state.page === "home") { loadHome(); }
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
      var refresh = { pets: loadPets, handbook: loadHandbook, "male-matrix": loadMaleMatrix,
        "breeder-library": loadBreederLibrary, colors: loadColors };
      if (refresh[state.page]) { refresh[state.page](false); }
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

  /* ---------- 精灵图鉴 ---------- */
  var HB_PAGE_SIZE = 120; // 一次渲染上限：1015 个富卡片全量入 DOM 会明显卡顿
  var hbQuery = "";

  function loadHandbook(resetLimit, reuse) {
    if (resetLimit !== false) { state.hbLimit = HB_PAGE_SIZE; }
    var params = {
      search: state.hb.search,
      type: state.hb.type,
      collected: state.hb.mode === "collected" ? "1" : "",
      uncollected: state.hb.mode === "uncollected" ? "1" : ""
    };
    var path = "/api/handbook" + query(params);
    var owner = accountRequests.petContext();
    if (reuse && state.hbData && state.hbData.uid === owner.uid
        && state.hbData.version >= owner.version && hbQuery === path) { return Promise.resolve(); }
    return accountRequests.request("handbook", path).then(function (payload) {
      if (!payload) { return; }
      state.hbData = payload;
      hbQuery = path;
      state.hbSpecies = payload.species || [];
      renderHandbook(payload);
    }).catch(function (err) { toast("图鉴加载失败：" + err.message, true); });
  }

  function renderHandbook(payload) {
    $("hb-count").textContent = "收录 " + (payload.collected || 0) + " / " + (payload.total || 0) + " 种";
    var all = payload.species || [];
    var shown = all.slice(0, state.hbLimit);
    var remaining = all.length - shown.length;
    $("hb-empty").hidden = all.length > 0;

    // 系别下拉与模式按钮只建一次
    if (!state.hbTypeBuilt && (payload.type_options || []).length) {
      state.hbTypeBuilt = true;
      $("hb-type").innerHTML = '<option value="">全部系别</option>'
        + payload.type_options.map(function (name) {
            return '<option value="' + esc(name) + '">' + esc(name) + "</option>";
          }).join("");
    }

    $("hb-grid").innerHTML = shown.map(function (item) {
      var types = (item.type_names || []).map(function (name, index) {
        var color = (item.type_colors || [])[index] || TYPE_FALLBACK;
        return '<span class="type-badge" style="' + badgeStyle(color) + '">' + esc(name) + "</span>";
      }).join(" ");
      var evo = (item.evolutions || []).length
        ? '<div class="hb-evo">进化 → <b>' + esc(item.evolutions[0].name) + "</b>"
          + (item.evolutions.length > 1 ? " 等 " + item.evolutions.length + " 条" : "") + "</div>"
        : "";
      var badge = item.collected
        ? '<span class="hb-badge">拥有 ' + item.owned_count + " · Lv" + item.best_level + "</span>"
        : '<span class="hb-badge none">未收集</span>';
      var dexLabel = item.handbook_no || (item.dex_no ? String(item.dex_no) : item.key);
      var img = item.icon_url
        ? '<img src="' + esc(item.icon_url) + '" alt="" loading="lazy" onerror="this.remove()">'
        : "";
      return '<article class="hb-card' + (item.collected ? "" : " uncollected")
        + '" data-key="' + esc(item.key) + '" role="button" tabindex="0" aria-label="查看' + esc(item.name) + '详情">'
        + '<div class="hb-head"><span class="hb-key">' + esc(dexLabel) + "</span>"
        + '<span class="hb-art">' + esc((item.name || "?").slice(0, 1)) + img + "</span>"
        + "<div><strong>" + esc(item.name) + "</strong>"
        + "<small>" + (item.stage ? "第 " + item.stage + " 阶" : "") + "</small></div></div>"
        + '<div class="hb-meta">' + (types || '<span class="muted">—</span>')
        + '<span class="hb-sum">六维 ' + (item.stat_sum || "—") + "</span></div>"
        + badge + evo
        + "</article>";
    }).join("");

    // 分批渲染的「显示更多」：剩余过多时给出提示，避免误解为只收录了这些
    if (remaining > 0) {
      var footer = document.createElement("div");
      footer.className = "hb-more";
      footer.innerHTML = '<button id="hb-more-btn" class="ghost-button small">显示更多（剩余 '
        + remaining + " 种）</button>";
      $("hb-grid").appendChild(footer);
      footer.querySelector("#hb-more-btn").addEventListener("click", function () {
        state.hbLimit += HB_PAGE_SIZE * 2;
        renderHandbook(state.hbData);
      });
    }

    $("hb-grid").querySelectorAll(".hb-card").forEach(function (card) {
      card.addEventListener("click", function () {
        state.hbSelected = card.dataset.key;
        $("hb-grid").querySelectorAll(".hb-card").forEach(function (node) {
          node.classList.toggle("active", node === card);
        });
        renderHandbookDetail(state.hbSelected);
      });
    });
    if (state.hbSelected) { renderHandbookDetail(state.hbSelected); }
  }

  function findSpecies(key) {
    for (var i = 0; i < (state.hbSpecies || []).length; i++) {
      if (state.hbSpecies[i].key === key) { return state.hbSpecies[i]; }
    }
    return null;
  }

  function renderHandbookDetail(key) {
    var item = findSpecies(key);
    var panel = $("hb-detail");
    if (!item) {
      panel.innerHTML = '<div class="empty-hint">点击左侧图鉴卡片查看详情</div>';
      return;
    }
    var stats = item.stats || {};
    var peak = Math.max.apply(null, Object.keys(stats).map(function (k) { return stats[k]; }).concat([1]));
    var labels = { hp: "生命", atk: "物攻", spa: "魔攻", def: "物防", spd: "魔防", spe: "速度" };
    var rows = ["hp", "atk", "spa", "def", "spd", "spe"].map(function (slot) {
      var value = stats[slot] || 0;
      return "<tr><td>" + labels[slot] + '</td><td class="num">' + value + "</td>"
        + '<td class="bar"><span class="detail-bar"><i style="width:'
        + Math.round((value / peak) * 100) + '%"></i></span></td></tr>';
    }).join("");

    var types = (item.type_names || []).map(function (name, index) {
      var color = (item.type_colors || [])[index] || TYPE_FALLBACK;
      return '<span class="type-badge" style="' + badgeStyle(color) + '">' + esc(name) + "</span>";
    }).join(" ") || '<span class="muted">—</span>';

    var chain = (item.chain_members || []).length ? item.chain_members : item.evolutions || [];
    var evoHtml = chain.length
      ? chain.map(function (evo) {
          return '<span class="skill-chip">' + esc(evo.name) + "（" + esc(evo.key) + "）</span>";
        }).join("")
      : '<span class="muted">无进化记录</span>';

    var owned = item.collected
      ? '<b class="positive">已收集</b> · 拥有 ' + item.owned_count + " 只 · 最高 Lv" + item.best_level
      : '<span class="muted">尚未收集</span>';

    var metaLines = [];
    var dexText = item.handbook_no || (item.dex_no ? String(item.dex_no) : "");
    if (dexText) { metaLines.push("图鉴号 " + esc(dexText)); }
    var ratio = item.gender_ratio || [0, 0];
    if (ratio[0] || ratio[1]) {
      metaLines.push("性别比 ♂" + ratio[0] + "% / ♀" + ratio[1] + "%");
    }
    if (item.has_shiny) { metaLines.push("有闪光形态"); }

    panel.innerHTML =
      '<div class="detail-title"><h2>' + esc(item.name) + "</h2>"
      + '<span class="muted">#' + esc(item.key) + "</span></div>"
      + '<div class="detail-sub">' + owned + "</div>"
      + (metaLines.length ? '<div class="detail-sub">' + metaLines.join(" · ") + "</div>" : "")

      + (item.description
        ? '<div class="detail-section"><h3>图鉴描述</h3><p class="species-desc">' + esc(item.description) + "</p></div>"
        : "")

      + '<div class="detail-section"><h3>系别</h3><div class="info-line">' + types + "</div></div>"

      + ((item.egg_groups || []).length
          ? '<div class="detail-section"><h3>蛋组</h3><div class="skill-list">'
            + item.egg_groups.map(function (g) { return '<span class="skill-chip">' + esc(g) + "</span>"; }).join("")
            + "</div></div>"
          : "")

      + window.SpriteLensAppearance.ranges("物种参考范围", item.reference_ranges)
      + '<div class="detail-section"><h3>种族值</h3>'
      + '<table class="stat-table"><tbody>' + rows + "</tbody></table>"
      + '<div class="info-line muted">总和 ' + (item.stat_sum || 0)
      + (item.max_energy ? " · 最大能量 " + item.max_energy : "")
      + (item.quality ? " · 品质 " + item.quality : "") + "</div></div>"

      + '<div class="detail-section"><h3>进化链</h3><div class="skill-list">' + evoHtml + "</div></div>";
  }

  function bindHandbookFilters() {
    var timer = null;
    $("hb-search").addEventListener("input", function (event) {
      state.hb.search = event.target.value.trim();
      clearTimeout(timer);
      timer = setTimeout(loadHandbook, 220);
    });
    $("hb-type").addEventListener("change", function () {
      state.hb.type = $("hb-type").value;
      loadHandbook();
    });
    $("hb-mode").querySelectorAll("button").forEach(function (node) {
      node.addEventListener("click", function () {
        state.hb.mode = node.dataset.mode;
        $("hb-mode").querySelectorAll("button").forEach(function (item) {
          item.classList.toggle("active", item === node);
        });
        loadHandbook();
      });
    });
  }

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
      load: function () {
        if (mounted) { mounted.resume(); return; }
        var current = ++generation;
        var root = $("page-egg-dex");
        root.textContent = "正在加载蛋图鉴…";
        return import("/static/vue/entry.js").then(function (page) {
          if (current !== generation) { return; }
          mounted = page.mount(root, TOKEN);
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

  /* ---------- 我的家园 ---------- */
  var homeState = { data: null, version: -1 };

  function loadHome() {
    return accountRequests.request("home", "/api/home").then(function (payload) {
      if (!payload) { return; }
      homeState.data = payload;
      homeState.version = payload.version || 0;
      renderHome();
    }).catch(function (err) { toast("家园加载失败：" + err.message, true); });
  }

  function renderHome() {
    var payload = homeState.data;
    if (!payload) { return; }
    $("home-deltas").hidden = !(payload.pending_deltas > 0);
    if (!payload.available) {
      $("home-meta").textContent = "等待家园快照（进入家园后自动更新）";
      $("home-resident-count").textContent = "—"; $("home-nest-count").textContent = "—";
      $("home-residents").innerHTML = "";
      $("home-residents-empty").hidden = false;
      $("home-nests").innerHTML = "";
      $("home-nests-empty").hidden = false;
      $("home-furniture-line").textContent = "—";
      return;
    }
    $("home-meta").textContent = "房间等级 " + payload.room_level + " · 观察快照 #" + payload.version + "（完整性未确认）";
    var residents = payload.residents || [];
    $("home-resident-count").textContent = residents.length + " 只";
    $("home-residents").innerHTML = residents.map(function (r) {
      var gender = r.gender === 2 ? '<span class="female-mark"><svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><use href="/static/icons/sprite.svg#gender-female"></use></svg></span>'
        : (r.gender === 1 ? '<span class="male-mark"><svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><use href="/static/icons/sprite.svg#gender-male"></use></svg></span>' : "");
      var img = r.icon_url
        ? '<img src="' + esc(r.icon_url) + '" alt="" loading="lazy" onerror="this.remove()">'
        : "";
      return '<div class="home-resident">'
        + '<span class="pc-avatar">' + esc((r.name || "?").slice(0, 1)) + img + "</span>"
        + '<div><b>' + esc(r.name) + "</b>" + gender
        + '<small>' + (r.level ? "Lv" + r.level : "") + (r.species_name ? " · " + esc(r.species_name) : "") + "</small></div>"
        + '<span class="muted home-pos">坐标 ' + r.position.join(", ") + "</span></div>";
    }).join("");
    $("home-residents-empty").hidden = residents.length > 0;
    var nests = payload.nests || [];
    $("home-nest-count").textContent = nests.length + " 个";
    $("home-nests").innerHTML = nests.map(function (nest) {
      return '<div class="home-nest"><div><b>' + esc(nest.name) + "</b>"
        + '<small>配置 #' + nest.config_id + " · 坐标 " + nest.position.join(", ") + "</small></div>"
        + '<span class="status-pill">产蛋窝</span></div>';
    }).join("");
    $("home-nests-empty").hidden = nests.length > 0;
    var furniture = payload.furniture || [];
    $("home-furniture-line").textContent = "共 " + furniture.length + " 件（含窝 " + nests.length + "）";
  }

  /* ---------- 种公母库（性别分组的配种宠物库） ---------- */
  function loadBreederLibrary() {
    Promise.all([
      accountRequests.request("breeder-male", "/api/male-matrix" + query({ gender: "male" })),
      accountRequests.request("breeder-female", "/api/male-matrix" + query({ gender: "female" }))
    ]).then(function (results) {
      if (!results[0] || !results[1] || results[0].uid !== results[1].uid) { return; }
      renderBreederSection("bl-male", "bl-male-count", results[0]);
      renderBreederSection("bl-female", "bl-female-count", results[1]);
    }).catch(function (err) { toast("种公母库加载失败：" + err.message, true); });
  }

  function renderBreederSection(listId, countId, payload) {
    var natures = payload.natures || [];
    var total = payload.matched || 0;
    $(countId).textContent = total + " 只（性格组 " + natures.length + "）";
    $(listId).innerHTML = natures.map(function (nature) {
      var groups = (payload.groups || []).filter(function (g) {
        return payload.cells[nature.name + "|" + g];
      });
      if (!groups.length) { return ""; }
      var natureCount = 0;
      var blocks = groups.map(function (g) {
        var pets = payload.cells[nature.name + "|" + g] || [];
        natureCount += pets.length;
        var chips = pets.map(function (pet) {
          return petChip(pet);
        }).join("");
        return '<div class="bl-group"><b>' + esc(g)
          + '<span class="muted">' + pets.length + " 只</span></b>"
          + '<div class="bl-chips">' + chips + "</div></div>";
      }).join("");
      return '<details class="bl-nature" open><summary>' + esc(nature.name)
        + '<span class="count-badge">' + natureCount + "</span>"
        + '<small>' + (nature.positive ? (STAT_CN[nature.positive] || nature.positive) + "↑ " : "")
        + (nature.negative ? (STAT_CN[nature.negative] || nature.negative) + "↓" : "") + "</small></summary>"
        + blocks + "</details>";
    }).join("") || '<div class="empty-hint">没有符合条件的宠物</div>';
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
  function loadColors() {
    accountRequests.request("colors", "/api/colors").then(function (payload) {
      if (payload) { renderColors(payload); }
    }).catch(function (err) {
      toast("色卡加载失败：" + err.message, true);
    });
  }

  function petChip(pet, withLevel) {
    var mark = '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><use href="/static/icons/sprite.svg#gender-' + (pet.gender === 2 ? "female" : "male") + '"></use></svg>';
    return '<span class="mm-pet" data-mm="' + pet.gid + '"><img src="' + esc(pet.icon_url)
      + '" alt="" loading="lazy" onerror="this.remove()">' + mark + esc(pet.name)
      + (withLevel === false ? "" : '<small>Lv' + pet.level + "</small>") + "</span>" + window.SpriteLensPetPresentation.colorCard(pet.color_card);
  }

  function axisSwatch(axis) {
    return axis && axis.hex
      ? '<i class="swatch" style="background:' + esc(axis.hex) + '"></i>' : "";
  }

  function renderColors(payload) {
    var baseAxis = payload.base_axis || [];
    var mixAxis = payload.mix_axis || [];
    var matrix = payload.matrix || {};
    var head = '<tr><th class="mm-corner">混色 \ 底色</th>' + baseAxis.map(function (b) {
      return "<th>" + axisSwatch(b) + esc(b.name) + "</th>";
    }).join("") + "</tr>";
    var body = mixAxis.map(function (mix) {
      var cells = baseAxis.map(function (base) {
        var pets = matrix[base.name + "|" + mix.name];
        if (!pets) { return "<td class='mm-cell empty'>—</td>"; }
        var chips = pets.map(petChip).join("");
        return '<td class="mm-cell">' + chips + "</td>";
      }).join("");
      return '<tr><th class="mm-rowhead">' + axisSwatch(mix) + "<b>" + esc(mix.name) + "</b></th>" + cells + "</tr>";
    }).join("");
    $("cl-matrix").innerHTML = "<table><thead>" + head + "</thead><tbody>" + body + "</tbody></table>";
    $("cl-empty").hidden = (payload.pet_total || 0) > 0;
    /* 收录卡数：矩阵内 + 赛季卡涉及的卡号去重 */
    var seen = {};
    Object.keys(matrix).forEach(function (key) {
      (matrix[key] || []).forEach(function (pet) { seen[pet.card_id] = true; });
    });
    var seasonal = payload.seasonal || [];
    seasonal.forEach(function (pet) { seen[pet.card_id] = true; });
    var collected = Object.keys(seen).length;
    $("cl-meta").textContent = "收录 " + collected + " / " + payload.card_total + " 张 · 持有者 "
      + payload.pet_total + " 只 · 赛季卡 " + seasonal.length + " 只";
    $("cl-seasonal").innerHTML = seasonal.map(petChip).join("");
    $("cl-seasonal-count").textContent = seasonal.length + " 只";
    $("cl-seasonal-empty").hidden = seasonal.length > 0;
    var unknown = payload.unknown || [];
    $("cl-unknown").innerHTML = unknown.map(function (pet) {
      return petChip(pet) + '<span class="muted">#' + esc(pet.card_id) + "</span>";
    }).join("");
    $("cl-unknown-count").textContent = unknown.length + " 只";
    $("cl-unknown-empty").hidden = unknown.length > 0;
  }

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
      bindHandbookFilters();
      bindMaleMatrixActions();
      bindCaptureActions();
      loadIfaces();
      connectPush();
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
