/* F02：受控网络交错；即使 AbortController 未让旧响应停止，也禁止提交。 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const sandbox = { window: {}, AbortController };
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);

async function run() {
  const calls = [];
  const api = (path, options) => new Promise((resolve, reject) => calls.push({ path, options, resolve, reject }));
  const manager = sandbox.window.SpriteLensAccountRequests.create(api);
  const state = (uid, version) => ({ uid, pets_version: version, egg_box_version: version,
    home_version: version, flower_version: version });
  manager.observe(state(101, 10));
  const oldA = manager.request("egg-box", "/old-a");
  assert.equal(manager.observe(state(202, 11)).changed, true);
  assert.equal(calls[0].options.signal.aborted, true);
  const b = manager.request("egg-box", "/b");
  calls[1].resolve({ uid: 202, version: 11, total: 2 });
  assert.equal((await b).total, 2);
  manager.observe(state(101, 12));
  calls[0].resolve({ uid: 101, version: 99, total: 999 });
  assert.equal(await oldA, null); // A→B→A，uid 相同也必须拒绝旧代次

  const first = manager.request("home", "/first");
  const second = manager.request("home", "/second");
  calls[3].resolve({ uid: 101, version: 12, name: "new" });
  assert.equal((await second).name, "new");
  calls[2].resolve({ uid: 101, version: 99, name: "old" });
  assert.equal(await first, null);

  const mismatch = manager.request("flowers", "/mismatch");
  calls[4].resolve({ uid: 202, version: 99 });
  assert.equal(await mismatch, null);
  const outdated = manager.request("home", "/outdated");
  manager.observe({ ...state(101, 12), home_version: 14 });
  calls[5].resolve({ uid: 101, version: 13 });
  assert.equal(await outdated, null);
  assert.equal(manager.observe({ ...state(202, 12), home_version: 13 }).accepted, false);

  const leave = manager.request("pets", "/leave");
  manager.cancel("pets");
  calls[6].reject(new Error("旧页面网络失败"));
  assert.equal(await leave, null);
  const malformed = manager.request("colors", "/bad-contract");
  calls[7].resolve({ version: 12 });
  await assert.rejects(malformed, /uid\/version/);
  const failure = manager.request("colors", "/failure");
  calls[8].reject(new Error("当前请求失败"));
  await assert.rejects(failure, /当前请求失败/);

  manager.observe({ ...state(101, 12), pets_version: 100, home_version: 14 });
  const independent = manager.request("egg-box", "/independent");
  calls[9].resolve({ uid: 101, version: 12 });
  assert.equal((await independent).version, 12); // 域版本不能用宠物版本代替
}
run().catch(error => { console.error(error); process.exitCode = 1; });
