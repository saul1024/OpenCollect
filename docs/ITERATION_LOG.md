# OpenCollect Iteration Log

这个文档记录每次迭代实际做了什么、验证了什么、下一步建议做什么。路线和任务清单见 `docs/ROADMAP.md`。

## 记录模板

```md
## YYYY-MM-DD - 迭代标题

任务：
- `OC-...`

完成：
- ...

验证：
- ...

遗留问题：
- ...

下一步：
- ...
```

## 2026-06-03 - P6.0 访问保护和生产配置

任务：
- `OC-P6-001`
- `OC-P6-002`
- `OC-P6-003`
- `OC-P6-006`

完成：
- 新增单用户访问口令登录，支持 `AUTH_PASSWORD_HASH` 校验。
- 新增 HMAC 签名 session token，登录后写入 httpOnly cookie，退出时清除 cookie。
- 新增 `/login` 登录页，以及 `/api/auth/login`、`/api/auth/logout`、`/api/auth/session`。
- 新增 auth middleware：`AUTH_ENABLED=true` 时未登录访问主页面跳转 `/login`，未登录访问 API 返回 `401 UNAUTHORIZED`。
- 保护收藏列表、收藏写入、编辑、删除、清空、JSON 导入导出、sync API、媒体代理等既有 API。
- 主应用新增“退出”按钮；前端请求收到 `401` 时跳转登录页。
- 新增生产配置校验：`APP_ENV=production` 时必须启用 auth，且必须提供 `AUTH_PASSWORD_HASH` 和长度足够的 `AUTH_SESSION_SECRET`。
- 开发环境仍可用 `AUTH_ENABLED=false` 直接使用，避免本机默认启动被锁住。
- 输出验收截图：`outputs/p6/p6-auth-login.png`、`outputs/p6/p6-auth-app.png`。

验证：
- `uv run pytest backend/tests/test_auth.py backend/tests/test_api.py`
- Chrome headless 本机 auth-enabled 服务冒烟：未登录 `/` 跳 `/login?next=/`；未登录 `/api/collections` 返回 `401`；错误口令显示“口令错误”；正确口令登录后进入收藏页；刷新后仍保持登录；退出后回到 `/login` 且 API 返回 `401`。

遗留问题：
- 本机已通过响应头检查覆盖生产 cookie `Secure` 标记，但真实 HTTPS、反向代理和公网域名下的 cookie 行为仍需要部署后验收。
- P6.1 的媒体代理 host allowlist、API 限流和 `/api/health` 尚未开始。

下一步：
- 进入 `P6.1`：`OC-P6-004`、`OC-P6-005`、`OC-P6-007`。

## 2026-06-03 - P6 上线底座推进计划

任务：
- P6 工作项梳理

完成：
- 新增 `docs/P6_LAUNCH_PLAN.md`，把 P6 拆成 P6.0 到 P6.3 四个阶段。
- 明确 P6 第一阶段目标：先做可安全上线的单用户版本，不直接展开完整多用户账号系统。
- 固化每轮推进节奏：选定任务 ID、补测试或冒烟、实现、验证、更新文档和日志。
- 把 P6.0 定义为下一轮优先执行范围：访问口令登录、签名 session、保护页面/API、生产配置校验。
- 把媒体代理防滥用、限流、健康检查、部署文档、日志、备份恢复和数据隔离预研分别放入后续轮次。
- 更新 `docs/ROADMAP.md`，把 P6 状态调整为 `Next`，并同步新的任务 ID 和轮次。

验证：
- 文档结构检查：`docs/P6_LAUNCH_PLAN.md` 已覆盖目标、阶段节奏、工作项、验收标准、测试要求和下一轮推荐范围。
- 路线图检查：`docs/ROADMAP.md` 中 P6 拆解与 P6 计划文档一致。

遗留问题：
- 这次只落地计划文档，尚未开始 P6.0 的认证和生产配置实现。

下一步：
- 执行 `P6.0`：`OC-P6-001`、`OC-P6-002`、`OC-P6-003`、`OC-P6-006`。

## 2026-06-02 - P5 第二轮重试和 JSON 导入导出

任务：
- `OC-P5-004`
- `OC-P5-005`
- `OC-P5-006`

完成：
- 批量导入结果中的失败项和暂停项新增“重试”入口，单项重试只重新请求该链接，不重跑已成功或已重复的项。
- 批量统计改为根据每条结果状态重新计算，重试后成功数、失败数、重复数不会漂移。
- 重试继续走现有 `baseRevision` 和本地写入语义：冲突时暂停并提示，不静默覆盖；成功后只标记本地 dirty，不自动上传 COS。
- 新增 `GET /api/collections/export`，导出完整数据文件，包含 `schemaVersion`、`revision`、`updatedAt`、`collections`。
- 新增 `POST /api/collections/import-json`，导入完整 JSON 文件，复用 Store 去重、revision 校验和 sync dirty 标记。
- 前端新增“导出 JSON”和“导入 JSON”按钮；导入前校验 JSON、schema 和 `collections` 字段。
- 非法 JSON 或不支持的导入文件不会请求后端，不改写现有收藏。
- 输出验收截图：`outputs/p5/p5-json-retry-after.png`、`outputs/p5/p5-json-mobile.png`。

验证：
- `node --check public/app.js`
- `node --check public/view-model.js`
- `node --check frontend-tests/view-model.test.mjs`
- `npm run test:frontend`
- `uv run pytest backend/tests/test_api.py backend/tests/test_json_store.py`
- Chrome headless mock 冒烟：失败项重试前调用成功链接 1 次、失败链接 1 次；重试后只额外调用失败链接 1 次，最终成功 2、失败 0。
- Chrome headless mock 冒烟：导出生成 `application/json` 下载，文件名包含 revision。
- Chrome headless mock 冒烟：合法 JSON 导入携带当前 `baseRevision`，非法 JSON 不发起导入请求。
- 移动端 Chrome headless 截图检查：`scrollWidth=390`、`innerWidth=390`，新增工具按钮无横向溢出。

遗留问题：
- 真实rednote批量解析仍可能受平台风控影响；当前策略继续限制为小批次、串行、低频。
- JSON 导入目前采用整体文件导入，不提供字段级冲突合并 UI；旧 revision 冲突会要求用户刷新后重试。

下一步：
- 进入 `P6 上线底座`，或先补 P2.5 中仍未覆盖的前端同步状态自动化测试。

## 2026-06-02 - P5 第一轮批量链接导入

任务：
- `OC-P5-001`
- `OC-P5-002`
- `OC-P5-003`

完成：
- 粘贴框支持从任意分享文本中提取多个 `http` / `https` 链接，不要求用户按固定格式输入。
- 链接可用换行、空格、英文逗号、中文逗号或普通分享文案分隔；尾部常见中文/英文标点会自动剥离。
- 批量导入前生成任务计划：单批最多 20 条，批内重复链接直接标记为重复，不发起请求。
- 批量导入按顺序串行执行，默认每条间隔 2 秒，避免并发打到rednote。
- 导入面板展示总数、完成数、成功数、失败数、重复数、进度条和逐条结果。
- 已收藏过的链接显示为重复，并保留定位已有卡片能力。
- 单条普通失败不阻塞后续链接；遇到平台限制、解析结构变化或连续网络失败时暂停剩余任务。
- 成功导入后沿用现有本地写入语义：更新 revision 和 dirty 状态，但不自动上传 COS。
- 输出验收截图：`outputs/p5/p5-batch-import-after.png`。

验证：
- `node --check public/app.js`
- `node --check public/view-model.js`
- `node --check frontend-tests/view-model.test.mjs`
- `npm run test:frontend`
- `uv run pytest backend/tests/test_xhs_parser.py`
- Chrome headless mock 冒烟：5 条输入得到成功 2、重复 2、失败 1；批内重复没有发起收藏请求。
- Chrome headless mock 冒烟：平台限制后暂停剩余任务，后续链接没有继续请求。

遗留问题：
- `OC-P5-004` 失败项重试仍未实现。
- `OC-P5-005` / `OC-P5-006` JSON 导出和导入仍未实现。
- 真实rednote批量导入仍受平台风控和页面结构变化影响，需要保持小批次、串行、低频策略。

下一步：
- 继续完成 P5 第二轮：失败项重试、JSON 导出和 JSON 导入。

## 2026-06-02 - P4 第二轮详情和状态 UI 打磨

任务：
- `OC-P4-004`
- `OC-P4-005`

完成：
- 详情浮层右侧重排为作者、来源时间、标题正文、标签、互动统计和底部操作，降低操作按钮对阅读区的干扰。
- 详情页保留原文、重新抓取、编辑、删除入口，并把它们收敛到底部操作区。
- 详情页标签继续可点击筛选，正文、标签和互动数据更接近rednote笔记的阅读节奏。
- 新增统一 `state-card` 状态组件，复用到空收藏、搜索无结果、媒体缺失和抓取失败提示。
- 移动端详情底部统计和操作按钮改为两列网格，避免窄屏挤压和横向溢出。
- 输出验收截图：`outputs/p4/p4-detail-after-desktop.png`、`outputs/p4/p4-detail-after-mobile.png`、`outputs/p4/p4-detail-mobile-footer-after.png`、`outputs/p4/p4-state-no-results-after.png`。

验证：
- `node --check public/app.js`
- `node --check public/view-model.js`
- `npm run test:frontend`
- `uv run pytest`
- `uv run python -m compileall backend/app backend/tests`
- Chrome headless 真实页面冒烟：详情可打开；详情 footer 有 4 个操作；统计有 4 项；搜索无结果状态文案正确；桌面和移动端无横向溢出。
- 临时数据目录 Chrome headless 回归：详情页删除后 6 条变 5 条，toast 撤销后恢复 6 条；未触碰真实 `data/collections.json` 或 COS。

遗留问题：
- P4 已完成；真实rednote不同媒体比例、视频和抓取失败样本仍需要后续在新增样本时持续回归。

下一步：
- 进入 `P5 批量链接导入和导出`。

## 2026-06-02 - P4 第一轮视觉和交互打磨

任务：
- `OC-P4-001`
- `OC-P4-002`
- `OC-P4-003`

完成：
- 卡片媒体区改为读取图片或视频真实宽高生成 `--media-ratio`，缺少宽高时使用稳定兜底比例，并限制极端比例对瀑布流的影响。
- 删除卡片上常驻的“重新抓取 / 编辑 / 删除”文字操作区，改为右上角 `...` 菜单。
- `...` 菜单保留重新抓取、编辑、删除能力；点击卡片、编辑、刷新、删除和页面外部区域都会收起菜单。
- 平台角标从高饱和红色弱化为半透明浅色标签，详情页平台标识同步降低视觉权重。
- 保留搜索、筛选、排序、标签筛选、详情浮层、删除和撤销等已有能力。
- 顺带修复移动端顶部操作按钮在窄屏下横向溢出的问题。
- 输出优化前后视觉对比：`outputs/p4/p4-before-after-desktop.png`、`outputs/p4/p4-before-after-mobile.png`。

验证：
- `node --check public/app.js`
- `node --check public/view-model.js`
- `node --check frontend-tests/view-model.test.mjs`
- `npm run test:frontend`
- `uv run pytest`
- `uv run python -m compileall backend/app backend/tests`
- Chrome headless 真实页面冒烟：`...` 菜单默认隐藏且可打开；编辑浮层可打开并关闭菜单；筛选后详情浮层可打开；卡片比例变量生效；平台角标颜色已弱化。
- 临时数据目录 Chrome headless 回归：通过菜单删除后卡片数量减少，toast 撤销后恢复；未触碰真实 `data/collections.json` 或 COS。
- 视觉截图回归：桌面和移动端无明显重叠、溢出或菜单常驻问题。

遗留问题：
- P4 仍保留 `OC-P4-004` 详情页正文、标签、互动信息继续贴近rednote笔记。
- P4 仍保留 `OC-P4-005` 空态、加载态、错误态统一。
- 当前真实样本多为接近 3:4 的图片，比例变化主要体现为去掉旧的下标驱动高度差；横图、超长竖图和更多视频样本后续需要继续回归。

下一步：
- 继续完成 P4 第二轮：详情页阅读体验和状态 UI 统一。

## 2026-06-02 - P3 搜索、筛选、标签整理

任务：
- `OC-P3-001` 到 `OC-P3-006`

完成：
- 收藏页新增搜索、平台筛选、类型筛选、标签筛选和排序工具条。
- 抽出 `public/view-model.js`，统一处理标题/正文/作者/标签全文搜索、平台/类型/标签筛选、标签规范化和收藏时间/原发布时间排序。
- 卡片和详情页的标签改为可点击筛选入口。
- 搜索和筛选结果使用 `当前/全部` 数量展示；无匹配时显示独立空态，不影响原始收藏数据。
- 编辑标签继续走现有 PATCH API，后端会去重、去 `#` / `[话题]`，并标记同步 dirty。
- 顺带修复静态文件服务，禁止 `public/.env` 这类点文件被前端访问。

验证：
- `npm run test:frontend`
- `node --check public/app.js`
- `node --check public/view-model.js`
- `uv run pytest`
- `uv run python -m compileall backend/app backend/tests`
- Chrome headless 真实页面冒烟：初始 5 条卡片，搜索“拌饭”得到 1 条，无结果空态正常，点击标签筛出 1 条，视频筛选得到 0 条，发布时间新到旧首条为“剪掉头发好像整个人变了”。
- 临时数据目录双标签页回归：Tab1 删除后 Tab2 自动变为 1 条，Tab1 撤销后两个标签页都恢复 2 条。

遗留问题：
- P3 仍是前端内存过滤，适合当前 PoC 数据量；后续数据量显著增大时再评估后端查询或索引。
- 当前平台筛选只有 rednote 有真实数据，其他平台仍是后续扩展。

下一步：
- 进入 `P4 rednote视觉和交互打磨` 或 `P5 批量链接导入和导出`。

## 2026-06-01 - P2 解析稳定性、去重和重新抓取

任务：
- `OC-P2-001` 到 `OC-P2-005`
- `OC-P2-008`

完成：
- `POST /api/collect` 改为重复收藏显式返回 `duplicated=true` 和 `existingId`，重复时不写盘、不增加 revision、不覆盖用户编辑内容。
- 收藏去重使用 `id`、`sourceId` 和规范化 `canonicalUrl`，同一rednote笔记的参数差异链接会识别为同一条。
- 解析错误增加稳定 `reason`：`INVALID_LINK`、`MISSING_XSEC_TOKEN`、`NETWORK_FAILED`、`PLATFORM_BLOCKED`、`CONTENT_NOT_FOUND`、`PARSE_SCHEMA_CHANGED`、`UNKNOWN`。
- 新增 `POST /api/collections/{id}/refresh`，支持重新抓取已有收藏；成功时刷新平台字段，保留用户编辑过的标题、正文、标签和原文链接。
- 新增 `fetch` 状态字段，记录最近抓取成功/尝试时间、失败 reason 和失败信息。
- 视频字段新增 `bizId` 和 `streams[]`，保存主播放地址、备用地址、清晰度、编码、尺寸、时长等候选流。
- 前端重复收藏会定位已有卡片；卡片和详情页新增“刷新/重新抓取”；刷新失败保留旧收藏并展示最近失败原因；视频播放会尝试结构化候选流。

验证：
- `uv run pytest`
- `uv run python -m compileall backend/app backend/tests`
- `node --check public/app.js`

验收覆盖：
- 后端测试覆盖重复收藏不新增、不覆盖用户编辑、revision 不变化。
- 后端测试覆盖结构化解析错误 reason。
- 后端测试覆盖重新抓取成功、失败保留旧收藏、刷新冲突返回 `409 CONFLICT`。
- Store 测试覆盖用户编辑字段保留、抓取失败状态持久化。
- 解析器测试覆盖视频候选流入库和 SSR 结构变化 reason。

遗留问题：
- 当前未新增浏览器自动化测试；前端交互通过 JS 语法检查和后端契约测试兜底，后续可补 Playwright 覆盖重复定位、刷新按钮和视频回退。
- 真实rednote可用性仍受平台风控、页面结构和资源链接有效期影响。

## 2026-05-29 - 移除 originVideoKey 获取链路

任务：
- `OC-P2-006`
- `OC-P2-007`

完成：
- 删除rednote Web 详情补充链路，不再启动本地 Chrome 调用 `/api/sns/web/v1/feed` 补充视频字段。
- 删除 `originVideoKey` / `originVideoUrl` 的解析、拼接、测试和环境变量配置。
- 从 Video API schema 移除 `originVideoKey` / `originVideoUrl` 输出字段。
- 移除显式 `websockets` 依赖。

决策：
- 放弃继续获取 `originVideoKey`。当前rednote Web 端不稳定返回该字段，后续视频能力转向保存平台返回的结构化 stream 元数据。

下一步：
- 进入 `OC-P2-008`，评估 `streams[]`、`bizId`、`md5`、`streamType`、码率、分辨率等字段的入库设计。

## 2026-05-29 - rednote视频详情字段探索

任务：
- `OC-P2-006`
- `OC-P2-007`

完成：
- 新增rednote Web 详情补充链路：对缺少 `originVideoKey` 的视频笔记，通过本地 Chrome 页面上下文调用 `/api/sns/web/v1/feed`。
- 后端不硬编码rednote签名算法，复用页面自身 Web 模块发起同站详情请求。
- `normalize_video` 和详情补充逻辑支持从 `originVideoKey` / `origin_video_key` 读取并保存原视频资源 key。
- 显式声明 `websockets` 依赖，避免依赖 uvicorn 的间接安装。

验证：
- 当前本地视频样本 `63f4c1340000000012031a6e` 的 Web 详情接口可请求成功，返回 `media.video.bizId`、`mediaV2.video.biz_id`、`stream.masterUrl`、`backupUrls`、封面帧等字段。
- 当前样本返回体没有字面量 `originVideoKey` / `origin_video_key`。
- 当前 `xhs-pc-web` 静态包中也没有 `originVideoKey` / `origin_video_key` 字符串。
- `.venv/bin/python -m pytest`
- `.venv/bin/python -m compileall backend/app backend/tests`
- `node --check public/app.js`

遗留问题：
- 现有 Web 详情接口已经能补充视频详情，但不能证明当前 Web 端一定下发 `originVideoKey`。
- `bizId`、`mediaV2.video.biz_id`、stream path 看起来更稳定，但它们不是 `originVideoKey`，是否入库需要作为 `OC-P2-008` 单独评估。

下一步：
- 优先完成 P2 的去重、失败原因分层、重新抓取。
- 如果继续打磨视频元数据，先定义 `sourceVideoId` / `sourceVideoBizId` / `streamKey` 这类字段的语义，再进入实现。

## 2026-05-26 - 建立 PoC 追踪文档

任务：
- 建立本地路线图和迭代记录机制。

完成：
- 新增 `docs/ROADMAP.md`，固化 P0 到 P5 的优先级。
- 新增 `docs/ITERATION_LOG.md`，用于持续记录每次迭代。
- 明确账号绑定自动导入暂时搁置，标记为 `Blocked`。

当前 PoC 状态：
- 已支持rednote单条收藏解析。
- 已支持收藏瀑布流和笔记详情。
- 已支持多图切换和视频播放代理。
- 已支持编辑、删除、清空、撤销。
- 已支持清空后空态。
- 已支持平台来源角标。
- 当前主存储仍是浏览器 `localStorage`。

下一步建议：
- 优先做 `P0 后端存储和收藏 API`。
- 第一批任务建议选择：`OC-P0-001` 到 `OC-P0-004`。

## 2026-05-26 - 确认后端存储与云同步方案

任务：
- 明确后端技术选型和低成本云同步方案。

完成：
- 确认后端采用 `Go + Gin`。
- 确认主存储采用本地 `data/collections.json`。
- 确认云同步采用可选 `OSS/S3-compatible` 对象存储。
- 新增 `docs/BACKEND_STORAGE_SYNC_DESIGN.md`，整理完整方案。
- 更新 `docs/ROADMAP.md`，把 P0 从 SQLite 改为 Go 后端 + JSON Store，把 OSS/S3 同步拆到 P1。

方案边界：
- 第一阶段不使用 MySQL/Postgres 云数据库。
- 第一阶段只支持单实例写入，避免多个实例同时覆盖对象存储文件。
- 前端不直接持有对象存储密钥，所有云同步由后端完成。

下一步建议：
- 从 `OC-P0-001` 到 `OC-P0-004` 开始实现 Go 后端骨架和本地 JSON Store。

## 2026-05-27 - 落地 Go 后端 JSON Store 和收藏 API

任务：
- `OC-P0-001` 到 `OC-P0-012`

完成：
- 新增 Go module 和 `cmd/opencollect` 服务入口。
- 新增 Gin API：收藏列表、详情、导入、编辑、删除、清空、收藏解析、图片代理、视频代理。
- 新增本地 JSON Store：启动加载、缺省初始化、并发锁、revision、临时文件写入和原子替换。
- 前端主数据源切换到 `/api/collections`，保留旧 `localStorage` 首次迁移逻辑。
- 编辑、删除、清空和撤销都改为通过后端 API 写入。
- 保留 `server.js` 作为 Node 版本可运行基线，Go 服务可用 `PORT=3001` 并行验证。

验证：
- `node --check public/app.js`
- `node --check server.js`
- `go test ./...`
- `curl` 验证静态文件、列表、导入、编辑、删除、清空 API。
- Headless Chrome 端到端验证旧 `localStorage` 迁移、编辑、删除、删除撤销、清空、清空撤销和空态展示。

遗留问题：
- OSS/S3 云同步还未实现，转入 P1。
- rednote真实页面解析和视频流仍需要用更多真实链接回归；平台结构或风控变化会影响成功率。
- 当前仍是单实例文件写入模型，暂不支持多实例同时写同一个对象存储文件。

下一步：
- 进入 `P1 OSS/S3 云同步`，先实现 `NoopSyncer` 接口和同步状态文件，再接 S3-compatible provider。

## 2026-05-27 - Python FastAPI 后端兼容迁移

任务：
- `OC-P0.5-001` 到 `OC-P0.5-008`

完成：
- 新增 `uv` 项目配置：`pyproject.toml` 和 `uv.lock`。
- 新增 Python 后端目录：`backend/app/`。
- 用 FastAPI 迁移收藏 API、静态文件服务、JSON Store、rednote解析、图片代理和视频代理。
- 保持 `data/collections.json` schema、API 路径和前端响应结构兼容。
- Python 服务可运行在 `3002`，并保持 API 与 JSON schema 兼容。

验证：
- `uv sync`
- `uv run python -m compileall backend/app`
- `uv run pytest`
- `curl` 验证 Python 服务静态首页和 `/api/collections`。
- Node live check 验证 Python API 导入、编辑、删除。
- `/api/sample` 返回多图rednote示例。
- `/api/collect` 实际解析rednote示例并返回 8 张图片，验证后删除临时收藏。

遗留问题：
- 旧 Go 后端在后续清理迭代中移除。
- OSS/S3 云同步仍未实现，继续放在 P1。
- 真实rednote解析仍受平台页面结构和访问限制影响，需要持续回归。

下一步：
- 开始 `P1 OSS/S3 云同步` 的 Python 实现。

## 2026-05-27 - 清理旧 Go 后端

任务：
- `OC-P0-017`

完成：
- 删除旧 Go 服务入口和后端实现目录。
- 删除 Go module 文件和本地 Go 构建/模块缓存。
- 更新 `docs/ROADMAP.md`，将当前后端主线统一为 Python FastAPI。
- 更新 `docs/BACKEND_STORAGE_SYNC_DESIGN.md`，移除当前方案中的旧后端参考路径和运行方式。

验证：
- `uv run pytest`
- `uv run python -m compileall backend/app`
- `node --check public/app.js`
- `curl` 验证 Python 服务仍可访问 `/api/collections`。

遗留问题：
- 历史迭代日志中仍保留旧 Go 方案的实现记录，用于说明演进过程。

下一步：
- 进入 `P1 OSS/S3 云同步` 的 Python 实现。

## 2026-05-27 - 笔记详情改为浮层

任务：
- 收藏页视觉和交互打磨。

完成：
- 移除收藏页右侧常驻详情栏。
- 收藏瀑布流恢复全宽展示。
- 点击收藏卡片后打开详情浮层，保留作者、原文、编辑、删除、关闭、多图轮播、视频展示和统计信息。
- 支持点击遮罩和 `Esc` 关闭详情。

验证：
- `node --check public/app.js`
- Headless Chrome 端到端验证：默认全宽瀑布流、点击卡片打开浮层、轮播下一张/上一张、点击 `x` 关闭并回到瀑布流。

遗留问题：
- 后续可继续把卡片管理入口从常驻 hover 按钮弱化为 `...` 菜单。

## 2026-05-27 - 修复浮层缓存和列表排布

任务：
- 收藏页视觉和交互回归修复。

完成：
- 给 `styles.css` 和 `app.js` 加版本参数，避免浏览器继续使用旧资源导致点击卡片不弹出详情。
- 收藏列表从 CSS 多列纵向填充改为按可用宽度计算列数，并把卡片横向分发到列容器，避免内容一直堆在左侧。
- 保留卡片不同封面比例，继续维持接近rednote的瀑布流观感。

验证：
- `node --check public/app.js`
- Headless Chrome 端到端验证：列表为多列 grid、测试卡片分布到多个横向位置、点击卡片打开浮层、3 图轮播下一张/上一张都可用。
- `uv run pytest`

遗留问题：
- 真正按媒体真实宽高做最短列排布仍放在 `OC-P4-001` 后续处理。

## 2026-05-27 - 接入 COS/S3 云同步骨架

任务：
- `OC-P1-001` 到 `OC-P1-007`

完成：
- 新增 `backend/app/sync/`，实现 `Syncer`、`NoopSyncer`、S3-compatible `S3Syncer` 和同步状态管理。
- 支持 `SYNC_PROVIDER=cos`，并兼容 `COS_*` 和通用 `S3_*` 环境变量。
- 启动时可从对象存储拉取 `collections.json` 并覆盖本地文件。
- JSON Store 本地写入成功后触发云端备份和上传，失败不影响本地 API 操作。
- 新增 `data/sync-state.json` 状态记录，以及 `GET /api/sync/status`、`POST /api/sync/retry`。
- 更新 `docs/BACKEND_STORAGE_SYNC_DESIGN.md` 和 `docs/ROADMAP.md`，把首个云目标明确为腾讯云 COS。

验证：
- `uv run python -m compileall backend/app backend/tests`
- `uv run pytest`
- 单测覆盖启动拉取、写后备份上传、上传失败不影响本地写入。

遗留问题：
- 还没有真实腾讯云 COS Bucket 和密钥，`OC-P1-008` 需要拿到配置后做端到端验证。

补充：
- 后端配置已支持自动读取项目根目录 `.env`，无需用 shell `source .env`。
- 修正 `SYNC_PROVIDER=s3` 时错误优先读取 `COS_*` 的问题，现在会按 provider 决定配置优先级。
- `SYNC_PROVIDER=cos` 时会识别 `<region>` 这类未替换占位符，并在同步状态中记录配置错误。
- 真实腾讯云 COS 私有 Bucket 验证通过：启动拉取成功，`POST /api/sync/retry` 上传成功，并生成 `opencollect/backups/collections-20260528T034614Z-rev23.json`。
- 修复 COS Endpoint 使用 Bucket 专属域名时重复拼接 bucket 的问题。
- 修复 S3/COS 客户端缺少响应状态检查方法的问题。

## 2026-05-28 - 规划手动保存并上传

任务：
- 固化手动上传和多页面一致性讨论结果。

完成：
- 在 `docs/ROADMAP.md` 新增 `P2.5 手动保存并上传`，拆出固定手动上传、同步状态、前端按钮、离开提示、BroadcastChannel 等任务。
- 在 `docs/ROADMAP.md` 新增 `P2.6 多页面和冲突防护优化`，记录 `baseRevision`、`409 CONFLICT`、云端 revision 校验和远期合并策略。
- 在 `docs/BACKEND_STORAGE_SYNC_DESIGN.md` 补充手动模式的数据流、第一版交互、多页面处理和未来优化。

决策：
- 第一版手动模式仍保留本地立即写入，避免刷新和重启丢数据。
- COS 上传改为用户点击“保存并上传”触发。
- 多页面第一版先用 `BroadcastChannel` 自动刷新，复杂冲突检测放到 P2.6。

下一步建议：
- 如果优先做该方向，从 `OC-P2.5-001` 到 `OC-P2.5-004` 开始，先完成后端模式切换和前端按钮闭环。

## 2026-05-28 - 补充 P2.5 验收和测试标准

任务：
- 明确 P2.5 手动保存并上传的验收口径。

完成：
- 在 `docs/ROADMAP.md` 为 P2.5 增加 12 条验收标准，覆盖自动/手动模式、dirty 状态、前端按钮、离开提示、多页面同步、兼容接口和首次加载状态。
- 在 `docs/ROADMAP.md` 为 P2.5 增加测试标准，覆盖后端单测、前端自动化、BroadcastChannel 和真实 COS 回归。
- 在 `docs/BACKEND_STORAGE_SYNC_DESIGN.md` 补充手动模式的后端、前端和真实 COS 验收标准。

下一步建议：
- 实施 P2.5 时按验收标准逐项打勾，优先完成 `AC-P2.5-001` 到 `AC-P2.5-006` 的后端闭环。

## 2026-05-28 - 实施固定手动上传

任务：
- 按“无 auto 模式，统一 manual”执行 P2.5。

完成：
- 后端本地写入后只更新 `sync-state.json` 的 dirty 状态，不再自动推送 COS。
- 新增 `POST /api/sync/push`，保留 `POST /api/sync/retry` 兼容入口。
- 前端增加“保存并上传”按钮、同步状态、离开页面提示和同浏览器多页面刷新。
- 文档移除 `SYNC_MODE=auto|manual` 规划，明确云同步固定为手动上传。

## 2026-06-01 - 实施 P2.6 多页面和冲突防护

任务：
- `OC-P2.6-001` 到 `OC-P2.6-007`

完成：
- 前端所有写操作携带 `baseRevision`，后端对收藏、编辑、删除、清空、导入、重新抓取做 revision 校验。
- 旧页面提交会返回 `409 CONFLICT` 和 `currentRevision`；前端收到后刷新最新数据，编辑弹窗保留草稿。
- 收藏和重新抓取在旧 revision 下会先做本地校验，不再先调用rednote解析。
- `POST /api/sync/push` 上传前拉取云端并比较 `sync-base.json`；云端变化时阻止静默覆盖。
- 本地和云端都是纯新增时自动合并为新 revision；同一条编辑、删除、清空等不可安全合并场景进入 `remote_conflict`。
- 前端在云端冲突时展示“拉取云端”和“覆盖云端”；拉取会备份本地，覆盖会备份远端和本地。
- 更新 `README.md`、`docs/ROADMAP.md`、`docs/BACKEND_STORAGE_SYNC_DESIGN.md` 的 P2.6 行为和验收标准。

验证：
- `uv run pytest`，39 个后端测试通过。
- `uv run python -m compileall backend/app backend/tests`
- `node --check public/app.js`
- 本地服务 `http://127.0.0.1:3002/` 启动成功，`/`、`/api/collections`、`/api/sync/status`、`/api/sample` 冒烟均返回 200。

遗留问题：
- 多设备编辑同一条收藏当前不做字段级合并或冲突副本，按 P2.6 验收口径进入手动“拉取云端 / 覆盖云端”处理。
