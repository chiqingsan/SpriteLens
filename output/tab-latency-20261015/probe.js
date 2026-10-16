(() => {
  const records = [];
  const log = value => {
    records.push(value);
    let node = document.getElementById('tab-probe');
    if (!node && document.body) { node = document.createElement('pre'); node.id = 'tab-probe'; node.hidden = true; document.body.append(node); }
    if (node) node.textContent = records.map(item => JSON.stringify(item)).join('\n');
  };
  const round = value => Math.round(value * 100) / 100;
  let clickId = 0;
  let nodeId = 0;
  const nodeIds = new WeakMap();
  const original = window.fetch;
  window.fetch = async (...args) => {
    const start = performance.now(), id = clickId;
    const response = await original(...args);
    const url = new URL(String(args[0]), location.href).pathname;
    if (!url.startsWith('/api/')) return response;
    log({ kind: 'fetch', click: id, url, start: round(start), headersMs: round(performance.now() - start) });
    const json = response.json.bind(response);
    response.json = async () => {
      const decodeStart = performance.now(), value = await json();
      log({ kind: 'json', click: id, url, decodeMs: round(performance.now() - decodeStart), totalMs: round(performance.now() - start) });
      requestAnimationFrame(() => requestAnimationFrame(() => log({ kind: 'responsePaint', click: id, url, totalMs: round(performance.now() - start) })));
      return value;
    };
    return response;
  };
  new PerformanceObserver(list => list.getEntries().forEach(entry => log({ kind: 'longtask', start: round(entry.startTime), ms: round(entry.duration), click: clickId }))).observe({ type: 'longtask', buffered: true });
  document.addEventListener('click', event => {
    const target = event.target.closest('.nav-item, [data-box], #pet-view button');
    if (!target) return;
    const id = ++clickId, start = performance.now();
    log({ kind: 'click', click: id, start: round(start), page: target.dataset.page || '', box: target.dataset.box || '', text: target.textContent.trim() });
    queueMicrotask(() => log({ kind: 'handler', click: id, ms: round(performance.now() - start) }));
    requestAnimationFrame(() => {
      const page = document.querySelector('.page.active');
      log({ kind: 'frame', click: id, ms: round(performance.now() - start), page: page?.id, animation: page ? getComputedStyle(page).animationDuration : null });
      requestAnimationFrame(() => {
        const card = page?.querySelector('article');
        if (card && !nodeIds.has(card)) nodeIds.set(card, ++nodeId);
        log({ kind: 'secondFrame', click: id, ms: round(performance.now() - start),
          cards: page?.querySelectorAll('article').length, firstCard: card ? nodeIds.get(card) : null });
      });
    });
  }, true);
  document.addEventListener('animationend', event => {
    if (event.animationName === 'page-in') log({ kind: 'animationEnd', click: clickId, at: round(performance.now()), durationMs: event.elapsedTime * 1000, cards: event.target.querySelectorAll('article').length });
  }, true);
})();
