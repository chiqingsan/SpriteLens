// 实际 TypeScript composable + 合成载荷；仅用 deferred 控制请求完成顺序。
const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
const { createRequire } = require('node:module');
const root = path.resolve(__dirname, '../..');
const req = createRequire(path.join(root, 'frontend/package.json'));
const ts = req('typescript');
require.extensions['.ts'] = (module, file) => module._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, file);
const { effectScope } = req('vue');
const { useEggBox } = require(path.join(root, 'frontend/src/composables/useEggBox.ts'));
const base = { nature_id: 0, nest_override: '', note: '', voice_tag: '' };
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const tick = () => new Promise(resolve => setImmediate(resolve));
function entry(id, annotations = base) {
  return { instance_id: id, egg_conf_id: 3001001, egg_name: `Egg${id}`, species_name: '',
    chain_names: [], description: '', description_source: '', icon_url: '', fallback_icon_url: '',
    egg_type_name: '', egg_kind: 'regular', egg_group_names: [], hatch_label: '', quantity: 1,
    obtained_at: id, historical: false, hatching: false, hatch_known: false,
    historical_hatching: false, favorite: false, hatch_progress: 0, special_egg_conf_id: 0,
    height_cm: 0, weight_g: 0, home_egg: false, annotations: { ...annotations },
    tags: { nature: '', weight: null, voice: null, medals: [], nest: '' },
    measurement_ranges: { height_cm: null, weight_g: null } };
}
function setup() {
  let uid = 42;
  const stored = new Map([[42, { ...base }], [84, { ...base }]]);
  const requests = [];
  const payload = () => ({ eggs: [entry(1, stored.get(uid))], uid, total: 1, hatching: null,
    historical_hatching: 0, source: 'observed', version: 1, nature_options: [] });
  const host = { load: async () => payload(), cancel() {}, versionChanged() {}, saveFavorite: async () => {},
    saveAnnotations(value) {
      const d = deferred(); requests.push({ value: { ...value }, ...d });
      return d.promise.then(() => { const { uid: target, instance_id, ...annotations } = value; stored.set(target, annotations); });
    } };
  const scope = effectScope();
  const model = scope.run(() => useEggBox(host));
  return { model, host, scope, stored, requests, payload, setUid: value => { uid = value; },
    edit(note) { model.updateAnnotations(uid, 1, { ...base, note }); model.saveAnnotations(uid, 1); },
    shown() { return model.annotationsFor(model.data.value.eggs[0]); } };
}
async function accountQueues() {
  const t = setup(); await t.model.load();
  t.edit('old-1'); t.edit('old-2');
  t.model.resetAccount(); t.setUid(84); await t.model.load();
  t.model.resetAccount(); t.setUid(42); await t.model.load(); t.edit('new-3');
  assert.equal(t.requests.length, 1, '同一目标不能并行创建第二个保存队列');
  t.requests[0].resolve(); await tick();
  assert.equal(t.requests.length, 2);
  assert.equal(t.requests[1].value.note, 'new-3');
  t.requests[1].resolve(); await tick();
  assert.equal(t.stored.get(42).note, 'new-3');
  assert.equal(t.shown().note, 'new-3');
  console.log(JSON.stringify({ probe: 'account_aba_save_queues',
    requests: t.requests.map(r => r.value.note), persisted: t.stored.get(42).note,
    displayed: t.shown().note, expected: 'new-3' }));
  t.scope.stop();
}
async function staleCleanup() {
  const t = setup(); await t.model.load(); const oldRefresh = deferred(); let held = false;
  t.host.load = () => { if (!held) { held = true; return oldRefresh.promise; } return Promise.resolve(t.payload()); };
  t.edit('saved-old'); t.requests[0].resolve(); await tick();
  const oldPayload = t.payload();
  t.model.resetAccount(); await t.model.load(); t.edit('new-draft');
  const before = t.shown().note;
  oldRefresh.resolve(oldPayload); await tick();
  const after = t.shown().note;
  assert.equal(after, 'new-draft');
  t.model.updateAnnotations(42, 1, { ...t.shown(), nature_id: 7 }); t.model.saveAnnotations(42, 1);
  t.requests[1].resolve(); await tick();
  t.requests[2].resolve(); await tick();
  assert.equal(t.stored.get(42).note, 'new-draft');
  console.log(JSON.stringify({ probe: 'stale_refresh_deletes_new_state', before, after,
    expected: 'new-draft', new_save_inflight_at_cleanup: true,
    persistedNoteAfterNatureOnlyEdit: t.stored.get(42).note }));
  t.scope.stop();
}
async function untouchedDraft() {
  const t = setup(); await t.model.load(); t.shown();
  t.stored.set(42, { ...base, nature_id: 7 }); await t.model.load();
  const displayedNature = t.shown().nature_id;
  assert.equal(displayedNature, 7);
  t.model.updateAnnotations(42, 1, { ...t.shown(), note: 'only-note' }); t.model.saveAnnotations(42, 1);
  t.requests[0].resolve(); await tick();
  assert.equal(t.stored.get(42).nature_id, 7);
  console.log(JSON.stringify({ probe: 'untouched_draft_blocks_refresh', remoteNature: 7,
    displayedNature, savedNature: t.stored.get(42).nature_id }));
  t.scope.stop();
}
async function failedDraftRetry() {
  const t = setup(); await t.model.load(); t.edit('retry-me');
  t.requests[0].reject(new Error('synthetic disk failure')); await tick();
  t.model.clearSelection(); t.model.select(t.model.data.value.eggs[0]);
  const retained = t.shown().note === 'retry-me' && t.model.annotationErrorFor(t.model.data.value.eggs[0]) === 'synthetic disk failure';
  t.model.saveAnnotations(42, 1); t.requests[1].resolve(); await tick();
  assert.equal(retained, true);
  assert.equal(t.stored.get(42).note, 'retry-me');
  assert.equal(t.model.annotationErrorFor(t.model.data.value.eggs[0]), '');
  console.log(JSON.stringify({ probe: 'failed_draft_retry', retained,
    persisted: t.stored.get(42).note, errorAfterRetry: t.model.annotationErrorFor(t.model.data.value.eggs[0]) }));
  t.scope.stop();
}
(async () => { await accountQueues(); await staleCleanup(); await untouchedDraft(); await failedDraftRetry(); })().catch(e => { console.error(e); process.exitCode = 1; });
