/* 小洛探探 SpriteLens — 前端逻辑（原生 JS，零框架、零构建）
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
    pets: [],
    petOptions: null,
    selectedPetGid: null,
    events: [],
    selectedEventIndex: null,
    filters: { search: "", level_min: 1, level_max: 100, natures: [], types: [], talent_min: 0, gender: 0, sort: "gid", desc: false },
    petView: "point",
    petPage: 1,
    petBox: null,
    petTeams: false,
    lastPayload: null,
    hb: { search: "", type: "", mode: "all" },
    hbData: null,
    hbSpecies: [],
    hbSelected: null,
    hbTypeBuilt: false,
    hbLimit: 120,
    capture: null,
    petTotal: 0
  };

  /* ---------- 导航 ---------- */
  function switchPage(name) {
    if (state.page === "pets") {
      state.petScrollTop = $("pet-grid").closest(".table-wrap").scrollTop;
    }
    window.SpriteLensUI.closeDetail(false, true);
    state.page = name;
    document.querySelectorAll(".page").forEach(function (node) {
      node.classList.toggle("active", node.id === "page-" + name);
    });
    document.querySelectorAll(".nav-item").forEach(function (node) {
      node.classList.toggle("active", node.dataset.page === name);
      if (node.dataset.page === name) { node.setAttribute("aria-current", "page"); }
      else { node.removeAttribute("aria-current"); }
    });
    if (name === "pets") { loadPets(false, true); }
    if (name === "handbook") { loadHandbook(); }
    if (name === "egg-dex") { loadEggDex(); }
    if (name === "egg-box") { loadEggBox(); }
    if (name === "male-matrix") { loadMaleMatrix(); }
    if (name === "home") { loadHome(); }
    if (name === "breeder-library") { loadBreederLibrary(); }
    if (name === "flowers") { loadFlowers(); }
    if (name === "colors") { loadColors(); }
    if (name === "events") { loadEvents(); }
    if (name === "capture") { loadCapture(); }
    if (name === "overview") { loadOverview(); }
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

  function loadOverview() {
    api("/api/pets").then(function (payload) {
      // 概览统计从 bootstrap 的 overview 已给；单独刷新时用 pets 的 total 兜底
      $("ov-total").textContent = payload.total || 0;
    }).catch(function () {});
  }

  /* ---------- 顶栏状态 ---------- */
  function renderRole(identity, cached) {
    var role = identity || cached;
    $("role-label").textContent = identity ? "当前角色" : cached ? "上次角色 · 本次未确认" : "当前角色";
    if (role) {
      $("role-name").textContent = role.name || "未知角色";
      $("role-uid").textContent = "UID " + role.uid + (role.level ? " · Lv" + role.level : "");
    } else {
      $("role-name").textContent = "等待识别角色";
      $("role-uid").textContent = "UID —";
    }
  }

  function setPill(id, text, tone) {
    var node = $(id);
    node.textContent = text;
    node.className = "status-pill " + (tone || "idle");
  }

  function renderState(payload) {
    var capture = payload.capture || {};
    setPill("pill-listen", "采集：" + (capture.running ? "进行中" : "未启动"), capture.running ? "ok" : "idle");
    setPill("pill-key", "密钥：" + (capture.any_key ? "已获取" : "未获取"), capture.any_key ? "ok" : "warn");
    setPill("pill-record", "录制：" + (capture.recording ? "开" : "关"), capture.recording ? "ok" : "idle");
    setPill("pill-pets", "宠物：" + (payload.pets_total || 0) + " 只", (payload.pets_total || 0) > 0 ? "ok" : "idle");

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

    // 顶栏单按钮切换：运行中 = 危险色"停止采集"，否则主色"开始采集"
    var toggle = $("btn-toggle");
    if (toggle) {
      var running = !!capture.running;
      toggle.textContent = running ? "停止采集" : "开始采集";
      toggle.classList.toggle("stop-button", running);
      toggle.onclick = running ? doStop : doStart;
    }
    $("btn-capture-start").disabled = !!capture.running;
    $("btn-capture-stop").disabled = !capture.running;

    // 蛋仓有新数据且当前在蛋仓页 → 自动刷新（版本号变化才触发）
    if (payload.egg_box_version !== undefined && payload.egg_box_version !== eggBoxState.version) {
      eggBoxState.version = payload.egg_box_version;
      if (state.page === "egg-box") { loadEggBox(); }
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

    if (payload.stats && payload.stats.types && state.page === "overview") {
      renderTypeDist(payload.stats.types || []);
    }

    if (state.page === "capture") { renderCaptureSummary(payload.capture || {}); }
    if (payload.environment) { renderEnvBanner(payload.environment); }
    var version = payload.pets_version;
    if (version !== undefined && version !== state._petsVersion) {
      state._petsVersion = version;
      if (state.page === "pets") { loadPets(false); }
    }
  }

  /* ---------- 宠物仓库 ---------- */
  function loadPets(resetPage, restoreWorkspace) {
    if (resetPage !== false) { state.petPage = 1; }
    var requestId = (state._petRequest || 0) + 1;
    state._petRequest = requestId;
    $("pet-count").textContent = "更新中…";
    $("pet-grid").setAttribute("aria-busy", "true");
    var f = state.filters;
    var params = {
      search: f.search,
      level_min: f.level_min,
      level_max: f.level_max,
      natures: f.natures.join(","),
      types: f.types.join(","),
      talent_min: f.talent_min || "",
      gender: f.gender || "",
      sort: f.sort,
      desc: f.desc ? "1" : ""
    };
    Object.assign(params, window.SpriteLensPetFilters.query());
    return api("/api/pets" + query(params)).then(function (payload) {
      if (requestId !== state._petRequest) { return; }
      $("pet-grid").setAttribute("aria-busy", "false");
      state.pets = payload.pets || [];
      state.petTotal = payload.total || 0;
      state.lastPayload = payload;
      renderPetFilters(payload.options || {});
      renderPets(payload);
      if (state.selectedPetGid && !findPet(state.selectedPetGid)) {
        window.SpriteLensUI.closeDetail(false);
        state.selectedPetGid = null; setPetDetailOpen(false);
      }
      if (state.selectedPetGid) {
        renderPetDetail(state.selectedPetGid);
        if (restoreWorkspace && state.page === "pets") {
          var selected = document.querySelector('#page-pets [data-gid="' + state.selectedPetGid + '"]');
          window.SpriteLensUI.openDetail("pet-detail", selected);
        }
      }
      if (restoreWorkspace) { $("pet-grid").closest(".table-wrap").scrollTop = state.petScrollTop || 0; }
    }).catch(function (err) {
      if (requestId !== state._petRequest) { return; }
      $("pet-grid").setAttribute("aria-busy", "false");
      $("pet-count").textContent = "加载失败";
      $("pet-empty").hidden = false;
      $("pet-empty-copy").textContent = "精灵数据加载失败，请重新进入本页重试。";
      $("btn-empty-reset").hidden = true;
      toast("宠物数据加载失败：" + err.message, true);
    });
  }

  function renderPetFilters(options) {
    if (options.natures && !$("f-natures").dataset.built) {
      $("f-natures").dataset.built = "1";
      $("f-natures").innerHTML = options.natures.map(function (item) {
        return '<button class="chip" data-nature="' + item.id + '">' + esc(item.name) + "</button>";
      }).join("");
      $("f-natures").querySelectorAll(".chip").forEach(function (node) {
        node.addEventListener("click", function () {
          node.classList.toggle("active");
          state.filters.natures = Array.prototype.map.call(
            $("f-natures").querySelectorAll(".chip.active"),
            function (item) { return Number(item.dataset.nature); }
          );
          loadPets();
        });
      });
    }
    if (options.types && !$("f-types").dataset.built) {
      $("f-types").dataset.built = "1";
      $("f-types").innerHTML = options.types.map(function (name) {
        return '<button class="chip" data-type="' + esc(name) + '">' + esc(name) + "</button>";
      }).join("");
      $("f-types").querySelectorAll(".chip").forEach(function (node) {
        node.addEventListener("click", function () {
          node.classList.toggle("active");
          state.filters.types = Array.prototype.map.call(
            $("f-types").querySelectorAll(".chip.active"),
            function (item) { return item.dataset.type; }
          );
          loadPets();
        });
      });
    }
    if (options.sorts && !$("f-sort").dataset.built) {
      $("f-sort").dataset.built = "1";
      $("f-sort").innerHTML = options.sorts.map(function (item) {
        return '<option value="' + item.key + '">' + esc(item.label) + "</option>";
      }).join("");
    }
    if (options.talent_max !== undefined && !$("f-talent").dataset.built) {
      $("f-talent").dataset.built = "1";
      var max = Math.max(Number(options.talent_max) || 0, 0);
      var html = '<option value="0">不限</option>';
      for (var i = 1; i <= max; i++) { html += '<option value="' + i + '">≥ ' + i + ' 阶</option>'; }
      $("f-talent").innerHTML = html;
    }
  }

  var PET_PAGE_SIZE = 60; // 浏览分页，不代表游戏内箱位。

  function renderPets(payload) {
    var pets = payload.pets || [];
    var backpack = payload.backpack || { boxes: [] };
    var boxes = (backpack.boxes || []).filter(function (box) {
      return box.slots.length !== 30 || box.slots.some(function (slot) { return slot.state !== "empty"; });
    });
    var fixed = state.petView === "point";
    var box = boxes.filter(function (item) { return item.box_id === state.petBox; })[0];
    if (!box && boxes.length) {
      box = boxes.filter(function (item) { return item.matched; })[0] || boxes[0];
      state.petBox = box.box_id;
    }
    var focused = $("pet-grid").contains(document.activeElement) ? document.activeElement : null;
    var focusGid = focused && focused.dataset.gid;
    var scrollWrap = $("pet-grid").closest(".table-wrap");
    var scrollTop = scrollWrap.scrollTop, scrollLeft = scrollWrap.scrollLeft;
    var shown = pets;
    if (state.petView !== "table" && !fixed) {
      var pages = Math.max(1, Math.ceil(pets.length / PET_PAGE_SIZE));
      if (state.petPage > pages) { state.petPage = pages; }
      var start = (state.petPage - 1) * PET_PAGE_SIZE;
      shown = pets.slice(start, start + PET_PAGE_SIZE);
    }
    $("pet-count").textContent = "命中 " + (payload.shown || 0) + " / " + (payload.total || 0) + " 只";
    $("pet-empty").hidden = fixed ? (state.petTeams ? !!(backpack.teams || []).length : !!box) : pets.length > 0;
    $("pet-empty-copy").textContent = fixed ? (state.petTeams ? "尚未采集出战队伍，登录游戏后同步。" : (backpack.boxes || []).length ? "已采集的箱子均为空箱，可切换出战背包查看队伍。" : "尚未采集游戏箱表。登录游戏后同步，可切换属性卡片或对比表格查看已采集精灵。") : payload.total > 0
      ? "没有符合筛选条件的精灵，可清除筛选后查看全部。"
      : "暂无精灵数据：开始采集后登录游戏，等待数据同步。";
    $("btn-empty-reset").hidden = fixed || pets.length > 0 || !payload.total;
    $("pet-box-navigation").hidden = state.petView !== "point";
    $("f-sort").disabled = fixed; $("f-desc").disabled = fixed;
    $("f-sort").closest("label").hidden = fixed;
    $("f-desc").closest("label").hidden = fixed;
    $("f-sort").title = fixed ? "游戏箱位固定，排序用于属性卡片和对比表格" : "";

    if (state.petView === "point") {
      $("pet-grid").hidden = false;
      $("pet-table").hidden = true;
      renderBoxNavigation(backpack, box, boxes);
      var byGid = {};
      pets.forEach(function (pet) { byGid[pet.gid] = pet; });
      var slots = state.petTeams ? (backpack.teams || []).reduce(function (all, team) { return all.concat(team.slots); }, []) : box && box.slots;
      renderPetPoints(slots ? slots.map(function (slot) { return slot.state === "matched" ? byGid[slot.gid] : null; }) : [], slots, state.petTeams);
      $("pet-pager").hidden = true;
    } else if (state.petView === "card") {
      $("pet-grid").hidden = false;
      $("pet-table").hidden = true;
      renderPetCards(shown);
      renderPetPager(pets.length);
    } else {
      $("pet-grid").hidden = true;
      $("pet-table").hidden = false;
      $("pet-pager").hidden = true;
      renderPetTable(shown);
    }
    scrollWrap.scrollTop = scrollTop; scrollWrap.scrollLeft = scrollLeft;
    if (focusGid) {
      var nextFocus = $("pet-grid").querySelector('[data-gid="' + focusGid + '"]');
      if (nextFocus) { nextFocus.focus({ preventScroll: true }); }
      else { $("pet-box-navigation").querySelector("button")?.focus({ preventScroll: true }); }
    }
    document.dispatchEvent(new CustomEvent("petsrendered", { detail: payload }));
  }

  function renderBoxNavigation(backpack, box, boxes) {
    var index = boxes.indexOf(box), from = Math.floor(Math.max(0, index) / 10) * 10;
    var html = '<div class="box-navigation-row">';
    html += '<button class="ghost-button small' + (state.petTeams ? ' active' : '') + '" data-box="0" aria-pressed="' + state.petTeams + '">出战背包' + ((backpack.teams || []).length ? ' · ' + backpack.teams.reduce(function (sum, team) { return sum + team.matched; }, 0) : '') + '</button>';
    if (boxes.length) {
      if (boxes.length > 10) { html += '<button class="ghost-button small" data-box="' + boxes[Math.max(0, from - 1)].box_id + '"' + (from === 0 ? ' disabled' : '') + '>上一批</button>'; }
      boxes.slice(from, from + 10).forEach(function (item) {
        var active = !state.petTeams && item === box;
        html += '<button class="box-number' + (active ? ' active' : '') + (backpack.filtering && item.matched ? ' box-hit' : '') + '" data-box="' + item.box_id + '" aria-pressed="' + active + '" title="第 ' + item.box_id + ' 箱 · 命中 ' + item.matched + ' 只">' + item.box_id + '<small>' + item.matched + '</small></button>';
      });
      if (boxes.length > 10) { html += '<button class="ghost-button small" data-box="' + boxes[Math.min(boxes.length - 1, from + 10)].box_id + '"' + (from + 10 >= boxes.length ? ' disabled' : '') + '>下一批</button>'; }
      html += '<label class="inline-field">跳转<select id="pet-box-jump" aria-label="跳转游戏箱号">' + boxes.map(function (item) { return '<option value="' + item.box_id + '"' + (item === box ? ' selected' : '') + '>第 ' + item.box_id + ' 箱</option>'; }).join('') + '</select></label>';
      var hits = boxes.filter(function (item) { return item.matched > 0; });
      var before = hits.filter(function (item) { return box && item.box_id < box.box_id; }).pop();
      var after = hits.filter(function (item) { return box && item.box_id > box.box_id; })[0];
      if (backpack.filtering) { html += '<button class="ghost-button small" data-box="' + (before ? before.box_id : '') + '"' + (!before ? ' disabled' : '') + '>上一命中箱</button><button class="ghost-button small" data-box="' + (after ? after.box_id : '') + '"' + (!after ? ' disabled' : '') + '>下一命中箱</button>'; }
    }
    html += '</div>';
    var description = state.petTeams
      ? '出战背包 · 3 队 × 6 格' + (backpack.active_team ? ' · 当前出战第 ' + backpack.active_team + ' 队' : '') + ((backpack.teams || []).some(function (team) { return team.historical; }) ? ' · 历史队伍，登录后更新' : '') : box
      ? '第 ' + box.box_id + ' 箱' + (box.name ? ' · ' + box.name : '') + ' · 命中 ' + box.matched + ' / 已知占用 ' + box.occupied + ' 格 · 6 列 × 5 行' + (box.historical ? ' · 历史箱表，登录后更新' : ' · 本次采集') + (box.unknown ? ' · ' + box.unknown + ' 格未采集' : '')
      : (backpack.boxes || []).length ? '已采集的箱子均为空箱。' : '没有已采集箱表；不会将未采集的箱子显示为空箱。';
    $("pet-box-navigation").innerHTML = html + '<div class="box-status-row"><p class="filter-note" role="status">' + esc(description.replace(' · 6 列 × 5 行', '')) + '</p>' + (box || state.petTeams ? '<details class="box-help"><summary>箱位说明</summary><p>空格：空位 · 筛掉：不匹配条件 · 待补：个体资料未到 · 未采集：槽位未知。窄窗口可横向滚动；方向键浏览精灵，Enter打开详情，Esc返回。</p></details>' : '') + '</div>';
  }

  function selectPetBox(boxId) {
    state.petTeams = Number(boxId) === 0;
    if (!state.petTeams) { state.petBox = Number(boxId); }
    window.SpriteLensUI.closeDetail(false, true);
    renderPets(state.lastPayload || {});
    var wrap = $("pet-grid").closest(".table-wrap"); wrap.scrollTop = 0; wrap.scrollLeft = 0;
    var selected = $("pet-grid").querySelector('[data-gid="' + state.selectedPetGid + '"]');
    (selected || $("pet-box-navigation").querySelector('[data-box="' + (state.petTeams ? 0 : state.petBox) + '"]'))?.focus({ preventScroll: true });
  }

  /* 精灵图：有图显示立绘（覆盖在首字之上）；加载失败自动移除，露出首字头像 */
  /* 点阵视图承载可比较的信息，悬停不放大，避免遮挡相邻宠物。 */
  function bindPointGrid() {
    $("pet-box-navigation").addEventListener("click", function (event) {
      var button = event.target.closest("[data-box]");
      if (button && !button.disabled) { selectPetBox(button.dataset.box); }
    });
    $("pet-box-navigation").addEventListener("change", function (event) { if (event.target.id === "pet-box-jump") { selectPetBox(event.target.value); } });
    $("pet-detail").addEventListener("click", function (event) {
      var button = event.target.closest("[data-locate-box], [data-locate-team]");
      if (!button) { return; }
      state.petView = "point"; window.SpriteLensAppearance.view("point");
      $("pet-view").querySelectorAll("button").forEach(function (node) { var active = node.dataset.view === "point"; node.classList.toggle("active", active); node.setAttribute("aria-pressed", String(active)); });
      selectPetBox(button.hasAttribute("data-locate-team") ? 0 : button.dataset.locateBox);
    });
    $("pet-grid").addEventListener("keydown", function (event) {
      if (!$("pet-grid").classList.contains("game-box-grid")) { return; }
      var cell = event.target.closest("[data-slot]"), step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -6, ArrowDown: 6 }[event.key];
      if (!cell || !step) { return; }
      event.preventDefault();
      var original = Number(cell.dataset.slot), slot = original + step;
      while (slot >= 1 && slot <= (state.petTeams ? 18 : 30)) {
        if (Math.abs(step) === 1 && Math.floor((slot - 1) / 6) !== Math.floor((original - 1) / 6)) { break; }
        var target = $("pet-grid").querySelector('button[data-slot="' + slot + '"]');
        if (target) { target.focus(); break; } slot += step;
      }
    });
    $("pet-grid").addEventListener("click", function (event) {
      var cell = event.target.closest("[data-gid]");
      if (!cell || state.petView !== "point") { return; }
      state.selectedPetGid = Number(cell.dataset.gid);
      setPetDetailOpen(true);
      renderPetDetail(state.selectedPetGid);
    });
  }
  function renderPetPoints(pets, slots, teams) {
    $("pet-grid").className = "pet-grid point-grid" + (slots ? " game-box-grid" : "");
    $("pet-grid").hidden = false;
    $("pet-table").hidden = true;
    $("pet-grid").innerHTML = pets.map(function (pet, index) {
      var heading = teams && index % 6 === 0 ? '<div class="pet-team-heading">第 ' + (Math.floor(index / 6) + 1) + ' 队' + (((state.lastPayload || {}).backpack || {}).active_team === Math.floor(index / 6) + 1 ? ' · 当前出战' : '') + '</div>' : '';
      if (!pet) {
        var status = slots[index].state, label = { empty: "空格", filtered: "筛掉", missing: "待补", unknown: "未采集" }[status];
        return heading + '<div class="pet-box-slot slot-' + status + '" aria-label="第 ' + (Math.floor(index / 6) + 1) + (teams ? ' 队第 ' : ' 行第 ') + (index % 6 + 1) + (teams ? ' 格，' : ' 列，') + label + '"><span>' + label + '</span></div>';
      }
      var mark = pet.gender === 2 ? "♀" : (pet.gender === 1 ? "♂" : "—");
      var genderClass = pet.gender === 2 ? "female" : (pet.gender === 1 ? "male" : "");
      return heading + '<button type="button" class="point-pet ' + genderClass + (state.selectedPetGid === pet.gid ? " selected" : "")
        + '" data-slot="' + (index + 1) + '" data-gid="' + pet.gid + '" aria-pressed="' + (state.selectedPetGid === pet.gid) + '" aria-label="' + esc(pet.name) + '，' + esc(pet.nature_name) + (slots ? '，第 ' + (Math.floor(index / 6) + 1) + (teams ? ' 队第 ' : ' 行第 ') + (index % 6 + 1) + (teams ? ' 格' : ' 列') : '') + '">'
        + '<span class="point-top"><span class="pc-gender ' + genderClass + '" title="' + (pet.gender === 2 ? "雌性" : (pet.gender === 1 ? "雄性" : "未知性别")) + '">' + mark + '</span>'
        + '<span class="point-markers"><span class="point-rarity-slot">' + window.SpriteLensPetPresentation.rarity(pet) + '</span><span class="point-color-slot">' + window.SpriteLensPetPresentation.colorCard(pet.color_card) + '</span></span>'
        + '<span class="point-nature" title="' + esc(pet.nature_name) + '">' + esc(pet.nature_name) + '</span></span>'
        + '<span class="point-portrait-row"><span class="point-groups" data-pet-display="groups">' + [0, 1].map(function (index) { var group = (pet.egg_groups || [])[index]; return '<span class="point-group-slot">' + (group && !/^(未知|未知组|未发现|未发现组|暂无数据)$/.test(group) ? '<span class="point-egg-group" title="' + esc(group) + '">' + esc(group.replace(/组$/, "")) + '</span>' : '') + '</span>'; }).join("") + '</span>'
        + window.SpriteLensPetPresentation.avatar(pet, "point-avatar")
        + '<span class="point-medals">' + window.SpriteLensPetPresentation.medal(pet, true) + '</span></span>'
        + '<span class="point-name" title="' + esc(pet.name) + '">' + esc(pet.name) + '</span>'
        + '<span class="point-metrics">' + pointMetric(pet, "height", "") + pointMetric(pet, "weight", "") + pointMetric(pet, "voice", "db") + '</span>'
        + "</button>";
    }).join("");
  }

  function pointMetric(pet, field, unit) {
    var text = pet[field + "_text"], unknown = !text || text === "暂无数据";
    var value = unknown ? "—" : text, label = "声音", title = unknown ? "暂无数据" : text + " dB";
    if (field !== "voice") {
      var position = (pet.range_positions || {})[field];
      label = (field === "height" ? "身高" : "体重") + " · 物种参考范围位置";
      value = !position || position.ratio === null ? "—" : position.status !== "within" ? "超界" : (position.ratio === 0 || position.ratio === 1 ? position.ratio * 100 : (position.ratio * 100).toFixed(1)) + "%";
      title = label + "：" + (value === "—" ? "暂无有效参考范围" : value === "超界" ? "超出参考范围" : value) + " · 实际值 " + (text || "暂无数据");
    }
    return '<span data-pet-display="' + field + '" title="' + esc(title) + '"><b>' + esc(value) + '</b>' + (!unit || value === "—" || value === "超界" ? '' : '<small class="metric-unit">' + unit + '</small>') + '</span>';
  }

  function positionText(pet, field) {
    var position = (pet.range_positions || {})[field];
    var text = !position || position.ratio === null ? "暂无范围" : position.status !== "within" ? "超出范围" : (position.ratio * 100).toFixed(1) + "%";
    return '<small data-pet-display="positions" title="物种参考范围位置">' + text + '</small>';
  }

  function businessMarks(pet) {
    return window.SpriteLensPetPresentation.rarity(pet) + window.SpriteLensPetPresentation.colorCard(pet.color_card)
      + window.SpriteLensPetPresentation.medal(pet);
  }

  function locationDetail(pet) {
    var location = pet.location;
    if (!location) { return '<div class="detail-section"><h3>游戏背包位置</h3><p class="filter-note">暂无箱位或队伍位置，登录游戏后自动同步。</p></div>'; }
    if (location.team_id) { return '<div class="detail-section"><h3>出战背包位置</h3><p class="info-line">第 ' + location.team_id + ' 队 · 第 ' + location.slot + ' 格</p><p class="filter-note">' + (location.historical ? '历史队伍，登录后更新。' : '本次采集的普通出战队伍。') + '</p><button class="ghost-button small" data-locate-team="' + location.team_id + '">定位到出战背包</button></div>'; }
    var text = '第 ' + location.box_id + ' 箱 · 第 ' + location.row + ' 行第 ' + location.column + ' 列';
    var slots = Array.from({ length: 30 }, function (_, index) { return '<span' + (index + 1 === location.slot ? ' class="active"' : '') + '></span>'; }).join('');
    var box = ((state.lastPayload || {}).backpack || {}).boxes || [];
    var historical = box.some(function (item) { return item.box_id === location.box_id && item.historical; });
    return '<div class="detail-section"><h3>游戏背包位置</h3><p class="info-line">' + text + '</p><div class="pet-location-grid" role="img" aria-label="' + text + '">' + slots + '</div><p class="filter-note">' + (historical ? '历史箱位，登录后更新。' : '最近采集的箱位，游戏内移动后自动更新。') + '</p><button class="ghost-button small" data-locate-box="' + location.box_id + '">定位到此箱</button></div>';
  }

  function petAvatarHtml(pet) {
    return window.SpriteLensPetPresentation.avatar(pet, "pc-avatar");
  }

  /* 卡片视图（对标蛋神「点阵背包」）：紧凑卡片承载可比较的关键信息 */
  function renderPetCards(pets) {
    $("pet-grid").className = "pet-grid";
    $("pet-grid").innerHTML = pets.map(function (pet) {
      var genderClass = pet.gender === 2 ? "female" : (pet.gender === 1 ? "male" : "");
      var genderMark = pet.gender === 2 ? "♀" : (pet.gender === 1 ? "♂" : "—");
      var typeBadges = (pet.type_names || []).map(function (name, index) {
        var color = (pet.type_colors || [])[index] || TYPE_FALLBACK;
        return '<span class="type-badge" style="' + badgeStyle(color) + '">' + esc(name) + "</span>";
      }).join("") || '<span class="type-badge" style="' + badgeStyle(TYPE_FALLBACK) + '">未知</span>';

      var stats = (pet.stats || []).map(function (stat) {
        return '<div class="pc-stat"><small>' + esc(stat.label) + '</small><b>' + stat.value + "</b>"
          + '<span class="mini-bar"><i style="width:' + (stat.ratio * 100).toFixed(1) + '%"></i>'
          + (stat.race_ratio ? '<u style="left:' + (stat.race_ratio * 100).toFixed(1) + '%"></u>' : "")
          + "</span></div>";
      }).join("");

      var foot = [];
      if (pet.is_shiny || pet.is_colorful || (pet.medal_marks || []).length) { foot.push(businessMarks(pet)); }
      if ((pet.egg_groups || []).length) { foot.push('<span class="pc-pct" data-pet-display="groups">' + esc(pet.egg_groups.join(" / ")) + "</span>"); }
      foot.push('<span class="pc-pct" data-pet-display="height">身高 ' + esc(pet.height_text) + positionText(pet, "height") + "</span>");
      foot.push('<span class="pc-pct" data-pet-display="weight">体重 ' + esc(pet.weight_text) + positionText(pet, "weight") + "</span>");
      foot.push('<span class="pc-pct" data-pet-display="voice">声音 ' + esc(pet.voice_text) + (pet.voice_text !== "暂无数据" ? " dB" : "") + "</span>");

      var dexTag = pet.dex_no ? "#" + pet.dex_no : "编号 " + pet.gid;
      return '<article class="pet-card ' + genderClass + (state.selectedPetGid === pet.gid ? " selected" : "")
        + '" data-gid="' + pet.gid + '" role="button" tabindex="0" aria-label="查看' + esc(pet.name) + '详情">'
        + '<div class="pc-top"><span class="pc-gender ' + genderClass + '">' + genderMark + "</span>"
        + '<span class="pc-nature">' + esc(pet.nature_name) + "</span>"
        + '<span class="pc-badges">' + typeBadges + "</span></div>"
        + '<div class="pc-body">' + petAvatarHtml(pet)
        + '<div class="pc-lines"><span class="pc-name" title="' + esc(pet.name) + '">'
        + esc(pet.name) + "</span>"
        + '<span class="pc-sub">' + esc(dexTag)
        + "</span></div></div>"
        + '<div class="pc-stats">' + stats + "</div>"
        + '<div class="pc-foot">' + (foot.join(" ") || '<span class="muted">—</span>')
        + '<span class="pc-talent" style="' + badgeStyle(pet.talent_color) + '">'
        + pet.talent_rank + "阶</span></div>"
        + "</article>";
    }).join("");

    $("pet-grid").querySelectorAll(".pet-card").forEach(function (card) {
      card.addEventListener("click", function () {
        state.selectedPetGid = Number(card.dataset.gid);
        $("pet-grid").querySelectorAll(".pet-card").forEach(function (node) {
          node.classList.toggle("selected", node === card);
        });
        renderPetDetail(state.selectedPetGid);
      });
    });
  }

  /* 分页条（对标蛋神「第 N/M 箱」）：数据多时按页切，避免一次铺满 DOM */
  function renderPetPager(totalCount) {
    var pager = $("pet-pager");
    if (state.petView === "table" || !totalCount) {
      pager.hidden = true;
      pager.innerHTML = "";
      return;
    }
    pager.hidden = false;
    var pages = Math.ceil(totalCount / PET_PAGE_SIZE);
    var current = state.petPage;
    var buttons = [];
    // 首页/上一页
    buttons.push('<button data-page="1"' + (current === 1 ? " disabled" : "") + ">首页</button>");
    buttons.push('<button data-page="' + (current - 1) + '"' + (current === 1 ? " disabled" : "") + ">上一页</button>");
    // 页码窗口：当前页附近 ±4
    var from = Math.max(1, current - 4);
    var to = Math.min(pages, from + 8);
    from = Math.max(1, to - 8);
    for (var i = from; i <= to; i++) {
      buttons.push('<button data-page="' + i + '"' + (i === current ? ' class="active" aria-current="page"' : "") + ">" + i + "</button>");
    }
    buttons.push('<button data-page="' + (current + 1) + '"' + (current === pages ? " disabled" : "") + ">下一页</button>");
    buttons.push('<span class="pager-info">浏览页 ' + current + " / " + pages + " · 每页 " + PET_PAGE_SIZE + " 只</span>");
    pager.innerHTML = buttons.join("");

    pager.querySelectorAll("button[data-page]").forEach(function (node) {
      node.addEventListener("click", function () {
        var page = Number(node.dataset.page);
        if (!page || page === state.petPage) { return; }
        state.petPage = page;
        window.SpriteLensUI.closeDetail(false);
        renderPets(state.lastPayload || { pets: state.pets, total: state.petTotal });
        var wrap = $("pet-grid").closest(".table-wrap");
        if (wrap) { wrap.scrollTop = 0; }
      });
    });
  }

  /* 表格视图（原密集表，保留给需要横向比对的场景） */
  function renderPetTable(pets) {
    $("pet-rows").innerHTML = pets.map(function (pet) {
      var species = pet.species_name && pet.species_name !== pet.name
        ? '<small>' + esc(pet.species_name) + "</small>" : "<small></small>";
      var types = (pet.type_names || []).map(function (name, index) {
        var color = (pet.type_colors || [])[index] || TYPE_FALLBACK;
        return '<span class="type-badge" style="' + badgeStyle(color) + '">' + esc(name) + "</span>";
      }).join("") || '<span class="muted">—</span>';

      var natureExtra = "";
      if (pet.nature_positive) { natureExtra += ' <span class="positive">↑' + esc(pet.nature_positive) + "</span>"; }
      if (pet.nature_negative) { natureExtra += ' <span class="negative">↓' + esc(pet.nature_negative) + "</span>"; }
      var nature = '<div class="nature-cell"><strong>' + esc(pet.nature_name) + "</strong>"
        + '<small>' + natureExtra + "</small></div>";

      var stats = (pet.stats || []).map(function (stat) {
        return '<div class="mini-stat"><b>' + stat.value + "</b><small>" + esc(stat.label) + "</small>"
          + '<span class="mini-bar"><i style="width:' + (stat.ratio * 100).toFixed(1) + '%"></i>'
          + (stat.race_ratio ? '<u style="left:' + (stat.race_ratio * 100).toFixed(1) + '%"></u>' : "")
          + "</span></div>";
      }).join("");

      function measurement(field, label, color) {
        var position = (pet.range_positions || {})[field];
        var valid = position && position.ratio !== null;
        var hint = valid ? (position.status === "within" ? "范围位置 " + Math.round(position.ratio * 100) + "%" : "超出参考范围") : "暂无参考范围";
        return '<div class="body-row" title="' + hint + '"><em>' + label + '</em>'
          + (valid ? '<span class="body-bar" aria-label="' + hint + '"><i class="' + color + '" style="width:' + (pet[field + "_pct"] * 100).toFixed(1) + '%"></i></span>' : '')
          + '<span>' + esc(pet[field + "_text"]) + '</span></div>';
      }
      var body = '<div class="body-cell">'
        + measurement("height", "身高", "h")
        + measurement("weight", "体重", "w")
        + '<div class="body-row"><em>声音</em><span class="body-bar"><i class="v" style="width:'
          + (pet.voice_pct * 100).toFixed(1) + '%"></i></span><span>' + esc(pet.voice_text) + (pet.voice_text !== "暂无数据" ? " dB" : "") + "</span></div>"
        + "</div>";

      var skills = (pet.skills || []).filter(function (item) { return item.equipped; });
      var skillHtml = skills.length
        ? '<div class="skill-list">' + skills.map(function (item) {
            return '<span class="skill-chip">' + esc(item.name) + "</span>";
          }).join("") + "</div>"
        : '<span class="muted">—</span>';

      return '<tr data-gid="' + pet.gid + '" role="button" tabindex="0" aria-label="查看' + esc(pet.name) + '详情">'
        + '<td><div class="pet-cell">' + petAvatarHtml(pet)
          + "<div><strong>" + esc(pet.name) + "</strong>" + species + "</div></div></td>"
        + '<td class="' + (pet.type_names && pet.type_names.length ? "" : "col-types") + '">' + types + "</td>"
        + "<td>" + nature + "</td>"
        + '<td><div class="mini-stats">' + stats + "</div></td>"
        + '<td><span class="talent-badge" style="' + badgeStyle(pet.talent_color) + '">'
          + pet.talent_rank + "阶</span></td>"
        + '<td class="col-body">' + body + "</td>"
        + "<td>" + skillHtml + "</td>"
        + '<td class="col-gid">' + pet.gid + "</td>"
        + "</tr>";
    }).join("");

    $("pet-rows").querySelectorAll("tr").forEach(function (row) {
      row.addEventListener("click", function () {
        state.selectedPetGid = Number(row.dataset.gid);
        $("pet-rows").querySelectorAll("tr").forEach(function (item) {
          item.classList.toggle("active", item === row);
        });
        renderPetDetail(state.selectedPetGid);
      });
    });
  }

  function findPet(gid) {
    for (var i = 0; i < state.pets.length; i++) {
      if (state.pets[i].gid === gid) { return state.pets[i]; }
    }
    return null;
  }

  /* 详情与筛选复用右侧栏，列表始终保持同一宽度。 */
  function setPetDetailOpen(open) {
    var workspace = document.querySelector("#page-pets .workspace.split");
    if (workspace) { workspace.classList.toggle("has-detail", !!open); }
  }

  document.addEventListener("detailclosed", function (event) {
    if (event.detail === "pet-detail") {
      state.selectedPetGid = null;
      document.querySelectorAll("#page-pets [data-gid]").forEach(function (node) {
        node.classList.remove("selected", "active");
        node.setAttribute("aria-pressed", "false");
      });
    }
    if (event.detail === "event-detail") { state.selectedEventIndex = null; }
  });

  function renderPetDetail(gid) {
    var pet = findPet(gid);
    var panel = $("pet-detail");
    if (!pet) {
      panel.innerHTML = '<div class="empty-hint">点击宠物卡片查看详情</div>';
      setPetDetailOpen(false);
      return;
    }
    setPetDetailOpen(true); // 选中是显式意图：展开详情栏（默认收起给卡片让宽）
    var peak = 0;
    (pet.stats || []).forEach(function (stat) { peak = Math.max(peak, stat.value); });
    var statRows = (pet.stats || []).map(function (stat) {
      var ratio = peak ? Math.min(1, stat.value / peak) : 0;
      var raceRatio = peak ? Math.min(1, stat.race / peak) : 0;
      return "<tr><td>" + esc(stat.label) + "</td>"
        + '<td class="num">' + stat.value + "</td>"
        + '<td class="race">' + (stat.race || "—") + "</td>"
        + '<td class="bar"><span class="detail-bar"><i style="width:' + (ratio * 100).toFixed(1) + '%"></i>'
        + '<u style="left:' + (raceRatio * 100).toFixed(1) + '%"></u></span></td></tr>';
    }).join("");

    var natureLine = esc(pet.nature_name);
    if (pet.nature_positive) { natureLine += ' <span class="positive">↑' + esc(STAT_CN[pet.nature_positive] || pet.nature_positive) + "</span>"; }
    if (pet.nature_negative) { natureLine += ' <span class="negative">↓' + esc(STAT_CN[pet.nature_negative] || pet.nature_negative) + "</span>"; }

    var types = (pet.type_names || []).map(function (name, index) {
      var color = (pet.type_colors || [])[index] || TYPE_FALLBACK;
      return '<span class="type-badge" style="' + badgeStyle(color) + '">' + esc(name) + "</span>";
    }).join(" ") || '<span class="muted">—</span>';

    var skills = pet.skills || [];
    var skillHtml = skills.length ? skills.map(function (item) {
      return '<span class="skill-chip">' + esc(item.name)
        + (item.equipped ? "" : "·未装备") + "</span>";
    }).join("") : '<span class="muted">无技能数据</span>';

    panel.innerHTML =
      '<div class="detail-hero">' + petAvatarHtml(pet) + '<div><div class="detail-title"><h2>' + esc(pet.name) + "</h2>"
      + '<span class="muted">Lv' + pet.level + "</span></div>"
      + '<div class="detail-sub">编号 ' + pet.gid + " · 图鉴 " + (pet.base_conf_id || "—")
      + "</div></div></div>"
      + '<div class="point-tags">' + businessMarks(pet) + '</div>'
      + (pet.worn_medal_id ? '<p class="info-line muted">佩戴奖牌：' + esc(pet.worn_medal_name) + '</p>' : '')
      + locationDetail(pet)

      + '<div class="detail-section"><h3>系别 / 性格</h3>'
      + '<div class="info-line">' + types + "</div>"
      + '<div class="info-line"><b>' + natureLine + "</b></div></div>"
      + '<div class="info-line muted">蛋组：' + esc((pet.egg_groups || []).join(" / ") || "暂无数据") + '</div>'

      + '<div class="detail-section"><h3>六维对照</h3>'
      + '<table class="stat-table"><tbody>' + statRows + "</tbody></table>"
      + '<div class="info-line muted">数值 / 种族值（竖线为种族值参考）· 总和 '
      + (pet.stat_sum || 0) + (pet.species_stat_sum ? " / 种族 " + pet.species_stat_sum : "")
      + "</div></div>"

      + '<div class="detail-section"><h3>个体实际值 · 体型 / 声音</h3>'
      + '<div class="meta-grid">'
      + '<div class="meta-cell"><span>身高</span><b>' + esc(pet.height_text) + "</b></div>"
      + '<div class="meta-cell"><span>体重</span><b>' + esc(pet.weight_text) + "</b></div>"
      + '<div class="meta-cell"><span>声音</span><b>' + esc(pet.voice_text) + (pet.voice_text !== "暂无数据" ? " dB" : "") + "</b></div>"
      + '<div class="meta-cell"><span>天赋阶</span><b>' + pet.talent_rank + " 阶</b></div>"
      + "</div></div>"

      + window.SpriteLensAppearance.ranges("物种参考范围", pet.reference_ranges, pet.range_positions)
      + window.SpriteLensAppearance.ranges("蛋基础范围", pet.egg_ranges)
      + '<div class="detail-section"><h3>技能</h3><div class="skill-list">' + skillHtml + "</div></div>";
  }

  /* ---------- 筛选交互 ---------- */
  function bindPetFilters() {
    var timer = null;
    // 视图切换：点阵背包（默认）/ 属性卡片 / 对比表格。
    $("pet-view").querySelectorAll("button").forEach(function (node) {
      node.addEventListener("click", function () {
        window.SpriteLensUI.closeDetail(false);
        state.petView = node.dataset.view;
        window.SpriteLensAppearance.view(state.petView);
        state.petPage = 1;
        $("pet-view").querySelectorAll("button").forEach(function (item) {
          item.classList.toggle("active", item === node);
          item.setAttribute("aria-pressed", String(item === node));
        });
        renderPets(state.lastPayload || { pets: state.pets, total: state.petTotal, shown: state.pets.length });
      });
    });
    $("f-search").addEventListener("input", function (event) {
      state.filters.search = event.target.value.trim();
      clearTimeout(timer);
      timer = setTimeout(loadPets, 220);
    });
    $("f-level-min").addEventListener("input", function () {
      var min = Number($("f-level-min").value);
      var max = Number($("f-level-max").value);
      if (min > max) { $("f-level-max").value = String(min); max = min; }
      state.filters.level_min = min;
      state.filters.level_max = max;
      $("f-level-label").textContent = min + " – " + max;
      clearTimeout(timer);
      timer = setTimeout(loadPets, 180);
    });
    $("f-level-max").addEventListener("input", function () {
      var min = Number($("f-level-min").value);
      var max = Number($("f-level-max").value);
      if (max < min) { $("f-level-min").value = String(max); min = max; }
      state.filters.level_min = min;
      state.filters.level_max = max;
      $("f-level-label").textContent = min + " – " + max;
      clearTimeout(timer);
      timer = setTimeout(loadPets, 180);
    });
    $("f-talent").addEventListener("change", function () {
      state.filters.talent_min = Number($("f-talent").value) || 0;
      loadPets();
    });
    $("f-gender").addEventListener("change", function () {
      state.filters.gender = Number(this.value) || 0;
      loadPets();
    });
    $("f-sort").addEventListener("change", function () {
      state.filters.sort = $("f-sort").value;
      loadPets();
    });
    $("f-desc").addEventListener("change", function () {
      state.filters.desc = $("f-desc").checked;
      loadPets();
    });
    $("btn-reset-filters").addEventListener("click", function () {
      clearTimeout(timer);
      state.filters = { search: "", level_min: 1, level_max: 100, natures: [], types: [], talent_min: 0, gender: 0, sort: "gid", desc: false };
      $("f-search").value = "";
      $("f-level-min").value = "1";
      $("f-level-max").value = "100";
      $("f-level-label").textContent = "1 – 100";
      $("f-talent").value = "0";
      $("f-gender").value = "0";
      $("f-sort").value = "gid";
      $("f-desc").checked = false;
      $("f-natures").querySelectorAll(".chip").forEach(function (node) { node.classList.remove("active"); });
      $("f-types").querySelectorAll(".chip").forEach(function (node) { node.classList.remove("active"); });
      loadPets();
    });
    $("btn-empty-reset").addEventListener("click", function () { $("btn-reset-filters").click(); });

  }

  /* ---------- 精灵图鉴 ---------- */
  var HB_PAGE_SIZE = 120; // 一次渲染上限：1015 个富卡片全量入 DOM 会明显卡顿

  function loadHandbook(resetLimit) {
    if (resetLimit !== false) { state.hbLimit = HB_PAGE_SIZE; }
    var params = {
      search: state.hb.search,
      type: state.hb.type,
      collected: state.hb.mode === "collected" ? "1" : "",
      uncollected: state.hb.mode === "uncollected" ? "1" : ""
    };
    return api("/api/handbook" + query(params)).then(function (payload) {
      state.hbData = payload;
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
      toggle.textContent = running ? "停止采集" : "开始采集";
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

  /* ---------- 蛋图鉴 ---------- */
  var eggDexState = { search: "", group: "", egg_type: "", hatch_min_hours: "", built: false, data: null, selected: null };

  /* 蛋卡头像：蛋图标 → 立绘 → 首字，两级 onerror 降级 */
  function eggAvatarHtml(egg) {
    var letter = esc((egg.name || "?").slice(0, 1));
    var fallback = egg.icon_url
      ? "this.onerror=function(){this.remove()};this.src='" + esc(egg.icon_url) + "'"
      : "this.remove()";
    var img = egg.egg_icon_url
      ? '<img src="' + esc(egg.egg_icon_url) + '" alt="" loading="lazy" onerror="' + fallback + '">'
      : (egg.icon_url
        ? '<img src="' + esc(egg.icon_url) + '" alt="" loading="lazy" onerror="this.remove()">'
        : "");
    return '<span class="hb-art">' + letter + img + "</span>";
  }

  function hatchSecondsLabel(seconds) {
    if (!seconds) { return "—"; }
    if (seconds < 3600) { return Math.round(seconds / 60) + " 分钟"; }
    var hours = seconds / 3600;
    return (hours % 1 === 0 ? hours : hours.toFixed(1)) + " 小时";
  }

  function loadEggDex() {
    api("/api/eggs" + query({
      search: eggDexState.search,
      group: eggDexState.group,
      egg_type: eggDexState.egg_type,
      hatch_min_hours: eggDexState.hatch_min_hours
    })).then(function (payload) {
      eggDexState.data = payload;
      renderEggDex(payload);
    }).catch(function (err) { toast("蛋图鉴加载失败：" + err.message, true); });
  }

  function renderEggDex(payload) {
    if (!eggDexState.built) {
      eggDexState.built = true;
      $("ed-group").innerHTML = '<option value="">全部蛋组</option>'
        + (payload.groups || []).map(function (name) {
            return '<option value="' + esc(name) + '">' + esc(name) + "</option>";
          }).join("");
      $("ed-type").innerHTML = '<option value="">全部类型</option>'
        + (payload.egg_types || []).map(function (name) {
            return '<option value="' + esc(name) + '">' + esc(name) + "</option>";
          }).join("");
    }
    $("ed-count").textContent = "收录 " + (payload.shown || 0) + " / " + (payload.total || 0) + " 种蛋";
    $("ed-grid").innerHTML = (payload.eggs || []).map(function (egg) {
      var groups = (egg.egg_group_names || []).map(function (g) {
        return '<span class="skill-chip">' + esc(g) + "</span>";
      }).join(" ");
      return '<article class="hb-card' + (eggDexState.selected === egg.egg_conf_id ? " active" : "")
        + '" data-egg="' + egg.egg_conf_id + '" role="button" tabindex="0" aria-label="查看' + esc(egg.egg_name) + '详情">'
        + '<div class="hb-head"><span class="hb-key">' + esc(egg.handbook_no || "—") + "</span>"
        + eggAvatarHtml(egg)
        + "<div><strong>" + esc(egg.egg_name) + "</strong>"
        + "<small>" + esc(egg.name) + "</small></div></div>"
        + '<div class="hb-meta">' + (groups || '<span class="muted">—</span>') + "</div>"
        + '<span class="hb-badge"><svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><use href="/static/icons/sprite.svg#clock"></use></svg> ' + esc(egg.hatch_label || "—") + "</span>"
        + "</article>";
    }).join("");
    $("ed-empty").hidden = (payload.eggs || []).length > 0;
    if (eggDexState.selected !== null) { renderEggDetail(eggDexState.selected); }
  }

  function renderEggDetail(eggConfId) {
    var eggs = (eggDexState.data || {}).eggs || [];
    var egg = null;
    for (var i = 0; i < eggs.length; i++) {
      if (eggs[i].egg_conf_id === eggConfId) { egg = eggs[i]; break; }
    }
    var panel = $("ed-detail");
    document.querySelectorAll("#ed-grid [data-egg]").forEach(function (node) {
      node.classList.toggle("active", Number(node.dataset.egg) === Number(eggConfId));
    });
    if (!egg) { panel.innerHTML = '<div class="empty-hint">蛋数据不存在</div>'; return; }

    var seconds = egg.hatch_seconds || 0;
    var speedRows = [["原始", seconds], ["5 倍速", seconds / 5], ["6 倍速", seconds / 6], ["30 倍速", seconds / 30]]
      .map(function (row) {
        return '<div class="speed-row"><span>' + row[0] + '</span><b>' + hatchSecondsLabel(row[1]) + "</b></div>";
      }).join("");
    var male = egg.gender_male || 0, female = egg.gender_female || 0;
    var ring = (male || female)
      ? '<div class="gender-ring" style="background:conic-gradient(var(--male-strong) 0 ' + male + "%, var(--female-strong) " + male + '% 100%)"><b>'
        + (male ? "♂ " + male + "%" : "♀ " + female + "%") + "</b></div>"
      : '<div class="gender-ring unknown"><b>暂无数据</b></div>';
    var chain = (egg.chain || []).map(function (baseId) {
      var member = null;
      for (var j = 0; j < eggs.length; j++) {
        if (eggs[j].base_id === baseId) { member = eggs[j]; break; }
      }
      return '<span class="skill-chip">' + esc((egg.chain_names || {})[baseId] || (member ? member.name : "#" + baseId)) + "</span>";
    }).join('<span class="chain-arrow">→</span>');
    var height = egg.height || [0, 0], weight = egg.weight || [0, 0];

    panel.innerHTML =
      '<div class="detail-title"><h2>' + esc(egg.egg_name) + "</h2>"
      + '<span class="muted">#' + esc(egg.egg_conf_id) + "</span></div>"
      + '<div class="detail-sub">' + esc(egg.name)
      + (egg.handbook_no ? " · 图鉴号 " + esc(egg.handbook_no) : "")
      + " · " + esc(egg.egg_type_name || "普通") + "</div>"
      + '<div class="detail-section"><h3>孵化时长</h3>' + speedRows + "</div>"
      + '<div class="detail-section"><h3>公母比例</h3>' + ring + "</div>"
      + window.SpriteLensAppearance.ranges("蛋基础范围", egg.reference_ranges)
      + '<div class="detail-section"><h3>进化链</h3><div class="skill-list">'
      + (chain || '<span class="muted">—</span>') + "</div></div>";
  }

  function bindEggDexFilters() {
    var debounced = null;
    $("ed-search").addEventListener("input", function (event) {
      eggDexState.search = event.target.value.trim();
      clearTimeout(debounced);
      debounced = setTimeout(loadEggDex, 220);
    });
    $("ed-group").addEventListener("change", function (event) {
      eggDexState.group = event.target.value; loadEggDex();
    });
    $("ed-type").addEventListener("change", function (event) {
      eggDexState.egg_type = event.target.value; loadEggDex();
    });
    $("ed-hatch").addEventListener("change", function (event) {
      eggDexState.hatch_min_hours = event.target.value; loadEggDex();
    });
    $("ed-grid").addEventListener("click", function (event) {
      var card = event.target.closest("[data-egg]");
      if (!card) { return; }
      eggDexState.selected = Number(card.dataset.egg);
      renderEggDetail(eggDexState.selected);
    });
  }

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

  /* ---------- 蛋蛋仓库 ---------- */
  var eggBoxState = { search: "", mode: "all", data: null, selected: null, version: -1 };

  function loadEggBox() {
    api("/api/egg-box").then(function (payload) {
      eggBoxState.data = payload;
      eggBoxState.version = payload.version || 0;
      renderEggBox();
    }).catch(function (err) { toast("蛋仓加载失败：" + err.message, true); });
  }

  function eggBoxFilter(eggs) {
    var keyword = eggBoxState.search.trim().toLowerCase();
    return (eggs || []).filter(function (egg) {
      if (eggBoxState.mode === "hatching" && !egg.hatching) { return false; }
      if (!keyword) { return true; }
      return (egg.egg_name || "").toLowerCase().indexOf(keyword) >= 0
        || (egg.species_name || "").toLowerCase().indexOf(keyword) >= 0
        || String(egg.instance_id).indexOf(keyword) >= 0;
    });
  }

  function renderEggBox() {
    var payload = eggBoxState.data;
    if (!payload) { return; }
    var shown = eggBoxFilter(payload.eggs);
    $("eb-count").textContent = "共 " + payload.total + " 枚";
    $("eb-hatching").textContent = "在孵 " + (payload.hatching || 0);
    $("eb-grid").innerHTML = shown.map(function (egg) {
      var progress = Math.round((egg.hatch_progress || 0) * 100);
      var bar = egg.hatching
        ? '<div class="egg-progress"><i style="width:' + progress + '%"></i><b>' + progress + "%</b></div>"
        : '<span class="hb-badge none">未孵化</span>';
      var qty = egg.quantity > 1 ? '<span class="egg-qty">×' + egg.quantity + "</span>" : "";
      var img = egg.icon_url
        ? '<img src="' + esc(egg.icon_url) + '" alt="" loading="lazy" '
          + 'onerror="this.onerror=function(){this.remove()};this.src=\'' + esc(egg.fallback_icon_url || "") + '\'">'
        : "";
      return '<article class="hb-card' + (eggBoxState.selected === egg.instance_id ? " active" : "")
        + '" data-eb="' + egg.instance_id + '" role="button" tabindex="0" aria-label="查看' + esc(egg.egg_name) + '详情">'
        + '<div class="hb-head"><span class="hb-key">#' + esc(egg.instance_id) + "</span>"
        + '<span class="hb-art">' + esc((egg.egg_name || "?").slice(0, 1)) + img + "</span>"
        + "<div><strong>" + esc(egg.egg_name) + "</strong>"
        + "<small>" + esc(egg.species_name || "—") + "</small></div>" + qty + "</div>"
        + '<div class="hb-meta"><span class="muted">' + esc(egg.egg_type_name || "") + "</span>"
        + '<span class="muted">' + esc(egg.hatch_label || "") + "</span></div>"
        + bar
        + "</article>";
    }).join("");
    $("eb-empty").hidden = shown.length > 0;
    if (eggBoxState.selected !== null) { renderEggBoxDetail(eggBoxState.selected); }
  }

  function renderEggBoxDetail(instanceId) {
    var payload = eggBoxState.data;
    var eggs = (payload || {}).eggs || [];
    var egg = null;
    for (var i = 0; i < eggs.length; i++) {
      if (eggs[i].instance_id === instanceId) { egg = eggs[i]; break; }
    }
    var panel = $("eb-detail");
    document.querySelectorAll("#eb-grid [data-eb]").forEach(function (node) {
      node.classList.toggle("active", Number(node.dataset.eb) === Number(instanceId));
    });
    if (!egg) { panel.innerHTML = '<div class="empty-hint">蛋不存在或已被清空</div>'; return; }
    var progress = Math.round((egg.hatch_progress || 0) * 100);
    var hatchedMinutes = egg.hatching && egg.hatch_progress
      ? "（孵化数据以游戏内为准）" : "";
    panel.innerHTML =
      '<div class="detail-title"><h2>' + esc(egg.egg_name) + "</h2>"
      + '<span class="muted">#' + esc(egg.instance_id) + "</span></div>"
      + '<div class="detail-sub">' + esc(egg.species_name || "未知物种")
      + (egg.egg_type_name ? " · " + esc(egg.egg_type_name) : "")
      + (egg.quantity > 1 ? " · 数量 ×" + egg.quantity : "") + "</div>"
      + '<div class="detail-section"><h3>孵化状态</h3>'
      + (egg.hatching
        ? '<div class="egg-progress large"><i style="width:' + progress + '%"></i><b>' + progress + "%</b></div>"
          + '<div class="info-line muted">孵化时长参考 ' + esc(egg.hatch_label || "—") + hatchedMinutes + "</div>"
        : '<div class="info-line">未开始孵化 · 参考时长 ' + esc(egg.hatch_label || "—") + "</div>")
      + "</div>"
      + '<div class="detail-section"><h3>个体实际值</h3><dl class="detail-rows">'
      + '<div><dt>获得时间</dt><dd>' + (egg.obtained_at ? new Date(egg.obtained_at * 1000).toLocaleString() : "未知") + "</dd></div>"
      + '<div><dt>身高</dt><dd>' + (egg.height_cm ? (egg.height_cm / 100).toFixed(2) + " m" : "暂无数据") + "</dd></div>"
      + '<div><dt>体重</dt><dd>' + (egg.weight_g ? (egg.weight_g / 1000).toFixed(2) + " kg" : "暂无数据") + "</dd></div>"
      + "</dl></div>"
      + window.SpriteLensAppearance.ranges("蛋基础范围", egg.reference_ranges);
  }

  function bindEggBoxActions() {
    var debounced = null;
    $("eb-search").addEventListener("input", function (event) {
      eggBoxState.search = event.target.value;
      clearTimeout(debounced);
      debounced = setTimeout(renderEggBox, 200);
    });
    $("eb-mode").addEventListener("click", function (event) {
      var btn = event.target.closest("[data-mode]");
      if (!btn) { return; }
      eggBoxState.mode = btn.dataset.mode;
      document.querySelectorAll("#eb-mode [data-mode]").forEach(function (node) {
        node.classList.toggle("active", node === btn);
      });
      renderEggBox();
    });
    $("eb-grid").addEventListener("click", function (event) {
      var card = event.target.closest("[data-eb]");
      if (!card) { return; }
      eggBoxState.selected = Number(card.dataset.eb);
      renderEggBoxDetail(eggBoxState.selected);
    });

  }

  /* ---------- 种公阵列（性格 × 蛋组覆盖矩阵） ---------- */
  var mmState = { gender: "all", data: null, selected: null };

  function loadMaleMatrix() {
    api("/api/male-matrix" + query({ gender: mmState.gender })).then(function (payload) {
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
        + '<span class="' + (pet.gender === 2 ? "female" : "male") + '-mark">' + (pet.gender === 2 ? "♀" : "♂") + "</span></div>";
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
      state.filters.search = String(chip.dataset.mm);
      var searchBox = $("f-search");
      if (searchBox) { searchBox.value = String(chip.dataset.mm); }
      loadPets();
    });
    document.getElementById("page-breeder-library").addEventListener("click", function (event) {
      var chip = event.target.closest("[data-mm]");
      if (!chip) { return; }
      switchPage("pets");
      state.filters.search = String(chip.dataset.mm);
      var searchBox = $("f-search");
      if (searchBox) { searchBox.value = String(chip.dataset.mm); }
      loadPets();
    });
    $("mm-matrix").addEventListener("click", function (event) {
      var chip = event.target.closest("[data-mm]");
      if (chip) {
        // 跳到精灵背包并按 gid 搜索（详情可查）
        switchPage("pets");
        state.filters.search = String(chip.dataset.mm);
        var searchBox = $("f-search");
        if (searchBox) { searchBox.value = String(chip.dataset.mm); }
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
    api("/api/home").then(function (payload) {
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
      $("home-residents").innerHTML = "";
      $("home-residents-empty").hidden = false;
      $("home-nests").innerHTML = "";
      $("home-nests-empty").hidden = false;
      $("home-furniture-line").textContent = "—";
      return;
    }
    $("home-meta").textContent = "房间等级 " + payload.room_level + " · 快照 #" + payload.version;
    var residents = payload.residents || [];
    $("home-resident-count").textContent = residents.length + " 只";
    $("home-residents").innerHTML = residents.map(function (r) {
      var gender = r.gender === 2 ? '<span class="female-mark">♀</span>'
        : (r.gender === 1 ? '<span class="male-mark">♂</span>' : "");
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
      api("/api/male-matrix" + query({ gender: "male" })),
      api("/api/male-matrix" + query({ gender: "female" }))
    ]).then(function (results) {
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
    api("/api/flowers").then(function (payload) {
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
      $("fl-own").innerHTML = "";
      $("fl-friends").innerHTML = "";
      $("fl-own-empty").hidden = false;
      $("fl-friends-empty").hidden = false;
      return;
    }
    $("fl-meta").textContent = "快照 #" + payload.version + " · 我的花 " + (payload.own || []).length + " 朵";
    $("fl-own").innerHTML = (payload.own || []).map(flowerCard).join("");
    $("fl-own-empty").hidden = (payload.own || []).length > 0;
    $("fl-friends").innerHTML = (payload.friends || []).map(flowerCard).join("");
    $("fl-friend-count").textContent = (payload.friends || []).length + " 条";
    $("fl-friends-empty").hidden = (payload.friends || []).length > 0;
  }

  /* ---------- 炫彩色卡 ---------- */
  function loadColors() {
    api("/api/colors").then(renderColors).catch(function (err) {
      toast("色卡加载失败：" + err.message, true);
    });
  }

  function petChip(pet, withLevel) {
    var mark = pet.gender === 2 ? "♀" : "♂";
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
  document.addEventListener("preferenceschanged", function (event) {
    var mode = event.detail.pet_image || "portrait";
    if (mode === lastImageMode) { return; }
    lastImageMode = mode;
    if (!state.lastPayload) { return; }
    var scroll = $("pet-grid").parentElement, top = scroll.scrollTop, left = scroll.scrollLeft;
    renderPets(state.lastPayload);
    if (state.selectedPetGid) { renderPetDetail(state.selectedPetGid); }
    scroll.scrollTop = top; scroll.scrollLeft = left;
  });

  /* ---------- 启动（15s 超时 + 自动重试 2 次，与自恢复链协同） ---------- */
  var BOOT_RETRIES = 2;

  function bootAttempt(remaining) {
    var controller = ("AbortController" in window) ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, 15000) : null;
    api("/api/bootstrap", { signal: controller ? controller.signal : undefined }).then(function (payload) {
      if (timer) { clearTimeout(timer); }
      window.SpriteLensAppearance.initialize(payload.ui_preferences, function (changes) {
        return api("/api/ui/preferences", { method: "POST", body: changes });
      }, toast);
      window.SpriteLensPetFilters.initialize(loadPets);
      window.SpriteLensBackpackControls.initialize(function (value) {
        state.filters.search = value.search || ""; state.filters.level_min = value.level_min || 1; state.filters.level_max = value.level_max || 100;
        state.filters.natures = (value.natures || []).slice(); state.filters.types = (value.types || []).slice();
        state.filters.talent_min = value.talent_min || 0; state.filters.gender = value.gender || 0;
        $("f-search").value = state.filters.search; $("f-level-min").value = state.filters.level_min; $("f-level-max").value = state.filters.level_max;
        $("f-level-label").textContent = state.filters.level_min + " – " + state.filters.level_max;
        $("f-talent").value = state.filters.talent_min; $("f-gender").value = state.filters.gender;
        $("f-natures").querySelectorAll(".chip").forEach(function (node) { var active = state.filters.natures.indexOf(Number(node.dataset.nature)) >= 0; node.classList.toggle("active", active); node.setAttribute("aria-pressed", String(active)); });
        $("f-types").querySelectorAll(".chip").forEach(function (node) { var active = state.filters.types.indexOf(node.dataset.type) >= 0; node.classList.toggle("active", active); node.setAttribute("aria-pressed", String(active)); });
        window.SpriteLensPetFilters.restore(value); loadPets();
      }, toast);
      state.petView = payload.ui_preferences.pet_view;
      $("pet-view").querySelectorAll("button").forEach(function (node) {
        node.classList.toggle("active", node.dataset.view === state.petView);
        node.setAttribute("aria-pressed", String(node.dataset.view === state.petView));
      });
      $("startup").hidden = true;
      $("app").hidden = false;
      if (payload.app && payload.app.version) {
        var versionNode = $("app-version");
        if (versionNode) { versionNode.textContent = "v" + payload.app.version + " · 纯本地运行"; }
      }
      renderOverview(payload.overview || {});
      state.petOptions = (payload.pets || {}).options || null;
      state.pets = (payload.pets || {}).pets || [];
      state.petTotal = (payload.pets || {}).total || 0;
      state.lastPayload = payload.pets || {};
      renderPetFilters(state.petOptions || {});
      renderPets(payload.pets || {});
      renderCapture(payload.capture || {});
      renderState(payload.state || {});
      renderFeaturePlaceholders();
      bindPetFilters();
      bindPointGrid();
      bindHandbookFilters();
      bindEggDexFilters();
      bindEggBoxActions();
      bindMaleMatrixActions();
      bindCaptureActions();
      loadIfaces();
      connectPush();
      if (window.__spritelensBoot) { window.__spritelensBoot.ready(); }
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
