/* 迁移桥只负责挂载，筛选与配对状态由 Vue 页面持有。 */
(function () {
  "use strict";
  window.SpriteLensBreederLibrary = {
    create: function (host) {
      var page = null, generation = 0;
      function pause() { generation++; if (page) { page.pause(); } }
      return {
        load: function () {
          if (page) { return page.load(); }
          var current = ++generation;
          var root = document.getElementById("breeder-library-root");
          root.textContent = "正在加载筛选配对…";
          return import("/static/vue/entry.js").then(function (module) {
            if (current !== generation) { return; }
            page = module.mountBreederLibrary(root, host);
            return page.load();
          }).catch(function (error) {
            if (current === generation) { root.textContent = "筛选配对启动失败，请切页重试：" + error.message; }
          });
        },
        pause: pause,
        resetAccount: function () { generation++; if (page) { page.resetAccount(); } },
        unmount: function () { pause(); if (page) { page.unmount(); page = null; } }
      };
    }
  };
})();
