/* 详情抽屉与键盘交互独立于数据渲染，避免各页面重复处理焦点和遮罩。 */
(function () {
  "use strict";

  var activePanel = null;
  var returnTarget = null;
  var narrow = window.matchMedia("(max-width: 1360px)");
  var petNarrow = window.matchMedia("(max-width: 1360px)");
  var backdrop = document.getElementById("detail-backdrop");
  var observer = new MutationObserver(decorateDetail);
  var inertNodes = [];

  function isModal() {
    return !!activePanel && (activePanel.id === "pet-detail" ? petNarrow.matches : narrow.matches);
  }

  function detailItems() {
    return Array.prototype.slice.call(document.querySelectorAll("#pet-grid [data-gid], #pet-rows [data-gid]"))
      .filter(function (node) { return node.getClientRects().length; });
  }

  function decorateDetail() {
    if (!activePanel || activePanel.querySelector(".detail-close")) { return; }
    var button = document.createElement("button");
    button.type = "button";
    button.className = "ghost-button small detail-close";
    button.textContent = activePanel.id === "pet-detail" ? "返回筛选" : "关闭详情";
    button.addEventListener("click", function () { closeDetail(); });
    activePanel.insertBefore(button, activePanel.firstChild);
    if (activePanel.id === "pet-detail") {
      var items = detailItems();
      var selected = items.filter(function (node) { return node.classList.contains("selected") || node.classList.contains("active"); })[0];
      var index = items.indexOf(selected || returnTarget);
      var nav = document.createElement("div");
      nav.className = "detail-navigation";
      ["上一只", "下一只"].forEach(function (label, direction) {
        var next = document.createElement("button");
        next.type = "button";
        next.className = "ghost-button small";
        next.textContent = label;
        var target = items[index + (direction ? 1 : -1)];
        next.disabled = index < 0 || !target;
        next.addEventListener("click", function () {
          target.click();
          if (!activePanel) { return; }
          var controls = activePanel.querySelectorAll(".detail-navigation button");
          var focus = controls[direction];
          if (!focus || focus.disabled) { focus = activePanel.querySelector(".detail-close"); }
          focus.focus({ preventScroll: true });
        });
        nav.appendChild(next);
      });
      activePanel.insertBefore(nav, button.nextSibling);
    }
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
    if (id === "pet-detail") {
      panel.parentNode.classList.add("has-detail");
      document.querySelectorAll("#page-pets [data-gid]").forEach(function (node) {
        var selected = source && node.dataset.gid === source.dataset.gid;
        node.classList.toggle("selected", !!selected);
        node.setAttribute("aria-pressed", String(!!selected));
      });
    }
    panel.setAttribute("aria-label", "详情");
    decorateDetail();
    observer.observe(panel, { childList: true });
    syncDrawer();
    if (isModal()) { panel.querySelector(".detail-close").focus({ preventScroll: true }); }
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest(".nav-item")) { return; }
    var source = event.target.closest(".point-pet, .pet-card, #pet-rows tr, #hb-grid .hb-card, #ed-grid .hb-card, #eb-grid .hb-card, #mm-matrix [data-mmkey]");
    if (!source || event.target.closest("[data-mm]")) { return; }
    var panel = source.closest(".workspace").querySelector(".detail-panel");
    if (panel) { openDetail(panel.id, source); }
  });

  document.addEventListener("keydown", function (event) {
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
  petNarrow.addEventListener("change", function () {
    syncDrawer();
    if (isModal()) { activePanel.querySelector(".detail-close").focus({ preventScroll: true }); }
  });

  /* 条件摘要复用现有输入事件，保证移除标签与手动修改走同一数据路径。 */
  document.addEventListener("petsrendered", function (event) {
    var filters = event.detail.filters || {};
    var summary = document.getElementById("pet-active-filters");
    summary.replaceChildren();
    function add(label, clear) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "filter-tag";
      button.textContent = label + " ×";
      button.setAttribute("aria-label", "移除筛选：" + label);
      button.addEventListener("click", clear);
      summary.appendChild(button);
    }
    function change(id, value, type) {
      var input = document.getElementById(id);
      if (input.type === "checkbox") { input.checked = value; }
      else { input.value = value; }
      input.dispatchEvent(new Event(type || "change", { bubbles: true }));
    }
    if (filters.search) { add("搜索：" + filters.search, function () { change("f-search", "", "input"); }); }
    if (filters.gender) { add(filters.gender === 1 ? "雄性" : "雌性", function () { change("f-gender", "0"); }); }
    if (filters.level_min > 1 || filters.level_max < 100) {
      add("等级 " + filters.level_min + "–" + filters.level_max, function () {
        change("f-level-min", "1", "input"); change("f-level-max", "100", "input");
      });
    }
    if (filters.talent_min) { add("天赋 ≥ " + filters.talent_min + " 阶", function () { change("f-talent", "0"); }); }
    (filters.natures || []).forEach(function (id) {
      var chip = document.querySelector('[data-nature="' + Number(id) + '"]');
      if (chip) { add("性格：" + chip.textContent, function () { chip.click(); }); }
    });
    (filters.types || []).forEach(function (name) {
      var chip = Array.prototype.slice.call(document.querySelectorAll("#f-types .chip"))
        .filter(function (node) { return node.dataset.type === name; })[0];
      if (chip) { add("系别：" + name, function () { chip.click(); }); }
    });
    summary.hidden = !summary.childElementCount;
    var maxed = document.getElementById("quick-maxed");
    var isMaxed = filters.level_min === 60 && filters.level_max === 100;
    maxed.classList.toggle("active", isMaxed);
    maxed.setAttribute("aria-pressed", String(isMaxed));
    document.querySelectorAll("#f-natures .chip, #f-types .chip").forEach(function (node) {
      node.setAttribute("aria-pressed", String(node.classList.contains("active")));
    });
  });
  document.getElementById("quick-maxed").addEventListener("click", function () {
    var min = document.getElementById("f-level-min");
    var max = document.getElementById("f-level-max");
    var enabled = min.value === "60" && max.value === "100";
    min.value = enabled ? "1" : "60";
    max.value = "100";
    min.dispatchEvent(new Event("input", { bubbles: true }));
  });

  window.SpriteLensUI = { openDetail: openDetail, closeDetail: closeDetail };
})();
