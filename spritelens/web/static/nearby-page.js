/* 附近页装配；复用应用壳的 REST 和唯一 WS，不持有业务实体。 */
(function () {
  "use strict";
  window.SpriteLensNearby = { create: function (request, token) {
    var mounted = null, summary = null, generation = 0, active = false;
    var floating = false, feedController = null, feedQueued = false, hadSnapshot = false, heartbeat = null, disconnectTimer = null;
    var channel = new BroadcastChannel("spritelens-nearby-" + token);
    async function requestNearby(signal) {
      var controller = new AbortController();
      function cancel() { controller.abort(); }
      signal.addEventListener("abort", cancel, { once: true });
      if (signal.aborted) { cancel(); }
      var timeout = window.setTimeout(cancel, 8000);
      try { return await request("/api/nearby", { signal: controller.signal }); }
      catch (error) {
        if (controller.signal.aborted && !signal.aborted) { throw new Error("附近观察请求超时，请重试"); }
        throw error;
      } finally { window.clearTimeout(timeout); signal.removeEventListener("abort", cancel); }
    }
    function currentCycle(payload) {
      return !summary || payload.uid === summary.uid && payload.observation_id >= summary.observation_id;
    }
    function publish(payload) {
      if (floating && currentCycle(payload)) {
        channel.postMessage({ kind: "snapshot", payload: payload });
        hadSnapshot = true;
      }
      return payload;
    }
    function reportFailure(error, signal) {
      if (!floating || (signal && signal.aborted)) { return; }
      var message = error && error.message ? error.message : String(error);
      /* 已有图像时只标注过期，刷新失败不能清空悬浮雷达的旧图；无图像才进入错误空态。 */
      channel.postMessage(hadSnapshot ? { kind: "stale", message: message } : { kind: "error", message: message });
    }
    function cancelFeed() { feedQueued = false; if (feedController) { feedController.abort(); feedController = null; } }
    function stopFloating() { floating = false; hadSnapshot = false; cancelFeed(); }
    window.addEventListener("radar-closed", stopFloating);
    /* 页面存活且推送在线时持续广播心跳，悬浮雷达据此判断数据是否仍然新鲜。
       连接断开后暂停心跳：超过 3 秒没有消息，雷达自行清空并提示失效。 */
    function startHeartbeat() {
      if (heartbeat) { return; }
      heartbeat = window.setInterval(function () { channel.postMessage({ kind: "ping" }); }, 1000);
    }
    function stopHeartbeat() {
      if (heartbeat) { window.clearInterval(heartbeat); heartbeat = null; }
    }
    startHeartbeat();
    function loadPage(signal) {
      return requestNearby(signal).then(function (payload) {
        if (!signal.aborted) { publish(payload); }
        return payload;
      }, function (error) {
        reportFailure(error, signal);
        throw error;
      });
    }
    function loadFloating() {
      if (feedController) { feedQueued = true; return; }
      var current = feedController = new AbortController();
      requestNearby(current.signal).then(function (payload) {
        if (!current.signal.aborted) { publish(payload); }
      }, function (error) {
        reportFailure(error, current.signal);
      }).finally(function () {
        if (feedController !== current) { return; }
        feedController = null;
        if (feedQueued && floating) { feedQueued = false; loadFloating(); }
      });
    }
    channel.onmessage = function (event) {
      if (event.data.kind === "subscribe") {
        floating = true;
        hadSnapshot = false;
        if (summary) { channel.postMessage({ kind: "summary", summary: summary }); loadFloating(); }
        else { channel.postMessage({ kind: "error", message: "当前没有可用的附近观察数据" }); }
      } else if (event.data.kind === "unsubscribe") {
        stopFloating();
      }
    };
    function leave() {
      active = false; generation++;
      if (mounted) { mounted.pause(); }
      if (floating && summary) { loadFloating(); }
      /* 只隐藏不卸载：切页后保留搜索、排序、选中与滚动位置。 */
    }
    function enter() {
      active = true;
      var current = ++generation, root = document.getElementById("nearby-root");
      if (mounted) {
        mounted.resume();
        if (!summary) {
          mounted.update(null);
          return;
        }
        var pending = summary;
        mounted.update(pending);
        return;
      }
      root.textContent = "正在加载附近精灵…";
      return import("/static/vue/entry.js").then(function (vue) {
        if (!active || current !== generation) { return; }
        mounted = vue.mountNearby(root, {
          load: loadPage,
          openFloating: function () {
            if (!window.pywebview || !window.pywebview.api.open_radar) { return Promise.reject(new Error("置顶悬浮雷达请在桌面版中打开")); }
            return window.pywebview.api.open_radar();
          }
        });
        if (summary) { mounted.update(summary); }
        else { return mounted.load(); }
      }).catch(function (error) {
        mounted = null;
        if (active && current === generation) { root.textContent = "附近页面加载失败，请切页重试：" + error.message; }
      });
    }
    function update(next) {
        var changed = next && (!summary || next.uid !== summary.uid || next.observation_id !== summary.observation_id || next.version !== summary.version || next.phase !== summary.phase);
        if (!next || (summary && (next.uid !== summary.uid || next.observation_id !== summary.observation_id))) {
          hadSnapshot = false; cancelFeed();
        }
        summary = next;
        if (floating) { channel.postMessage(next ? { kind: "summary", summary: next } : { kind: "error", message: "当前没有可用的附近观察数据" }); }
        // 隐藏页面仍接收归属失效，但暂停请求，避免回页闪现旧周期实体。
        if (mounted) { mounted.update(next); }
        if (floating && changed && (!mounted || !active)) { loadFloating(); }
    }
    return { enter: enter, leave: leave,
      /* 推送连接断开/恢复由壳通知；断线期间不假装数据仍然新鲜。 */
      suspend: function () {
        stopHeartbeat();
        if (!disconnectTimer) { disconnectTimer = window.setTimeout(function () { disconnectTimer = null; update(null); }, 3000); }
      },
      resume: function () {
        if (disconnectTimer) { window.clearTimeout(disconnectTimer); disconnectTimer = null; }
        startHeartbeat();
      },
      unmount: function () {
        stopFloating();
        leave();
        stopHeartbeat();
        if (disconnectTimer) { window.clearTimeout(disconnectTimer); disconnectTimer = null; }
        window.removeEventListener("radar-closed", stopFloating);
        if (mounted) { mounted.unmount(); mounted = null; }
        channel.close();
      },
      update: update };
  } };
})();
