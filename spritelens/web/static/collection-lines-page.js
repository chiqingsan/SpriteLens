/* 迁移期页面装配；产线状态、请求代次和渲染归 Vue 所有。 */
(function () {
  "use strict";
  window.SpriteLensCollectionLines = {
    create: function (host) {
      var page = null, generation = 0;
      function pause() { generation++; if (page) { page.pause(); } }
      return {
        load: function () {
          if (page) { return page.load(); }
          var current = ++generation;
          var root = document.getElementById("collection-lines-root");
          root.textContent = "正在加载双牌产线…";
          return import("/static/vue/entry.js").then(function (module) {
            if (current !== generation) { return; }
            page = module.mountCollectionLines(root, host);
            return page.load();
          }).catch(function (error) {
            if (current === generation) { root.textContent = "产线页面启动失败，请切页重试：" + error.message; }
          });
        },
        pause: pause,
        resetAccount: function () { generation++; if (page) { page.resetAccount(); } },
        unmount: function () { pause(); if (page) { page.unmount(); page = null; } }
      };
    }
  };
})();
