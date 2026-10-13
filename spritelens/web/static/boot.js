/* 启动自恢复链（对标同类桌面壳产品的 desktop-boot 方案）：
 *
 * 1. 全局捕获 script/link 资源加载错误 —— 前端文件缺失/损坏时给出可见失败
 *    而不是白屏，并提供"重新加载"按钮；
 * 2. 启动面板完全内联、不依赖任何后续模块 —— 即使 app.js 加载失败也能显示；
 * 3. 桌面端只向原生启动面板报告失败/首屏就绪，浏览器模式自行淡出网页面板。
 *
 * 约束：本文件不得依赖 sessionStorage 之外的任何浏览器存储或后续模块。
 */
(function () {
  "use strict";

  // 本脚本在 head 里先于外部样式执行；资源失败可能早于面板 DOM 创建。
  var panel;
  var complete = false;
  var painted = false;
  var nativeCover = false;
  var desktopStartup = new URLSearchParams(window.location.search).get("desktop") === "1";
  if (desktopStartup) { document.documentElement.classList.add("desktop-startup"); }
  var nativeReadySent = false;
  var resourceFailed = false;
  var failure = false;
  var lastMessage = "正在启动…";
  var timer;

  function reportNative() {
    if (!nativeCover) { return; }
    var api = window.pywebview.api;
    if (painted && !nativeReadySent) {
      nativeReadySent = true;
      api.startup_ready().catch(function (error) { console.error("启动面板关闭失败", error); });
    } else if (failure && !painted) {
      api.startup_failed(lastMessage).catch(function (error) { console.error("启动失败提示更新失败", error); });
    }
  }

  window.addEventListener("pywebviewready", function () {
    nativeCover = typeof window.pywebview.api.startup_ready === "function";
    if (!nativeCover) { return; }
    // 原生画面覆盖整个窗口。网页 loaded、标题栏出现与主题应用都在其后完成。
    if (panel) { panel.hidden = true; }
    reportNative();
  });

  function message(text) {
    lastMessage = text;
    var node = panel && panel.querySelector("[data-startup-message]");
    if (node) { node.textContent = text; }
  }

  function failed(reason) {
    if (complete) { return; }
    failure = true;
    message("启动失败：" + reason + "。可尝试重新加载。");
    if (panel) { panel.classList.add("startup-failed"); }
    var button = panel && panel.querySelector("button");
    if (button) { button.hidden = false; }
    reportNative();
  }

  // 资源加载错误（script/link 标签）走捕获阶段，业务异常（window.onerror）不在此拦截
  window.addEventListener("error", function (event) {
    if (event.target === window) { return; }
    var tag = event.target && event.target.tagName;
    if (tag !== "SCRIPT" && tag !== "LINK") { return; }
    var src = (event.target && (event.target.src || event.target.href)) || "未知资源";
    resourceFailed = true;
    failed((tag === "LINK" ? "样式" : "脚本") + " " + src);
  }, true);

  window.addEventListener("DOMContentLoaded", function () {
    panel = document.getElementById("startup");
    if (nativeCover || desktopStartup) { panel.hidden = true; }
    message(lastMessage);
    if (failure) {
      panel.classList.add("startup-failed");
      panel.querySelector("button").hidden = false;
    }
    // app.js 会在 bootstrap 成功后标记完成；未标记则 20s 后提示可重试
    timer = setTimeout(function () {
      if (!complete && !resourceFailed) { failed("启动超时（本地服务无响应？）"); }
    }, 20000);
  });

  // app.js 调用：标记启动成功 / 转达 bootstrap 失败（自动重试耗尽后）
  window.__spritelensBoot = {
    ready: function () {
      if (resourceFailed || complete) { return; }
      complete = true;
      clearTimeout(timer);
      document.getElementById("app").hidden = false;
      panel.classList.remove("startup-failed");
      requestAnimationFrame(function () {
        // 先让首屏布局绘制一帧，快速启动时也能可靠触发 opacity 过渡。
        requestAnimationFrame(function () {
          painted = true;
          if (nativeCover) {
            panel.hidden = true;
            reportNative();
            return;
          }
          if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
            panel.hidden = true;
            return;
          }
          panel.addEventListener("transitionend", function () { panel.hidden = true; }, { once: true });
          panel.classList.add("startup-ready");
        });
      });
    },
    failed: failed,
    message: message
  };
})();
