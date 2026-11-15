(function () {
  "use strict";
  var returnKey = 'spritelens.preview.return';
  var activeKey = 'spritelens.preview.active';
  var preview = new URLSearchParams(location.search).get('debug-preview') === '1';
  function captureReturnUrl() {
    if (!preview) { return; }
    var values = new URLSearchParams(location.hash.slice(1));
    var url = values.get('return');
    if (url) { sessionStorage.setItem(returnKey, url); }
  }
  function initialize(api, token, toast) {
    var enter = document.getElementById('btn-debug-preview');
    var exit = document.getElementById('btn-exit-preview');
    var settingsExit = document.getElementById('btn-exit-preview-settings');
    if (preview) {
      enter.hidden = true;
      exit.hidden = false;
      settingsExit.hidden = false;
      document.getElementById('debug-preview-description').textContent = '当前正在查看临时空数据，退出后返回真实界面。';
      document.getElementById('btn-toggle').hidden = true;
      async function exitPreview() {
        var target = sessionStorage.getItem(returnKey);
        if (!target) { toast('找不到返回地址，请关闭窗口并重新打开软件。', true); return; }
        var result = await window.SpriteLensPrepareClose();
        if (!result.ok) { toast('无法退出预览：' + result.error, true); return; }
        location.replace(target);
      }
      exit.addEventListener('click', exitPreview);
      settingsExit.addEventListener('click', exitPreview);
      return;
    }
    if (sessionStorage.getItem(activeKey) === '1') {
      api('/api/debug-preview/stop', { method: 'POST' }).then(function () {
        sessionStorage.removeItem(activeKey);
      }).catch(function (error) { toast('关闭调试预览失败：' + error.message, true); });
    }
    enter.addEventListener('click', async function () {
      enter.disabled = true;
      var started = false;
      try {
        var result = await window.SpriteLensPrepareClose();
        if (!result.ok) { throw new Error(result.error); }
        var response = await api('/api/debug-preview/start', { method: 'POST' });
        started = true;
        var target = new URL(response.url);
        var returnUrl = new URL(location.href);
        returnUrl.hash = 'token=' + encodeURIComponent(token);
        target.searchParams.set('debug-preview', '1');
        if (document.body.classList.contains('desktop-window')) { target.searchParams.set('desktop', '1'); }
        var fragment = new URLSearchParams(target.hash.slice(1));
        fragment.set('return', returnUrl.href);
        target.hash = fragment.toString();
        sessionStorage.setItem(activeKey, '1');
        location.assign(target.href);
      } catch (error) {
        if (started) {
          try { await api('/api/debug-preview/stop', { method: 'POST' }); }
          catch (cleanupError) { toast('关闭调试预览失败：' + cleanupError.message, true); }
        }
        window.SpriteLensCancelClose();
        enter.disabled = false;
        toast('无法进入调试预览：' + error.message, true);
      }
    });
  }
  window.SpriteLensDebugPreview = { captureReturnUrl: captureReturnUrl, initialize: initialize };
})();
