/* 自绘标题栏只在 pywebview 桥就绪后启用，与业务页面的状态和 DOM 分离。 */
(function () {
  "use strict";

  var titlebar = document.getElementById("desktop-titlebar");
  var maximize = document.getElementById("window-maximize");
  var api;
  var pendingResize;
  var resizing = false;

  async function flushResize() {
    if (resizing || !pendingResize) { return; }
    var size = pendingResize;
    pendingResize = null;
    resizing = true;
    try {
      await api.resize_window(size.edge, size.width, size.height);
    } catch (error) {
      pendingResize = null;
      document.getElementById("window-error").textContent = "窗口缩放失败";
      console.error("窗口缩放失败", error);
    } finally {
      resizing = false;
      flushResize();
    }
  }

  function updateState(state) {
    document.body.dataset.windowMaximized = String(state.maximized);
    var label = state.maximized ? "还原窗口" : "最大化";
    maximize.title = label;
    maximize.setAttribute("aria-label", label);
  }

  async function invoke(action, argument) {
    try {
      if (argument === undefined) { await api[action](); }
      else { await api[action](argument); }
      document.getElementById("window-error").textContent = "";
    } catch (error) {
      // 操作失败留在标题栏，启动或业务脚本异常时仍可看见。
      document.getElementById("window-error").textContent = "窗口操作失败";
      console.error("窗口操作失败", error);
    }
  }

  function ready() {
    api = window.pywebview.api;
    document.body.classList.add("desktop-window");
    titlebar.hidden = false;
    api.get_window_state().then(updateState).catch(function (error) {
      console.error("窗口状态读取失败", error);
    });
    titlebar.querySelectorAll("[data-window-action]").forEach(function (button) {
      button.addEventListener("click", function () { invoke(button.dataset.windowAction); });
    });
    // 拖动区域的移动、双击和贴边吸附交给 WebView2/Windows，JS 不逐帧移动窗口。
    document.querySelectorAll("[data-resize-edge]").forEach(function (edge) {
      var start;
      edge.addEventListener("pointerdown", function (event) {
        if (event.button !== 0) { return; }
        event.preventDefault();
        start = { x: event.screenX, y: event.screenY, width: window.innerWidth, height: window.innerHeight };
        edge.setPointerCapture(event.pointerId);
      });
      edge.addEventListener("pointermove", function (event) {
        if (!start) { return; }
        var direction = Number(edge.dataset.resizeEdge);
        var dx = event.screenX - start.x;
        var dy = event.screenY - start.y;
        pendingResize = {
          edge: direction,
          width: Math.round(start.width + ([1, 4, 7].includes(direction) ? -dx : [2, 5, 8].includes(direction) ? dx : 0)),
          height: Math.round(start.height + ([3, 4, 5].includes(direction) ? -dy : [6, 7, 8].includes(direction) ? dy : 0))
        };
        flushResize();
      });
      edge.addEventListener("lostpointercapture", function () {
        start = null;
      });
    });
  }

  window.addEventListener("desktop-window-state", function (event) { updateState(event.detail); });
  window.addEventListener("pywebviewready", ready, { once: true });
})();
