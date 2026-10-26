/* 外观与浏览器调试设置。 */
(function () {
  "use strict";
  var preferences = { theme: "miaomiao", pet_view: "point", fields: { groups: true, height: true, weight: true, voice: true, positions: false }, shortcuts: [], home_orders: {} };
  var saveQueue = Promise.resolve();
  var save = null;
  var notify = null;
  var openBrowser = null;

  function apply(value) {
    preferences = Object.assign({}, value);
    document.documentElement.dataset.theme = preferences.theme;
    Object.keys(preferences.fields).forEach(function (field) {
      document.getElementById("page-pets").classList.toggle("hide-pet-" + field, !preferences.fields[field]);
      var input = document.querySelector('[data-pet-field="' + field + '"]');
      if (input) { input.checked = preferences.fields[field]; }
    });
    document.querySelectorAll("[data-theme-choice]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.themeChoice === preferences.theme));
    });
    document.dispatchEvent(new CustomEvent("preferenceschanged", { detail: preferences }));
  }

  function update(changes) {
    var draft = { theme: changes.theme || preferences.theme, pet_view: changes.pet_view || preferences.pet_view,
      fields: Object.assign({}, preferences.fields, changes.fields || {}), shortcuts: changes.shortcuts || preferences.shortcuts || [],
      home_orders: changes.home_orders || preferences.home_orders || {} };
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
    initialize: function (value, persist, toast, open) { save = persist; notify = toast; openBrowser = open; apply(value); },
    view: function (view) { update({ pet_view: view }); },
    shortcuts: function (items) { return update({ shortcuts: items }); }
  };
})();
