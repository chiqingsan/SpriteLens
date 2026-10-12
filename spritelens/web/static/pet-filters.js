/* 扩展筛选通过原有筛选管线提交，单位为 m / kg / dB。 */
(function () {
  "use strict";
  var filters = { egg_groups: [], egg_mode: "any" };
  var reload = null;
  var timer = null;
  function rangeValues() {
    document.querySelectorAll("[data-measure-filter]").forEach(function (input) { filters[input.dataset.measureFilter] = input.value; });
  }
  function validInputs() {
    var valid = true;
    document.querySelectorAll("[data-measure-filter]").forEach(function (input) {
      var value = Number(input.value), key = input.dataset.measureFilter;
      var invalid = input.validity.badInput || (input.value !== "" && (!Number.isFinite(value) || (key.indexOf("voice") !== 0 && value < 0) || (key.indexOf("position") >= 0 && value > 100)));
      input.setAttribute("aria-invalid", String(invalid));
      if (invalid) { valid = false; }
    });
    document.getElementById("measurement-filter-status").textContent = valid ? "" : "请输入有效范围：体型不能为负，范围位置为 0–100%。";
    return valid;
  }
  document.getElementById("f-egg-mode").addEventListener("change", function () { filters.egg_mode = this.value; reload(); });
  document.querySelectorAll("[data-measure-filter]").forEach(function (input) {
    input.addEventListener("input", function () { clearTimeout(timer); if (!validInputs()) { return; } rangeValues(); timer = setTimeout(function () { timer = null; reload(); }, 220); });
    input.addEventListener("change", function () {
      clearTimeout(timer); timer = null;
      if (!validInputs()) { return; }
      var swapped = false;
      ["height", "weight", "voice", "height_position", "weight_position"].forEach(function (field) {
        var low = document.querySelector('[data-measure-filter="' + field + '_min"]');
        var high = document.querySelector('[data-measure-filter="' + field + '_max"]');
        if (low.value !== "" && high.value !== "" && Number(low.value) > Number(high.value)) {
          var previous = low.value; low.value = high.value; high.value = previous;
          swapped = true;
        }
      });
      rangeValues(); reload();
      if (swapped) { document.getElementById("measurement-filter-status").textContent = "已交换上下限。"; }
    });
  });
  document.getElementById("btn-reset-filters").addEventListener("click", function () {
    clearTimeout(timer); filters = { egg_groups: [], egg_mode: "any" };
    document.getElementById("f-egg-mode").value = "any";
    document.querySelectorAll("[data-measure-filter]").forEach(function (input) { input.value = ""; });
    validInputs();
    document.querySelectorAll("#f-egg-groups .chip").forEach(function (chip) { chip.classList.remove("active"); chip.setAttribute("aria-pressed", "false"); });
  });
  document.addEventListener("petsrendered", function (event) {
    var options = (event.detail.options || {}).egg_groups || [];
    var group = document.getElementById("f-egg-groups");
    // 选项未变化时保留按钮节点，键盘焦点不因一次筛选响应丢失。
    if (group.dataset.options !== JSON.stringify(options)) {
      group.dataset.options = JSON.stringify(options); group.replaceChildren();
      options.forEach(function (name) {
        var chip = document.createElement("button"); chip.className = "chip"; chip.textContent = name;
        chip.addEventListener("click", function () {
          var index = filters.egg_groups.indexOf(name);
          if (index >= 0) { filters.egg_groups.splice(index, 1); } else { filters.egg_groups.push(name); }
          reload();
        });
        group.appendChild(chip);
      });
    }
    group.querySelectorAll(".chip").forEach(function (chip) {
      var active = filters.egg_groups.indexOf(chip.textContent) >= 0;
      chip.classList.toggle("active", active); chip.setAttribute("aria-pressed", String(active));
    });
    var summary = document.getElementById("pet-active-filters");
    function tag(text, clear) {
      var button = document.createElement("button"); button.className = "filter-tag"; button.textContent = text + " ×";
      button.setAttribute("aria-label", "移除筛选：" + text); button.addEventListener("click", clear); summary.appendChild(button);
    }
    var applied = event.detail.filters || {};
    if ((applied.egg_groups || []).length) {
      tag("蛋组（" + (applied.egg_mode === "all" ? "同时匹配" : "匹配任一") + "）：" + applied.egg_groups.join(" / "), function () { filters.egg_groups = []; reload(); });
    }
    [["height", "身高", "m"], ["weight", "体重", "kg"], ["voice", "声音", "dB"], ["height_position", "身高范围位置", "%"], ["weight_position", "体重范围位置", "%"]].forEach(function (spec) {
      var low = applied[spec[0] + "_min"], high = applied[spec[0] + "_max"];
      if (low != null || high != null) {
        tag(spec[1] + " " + (low == null ? "不限" : low) + "–" + (high == null ? "不限" : high) + " " + spec[2], function () {
          ["min", "max"].forEach(function (bound) { var key = spec[0] + "_" + bound; filters[key] = ""; document.querySelector('[data-measure-filter="' + key + '"]').value = ""; }); reload();
        });
      }
    });
    summary.hidden = !summary.childElementCount;
    document.querySelectorAll("[data-voice-preset]").forEach(function (button) {
      var active = applied.voice_min === Number(button.dataset.voicePreset) && applied.voice_max === Number(button.dataset.voicePreset);
      button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active));
    });
  });
  document.querySelectorAll("[data-voice-preset]").forEach(function (button) {
    button.addEventListener("click", function () {
      var value = button.getAttribute("aria-pressed") === "true" ? "" : button.dataset.voicePreset;
      document.querySelector('[data-measure-filter="voice_min"]').value = value;
      document.querySelector('[data-measure-filter="voice_max"]').value = value;
      rangeValues(); validInputs(); reload();
    });
  });
  window.SpriteLensPetFilters = { initialize: function (load) { reload = load; },
    restore: function (value) {
      clearTimeout(timer); filters = { egg_groups: (value.egg_groups || []).slice(), egg_mode: value.egg_mode || "any" };
      document.getElementById("f-egg-mode").value = filters.egg_mode;
      document.querySelectorAll("[data-measure-filter]").forEach(function (input) { input.value = value[input.dataset.measureFilter] == null ? "" : value[input.dataset.measureFilter]; });
      rangeValues(); validInputs();
    }, query: function () { return Object.assign({}, filters, { egg_groups: filters.egg_groups.join(",") }); } };
})();
