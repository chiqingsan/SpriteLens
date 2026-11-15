(function () {
  "use strict";
  var steps = [
    { title: "欢迎使用小洛探探", text: "小洛探探会在本机观察游戏数据。软件默认打开即采集；如果缺少 Npcap，请到设置的「采集与连接」按提示安装。" },
    { title: "先采集，再进入游戏", text: "确认采集已启动后再登录游戏。如果游戏已经登录，请返回登录界面重新进入，以便获取连接所需的数据。" },
    { title: "查看你的游戏数据", text: "侧栏的精灵背包、蛋仓和附近精灵展示采集到的数据。精灵图鉴和蛋图鉴无需采集，也可以直接查询。" },
    { title: "遇到问题时", text: "在侧栏打开「设置」，查看「采集与连接」中的状态和诊断。以后也可以在设置的「关于」中重新查看本引导。" }
  ];
  var dialog, index = 0, pending = false, save, previousFocus, saving = false;
  function render() {
    dialog.querySelector('[data-step]').textContent = '使用引导 ' + (index + 1) + ' / ' + steps.length;
    dialog.querySelector('h2').textContent = steps[index].title;
    dialog.querySelector('[data-copy]').textContent = steps[index].text;
    dialog.querySelector('[data-back]').disabled = index === 0 || saving;
    dialog.querySelector('[data-next]').textContent = index === steps.length - 1 ? '完成' : '下一步';
    dialog.querySelector('[data-next]').disabled = saving;
    dialog.querySelector('[data-skip]').disabled = saving;
  }
  function open() {
    if (dialog.open) { return; }
    previousFocus = document.activeElement;
    index = 0;
    dialog.querySelector('[data-error]').textContent = '';
    render();
    dialog.showModal();
    dialog.querySelector('[data-next]').focus();
  }
  function close() {
    dialog.close();
    if (previousFocus && previousFocus.isConnected) { previousFocus.focus(); }
  }
  async function finish() {
    if (saving) { return; }
    if (!pending) { close(); return; }
    saving = true;
    render();
    dialog.querySelector('[data-error]').textContent = '';
    try {
      await save();
      pending = false;
      close();
    } catch (error) {
      dialog.querySelector('[data-error]').textContent = '保存失败：' + error.message + '。请重试。';
    } finally {
      saving = false;
      render();
    }
  }
  window.SpriteLensOnboarding = {
    initialize: function (isPending, saveCompletion) {
      if (dialog) { return; }
      pending = isPending === true;
      save = saveCompletion;
      dialog = document.createElement('dialog');
      dialog.className = 'onboarding-dialog';
      dialog.setAttribute('aria-labelledby', 'onboarding-title');
      dialog.innerHTML = '<div class="onboarding-content"><p class="onboarding-step" data-step></p><h2 id="onboarding-title"></h2><p class="onboarding-copy" data-copy></p><p class="onboarding-error" data-error role="alert"></p></div><footer><button type="button" class="ghost-button" data-skip>跳过</button><div class="onboarding-actions"><button type="button" class="ghost-button" data-back>上一步</button><button type="button" class="primary-button" data-next>下一步</button></div></footer>';
      document.body.appendChild(dialog);
      dialog.querySelector('[data-back]').addEventListener('click', function () { if (index > 0) { index--; render(); } });
      dialog.querySelector('[data-next]').addEventListener('click', function () { if (index < steps.length - 1) { index++; render(); } else { finish(); } });
      dialog.querySelector('[data-skip]').addEventListener('click', finish);
      dialog.addEventListener('cancel', function (event) { event.preventDefault(); finish(); });
      document.getElementById('btn-onboarding').addEventListener('click', open);
      if (pending) { requestAnimationFrame(open); }
    }
  };
})();
