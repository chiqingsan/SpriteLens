/* 蛋图鉴页：该页 state/load/render/bind（阶段1.6，自 app.js 抽出的第一刀）。
 *
 * 协作函数（api/query/$/esc/toast）由启动方显式传入，不读取其他页面的
 * 私有状态；主题等跨视图能力经 window.SpriteLensAppearance 消费。
 * 初始化幂等：bind 只执行一次；可筛选加载处理请求乱序（requestId 防旧覆新）。
 */
(function () {
  "use strict";

  var state = { search: "", group: "", egg_type: "", hatch_min_hours: "", built: false, data: null, selected: null };
  var requestId = 0;   // 筛选请求序号：旧响应不得覆盖新结果
  var bound = false;   // 事件绑定幂等：初始化重试不得重复绑定

  /* 蛋卡头像：蛋图标 → 立绘 → 首字，两级 onerror 降级 */
  function eggAvatarHtml(esc, egg) {
    var letter = esc((egg.name || "?").slice(0, 1));
    var fallback = egg.icon_url
      ? "this.onerror=function(){this.remove()};this.src='" + esc(egg.icon_url) + "'"
      : "this.remove()";
    var img = egg.egg_icon_url
      ? '<img src="' + esc(egg.egg_icon_url) + '" alt="" loading="lazy" onerror="' + fallback + '">'
      : (egg.icon_url
        ? '<img src="' + esc(egg.icon_url) + '" alt="" loading="lazy" onerror="this.remove()">'
        : "");
    return '<span class="hb-art">' + letter + img + "</span>";
  }

  function hatchSecondsLabel(seconds) {
    if (!seconds) { return "—"; }
    if (seconds < 3600) { return Math.round(seconds / 60) + " 分钟"; }
    var hours = seconds / 3600;
    return (hours % 1 === 0 ? hours : hours.toFixed(1)) + " 小时";
  }

  function createEggDexPage(context) {
    var api = context.api;
    var query = context.query;
    var $ = context.$;
    var esc = context.esc;
    var toast = context.toast;

    function load() {
      var current = ++requestId;
      return api("/api/eggs" + query({
        search: state.search,
        group: state.group,
        egg_type: state.egg_type,
        hatch_min_hours: state.hatch_min_hours
      })).then(function (payload) {
        if (current !== requestId) { return; }  // 旧响应丢弃
        state.data = payload;
        render(payload);
      }).catch(function (err) {
        if (current !== requestId) { return; }
        toast("蛋图鉴加载失败：" + err.message, true);
      });
    }

    function render(payload) {
      if (!state.built) {
        state.built = true;
        $("ed-group").innerHTML = '<option value="">全部蛋组</option>'
          + (payload.groups || []).map(function (name) {
              return '<option value="' + esc(name) + '">' + esc(name) + "</option>";
            }).join("");
        $("ed-type").innerHTML = '<option value="">全部类型</option>'
          + (payload.egg_types || []).map(function (name) {
              return '<option value="' + esc(name) + '">' + esc(name) + "</option>";
            }).join("");
      }
      $("ed-count").textContent = "收录 " + (payload.shown || 0) + " / " + (payload.total || 0) + " 种蛋";
      $("ed-grid").innerHTML = (payload.eggs || []).map(function (egg) {
        var groups = (egg.egg_group_names || []).map(function (g) {
          return '<span class="skill-chip">' + esc(g) + "</span>";
        }).join(" ");
        return '<article class="hb-card' + (state.selected === egg.egg_conf_id ? " active" : "")
          + '" data-egg="' + egg.egg_conf_id + '" role="button" tabindex="0" aria-label="查看' + esc(egg.egg_name) + '详情">'
          + '<div class="hb-head"><span class="hb-key">' + esc(egg.handbook_no || "—") + "</span>"
          + eggAvatarHtml(esc, egg)
          + "<div><strong>" + esc(egg.egg_name) + "</strong>"
          + "<small>" + esc(egg.name) + "</small></div></div>"
          + '<div class="hb-meta">' + (groups || '<span class="muted">—</span>') + "</div>"
          + '<span class="hb-badge"><svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><use href="/static/icons/sprite.svg#clock"></use></svg> ' + esc(egg.hatch_label || "—") + "</span>"
          + "</article>";
      }).join("");
      $("ed-empty").hidden = (payload.eggs || []).length > 0;
      if (state.selected !== null) { renderDetail(state.selected); }
    }

    function renderDetail(eggConfId) {
      var eggs = (state.data || {}).eggs || [];
      var egg = null;
      for (var i = 0; i < eggs.length; i++) {
        if (eggs[i].egg_conf_id === eggConfId) { egg = eggs[i]; break; }
      }
      var panel = $("ed-detail");
      document.querySelectorAll("#ed-grid [data-egg]").forEach(function (node) {
        node.classList.toggle("active", Number(node.dataset.egg) === Number(eggConfId));
      });
      if (!egg) { panel.innerHTML = '<div class="empty-hint">蛋数据不存在</div>'; return; }

      var seconds = egg.hatch_seconds || 0;
      var speedRows = [["原始", seconds], ["5 倍速", seconds / 5], ["6 倍速", seconds / 6], ["30 倍速", seconds / 30]]
        .map(function (row) {
          return '<div class="speed-row"><span>' + row[0] + '</span><b>' + hatchSecondsLabel(row[1]) + "</b></div>";
        }).join("");
      var male = egg.gender_male || 0, female = egg.gender_female || 0;
      var ring = (male || female)
        ? '<div class="gender-ring" style="background:conic-gradient(var(--male-strong) 0 ' + male + "%, var(--female-strong) " + male + '% 100%)"><b>'
          + (male ? "♂ " + male + "%" : "♀ " + female + "%") + "</b></div>"
        : '<div class="gender-ring unknown"><b>暂无数据</b></div>';
      var chain = (egg.chain || []).map(function (baseId) {
        var member = null;
        for (var j = 0; j < eggs.length; j++) {
          if (eggs[j].base_id === baseId) { member = eggs[j]; break; }
        }
        return '<span class="skill-chip">' + esc((egg.chain_names || {})[baseId] || (member ? member.name : "#" + baseId)) + "</span>";
      }).join('<span class="chain-arrow">→</span>');

      panel.innerHTML =
        '<div class="detail-title"><h2>' + esc(egg.egg_name) + "</h2>"
        + '<span class="muted">#' + esc(egg.egg_conf_id) + "</span></div>"
        + '<div class="detail-sub">' + esc(egg.name)
        + (egg.handbook_no ? " · 图鉴号 " + esc(egg.handbook_no) : "")
        + " · " + esc(egg.egg_type_name || "普通") + "</div>"
        + '<div class="detail-section"><h3>孵化时长</h3>' + speedRows + "</div>"
        + '<div class="detail-section"><h3>公母比例</h3>' + ring + "</div>"
        + window.SpriteLensAppearance.ranges("蛋基础范围", egg.reference_ranges)
        + '<div class="detail-section"><h3>进化链</h3><div class="skill-list">'
        + (chain || '<span class="muted">—</span>') + "</div></div>";
    }

    function bind() {
      if (bound) { return; }
      bound = true;
      var debounced = null;
      $("ed-search").addEventListener("input", function (event) {
        state.search = event.target.value.trim();
        clearTimeout(debounced);
        debounced = setTimeout(load, 220);
      });
      $("ed-group").addEventListener("change", function (event) {
        state.group = event.target.value; load();
      });
      $("ed-type").addEventListener("change", function (event) {
        state.egg_type = event.target.value; load();
      });
      $("ed-hatch").addEventListener("change", function (event) {
        state.hatch_min_hours = event.target.value; load();
      });
      $("ed-grid").addEventListener("click", function (event) {
        var card = event.target.closest("[data-egg]");
        if (!card) { return; }
        state.selected = Number(card.dataset.egg);
        renderDetail(state.selected);
      });
      $("ed-grid").addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") { return; }
        var card = event.target.closest("[data-egg]");
        if (!card) { return; }
        event.preventDefault();
        state.selected = Number(card.dataset.egg);
        renderDetail(state.selected);
      });
    }

    return { load: load, bind: bind };
  }

  window.SpriteLensEggDex = { create: createEggDexPage };
})();
