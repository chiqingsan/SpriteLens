const root = document.getElementById('radar-root');
const token = new URLSearchParams(location.hash.slice(1)).get('token');
history.replaceState(null, '', location.pathname);
const channel = new BroadcastChannel('spritelens-nearby-' + token);
const queuedMessages = [];
let mounted = false;
let started = false;
function queueMessage(event) {
  if (!mounted) { queuedMessages.push(event); }
}
channel.addEventListener('message', queueMessage);
function showFailure(message) {
  if (mounted) { return; }
  const box = document.createElement('p');
  box.setAttribute('role', 'alert');
  box.style.cssText = 'margin:16px;padding:12px;border-radius:6px;background:var(--danger-soft);color:var(--danger-ink);line-height:1.6;font-size:13px;';
  box.textContent = message;
  root.replaceChildren(box);
  root.dataset.ready = '';
}
const startTimeout = setTimeout(() => {
  if (!started) { showFailure('雷达初始化超时，请重新打开悬浮雷达'); }
}, 8000);
function waitForStyles() {
  const vueStyles = [...document.querySelectorAll('link[rel="stylesheet"]')]
    .filter(link => link.href.includes('/static/vue/'));
  return Promise.all(vueStyles.map(link => new Promise(resolve => {
    link.addEventListener('load', resolve, { once: true });
    link.addEventListener('error', resolve, { once: true });
    if (link.sheet?.cssRules.length) { resolve(); }
  })));
}
async function start() {
  try {
    await waitForStyles();
    const { mountFloatingRadar } = await import('/static/vue/radar-entry.js');
    /* 入口加载后才注入 Vue 样式链接，等它们就绪再挂载，避免未样式化的布局闪烁。 */
    await waitForStyles();
    if (started) { return; }
    started = true;
    clearTimeout(startTimeout);
    const ready = window.pywebview?.api ? Promise.resolve() : new Promise(resolve => window.addEventListener('pywebviewready', resolve, { once: true }));
    mountFloatingRadar(root, channel, {
      close: async () => { await ready; return window.pywebview.api.close_radar(); },
      setOpacity: async percent => { await ready; return window.pywebview.api.set_radar_opacity(percent); }
    });
    root.dataset.ready = '';
    mounted = true;
    channel.removeEventListener('message', queueMessage);
    for (const event of queuedMessages) { channel.onmessage?.(event); }
    queuedMessages.length = 0;
  } catch (error) {
    clearTimeout(startTimeout);
    const detail = error && error.message ? `：${error.message}` : '';
    showFailure(`雷达初始化失败，请重新打开悬浮雷达${detail}`);
  }
}
start();
