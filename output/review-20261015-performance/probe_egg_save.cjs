// 一次性审查探针：运行当前 SFC 的 setup，不启动浏览器，不发真实保存请求。
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const root = path.resolve(__dirname, '../..');
const req = createRequire(path.join(root, 'frontend/package.json'));
const { parse, compileScript } = req('@vue/compiler-sfc');
const ts = req('typescript');
const vue = req('vue');
const source = fs.readFileSync(path.join(root, 'frontend/src/components/EggBoxDetail.vue'), 'utf8');
const script = compileScript(parse(source).descriptor, { id: 'audit' });
const code = ts.transpileModule(script.content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const moduleValue = { exports: {} };
// 子组件与模板不参与保存逻辑；保留原 setup 和 Vue 响应式运行时。
new Function('require', 'module', 'exports', code)(
  name => name === 'vue' ? vue : { default: {} }, moduleValue, moduleValue.exports,
);
const Component = moduleValue.exports.default;
Component.render = () => null;
const renderer = vue.createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  insert: () => {}, remove: () => {}, setText: () => {}, setElementText: () => {},
  parentNode: () => null, nextSibling: () => null, patchProp: () => {},
});
const saves = [];
let finishFirst;
const props = {
  egg: { instance_id: 1, annotations: { nature_id: 0, nest_override: '', note: '', voice_tag: '' } },
  position: 1, total: 2, favoriteSaving: false, natureOptions: [],
  saveAnnotations: (value, id) => {
    saves.push({ id, nature_id: value.nature_id });
    return saves.length === 1 ? new Promise(resolve => { finishFirst = resolve; }) : Promise.resolve();
  },
};
const host = {};
const vnode = vue.h(Component, props);
renderer.render(vnode, host);
const state = vnode.component.setupState;
state.toggleNature(1);
state.toggleNature(2);
renderer.render(vue.h(Component, {
  ...props,
  egg: { instance_id: 2, annotations: { nature_id: 0, nest_override: '', note: '', voice_tag: '' } },
}), host);
finishFirst();
setImmediate(() => {
  console.log(JSON.stringify({ probe: 'egg_annotation_target_switch', user_edited_egg: 1, save_targets: saves }));
  renderer.render(null, host);
});
