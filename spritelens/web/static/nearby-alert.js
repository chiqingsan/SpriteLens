/* 附近精灵声音提醒：发现双牌重点精灵时响一声。
   重点精灵 = 快照 actors 中 attention 为 double（双牌）的实体；单牌（marked）只显示标记、不发声；
   这里只负责判断与发声，不渲染页面，任何失败都静默降级，不能影响附近页与雷达。 */
(function () {
  "use strict";
  var STORAGE_KEY = "spritelens.nearby.sound";
  /* 同一实体换周期、短暂消失后重现都很常见，十分钟冷却避免把它当成新闻反复响。 */
  var COOLDOWN_MS = 10 * 60 * 1000;

  function readStorage() {
    /* 隐私模式或禁用存储时访问 localStorage 会抛错：按未持久化处理，本次会话仍可开关。 */
    try {
      var storage = window.localStorage;
      if (storage && typeof storage.getItem === "function" && typeof storage.setItem === "function") { return storage; }
    } catch (error) { /* 访问被拒只影响持久化 */ }
    return null;
  }
  function readEnabled(storage) {
    if (!storage) { return true; }
    try { return storage.getItem(STORAGE_KEY) !== "0"; } catch (error) { return true; }
  }
  function writeEnabled(storage, value) {
    if (!storage) { return; }
    try { storage.setItem(STORAGE_KEY, value ? "1" : "0"); } catch (error) { /* 写入失败不影响本次会话 */ }
  }

  window.SpriteLensNearbyAlert = { create: function (options) {
    options = options || {};
    /* 存储、时钟与发声都可注入，测试不需要真实音频和本地存储。 */
    var storage = options.storage !== undefined ? options.storage : readStorage();
    var now = typeof options.now === "function" ? options.now : Date.now;
    var play = typeof options.play === "function" ? options.play : playChime;
    var enabledState = readEnabled(storage);
    var baselineNext = false;
    var known = new Map();
    var cooldown = new Map();
    var lastUid = null, lastObservation = null, lastVersion = null, lastCycle = "";
    var audio = null, listening = false;

    function audioContext() {
      if (audio) { return audio; }
      var Ctor = window.AudioContext || window.webkitAudioContext;
      if (!Ctor) { return null; }
      try { audio = new Ctor(); } catch (error) { audio = null; /* 创建失败只降级为静音，不重试以免每次提醒都抛错 */ }
      return audio;
    }
    function resumeAudio() {
      var context = audioContext();
      if (!context) { return null; }
      try {
        if (context.state === "suspended" && typeof context.resume === "function") {
          var pending = context.resume();
          if (pending && typeof pending.then === "function") { pending.then(function () {}, function () {}); }
        }
      } catch (error) { /* 自动播放策略拒绝恢复时静默，用户下一次手势还有机会 */ }
      return context;
    }
    function tone(context, frequency, start, duration, peak) {
      var oscillator = context.createOscillator();
      var gain = context.createGain();
      oscillator.type = "sine";
      oscillator.frequency.setValueAtTime(frequency, start);
      /* 指数包络从极小值起落，避免起音爆音；两音上行构成易分辨的提示音。 */
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(peak, start + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.start(start);
      oscillator.stop(start + duration + 0.02);
    }
    function playChime() {
      try {
        var context = resumeAudio();
        if (!context) { return; }
        var start = context.currentTime + 0.01;
        tone(context, 987.77, start, 0.22, 0.16);
        tone(context, 1318.51, start + 0.11, 0.3, 0.12);
      } catch (error) { /* 音频不可用绝不影响附近页 */ }
    }
    function unlock() { resumeAudio(); }
    function listen() {
      if (listening || typeof window.addEventListener !== "function") { return; }
      listening = true;
      /* 浏览器要求用户手势后才允许出声：首次点击或按键顺带解锁音频。 */
      window.addEventListener("pointerdown", unlock, { passive: true, once: true });
      window.addEventListener("keydown", unlock, { passive: true, once: true });
    }
    function stopListening() {
      if (!listening) { return; }
      listening = false;
      if (typeof window.removeEventListener === "function") {
        window.removeEventListener("pointerdown", unlock, { passive: true, once: true });
        window.removeEventListener("keydown", unlock, { passive: true, once: true });
      }
    }
    function pruneCooldown(timestamp) {
      cooldown.forEach(function (stamp, id) {
        if (timestamp - stamp >= COOLDOWN_MS) { cooldown.delete(id); }
      });
    }
    function evaluate(payload) {
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) { return; }
      if (!Array.isArray(payload.actors)) { return; }
      if (typeof payload.uid !== "string" && typeof payload.uid !== "number") { return; }
      if (typeof payload.observation_id !== "number" || !isFinite(payload.observation_id)
          || typeof payload.version !== "number" || !isFinite(payload.version)) { return; }
      var uid = String(payload.uid), observation = payload.observation_id, version = payload.version;
      /* 同一 uid 里更旧的观察是迟到的慢响应：忽略，避免旧周期把已知状态倒回去。 */
      if (uid === lastUid && lastObservation !== null && observation < lastObservation) { return; }
      /* 同周期的旧版本同样不能改变已知实体或补发提示音。 */
      if (uid === lastUid && observation === lastObservation && lastVersion !== null && version < lastVersion) { return; }
      lastUid = uid; lastObservation = observation; lastVersion = version;
      var cycle = uid + ":" + observation;
      /* known 只描述当前观察周期；换周期后“仍在列表里”的双牌需要重新判断。 */
      if (cycle !== lastCycle) { lastCycle = cycle; known.clear(); }
      var timestamp = now();
      pruneCooldown(timestamp);
      var candidates = [];
      var present = new Set();
      for (var index = 0; index < payload.actors.length; index++) {
        var actor = payload.actors[index];
        if (!actor || typeof actor !== "object") { continue; }
        if (typeof actor.actor_id !== "string") { continue; }
        var attention = actor.attention;
        if (attention !== "normal" && attention !== "marked" && attention !== "double") { continue; }
        present.add(actor.actor_id);
        var key = attention === "double";
        var wasKey = known.get(actor.actor_id) === "double";
        known.set(actor.actor_id, attention);
        /* 只在“本次才变成双牌”时提醒：持续留在列表里的同一实体不能每份快照都响；单牌新出现不响，之后升为双牌再响。 */
        if (key && !wasKey && !cooldown.has(actor.actor_id)) { candidates.push(actor.actor_id); }
      }
      known.forEach(function (_, id) { if (!present.has(id)) { known.delete(id); } });
      /* 开启后的第一份快照只建立基线，不把用户刚在列表里看到的双牌再补响一次。 */
      if (baselineNext) { baselineNext = false; return; }
      if (!enabledState || !candidates.length) { return; }
      for (var count = 0; count < candidates.length; count++) { cooldown.set(candidates[count], timestamp); }
      /* 一份快照里出现多个双牌也只响一声，避免叠音。 */
      try { play(); } catch (error) { /* 注入的播放实现异常也不能影响附近页 */ }
    }
    function toggle(next) {
      var target = typeof next === "boolean" ? next : !enabledState;
      if (target === enabledState) { return enabledState; }
      enabledState = target;
      writeEnabled(storage, target);
      if (target) {
        /* 先标记基线再试听：试听本身就是用户手势，正好解锁浏览器音频。 */
        baselineNext = true;
        try { play(); } catch (error) { /* 试听失败不影响开关状态 */ }
      }
      return enabledState;
    }
    function dispose() {
      stopListening();
      if (audio) {
        var context = audio;
        audio = null;
        try {
          var pending = typeof context.close === "function" ? context.close() : null;
          if (pending && typeof pending.then === "function") { pending.then(function () {}, function () {}); }
        } catch (error) { /* 关闭失败只影响资源回收，不影响页面 */ }
      }
      known.clear();
      cooldown.clear();
    }
    listen();
    return { evaluate: evaluate, enabled: function () { return enabledState; }, toggle: toggle, dispose: dispose };
  } };
})();
