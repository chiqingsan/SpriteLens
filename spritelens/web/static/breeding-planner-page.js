/* 独立 Vue 规划页；账号/请求仍由原壳提供。 */
(function () {
  "use strict";
  window.SpriteLensBreedingPlanner = {
    create: function (host) {
      var page = null, generation = 0;
      function pause() { generation++; host.cancel(); if (page) { page.pause(); } }
      return {
        load: function () {
          if (page) { return page.load(); }
          var current = ++generation, root = document.getElementById("breeding-planner-root");
          root.textContent = "正在加载智能配窝…";
          return import("/static/vue/entry.js").then(function (module) {
            if (current !== generation) { return; }
            page = module.mountBreedingPlanner(root, host);
            return page.load();
          }).catch(function (error) {
            if (current === generation) { root.textContent = "智能配窝启动失败：" + error.message; }
          });
        },
        pause: pause,
        flush: function () { return page ? page.flush() : Promise.resolve(); },
        resetAccount: function () { pause(); if (page) { page.resetAccount(); } },
        unmount: function () { pause(); if (page) { page.unmount(); page = null; } }
      };
    }
  };
})();
