# P6 Launch Plan

更新日期：2026-06-03

## 目标

P6 的目标不是一次性做完整 SaaS，而是把当前 PoC 推进到“可以安全放到公网给自己使用”的状态。

核心判断标准：

- 公开域名下，未授权用户不能访问收藏数据或调用写入 API。
- `/api/collect`、媒体代理、批量导入、JSON 导入不会被公开滥用。
- 生产环境配置错误时能明确阻止或提示，避免裸奔上线。
- 数据仍沿用当前本地 JSON + COS 手动同步模型，不在 P6 第一轮引入数据库或完整多用户系统。

## 阶段节奏

每轮只推进 2 到 4 个任务 ID，避免认证、限流、部署和数据隔离同时铺开。

每轮固定流程：

1. 选定本轮任务 ID，确认验收标准。
2. 先补后端契约测试或浏览器冒烟用例。
3. 实现最小可验证功能。
4. 运行 `node --check`、`npm run test:frontend`、`uv run pytest`、`compileall`。
5. 需要 UI 的轮次输出桌面和移动端截图。
6. 更新 `docs/ROADMAP.md` 和 `docs/ITERATION_LOG.md`。

每轮完成门槛：

- 本轮验收标准全部通过。
- 新增配置、API、UI 都有测试或冒烟证据。
- 没有遗留运行中的测试服务或临时浏览器进程。
- 不把未完成的后续任务标记为 Done。

## P6.0：访问保护和生产配置

目标：先阻止公网裸访问。

任务：

- `OC-P6-001` 新增单用户访问口令登录。
- `OC-P6-002` 新增签名 session cookie 和退出登录。
- `OC-P6-003` 保护主页面和所有 API。
- `OC-P6-006` 增加生产环境配置校验。

验收标准：

- 未登录访问 `/` 跳转 `/login`。
- 未登录访问 `/api/collections`、`/api/collect`、收藏 CRUD、JSON 导入导出、sync API 返回 `401`。
- 登录成功后设置 httpOnly session cookie，并能正常进入收藏页。
- 退出登录后 cookie 被清除，再访问主页面回到登录页。
- `APP_ENV=production` 时缺少 `AUTH_SESSION_SECRET` 或口令配置会启动失败。
- `AUTH_ENABLED=false` 只允许开发环境使用。

建议技术方案：

- 后端新增 `backend/app/auth.py`。
- 使用 `hashlib.pbkdf2_hmac` 校验口令 hash。
- 使用 HMAC SHA256 签名 session token。
- cookie 设置 `HttpOnly`、`SameSite=Lax`，生产环境设置 `Secure`。
- 前端新增 `public/login.html`，主应用遇到 `401` 跳转登录页。

测试要求：

- 后端测试覆盖登录成功、登录失败、退出、过期 token、未登录 API 401。
- 后端测试覆盖 production 配置缺失时启动失败。
- Chrome headless 覆盖未登录跳转、登录后进入、刷新保持登录、退出回登录。

## P6.1：媒体代理防滥用、限流和健康检查

目标：防止公开服务被当作抓取代理或被刷爆。

任务：

- `OC-P6-004` 媒体代理 host allowlist。
- `OC-P6-005` API 限流。
- `OC-P6-007` 健康检查 API。

验收标准：

- 未登录访问 `/api/image`、`/api/media` 返回 `401`。
- 登录后访问非 allowlist host 返回明确错误，不代理任意公网 URL。
- `/api/auth/login`、`/api/collect`、`/api/image`、`/api/media`、`/api/collections/import-json` 有基础限流。
- 超限返回 `429 RATE_LIMITED`。
- `/api/health` 返回服务状态、auth 是否启用、sync provider、数据文件可读写状态。
- `/api/health` 不暴露 SecretId、SecretKey、bucket key 等敏感信息。

建议技术方案：

- 后端新增 `backend/app/rate_limit.py`，先做进程内 token bucket 或滑动窗口。
- 限流 key：登录后用 owner/session，未登录用 client IP。
- 媒体代理允许 host 后缀优先为 `.xhscdn.com`，后续再按真实资源补充。

测试要求：

- 后端测试覆盖 allowlist 命中、非 allowlist 拒绝。
- 后端测试覆盖登录接口和 collect 接口超限。
- 后端测试覆盖 `/api/health` 字段和敏感信息缺失。

## P6.2：部署文档、日志和备份恢复

目标：让服务可部署、可观测、可恢复。

任务：

- `OC-P6-008` 部署文档。
- `OC-P6-009` 操作日志。
- `OC-P6-010` 备份恢复入口。
- `OC-P6-011` 部署冒烟脚本。

验收标准：

- 文档说明环境变量、启动命令、反向代理、COS 配置、数据目录、备份路径。
- 日志记录登录失败、收藏导入、JSON 导入、删除、清空、sync push/pull、冲突和解析失败。
- 提供从本地备份或 COS 备份恢复数据的受保护入口。
- 部署冒烟脚本可验证登录、收藏列表、JSON 导入导出、sync 状态和健康检查。

建议技术方案：

- 日志先使用结构化 JSON line 文件，不引入外部日志系统。
- 备份恢复先只支持列出和恢复本地备份；COS 备份恢复作为后续扩展。
- 冒烟脚本使用当前已有 headless Chrome / curl 风格，不新增测试框架。

测试要求：

- 后端测试覆盖日志写入和不记录敏感 cookie/secret。
- 后端测试覆盖恢复前会先备份当前数据。
- 脚本在临时数据目录运行，不改真实 `data/collections.json`。

## P6.3：数据隔离预研，不立即实现完整多用户

目标：为后续多用户留边界，但不在 P6 第一阶段扩大系统复杂度。

任务：

- `OC-P6-012` 数据路径抽象预研。
- `OC-P6-013` 单 owner 数据路径设计。
- `OC-P6-014` 完整多用户账号系统方案。

验收标准：

- 输出数据路径方案：当前单文件、单 owner、多 owner 的迁移路径。
- 明确哪些 API 需要 owner 上下文。
- 明确 COS object key 如何按 owner 隔离。
- 不在 P6.0 到 P6.2 里改动现有 `collections.json` schema。

## 暂不推进

- 不做用户注册。
- 不做 OAuth。
- 不托管 rednote 登录态。
- 不做自动导入用户点赞/收藏。
- 不引入 SQLite/Postgres，除非后续数据量或多用户需求明确超过 JSON Store 边界。

## 当前推荐下一轮

`P6.0` 已在本机完成验证。下一轮优先执行 `P6.1`：

- `OC-P6-004` 媒体代理 host allowlist。
- `OC-P6-005` API 限流。
- `OC-P6-007` 健康检查 API。

真实 HTTPS、反向代理和公网域名下的 `Secure` cookie 行为需要在部署后单独验收。
