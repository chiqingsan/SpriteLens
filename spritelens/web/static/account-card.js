/* 账号卡片与本地历史账号切换浮层。 */
(function () {
  "use strict";

  var role = null;
  var concealed = false;
  var api = null;
  var notify = function () {};
  var onState = function () {};
  var selectedUid = 0;
  var pendingUid = 0;
  var accountData = null;
  var switching = false;
  var card = document.getElementById("account-card");
  var information = card.querySelector("details");
  var popover = document.getElementById("account-popover");
  var accountList = document.getElementById("account-list");
  var switchNote = document.getElementById("account-switch-note");
  var switchButton = document.getElementById("btn-account-switch");
  var uid = document.getElementById("role-uid");
  var uidButton = document.getElementById("btn-uid-visibility");
  var avatar = document.getElementById("role-avatar");
  var avatarFallback = document.getElementById("role-avatar-fallback");
  var renderedRoleKey = null;

  function icon(name, className) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", className || "ui-icon");
    svg.setAttribute("aria-hidden", "true");
    var use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "/static/icons/sprite.svg#" + name);
    svg.appendChild(use);
    return svg;
  }

  function maskedUid(value) {
    var text = String(value || "");
    if (text.length <= 5) { return text; }
    return text.slice(0, 3) + "••••" + text.slice(-2);
  }

  function validAvatar(value) {
    var source = String(value || "");
    return /^\/static\/account-avatars\/\d+\.png$/.test(source) ? source : "";
  }

  function logoAvatar() {
    var image = document.createElement("img");
    image.src = "/static/favicon.png";
    image.alt = "";
    return image;
  }

  function showUid() {
    uid.textContent = role ? "UID " + (concealed ? "••••••••" : role.uid) : "UID —";
    uidButton.hidden = !role;
    uidButton.setAttribute("aria-pressed", String(concealed));
    uidButton.setAttribute("aria-label", concealed ? "显示 UID" : "隐藏 UID");
    uidButton.querySelector("use").setAttribute("href", "/static/icons/sprite.svg#" + (concealed ? "eye-off" : "eye"));
  }

  function renderAvatar(node, source) {
    node.replaceChildren();
    var image = document.createElement("img");
    image.alt = "";
    image.referrerPolicy = "no-referrer";
    if (source) {
      image.src = source;
      image.addEventListener("error", function () {
        node.replaceChildren(logoAvatar());
      }, { once: true });
    } else {
      node.appendChild(logoAvatar());
      return;
    }
    node.appendChild(image);
  }

  function updateSwitchButton() {
    var blocked = !accountData || accountData.can_switch === false || switching;
    switchButton.disabled = blocked || Number(pendingUid) === Number(selectedUid);
    switchButton.textContent = switching ? "切换中…" : "切换查看";
    switchNote.hidden = !(accountData && accountData.reason);
    switchNote.textContent = accountData && accountData.reason || "";
  }

  function renderAccountList() {
    accountList.replaceChildren();
    if (!accountData || !accountData.accounts || !accountData.accounts.length) {
      var empty = document.createElement("span");
      empty.className = "muted";
      empty.textContent = "暂无历史账号";
      accountList.appendChild(empty);
      switchButton.disabled = true;
      return;
    }
    var canSwitch = accountData.can_switch !== false && !switching;
    accountData.accounts.forEach(function (profile) {
      var current = Number(profile.uid) === Number(pendingUid);
      var button = document.createElement("button");
      button.type = "button";
      button.className = "account-option" + (current ? " current" : "");
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", String(current));
      button.disabled = !canSwitch && Number(profile.uid) !== Number(selectedUid);
      var profileAvatar = document.createElement("span");
      profileAvatar.className = "account-option-avatar";
      renderAvatar(profileAvatar, validAvatar(profile.avatar_url));
      var copy = document.createElement("span");
      copy.className = "account-option-copy";
      var name = document.createElement("strong");
      name.textContent = profile.name || "未命名账号";
      var detail = document.createElement("small");
      detail.textContent = "Lv" + (profile.level || "—") + " · UID " + maskedUid(profile.uid)
        + ((accountData.live_uids || []).indexOf(profile.uid) >= 0 ? " · 连接已识别" : "");
      copy.appendChild(name);
      copy.appendChild(detail);
      var check = document.createElement("span");
      check.className = "account-option-check";
      check.textContent = Number(profile.uid) === Number(selectedUid) ? "✓" : "";
      button.appendChild(profileAvatar);
      button.appendChild(copy);
      button.appendChild(check);
      button.addEventListener("click", function () {
        pendingUid = Number(profile.uid);
        renderAccountList();
        updateSwitchButton();
      });
      accountList.appendChild(button);
    });
    updateSwitchButton();
  }

  function setAccountData(data) {
    accountData = data || { accounts: [], can_switch: false, reason: "" };
    selectedUid = Number(accountData.selected_uid || selectedUid || 0);
    if (!pendingUid || !accountData.accounts.some(function (item) { return Number(item.uid) === Number(pendingUid); })) {
      pendingUid = selectedUid;
    }
    renderAccountList();
  }

  function loadAccounts() {
    if (!api) { return; }
    accountList.textContent = "正在读取账号…";
    api("/api/accounts").then(setAccountData).catch(function (error) {
      accountList.textContent = "历史账号读取失败";
      updateSwitchButton();
      notify("账号列表加载失败：" + error.message, true);
    });
  }

  function positionPopover() {
    if (!information.open) { return; }
    var cardRect = card.getBoundingClientRect();
    var sidebar = document.querySelector(".sidebar").getBoundingClientRect();
    var narrow = window.matchMedia("(max-width: 760px)").matches;
    popover.style.left = Math.round(narrow ? sidebar.right + 8 : cardRect.left) + "px";
    popover.style.top = Math.round(cardRect.bottom + 8) + "px";
  }

  function selectAccount() {
    if (!api || switching || !pendingUid || Number(pendingUid) === Number(selectedUid)) { return; }
    switching = true;
    updateSwitchButton();
    renderAccountList();
    api("/api/accounts/select", { method: "POST", body: { uid: pendingUid } })
      .then(function (result) {
        switching = false;
        setAccountData(result.accounts);
        information.open = false;
        onState(result.state);
        notify("已切换到「" + ((result.account && result.account.name) || "未命名账号") + "");
      })
      .catch(function (error) {
        switching = false;
        updateSwitchButton();
        renderAccountList();
        notify("账号切换失败：" + error.message, true);
      });
  }

  avatar.addEventListener("error", function () {
    avatar.hidden = true;
    avatarFallback.hidden = false;
  });
  uidButton.addEventListener("click", function () {
    concealed = !concealed;
    showUid();
  });
  information.addEventListener("toggle", function () {
    popover.hidden = !information.open;
    if (information.open) {
      positionPopover();
      loadAccounts();
    }
  });
  switchButton.addEventListener("click", selectAccount);
  document.addEventListener("pointerdown", function (event) {
    if (!card.contains(event.target)) { information.open = false; }
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") { information.open = false; }
  });
  window.addEventListener("resize", positionPopover);

  window.SpriteLensAccountCard = {
    init: function (options) {
      options = options || {};
      api = options.api || null;
      notify = options.notify || notify;
      onState = options.onState || onState;
    },
    render: function (identity, cached) {
      role = identity || cached;
      // 实时 self_info 可能没有名片头像；同一账号的历史缓存仍是可信头像来源。
      var cachedAvatar = identity && cached && Number(identity.uid) === Number(cached.uid) ? cached.avatar_url : "";
      var source = validAvatar(role && role.avatar_url) || validAvatar(cachedAvatar);
      var roleKey = JSON.stringify([role && role.uid, role && role.name, role && role.level, source]);
      if (roleKey === renderedRoleKey) { return; }
      renderedRoleKey = roleKey;
      var name = role ? role.name || "未命名账号" : "尚未识别账号";
      var label = role ? "Lv" + (role.level || "—") : "登录游戏后识别";
      var nameNode = document.getElementById("role-name");
      var labelNode = document.getElementById("role-label");
      if (nameNode.textContent !== name) { nameNode.textContent = name; }
      if (labelNode.textContent !== label) { labelNode.textContent = label; }
      card.classList.toggle("account-empty", !role);
      var previousUid = selectedUid;
      selectedUid = role ? Number(role.uid) : selectedUid;
      if ((avatar.getAttribute("src") || "") !== source) {
        avatar.hidden = !source;
        avatarFallback.hidden = !!source;
        if (source) { avatar.src = source; } else { avatar.removeAttribute("src"); }
      }
      showUid();
      if (information.open && accountData && previousUid !== selectedUid) { renderAccountList(); }
    }
  };
})();
