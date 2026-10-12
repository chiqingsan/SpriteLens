/* 快捷条件保存定义，不保存当前业务筛选；所有应用仍走背包查询管线。 */
(function () {
  "use strict";
  var shortcuts = [], applied = {}, applyFilters = null, notify = null, pending = null;
  var moreNatures = false;
  var editor = document.getElementById("shortcut-editor");

  function renderShortcuts() {
    var container = document.getElementById("saved-shortcuts"); container.replaceChildren();
    shortcuts.forEach(function (item, index) {
      var row = document.createElement("div"); row.className = "saved-shortcut";
      var button = document.createElement("button"); button.type = "button"; button.className = "chip"; button.textContent = item.name;
      var active = Object.keys(item.filters).every(function (key) { return JSON.stringify(item.filters[key]) === JSON.stringify(applied[key]); });
      button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active));
      button.addEventListener("click", function () { applyFilters(item.filters); });
      var remove = document.createElement("button"); remove.type = "button"; remove.className = "shortcut-remove";
      remove.innerHTML = '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><use href="/static/icons/sprite.svg#x"></use></svg>';
      remove.setAttribute("aria-label", "移除快捷条件：" + item.name);
      remove.addEventListener("click", function () { var next = shortcuts.slice(); next.splice(index, 1); window.SpriteLensAppearance.shortcuts(next); });
      row.append(button, remove); container.appendChild(row);
    });
  }
  function updateNatures() {
    var nodes = document.querySelectorAll("#f-natures .chip");
    nodes.forEach(function (node, index) { node.hidden = !moreNatures && index >= 8 && !node.classList.contains("active"); });
    var button = document.getElementById("btn-more-natures");
    button.hidden = nodes.length <= 8; button.textContent = moreNatures ? "收起其他性格" : "更多性格（" + Math.max(0, nodes.length - 8) + "）";
    button.setAttribute("aria-expanded", String(moreNatures));
  }
  function summarize(key, text) { document.querySelector('[data-filter-summary="' + key + '"]').textContent = text; }
  document.getElementById("btn-more-natures").addEventListener("click", function () { moreNatures = !moreNatures; updateNatures(); });
  document.getElementById("btn-pin-filters").addEventListener("click", function () {
    var pendingRange = Array.from(document.querySelectorAll("[data-measure-filter]")).some(function (input) {
      var value = applied[input.dataset.measureFilter]; return input.value === "" ? value != null : Number(input.value) !== value;
    });
    if (document.getElementById("pet-grid").getAttribute("aria-busy") === "true" || document.querySelector('[data-measure-filter][aria-invalid="true"]') || pendingRange || document.getElementById("f-search").value.trim().toLowerCase() !== (applied.search || "")) { notify("请等待筛选完成并确认输入有效", true); return; }
    if (shortcuts.length >= 6) { notify("最多固定六组条件，请先移除一组", true); return; }
    var tags = Array.from(document.querySelectorAll("#pet-active-filters .filter-tag")).map(function (node) { return node.textContent.replace(/ ×$/, "").trim(); });
    if (!tags.length) { notify("请先选择要固定的筛选条件", true); return; }
    pending = JSON.parse(JSON.stringify(applied)); editor.hidden = false;
    document.getElementById("shortcut-name").value = tags.join(" · ").slice(0, 40); document.getElementById("shortcut-name").focus();
  });
  document.getElementById("btn-cancel-shortcut").addEventListener("click", function () { editor.hidden = true; pending = null; });
  editor.addEventListener("submit", function (event) {
    event.preventDefault(); var name = document.getElementById("shortcut-name").value.trim();
    if (!name || !pending) { return; }
    window.SpriteLensAppearance.shortcuts(shortcuts.concat([{ name: name, filters: pending }])); editor.hidden = true; pending = null;
  });
  document.addEventListener("preferenceschanged", function (event) { shortcuts = event.detail.shortcuts || []; renderShortcuts(); });
  document.addEventListener("petsrendered", function (event) {
    applied = event.detail.filters || {}; updateNatures(); renderShortcuts();
    ["natures", "types", "egg_groups"].forEach(function (key) { summarize(key, (applied[key] || []).length ? "已选 " + applied[key].length + " 项" : "不限"); });
    [["measurements", ["height", "weight", "voice"]], ["positions", ["height_position", "weight_position"]]].forEach(function (spec) {
      var count = spec[1].filter(function (field) { return applied[field + "_min"] != null || applied[field + "_max"] != null; }).length;
      summarize(spec[0], count ? "已设 " + count + " 项" : "不限");
    });
  });
  document.querySelector(".pet-view-settings").addEventListener("keydown", function (event) { if (event.key === "Escape") { this.open = false; this.querySelector("summary").focus(); } });
  window.SpriteLensBackpackControls = { initialize: function (apply, toast) { applyFilters = apply; notify = toast; } };
})();
