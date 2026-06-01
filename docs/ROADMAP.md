# OpenCollect PoC Roadmap

更新日期：2026-06-01

## 目标

这个文档用于追踪 OpenCollect PoC 的后续迭代优先级。判断标准是：这个 PoC 是否能证明用户愿意把小红书内容沉淀到 OpenCollect，并且之后真的会回来找、看、整理。

## 状态约定

- `Done`：已完成并验证。
- `Doing`：当前正在做。
- `Next`：下一阶段优先做。
- `Backlog`：已确认价值，但暂不做。
- `Blocked`：需要外部条件或方案确认。

## 当前已完成

- `Done` 单条小红书链接收藏解析。
- `Done` 收藏页瀑布流。
- `Done` 笔记详情展示。
- `Done` 笔记详情浮层展示。
- `Done` 多图左右切换。
- `Done` 视频播放代理。
- `Done` 详情右上角 `x` 收起。
- `Done` 编辑收藏内容。
- `Done` 删除收藏内容，并支持 toast 撤销。
- `Done` 一键清空收藏，并支持网页内确认和撤销。
- `Done` 清空后的完整空态 UI。
- `Done` 收藏卡片和详情页的平台来源标识。
- `Done` Python FastAPI 后端 + 本地 JSON Store + 收藏 API。
- `Done` 旧 `localStorage` 收藏迁移到后端。
- `Done` 重复收藏识别和定位。
- `Done` 解析失败原因分层。
- `Done` 已收藏内容重新抓取和抓取状态记录。

## 优先级路线

| 优先级 | 方向 | 状态 | 目标 | 验收标准 |
| --- | --- | --- | --- | --- |
| P0 | Python FastAPI 后端 + JSON Store + 收藏 API | Done | 从 `localStorage` 迁移到后端本地 JSON Store，建立稳定 API 边界 | 前端不改即可运行；收藏 CRUD、抓取、图片/视频代理可用；测试通过 |
| P1 | OSS/S3 云同步 | Done | 把本地 JSON 数据文件同步到低成本对象存储，首个目标为腾讯云 COS | 启动时可从云端拉取；写入后可上传；支持备份和同步失败提示 |
| P2 | 解析稳定性、去重、重新抓取 | Done | 让收藏失败原因清楚，重复收藏可识别，旧收藏可刷新元数据 | 重复链接提示已存在；失败原因分层；支持重新抓取并更新标题/媒体/统计 |
| P2.5 | 手动保存并上传 | Backlog | 本地变更先落盘，用户点击后再上传 COS，降低误覆盖和上传频率 | 变更后显示未上传；点击保存并上传后同步 COS；离开页面有提示 |
| P3 | 搜索、筛选、标签整理 | Backlog | 证明收藏系统的“找回来”价值 | 可按标题/正文/作者/标签搜索；可按平台/类型筛选；可编辑标签 |
| P4 | 小红书视觉和交互打磨 | Backlog | 让内容流和详情更接近真实小红书使用感 | 卡片比例基于媒体比例；管理操作更弱化；详情阅读体验更完整 |
| P5 | 批量链接导入和导出 | Backlog | 在不碰账号登录态的前提下提升导入效率 | 支持多链接粘贴导入；展示成功/失败/重复结果；支持 JSON 导出/导入 |
| P6 | 上线底座 | Backlog | 支撑真实域名和多用户使用 | 用户数据隔离；API 限流；日志；备份；基础账号系统 |
| Hold | 绑定个人账号自动导入点赞/收藏 | Blocked | 通过用户账号导入小红书点赞/收藏列表 | 暂不推进；缺少适合普通个人账号的官方授权 API，避免托管用户登录态 |

## P0 拆解：Python FastAPI 后端 + JSON Store + 收藏 API

- [x] `OC-P0-001` 确认 Python + FastAPI + JSON Store 作为后端主方案。
- [x] `OC-P0-002` 定义 `data/collections.json` schema。
- [x] `OC-P0-003` 新增 `uv` + FastAPI + uvicorn 项目配置。
- [x] `OC-P0-004` 实现本地 JSON Store：加载、初始化、原子写、revision。
- [x] `OC-P0-005` 新增收藏列表 API：`GET /api/collections`。
- [x] `OC-P0-006` 新增创建/导入 API：`POST /api/collections/import-local`。
- [x] `OC-P0-007` 新增编辑 API：`PATCH /api/collections/:id`。
- [x] `OC-P0-008` 新增删除 API：`DELETE /api/collections/:id`。
- [x] `OC-P0-009` 新增清空 API：`DELETE /api/collections`。
- [x] `OC-P0-010` 前端从 API 读取和写入，不再以 `localStorage` 为主存储。
- [x] `OC-P0-011` 首次打开时迁移旧 `localStorage` 数据到后端。
- [x] `OC-P0-012` 迁移静态文件服务。
- [x] `OC-P0-013` 迁移小红书抓取解析逻辑。
- [x] `OC-P0-014` 迁移图片代理和视频 Range 代理。
- [x] `OC-P0-015` 增加 Python Store/API 测试。
- [x] `OC-P0-016` 验证 Python 服务下 `/api/sample` 和 `/api/collect` 可用。
- [x] `OC-P0-017` 清理旧 Go 后端源码、Go module 和 Go 缓存。

## P1 拆解：OSS/S3 云同步

- [x] `OC-P1-001` 抽象 `Syncer` 接口：`Pull`、`Push`、`Backup`。
- [x] `OC-P1-002` 实现 `NoopSyncer`。
- [x] `OC-P1-003` 实现 S3-compatible `S3Syncer`，支持 `SYNC_PROVIDER=cos`。
- [x] `OC-P1-004` 启动时从对象存储拉取 `collections.json`。
- [x] `OC-P1-005` 写入后上传最新 `collections.json`。
- [x] `OC-P1-006` 上传前生成云端备份。
- [x] `OC-P1-007` 记录同步状态和失败原因。
- [x] `OC-P1-008` 使用真实腾讯云 COS Bucket 做端到端验证。

## P2 拆解：解析稳定性、去重、重新抓取

- [x] `OC-P2-001` 根据 `sourceUrl` 和 `note.id` 做去重。
- [x] `OC-P2-002` 重复收藏时定位到已有卡片。
- [x] `OC-P2-003` 把解析失败分成：链接无效、缺少 `xsec_token`、平台限制、网络失败、未知错误。
- [x] `OC-P2-004` 增加“重新抓取”按钮，刷新已有收藏的元数据。
- [x] `OC-P2-005` 记录最近一次抓取时间和失败原因。
- [x] `OC-P2-006` 移除 `originVideoKey` 获取链路，不再通过本地 Chrome 调小红书 Web 详情接口补字段。
- [x] `OC-P2-007` 从 Video API schema 移除 `originVideoKey` / `originVideoUrl` 输出。
- [x] `OC-P2-008` 评估并实现结构化视频流字段，例如 `streams[]`、`media.video.bizId`、`mediaV2.video.biz_id` 或 stream path。

## P2.5 拆解：手动保存并上传

- [x] `OC-P2.5-001` 移除写后自动上传，云同步固定为手动上传；本地写入后只标记未上传。
- [x] `OC-P2.5-002` 扩展 `sync-state.json`：记录 `dirty`、`pending_revision`、`last_pushed_revision`、`last_local_change_at`。
- [x] `OC-P2.5-003` 新增 `POST /api/sync/push`，语义化执行“保存并上传”；保留 `/api/sync/retry` 作为兼容入口。
- [x] `OC-P2.5-004` 前端顶部增加“保存并上传”按钮和同步状态：已同步、有本地更改、上传中、上传失败。
- [x] `OC-P2.5-005` 本地变更后通过 `BroadcastChannel` 通知同浏览器其他页面刷新收藏列表和同步状态。
- [x] `OC-P2.5-006` 当存在未上传变更时，刷新、关闭、离开页面触发 `beforeunload` 提示。
- [x] `OC-P2.5-007` 保存并上传成功后清除未上传状态，并展示最近上传时间。
- [x] `OC-P2.5-008` 上传失败时保留未上传状态，展示失败原因并允许再次点击上传。

### P2.5 验收标准

- [x] `AC-P2.5-001` 新增、编辑、删除、清空只写入本地 `data/collections.json`，不会自动上传 COS。
- [x] `AC-P2.5-002` 发生本地变更后，`GET /api/sync/status` 返回 `dirty=true`、`pending_revision=当前 revision`。
- [x] `AC-P2.5-003` 本地变更后，前端显示“有本地更改”状态，并突出显示“保存并上传”按钮。
- [x] `AC-P2.5-004` 点击“保存并上传”会调用 `POST /api/sync/push`，成功后上传主文件和备份文件到 COS。
- [x] `AC-P2.5-005` 上传成功后，状态变为 `dirty=false`、`pending_revision=0`、`last_pushed_revision=当前 revision`。
- [x] `AC-P2.5-006` 上传失败时，本地数据不回滚，状态保留 `dirty=true` 和失败原因，前端允许再次点击上传。
- [x] `AC-P2.5-007` 存在未上传更改时，刷新、关闭或离开页面触发浏览器离开提示。
- [x] `AC-P2.5-008` 同浏览器多页面中，一个页面发生本地变更后，其他页面能自动刷新列表和同步状态。
- [x] `AC-P2.5-009` 同浏览器多页面中，一个页面上传成功后，其他页面能同步显示“已同步”。
- [x] `AC-P2.5-010` `POST /api/sync/retry` 仍可用，并与 `POST /api/sync/push` 行为兼容。
- [x] `AC-P2.5-011` 页面首次加载时会显示当前同步状态，不需要用户先发生写操作。

### P2.5 测试标准

- [x] 后端单测覆盖写后只标记 dirty，不调用 push。
- [x] 后端单测覆盖 `POST /api/sync/push` 成功后清除 dirty。
- [x] 后端单测覆盖 `POST /api/sync/push` 失败后保留 dirty 和错误信息。
- [x] 后端单测覆盖 `/api/sync/status` 不暴露 `SecretId`、`SecretKey`。
- [ ] 前端自动化测试覆盖本地变更后按钮状态变为“保存并上传”。
- [ ] 前端自动化测试覆盖上传成功后按钮和状态恢复为“已同步”。
- [ ] 前端自动化测试覆盖上传失败提示和重试入口。
- [ ] 前端自动化测试覆盖 `beforeunload` 在 dirty 状态下注册提示，在已同步状态下不提示。
- [ ] 浏览器端测试覆盖两个标签页之间的 `BroadcastChannel` 状态刷新。
- [ ] 真实 COS 回归：手动模式下本地变更不会立即改变 COS，点击上传后 COS `collections.json` revision 才更新。

## P2.6 拆解：多页面和冲突防护优化

- [ ] `OC-P2.6-001` 前端写操作携带 `baseRevision`。
- [ ] `OC-P2.6-002` 后端对编辑、删除、清空增加 revision 校验，旧页面提交返回 `409 CONFLICT`。
- [ ] `OC-P2.6-003` 前端收到 `409` 后自动重新拉取收藏，提示“数据已在其他页面更新”。
- [ ] `OC-P2.6-004` 编辑弹窗遇到 `409` 时保留用户输入，但要求基于最新数据重新确认。
- [ ] `OC-P2.6-005` 上传前校验云端 revision 是否等于本地启动时的 base revision，发现云端已变化时阻止覆盖。
- [ ] `OC-P2.6-006` 增加“仍然覆盖云端”和“先拉取云端”两个明确操作。
- [ ] `OC-P2.6-007` 远期支持云端和本地集合级合并：本地新增、云端新增自动合并；同一条编辑冲突保留冲突副本。

## P3 拆解：搜索、筛选、标签整理

- [ ] `OC-P3-001` 增加全文搜索输入。
- [ ] `OC-P3-002` 支持标题、正文、作者、标签搜索。
- [ ] `OC-P3-003` 支持平台筛选。
- [ ] `OC-P3-004` 支持图文/视频筛选。
- [ ] `OC-P3-005` 支持标签编辑和标签筛选。
- [ ] `OC-P3-006` 支持收藏时间、原发布时间排序。

## P4 拆解：视觉和交互打磨

- [ ] `OC-P4-001` 卡片高度改为基于图片/视频真实比例。
- [ ] `OC-P4-002` 卡片管理入口从常驻按钮改为更弱的 `...` 菜单。
- [ ] `OC-P4-003` 平台角标视觉弱化，降低对内容主视觉的干扰。
- [ ] `OC-P4-004` 详情页正文、标签、互动信息继续贴近小红书笔记。
- [ ] `OC-P4-005` 空态、加载态、错误态统一。

## P5 拆解：批量导入和导出

- [ ] `OC-P5-001` 支持多链接粘贴。
- [ ] `OC-P5-002` 增加导入任务进度。
- [ ] `OC-P5-003` 展示成功、失败、重复数量。
- [ ] `OC-P5-004` 支持失败项重试。
- [ ] `OC-P5-005` 支持 JSON 导出。
- [ ] `OC-P5-006` 支持 JSON 导入。

## P6 拆解：上线底座

- [ ] `OC-P6-001` 基础用户系统。
- [ ] `OC-P6-002` 用户收藏数据隔离。
- [ ] `OC-P6-003` API rate limit，尤其是媒体代理。
- [ ] `OC-P6-004` 解析失败和媒体代理失败日志。
- [ ] `OC-P6-005` 数据文件备份和恢复策略。
- [ ] `OC-P6-006` 生产域名部署检查。

## 跟踪规则

1. 每次只把一个方向标记为 `Doing`。
2. 每次迭代开始前，从本文件选择 1 到 3 个任务 ID。
3. 每次迭代结束后，把完成项改成 `[x]`，并更新状态表。
4. 每次迭代结束后，在 `docs/ITERATION_LOG.md` 追加一条记录。
5. 如果发现任务不再成立，不删除，改成 `Blocked` 或在日志里说明原因。
