/* 账号展示只消费现有快照；UID 可见性是本窗口的局部状态。 */
(function () {
  "use strict";
  var role = null;
  var concealed = false;
  var uid = document.getElementById("role-uid");
  var button = document.getElementById("btn-uid-visibility");
  function showUid() {
    uid.textContent = role ? "UID " + (concealed ? "••••••••" : role.uid) : "UID —";
    button.hidden = !role;
    button.setAttribute("aria-pressed", String(concealed));
    button.setAttribute("aria-label", concealed ? "显示 UID" : "隐藏 UID");
    button.querySelector("use").setAttribute("href", "/static/icons/sprite.svg#" + (concealed ? "eye-off" : "eye"));
  }
  button.addEventListener("click", function () { concealed = !concealed; showUid(); });
  var card = document.getElementById("account-card");
  var information = card.querySelector("details");
  document.addEventListener("pointerdown", function (event) { if (!card.contains(event.target)) { information.open = false; } });
  document.addEventListener("keydown", function (event) { if (event.key === "Escape") { information.open = false; } });
  window.SpriteLensAccountCard = {
    render: function (identity, cached) {
      role = identity || cached;
      document.getElementById("role-name").textContent = role ? role.name || "未命名账号" : "尚未识别账号";
      document.getElementById("role-label").textContent = identity ? "当前账号" : cached ? "本次未确认" : "登录游戏后识别";
      document.getElementById("role-level").textContent = role && role.level ? "角色等级 Lv" + role.level : "暂无角色等级";
      document.getElementById("account-card").classList.toggle("account-empty", !role);
      showUid();
    }
  };
})();
