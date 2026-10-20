# 本地 Wiki 补充资料

状态：当前维护说明。读者：资源维护者、前端和后端开发者。用途：维护离线图鉴资料来源与导入边界；持续验收状态见 ROADMAP 的 F04-U4。

## 内容与身份

基础目录继续使用 species.json、eggs.json，已有数值不被此次导入覆盖。
补充目录 `data/static/wiki_reference.json` 来自 [B 站 Wiki](https://wiki.biligame.com/nrc/首页) 的
`模块:Pets/data/Catalog`、`Skills`、`Learnsets`、`Evolutions`。
2026-10-19 快照包含 633 个来源物种、825 项技能/特性；其中 614 个本地物种通过游戏 ID 与名称核对，
具有 30,390 条学习记录与 614 项特性。其余条目保持缺失，不按相似名称匹配或借用其它形态。
补充数据是第三方资料快照，不是实时游戏状态；页面注明来源、收录日期和原始条目链接。
历史活动保留原日期，不能宣称仍可参与。特殊蛋记录按物种汇集，不冒认当前蛋配置的固定产出。

## 导入与更新

使用 Wiki 的 MediaWiki API 读取上述四个模块的原始 Lua 内容，例如
`/nrc/api.php?action=query&titles=模块:Pets/data/Catalog&prop=revisions&rvprop=content&format=json`，
将 revisions 中的原始内容分别保存为 `wiki-Catalog.txt`、`wiki-Skills.txt`、`wiki-Learnsets.txt`、`wiki-Evolutions.txt`。
网络请求失败时保留已发布快照，不生成空目录替换。

运行 `python tools/import_wiki_reference.py --source <输入目录> --output <暂存输出>/wiki_reference.json`。
导入器只解析数据字面量，不执行 Lua，不添加运行时依赖；来源模块 URL 和原始 SHA-256 写入输出。
先在暂存目录检查来源哈希、条目数量、游戏 ID 冲突、学习表关联与名称匹配，
再将核对后的单个 JSON 发布到 data/static。更新差异应明确匹配/缺失数量变化。
来源原始文件、临时脚本和截图不加入运行包。本机绝对路径不写入来源记录。

## 运行边界

StaticData 持有只读 WikiReference，按游戏 ID 与名称核对后返回补充资料。
`/api/handbook` 和 `/api/eggs` 仅在 `details=1` 时附带 wiki 字段；普通列表不展开技能和来源记录。
蛋目录未记录性别比时，只联查 ID 与名称一致的精灵基础性别比；缺失或形态不符仍显示未知。
Vue 独占详情请求和选择，切页/关闭取消并失效旧请求；加载失败保留当前条目，允许重试。
缺文件表示没有补充数据；损坏的已发布 JSON 暴露加载错误，不静默冒充空目录。
资源随现有 data/static 打包，不改变用户数据、账号、持久化和协议。

验证最小集合：`tests.test_wiki_reference`、`tests.test_eggs`、`tests.test_web_server.HandbookPayloadTest`，
以及前端现有图鉴生命周期回归和 Vue 构建。导入器/身份关联改动需保留必要数据正确性回归；
布局用页面检查，不增加固定 DOM 或像素测试。WebView2/exe 另行实机验收。

## UI 对照与边界

当前版式按蛋神电脑版 1.2.0 的随包 webui 重建，未直接引入其应用脚本。
静态依据为 feature-pages.js 的 566–674 行和 app.css 的 856–918 行最终覆盖；
实际每页 15 条、5×3 卡片、常驻详情和筛选逻辑经提取页面渲染核对。
REA 的静态分析 Evidence ID：`ev_3b62f780d12d060f1d0a08d04b3d87156a4368e1ff649d85ee632ffc5149452b`，
来源树 SHA-256：`706b9391c4e45615d2efbe4df7a0074eb1162773d0b737de4f2c8556a41b4482`；
本次只选择 feature-pages.js 进行语义分析，其它功能不在结论覆盖范围。
运行渲染使用原提取 CSS/渲染函数和本地目录投影，是隔离的页面参考，不代表启动并验证完整蛋神客户端。

详情主体改为连续卡片式呈现；技能、相性、进化条件和特殊蛋来源折叠保留。
不复制参考里未经验证的体型奖牌端点、2%阈值或跨形态取首条规则。
蛋“同乘”只读取 ID/名称匹配的 Wiki can_double_ride，不将可骑乘字段替代同乘，也不把未知值当否。
