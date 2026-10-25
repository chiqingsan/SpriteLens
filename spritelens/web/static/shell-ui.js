/* 小洛探探 SpriteLens — 壳层扩展（命令面板 + 侧栏折叠）
 *
 * 只依赖 window.SpriteLensShell / window.SpriteLensAppearance 暴露的能力，
 * 不直接操作各页面的私有数据，页面切换统一走 switchPage。
 */
(function () {
  "use strict";

  var RAIL_KEY = "spritelens.sidebarRail";
  var SPRITE = "/static/icons/sprite.svg";
  var shell = window.SpriteLensShell;
  if (!shell) { return; }

  function $(id) { return document.getElementById(id); }
  function icon(name) {
    return '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="' + SPRITE + "#" + name + '"></use></svg>';
  }

  /* ---------- 侧栏折叠 ---------- */

  var appShell = $("app");
  var railButton = $("btn-rail-toggle");
  var railTimer = 0;

  function readRail() {
    try { return localStorage.getItem(RAIL_KEY) === "1"; } catch (error) { return false; }
  }

  function writeRail(value) {
    try { localStorage.setItem(RAIL_KEY, value ? "1" : "0"); } catch (error) { /* 隐私模式忽略 */ }
  }

  // 折叠后文字被隐藏，用 title 提示补回可读性。
  function syncRailTitles(collapsed) {
    var items = document.querySelectorAll("#main-nav .nav-item, .sidebar-settings");
    Array.prototype.forEach.call(items, function (item) {
      if (collapsed) {
        if (!item.dataset.railTitle) { item.dataset.railTitle = (item.textContent || "").replace(/\s+/g, " ").trim(); }
        if (item.dataset.railTitle) { item.title = item.dataset.railTitle; }
      } else if (item.dataset.railTitle) {
        item.removeAttribute("title");
      }
    });
  }

  function applyRail(collapsed, persist) {
    if (!appShell || !railButton) { return; }
    appShell.classList.toggle("sidebar-rail", collapsed);
    syncRailTitles(collapsed);
    railButton.setAttribute("aria-pressed", String(collapsed));
    var label = collapsed ? "展开侧栏（Ctrl+B）" : "折叠侧栏（Ctrl+B）";
    railButton.title = label;
    railButton.setAttribute("aria-label", collapsed ? "展开侧栏" : "折叠侧栏");
    var use = railButton.querySelector("use");
    if (use) { use.setAttribute("href", SPRITE + "#" + (collapsed ? "layout-sidebar-left-expand" : "layout-sidebar-left-collapse")); }
    if (persist) { writeRail(collapsed); }
    // 宽度过渡结束后再对齐导航滑块，避免测量到动画中间值。
    window.clearTimeout(railTimer);
    railTimer = window.setTimeout(function () { if (shell.syncNavIndicator) { shell.syncNavIndicator(); } }, 260);
    window.requestAnimationFrame(function () { if (shell.syncNavIndicator) { shell.syncNavIndicator(); } });
  }

  if (railButton) {
    railButton.addEventListener("click", function () {
      applyRail(!appShell.classList.contains("sidebar-rail"), true);
    });
    applyRail(readRail(), false);
  }

  /* ---------- 命令面板 ---------- */

  var ICONS = {
    pets: "backpack", handbook: "book-2", "egg-dex": "egg", "egg-box": "box",
    "breeder-library": "users", planner: "sitemap", "collection-lines": "checklist",
    home: "home", nearby: "eye", colors: "palette", capture: "settings"
  };

  function navPages() {
    var seen = Object.create(null);
    var items = [];
    document.querySelectorAll("#main-nav .nav-item[data-page]").forEach(function (node) {
      var page = node.dataset.page;
      if (seen[page]) { return; }
      seen[page] = true;
      var groupNode = node.closest(".nav-group");
      var group = groupNode && groupNode.querySelector(".nav-group-title");
      items.push({
        group: "页面",
        label: node.textContent.trim(),
        hint: group ? group.textContent.trim() : "",
        icon: ICONS[page] || "layout-dashboard",
        keywords: [page],
        keepOpen: false,
        run: function () { shell.switchPage(page); }
      });
    });
    return items;
  }

  function buildActions() {
    var actions = [];
    var toggle = $("btn-toggle");
    var capturing = toggle && toggle.textContent.indexOf("停止") >= 0;
    actions.push({
      group: "操作",
      label: capturing ? "停止采集" : "开始采集",
      hint: "顶栏按钮",
      icon: capturing ? "player-stop" : "player-play",
      keywords: ["capture", "采集", capturing ? "stop" : "start"],
      run: function () { shell.toggleCapture(); }
    });
    actions.push({
      group: "操作",
      label: "折叠 / 展开侧栏",
      hint: "Ctrl+B",
      icon: "layout-sidebar-left-collapse",
      keywords: ["sidebar", "rail", "侧栏"],
      run: function () { applyRail(!appShell.classList.contains("sidebar-rail"), true); }
    });
    actions.push({
      group: "操作",
      label: "打开设置与采集",
      hint: "页面",
      icon: "settings",
      keywords: ["settings", "capture", "设置", "采集"],
      run: function () { shell.switchPage("capture"); }
    });
    var theme = window.SpriteLensAppearance;
    if (theme && theme.initialize) {
      var current = theme.currentTheme ? theme.currentTheme() : "";
      [["喵喵", "miaomiao"], ["火花", "huohua"], ["水蓝蓝", "shuilanlan"]].forEach(function (pair) {
        actions.push({
          group: "外观",
          label: "切换到主题：" + pair[0],
          hint: current === pair[1] ? "当前" : "",
          icon: "palette",
          keywords: ["theme", "主题", pair[1]],
          run: function () { theme.theme(pair[1]); }
        });
      });
    }
    return actions;
  }

  var layer = null;
  var input = null;
  var listNode = null;
  var items = [];
  var visible = [];
  var activeIndex = 0;
  var lastTrigger = null;

  function normalize(text) {
    return String(text || "").toLowerCase().trim();
  }

  function matches(item, term) {
    if (!term) { return true; }
    var haystack = normalize(item.label + " " + (item.hint || "") + " " + (item.keywords || []).join(" "));
    return term.split(/\s+/).every(function (part) { return haystack.indexOf(part) >= 0; });
  }

  function render() {
    var term = normalize(input.value);
    visible = items.filter(function (item) { return matches(item, term); });
    if (activeIndex >= visible.length) { activeIndex = Math.max(0, visible.length - 1); }
    var html = "";
    var lastGroup = "";
    visible.forEach(function (item, index) {
      if (item.group !== lastGroup) {
        lastGroup = item.group;
        html += '<li class="ui-command-group" role="presentation">' + item.group + "</li>";
      }
      html += '<li class="ui-command-item' + (index === activeIndex ? " is-active" : "") + '" role="option" aria-selected="' + (index === activeIndex) + '" data-index="' + index + '">' +
        icon(item.icon) + '<span class="ui-command-label">' + escapeHtml(item.label) + "</span>" +
        (item.hint ? '<span class="ui-command-hint">' + escapeHtml(item.hint) + "</span>" : "") +
        "</li>";
    });
    if (!visible.length) { html = '<li class="ui-command-empty" role="presentation">没有匹配的页面或命令</li>'; }
    listNode.innerHTML = html;
    var active = listNode.querySelector(".ui-command-item.is-active");
    if (active && active.scrollIntoView) { active.scrollIntoView({ block: "nearest" }); }
  }

  function escapeHtml(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function move(delta) {
    if (!visible.length) { return; }
    activeIndex = (activeIndex + delta + visible.length) % visible.length;
    render();
  }

  function execute(index) {
    var item = visible[index];
    if (!item) { return; }
    closePalette();
    item.run();
  }

  function buildPalette() {
    layer = document.createElement("div");
    layer.className = "ui-command-layer";
    layer.hidden = true;
    layer.innerHTML =
      '<div class="ui-command-backdrop" data-command-close="1"></div>' +
      '<div class="ui-command" role="dialog" aria-modal="true" aria-label="搜索与命令">' +
        '<div class="ui-command-input-row">' + icon("search") +
          '<input id="ui-command-input" type="text" role="combobox" aria-expanded="true" aria-controls="ui-command-list" aria-autocomplete="list" autocomplete="off" spellcheck="false" placeholder="搜索页面或命令…">' +
          '<kbd class="ui-kbd">Esc</kbd>' +
        "</div>" +
        '<ul id="ui-command-list" class="ui-command-list" role="listbox" aria-label="命令列表"></ul>' +
        '<div class="ui-command-foot"><span><kbd class="ui-kbd">↑</kbd><kbd class="ui-kbd">↓</kbd> 选择</span><span><kbd class="ui-kbd">Enter</kbd> 执行</span><span><kbd class="ui-kbd">Ctrl K</kbd> 打开</span></div>' +
      "</div>";
    document.body.appendChild(layer);
    input = $("ui-command-input");
    listNode = $("ui-command-list");
    layer.addEventListener("click", function (event) {
      if (event.target.closest("[data-command-close]")) { closePalette(); }
    });
    listNode.addEventListener("mousemove", function (event) {
      var item = event.target.closest(".ui-command-item");
      if (!item) { return; }
      var index = Number(item.dataset.index);
      if (index !== activeIndex) { activeIndex = index; render(); }
    });
    listNode.addEventListener("click", function (event) {
      var item = event.target.closest(".ui-command-item");
      if (item) { execute(Number(item.dataset.index)); }
    });
    input.addEventListener("input", function () { activeIndex = 0; render(); });
    input.addEventListener("keydown", function (event) {
      if (event.isComposing) { return; }
      if (event.key === "ArrowDown") { event.preventDefault(); move(1); }
      else if (event.key === "ArrowUp") { event.preventDefault(); move(-1); }
      else if (event.key === "Enter") { event.preventDefault(); execute(activeIndex); }
      else if (event.key === "Escape") { event.preventDefault(); closePalette(); }
    });
  }

  function openPalette(trigger) {
    if (!layer) { buildPalette(); }
    lastTrigger = trigger || document.activeElement;
    items = navPages().concat(buildActions());
    activeIndex = 0;
    input.value = "";
    layer.hidden = false;
    render();
    input.focus();
    document.body.classList.add("ui-command-open");
  }

  function closePalette() {
    if (!layer || layer.hidden) { return; }
    layer.hidden = true;
    document.body.classList.remove("ui-command-open");
    if (lastTrigger && lastTrigger.focus) { lastTrigger.focus(); }
  }

  var triggerButton = $("btn-command");
  if (triggerButton) {
    triggerButton.addEventListener("click", function () { openPalette(triggerButton); });
  }

  document.addEventListener("keydown", function (event) {
    var key = event.key.toLowerCase();
    if ((event.ctrlKey || event.metaKey) && key === "k") {
      event.preventDefault();
      if (layer && !layer.hidden) { closePalette(); }
      else { openPalette(triggerButton); }
      return;
    }
    if ((event.ctrlKey || event.metaKey) && key === "b") {
      if (railButton) { event.preventDefault(); applyRail(!appShell.classList.contains("sidebar-rail"), true); }
    }
    if (layer && !layer.hidden && event.key === "Escape") { closePalette(); }
  });
})();
