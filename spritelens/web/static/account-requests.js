/* F02 迁移期请求时序：账号归属只由 state 接收入口更新，页面不维护第二份 uid。 */
(function () {
  "use strict";
  function create(api) {
    var uid = null;
    var versions = {};
    var fields = { overview: "pets_version", pets: "pets_version", handbook: "pets_version",
      "male-matrix": "pets_version", "breeder-male": "pets_version", "breeder-female": "pets_version",
      colors: "pets_version", "egg-box": "egg_box_version", home: "home_version", flowers: "flower_version" };
    var generation = 0;
    var pending = {};
    function cancel(key) {
      var current = pending[key];
      if (current) { current.controller.abort(); delete pending[key]; }
    }
    function observe(state) {
      var nextUid = state.uid;
      if (!Number.isSafeInteger(nextUid) || nextUid < 0) { throw new Error("状态载荷缺少有效 uid"); }
      var names = ["pets_version", "egg_box_version", "home_version", "flower_version"];
      if (names.some(function (name) { return !Number.isSafeInteger(state[name]); })) {
        throw new Error("状态载荷缺少有效版本");
      }
      if (names.some(function (name) { return state[name] < (versions[name] || 0); })) {
        return { accepted: false, changed: false };
      }
      var changed = uid !== null && uid !== nextUid;
      if (uid !== nextUid) {
        generation++;
        Object.keys(pending).forEach(cancel);
      }
      uid = nextUid;
      names.forEach(function (name) { versions[name] = state[name]; });
      return { accepted: true, changed: changed };
    }
    function request(key, path) {
      cancel(key);
      var ticket = { generation: generation, uid: uid, controller: new AbortController() };
      pending[key] = ticket;
      function current() { return pending[key] === ticket && ticket.generation === generation; }
      return api(path, { signal: ticket.controller.signal }).then(function (payload) {
        if (!current()) { return null; }
        if (!Number.isSafeInteger(payload.uid) || !Number.isSafeInteger(payload.version)) {
          throw new Error("账号载荷缺少有效 uid/version");
        }
        if (payload.uid !== ticket.uid || payload.version < versions[fields[key]]) { return null; }
        return payload;
      }).catch(function (err) {
        if (!current() || ticket.controller.signal.aborted) { return null; }
        throw err;
      });
    }
    return { observe: observe, request: request, cancel: cancel,
      petContext: function () { return { uid: uid, version: versions.pets_version, generation: generation }; } };
  }
  window.SpriteLensAccountRequests = { create: create };
})();
