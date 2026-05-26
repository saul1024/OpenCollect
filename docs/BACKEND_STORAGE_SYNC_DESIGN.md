# OpenCollect 后端存储与云同步方案

更新日期：2026-05-26

## 结论

OpenCollect 下一阶段后端采用：

```txt
Go + Gin
+ 本地 JSON Store
+ 可选 OSS/S3 云同步
+ REST API
+ 单实例部署
```

这个方案优先满足 PoC 阶段的几个目标：

- 成本极低，不依赖云数据库。
- 数据不再只存在浏览器 `localStorage`。
- 前端通过稳定 API 读写收藏，后续存储实现可替换。
- 支持把数据文件同步到 OSS、S3、Cloudflare R2 等对象存储。
- 后端贴合维护者的 Go 技术栈。

## 当前背景

当前 PoC 的后端是 Node.js 原生 `http` 服务，主要负责：

- 静态文件服务。
- 小红书链接解析。
- 图片代理：`GET /api/image`。
- 视频代理：`GET /api/media`。
- 收藏解析：`POST /api/collect`。

当前收藏主数据仍在浏览器 `localStorage`，这会带来：

- 换浏览器或清缓存后数据丢失。
- 无法做云端同步。
- 不适合批量导入和长期积累。
- 后续做用户系统、搜索、同步时需要重构。

## 目标

第一阶段目标不是做复杂后端，而是建立稳定的数据边界：

```txt
前端 UI
  |
  | REST API
  v
Go + Gin 后端
  |
  | 本地读写
  v
data/collections.json
  |
  | 可选同步
  v
OSS/S3/R2
```

前端不再直接把收藏作为主数据写入 `localStorage`。`localStorage` 只用于迁移、临时 UI 状态或后续缓存。

## 非目标

第一阶段暂不做：

- MySQL、Postgres 等云数据库。
- 多实例并发写同一份对象存储文件。
- 用户账号系统。
- 小红书个人账号绑定导入。
- 媒体文件下载归档。
- 复杂全文搜索引擎。

## 技术选型

| 模块 | 选择 | 原因 |
| --- | --- | --- |
| 语言 | Go | 维护者主技术栈；部署简单；适合文件存储、代理和同步任务 |
| API 框架 | Gin | JSON API 开发快；路由、中间件、参数绑定成熟 |
| 主存储 | 本地 JSON 文件 | 成本最低；PoC 足够；便于 OSS 同步 |
| 云同步 | S3-compatible 优先 | 可兼容 AWS S3、Cloudflare R2、部分 OSS/COS 兼容接口 |
| 日志 | `log/slog` | Go 标准库，够用 |
| 配置 | 环境变量 | 简单、部署友好 |
| 部署 | 单实例 Node/Go 服务二选一，目标迁 Go | 避免对象存储写冲突 |

## 目录结构建议

Go 后端可以新增在不破坏现有 Node 版本的目录中：

```txt
cmd/opencollect/
  main.go

internal/
  api/
    router.go
    collections.go
    collect.go
    media.go
  store/
    json_store.go
    model.go
  syncer/
    syncer.go
    noop.go
    s3.go
  xhs/
    parser.go
  media/
    proxy.go
  config/
    config.go

public/
  index.html
  app.js
  styles.css

data/
  collections.json
  sync-state.json
```

迁移时建议保留现有 `server.js` 作为可运行基线，Go 后端逐步接管能力。

## 数据文件结构

本地数据文件：

```txt
data/collections.json
```

建议结构：

```json
{
  "schemaVersion": 1,
  "revision": 1,
  "updatedAt": "2026-05-26T00:00:00.000Z",
  "collections": []
}
```

单条收藏结构：

```json
{
  "id": "internal-id-or-source-id",
  "platform": "xiaohongshu",
  "sourceId": "xhs-note-id",
  "sourceUrl": "https://www.xiaohongshu.com/explore/...",
  "canonicalUrl": "https://www.xiaohongshu.com/explore/...",
  "type": "normal",
  "title": "笔记标题",
  "content": "笔记正文",
  "author": {
    "id": "author-id",
    "name": "作者名",
    "avatar": "https://..."
  },
  "images": [
    {
      "url": "https://...",
      "width": 1080,
      "height": 1440,
      "livePhoto": false
    }
  ],
  "video": null,
  "tags": ["标签"],
  "stats": {
    "likes": "0",
    "collects": "0",
    "comments": "0",
    "shares": "0"
  },
  "sourceCreatedAt": "",
  "sourceUpdatedAt": "",
  "collectedAt": "2026-05-26T00:00:00.000Z",
  "updatedAt": "2026-05-26T00:00:00.000Z",
  "deletedAt": ""
}
```

说明：

- 媒体字段只保存原始 URL 和元数据，不默认下载图片或视频。
- `deletedAt` 预留给软删除。PoC 第一版可以物理删除。
- `revision` 每次写入递增，用于同步和排查覆盖问题。

## 本地 JSON Store 职责

`store.JsonStore` 负责：

- 启动时加载 `data/collections.json`。
- 文件不存在时初始化空数据。
- 文件损坏时返回明确错误，后续可从备份恢复。
- 内存中维护当前数据。
- 用 `sync.RWMutex` 保护并发读写。
- 写入时先写 `.tmp` 文件，再原子替换。
- 每次写入递增 `revision`，更新 `updatedAt`。

写入流程：

```txt
API 请求
  -> 参数校验
  -> store 加锁
  -> 修改内存数据
  -> marshal JSON
  -> 写 collections.json.tmp
  -> rename tmp -> collections.json
  -> store 解锁
  -> 触发云同步
```

## 云同步职责

同步模块抽象为：

```go
type Syncer interface {
    Pull(ctx context.Context) ([]byte, error)
    Push(ctx context.Context, data []byte) error
    Backup(ctx context.Context, data []byte) error
}
```

第一版实现：

- `NoopSyncer`：不开启云同步，只用本地文件。
- `S3Syncer`：兼容 S3/R2/部分 OSS S3-compatible API。

启动流程：

```txt
服务启动
  -> 如果 SYNC_PROVIDER=none，读取本地文件
  -> 如果 SYNC_PROVIDER=s3，先尝试从云端拉取 collections.json
  -> 下载成功：覆盖本地 data/collections.json
  -> 下载失败但本地存在：使用本地文件启动，并记录警告
  -> 两者都不存在：初始化空文件
```

写入同步流程：

```txt
本地写入成功
  -> 上传最新 collections.json 到对象存储
  -> 可选：上传前把旧版本写入 backups/
```

PoC 第一版建议使用“立即上传”，避免最后几秒数据未同步。后续如果写入频率上升，再改为 debounce 合并上传。

## 对象存储路径建议

```txt
opencollect/
  collections.json
  backups/
    collections-2026-05-26T10-30-00Z.json
```

## 配置项

```txt
PORT=3000
DATA_DIR=./data

SYNC_PROVIDER=none

S3_ENDPOINT=
S3_REGION=auto
S3_BUCKET=
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=
S3_OBJECT_KEY=opencollect/collections.json
S3_BACKUP_PREFIX=opencollect/backups/
S3_FORCE_PATH_STYLE=true
```

说明：

- 前端不能持有对象存储 AccessKey。
- 所有云存储写权限只放在后端环境变量中。
- 如果使用阿里 OSS 原生 SDK，可后续新增 `OSS_PROVIDER=aliyun`，不要让业务层依赖具体厂商。

## API 设计

第一版 API：

```txt
GET    /api/collections
GET    /api/collections/:id
POST   /api/collect
PATCH  /api/collections/:id
DELETE /api/collections/:id
DELETE /api/collections
POST   /api/collections/import-local
GET    /api/image?url=...
GET    /api/media?url=...
```

### GET /api/collections

返回收藏列表。

可选查询参数：

```txt
platform=xiaohongshu
type=normal|video
q=关键词
```

第一版可以先只返回全部，搜索筛选放到 P2。

### POST /api/collect

请求：

```json
{
  "input": "小红书分享文本或链接"
}
```

流程：

```txt
识别链接
  -> 解析小红书详情
  -> 标准化 note
  -> upsert 到 JSON Store
  -> 同步云端
  -> 返回收藏对象
```

### PATCH /api/collections/:id

用于编辑标题、正文、标签、原文链接等用户可编辑字段。

### DELETE /api/collections/:id

删除单条收藏。

PoC 第一版可以物理删除。若需要更强撤销，可改为软删除。

### DELETE /api/collections

清空全部收藏。

### POST /api/collections/import-local

用于把旧 `localStorage` 数据迁移到后端。

请求：

```json
{
  "collections": []
}
```

后端负责去重、补默认字段、写入 JSON Store。

## 前端迁移策略

当前前端仍使用 `localStorage`。迁移后：

```txt
页面启动
  -> GET /api/collections
  -> 如果后端为空且 localStorage 有旧数据
  -> POST /api/collections/import-local
  -> 成功后设置 opencollect:migrated:v1=true
```

前端内存仍可保留 `notes` 数组用于渲染，但主数据源变为后端 API。

编辑、删除、清空、撤销：

- 编辑：`PATCH /api/collections/:id`
- 删除：`DELETE /api/collections/:id`
- 清空：`DELETE /api/collections`
- 撤销：PoC 第一版可以前端持有被删除数据，再调用导入/恢复 API

## 小红书解析迁移策略

这是从 Node 迁 Go 的最大不确定点。

建议分阶段：

1. Go 后端先实现静态文件服务、JSON Store、收藏 CRUD API。
2. 小红书解析暂时可保留 Node 版本作为参考或后续迁移。
3. 迁移 Go 版解析时，重点处理 `window.__INITIAL_STATE__` 的提取和结构解析。
4. 媒体代理可较早迁移到 Go，Go 对 Range 转发和流式响应很适合。

如果希望一次性替换 Node 后端，则 Go 版必须同时实现：

- 小红书链接识别。
- 短链跳转解析。
- SSR 数据提取。
- 笔记详情标准化。
- 图片代理。
- 视频 Range 代理。

## 风险和应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| JSON 文件被写坏 | 数据不可读 | `.tmp` 原子写；写前/写后校验；保留备份 |
| 多实例同时写 OSS | 数据覆盖 | 第一阶段只支持单实例；后续引入 ETag/revision 冲突检测 |
| OSS 上传失败 | 云端不是最新 | 本地写入仍成功；记录同步失败；提供手动重试 |
| JSON 文件变大 | 读写变慢 | PoC 可接受；后续拆分文件或迁 SQLite/Postgres |
| 小红书页面结构变化 | 解析失败 | 错误分层；保留重新抓取；记录失败原因 |
| AccessKey 泄露 | 云端数据风险 | 只放后端环境变量；前端永不直连 OSS 写接口 |

## 实施计划

第一轮：

- `OC-P0-001` 确认 Go + Gin + JSON Store 作为后端主方案。
- `OC-P0-002` 定义 `collections.json` schema。
- `OC-P0-003` 初始化 Go 后端骨架和 Gin 路由。
- `OC-P0-004` 实现本地 JSON Store。

第二轮：

- `OC-P0-005` 实现 `GET /api/collections`。
- `OC-P0-006` 实现 `POST /api/collections/import-local`。
- `OC-P0-007` 实现 `PATCH /api/collections/:id`。
- `OC-P0-008` 实现 `DELETE /api/collections/:id`。
- `OC-P0-009` 实现 `DELETE /api/collections`。

第三轮：

- `OC-P0-010` 前端改为 API 读写。
- `OC-P0-011` localStorage 迁移到 JSON Store。
- `OC-P0-012` 验证编辑、删除、清空、撤销、平台角标。

第四轮：

- `OC-P1-001` 抽象 `Syncer` 接口。
- `OC-P1-002` 实现 `NoopSyncer`。
- `OC-P1-003` 实现 S3-compatible `S3Syncer`。
- `OC-P1-004` 启动时从对象存储拉取。
- `OC-P1-005` 写入后上传对象存储。
- `OC-P1-006` 上传前生成云端备份。
- `OC-P1-007` 记录同步状态和失败原因。

## 最终判断

这个方案牺牲了数据库的强查询能力，但换来最低成本和最快可落地的云同步能力。对当前 PoC 来说是合理的。

后续如果收藏数量、查询复杂度或多用户需求上来，可以平滑迁移：

```txt
JSON Store -> SQLite -> Postgres/MySQL
```

由于前端只依赖 REST API，存储层替换不会要求前端大改。
