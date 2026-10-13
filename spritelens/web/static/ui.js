/* 详情抽屉与键盘交互独立于数据渲染，避免各页面重复处理焦点和遮罩。 */
(function () {
  "use strict";

  var activePanel = null;
  var returnTarget = null;
  var narrow = window.matchMedia("(max-width: 1360px)");
  var backdrop = document.getElementById("detail-backdrop");
  var observer = new MutationObserver(decorateDetail);
  var inertNodes = [];

  function isModal() {
    return !!activePanel && narrow.matches;
  }

  function decorateDetail() {
    if (!activePanel || activePanel.querySelector(".detail-close")) { return; }
    var button = document.createElement("button");
    button.type = "button";
    button.className = "ghost-button small detail-close";
    button.textContent = "关闭详情";
    button.addEventListener("click", function () { closeDetail(); });
    activePanel.insertBefore(button, activePanel.firstChild);
    if (isModal() && document.activeElement === document.body) { button.focus({ preventScroll: true }); }
  }

  function syncDrawer() {
    inertNodes.forEach(function (node) { node.inert = false; });
    inertNodes = [];
    var modal = isModal();
    backdrop.hidden = !modal;
    document.body.classList.toggle("drawer-open", modal);
    if (!activePanel) { return; }
    activePanel.setAttribute("role", modal ? "dialog" : "region");
    if (modal) {
      activePanel.setAttribute("aria-modal", "true");
      inertNodes = Array.prototype.slice.call(document.querySelectorAll(".sidebar, .topbar"));
      Array.prototype.forEach.call(activePanel.parentNode.children, function (node) {
        if (node !== activePanel) { inertNodes.push(node); }
      });
      inertNodes.forEach(function (node) { node.inert = true; });
    } else {
      activePanel.removeAttribute("aria-modal");
    }
  }

  function closeDetail(restoreFocus, preserveSelection) {
    if (!activePanel) { return; }
    var panel = activePanel;
    var target = returnTarget;
    observer.disconnect();
    panel.classList.remove("detail-open");
    panel.classList.add("detail-closed");
    panel.removeAttribute("aria-modal");
    panel.setAttribute("role", "region");
    panel.parentNode.classList.remove("has-detail");
    panel.parentNode.classList.add("detail-collapsed");
    activePanel = null;
    returnTarget = null;
    syncDrawer();
    if (!preserveSelection) { document.dispatchEvent(new CustomEvent("detailclosed", { detail: panel.id })); }
    if (restoreFocus !== false) {
      if (!target || !target.isConnected) {
        target = Array.prototype.slice.call(panel.parentNode.querySelectorAll("button, input, select, [tabindex='0']"))
          .filter(function (node) { return !node.disabled && node.getClientRects().length; })[0];
      }
      if (target) { target.focus({ preventScroll: true }); }
    }
  }

  function openDetail(id, source) {
    var panel = document.getElementById(id);
    if (!panel || !panel.closest(".page.active")) { return; }
    if (activePanel && activePanel !== panel) { closeDetail(false); }
    activePanel = panel;
    returnTarget = source || document.activeElement;
    panel.classList.remove("detail-closed");
    panel.classList.add("detail-open");
    panel.parentNode.classList.remove("detail-collapsed");
    panel.setAttribute("aria-label", "详情");
    decorateDetail();
    observer.observe(panel, { childList: true });
    syncDrawer();
    if (isModal()) { panel.querySelector(".detail-close").focus({ preventScroll: true }); }
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-vue-page]")) { return; }
    if (event.target.closest(".nav-item")) { return; }
    var source = event.target.closest("#hb-grid .hb-card, #eb-grid .hb-card, #mm-matrix [data-mmkey]");
    if (!source || event.target.closest("[data-mm]")) { return; }
    var panel = source.closest(".workspace").querySelector(".detail-panel");
    if (panel) { openDetail(panel.id, source); }
  });

  document.addEventListener("keydown", function (event) {
    if (event.target.closest("[data-vue-page]")) { return; }
    if (activePanel && event.key === "Escape") {
      event.preventDefault();
      closeDetail();
      return;
    }
    if (isModal() && event.key === "Tab") {
      var controls = Array.prototype.slice.call(activePanel.querySelectorAll("button, a[href], input, select, [tabindex='0']"))
        .filter(function (node) { return !node.disabled && node.getClientRects().length; });
      var first = controls[0];
      var last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
      return;
    }
    var item = event.target.closest("[role='button'][tabindex='0']");
    if (item && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault(); item.click();
    }
  });

  document.getElementById("btn-pet-filters").addEventListener("click", function () {
    var expanded = this.getAttribute("aria-expanded") !== "true";
    this.setAttribute("aria-expanded", String(expanded));
    document.getElementById("pet-filters").classList.toggle("filters-open", expanded);
  });
  document.getElementById("btn-close-pet-filters").addEventListener("click", function () {
    var button = document.getElementById("btn-pet-filters");
    button.click();
    button.focus({ preventScroll: false });
  });
  backdrop.addEventListener("click", function () { closeDetail(); });
  narrow.addEventListener("change", function () {
    syncDrawer();
    if (isModal()) {
      activePanel.querySelector(".detail-close").focus({ preventScroll: true });
    }
  });
  window.SpriteLensUI = { openDetail: openDetail, closeDetail: closeDetail };
})();
