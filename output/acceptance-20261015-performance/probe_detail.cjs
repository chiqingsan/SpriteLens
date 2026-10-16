// 用实际 TypeScript 模块校验实际 Python 载荷与详情乱序，不修改源码。
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const root = path.resolve(__dirname, '../..');
const req = createRequire(path.join(root, 'frontend/package.json'));
const ts = req('typescript');
require.extensions['.ts'] = (module, file) => module._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, file);
const { parsePets, parsePetDetail } = require(path.join(root, 'frontend/src/types/pets.ts'));
const { usePets } = require(path.join(root, 'frontend/src/composables/usePets.ts'));
const payload = JSON.parse(fs.readFileSync(path.join(__dirname, 'backend-contract-known.json'), 'utf8'));
const queue = [];
const model = usePets(() => new Promise(resolve => queue.push(resolve)),
  () => ({ uid: 101, version: 10, generation: 1 }), () => ({}), () => {}, () => {});
(async () => {
  model.activate(); model.accept(parsePets(payload.summary));
  model.selected.value = 1; const first = model.loadDetail(1);
  model.selected.value = 2; const second = model.loadDetail(2);
  queue[1](payload.details[1]); await second;
  queue[0](payload.details[0]); await first;
  const order = model.detail.value?.gid;
  model.selected.value = 1; const third = model.loadDetail(1);
  model.resetAccount(); queue[2](payload.details[0]); await third;
  let unknownBackpackError = '';
  try { parsePets(JSON.parse(fs.readFileSync(path.join(__dirname, 'backend-contract.json'), 'utf8')).summary); }
  catch (error) { unknownBackpackError = error.message; }
  const runtime = path.join(root, 'spritelens/web/static/vue');
  const manifest = JSON.parse(fs.readFileSync(path.join(runtime, '.vite/manifest.json'), 'utf8'));
  const bundle = fs.readFileSync(path.join(runtime, manifest['src/main.ts'].file), 'utf8');
  const ast = ts.createSourceFile('runtime.js', bundle, ts.ScriptTarget.Latest);
  const functions = ast.statements.filter(ts.isFunctionDeclaration);
  const runtimeParser = functions.find(node => node.getText(ast).includes('宠物列表数据格式不正确'));
  let runtimeParserError = '';
  try {
    new Function('value', functions.map(node => node.getText(ast)).join('\n') + `\nreturn ${runtimeParser.name.text}(value);`)(payload.summary);
  } catch (error) { runtimeParserError = error.message; }
  console.log(JSON.stringify({ probe: 'pet_detail_source_contract', summary_count: model.data.value?.pets.length ?? payload.summary.pets.length,
    details_valid: payload.details.every(value => !!parsePetDetail(value)), wrong_uid_status: payload.wrong_uid_status,
    latest_selection_after_reordering: order, stale_detail_after_account_reset: model.detail.value,
    summary_has_stats: 'stats' in payload.summary.pets[0], unknownBackpackError, runtimeParserError }));
})().catch(error => { console.error(error); process.exitCode = 1; });
