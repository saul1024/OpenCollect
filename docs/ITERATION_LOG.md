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

## 2026-06-01 - P2 解析稳定性、去重和重新抓取

任务：
- `OC-P2-001` 到 `OC-P2-005`
- `OC-P2-008`

完成：
- `POST /api/collect` 改为重复收藏显式返回 `duplicated=true` 和 `existingId`，重复时不写盘、不增加 revision、不覆盖用户编辑内容。
- 收藏去重使用 `id`、`sourceId` 和规范化 `canonicalUrl`，同一小红书笔记的参数差异链接会识别为同一条。
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
- 真实小红书可用性仍受平台风控、页面结构和资源链接有效期影响。

## 2026-05-29 - 移除 originVideoKey 获取链路

任务：
- `OC-P2-006`
- `OC-P2-007`

完成：
- 删除小红书 Web 详情补充链路，不再启动本地 Chrome 调用 `/api/sns/web/v1/feed` 补充视频字段。
- 删除 `originVideoKey` / `originVideoUrl` 的解析、拼接、测试和环境变量配置。
- 从 Video API schema 移除 `originVideoKey` / `originVideoUrl` 输出字段。
- 移除显式 `websockets` 依赖。

决策：
- 放弃继续获取 `originVideoKey`。当前小红书 Web 端不稳定返回该字段，后续视频能力转向保存平台返回的结构化 stream 元数据。

下一步：
- 进入 `OC-P2-008`，评估 `streams[]`、`bizId`、`md5`、`streamType`、码率、分辨率等字段的入库设计。

## 2026-05-29 - 小红书视频详情字段探索

任务：
- `OC-P2-006`
- `OC-P2-007`

完成：
- 新增小红书 Web 详情补充链路：对缺少 `originVideoKey` 的视频笔记，通过本地 Chrome 页面上下文调用 `/api/sns/web/v1/feed`。
- 后端不硬编码小红书签名算法，复用页面自身 Web 模块发起同站详情请求。
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
- 已支持小红书单条收藏解析。
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
- 小红书真实页面解析和视频流仍需要用更多真实链接回归；平台结构或风控变化会影响成功率。
- 当前仍是单实例文件写入模型，暂不支持多实例同时写同一个对象存储文件。

下一步：
- 进入 `P1 OSS/S3 云同步`，先实现 `NoopSyncer` 接口和同步状态文件，再接 S3-compatible provider。

## 2026-05-27 - Python FastAPI 后端兼容迁移

任务：
- `OC-P0.5-001` 到 `OC-P0.5-008`

完成：
- 新增 `uv` 项目配置：`pyproject.toml` 和 `uv.lock`。
- 新增 Python 后端目录：`backend/app/`。
- 用 FastAPI 迁移收藏 API、静态文件服务、JSON Store、小红书解析、图片代理和视频代理。
- 保持 `data/collections.json` schema、API 路径和前端响应结构兼容。
- Python 服务可运行在 `3002`，并保持 API 与 JSON schema 兼容。

验证：
- `uv sync`
- `uv run python -m compileall backend/app`
- `uv run pytest`
- `curl` 验证 Python 服务静态首页和 `/api/collections`。
- Node live check 验证 Python API 导入、编辑、删除。
- `/api/sample` 返回多图小红书示例。
- `/api/collect` 实际解析小红书示例并返回 8 张图片，验证后删除临时收藏。

遗留问题：
- 旧 Go 后端在后续清理迭代中移除。
- OSS/S3 云同步仍未实现，继续放在 P1。
- 真实小红书解析仍受平台页面结构和访问限制影响，需要持续回归。

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
- 保留卡片不同封面比例，继续维持接近小红书的瀑布流观感。

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
