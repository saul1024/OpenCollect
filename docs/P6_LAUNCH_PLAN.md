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

## P6.1：API 安全基线

目标：在 P6.0 登录保护基础上，补齐公开入口防爆破、写接口来源校验、媒体资源级授权和最小健康检查，避免公网服务被借用或刷爆。

任务：

- `OC-P6-004` 媒体代理资源级授权和 SSRF 防护。
- `OC-P6-005` 公开入口防爆破和 API 限流。
- `OC-P6-007` 健康检查 API。
- `OC-P6-015` API 请求响应访问控制强化。

验收标准：

- 未登录访问业务 API 继续返回 `401`。
- `/api/auth/login` 连续错误登录会触发 `429 RATE_LIMITED`，冷却期内不能用正确口令立即绕过。
- `/login`、`/api/auth/session`、`/api/health` 有轻量限流。
- 已登录但缺少或伪造 CSRF token 的 `POST`、`PATCH`、`DELETE` 写接口返回 `403 FORBIDDEN`。
- 前端正常收藏、编辑、删除、导入、同步和退出登录时自动携带 CSRF token，不被误伤。
- 媒体代理不再接受任意外部 URL，只能通过 `collection_id + media_index` 代理当前收藏数据中的媒体。
- 媒体代理拒绝非 `http/https`、localhost、内网地址、metadata 地址、异常重定向、超时和超大小响应。
- `/api/auth/login`、`/api/collect`、媒体代理、`/api/collections/import-json` 有基础限流。
- 超限返回 `429 RATE_LIMITED`。
- `/api/health` 返回服务状态、auth 是否启用、sync provider、数据文件可读写状态。
- `/api/health` 不暴露 SecretId、SecretKey、bucket、cookie、password、session secret、本地绝对路径等敏感信息。

建议技术方案：

- 后端新增 `backend/app/rate_limit.py`，先做进程内 token bucket 或滑动窗口。
- 限流 key：登录后用 owner/session，未登录用 client IP。
- 后端在登录成功时签发 CSRF token，Web 前端写请求通过 `X-CSRF-Token` 发送。
- 媒体代理接口改为按收藏 ID 和媒体下标寻址，后端从 `collections.json` 读取真实 URL，不再信任客户端传入的任意 URL。
- 媒体代理保留协议、IP、重定向、响应大小和 content-type 校验；host allowlist 仅作为后续可选兜底，不作为本轮主方案。

测试要求：

- 后端测试覆盖登录防爆破、冷却、公开接口轻量限流和业务接口超限。
- 后端测试覆盖 CSRF 缺失、错误和正确 token。
- 后端测试覆盖媒体只能代理收藏内资源，且拒绝任意 URL、内网地址、非 http/https、异常重定向。
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

## 上线后回归清单

以下项目必须等真实公网域名、HTTPS 证书和反向代理配置完成后统一回归。本机验收只能证明代码路径，不能完全证明真实部署链路。

### 访问保护和 cookie

- [ ] 公网域名访问 `/` 时，未登录会跳转到 `/login?next=/`。
- [ ] 未登录访问 `/api/collections`、收藏写接口、sync API、媒体代理全部返回 `401`。
- [ ] 正确口令登录后，浏览器收到 `opencollect_session`，并带有 `HttpOnly`、`SameSite=Lax`、`Secure`、`Path=/`。
- [ ] 正确口令登录后，浏览器收到 `opencollect_csrf`，并带有 `SameSite=Lax`、`Secure`、`Path=/`。
- [ ] HTTPS 域名刷新页面后仍保持登录；退出登录后两个 cookie 都被清除。
- [ ] HTTP 到 HTTPS 的跳转不会导致 cookie 丢失、重复登录或登录后回到错误路径。

### API 安全基线

- [ ] 公网下错误口令连续尝试会触发 `429 RATE_LIMITED`，冷却期内正确口令不能立即绕过。
- [ ] `/login`、`/api/auth/session`、`/api/health` 在公网下有轻量限流，不会被无限探测。
- [ ] 已登录后，抓包重放写接口但不带 `X-CSRF-Token` 返回 `403 FORBIDDEN`。
- [ ] 已登录后，抓包重放写接口但带伪造 `X-CSRF-Token` 返回 `403 FORBIDDEN`。
- [ ] 前端正常收藏、编辑、删除、JSON 导入、sync push/pull、退出登录不被 CSRF 误伤。
- [ ] 反向代理传入的 `X-Forwarded-For` 能被限流正确识别；如果部署在多层代理后，需要确认不会把所有用户都识别成同一个代理 IP。

### 媒体代理和 SSRF

- [ ] 旧接口 `/api/image?url=...`、`/api/media?url=...` 在公网下返回 `403`，不能代理任意 URL。
- [ ] 新媒体接口只能访问已收藏数据里的图片、视频、头像和封面。
- [ ] 抓包构造 localhost、内网 IP、metadata IP、非 `http/https` 协议会被拒绝。
- [ ] 媒体重定向到内网或异常地址会被拒绝。
- [ ] 真实收藏里的图片和视频在公网域名下能正常加载，Range 播放视频可用。
- [ ] 媒体超时、超大小、异常 content-type 有明确错误，不导致服务阻塞或 500。

### 健康检查和敏感信息

- [ ] `/api/health` 在公网下返回 `status`、`authEnabled`、`sync.provider`、数据文件读写状态。
- [ ] `/api/health` 不暴露 SecretId、SecretKey、bucket、cookie、password、session secret、本地绝对路径。
- [ ] 未登录用户访问 `/api/health` 不会看到内部部署路径或云存储对象 key。

### COS 同步和数据安全

- [ ] 生产 `DATA_DIR` 指向预期持久化目录，重启服务后收藏数据仍在。
- [ ] 启动时能从真实 COS 拉取现有 `collections.json`，失败时前端能看到明确同步状态。
- [ ] 本地变更不会自动覆盖 COS；点击“保存并上传”后 COS revision 更新。
- [ ] 远端有新版本时，本地旧 revision 写入仍返回冲突或进入既定合并流程。
- [ ] 上传前能生成云端备份，备份 key 不暴露到未授权响应里。

### 部署和浏览器回归

- [ ] 生产环境缺少 `AUTH_PASSWORD_HASH`、`AUTH_SESSION_SECRET` 或 `AUTH_ENABLED=true` 时启动失败。
- [ ] 静态资源 cache-busting 生效，浏览器不会继续使用旧 `app.js`。
- [ ] 桌面和移动浏览器都能完成登录、刷新保持登录、退出登录。
- [ ] 真实域名下收藏、编辑、删除、撤销、JSON 导入导出、sync push/pull、媒体查看的主流程可用。
- [ ] 反向代理、应用日志和浏览器控制台没有持续 4xx/5xx、CORS、mixed content 或 cookie warning。

## 暂不推进

- 不做用户注册。
- 不做 OAuth。
- 不托管 rednote 登录态。
- 不做自动导入用户点赞/收藏。
- 不引入 SQLite/Postgres，除非后续数据量或多用户需求明确超过 JSON Store 边界。

## 当前推荐下一轮

`P6.1` 已在本机完成验证。下一轮优先执行 `P6.2`：

- `OC-P6-008` 部署文档。
- `OC-P6-009` 操作日志。
- `OC-P6-010` 备份恢复入口。
- `OC-P6-011` 部署冒烟脚本。

真实 HTTPS、反向代理和公网域名下的回归项目统一记录在“上线后回归清单”。
