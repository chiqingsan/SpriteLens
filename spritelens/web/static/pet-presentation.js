/* 官方头像与独立色卡展示。粒子由采集数据决定，不模拟抽取概率。 */
(function () {
  "use strict";
  function esc(value) { var node = document.createElement("span"); node.textContent = value == null ? "" : value; return node.innerHTML; }
  function avatar(pet, klass) {
    var artwork = window.SpriteLensAppearance.imageMode() === "artwork";
    // 头像缺失保留首字，不把全身图冒充头像。立绘可回退已有本地小图。
    var url = artwork ? pet.artwork_url || pet.icon_url : pet.portrait_url;
    return '<span class="' + klass + ' pet-image' + (artwork ? ' is-artwork' : '') + '"><span aria-hidden="true">'
      + esc((pet.name || "?").slice(0, 1)) + '</span>' + (url ? '<img src="' + esc(url) + '" alt="" loading="lazy" onerror="this.remove()">' : '') + '</span>';
  }
  function colorCard(card) {
    if (!card) { return ""; }
    var id = String(card.card_id), label = card.name + ' · ' + card.particle_name;
    var special = /^(s[1-4]|1000)$/.test(id);
    var content;
    if (special) {
      content = '<img src="/static/color-cards/' + id + '.png" alt="" onerror="this.remove()">';
    } else {
      if (!/^#[0-9a-f]{6}$/i.test(card.base_color) || !/^#[0-9a-f]{6}$/i.test(card.mix_color)) { return ""; }
      content = '<svg viewBox="0 0 100 60" preserveAspectRatio="none" aria-hidden="true"><rect width="100" height="60" fill="' + card.mix_color
        + '"></rect><path d="M0 30 Q25 12 50 30 T100 30 V60 H0 Z" fill="' + card.base_color + '"></path></svg>';
      var pattern = { 1: "sparkle_four", 2: "heart", 3: "diamond", 4: "star_outline" }[card.particle_id];
      if (pattern) { content += '<img src="/static/color-cards/pattern_' + pattern + '.png" alt="" onerror="this.remove()">'; }
    }
    return '<span class="pet-color-card" role="img" aria-label="' + esc(label) + '" title="' + esc(label) + '">' + content + '</span>';
  }
  function rarity(pet) {
    if (!pet.is_shiny && !pet.is_colorful) { return ""; }
    var kind = pet.is_colorful ? (pet.is_shiny ? "shiny-colorful" : "colorful") : "shiny";
    var id = (pet.color_card || {}).card_id;
    if (pet.is_colorful && /^(s[1-4]|1000)$/.test(String(id))) { kind = (id === "1000" ? "blackwhite" : id) + "-" + kind; }
    var label = (pet.is_shiny ? "异色" : "") + (pet.is_colorful ? "炫彩" : "");
    return '<span class="pet-rarity" title="' + label + '"><img src="/static/rarity/' + kind + '-fit.png" alt="' + label + '" onerror="this.replaceWith(document.createTextNode(this.alt))"></span>';
  }
  function medal(pet, slots) {
    var marks = pet.medal_marks || [];
    function tag(mark) {
      if (!mark) { return ''; }
      var id = { "大": 1001, "小": 1002, "粗": 1025, "婉": 1026 }[mark.label];
      return '<span class="pet-medal' + (id ? ' has-icon' : '') + '" title="' + esc(mark.name + (mark.source === "reference" ? " · 体型/声音参考标记" : " · 当前佩戴")) + '"><span>' + esc(mark.label) + '</span>'
        + (id ? '<img src="/static/medals/' + id + '.png" alt="' + esc(mark.name) + '" onerror="this.parentNode.classList.remove(\'has-icon\');this.remove()">' : '') + '</span>';
    }
    return slots ? ["大小", "粗婉"].map(function (group) {
      return '<span class="point-medal-slot">' + tag(marks.find(function (mark) { return group.indexOf(mark.label) !== -1; })) + '</span>';
    }).join("") : marks.map(tag).join("");
  }
  window.SpriteLensPetPresentation = { avatar: avatar, colorCard: colorCard, rarity: rarity, medal: medal };
})();
