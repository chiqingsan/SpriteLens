/* 启动自恢复链（对标同类桌面壳产品的 desktop-boot 方案）：
 *
 * 1. 全局捕获 script/link 资源加载错误 —— 前端文件缺失/损坏时给出可见失败
 *    而不是白屏，并提供"重新加载"按钮；
 * 2. 启动面板完全内联、不依赖任何后续模块 —— 即使 app.js 加载失败也能显示；
 * 3. bootstrap 请求超时与自动重试在 app.js 侧完成（boot.js 只管资源层）。
 *
 * 约束：本文件不得依赖 sessionStorage 之外的任何浏览器存储或后续模块。
 */
(function () {
  "use strict";

  var panel = document.getElementById("startup");
  var complete = false;

  function message(text) {
    var node = panel && panel.querySelector("[data-startup-message]");
    if (node) { node.textContent = text; }
  }

  function failed(reason) {
    if (complete) { return; }
    message("界面资源加载失败：" + reason + "。可尝试重新加载。");
    var button = panel && panel.querySelector("button");
    if (button) { button.hidden = false; }
  }

  // 资源加载错误（script/link 标签）走捕获阶段，业务异常（window.onerror）不在此拦截
  window.addEventListener("error", function (event) {
    if (event.target === window) { return; }
    var tag = event.target && event.target.tagName;
    if (tag !== "SCRIPT" && tag !== "LINK") { return; }
    var src = (event.target && (event.target.src || event.target.href)) || "未知资源";
    failed((tag === "LINK" ? "样式" : "脚本") + " " + src);
  }, true);

  window.addEventListener("DOMContentLoaded", function () {
    // app.js 会在 bootstrap 成功后标记完成；未标记则 20s 后提示可重试
    setTimeout(function () {
      if (!complete) { failed("启动超时（本地服务无响应？）"); }
    }, 20000);
  });

  // app.js 调用：标记启动成功 / 转达 bootstrap 失败（自动重试耗尽后）
  window.__spritelensBoot = {
    ready: function () { complete = true; },
    failed: failed,
    message: message
  };
})();
