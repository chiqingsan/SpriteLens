/* 小洛探探 SpriteLens — 壳层扩展：可折叠侧栏
 *
 * 只依赖 window.SpriteLensShell.syncNavIndicator 暴露的能力，
 * 折叠状态写入 localStorage，宽度过渡结束后重新对齐导航滑块。
 */
(function () {
  "use strict";

  var RAIL_KEY = "spritelens.sidebarRail";
  var SPRITE = "/static/icons/sprite.svg";
  var shell = window.SpriteLensShell;
  if (!shell) { return; }

  function $(id) { return document.getElementById(id); }

  var appShell = $("app");
  var railButton = $("btn-rail-toggle");
  var railTimer = 0;
  var railFrame = 0;

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
    if (persist) { appShell.classList.add("rail-motion", "rail-animating"); }
    appShell.classList.toggle("sidebar-rail", collapsed);
    syncRailTitles(collapsed);
    railButton.setAttribute("aria-pressed", String(collapsed));
    var label = collapsed ? "展开侧栏（Ctrl+B）" : "折叠侧栏（Ctrl+B）";
    railButton.title = label;
    railButton.setAttribute("aria-label", collapsed ? "展开侧栏" : "折叠侧栏");
    var use = railButton.querySelector("use");
    if (use) { use.setAttribute("href", SPRITE + "#" + (collapsed ? "layout-sidebar-left-expand" : "layout-sidebar-left-collapse")); }
    if (persist) { writeRail(collapsed); }
    window.clearTimeout(railTimer);
    window.cancelAnimationFrame(railFrame);
    function syncFrame() {
      if (shell.syncNavIndicator) { shell.syncNavIndicator(); }
      railFrame = window.requestAnimationFrame(syncFrame);
    }
    if (persist) { railFrame = window.requestAnimationFrame(syncFrame); }
    else if (shell.syncNavIndicator) { window.requestAnimationFrame(shell.syncNavIndicator); }
    railTimer = window.setTimeout(function () {
      window.cancelAnimationFrame(railFrame);
      if (shell.syncNavIndicator) { shell.syncNavIndicator(); }
      appShell.classList.remove("rail-animating");
    }, 220);
  }

  if (railButton) {
    railButton.addEventListener("click", function () {
      applyRail(!appShell.classList.contains("sidebar-rail"), true);
    });
    applyRail(readRail(), false);
  }

  document.addEventListener("keydown", function (event) {
    var key = event.key.toLowerCase();
    if ((event.ctrlKey || event.metaKey) && key === "b" && railButton) {
      event.preventDefault();
      applyRail(!appShell.classList.contains("sidebar-rail"), true);
    }
  });
})();
