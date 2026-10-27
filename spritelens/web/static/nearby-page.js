/* 附近页装配；复用应用壳的 REST 和唯一 WS，不持有业务实体。 */
(function () {
  "use strict";
  /* 隐藏页供数的最小间隔：提醒默认开启时，每条推送都全量读取会打满本地服务。 */
  var SHELL_MIN_INTERVAL_MS = 2000;
  window.SpriteLensNearby = { create: function (request, token) {
    /* 旧构建/测试没有提醒模块时优雅降级：附近页与雷达照常工作，只是没有声音。 */
    var alertApi = window.SpriteLensNearbyAlert ? window.SpriteLensNearbyAlert.create() : null;
    var mounted = null, summary = null, generation = 0, active = false;
    var floating = false, feedController = null, feedQueued = false, feedLast = 0, feedTimer = null, hadSnapshot = false, heartbeat = null, disconnectTimer = null;
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
      return !summary || payload.uid === summary.uid && (payload.observation_id > summary.observation_id
        || payload.observation_id === summary.observation_id && payload.version >= summary.version);
    }
    function publish(payload) {
      /* 旧 REST 响应不应倒退悬浮窗状态，更不能触发已经过时的声音提醒。 */
      if (!currentCycle(payload)) { return payload; }
      /* 声音提醒复用同一份快照；它自己判重与降级，失败不影响列表与雷达。 */
      if (alertApi) {
        try { alertApi.evaluate(payload); } catch (error) { /* 提醒失败只丢提示音 */ }
      }
      if (floating) {
        channel.postMessage({ kind: "snapshot", payload: payload });
        hadSnapshot = true;
      }
      return payload;
    }
    /* 页面可见时 Vue 会自己按摘要取快照；隐藏或未挂载时才由壳层替雷达和声音提醒供数。 */
    function feedNeeded() { return floating || Boolean(alertApi && alertApi.enabled()); }
    function reportFailure(error, signal) {
      if (!floating || (signal && signal.aborted)) { return; }
      var message = error && error.message ? error.message : String(error);
      /* 已有图像时只标注过期，刷新失败不能清空悬浮雷达的旧图；无图像才进入错误空态。 */
      channel.postMessage(hadSnapshot ? { kind: "stale", message: message } : { kind: "error", message: message });
    }
    function clearFeedTimer() { if (feedTimer) { window.clearTimeout(feedTimer); feedTimer = null; } }
    function cancelFeed() { feedQueued = false; clearFeedTimer(); if (feedController) { feedController.abort(); feedController = null; } }
    /* 页面隐藏或未挂载时的补数据要走最小间隔节流；页面自己的读取、回页与补发保持立即执行。 */
    function feedNow() {
      clearFeedTimer();
      feedLast = Date.now();
      loadFloating();
    }
    function feedSoon() {
      if (feedController) { feedQueued = true; return; }
      if (feedTimer) { return; }
      var wait = SHELL_MIN_INTERVAL_MS - (Date.now() - feedLast);
      if (wait <= 0) { feedNow(); return; }
      feedTimer = window.setTimeout(function () { feedTimer = null; feedNow(); }, wait);
    }
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
      }).finally(function () {
        /* 页面加载完时可能已切到后台：声音提醒还需要快照，补一次供数当基线。 */
        if (feedNeeded() && (!mounted || !active)) { feedNow(); }
      });
    }
    function loadFloating() {
      if (feedController) { feedQueued = true; return; }
      var current = feedController = new AbortController();
      requestNearby(current.signal).then(function (payload) {
        if (!current.signal.aborted) { publish(payload); }
      }, function (error) {
        reportFailure(error, current.signal);
        /* 失败后下一次推送立即重试，不让节流窗口拖住可恢复的读取。 */
        if (feedController === current) { feedLast = 0; }
      }).finally(function () {
        if (feedController !== current) { return; }
        feedController = null;
        if (feedQueued && feedNeeded()) { feedQueued = false; feedLast = Date.now(); loadFloating(); }
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
      if (floating && summary) { feedNow(); }
      /* 只隐藏不卸载：切页后保留搜索、排序、选中与滚动位置。 */
    }
    function enter() {
      active = true;
      var current = ++generation, root = document.getElementById("nearby-root");
      /* 回页时页面自己会立即取一次；先清掉隐藏页的排程与在途请求，避免重复读取。 */
      clearFeedTimer();
      if (feedController) { cancelFeed(); }
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
        var host = {
          load: loadPage,
          /* 地图和雷达共用静态清单；页面读取一次，失败时显示重试入口。 */
          loadMaps: function () { return request("/api/world-maps"); },
          openFloating: function () {
            if (!window.pywebview || !window.pywebview.api.open_radar) { return Promise.reject(new Error("置顶悬浮雷达请在桌面版中打开")); }
            return window.pywebview.api.open_radar();
          },
          /* 清除足迹是写操作：只重置当前地图覆盖层，不影响附近列表与观察周期；超时与读取一致，避免按钮一直停在清除中。 */
          resetCoverage: function (owner) {
            var controller = new AbortController();
            var timeout = window.setTimeout(function () { controller.abort(); }, 8000);
            return request("/api/nearby/coverage/reset", { method: "POST", body: owner, signal: controller.signal })
              .catch(function (error) {
                if (controller.signal.aborted) { throw new Error("清除足迹请求超时，请重试"); }
                throw error;
              })
              .finally(function () { window.clearTimeout(timeout); });
          }
        };
        /* 提醒能力由壳层注入，Vue 只负责按钮状态与试听，不自己发声。 */
        if (alertApi) {
          host.alert = {
            enabled: function () { return alertApi.enabled(); },
            toggle: function (next) { return alertApi.toggle(next); }
          };
        }
        mounted = vue.mountNearby(root, host);
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
        /* 页面不可见（切页或从未打开）时按最小间隔合并供数：提醒音默认开启，
           不能每条 500ms 推送都全量读一次快照；首份快照与失败重试仍立即执行。 */
        if (changed && (!mounted || !active) && feedNeeded()) { feedSoon(); }
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
        if (alertApi) { alertApi.dispose(); alertApi = null; }
        channel.close();
      },
      update: update };
  } };
})();
