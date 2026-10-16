// 验收探针：执行实际 Vue setup/TS 模块；不修改生产源码，不访问网络。
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const root = path.resolve(__dirname, '../..');
const req = createRequire(path.join(root, 'frontend/package.json'));
const vue = req('vue');
const ts = req('typescript');
const { parse, compileScript } = req('@vue/compiler-sfc');
const source = fs.readFileSync(path.join(root, 'frontend/src/components/EggBoxDetail.vue'), 'utf8');
const compiled = compileScript(parse(source).descriptor, { id: 'acceptance' }).content;
const moduleValue = { exports: {} };
new Function('require', 'module', 'exports', ts.transpileModule(compiled, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText)(name => name === 'vue' ? vue : { default: {} }, moduleValue, moduleValue.exports);
const Component = moduleValue.exports.default;
Component.render = () => null;
const renderer = vue.createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  insert: () => {}, remove: () => {}, setText: () => {}, setElementText: () => {},
  parentNode: () => null, nextSibling: () => null, patchProp: () => {},
});
const egg = (id, nature = 0) => ({ instance_id: id,
  annotations: { nature_id: nature, nest_override: '', note: '', voice_tag: '' } });
const tick = async () => { await vue.nextTick(); await new Promise(resolve => setImmediate(resolve)); };
function mount(save) {
  const host = {};
  let vnode;
  const render = (id, nature = 0) => {
    vnode = vue.h(Component, { uid: 101, egg: egg(id, nature), position: 1, total: 2,
      favoriteSaving: false, natureOptions: [], saveAnnotations: save });
    renderer.render(vnode, host);
    return vnode.component.setupState;
  };
  return { render, state: () => vnode.component.setupState, unmount: () => renderer.render(null, host) };
}
async function targetSwitch(returnToFirst) {
  const saves = [];
  let finish;
  const app = mount((value, uid, id) => {
    saves.push({ uid, id, ...value });
    return saves.length === 1 ? new Promise(resolve => { finish = resolve; }) : Promise.resolve();
  });
  const state = app.render(1);
  state.toggleNature(1);
  if (!returnToFirst) state.toggleNature(2);
  app.render(2, 9); await tick();
  if (returnToFirst) {
    app.render(1); await tick();
    const observedNature = app.state().natureId;
    app.state().note = 'only change note';
    app.state().saveNote();
    finish(); await tick();
    console.log(JSON.stringify({ probe: 'return_to_inflight_egg', expectedNature: 1, observedNature, saves }));
  } else {
    finish(); await tick();
    console.log(JSON.stringify({ probe: 'original_wrong_target', saves }));
  }
  app.unmount();
}
async function failedDraftUnmount() {
  const app = mount(() => Promise.reject(new Error('synthetic disk failure')));
  app.render(1);
  app.state().note = 'unsaved draft'; app.state().saveNote(); await tick();
  const before = { note: app.state().note, error: app.state().annotationError };
  app.unmount(); app.render(1); await tick();
  const after = { note: app.state().note, error: app.state().annotationError };
  console.log(JSON.stringify({ probe: 'failed_draft_after_mobile_detail_reopen', before, after }));
  app.unmount();
}
(async () => { await targetSwitch(false); await targetSwitch(true); await failedDraftUnmount(); })()
  .catch(error => { console.error(error); process.exitCode = 1; });
