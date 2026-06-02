# OpenCollect

OpenCollect 是一个 UGC 内容收藏 PoC，目前优先支持rednote笔记收藏。目标是把分享链接解析成结构化收藏卡片，并在 Web 端提供接近rednote笔记的浏览体验。

当前主实现是 Python FastAPI 后端 + 静态前端 + 本地 JSON Store，并支持腾讯云 COS / S3-compatible 对象存储的手动云同步。

## 功能

- rednote分享文本或链接收藏
- 收藏瀑布流展示
- 标题、正文、作者、标签搜索
- 平台、类型、标签筛选
- 收藏时间和原发布时间排序
- 笔记详情浮层
- 多图轮播切换
- 视频播放、进度条和 Range 代理
- 编辑、删除、清空收藏
- 删除和清空后的 toast 撤销
- 重复收藏识别和定位
- 重新抓取已有收藏
- 解析失败原因分层提示
- 平台角标
- 本地 JSON 持久化
- COS/S3 手动保存并上传
- 多页面旧版本写入冲突防护
- 云端和本地纯新增自动合并
- 页面离开时提示未上传变更

## 技术栈

- Backend: Python 3.12, FastAPI, uvicorn, httpx, pydantic
- Frontend: 原生 HTML/CSS/JavaScript
- Storage: `data/collections.json`
- Cloud Sync: Tencent COS / S3-compatible API
- Tooling: uv, pytest

## 目录结构

```text
backend/
  app/
    api/        # REST API
    core/       # 配置加载
    media/      # 图片和视频代理
    store/      # JSON Store 和数据模型
    sync/       # COS/S3 同步
    xhs/        # rednote解析
  tests/        # 后端测试
data/           # 本地运行时数据，默认不提交
docs/           # 方案、路线图、迭代日志
public/         # Web 前端
```

## 本地启动

安装依赖：

```bash
uv sync
```

启动服务：

```bash
uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 3002
```

如果 `3002` 已被占用，可以换端口：

```bash
uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 3004
```

打开：

```text
http://127.0.0.1:3002/
```

FastAPI 会同时托管 `public/` 前端和 `/api/*` 后端接口。

## 配置

复制示例配置：

```bash
cp .env.example .env
```

默认本地模式不需要云配置：

```text
SYNC_PROVIDER=none
```

腾讯云 COS 示例：

```text
SYNC_PROVIDER=cos
COS_ENDPOINT=https://cos.<region>.myqcloud.com
COS_REGION=<region>
COS_BUCKET=<bucket>-<appid>
COS_SECRET_ID=<secret-id>
COS_SECRET_KEY=<secret-key>
COS_OBJECT_KEY=opencollect/collections.json
COS_BACKUP_PREFIX=opencollect/backups/
```

`.env` 已被 `.gitignore` 忽略，不要提交真实密钥。

## 数据同步

当前云同步是固定手动模式：

1. 新增、编辑、删除、清空会立即写入本地 `data/collections.json`。
2. 本地变更后，`data/sync-state.json` 会标记 `dirty=true`。
3. 前端显示“保存并上传”。
4. 用户点击后才会上传到 COS，并生成备份对象。

这可以避免每次本地整理都立刻覆盖云端数据。

写操作会携带当前 `baseRevision`。如果页面基于旧数据提交，后端返回 `409 CONFLICT` 和最新 revision，前端会刷新数据并提示重新确认。上传前也会比较云端 revision：本地和云端都只是新增不同收藏时会自动合并；同一条数据被改动或涉及删除、清空时会进入“云端冲突”，需要选择“拉取云端”或“覆盖云端”。

## 常用接口

```text
GET    /api/collections
GET    /api/collections/{id}
POST   /api/collect
PATCH  /api/collections/{id}
POST   /api/collections/{id}/refresh
DELETE /api/collections/{id}
DELETE /api/collections
POST   /api/sync/push
POST   /api/sync/pull
GET    /api/sync/status
GET    /api/image?url=...
GET    /api/media?url=...
```

## 测试

后端测试：

```bash
uv run pytest
```

Python 编译检查：

```bash
uv run python -m compileall backend/app backend/tests
```

前端语法检查：

```bash
node --check public/app.js
```

## 安全注意

- 不要提交 `.env`。
- 不要提交 `data/*.json`，其中可能包含收藏数据、原文链接、临时 token 或媒体 URL。
- 不要提交 `outputs/` 下的调试截图。
- COS Secret 只应存在后端环境变量中，不能暴露给前端。

## 当前限制

- 当前 PoC 首批只支持rednote。
- rednote页面结构和访问策略可能变化，解析成功率依赖平台返回的 SSR 数据。
- Web 端媒体访问可能需要后端代理，线上部署后会产生一定服务器带宽成本。
- 多设备编辑同一条收藏时当前不做字段级合并，系统会要求用户选择拉取云端或覆盖云端。

更多设计细节见：

- `docs/BACKEND_STORAGE_SYNC_DESIGN.md`
- `docs/ROADMAP.md`
- `docs/ITERATION_LOG.md`
