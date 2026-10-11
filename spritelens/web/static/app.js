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
    filters: { search: "", level_min: 1, level_max: 100, natures: [], types: [], talent_min: 0, first_catch: false, sort: "gid", desc: false },
    petView: "card",
    petPage: 1,
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
    state.page = name;
    document.querySelectorAll(".page").forEach(function (node) {
      node.classList.toggle("active", node.id === "page-" + name);
    });
    document.querySelectorAll(".nav-item").forEach(function (node) {
      node.classList.toggle("active", node.dataset.page === name);
    });
    if (name === "pets") { loadPets(); }
    if (name === "handbook") { loadHandbook(); }
    if (name === "egg-dex") { loadEggDex(); }
    if (name === "egg-box") { loadEggBox(); }
    if (name === "male-matrix") { loadMaleMatrix(); }
    if (name === "home") { loadHome(); }
    if (name === "breeder-library") { loadBreederLibrary(); }
    if (name === "flowers") { loadFlowers(); }
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
    $("ov-first").textContent = stats.first_catch || 0;
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

    renderRole(data.identity);
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
  function renderRole(identity) {
    if (identity) {
      $("role-name").textContent = identity.name || "未知角色";
      $("role-uid").textContent = "UID " + identity.uid + (identity.level ? " · Lv" + identity.level : "");
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

    var message = "准备就绪";
    if (capture.last_error) { message = capture.last_error; }
    else if (capture.running) {
      message = "原始流 " + (capture.raw_chunks || 0) + " 段 · 解密成功 " + (capture.decrypt_ok || 0);
    }
    $("capture-message").textContent = message;

    $("btn-start").disabled = !!capture.running;
    $("btn-stop").disabled = !capture.running;
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

    renderRole(payload.identity);
    var stats = payload.stats || {};
    $("ov-total").textContent = stats.total || 0;
    $("ov-first").textContent = stats.first_catch || 0;
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
      if (state.page === "pets") { loadPets(); }
    }
  }

  /* ---------- 宠物仓库 ---------- */
  function loadPets() {
    state.petPage = 1; // 条件/排序变化后回到第一页
    var f = state.filters;
    var params = {
      search: f.search,
      level_min: f.level_min,
      level_max: f.level_max,
      natures: f.natures.join(","),
      types: f.types.join(","),
      talent_min: f.talent_min || "",
      first_catch: f.first_catch ? "1" : "",
      sort: f.sort,
      desc: f.desc ? "1" : ""
    };
    return api("/api/pets" + query(params)).then(function (payload) {
      state.pets = payload.pets || [];
      state.petTotal = payload.total || 0;
      state.lastPayload = payload;
      renderPetFilters(payload.options || {});
      renderPets(payload);
      if (state.selectedPetGid) { renderPetDetail(state.selectedPetGid); }
    }).catch(function (err) { toast("宠物数据加载失败：" + err.message, true); });
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

  var PET_PAGE_SIZE = 60; // 卡片一页数量（对标蛋神「第 N/M 箱」）

  function renderPets(payload) {
    var pets = payload.pets || [];
    var shown = pets;
    if (state.petView === "card") {
      var pages = Math.max(1, Math.ceil(pets.length / PET_PAGE_SIZE));
      if (state.petPage > pages) { state.petPage = pages; }
      var start = (state.petPage - 1) * PET_PAGE_SIZE;
      shown = pets.slice(start, start + PET_PAGE_SIZE);
    }
    $("pet-count").textContent = "共 " + payload.total + " 只"
      + (payload.shown !== payload.total ? "（显示 " + payload.shown + " 只）" : "");
    $("pet-empty").hidden = pets.length > 0;

    if (state.petView === "card") {
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
  }

  /* 精灵图：有图显示立绘（覆盖在首字之上）；加载失败自动移除，露出首字头像 */
  function petAvatarHtml(pet) {
    var letter = esc((pet.name || "?").slice(0, 1));
    var bg = levelColor(pet.level);
    var img = pet.icon_url
      ? '<img src="' + esc(pet.icon_url) + '" alt="" loading="lazy" onerror="this.remove()">'
      : "";
    return '<span class="pc-avatar" style="background:' + bg + '">' + letter + img + "</span>";
  }

  /* 卡片视图（对标蛋神「点阵背包」）：紧凑卡片承载可比较的关键信息 */
  function renderPetCards(pets) {
    $("pet-grid").innerHTML = pets.map(function (pet) {
      var genderClass = pet.gender === 2 ? "female" : "male";
      var genderMark = pet.gender === 2 ? "♀" : "♂";
      var typeBadges = (pet.type_names || []).map(function (name, index) {
        var color = (pet.type_colors || [])[index] || TYPE_FALLBACK;
        return '<span class="type-badge" style="background:' + color + '">' + esc(name) + "</span>";
      }).join("") || '<span class="type-badge" style="background:' + TYPE_FALLBACK + '">未知</span>';

      var stats = (pet.stats || []).map(function (stat) {
        return '<div class="pc-stat"><b>' + stat.value + "</b>"
          + '<span class="mini-bar"><i style="width:' + (stat.ratio * 100).toFixed(1) + '%"></i>'
          + (stat.race_ratio ? '<u style="left:' + (stat.race_ratio * 100).toFixed(1) + '%"></u>' : "")
          + "</span></div>";
      }).join("");

      var foot = [];
      if (pet.height_text && pet.height_text !== "—") { foot.push('<span class="pc-pct">' + esc(pet.height_text) + "</span>"); }
      if (pet.weight_text && pet.weight_text !== "—") { foot.push('<span class="pc-pct">' + esc(pet.weight_text) + "</span>"); }
      if (pet.voice_text && pet.voice_text !== "—") { foot.push('<span class="pc-pct">' + esc(pet.voice_text) + "dB</span>"); }

      var dexTag = pet.dex_no ? "#" + pet.dex_no : "编号 " + pet.gid;
      return '<article class="pet-card ' + genderClass + (state.selectedPetGid === pet.gid ? " selected" : "")
        + '" data-gid="' + pet.gid + '">'
        + '<div class="pc-top"><span class="pc-gender ' + genderClass + '">' + genderMark + "</span>"
        + '<span class="pc-nature">' + esc(pet.nature_name) + "</span>"
        + '<span class="pc-badges">' + typeBadges + "</span></div>"
        + '<div class="pc-body">' + petAvatarHtml(pet)
        + '<div class="pc-lines"><span class="pc-name" title="' + esc(pet.name) + '">'
        + esc(pet.name) + "</span>"
        + '<span class="pc-sub">Lv' + pet.level + " · " + esc(dexTag)
        + (pet.is_first_catch ? ' · <span class="pc-first">首捕</span>' : "") + "</span></div></div>"
        + '<div class="pc-stats">' + stats + "</div>"
        + '<div class="pc-foot">' + (foot.join(" ") || '<span class="muted">—</span>')
        + '<span class="pc-talent" style="background:' + esc(pet.talent_color) + '">'
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
    if (state.petView !== "card" || totalCount <= PET_PAGE_SIZE) {
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
      buttons.push('<button data-page="' + i + '"' + (i === current ? ' class="active"' : "") + ">" + i + "</button>");
    }
    buttons.push('<button data-page="' + (current + 1) + '"' + (current === pages ? " disabled" : "") + ">下一页</button>");
    buttons.push('<span class="pager-info">第 ' + current + " / " + pages + " 页</span>");
    pager.innerHTML = buttons.join("");

    pager.querySelectorAll("button[data-page]").forEach(function (node) {
      node.addEventListener("click", function () {
        var page = Number(node.dataset.page);
        if (!page || page === state.petPage) { return; }
        state.petPage = page;
        renderPets(state.lastPayload || { pets: state.pets });
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
        return '<span class="type-badge" style="background:' + color + '">' + esc(name) + "</span>";
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

      var body = '<div class="body-cell">'
        + '<div class="body-row"><em>身高</em><span class="body-bar"><i class="h" style="width:'
          + (pet.height_pct * 100).toFixed(1) + '%"></i></span><span>' + esc(pet.height_text) + "</span></div>"
        + '<div class="body-row"><em>体重</em><span class="body-bar"><i class="w" style="width:'
          + (pet.weight_pct * 100).toFixed(1) + '%"></i></span><span>' + esc(pet.weight_text) + "</span></div>"
        + '<div class="body-row"><em>声音</em><span class="body-bar"><i class="v" style="width:'
          + (pet.voice_pct * 100).toFixed(1) + '%"></i></span><span>' + esc(pet.voice_text) + "</span></div>"
        + "</div>";

      var skills = (pet.skills || []).filter(function (item) { return item.equipped; });
      var skillHtml = skills.length
        ? '<div class="skill-list">' + skills.map(function (item) {
            return '<span class="skill-chip">' + esc(item.name) + "</span>";
          }).join("") + "</div>"
        : '<span class="muted">—</span>';

      return '<tr data-gid="' + pet.gid + '">'
        + '<td><div class="pet-cell">' + petAvatarHtml(pet)
          + "<div><strong>" + esc(pet.name) + "</strong>" + species + "</div></div></td>"
        + '<td class="' + (pet.type_names && pet.type_names.length ? "" : "col-types") + '">' + types + "</td>"
        + "<td>" + nature + "</td>"
        + '<td><div class="mini-stats">' + stats + "</div></td>"
        + '<td><span class="talent-badge" style="background:' + esc(pet.talent_color) + '">'
          + pet.talent_rank + "阶</span></td>"
        + '<td class="col-body">' + body + "</td>"
        + "<td>" + skillHtml + "</td>"
        + '<td class="col-first">' + (pet.is_first_catch ? '<span class="first-flag">✓</span>' : "") + "</td>"
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

  /* 详情栏开合：宠物页默认两栏（筛选 + 网格），选中后变三栏 */
  function setPetDetailOpen(open) {
    var workspace = document.querySelector("#page-pets .workspace.split");
    if (workspace) { workspace.classList.toggle("has-detail", !!open); }
  }

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
    if (pet.nature_positive) { natureLine += ' <span class="positive">↑' + esc(pet.nature_positive) + "</span>"; }
    if (pet.nature_negative) { natureLine += ' <span class="negative">↓' + esc(pet.nature_negative) + "</span>"; }

    var types = (pet.type_names || []).map(function (name, index) {
      var color = (pet.type_colors || [])[index] || TYPE_FALLBACK;
      return '<span class="type-badge" style="background:' + color + '">' + esc(name) + "</span>";
    }).join(" ") || '<span class="muted">—</span>';

    var skills = pet.skills || [];
    var skillHtml = skills.length ? skills.map(function (item) {
      return '<span class="skill-chip">' + esc(item.name)
        + (item.equipped ? "" : "·未装备") + "</span>";
    }).join("") : '<span class="muted">无技能数据</span>';

    panel.innerHTML =
      '<div class="detail-title"><h2>' + esc(pet.name) + "</h2>"
      + '<span class="muted">Lv' + pet.level + "</span></div>"
      + '<div class="detail-sub">编号 ' + pet.gid + " · 图鉴 " + (pet.base_conf_id || "—")
      + (pet.is_first_catch ? ' · <span class="first-flag">首捕</span>' : "") + "</div>"

      + '<div class="detail-section"><h3>系别 / 性格</h3>'
      + '<div class="info-line">' + types + "</div>"
      + '<div class="info-line"><b>' + natureLine + "</b></div></div>"

      + '<div class="detail-section"><h3>六维对照</h3>'
      + '<table class="stat-table"><tbody>' + statRows + "</tbody></table>"
      + '<div class="info-line muted">数值 / 种族值（竖线为种族值参考）· 总和 '
      + (pet.stat_sum || 0) + (pet.species_stat_sum ? " / 种族 " + pet.species_stat_sum : "")
      + "</div></div>"

      + '<div class="detail-section"><h3>体型 / 声音</h3>'
      + '<div class="meta-grid">'
      + '<div class="meta-cell"><span>身高</span><b>' + esc(pet.height_text) + "</b></div>"
      + '<div class="meta-cell"><span>体重</span><b>' + esc(pet.weight_text) + "</b></div>"
      + '<div class="meta-cell"><span>声音</span><b>' + esc(pet.voice_text) + "</b></div>"
      + '<div class="meta-cell"><span>天赋阶</span><b>' + pet.talent_rank + " 阶</b></div>"
      + "</div></div>"

      + '<div class="detail-section"><h3>技能</h3><div class="skill-list">' + skillHtml + "</div></div>";
  }

  /* ---------- 筛选交互 ---------- */
  function bindPetFilters() {
    var timer = null;
    // 视图切换：卡片（默认，对标蛋神点阵背包）/ 表格（横向比对）
    $("pet-view").querySelectorAll("button").forEach(function (node) {
      node.addEventListener("click", function () {
        state.petView = node.dataset.view;
        state.petPage = 1;
        $("pet-view").querySelectorAll("button").forEach(function (item) {
          item.classList.toggle("active", item === node);
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
    $("f-first").addEventListener("change", function (event) {
      state.filters.first_catch = event.target.checked;
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
      state.filters = { search: "", level_min: 1, level_max: 100, natures: [], types: [], talent_min: 0, first_catch: false, sort: "gid", desc: false };
      $("f-search").value = "";
      $("f-level-min").value = "1";
      $("f-level-max").value = "100";
      $("f-level-label").textContent = "1 – 100";
      $("f-talent").value = "0";
      $("f-first").checked = false;
      $("f-sort").value = "gid";
      $("f-desc").checked = false;
      $("f-natures").querySelectorAll(".chip").forEach(function (node) { node.classList.remove("active"); });
      $("f-types").querySelectorAll(".chip").forEach(function (node) { node.classList.remove("active"); });
      loadPets();
    });
    // 清空内存快照：本地库历史不受影响（需二次确认防误触）
    $("btn-clear-snapshot").addEventListener("click", function () {
      if (!window.confirm("清空当前会话的宠物快照？本地库历史数据不受影响。")) { return; }
      api("/api/pets/clear", { method: "POST" }).then(function (payload) {
        state.pets = payload.pets || [];
        state.selectedPetGid = null;
        renderPets(payload);
        $("pet-detail").innerHTML = '<div class="empty-hint">点击宠物卡片查看详情</div>';
        setPetDetailOpen(false);
        toast("已清空快照（本地库历史保留）");
      }).catch(function (err) { toast("清空失败：" + err.message, true); });
    });
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
        return '<span class="type-badge" style="background:' + color + '">' + esc(name) + "</span>";
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
        + '" data-key="' + esc(item.key) + '">'
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
      return '<span class="type-badge" style="background:' + color + '">' + esc(name) + "</span>";
    }).join(" ") || '<span class="muted">—</span>';

    var evoHtml = (item.evolutions || []).length
      ? item.evolutions.map(function (evo) {
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
        return '<tr data-index="' + row.index + '">'
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
            $("event-detail").innerHTML = '<div class="detail-section"><h3>解码详情</h3>'
              + '<pre class="detail-pre">' + colorizeDecoded(detail.detail) + "</pre></div>";
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
    $("capture-stats").textContent = "原始流 " + (totals.raw_chunks || 0) + " 段 / "
      + (totals.raw_bytes || 0) + " 字节 · 解密成功 " + (totals.decrypt_ok || 0)
      + " · 缺密钥 " + (totals.key_miss || 0) + " · 会话 " + sessions.length
      + (payload.event_log_name ? " · 事件日志 " + payload.event_log_name : "");
    $("session-rows").innerHTML = sessions.length ? sessions.map(function (item) {
      return "<tr><td>" + esc(item.session_id) + "</td>"
        + '<td>' + (item.has_key ? "✓" : "—") + "</td>"
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
    $("btn-start").addEventListener("click", doStart);
    $("btn-stop").addEventListener("click", doStop);
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

  function doStart() {
    api("/api/capture/start", { method: "POST" }).then(function (payload) {
      renderCapture(payload);
      if (payload.last_error) { toast("采集启动失败：" + payload.last_error, true); }
      else { toast("已开始采集"); }
    }).catch(function (err) { toast("启动失败：" + err.message, true); });
  }

  function doStop() {
    api("/api/capture/stop", { method: "POST" }).then(function (payload) {
      renderCapture(payload);
      toast("已停止采集");
    }).catch(function (err) { toast("停止失败：" + err.message, true); });
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
        + '" data-egg="' + egg.egg_conf_id + '">'
        + '<div class="hb-head"><span class="hb-key">' + esc(egg.handbook_no || "—") + "</span>"
        + eggAvatarHtml(egg)
        + "<div><strong>" + esc(egg.egg_name) + "</strong>"
        + "<small>" + esc(egg.name) + "</small></div></div>"
        + '<div class="hb-meta">' + (groups || '<span class="muted">—</span>') + "</div>"
        + '<span class="hb-badge">⏱ ' + esc(egg.hatch_label || "—") + "</span>"
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
      return '<span class="skill-chip">' + esc(member ? member.name : "#" + baseId) + "</span>";
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
      + '<div class="detail-section"><h3>身高 / 体重区间</h3><div class="info-line">'
      + "身高 " + height[0] + " – " + height[1] + " dm · 体重 " + weight[0] + " – " + weight[1] + " g</div></div>"
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
        + '" data-eb="' + egg.instance_id + '">'
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
      + '<div class="detail-section"><h3>属性</h3><dl class="detail-rows">'
      + '<div><dt>获得时间</dt><dd>' + (egg.obtained_at ? new Date(egg.obtained_at * 1000).toLocaleString() : "未知") + "</dd></div>"
      + '<div><dt>身高</dt><dd>' + (egg.height_cm ? egg.height_cm + " cm" : "—") + "</dd></div>"
      + '<div><dt>体重</dt><dd>' + (egg.weight_g ? egg.weight_g + " g" : "—") + "</dd></div>"
      + "</dl></div>";
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
    $("btn-eggbox-clear").addEventListener("click", function () {
      api("/api/egg-box/clear", { method: "POST" }).then(function (payload) {
        eggBoxState.data = payload;
        eggBoxState.selected = null;
        renderEggBox();
        toast("蛋仓快照已清空（本地库历史保留）");
      }).catch(function (err) { toast("清空失败：" + err.message, true); });
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
        var attr = ' data-mmkey="' + encodeURIComponent(key) + '"';
        if (!pets) { return '<td class="mm-cell empty"' + attr + '>—</td>'; }
        var chips = pets.map(function (pet) {
          var mark = pet.gender === 2 ? "♀" : "♂";
          return '<span class="mm-pet" data-mm="' + pet.gid + '"><img src="' + esc(pet.icon_url)
            + '" alt="" loading="lazy" onerror="this.remove()">' + mark + esc(pet.name) + "</span>";
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
      return '<div class="home-nest"><b>' + esc(nest.name) + "</b>"
        + '<span class="muted">配置 #' + nest.config_id + "</span></div>";
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
      var blocks = groups.map(function (g) {
        var pets = payload.cells[nature.name + "|" + g] || [];
        var chips = pets.map(function (pet) {
          var mark = pet.gender === 2 ? "♀" : "♂";
          return '<span class="mm-pet" data-mm="' + pet.gid + '"><img src="' + esc(pet.icon_url)
            + '" alt="" loading="lazy" onerror="this.remove()">' + mark + esc(pet.name)
            + '<small>Lv' + pet.level + "</small></span>";
        }).join("");
        return '<div class="bl-group"><b>' + esc(g) + '</b><div class="bl-chips">' + chips + "</div></div>";
      }).join("");
      return '<details class="bl-nature" open><summary>' + esc(nature.name)
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
    return '<div class="fl-card"><b>' + esc(r.pet_name) + "</b>"
      + '<small>槽位 #' + esc(r.slot_id) + "</small>"
      + '<span class="muted">' + planted + "</span></div>";
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

  /* ---------- 启动（15s 超时 + 自动重试 2 次，与自恢复链协同） ---------- */
  var BOOT_RETRIES = 2;

  function bootAttempt(remaining) {
    var controller = ("AbortController" in window) ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, 15000) : null;
    api("/api/bootstrap", { signal: controller ? controller.signal : undefined }).then(function (payload) {
      if (timer) { clearTimeout(timer); }
      if (window.__spritelensBoot) { window.__spritelensBoot.ready(); }
      $("startup").hidden = true;
      $("app").hidden = false;
      renderOverview(payload.overview || {});
      state.petOptions = (payload.pets || {}).options || null;
      state.pets = (payload.pets || {}).pets || [];
      state.petTotal = (payload.pets || {}).total || 0;
      renderPetFilters(state.petOptions || {});
      renderPets(payload.pets || {});
      renderCapture(payload.capture || {});
      renderState(payload.state || {});
      renderFeaturePlaceholders();
      bindPetFilters();
      bindHandbookFilters();
      bindEggDexFilters();
      bindEggBoxActions();
      bindMaleMatrixActions();
      bindCaptureActions();
      loadIfaces();
      connectPush();
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
