/* 本地 Tabler sprite；只装饰 UI，游戏资产和性别符号保持业务语义。 */
(function () {
  "use strict";
  var pages = { pets: "backpack", handbook: "book-2", "egg-dex": "egg",
    "egg-box": "box", "breeder-library": "users", planner: "sitemap",
    "collection-lines": "checklist", home: "home", colors: "palette", capture: "settings" };
  var controls = { "btn-pet-filters": "filter", "btn-reset-filters": "filter-off", "btn-empty-reset": "filter-off",
    "btn-close-pet-filters": "x",
    "btn-theme-default": "refresh", "btn-recheck": "refresh", "btn-npcap-install": "download",
    "btn-capture-start": "player-play", "btn-capture-stop": "player-stop", "btn-record-toggle": "activity",
    "btn-key-apply": "circle-check" };
  function icon(name, className) {
    return '<svg class="ui-icon ' + (className || '') + '" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/static/icons/sprite.svg#' + name + '"></use></svg>';
  }
  function decorate() {
    document.querySelectorAll(".nav-item[data-page]").forEach(function (button) {
      if (button.dataset.iconReady) { return; }
      var old = button.querySelector(".nav-icon");
      if (old) { old.outerHTML = icon(pages[button.dataset.page], "nav-icon"); }
      button.title = button.textContent.trim();
      button.setAttribute("aria-label", button.title);
      button.dataset.iconReady = "true";
    });
    Object.keys(controls).forEach(function (id) {
      var button = document.getElementById(id);
      if (button && !button.closest("[data-vue-page]") && !button.querySelector(".ui-icon")) { button.insertAdjacentHTML("afterbegin", icon(controls[id])); }
    });
    document.querySelectorAll(".detail-close, .detail-navigation button, [data-view], .empty-hint, .feature-placeholder, .filter-tag").forEach(function (node) {
      if (node.closest("[data-vue-page]")) { return; }
      if (node.querySelector(".ui-icon")) { return; }
      var name = "search";
      if (node.classList.contains("filter-tag")) {
        node.textContent = node.textContent.replace(/ ×$/, "");
        node.insertAdjacentHTML("beforeend", icon("x"));
        return;
      }
      if (node.classList.contains("detail-close")) { name = "x"; }
      else if (node.closest(".detail-navigation")) { name = node.textContent === "上一只" ? "chevron-left" : "chevron-right"; }
      else if (node.dataset.view) { name = node.dataset.view === "table" ? "table" : "layout-grid"; }
      else if (node.classList.contains("feature-placeholder")) { name = node.closest("#page-planner") ? "sitemap" : "checklist"; }
      node.insertAdjacentHTML("afterbegin", icon(name));
    });
    var toggle = document.getElementById("btn-toggle");
    if (toggle && !toggle.querySelector(".ui-icon")) { toggle.insertAdjacentHTML("afterbegin", icon(toggle.textContent.indexOf("停止") >= 0 ? "player-stop" : "player-play")); }
  }
  var pending = false;
  new MutationObserver(function () {
    if (pending) { return; }
    pending = true;
    requestAnimationFrame(function () { pending = false; decorate(); });
  }).observe(document.getElementById("app"), { childList: true, subtree: true });
  decorate();
})();
