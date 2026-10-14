/* 外观与浏览器调试设置；图片模式由背包使用现有载荷重新绘制。 */
(function () {
  "use strict";
  var preferences = { theme: "miaomiao", pet_view: "point", pet_image: "portrait", fields: { groups: true, height: true, weight: true, voice: true, positions: false }, shortcuts: [] };
  var saveQueue = Promise.resolve();
  var save = null;
  var notify = null;
  var openBrowser = null;

  function apply(value) {
    preferences = value;
    document.documentElement.dataset.theme = value.theme;
    document.getElementById("pet-image-mode").value = value.pet_image || "portrait";
    Object.keys(value.fields).forEach(function (field) {
      document.getElementById("page-pets").classList.toggle("hide-pet-" + field, !value.fields[field]);
      var input = document.querySelector('[data-pet-field="' + field + '"]');
      if (input) { input.checked = value.fields[field]; }
    });
    document.querySelectorAll("[data-theme-choice]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.themeChoice === value.theme));
    });
    document.dispatchEvent(new CustomEvent("preferenceschanged", { detail: value }));
  }

  function update(changes) {
    var draft = { theme: changes.theme || preferences.theme, pet_view: changes.pet_view || preferences.pet_view,
      pet_image: changes.pet_image || preferences.pet_image || "portrait",
      fields: Object.assign({}, preferences.fields, changes.fields || {}), shortcuts: changes.shortcuts || preferences.shortcuts || [] };
    apply(draft);
    document.getElementById("appearance-status").textContent = "保存中…";
    var result = saveQueue.then(function () { return save(draft); }).then(function (value) {
      document.getElementById("appearance-status").textContent = "偏好已保存";
      // 后续操作可能已经应用，保存较早响应不能覆盖新选择。
      return value;
    });
    saveQueue = result.catch(function (error) {
      document.getElementById("appearance-status").textContent = "保存失败，当前预览仍可用；请重试";
      notify(error.message, true);
    });
    return result;
  }

  document.querySelectorAll("[data-theme-choice]").forEach(function (button) {
    button.addEventListener("click", function () { update({ theme: button.dataset.themeChoice }); });
  });
  document.querySelectorAll("[data-pet-field]").forEach(function (input) {
    input.addEventListener("change", function () {
      var fields = {}; fields[input.dataset.petField] = input.checked; update({ fields: fields });
    });
  });
  document.getElementById("btn-theme-default").addEventListener("click", function () { update({ theme: "miaomiao" }); });

  document.getElementById("pet-image-mode").addEventListener("change", function () { update({ pet_image: this.value }); });

  document.getElementById("btn-open-browser").addEventListener("click", async function () {
    this.disabled = true;
    try {
      await openBrowser();
      notify("已请求打开默认浏览器，可按 F12 检查布局");
    } catch (error) {
      notify("打开浏览器失败：" + error.message, true);
    } finally {
      this.disabled = false;
    }
  });

  window.SpriteLensAppearance = {
    imageMode: function () { return preferences.pet_image || "portrait"; },
    initialize: function (value, persist, toast, open) { save = persist; notify = toast; openBrowser = open; apply(value); },
    view: function (view) { update({ pet_view: view }); },
    shortcuts: function (items) { return update({ shortcuts: items }); },
    ranges: function (title, ranges, positions) {
      function esc(text) { var node = document.createElement("span"); node.textContent = text; return node.innerHTML; }
      var content = ["height", "weight"].map(function (field) {
        var position = positions && positions[field];
        var extra = "";
        if (position && position.ratio !== null) {
          extra = position.status === "within" ? " · 范围位置 " + Math.round(position.ratio * 100) + "%" : " · 超出参考范围";
        }
        var meter = position && position.ratio !== null ? '<div class="reference-track" role="img" aria-label="' + (field === "height" ? "身高" : "体重") + extra + '"><i style="left:' + (Math.max(0, Math.min(1, position.ratio)) * 100) + '%"></i></div>' : '';
        return '<div class="info-line">' + (field === "height" ? "身高 " : "体重 ") + esc((ranges || {})[field] || "暂无数据") + extra + '</div>' + meter;
      }).join("");
      return '<div class="detail-section"><h3>' + esc(title) + '</h3>' + content + '</div>';
    }
  };
})();
