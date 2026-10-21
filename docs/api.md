# 远程 API 调用文档

供其他系统通过 HTTP 调用透网。机器可读的定义见 [openapi.json](openapi.json)，服务运行时也可以打开 `/docs` 查看。

## 基础

- 基础地址：`http://<地址>:<端口>/api/v1`，默认端口 9090
- 认证：除 `GET /health`、`GET /auth/status`、`POST /auth/login`、`POST /auth/bootstrap`、`POST /auth/logout` 和首次运行向导外，所有接口都需要登录，两种方式任选其一：
  - 脚本、其他系统：请求头 `Authorization: Bearer <令牌>`。令牌有两种：
    - 个人令牌（M6）：`lmp_` 开头，每个账号在网页“我的 API 令牌”或 `POST /tokens` 生成，权限与本人账号相同（只能访问自己有权限的项目）；可以是只读的（只能读取与计算，修改返回 403），默认 90 天过期，可撤销
    - 全局令牌：首次配置时生成，保存在 `config/config.toml` 的 `[security] api_token`，视为管理员（显示名 `api-token`）
  - 网页：`POST /auth/login` 用账号登录，服务端设置会话 Cookie `lmesh_session`（HttpOnly、SameSite=Strict，有效期 `security.session_hours`，默认 12 小时）；之后同源请求自动带上。带了 `Authorization` 头时以令牌为准
- 角色（REQ-030 / REQ-036）：管理员（admin，所有项目完全权限、账号、系统设置、AI 接口、公共设备库）、知识库维护员（maintainer，知识库与共享规则 / 基线 / 模板的修改、审核、发布、回滚）与普通用户（user）。标为“管理员”的接口对其他角色返回 403（code 1006）；标为“维护员”的接口对普通用户返回 403，普通用户可以用 `POST /kb/suggestions` 提建议
- 项目（REQ-035）：设备相关接口都在项目路径下，见下面的“项目、权限与兼容别名”
- 语言：`message` 字段按请求头 `Accept-Language` 返回中文、英文或巴西葡萄牙语；`code` 与 `data` 不随语言变化
- 耗时操作（文档抽取、批量往返测试等）采用“提交任务 → 返回任务 ID → 查询 `GET /tasks/{id}`”的方式

## 返回结构

```json
{"code": 0, "message": "成功", "data": { … }}
```

## 错误码

| code | HTTP 状态 | 含义 |
|---|---|---|
| 0 | 200 | 成功 |
| 1000 | 500 | 服务器内部错误，详情见日志 |
| 1001 | 422 | 参数错误；`data` 中给出出错的字段 |
| 1002 | 401 / 403 / 429 | 未登录、会话已过期或令牌错误（401）；登录时账号已停用（403）；连续登录失败被暂时锁定（429，`data.locked_until`） |
| 1003 | 409 | 当前状态不允许此操作（例如已配置后再提交向导） |
| 1004 | 404 | 资源不存在 |
| 1005 | 502 | 外部依赖失败（数据库、网络或 AI 接口） |
| 1006 | 403 | 没有权限：普通用户调用管理员或维护员接口、项目的只读成员修改数据、只读令牌修改数据、只限属主的操作（成员、转交、删除项目） |

## 项目、权限与兼容别名（M6）

- 项目路径：设备相关接口（导入、设备列表、配置图、对比、检查、清理、忽略项、翻译、变更、影响分析、拓扑与一致性、割接迁移、基线、版本历史、表格导出、报告、图查询与 AI 查询、配置检查项目与脚本、首页概况）写成 `/api/v1/projects/{project}/…`，例如 `GET /api/v1/projects/oam-vpn/devices`。`{project}` 是项目标识（在属主的项目里唯一，不同的人可以有同名项目；用户 2026-10-19 评审改选），也可以写 `属主/标识`（路径里写成 `属主%2F标识`，即 URL 编码后的样子，或 `属主~标识`）或项目编号。只写标识时先找调用者自己的项目（全局令牌为第一个管理员的）；自己没有时在调用者能访问的项目（成员；管理员为全部项目）里找，唯一匹配就用它，有多个时返回 409（code 1003，`data.candidates` 列出 `属主/标识`，提示“请写成 属主/标识”），不会静默挑一个。项目返回体的 `ref` 是规范引用：自己的项目写标识，别人的写 `属主/标识`；`full_ref` 总是 `属主/标识`。下表中“项目”一栏为“是”的接口都有项目路径版本
- 兼容别名（已弃用）：旧的无项目路径（例如 `GET /api/v1/devices`）仍然可用，落到调用者的默认项目（全局令牌为第一个管理员的默认项目）；响应头带 `Deprecation: true` 与 `Link: </api/v1/projects/<默认项目>/…>; rel="successor-version"`，OpenAPI 中标为 deprecated
- 项目里的设备：项目私有设备（导入或复制而来）与引用的公共设备（`source`：`private` / `public`）。引用的公共设备跟随公共库最新版本（`policy: follow`）或固定在某个版本（`policy: pin`，`pinned_version_id`，固定版本的序号 `pinned_seq`（第几版），公共库有更新版本时 `newer_available: true`）；设备列表、对比、检查等用到“最新版本”的地方都按项目的版本策略取当前版本
- 项目角色：属主（owner）、管理成员（manage，M9-8：可编辑的全部权限，另可审批加入申请、增减成员、管理邀请链接、设置“可被搜索”）、可编辑成员（edit）、只读成员（read）；管理员访问不是自己参与的项目时角色为 admin，拥有完全权限，访问写入审计（`GET /admin/audit`、`logs/audit.log`）
- 权限：查看（GET）与计算（不修改数据的 POST：对比、检查、清理脚本生成、翻译、变更脚本生成、影响分析、拓扑、导出、报告、图查询、模板校验与生成……）对所有项目角色开放；修改数据（导入、删除、忽略、规则调整、脚本保存、重新解析本项目）只限属主、可编辑成员与管理员；成员管理、加入申请的审批、邀请链接只限属主、管理成员与管理员；转交、删除项目、改标识只限属主与管理员；退出项目、复制项目或把设备复制到自己的项目只需能查看。不是成员的普通账号访问项目返回 404（不暴露项目是否存在）
- 只读的个人令牌只能调用查看与计算接口，其他接口返回 403（code 1006）
- 创建项目（M9-8，REQ-050）：管理员始终可以；普通账号要么配置 `auth.user_create_projects`（系统设置“普通用户可以创建项目”，默认关）打开，要么管理员单独授权（`PUT /users/{username}` 的 `can_create_projects`），否则 `POST /projects` 与复制项目返回 403（`projects.create_forbidden`）。不能创建的账号不自动建默认项目：没有任何项目时 `GET /workspace` 的 `default_project` 为 null，旧的无项目接口返回 409（`projects.no_project`）。已有的项目照常使用
- 加入项目（M9-8）：属主按用户名添加；“可被搜索”的项目可以在 `GET /discover` 里找到并申请（对外只显示名称、简介、属主、设备数）；邀请链接（有效期、角色、可选仍需审批，可撤销）。申请、审批、授权、邀请链接的建立 / 撤销 / 使用都写入审计

## 项目内的网络（M9，REQ-045）

- 网络是项目里平铺的独立工作区（文件夹只整理列表）。设备属于项目（导入、版本历史、删除设备在项目层），网络引用设备，一台设备可以在多个网络里；权限仍按项目。
- 按网络的路径：`/api/v1/projects/{project}/n/{network}/…`（`{network}` 为网络标识或编号），挂了项目路径的接口都有网络版本，例外是项目设备池的管理：删除设备与版本、删除预览、贴 / 删标签、型号规则（`/model-rules`），以及只在项目路径下的项目管理（设置、成员、转交、复制、引用、`/networks` 本身、`/ai/kb/sanitize-redact`）。网络不存在 404（code 1004）。
- 不带网络的项目路径与旧路径作用于项目的**默认网络**（升级时与新建项目时自动建，标识 `default`，包含全部设备、自动加入新设备，可以改名、不能删除、成员不能移出），所以现有调用不用改。界面上“全部设备”的汇总页由 `GET /projects/{p}/networks` 提供。
- 按网络独立的数据：拓扑视图标注（`/view-annotations`）、检查忽略（`/check/ignores`）、规则调整（`/rules`）、脚本（`/scripts`、`/check-projects`）、AI 建议与采纳记录（`/ai/…`）、检查结果汇总；拓扑、一致性、检查、基线、对比、变更、割接、影响分析、报告与导出、图查询只看本网络的设备，用本网络为每台设备选的版本（网络里固定的版本 → 项目引用公共设备固定的版本 → 最新版本）。模板、翻译规则集、型号规则、脱敏补充仍按项目 / 个人共用。
- 设备列表（`GET …/devices`）在项目路径与网络路径下每行另有 `networks`（所在网络：`id`、`slug`、`name`、`color`、`default`、`policy`、`version_id`）、`network_policy`（follow / pin）、`network_pinned_version_id`、`network_pinned_seq`、`network_newer_available`、`network_findings`（本网络最近的检查结果）；导入结果每个文件另有 `device_id` 与 `joined_networks`（这次新加入的网络：`via` 为 default / current / rule，`rule` 为命中的规则）。
- 拓扑（`GET …/topology?outside=true`、`POST …/topology` 的 `outside`）：返回体另有 `network`、节点的 `also_in`（还在哪些网络，不含当前与默认网络）；`outside` 为网络外的对端（`links`：`inside` 本网络一端、`peer` 对端设备与 `networks` 它所在的网络；`count`），只在非默认网络里有内容。
- 识别色：8 个颜色键 `slate`、`indigo`、`green`、`rust`、`teal`、`violet`、`amber`、`rose`（`GET /networks` 的 `palette`），按创建顺序自动分配，可以改成组内其他颜色；明 / 暗主题的具体色值由前端决定。

## 接口

| 接口 | 认证 | 作用 |
|---|---|---|
| `GET /health` | 否 | 健康检查：版本、是否已配置、数据库、知识库、AI 接口 |
| `GET /setup` | 否（仅未配置时） | 首次运行向导的参数定义（`groups`、`addresses`、`languages`）；`config_path` 是将写入的配置文件，`running` 是当前运行的 `server.host`、`server.port`（与它不同的项需要重启才生效） |
| `POST /setup` | 否（仅未配置时） | 提交向导结果；`dry_run: true` 时只校验；`admin: {"username", "password"}` 同时创建第一个管理员并登录（设置会话 Cookie），错误键为 `admin.username` / `admin.password` |
| `POST /setup/ai-test` | 否（仅未配置时） | 向导里测试 AI 接口（REQ-048）：`{provider, base_url, api_key, model}`，发一句测试请求；成功返回 `model`、`reply`、`elapsed_ms`；必填项不合格 422（`data.errors`）；调用失败 502，`data` 只有 `error_type` 与 `status`（HTTP 状态码）。API Key 不保存、不写日志，也不写调用记录 |
| `GET /auth/status` | 否 | 登录页需要的状态：`configured`、`has_users`（还没有账号时登录页改为用 API 令牌创建管理员）、`session_hours`、`registration`（自助注册，REQ-039：`open` 是否开放（还没有任何账号时不开放），`approval` 注册后是否需要管理员审核）；已配置且还没有账号时另返回 `config_file`（实例实际读取的配置文件绝对路径）与 `token_set`（是否设置了 API 令牌，布尔，不返回令牌内容），有账号后不返回这两项 |
| `POST /auth/login` | 否 | 用户名 + 密码登录：`{"username", "password"}`；成功返回 `user` 与 `expires_at` 并设置会话 Cookie；用户名或密码错误 401（不区分用户不存在），账号停用 403，自助注册后待审核 403（`data.reason = pending`，只在密码正确时这样提示），连续失败 `security.login_max_failures` 次（默认 5）锁定 `security.login_lock_minutes` 分钟（默认 15），锁定期间 429 |
| `POST /auth/bootstrap` | 否（仅没有任何账号时） | 用 API 令牌创建第一个管理员并登录：`{"token", "username", "password"}`；已有账号时 409，令牌不对 401 |
| `POST /auth/register` | 否 | 自助注册（REQ-039）：`{"username", "password"}`，规则同账号管理；新账号为普通用户（`origin = register`）。注册关闭（`auth.registration = false`，默认）或还没有任何账号时 403（code 1006，“注册未开放，请联系管理员”）；同一来源地址每小时超过 `auth.registration_rate_per_hour` 次（默认 5）429（`data.per_hour`）；用户名已存在 409；需要审核（`auth.registration_approval = true`，默认）时 `data.status = pending`，不发会话；不需审核时 `status = active`，同时登录（设置会话 Cookie，返回 `user` 与 `expires_at`）并建好默认项目。注册记入审计（不含密码） |
| `POST /auth/logout` | 否 | 登出：删除会话、清除 Cookie；`data.logged_out` 表示是否确实结束了一个会话 |
| `GET /auth/me` | 是 | 当前调用者：`username`、`role`（admin / maintainer / user）、`via`（session / token / pat；全局令牌调用时 username 为 `api-token`，个人令牌为本人账号）、`expires_at`、`read_only`（只读的个人令牌）、`token_prefix`（个人令牌的前 8 个字符） |
| `GET /me/prefs` | 是 | 我的个人偏好（REQ-047）：`{has_account, prefs}`；`prefs` 为 `lang`、`theme`（auto / light / dark）、`term_style`（huawei / cisco / nokia）、`icon_set`（cyl / geo / line），账号还没保存过时为 null；全局令牌 `has_account` 为 false |
| `PUT /me/prefs` | 是 | 保存个人偏好（只改给出的项）；取值不合格 422；全局令牌 409；只读个人令牌 403。网页登录后以账号的值为准，账号没保存过时把浏览器本地的值写入 |
| `DELETE /me/prefs` | 是 | 清除账号保存的偏好（恢复为没保存过） |
| `POST /auth/password` | 是（会话） | 修改自己的密码：`{"old_password", "new_password"}`（至少 8 个字符）；当前会话保留，其他会话失效（`sessions_closed`）；旧密码不对 422；用令牌调用 409 |
| `GET /users?status=` | 管理员 | 账号列表：`username`、`role`（admin / maintainer / user）、`status`（active / pending 待审核）、`origin`（admin 管理员建 / register 自助注册）、`projects`（拥有的非空项目数）、`tokens`（有效的个人令牌数）、`disabled`、`locked`、`locked_until`、`last_login_at`、`password_changed_at`、`created_at`（不含密码哈希） |
| `POST /users` | 管理员 | 新建账号：`{"username", "password", "role": "user\|maintainer\|admin"}`；用户名 2–64 个字符（字母、数字、点、下划线、短横线），不区分大小写唯一 |
| `PUT /users/{username}` | 管理员 | 改角色、停用 / 启用、解除锁定、单独授权创建项目（M9-8）：`{"role", "disabled", "unlock", "can_create_projects"}`；停用时会话立即失效；最后一个启用的管理员不能停用或降级、不能停用或降级自己（409） |
| `POST /users/{username}/approve` | 管理员 | 批准自助注册的待审核账号（REQ-039）：可以登录，并建好工作空间与默认项目；不是待审核时 409；记入审计 |
| `POST /users/{username}/reject` | 管理员 | 拒绝待审核账号：删除它（用户名可以再注册）；不是待审核时 409；记入审计 |
| `GET /auth/settings` | 管理员 | 自助注册设置：`registration`、`approval`、`rate_per_hour` 与各项来源（`sources`：default / file / env） |
| `PUT /auth/settings` | 管理员 | 保存自助注册设置：`{"registration", "approval", "rate_per_hour"}`（只给要改的项，`rate_per_hour` 1–1000）；写入配置文件 `[auth]` 分组，立即生效；记入审计 |
| `GET /settings` | 管理员 | 系统设置（REQ-049）：全部配置项按首次运行向导的分组（`groups[].fields[]` 与 `GET /setup` 相同，另有 `value`、`source`、`restart`、`readonly`：env / ai / secret / null）；`config_path`；`restart_pending`（配置文件已改、当前进程还在用旧值的项：`key`、`running`、`saved`）；`running`（正在运行的监听地址与端口）。敏感值只给出是否已设置 |
| `PUT /settings` | 管理员 | 保存系统设置：`{"values": {键: 值}, "dry_run": false}`，只改给出的项；逐项校验（端口与正在运行的不同时检查是否被占用），不合格 422 并在 `data.errors` 里逐项说明，不写入；写入 `config/config.toml`，立即生效的项马上生效，需要重启的项列在 `restart_pending`，不自动重启；记入审计（`settings.update`，只记配置键） |
| `POST /users/{username}/password` | 管理员 | 重置密码：`{"password"}`；同时解除锁定，该账号的会话全部失效 |
| `DELETE /users/{username}?transfer_to=&delete_projects=false` | 管理员 | 删除账号；不能删除自己和最后一个启用的管理员（409）；拥有非空项目时必须 `transfer_to`（项目、私有模板与规则集转交给该账号）或 `delete_projects=true`（一并删除），否则 409（`data.projects`）；自动建的空默认项目直接删除 |
| `GET /config` | 管理员 | 当前生效的配置，敏感值只显示是否已设置 |
| `POST /sanitize` | 是 | 脱敏一段配置文本：`{"text": "…", "level": "basic\|strict"}`；返回脱敏后的文本、厂商、各类替换数量和不含原值的替换报告 |
| `POST /configs` | 是 | 上传并导入配置（multipart：一个或多个 `files`，可以是 zip；`level` 默认 basic）。REQ-044：`profile` 对所有文件指定 Profile；`choices` 按文件名指定（JSON：`{"文件名": {"profile", "raw_only", "remember": {"scope": "project\|global", "name_pattern", "version", "feature"}}}`，`remember` 同时新建型号规则，`scope=global` 只限维护员与管理员，否则 403）；`unsupported=skip\|raw`（认不出厂商的文件不导入 / 只存原文，默认 skip）。手工选择只允许同厂商 / 同平台族（认不出厂商时任意），不允许的文件 `ok=false`、`error` 说明原因。每个文件的结果带 `profile_source`（auto / fallback / rule / manual / none）、`match_level`（exact / approx / none）、`rule_id`、`rule_created`、`raw_only` |
| `POST /configs/inspect` | 是 | 导入前识别（不入库，multipart 同上）：每个文件的设备名、厂商、版本、`match_level`、按选择顺序会用的 `profile` 与 `profile_source`、命中的型号规则 `rule`、设备之前的选择 `previous`、候选的试解析结果 `candidates`（同厂商 / 同平台族；认不出厂商时为全部 Profile；按识别出的命令行比例 `ratio` 排序，不用 AI）、`recommended`、“记住”预填的规则 `suggested_rule`；`can_global` 表示调用者能否建全局规则 |
| `GET /devices` | 是 | 已导入的设备与最新配置版本；REQ-044 起每台带 `profile_source`、`profile_rule_id`、`match_level`、`approx`（近似：厂商默认、型号规则、手工选择）、`unsupported`（认不出厂商，只存原文）、`unknown_ratio`（未识别行比例） |
| `GET /devices/{id}/profile-candidates` | 是 | 更换 Profile 的候选：当前选择与来源、`auto`（按选择顺序会自动选到的）、`candidates`（试解析结果）、`recommended`、`suggested_rule` |
| `PUT /devices/{id}/profile` | 是 | 更换 Profile 并重新解析最新版本：`{"profile": "…" \| null, "remember": {"scope", "name_pattern", "version", "feature"} \| null}`；`profile` 为空时改回自动选择；之后的导入与重新解析沿用手工选择；跨厂商 422；公共设备库的设备只限管理员（403）；只读成员 403 |
| `POST /devices/{id}/support-request` | 是（只读成员也可以） | 申请支持此型号：`{"model", "reason"}`；附设备信息与未识别行的前 20 种写法，进审核队列（类型 `suggestion`，`payload.kind = model`），提出人在 `GET /kb/suggestions` 看到结果 |
| `GET /model-rules` | 是 | 型号规则：`project`（本项目）与 `global`（全局），按生效顺序（本项目 > 全局；条件多的优先；一样多时先建的优先；停用的在后），每条带命中设备数 `devices`；`can_global` |
| `POST /model-rules` | 是（全局只限维护员与管理员） | 新建：`{"scope": "project\|global", "vendor", "name_pattern", "version", "feature", "profile", "note", "enabled", "reparse"}`；至少一个条件、正则有效、只能指向同厂商的 Profile（422）；`reparse=true` 时重新解析本项目里命中的设备（手工选择的不动），返回 `reparsed` |
| `POST /model-rules/test` | 是 | 试匹配（不保存）：本项目里会命中的设备，`taken_by` 为抢先的更早规则 |
| `PUT /model-rules/{id}` / `DELETE /model-rules/{id}` | 是（全局只限维护员与管理员） | 修改（只给要改的项，可带 `reparse`）/ 删除；别的项目的规则 404 |
| `GET /kb/model-support/{审核编号}` | 维护员 | 型号支持申请的处理状态：`derived`（派生的 Profile）、`released`（是否已在最近一次发布中）、`plan`（将改指向的规则、没有规则时将新建的全局规则、将重新解析的设备）、`bases`（基础 Profile 的试解析） |
| `POST /kb/model-support/{审核编号}/derive` | 维护员 | 从现有 Profile 派生：`{"id", "base", "title", "platform", "software", "version"}`；继承 `base`，只写差异，写入知识库草稿区；申请已处理 409 |
| `POST /kb/model-support/{审核编号}/retarget` | 维护员 | 匹配申请设备的型号规则改指向派生的 Profile（没有规则时新建一条全局规则），相关设备（所有项目，手工选择的不动；申请设备本身手工选的近似 Profile 改回自动）重新解析，申请标为通过；没有派生 409 |
| `POST /kb/validate` | 是 | 校验知识库 |
| `GET /kb/export` | 是 | 下载知识库包（zip） |
| `POST /kb/import?dry_run=false` | 是 | 上传知识库包（multipart 字段 `file`）；冲突送审核队列 |
| `GET /kb/releases` | 是 | 已发布的版本、提交历史、当前版本号 |
| `POST /kb/releases` | 维护员 | 发布：`{"version": null, "message": "…"}`，版本号为空时自动建议 |
| `GET /kb/diff?from=X&to=Y` | 是 | 版本对比；省略 `to` 时与工作区对比 |
| `POST /kb/rollback` | 管理员 | 回滚：`{"ref": "0.1.0"}` |
| `GET /kb/coverage?profile=P` | 是 | 覆盖矩阵 |
| `POST /kb/ingest` | 是 | 导入产品文档：`{"doc_dir": "服务器上的目录", "rules": "huawei-vrp8-md", "domains": null, "version": "", "use_ai": false}`；后台任务，返回 `task_id` |
| `GET /tasks/{id}` | 是 | 耗时任务的状态（queued / running / done / failed）、进度、结果 |
| `GET /review?status=pending&kind=…` | 是 | 审核队列（含各类型待审数量） |
| `GET /review/{id}` | 是 | 审核条目详情 |
| `POST /review/batch` | 是 | 批量通过：`{"kind": "card", "contains": null, "rules": null}` |
| `GET /ai/status` | 是 | 当前账号的 AI 是否可用（REQ-040：按账号的选择）：`configured`、`provider`、`models`、`effective`（`source` connection / personal、`choice`、`connection`（`id`、`name`、`public`）、`model`、`reason`）、`reason`（不可用的原因：`no_connection` 没有可用的管理员接口、`no_public` 管理员未开放公共接口、`public_closed` 所选接口已关闭或删除、`personal_missing` 个人接口未填写完整、`disabled_by_user` 选择了不使用） |
| `POST /ai/test` | 管理员 | （已弃用，改用下面两个测试接口）测试调用者当前生效的 AI 接口（不可用时 409） |
| `GET /ai/calls?limit=100&user=&connection_id=&task=` | 是 | AI 调用记录：每条带 `user`（发起人；全局令牌为 `api-token`，没有账号的命令行为 `cli`）、`connection`（接口名，个人接口为 `personal`）、`connection_id`（个人接口为空）、`source`、`feature`（skill 编号或任务）；管理员看全部（`scope: all`，可按 `user` 过滤），其他账号只看自己的（`scope: mine`） |
| `GET /ai/connections` | 管理员 | 管理员 AI 接口列表（REQ-040）：`connections`（`id`、`name`、`provider`、`base_url`、`api_key_set`、`model`、`model_extract`、`model_merge`、`model_ask`、`model_generate`、`public` 允许公共使用、`enabled`、`complete`、`is_default`（全局令牌与管理员默认用它）、`chosen_by`（明确选用它的账号数）、`usage`（本月 `calls`、`errors`、`tokens_in`、`tokens_out`））、`limits`（全局的 `timeout`、`max_tokens`，在配置文件中修改）；个人接口不在其中 |
| `POST /ai/connections` / `GET /ai/connections/{id}` / `PUT /ai/connections/{id}` / `DELETE /ai/connections/{id}` | 管理员 | 新建 / 查看 / 修改 / 删除：`{"name", "provider": "anthropic"\|"openai"\|"local", "base_url", "api_key", "clear_api_key", "model", "model_extract", "model_merge", "model_ask", "model_generate", "public": false, "enabled": true}`；修改时各字段可选，不传 `api_key` 保留原值；名称重复 409，填写不完整（Anthropic 需要 Key，其他需要地址；都需要模型）422；删除返回 `affected_users`（选用它的账号随后提示改选） |
| `POST /ai/connections/{id}/test` | 管理员 | 测试一个管理员接口（不论是否启用、是否公共），记入调用记录；AI 出错 502 |
| `GET /me/ai` | 是 | 我的 AI：`choice`（auto 默认 / connection / personal / none；全局令牌为 system）、`connection_id`、`personal`（个人接口，不含 Key，只有 `api_key_set`；只有本人能看到，管理员也看不到）、`options`（可选的管理员接口：普通账号只有启用且允许公共使用的，管理员为全部启用的）、`effective`、`is_admin`、`has_account`、`no_token_warn`（个人偏好：不提示大请求，M8-2） |
| `PUT /me/ai` | 是 | 修改：`{"choice", "connection_id", "personal": {…同接口字段}, "remove_personal": false, "no_token_warn": true}`（各项可选）；选不可用的接口或没有完整的个人接口时 422；全局令牌没有账号 409；只读令牌 403 |
| `POST /me/ai/test` | 是 | `{"target": "personal"\|"effective"}`：测试我的个人接口或当前生效的接口；不可用时 409（`data.reason`） |
| `GET /ai/usage?from=&to=&user=&connection_id=` | 是 | 用量统计（UTC 日期，含两端，默认最近 30 天）：`totals` 与 `by_day`（每天一行，没有调用补 0）、`by_user`、`by_connection`（个人接口统一记为 `personal`）、`by_feature`、`by_model`，每行 `key`、`calls`、`errors`、`tokens_in`、`tokens_out`；管理员看全部，其他账号只统计自己的（`scope`） |
| `GET /ai/usage/export?group=day\|user\|connection\|feature\|model&from=&to=` | 是 | 导出一组为 CSV（UTF-8 带 BOM；列 `key,calls,errors,tokens_in,tokens_out`），范围与权限同上 |
| `POST /review/{id}` | 是 | `{"action": "approve" \| "reject", "note": "", "edited": {…}}` |
| `POST /parse` | 是 | 解析配置文本：`{"text": "…", "profile": null}`；返回 Profile、各类行数、覆盖率与每一行的结果 |
| `POST /render` | 是 | 解析建图后渲染回文本：`{"text": "…", "profile": null, "canonical": false, "with_defaults": false}`；默认往返模式（`mode: roundtrip`）；`canonical: true` 规范模式，`with_defaults: true` 含默认值的完整配置（默认值行前有 `! default` 注释），返回 `text`、`lines`（`no`、`text`、`kind`、`origin` explicit / default、`nodes`、`card`）、`default_lines`、`uncovered`、`skipped_extras` |
| `POST /translate` | 是 | 配置翻译：`{"text": "…" 或 "version_id": 1 或 "device_id": 1, "profile": null, "to": "<目标 Profile>", "interface_map": {"Port-channel1": "Eth-Trunk1"}, "verify": true}`；返回 `text` 译文、`lines`（同 `/render`）、`warnings`（`default_differs` / `default_unknown` / `inferred_value` / `implicit_object` / `interface_type` / `verify_diff` / `verify_unknown`）、`unsupported`（`kind` node / ext / raw / unknown / negated，`params.reason` 为 `profile_unsupported` / `no_render` / `secret` / `not_translated`）、`defaults`（`explicit_equals_default` 省略的默认值）、`stats` 与 `verify`（`checked`、`equal`、`diffs`、`unexplained`）；每一项都有 `kind`、`key`（文案键）、`params`（文案参数）、`node`（源图中的节点）、`schema`、`lines`（原文行号）；目标 Profile 不存在或没有给出源配置时 422，设备或版本不存在时 404；源是使用近似 Profile 的设备时 `approx_profile`（`device`、`profile`、`source`、`rule_id`）提示下发前核对（REQ-044），否则为 null；`rule_set`（规则集编号）或 `rules`（规则集内容）选用翻译规则集（REQ-032），结果另有 `naming`（同 `POST /translate-rules/test`），不给时结果不变 |
| `GET /translate-rules` | 是 | 翻译规则集（REQ-032）列表：`items`（`id`、`title`、`description`、`from` / `to` 平台族、`builtin`、`file`、`counts`（`names`、`naming`、`ports`）、`valid`、`issues`、`updated`）与 `types`（可改名的对象类型：被引用的单键对象，`id`、`domain`、`title` 三语） |
| `GET /translate-rules/{id}` | 是 | 读取规则集：上面的字段 + `rules`（结构化，字段名 `names` / `naming` / `ports`，匹配源写 `from`）与 `source`（YAML 原文）；不存在 404 |
| `PUT /translate-rules/{id}` | 是 | 保存规则集到 `data/translate-rules/<id>.yaml`：`{"rules": {…}}`（合并进已有文件，保留注释与顺序）或 `{"source": "<YAML>"}`（原样写入）；规则有误 422（`data.issues`：`where`、`key`、`args`），内置规则集只读 409；登录用户都可保存 |
| `DELETE /translate-rules/{id}` | 是 | 删除我的规则集；内置规则集 409，不存在 404 |
| `GET /translate-rules/{id}/export` | 是 | 导出规则集（YAML 文件下载） |
| `POST /translate-rules/import` | 是 | 导入规则集：`{"source": "<YAML>", "id": null, "overwrite": false}`；编号已存在 409 |
| `POST /translate-rules/match` | 是 | 编辑器测试框：`{"rule_set" 或 "rules", "kind": "name"\|"port", "type": "vrf.instance", "value": "…", "to": null}`；返回 `result`、`rule`（命中的规则序号）、`mapped`、`naming_rule`、`fixes`、`problems`（`pattern` / `length`）、`max_length`、`limit_source`（`rule` / `knowledge`） |
| `POST /translate-rules/test` | 是 | 试运行：`{"rule_set" 或 "rules", "text" 或 "version_id" 或 "device_id", "profile", "to", "target_text"}`；返回 `renames`（`type`、`from`、`to`、`rule`、`fixes`、`refs`、`ref_nodes`、`applied`、`conflict`、`lines`）、`ports`（`from`、`to`、`rule`、`subinterfaces`、`applied`）、`conflicts`（`many_to_one` / `exists` / `target_exists` / `port_many_to_one` / `port_exists`）、`naming`（命名规范告警）、`text_refs`（原文行中的旧名）、`gaps`（`name_limit_unknown`）、`summary` |
| `POST /migrate` | 是 | 割接迁移：`{"text": "…" 或 "version_id": 1 或 "device_id": 1, "profile": null, "to": "<目标 Profile>", "interface_map": {"GE0/2/1": "GigabitEthernet0/0/1"}（可只给部分，`-` 表示不迁移）, "target_text": "<新设备现有配置>", "model": null, "on_conflict": "migrate", "verify": true}`；返回 `text`（新设备完整配置）、`delta`（只含需要新增 / 修改的部分；没有现有配置时同 `text`）、`interface_map`（`source`、`target`、`kind`、`source_speed`、`target_speed`、`basis` user / same_name / logical / same_index / same_speed / higher_speed / same_name_unverified / type_convert、`confidence`、`subinterfaces`、`configured`、`node`、`lines`）、`unmapped`（`reason` management / no_free_port / speed_unknown / no_target_type / unknown_type / duplicate_target / user_excluded）、`inventory`（`source` kb / target_config / none、`model`、`ports`、`verified`）、`warnings`（翻译告警 + `migrate.warn.*`：`speed_mismatch`、`type_mismatch`、`mgmt_not_migrated`、`interface_unmapped`、`ref_not_migrated`、`subinterfaces_follow`、`lag_renumbered`、`lag_member_not_migrated`、`lag_trunk_not_migrated`、`lag_speed_mismatch`、`target_conflict`、`target_coexist`、`target_occupied`、`verify_diff` 等）、`unsupported`、`defaults`、`merge`（`added`、`changed`、`same`、`conflicts`、`kept`）、`verify`（`checked`、`equal`、`diffs`、`unexplained`、`target_existing`）、`script`（复用增量变更模块：`available: true` 与 `script` / `rollback` / `items` / `verify`；模块不可用或出错时 `available: false` 与 `reason`）、`steps`（`no`、`phase`、`device` old / new / site、`key`、`params`、`commands`）、`stats`；目标 Profile、型号、冲突处理方式无效或没有给出源配置时 422，设备或版本不存在时 404；`rule_set` / `rules` 选用翻译规则集（端口规则在用户映射表之后、自动建议之前），结果另有 `naming` |
| `POST /migrate/suggest-map` | 是 | 割接迁移的接口映射建议：请求同 `/migrate`（不含 `on_conflict`、`verify`）；返回 `map`（同 `interface_map`）、`unmapped`、`warnings`、`inventory`、`stats`（`mapped`、`unmapped`、`by_basis`）；`rule_set` / `rules` 的端口映射规则也参与建议 |
| `GET /topology?devices=A,B,3` | 是 | 已导入设备（名称或编号，逗号分隔；省略时全部）的三层拓扑：`nodes`（设备：`id`、`device_id`、`version_id`、`profile`、`loopbacks`、`lsr_id`、`asn`、`links`）、`links`（`id`、`type` subnet / ospf / isis / ldp / ldp_remote / bgp / pw / bfd、`a` / `b`（`device`、`interface`、`address`、`node`、`facts`）、`segment`、`vrf`、`confidence` high / medium / low、`basis`（`rule`、`a_node`、`b_node`、`detail`））、`cross_edges`（跨设备依赖边：`rule`、`src` / `dst` 的设备与节点、`value`）、`unresolved`、`duplicates`、`summary`；没有设备时 409，设备不存在时 404 |
| `POST /topology` | 是 | 上传配置推导拓扑（可与已导入设备混合）：`{"configs": [{"name": "r1.cfg", "text": "…", "profile": null}], "device_ids": [1]}`，两者都为空时取全部已导入设备；结果同上；无法识别的配置 422（`data.source` 为文件名） |
| `POST /consistency` | 是 | 跨设备一致性检查：请求同 `POST /topology`，另加 `severity`；返回拓扑（链路带 `issues` 与 `severity`，设备带 `issues` 个数）+ `findings`（与 `/check` 相同的字段，另有 `link`、`link_type`、`device`、`devices`、`ends`（两端的设备、端点、节点、取值、行号））、`summary`（另有 `by_link`、`by_device`、`topology`）、`rules_loaded`、`rules_skipped`（Schema 中缺少节点而跳过的规则）、`texts`；规则文件写错时 409 |
| `POST /baseline` | 是 | 安全基线审计：`{"baseline": "basic", "configs": [{"name": "R1", "text": "…", "profile": null}], "device_ids": [1], "all": false}`（三者至少给一项，可混合；`all` 为全部已导入设备的最新版本）；返回 `baseline`、`baseline_info`（`title`、`description`、`includes`、`chain`）、`rules`（`id`、`severity`、`target`、`tags`、`profiles`、三语 `title` / `message` / `suggestion`、`remedy`（`huawei` / `cisco` 参考命令））、`matrix`（`rules`、`devices`、`cells[规则][设备]` 为 `pass` / `fail` / `na`）、`devices`（`device`、`profile`、`family`、`style`、`score`、`summary`（`pass`、`fail`、`na`、`failed_by_severity`、`has_errors`）、`results`、`failures`（`rule`、`severity`、`node`、`schema`、`key`、`lines`、`evidence`、`message` / `suggestion` 为文案键 + 参数、`remedy` 按设备平台族写法））、`summary`（`devices`、`rules`、`score`、`pass`、`fail`、`na`、`failures`、`has_errors`、`by_rule`）、`texts`；基线名写错或没有目标时 422，设备不存在时 404，规则文件写错时 409 |
| `GET /baseline/rules?baseline=strict` | 是 | 基线与规则：`profiles`（`id`、三语 `title` / `description`、`includes`、`chain`、`rules` 条数）、`rules`（字段同上，给出 `baseline` 时只列该基线的规则）、`total` |
| `POST /baseline/report` | 是 | 导出基线报告，直接返回文件（Content-Disposition: attachment）：请求同 `POST /baseline`，另加 `lang`（zh-CN / en）、`format`（html / md）、`style`（huawei / cisco）；内容为概要、设备 × 规则矩阵、每台设备的不符合项（含参考命令）与规则清单 |
| `POST /change` | 是 | 增量变更脚本：`{"current": {"text" 或 "version_id" 或 "device_id", "profile"}, "target": {…}, "rollback": true, "verify": true, "impact": true, "style": null, "lang": null}`（当前与目标同一平台族）；返回 `ops`（逐条命令：`seq`、`action` add / modify / delete / side_effect / mutex、`text`、`context`、`view`、`depth`、`object`、`label`、`domain`、`risk` low / medium / high、`risk_reasons`、`after`（排在哪些命令之后：`seq`、`kind`、`node`、`label`、`note` 三语说明对象）、`fallback`、`lines`）、`script`（带说明）、`script_plain`、`script_rows`（按视图分块的脚本行：`kind` frame / enter / cmd / quit、`depth`、`text`、`seq`（cmd 行对应的命令序号），与 `script_plain` 逐行对应）、`risk`、`summary`、`unsupported`、`warnings`、`verify`（模拟执行：`ok`、`equal`、`diff_count`、`new_dangling`、`order_violations`、`issues`、`unknown`）、`rollback`（同样结构）、`impact`（`seeds`、`objects`、`business`、`by_domain`、`by_business`、`summary`）、`approx_profile`（当前配置来自使用近似 Profile 的设备时的下发前提示，REQ-044；否则 null）；平台族不同或没有给出配置时 422，设备或版本不存在时 404 |
| `POST /change/report` | 是 | 导出变更报告，直接返回文件：请求同 `POST /change`，另加 `report_lang`（zh-CN / en）、`format`（html / md） |
| `GET /devices/{id}/history` | 是 | 版本历史时间线：`snapshots`（旧的在前：`id` 配置版本编号、`seq` 序号、`imports`（`imported_at`、`source_kind` file / dir / zip / api、`source_name`、`actor`、`duplicate`）、`import_count`、`kb_version`、`kb_current`、`fingerprint`、`tag`、`lines`、`nodes`、`graph_stored`、`vs_previous`（`added` / `modified` / `removed` / `renamed` / `noneff` / `fmt`）、`latest`）、`count`、`imports`、`tagged`、`keep` |
| `GET /devices/{id}/history/diff?a=&b=&rebuild=&show_noneff=&domain=&text=&context=` | 是 | 两个快照之间的变化（`context` 是原文差异每块前后保留的相同行数，默认 3，界面取 100000 拿整份原文在本地折叠；快照写法：配置版本编号、`v<编号>`、`#<序号>`、`latest`、`prev`、`tag:<标签>`；默认上一个 → 最新，A 总是较早的一侧）：`a` / `b`（快照信息与 `graph` stored / rebuilt）、`kb`（`a`、`b`、`current`、`differs`、`rebuilt`）、`summary`（对象级计数、`noneff` 只是写法不同、`fmt` 只是格式不同的行、`by_domain`）、`items`（`object` 规范编号、`schema`、`domain`、`kind` added / modified / removed / renamed、`from` / `to`、`lines_a` / `lines_b`、`changes`：`field`、`node`、`kind`、`a` / `b`（值、来源、行号））、`noneff`（`show_noneff=true` 时列出：`reason` default_explicit / spelling）、`text`（`hunks`：每行 `op` equal / del / add、`a` / `b` 行号、`node`、`fmt`）、`compare`（逐节点的对比结果） |
| `GET /devices/{id}/history/object?node=` | 是 | 一个对象在每个快照中的取值：`fields`、`snapshots`（`present`、`values`、`changed`、`lines`） |
| `PUT /devices/{id}/history/{version_id}/tag` / `DELETE …/tag` | 是 | 给快照贴标签 `{"tag"}`（永久保留，不受 `history.keep` 清理）/ 去掉标签 |
| `POST /devices/{id}/history/restore` | 是 | 回到某个快照：`{"to", "from": null, "style": null, "lang": null}`；返回 `from`、`to`（快照信息）、`change`（结构同 `POST /change`：脚本、回滚、模拟验证） |
| `POST /devices/{id}/history/report` | 是 | 导出版本差异报告，直接返回文件：`{"a", "b", "rebuild", "domain", "lang": "zh-CN\|en", "format": "html\|md", "style"}` |
| `GET /export/presets?style=` | 是 | 审计表格的预置模板：`presets`（`id`、`aliases`、`object`、`title` / `description`（三语）、`columns`（`key`、`field` 或 `derive`、`label` 三语、`schema`、`type`、`secret`、`empty`）、`where`、`filters`）、`derives` |
| `GET /export/fields?object=` | 是 | 不给 `object` 时列出全部对象类型；给出时列出可用字段（键字段、属性、子对象属性：`path`、`type`、`secret`、`semantic`）与派生列 |
| `POST /export/table` | 是 | 生成审计表格：`{"preset" 或 "object", "columns": null, "where": null, "filters": [{"field", "op", "value"}], "devices": "all" 或 [名称或编号], "configs": [{"name", "text", "profile"}], "defaults": true, "canonical_names": false, "style": "huawei", "format": "json\|csv\|xlsx", "lang": "zh-CN\|en\|pt-BR", "sheets": "per-device\|single"}`；`json` 返回 `columns`、`rows`（`device`、`device_id`、`version_id`、`node`、`key`、`lines`、`cells`：`value`、`origin` explicit / default / derived / none / unsupported、`nodes`、`lines`、`secret`）、`devices`、`filters`、`summary`；`csv` / `xlsx` 直接返回文件；敏感字段的 `value` 只是 true / false |
| `GET /features?q=&profile=&family=&domain=&state=&include_same=&limit=` | 是 | 特性能力查询：`profiles`、`items`（`node`、`domain`、`type`、`semantic`、`range`、`choices`、`kind` same / differs / gap、`profiles`：每个 Profile 的 `state` supported / unsupported / unfilled、`default`、`cards`、`syntax`、`undo`、`views`、`credibility`、`source`、`sources`、`inherited`、`origin`）、`total`、`hidden_same`、`counts` |
| `GET /features/detail?node=&profile=` | 是 | 一个特性的完整信息（含 `deps` 依赖规则） |
| `GET /features/diff?a=&b=&domain=&include_same=` | 是 | 两个 Profile 对比：`rows` 按 `kind` default（默认值不同）→ only_a → only_b → unfilled 排序，相同的默认只计数（`hidden_same`）；`counts` |
| `GET /ask/status` | 是 | AI 查询与生成是否可用：`configured`、`status` ready / not_configured、`models`、`sanitize`（always）、`guard_without_ai`、`grammar`（查询语言说明） |
| `POST /query` | 是 | 执行图查询（不需要 AI）：`{"query": "<查询文本>" 或 {"find", "on", "where", "return", "with_defaults", "limit"}, "devices", "configs"}`；返回 `query`、`text`（规范写法）、`columns`、`rows`（`n` 引用编号、`device`、`node`、`label`、`lines`、`cells`）、`count`、`truncated`；查询不合法时 422 |
| `POST /ask` | 是 | AI 自然语言查询：`{"question", "devices": null, "lang": null}`；返回 `status`（answered / query_invalid）、`question_sent`（脱敏后）、`attempts`、`query` / `query_text`、`result`（同 `POST /query`）、`answer`（`statements`：`text`、`cites`、`facts`（`row`、`field`、`value`、`actual`、`ok`、`node`）、`count`、`status` passed / corrected / unverifiable、`corrected_text`、`nodes`；`summary`）、`sent`（发给 AI 的内容，已脱敏）、`ai`（`model`、`calls`、`tokens_in`、`tokens_out`、`ms`）；未配置 AI 时 409，`data.status` = not_configured；AI 调用失败时 502 |
| `POST /guard` | 是 | 配置护栏（不需要 AI）：`{"text", "device" 或 "base_text", "profile", "template", "cross_device": true, "script": true, "merged": false, "lang"}`（`merged: true` 时另返回合并后的完整配置 `merged_text`，界面交给增量变更时用）；返回 `verdict` passed / blocked、`lines`（每行 `status` ok / bad / warn / ctx / skip、`issues`、`nodes`）、`issues`（`id`、`status` bad / warn / ok、`stage` parse / deps / template / conflict、`rule`、`line`、`message`（文案键与参数）、`text`）、`stages`、`summary`、`script`（通过时的增量变更脚本） |
| `POST /generate` | 是 | AI 生成配置：`{"request", "device", "profile", "template", "rounds": 2, "merged": false, "lang"}`（`merged: true` 时最后一轮的 `guard` 附 `merged_text`）；返回 `rounds`（每轮 `text` 与 `guard` 结果）、`final`、`verdict`、`request_sent`、`sent`、`ai`；未配置 AI 时 409 |
| `GET /projects/{p}/ai/suggestions/skills` | 项目成员 | AI 建议（M8-2，只在项目路径下）：可生成建议的 skill（`id`、三语 `title` / `description`、`group`、`enabled`、`scope` device / project、`categories`）与 `ai`（`configured`、`reason`、`warn_tokens` 大请求提示线：全局 `ai.warn_tokens`，本人关闭提示时为 0）；入口按钮据此显示不可用的原因 |
| `POST /projects/{p}/ai/suggestions/estimate` | 项目成员 | 运行前估计发给 AI 的量（不调用 AI）：`{"skill", "device_id", "params"}` → `tokens`、`threshold`、`warn`（超过提示线；0 表示不提示） |
| `POST /projects/{p}/ai/suggestions/run` | 可编辑 | 运行 skill 生成建议：`{"skill", "device_id", "params": {"device_ids": […]}, "wait": false}`；默认后台任务（返回 `task_id`、`batch_id`；`GET /tasks/{id}` 的 `message` 依次为 sanitize / send / generate / check），`wait: true` 同步返回批次；AI 不可用 409（`data.reason`），skill 不存在 404，单台设备的 skill 缺设备 422；AI 回复无法解析（已重试一次）或调用失败时批次 `status: failed`、`error.key` |
| `GET /projects/{p}/ai/suggestions/batches/{id}` / `POST …/batches/{id}/cancel` | 项目成员 / 可编辑 | 一次运行：`status`（queued / running / done / failed / cancelled）、`mode`（ai / replay）、`skill_version`、`connection`、`model`、`tokens_in` / `tokens_out`、`ai_call_ids`（调用记录编号）、`skill_run_id`、`counts`（total / pass / warn / reject）、`error`；取消：AI 回复到达后丢弃，不生成建议（已结束的 409） |
| `GET /projects/{p}/ai/suggestions?skill=&status=&check=&category=&device_id=&batch_id=&scope=&limit=&offset=` | 项目成员 | 建议列表（新的在前）：`total`、`counts`（按状态，不受状态过滤影响）、`items`（`id`、`skill`、`category`、`kind`、`title`、`content`、`original`（编辑前）、`edited`、`refs`（解析后的引用：`id`、`found`、`type`、`label`、`node`、`line`、`device_id`，供界面跳转）、`check`（`status` pass / warn / reject、`reasons`：`code`、`level`、`ref`、`detail`；`display` / `segments` 代码填入后的正文，`title_display`；脚本类 `result` 模拟结果）、`check_status`、`status`（pending / adopted / dismissed / reverted）、`kb`（知识库类）、`ai_call_id`、`connection`、`decided_by` / `decided_at`、`adopt_info`、`note`、`reverted_by` / `reverted_at`、`revert_info`） |
| `GET /projects/{p}/ai/suggestions/{id}` | 项目成员 | 一条建议；不存在或不在本项目 404 |
| `POST /projects/{p}/ai/suggestions/{id}/adopt` | 可编辑（知识库类：维护员与管理员） | 采纳：`{"content", "title", "refs", "note"}`（都可选；给出编辑后的内容时先用同一份事实重新校验）；被拒绝的建议或编辑后不合格 409（`data.check`）；按类别执行：视图标注写入项目、脚本新建为项目脚本、知识库草稿进审核队列、文字与依据只记录结论 |
| `POST /projects/{p}/ai/suggestions/adopt-batch` | 可编辑 | 按类别批量采纳：`{"category", "skill", "batch_id", "ids"}`，只采纳校验通过（pass）且待处理的；返回 `adopted`、`skipped`（warn / reject）、`failed` |
| `POST /projects/{p}/ai/suggestions/{id}/dismiss` / `…/restore` / `…/revert` | 可编辑 | 忽略待处理的建议 / 把忽略的恢复为待处理 / 撤销已采纳的（30 天内；视图标注恢复原值、审核项撤回、未改动的脚本删除；之后被改动过、审核项已处理或超过 30 天 409） |
| `GET /projects/{p}/ai/suggestions/adoptions?limit=` | 项目成员 | 采纳记录：已采纳与已撤销的建议（按采纳时间，新的在前） |
| `GET /projects/{p}/view-annotations?target_type=` | 项目成员 | 项目级视图标注（设备角色、分组、标签、层次）：`target_type`、`target`（设备编号）、`key`、`value`、`source`（user / ai）、`suggestion_id` |
| `GET /ai/skills?days=30` | 管理员 | 内置 AI skill（REQ-033）列表：`ai`（`configured`、`provider`、`status`）、`days`、`skills`（`id`、三语 `title` / `description`、`task`、`used_by`、`model_key`、`model`、`enabled`、`active`（`builtin` 或版本号）、`builtin_version`、`versions`、`modified`、`tools`、`checks`、`examples`、`stats`（近 N 天线上调用：`calls`、`passed` / `corrected` / `rejected` / `unverifiable` / `error`、`pass_rate`、`reject_rate`、`up`、`down`、`corrections`、`regression_cases`、`candidates`、`pending_evolutions`））；普通账号 403 |
| `GET /ai/skills/{id}` | 管理员 | skill 详情：列表字段 + `definition`（生效的 `system`、`prompt`、`templates`、`examples`、`tools`、`output`）、`builtin`（内置定义）、`variables`（`name`、`in`、三语 `desc`）、`samples`（试运行样例：`index`、`title`、`input`、`reply`）、`tool_choices`、`check_titles`、`output_formats`、`stats`、`ai`；不存在 404 |
| `PUT /ai/skills/{id}` | 管理员 | 保存为新版本并生效：`{"system", "prompt", "templates", "examples": [{"input", "output", "note"}], "tools", "output": {"format", "schema"}, "note"}`（只给要改的字段）；返回 `version`、`unchanged`（与生效版本相同时不新建）、`warnings`（`skills.warn.var_dropped`）、`skill`；校验不通过 422（`data.issues`：`field`、`key`、`params`——未登记的变量、缺少或多出的模板、示例缺输入输出、工具或输出格式不在可选范围） |
| `PUT /ai/skills/{id}/enabled` | 管理员 | 启用 / 停用 `{"enabled": false}`；停用后对应的 AI 功能返回 409（`data.status: skill_disabled`），脚本审查的 `ai.status` 为 `skill_disabled`，命令卡抽取跳过 AI |
| `GET /ai/skills/{id}/versions` / `GET …/versions/{version}` / `GET …/diff?a=&b=` | 管理员 | 版本历史（`version`、`label`、`source` builtin / edit / example / evolution、`saved_at`、`author`、`note`、`based_on`、`evolution`、`active`）；某版本的 `definition`；两个版本逐字段对比（`fields`：`field`、`changed`、`lines` 逐行 `op` same / del / add 与两侧行号，`examples` / `tools` / `output` 另给 `a`、`b`），`b` 可写 `current` |
| `POST /ai/skills/{id}/rollback` / `POST …/restore` | 管理员 | 回滚 `{"version": "2"}`（生效版本指向该版本，版本文件不删除）；恢复内置版本；返回 `active`；版本不存在 404 |
| `POST /ai/skills/{id}/test` | 管理员 | 试运行：`{"sample": 0 或 "case_id": 1 或 "input": {…}, "definition": {…草稿}, "version": null, "mode": "ai"\|"replay", "reply": null}`；返回 `mode`、`version`（草稿为 `draft`）、`sent`（实际发送的内容，脱敏后）、`reply`、`check`（`status`、`score`、`items`：`ok`、`reason`、`text`、`line`）、`ai`、`run_id`（真实调用时的调用记录，来源 test，不计入统计）；`mode: ai` 而未配置 AI 时 409 `not_configured`，回放不需要 AI |
| `GET /ai/skills/{id}/stats?days=` / `GET …/runs?limit=&status=&source=` / `GET …/runs/{run_id}` | 管理员 | 统计：`totals`、`daily`（每天按校验结论计数与评价）、`by_version`、`runs`（最近调用）；调用记录列表；一次调用的详情（`input`、`reply` 均为脱敏后，`detail` 校验明细） |
| `POST /ai/skills/feedback` | 是 | 对一次 AI 结果的反馈（所有登录账号；结果中的 `skill_runs[].run_id`，脚本审查为 `ai.skill_run`）：`{"run_id", "rating": "up"\|"down"\|null, "correction": ""}`；点踩或更正进入该 skill 的回归集，校验通过且点赞的成为候选示例，`rating` 为空且没有更正时撤销评价；返回 `case`（`id`、`kind`、`reason`、`existing`）；普通账号只能评价自己发起的调用，不存在 404 |
| `GET /ai/skills/{id}/cases` / `POST …/cases` / `DELETE …/cases/{cid}` / `POST …/cases/{cid}/example` | 管理员 | 回归集（`regression`：被拦截 / 被更正的线上调用自动入集，点踩、更正、手动加入）与候选示例（`candidates`）；`{"run_id", "kind", "note"}` 手动加入（同样的输入只留一条）；删除；把案例加入示例（输入为发给 AI 的正文，输出取更正，没有时取原回复），形成新版本并生效 |
| `POST /ai/skills/{id}/evolve` | 管理员 | 发起进化 `{"limit": 20, "wait": false}`：AI（skill-evolve）根据回归集与更正提出候选版本 → 代码检查保留全部变量 → 回归集上分别运行旧版本与候选、按代码校验打分（通过 1、无法校验 0.5、其余 0）→ 待批准；默认后台任务返回 `task_id`，`wait: true` 返回 `evolution`；未配置 AI 409 `not_configured`，回归集为空 409 `no_cases` |
| `GET /ai/skills/{id}/evolutions` / `GET …/evolutions/{eid}` / `POST …/approve` / `POST …/reject` | 管理员 | 进化记录（`status` pending / approved / rejected / failed、`base_version`、`rationale`（AI 的说明）、`summary`：`old`、`new`、`better`、`worse`、`same`）；详情另有 `candidate`、`diff`、`scores.cases`（每条案例旧 / 新的 `status`、`score`、`items`、`reply`、`delta`）；批准后候选保存为新版本并生效（`published_version`），放弃只改状态；已处理过 409 |
| `GET /check-projects` | 是 | 配置检查项目列表（REQ-031；普通账号只看到自己的，管理员与 API 令牌看到全部）：`id`、`name`、`description`、`device`（`id`、`name`、`vendor`、`platform`、`profile`）、`version_id`（为空表示跟随最新版本）、`default_kind` change / full、`order_check`、`ai_check`、`ai_rules`、`owner`、`scripts`、`last_check`（`errors`、`warnings`、`checked`、`at`）、`created_at`、`updated_at` |
| `POST /check-projects` / `GET` / `PUT` / `DELETE /check-projects/{id}` | 是 | 新建 / 详情（带 `script_list`）/ 修改 / 删除项目：`{"name", "description", "device_id", "version_id", "profile", "default_kind", "order_check": true, "ai_check": false, "ai_rules": []}`；设备或版本不存在 404，名称为空 422 |
| `GET /check-projects/ai-rules` | 是 | 可交给 AI 参与校验的规则（规则文件中 `ai: true`）：`rules`（`id`、`title`、`severity`、`target`、`domain`、`code`（是否也有代码断言））与 `configured`（AI 是否已配置；未配置时界面隐藏“AI 一起校验”） |
| `POST /check-projects/{id}/scripts` / `GET` / `PUT` / `DELETE …/scripts/{sid}` | 是 | 脚本：`{"name", "kind": change\|full, "content"}`；创建形成第一条修订；`PUT` 的 `content` 与最新修订不同时形成一条 manual 修订（返回 `revision`） |
| `POST /check-projects/{id}/scripts/{sid}/check` | 是 | 实时检查：`{"content"（编辑器内容，不保存；不填检查保存的内容）, "kind", "order", "ai": false, "ai_rules", "style", "lang"}`；返回 `line_kinds`（每行 command / unknown / raw / wrong_view / session / exit / comment / separator / blank）、`issues`（`line`、`lines`、`severity`、`category` parse / view / undo / override / side_effect / order / conflict / rule / ai、`code`、`source` code / ai、`status`（AI：passed / unverifiable）、`text`、`suggestion`、`message`）、`order`（`enabled`、`applicable`、`violations`、有顺序错误时 `reorder`）、`result`（变更脚本：新增 / 取消 / 覆盖 / 副作用删除的行、`removed`、`findings_new`、`findings_fixed`；完整配置：`unknown`、`raw`、`compare`）、`ai`（`status` not_configured / no_rules / ok / error / bad_reply、`accepted`、`rejected`（`rule`、`line`、`reason`）、`sent`（脱敏后发送的内容）、`cached`）、`summary`、`ms`、`script`（`saved`：检查的是保存的内容时摘要记在脚本上） |
| `POST /check-projects/{id}/scripts/{sid}/reorder` | 是 | 按依赖重排变更脚本：`{"content", "apply": false, "style", "lang"}`；返回 `script`、`moves`（`line` → `new_line`、`text`、`reasons`：`dir` after / before、`line`、`kind` contains / reference / referenced_by / side_effect / same_target / anchor、`label`、`note`、`text`）、`mapping`、`changed`、`before` / `after`（检查摘要与顺序错误数）；`apply: true` 时保存为修订（重排前的内容未保存时先存一条 manual 修订），返回 `revision`、`before_revision`；完整配置 422 |
| `GET /check-projects/{id}/scripts/{sid}/revisions` / `GET …/revisions/{rid}` / `POST …/revisions/{rid}/restore` | 是 | 修订记录（新的在前：`seq`、`source` create / manual / reorder / restore、`note`（重排的移动与原因、恢复自哪个修订）、`summary`、`author`、`lines`、`created_at`）/ 一条修订（含 `content`）/ 恢复到该修订（形成一条 restore 修订） |
| `POST /check-projects/diff` | 是 | 文本差异对比：`{"a": {"type": "revision", "revision_id"} \| {"type": "script", "script_id", "text"} \| {"type": "baseline", "project_id"} \| {"type": "text", "text", "kind", "project_id"}, "b": {…}, "ignore_order": false, "semantic": true, "style"}`；返回 `stats`（`add`、`del`、`change`、`move`、`equal`）、`rows`（`t` equal / change / add / del / move_from / move_to、`a` / `b` 行号、`at` / `bt` 文本、`sa` / `sb` 行内改动的字符区间、`to` / `from` 移动的另一端）、`moves`、`unified`、`unordered`（忽略顺序时：`only_a`、`only_b`）、`semantic`（按有效值比较；变更脚本比较在基线上执行后的结果） |
| `POST /check-projects/diff/report` | 是 | 下载差异，直接返回文件：请求同上，另加 `format`（unified：`.diff`；html：自包含报告）、`report_lang`（zh-CN / en） |
| `POST /impact` | 是 | 变更影响分析：`{"text" 或 "device_id" 或 "version_id", "profile": null, "nodes": ["<节点编号>"], "direction": "up"}`（up 谁受影响 / down 依赖谁 / both）；返回 `seeds`、`nodes`（遍历到的节点：`node`、`schema`、`kind`、`domain`、`depth`、`via`（从哪个节点到达）、`edge`、`direction`、`business`）、`objects`、`business`（业务对象与从起点出发的 `path`）、`by_domain`、`by_business`、`summary`；节点不存在时 404 |
| `POST /roundtrip` | 是 | 往返测试：给出 `text` 时同步返回差异；`{"samples": true}` 时作为后台任务跑全部样本，返回 `task_id` |
| `GET /devices/{id}/graph?domain=D&raw=false&version_id=V` | 是 | 设备最新配置版本（给出 `version_id` 时为该版本，不属于该设备时 404）的配置图：节点、边（`note` 为三语说明对象 `{zh-CN, en, pt-BR}`，没有时为 `{}`）、悬空引用、统计；`raw=true` 时包含功能域外的原文节点与原始配置文本；`profile_info` 为 Profile 来源与近似标记（REQ-044）；只存原文的设备（认不出厂商）没有配置图，409（`data.raw_only = true`） |
| `GET /devices/{id}/analysis?parts=&version_id=&defaults=true` | 是 | 设备配置分析（REQ-034）：`parts` 为 `summary`、`layers`、`script`、`graph` 中的若干个（逗号分隔，默认全部；写错时 422）。总有 `device`、`device_id`、`version_id`、`profile`、`family`、`kb_version`、`layer_info`（层与跨层特性的三语名称）。`summary`：`lines`（`total`、各类行数、`coverage`）、`domains`（`domain`、`objects`、`attrs`、`defaults`、`lines`）、`layers`、`cross_layer`、`dangling`、`defaults`（`total` 默认值节点数、`key` 其他平台族默认值不同的个数、`items`：`node`、`owner`、`schema`、`value`、`others`）、`unknown_lines`、`check`（`summary`、`top`、`texts`）、`baseline`（`score`、`summary`、`failures`、`failure_count`、`texts`；基线规则有错时为 null）、`history`（`current`、`previous`（第一个版本时为 null）、`summary`、`items`）。`layers`：`layers`（各层对象 / 属性 / 默认值计数）、`features`、`nodes`（节点 → 层）、`features_of`、`cross`（`from`、`to`、`kind` contains / reference / prerequisite、`from_layer`、`to_layer`、`via`、`count`）、`cross_by_layers`、`outside`、`unclassified`。`script`：`lines`（`no`、`kind`、`text`、`depth`、`parent`、`node`、`layer`、`domain`、`card`、`spans`：`s` / `e` 字符区间、`t` kw / param / ref、`p` 参数名、`ref` 目标节点）、`refs`（目标 → 引用行）、`defs`（目标 → 定义行）、`defaults`（`node`、`owner`、`schema`、`value`、`after` 插在哪一行之后、`depth`、`text` 该平台的命令写法；`defaults=false` 时为空）。`graph`：同 `GET /devices/{id}/graph?raw=true` |
| `POST /analysis` | 是 | 分析一份配置文本（不需要先导入）：`{"text", "profile", "name", "parts", "defaults": true}`；返回结构同上（没有版本历史与忽略记录，`summary.history` 为 null） |
| `POST /compare` | 是 | 配置对比：`{"a": {"text": "…" \| "version_id": 1 \| "device_id": 1, "profile": null}, "b": {…}, "domain": null, "include_raw": false, "interface_map": {"GE0/2/1": "Gi0/0/1"}, "rename_threshold": 1.0, "hide_identity": false}`（每边给 `text`、`version_id`、`device_id`（最新版本）之一；同时给 `device_id` 与 `version_id` 时检查版本属于该设备）；返回 `diffs`（`kind` added / removed / changed / renamed、`node_kind` object / attr / ext / raw、`node` 规范编号、`schema`、`domain`、`a` / `b` 各自的 `node` 原始编号、`value` 有效值、`origin`、`lines`，改名的 `from` / `to` / `similarity`，删除或新增对象的 `count`，`related` 关联差异）、`renames`、`summary`（`total`、`by_kind`、`by_domain`、`by_object`、`unknown`、`default_only`）、`unknown`（两边的未识别行）、`default_only`（只有一侧 Profile 有默认值、不可比的属性）、`a` / `b`（来源、设备、Profile、版本）与 `options`；`hide_identity: true` 时隐藏设备身份差异（Router ID、接口 IPv4 地址、BGP 对等体地址、IS-IS NET、主机名等，清单见 `options.hidden_identity`），被隐藏的差异放在 `hidden_diffs`，个数为 `summary.hidden_identity`；设备或版本不存在时 404 |
| `GET /devices/{id}/versions` | 是 | 设备的配置版本列表（新的在前）：`id`、`seq`（设备内序号）、`source_name`、`collected_at`、`kb_version`、`lines`、`latest`；对比界面选“变更前后”用 |
| `POST /check` | 是 | 配置检查：`{"text": "…" 或 "device_id": 1, "profile": null, "severity": "info", "domain": null}`（`text` 与 `device_id` 二选一）；返回 `findings`（`rule`、`severity`、`domain`、`node`、`nodes`、`lines`、`message` / `suggestion` 为文案键 + 参数）、`summary`（`total` 含被忽略的发现，`ignored` 被忽略的个数；按级别、规则、功能域的计数与 `has_errors` 不含被忽略的）；按设备检查时每条发现带 `ignored`、`ignore_reason`、`ignore_id`、`texts`（规则文件文案的三种语言）；规则文件写错时 409，`data.issues` 为问题清单 |
| `GET /devices/{id}/check?severity=info&domain=D&version_id=V` | 是 | 检查设备的最新配置版本（给出 `version_id` 时检查该版本，版本不属于该设备时 404），结果同上 |
| `POST /cleanup` | 是 | 冗余清理：`{"text": "…" 或 "device_id": 1, "profile": null, "objects": null}`（`objects` 给出时只清理这些对象：只被选中对象引用的级联孤儿随之删除，只选级联孤儿而引用它的对象仍在时跳过，`skipped.reason` 为 `parent_kept`（附 `via`）、`not_orphan` 或 `maybe_referenced`；结果 `selected: true`）；返回待删除对象（`reason`：orphan / cascade）、按顺序的删除命令（`text`、`context` 所在视图、`object`、`lines`、`card`、`fallback`、`fallback_reason`：`no_undo` 命令卡没有取消语法 / `undo_invalid` 取消语法写错 / `render_failed` 用原行参数渲染不出 / `match_failed` 回匹配失败）、脚本文本 `script`、未删除的对象 `skipped` 与删除后验证 `verify` |
| `GET /devices/{id}/versions/{vid}/text` | 是 | 配置版本的原文（脱敏后）：`{text, version_id, device_id, source_name}`；版本不存在或不属于该设备时 404 |
| `GET /devices/{id}/delete-preview` | 是 | 删除设备的预览（REQ-038，不删除）：`device`（`id`、`name`、`vendor`、`profile`）、`counts`（`versions`、`imports`、`nodes`、`edges`、`unknown_lines`、`check_ignores`）、`baseline`（以它为基线的配置检查项目 `projects`：`id`、`name`、`version_id`、`follows_latest`、`scripts`（`id`、`name`、`kind`）；`scripts` 脚本总数）、`blocked`（有项目以它为基线，不加 `force` 删除会 409）、`versions`（旧的在前：`id`、`seq`、`latest`、`collected_at`、`tag`、`imports` 导入次数、`pinned_by` 固定这个版本作基线的项目编号）；设备不存在 404 |
| `DELETE /devices/{id}?force=false` | 是（登录账号都可以） | 删除设备与它的全部配置版本、快照、图、未识别行、导入记录、检查忽略项；返回 `deleted`、`device`、`counts`（同预览）、`baseline_cleared`（被清空基线的项目，结构同 `baseline.projects`）；设备是配置检查项目的基线且没有 `force=true` 时 409（`data` 为删除预览），`force=true` 时删除并清空这些项目的基线设备与版本（脚本与修订保留）；设备不存在 404；删除记入日志（操作者、设备、版本个数） |
| `DELETE /devices/{id}/versions/{vid}?force=false` | 是（登录账号都可以） | 删除一个配置版本：返回 `deleted`、`device_id`、`version`（`id`、`seq`、`latest`）、`latest_version_id`（删除后的最新版本）、`versions_left`、`counts`（`imports`、`nodes`、`edges`、`unknown_lines`）、`baseline_cleared`（固定这个版本作基线、已改为跟随最新版本的项目）、`baseline_moved`（删除的是最新版本时，跟随最新版本、基线随之变为上一个版本的项目）、`recomputed`（变化计数已重算的下一个版本编号，删除最新版本时为 null）；最后一个版本 409（请删除设备）；版本被项目固定为基线且没有 `force=true` 时 409（`data.baseline`）；设备或版本不存在、版本不属于该设备 404 |
| `GET /kb/rules` | 是 | 检查规则：内置检查与知识库 `rules/` 中的规则（编号、`enabled`、`severity`、`source`（`builtin` 或规则文件名）、内置检查的 `default_severity`、适用的 Schema 节点、条件，以及三种语言的标题、说明、建议） |
| `PUT /kb/rules/{rule_id}` | 是 | 修改规则的开关与级别：`{"enabled": false, "severity": "info"}`（至少给一项）；知识库规则写回所在的规则文件，内置检查写入覆盖文件 `rules/builtin.yaml`，并提交运行时知识库；返回更新后的规则（结构同 `GET /kb/rules` 的一条）；规则不存在 404，写回后规则文件校验不通过时恢复原文件并返回 409 |
| `GET /check/ignores?device_id=1` | 是 | 忽略的检查发现：`ignores`（`id`、`device_id`、`rule`、`node`、`reason`、`created_at`）；设备不存在时 404 |
| `POST /check/ignores` | 是 | 忽略一条检查发现：`{"device_id": 1, "rule": "ref.orphan", "node": "rp.policy[X]", "reason": "…"}`，按（设备、规则、节点）唯一，重复提交时更新原因（`created: false`）；`reason` 为空时 422，设备或规则不存在时 404 |
| `DELETE /check/ignores/{id}` | 是 | 取消忽略；记录不存在时 404 |
| `GET /templates` | 是 | 参数化模板列表：`id`、`version`、`title`、`description`、`profile`、`profiles`、`family`、`file`、`vars`（变量个数）、`blocks`、`valid`；有问题的模板 `valid: false` 并附 `issues` |
| `GET /templates/{id}` | 是 | 一个模板：元数据、`match`、`vars`（`name`、`type`、`block`、`derived`、`expr`、约束）、`blocks`（`kind` repeat / optional、`min`、`max`）、`body` 正文与 `source` 模板文件原文、`digest`；不存在时 404 |
| `PUT /templates/{id}` | 是 | 新建或修改模板：`{"source": "<模板 YAML>"}`；校验格式、变量、占位符并解析建图正文后写入运行时知识库并提交；有问题时 409，`data.issues` 为问题清单（`where`、`key`、`args`）；路径中的编号与内容不一致时 422 |
| `POST /templates/check` | 是 | 按模板校验配置：`{"template_id": "…" 或 "template": "<YAML>", "text": "…" 或 "version_id": 1 或 "device_id": 1, "profile": null, "label": null, "extra": null, "extra_scope": null}`；返回 `compliant`、`variables`、`blocks`（重复块为实例列表，含 `_node`、`_lines`）、`row`、`unresolved`、`findings`（`kind`、`severity`、`block`、`instance`、`node` 模板中的模式、`actual_node`、`expected`、`actual`、`actual_origin`、`var`、`problem`、`count`、`parent`、`lines`、`template_lines`）、`notes`、`warnings`、`summary`；模板有问题时 409 |
| `POST /templates/extract` | 是 | 按模板提取变量（参数同上）：`variables`、`blocks`、`row`（可直接作为生成参数的一行）、`compliant`、`summary` 与 error 级发现 |
| `POST /templates/draft` | 是 | 模板制作辅助：`{"configs": [{"label": "R1", "text": "…"}, …], "template_id": "draft", "title": null, "profile": null}`（最多 20 份，第一份为基准，平台族必须相同）；返回 `source`（模板草稿 YAML）、`vars`（`name`、`type`、`values` 各设备的取值、`reason`、`positions`）、`params`（每份配置一行）、`optional_candidates`、`repeat_candidates`、`notes`、`verify`（每份源配置按草稿校验的结果）、`valid` / `issues` |
| `POST /templates/generate` | 是 | 批量生成：`{"template_id" 或 "template", "rows": [{…}] 或 "csv": "…", "engine": "text" \| "canon", "target_profile": null, "verify": true, "include_text": true}`；返回每行的 `device`、`file`、`ok`、`text`、`params`（规范化后的参数）、`errors`（`stage` params / render / parse / roundtrip / template，`problem` 文案键与参数）、`checks`（`parse` 未识别行、`roundtrip`、`template` 校验与 `mismatched`、`canon` 渲染器写不出的节点）与 `summary`（`total`、`ok`、`failed`）；没有参数行时 422；`rule_set` / `rules` 只用于 `engine: canon` |
| `POST /reports` | 是 | 导出报告，直接返回文件（`Content-Disposition: attachment`）：`{"kind": "compare" \| "check", "lang": "zh-CN" \| "en", "format": "html" \| "md", "compare": <与 POST /compare 相同>, "check": <与 POST /check 相同>}`；HTML 是自包含单文件（内联样式、明亮配色、可打印），Markdown 适合贴进工单；文件名 `compare-<A>-<B>.<lang>.<ext>`、`check-<设备>.<lang>.<ext>`；报告头写设备、配置版本、软件版本、Profile、知识库版本、生成时间与选项；对比报告按功能域分表（两侧有效值、来源、原文行号），并单列改名、不可比（default_only）、未识别行；检查报告按严重度分组，被忽略的单列，有孤儿时附清理脚本；参数错误 422，设备不存在 404 |
| `GET /unknown-lines?limit=50` | 是 | 已导入配置中的未识别行汇总 |
| `GET /unknown-lines/states` | 是 | 各未识别行模式的送审状态（pending / approved / rejected） |
| `POST /unknown-lines/review` | 是 | 把选中的模式送入审核队列：`{"patterns": ["…"]}`；已送审的跳过 |
| `GET /summary` | 是 | 首页概况：知识库版本与草稿修改数、Profile 平均覆盖率、待审数、未识别行、设备（含用旧知识库解析过的数量）、最近一次样本回归、AI 状态 |
| `POST /devices/rebuild` | 管理员（旧路径）/ 属主 / 可编辑（项目路径） | 按当前知识库重新解析设备（后台任务，返回 `task_id`）：旧路径为全部设备，项目路径为本项目的设备 |
| `POST /devices/{id}/rebuild` | 是 | 按当前知识库重新解析一台设备 |
| `GET /regression/last` | 是 | 最近一次样本往返回归的结果；没跑过时为 `null` |
| `GET /tasks?kind=K&limit=20` | 是 | 最近的后台任务 |
| `GET /kb/schema` | 是 | Schema：各功能域的节点、依赖规则（`note` 为三语说明对象）、可用的节点类型 |
| `PUT /kb/schema/nodes/{id}` | 是 | 新增或修改节点：`{"parent", "type", "key", "semantic", "range", "choices", "ordered", "ref", "deprecated", "replaced_by"}`；写入后校验，会引入错误时自动撤销并返回 422 |
| `GET /kb/schema/nodes/{id}/usage` | 是 | 删除前检查：子节点、引用、依赖规则、Profile 条目、映射到它的命令卡 |
| `DELETE /kb/schema/nodes/{id}` | 是 | 删除节点；仍被使用时 409，`data` 为使用情况（可改为标记 `deprecated`） |
| `GET /kb/profiles` | 是 | Profile 列表：继承、条目数、覆盖率、可信度分布、设备数 |
| `POST /kb/profiles` | 是 | 新建 Profile：`{"id", "title", "family", "inherits", "version", "platform", "software"}`，继承时只写差异 |
| `GET /kb/profiles/{id}` | 是 | 继承展开后的全部条目（每个 Schema 节点一行，含来源 Profile 与可信度；enum 节点带 `choices`、有取值范围的 integer 节点带 `range`，供默认值输入使用） |
| `PUT /kb/profiles/{id}/entries/{node}` | 是 | 人工修改条目：`{"supported", "default", "show_rule", "source", "verified", "note"}`，标记 `manual`，重新汇总时保留 |
| `DELETE /kb/profiles/{id}/entries/{node}` | 是 | 删除 Profile 自己的条目（继承来的条目在父 Profile 中修改） |
| `GET /kb/profile-compare?a=A&b=B` | 是 | 两个 Profile 逐节点对比：same / only_a / only_b / default（默认值不同）/ unfilled |
| `GET /kb/draft` | 是 | 草稿区：上次发布以来的修改（与 `/kb/diff` 相同结构）与提交记录 |
| `GET /kb/extractors` | 是 | 可用的命令卡抽取规则 |
| `GET /ai/settings` | 管理员 | （已弃用，改用 `/ai/connections`）第一个管理员 AI 接口的内容与全局的 `timeout`、`max_tokens`；API Key 只返回是否已设置 |
| `PUT /ai/settings` | 管理员 | （已弃用）`{"provider", "base_url", "api_key", "clear_api_key", "model", "model_extract", "model_merge", "timeout", "max_tokens"}`：接口字段写入第一个管理员 AI 接口（没有时新建 `default`，允许公共使用；`provider` 为空表示停用它），`timeout`、`max_tokens` 写入配置文件 |
| `GET /projects?all=false&owner=U` | 是 | 我的项目（`mine`，属主）与共享给我的（`shared`，成员）；管理员 `all=true` 时另列出其他人的项目（`others`）。每个项目：`slug`、`name`、`owner`、`role`、`members`、`settings`（`style` 显示风格、`rule_set` 翻译规则集、`baseline` 安全基线）、`counts`（`devices`、`private`、`refs`、`scripts`、`scripts_with_errors`）、`last_activity`、`migrated_from`；`default_project` 为我的默认项目 |
| `POST /projects` | 是 | 新建项目：`{"name", "slug", "description", "settings"}`；`slug` 全站唯一（2–64 个小写字母、数字、短横线），不给时由名称生成；已被使用 409，不合法 422；还没有默认项目时它成为默认项目；没有创建权限 403（M9-8） |
| `GET /workspace` | 是 | 我的工作空间：默认项目（没有项目也不能创建时为 null）、项目数、私有模板与规则集数、有效的个人令牌数、`can_create` 能否新建项目 |
| `PUT /workspace/default-project` | 是 | 设置默认项目：`{"project"}`（旧的无项目接口与命令行不带 `--project` 时用它） |
| `GET /projects/{p}` | 项目成员 | 项目详情：另含 `member_list`（`username`、`role`、`since`）与 `overrides`（本项目的规则调整） |
| `PUT /projects/{p}` | 属主 / 管理成员 / 可编辑 | 修改名称、说明、设置：`{"name", "description", "settings", "slug", "discoverable"}`；改标识只限属主与管理员；`discoverable`（可被搜索，M9-8）限属主、管理成员与管理员 |
| `GET /projects/{p}/delete-preview` | 项目成员 | 删除项目的影响：私有设备与版本数、引用数（只解除）、检查项目与脚本数、忽略项、成员数 |
| `DELETE /projects/{p}?confirm=<标识>` | 属主 / 管理员 | 删除项目：私有设备与它们的全部版本一起删除，引用的公共设备只解除引用；`confirm` 必须等于项目标识（否则 422） |
| `GET /projects/{p}/members` | 项目成员 | 成员：属主与成员（`manage` / `edit` / `read`），加入时间 |
| `PUT /projects/{p}/members/{username}` | 属主 / 管理成员 / 管理员 | 添加成员或改角色：`{"role": "manage\|edit\|read"}`；账号不存在 404，已停用 409 |
| `DELETE /projects/{p}/members/{username}` | 属主 / 管理成员 / 管理员；本人 | 移除成员；成员移除自己即退出项目 |
| `GET /projects/{p}/join-requests?status=pending` | 属主 / 管理成员 / 管理员 | 加入申请（M9-8）：`username`、`role`（申请的）、`reason`、`via`（search / invite）、`invite_prefix`、`status`、`decided_by`、`decided_role`、`note` |
| `POST /projects/{p}/join-requests/{id}/approve` / `…/decline` | 属主 / 管理成员 / 管理员 | 通过（`{"role"}` 可改角色，可给 `manage`）/ 拒绝（`{"note"}`）；已处理过 409 |
| `GET /projects/{p}/invites` / `POST /projects/{p}/invites` / `DELETE /projects/{p}/invites/{id}` | 属主 / 管理成员 / 管理员 | 邀请链接：列表（`prefix`、`role`、`requires_approval`、`expires_at`、`uses`、`state`）/ 新建（`{"role", "days": 1–90, "requires_approval", "note"}`，返回的 `token` 与 `path` 只出现这一次，服务器只存 SHA-256）/ 撤销 |
| `POST /projects/{p}/transfer` | 属主 / 管理员 | 转交（管理成员不能）：`{"to", "keep_as": "manage\|edit\|read\|null"}`；原属主默认留作可编辑成员；项目设置中用到的、原属主私有的翻译规则集复制一份给新属主（`rule_set_copied`） |
| `POST /projects/{p}/copy` | 项目成员 | 复制为我的新项目：`{"name", "slug", "devices", "scripts"}`；复制设置、规则调整、私有设备（各复制当前版本）、引用（同样的版本策略）、脚本（当前内容）；不复制成员 |
| `GET /projects/{p}/refs` | 项目成员 | 本项目引用的公共设备：`policy`、`pinned_version_id`、`pinned_seq`（固定版本的序号）、`public_latest_version_id`、`newer_available` |
| `POST /projects/{p}/refs` | 属主 / 可编辑 | 引用公共设备：`{"device_id", "version_id"}`（不给版本时跟随最新）；项目里已有同名设备 409 |
| `PUT /projects/{p}/refs/{device_id}` | 属主 / 可编辑 | 改版本策略：`{"version_id": 编号 \| null}`（null 为跟随最新） |
| `DELETE /projects/{p}/refs/{device_id}` | 属主 / 可编辑 | 解除引用（本项目对它的忽略项一并删除，以它为基线的检查项目基线置空）；`DELETE /projects/{p}/devices/{id}` 对引用的公共设备也是解除引用 |
| `POST /projects/{p}/devices/copy-in` | 属主 / 可编辑 | 把公共设备或自己能查看的其他项目的设备复制为本项目的私有设备：`{"device_id", "version_id", "name"}`；只复制一个版本（默认来源中的当前版本），同名时自动加 `-2`、`-3`（`renamed`），`from` 记录来源 |
| `GET /projects/{p}/rules` | 项目成员 | 检查规则在本项目中的设置：共享的级别与开关、本项目的调整（`override`）、生效值（`effective`） |
| `PUT /projects/{p}/rules/{rule}` | 属主 / 可编辑 | 本项目关闭某条规则或改级别：`{"enabled", "severity", "reason"}`，原因必填；只影响本项目的检查（`checks` 结果中带 `project_override`） |
| `DELETE /projects/{p}/rules/{rule}` | 属主 / 可编辑 | 恢复为共享规则的设置 |
| `GET /projects/{p}/scripts?kind=&device_id=` | 项目成员 | 本项目全部脚本（平铺）：所在的检查项目（`group`）、基线设备与版本策略、最近一次检查、顺序核查、AI、修订数、最后修改人 |
| `POST /projects/{p}/scripts` | 属主 / 可编辑 | 新建脚本：`{"name", "kind", "device_id", "version_id", "content", "order_check", "ai_check"}`；同时建一个保存基线与检查设置的检查项目，返回 `group` 与 `script` |
| `GET /projects/{p}/networks` | 项目成员 | 网络（M9）：`networks`（`id`、`slug`、`name`、`color`、`default`、`description`、`folder_id` / `folder`、`position`、`copied_from`、`last_activity`、`created_by`、`counts`：`devices`、`shared`（与其他网络共用）、`pinned`、`scripts`、`scripts_with_errors`、`check_groups`、`ai_pending`、`annotations`、`ignores`、`overrides`、`rules`、`findings`（`error` / `warning` / `info`、`devices_checked`、`last_run`））、`folders`、`palette`、`overview`（`devices`、`networks`、`in_several`、`only_default`、`imported_today`、`joined_by_rule_today`） |
| `POST /projects/{p}/networks` | 属主 / 可编辑 | 新建网络：`{"name", "slug", "description", "color", "folder_id", "device_ids", "policy": "follow\|pin", "rules": [{"kind": "name\|subnet", "pattern", "apply_existing"}]}`；标识在项目内唯一（重名 409），颜色不给时自动分配，不在 8 色里 422 |
| `GET /projects/{p}/networks/{net}` | 项目成员 | 网络详情：同上，另含 `rules` |
| `PUT /projects/{p}/networks/{net}` | 属主 / 可编辑 | 改名、标识、说明、颜色、文件夹（`folder_id`；`folder_id: null` 加 `move: true` 移出文件夹）、位置；默认网络可以改名 |
| `GET /projects/{p}/networks/{net}/delete-preview` | 项目成员 | 删除会一起删除的工作数据：`members`、`rules`、`annotations`、`ignores`、`overrides`、`check_groups`、`scripts`、`revisions`、`ai_batches`、`ai_suggestions`、`ai_adopted`；`deletable`（默认网络为 false） |
| `DELETE /projects/{p}/networks/{net}?confirm=<名称>` | 属主 / 可编辑 | 删除网络与它的工作数据（不进回收站，不删设备）；`confirm` 必须等于网络名称或标识（否则 422）；默认网络 409 |
| `POST /projects/{p}/networks/{net}/copy` | 属主 / 可编辑 | 复制网络：`{"name", "slug", "color", "folder_id"}`；复制成员与版本选择、自动加入规则与排除、视图标注、检查忽略、规则调整、脚本组与脚本（含全部修订）、已采纳（与已撤销）的 AI 建议与采纳记录（`note` 与 `adopt_info.copied_from` 注明复制自哪里），不复制待处理与已忽略的建议；返回体 `copied` 为各类计数，`copied_from` 为来源 |
| `POST /projects/{p}/network-folders` / `PUT …/{id}` / `DELETE …/{id}` | 属主 / 可编辑 | 文件夹：新建 `{"name"}`、改名或排序 `{"name", "position"}`、删除（里面的网络移到最外层，`moved`） |
| `GET /projects/{p}/networks/{net}/members` | 项目成员 | 成员：`device_id`、`name`、`vendor`、`platform`、`profile`、`source`、`versions`、`latest_version_id` / `latest_seq`（项目里的当前版本）、`policy`（follow / pin）、`version_id` / `seq`（本网络用的版本）、`newer_available`、`also_in`（还在哪些网络）、`join_source`（upgrade / default / manual / rule / suggestion / copy / import）、`rule`、`joined_by`、`joined_at`、`mgmt_address` |
| `POST /projects/{p}/networks/{net}/members` | 属主 / 可编辑 | 从项目设备池加入：`{"device_ids", "policy": "follow\|pin"}`（pin 固定在当前最新）；手工加入会清除排除；不在设备池 404 |
| `PUT /projects/{p}/networks/{net}/members` | 属主 / 可编辑 | 改版本策略（可批量）：`{"device_ids", "policy", "version_id"}`；`version_id` 只能配一台设备 |
| `POST /projects/{p}/networks/{net}/members/remove` / `…/unexclude` | 属主 / 可编辑 | 移出（可批量，记为排除，自动加入规则不再加入；默认网络 409）/ 撤销排除 |
| `GET /projects/{p}/networks/{net}/join-rules` | 项目成员 | 自动加入规则（`kind` name 设备名通配 / subnet 管理网段 CIDR）、`excluded`（排除的设备）、`all_new_devices`（默认网络为 true） |
| `POST /projects/{p}/networks/{net}/join-rules` / `PUT …/{id}` / `DELETE …/{id}` | 属主 / 可编辑 | 添加（`apply_existing` 同时加入现在命中的设备，返回 `added`）/ 修改 / 删除规则（已加入的设备不受影响）；默认网络不需要规则（409），重复的规则 409 |
| `POST /projects/{p}/networks/{net}/join-rules/preview` | 项目成员 | 命中预览：`{"kind", "pattern"}` → `matches`、`not_in_network`、`excluded`、`devices`（`state` member / outside / excluded，`mgmt_address`） |
| `GET /projects/{p}/network-suggestions?basis=&ignore_mgmt=&protocol=&regex=&prefix=` | 项目成员 | 建网建议（代码计算、不入库）：`basis` 为 components 连通分量（`ignore_mgmt` 不算管理口链路）/ igp（`protocol` all / isis / ospf，按 IS-IS 进程与 OSPF 进程 + 区域）/ bgp（本地 AS）/ name（`regex` 第一个括号，默认 `^(.+)-[^-]+$`）/ subnet（管理地址按 `prefix` 汇总）/ ai（M8 拓扑整理已采纳的分组，代码校验设备在项目里、组内连通）；每个建议：`key`、`name`、`slug`、`devices`、`count`、`overlap_existing`、`same_as`（与现有网络完全相同）、`overlap_suggestions`、`overlap_devices`、`rule`（name / subnet 可作自动加入规则）、`check`、`adoptable`；ai 依据另有 `source`（最近一次拓扑整理）与 `ai_configured` |
| `POST /projects/{p}/network-suggestions/adopt` | 属主 / 可编辑 | 采纳：`{"basis", "params", "keys", "with_rules", "folder_id", "names"}`；按同样的依据与参数重新计算，`keys` 为空时采纳全部可采纳的；每个建议建一个网络（成员加入方式 suggestion）；返回 `created`、`skipped`（`same_as_existing` / `check_failed` / `empty` / `not_found`） |
| `POST /projects/{p}/devices/rebuild` | 属主 / 可编辑 | 按当前知识库重新解析本项目的设备（后台任务）；旧路径 `POST /devices/rebuild` 为全部设备，只限管理员 |
| `GET /public-devices` | 是 | 公共设备库：版本数、最新版本、引用它的项目（普通账号只看到自己能访问的项目）、跟随 / 固定的引用数 |
| `GET /public-devices/{id}/versions` | 是 | 公共设备的版本（新的在前） |
| `POST /public-devices` | 管理员 | 导入到公共设备库（multipart `files`、`level`）；同名设备作为新版本，跟随最新的项目随之更新 |
| `DELETE /public-devices/{id}?force=false` | 管理员 | 删除公共设备；还有项目引用时 409（`data.projects`），`force=true` 一并解除引用 |
| `DELETE /public-devices/{id}/versions/{vid}` | 管理员 | 删除公共设备的一个版本；固定在该版本的引用改为跟随最新 |
| `POST /public-devices/rebuild` | 管理员 | 按当前知识库重新解析公共设备库（后台任务） |
| `GET /discover?q=` | 是 | 可被搜索的项目（M9-8）：只有 `ref`、`name`、`description`、`owner`、`devices` 与我的状态 `my_status`（owner / member / pending / declined / none） |
| `POST /discover/{编号或属主~标识}/join-requests` | 是（有账号） | 申请加入：`{"role": "read\|edit", "reason"}`；不可被搜索或不存在 404，已是成员或已有待审批的申请 409 |
| `GET /me/join-requests` / `DELETE /me/join-requests/{id}` | 是 | 我提交的加入申请 / 撤回 |
| `GET /me/create-permission` / `POST /me/create-permission/request` / `DELETE …/request` | 是 | 我能否新建项目（`can_create`、`open` 总开关、`granted` 单独授权、`request`）/ 申请创建权限 / 撤回 |
| `GET /me/notifications` | 是 | 等我处理的：我是属主或管理成员的项目里待审批的加入申请（`by_project`），管理员另有 `create_requests` |
| `GET /invites/{token}` / `POST /invites/{token}/accept` | 是（有账号） | 打开邀请链接（项目公开信息、角色、是否需审批、`state`）/ 加入：`status` 为 joined / pending / member；无效 404，过期或撤销 409 |
| `GET /admin/create-requests` / `POST /admin/create-requests/{id}/approve` / `…/decline` | 管理员 | 创建权限的申请与处理（通过即单独授权）；单独授权也可用 `PUT /users/{username}` 的 `can_create_projects` |
| `GET /admin/projects` | 管理员 | 所有项目：属主（`owner_disabled` 标出属主已停用）、成员、计数、最近活动；`owners`、`with_members`、`owner_disabled` 汇总 |
| `GET /admin/audit?project=&limit=200` | 管理员 | 访问审计：管理员进入（只读访问同一项目 30 分钟记一次）或修改他人项目、转交、删除；`at`、`actor`、`project`、`action`（enter / write / transfer / delete）、`detail`（方法与路由，不含请求内容） |
| `GET /users/{username}/projects` | 管理员 | 账号拥有的非空项目（删除账号前选择转交或一并删除） |
| `GET /tokens` | 是（账号） | 我的个人令牌：`name`、`prefix`（前 8 个字符）、`read_only`、`created_at`、`expires_at`、`last_used_at`、`last_used_ip`、`state`（active / expired / revoked）；不含令牌本身；全局令牌调用 409 |
| `POST /tokens` | 是（账号） | 生成个人令牌：`{"name", "read_only": false, "days": 90}`（`days` 为 0 或 null 表示不过期）；返回的 `token` 只出现这一次 |
| `POST /tokens/{id}/revoke` | 是（账号） | 撤销令牌（立即失效） |
| `DELETE /tokens/{id}` | 是（账号） | 从列表移除已撤销或已过期的令牌；有效的令牌 409 |
| `POST /kb/suggestions` | 是 | 对知识库提建议：`{"target", "kind": "default\|syntax\|description\|other", "current", "proposed", "reason", "project"}`；进入审核队列（类型 `suggestion`），维护员通过（采纳，知识库在对应页面修改）或驳回（`note` 为原因） |
| `GET /kb/suggestions?mine=true&status=all` | 是 | 建议列表：默认只看自己提的（含处理结果与驳回原因）；`mine=false` 只限维护员与管理员 |

## 示例

以下示例由 `tests/cases/api_cases.toml` 生成，测试通过即说明示例可用。Windows 下 curl 的引号规则不同，请使用 PowerShell 写法。

<!-- examples:begin -->

### 健康检查（不需要认证）

`GET /api/v1/health`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/health'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/health'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/health')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.configured` = `true`

### 未配置时读取向导参数

`GET /api/v1/setup`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/setup'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/setup'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/setup')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`

### 向导输入即校验：端口超出范围

`POST /api/v1/setup`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/setup' \
  -H 'Content-Type: application/json' \
  -d '{"language": "zh-CN", "dry_run": true, "values": {"server.port": 70000}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/setup' -ContentType 'application/json; charset=utf-8' -Body '{"language": "zh-CN", "dry_run": true, "values": {"server.port": 70000}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/setup', json={'language': 'zh-CN', 'dry_run': True, 'values': {'server.port': 70000}})
print(r.status_code, r.json())
```

HTTP 状态：`422`；返回中的关键字段：

- `code` = `1001`

### 提交向导结果

`POST /api/v1/setup`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/setup' \
  -H 'Content-Type: application/json' \
  -d '{"language": "en", "values": {"server.port": 9000, "security.api_token": "my-token-123456"}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/setup' -ContentType 'application/json; charset=utf-8' -Body '{"language": "en", "values": {"server.port": 9000, "security.api_token": "my-token-123456"}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/setup', json={'language': 'en', 'values': {'server.port': 9000, 'security.api_token': 'my-token-123456'}})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.api_token` = `"my-token-123456"`
- `data.token_generated` = `false`

### 已配置时不能再提交向导

`GET /api/v1/setup`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/setup'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/setup'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/setup')
print(r.status_code, r.json())
```

HTTP 状态：`409`；返回中的关键字段：

- `code` = `1003`

### 向导里测试 AI 接口：先检查必填项（OpenAI 兼容接口要地址、模型名必填），不发请求

`POST /api/v1/setup/ai-test`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/setup/ai-test' \
  -H 'Content-Type: application/json' \
  -d '{"provider": "openai", "base_url": "", "api_key": "sk-test", "model": ""}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/setup/ai-test' -ContentType 'application/json; charset=utf-8' -Body '{"provider": "openai", "base_url": "", "api_key": "sk-test", "model": ""}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/setup/ai-test', json={'provider': 'openai', 'base_url': '', 'api_key': 'sk-test', 'model': ''})
print(r.status_code, r.json())
```

HTTP 状态：`422`；返回中的关键字段：

- `code` = `1001`
- `data.errors.ai.base_url` = `"必须填写"`
- `data.errors.ai.model` = `"必须填写"`

### 系统设置（管理员）：按向导的分组列出全部配置项，带当前值、来源、是否需重启、只读原因（REQ-049）

`GET /api/v1/settings`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/settings' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/settings' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/settings', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.groups.0.id` = `"ui"`
- `data.groups.1.fields.0.key` = `"server.host"`
- `data.groups.1.fields.0.restart` = `true`
- `data.restart_pending` = `[]`

### 保存系统设置：写入 config/config.toml；改了端口要重启，restart_pending 列出（不自动重启）

`PUT /api/v1/settings`（需要令牌）

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/settings' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"values": {"server.port": 9123, "history.keep": 80}}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/settings' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"values": {"server.port": 9123, "history.keep": 80}}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/settings', headers={'Authorization': 'Bearer <令牌>'}, json={'values': {'server.port': 9123, 'history.keep': 80}})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.changed.0` = `"history.keep"`
- `data.restart_pending.0.key` = `"server.port"`
- `data.restart_pending.0.saved` = `9123`

### 保存系统设置：取值不合格时逐项返回原因，不写入

`PUT /api/v1/settings`（需要令牌）

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/settings' \
  -H 'Accept-Language: en' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"values": {"server.port": 70000, "security.api_token": "x"}}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/settings' -Headers @{'Accept-Language'='en'; 'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"values": {"server.port": 70000, "security.api_token": "x"}}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/settings', headers={'Accept-Language': 'en', 'Authorization': 'Bearer <令牌>'}, json={'values': {'server.port': 70000, 'security.api_token': 'x'}})
print(r.status_code, r.json())
```

HTTP 状态：`422`；返回中的关键字段：

- `code` = `1001`
- `data.errors.server.port` = `"Out of range"`
- `data.errors.security.api_token` = `"Sensitive values can only be changed in the config file or an environment variable"`

### 读取生效的配置（需要令牌）

`GET /api/v1/config`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/config' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/config' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/config', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.values.security.api_token` = `true`

### 缺少令牌

`GET /api/v1/config`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/config'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/config'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/config')
print(r.status_code, r.json())
```

HTTP 状态：`401`；返回中的关键字段：

- `code` = `1002`

### 脱敏一段配置文本

`POST /api/v1/sanitize`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/sanitize' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "sysname PE-01\n#\nbgp 65000\n peer 203.0.113.10 password cipher %^%#Fake%^%#\n#\nreturn", "level": "basic"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/sanitize' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "sysname PE-01\n#\nbgp 65000\n peer 203.0.113.10 password cipher %^%#Fake%^%#\n#\nreturn", "level": "basic"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/sanitize', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'sysname PE-01\n#\nbgp 65000\n peer 203.0.113.10 password cipher %^%#Fake%^%#\n#\nreturn', 'level': 'basic'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.vendor` = `"huawei"`
- `data.summary.secret` = `1`
- `data.summary.ip` = `1`

### 上传并导入配置文件

`POST /api/v1/configs`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/configs' \
  -H 'Authorization: Bearer <令牌>' \
  -F 'files=@tests/inputs/configs/huawei/basic.cfg' \
  -F 'files=@tests/inputs/configs/bad/notes.txt' \
  -F 'level=strict'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/configs' -Headers @{'Authorization'='Bearer <令牌>'} -Form @{'files'=Get-Item 'tests/inputs/configs/huawei/basic.cfg'; 'level'='strict'}
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/configs', headers={'Authorization': 'Bearer <令牌>'}, files=[('files', open('tests/inputs/configs/huawei/basic.cfg', 'rb')), ('files', open('tests/inputs/configs/bad/notes.txt', 'rb'))], data={'level': 'strict'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.files.0.ok` = `true`
- `data.files.0.vendor` = `"huawei"`
- `data.files.1.ok` = `false`

### 列出已导入的设备

`GET /api/v1/devices`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/devices' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/devices' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/devices', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.devices` = `[]`

### 校验知识库

`POST /api/v1/kb/validate`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/kb/validate' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/kb/validate' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/kb/validate', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.errors` = `0`

### 发布知识库版本

`POST /api/v1/kb/releases`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/kb/releases' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"message": "primeira versão"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/kb/releases' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"message": "primeira versão"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/kb/releases', headers={'Authorization': 'Bearer <令牌>'}, json={'message': 'primeira versão'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.version` = `"0.1.0"`

### 已发布的版本与提交历史

`GET /api/v1/kb/releases`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/kb/releases' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/kb/releases' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/kb/releases', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.releases` = `[]`

### 对比不存在的版本

`GET /api/v1/kb/diff?from=9.9.9`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/kb/diff?from=9.9.9' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/kb/diff?from=9.9.9' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/kb/diff?from=9.9.9', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 覆盖矩阵

`GET /api/v1/kb/coverage`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/kb/coverage' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/kb/coverage' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/kb/coverage', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`

### 审核队列

`GET /api/v1/review`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/review' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/review' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/review', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.total` = `0`

### 审核不存在的条目

`POST /api/v1/review/999`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/review/999' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"action": "approve"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/review/999' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"action": "approve"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/review/999', headers={'Authorization': 'Bearer <令牌>'}, json={'action': 'approve'})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 导入不存在的文档目录

`POST /api/v1/kb/ingest`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/kb/ingest' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"doc_dir": "/no/such/dir", "rules": "huawei-vrp8-md"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/kb/ingest' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"doc_dir": "/no/such/dir", "rules": "huawei-vrp8-md"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/kb/ingest', headers={'Authorization': 'Bearer <令牌>'}, json={'doc_dir': '/no/such/dir', 'rules': 'huawei-vrp8-md'})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 查询不存在的任务

`GET /api/v1/tasks/nope`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/tasks/nope' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/tasks/nope' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/tasks/nope', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 批量通过

`POST /api/v1/review/batch`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/review/batch' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"kind": "card", "contains": "vpn-target"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/review/batch' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"kind": "card", "contains": "vpn-target"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/review/batch', headers={'Authorization': 'Bearer <令牌>'}, json={'kind': 'card', 'contains': 'vpn-target'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.approved` = `0`

### AI 状态

`GET /api/v1/ai/status`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/ai/status' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/ai/status' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/ai/status', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.configured` = `false`

### 测试 AI 接口（未配置）

`POST /api/v1/ai/test`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/ai/test' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/ai/test' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/ai/test', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`409`；返回中的关键字段：

- `code` = `1003`

### 解析配置文本

`POST /api/v1/parse`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/parse' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "hostname R1\n!\nrouter bgp 65000\n neighbor 10.0.0.2 remote-as 65001\n!\nend"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/parse' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "hostname R1\n!\nrouter bgp 65000\n neighbor 10.0.0.2 remote-as 65001\n!\nend"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/parse', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'hostname R1\n!\nrouter bgp 65000\n neighbor 10.0.0.2 remote-as 65001\n!\nend'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.profile` = `"cisco-iosxe-asr920-17.15"`
- `data.counts.command` = `2`
- `data.counts.raw` = `1`

### 往返测试一段配置

`POST /api/v1/roundtrip`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/roundtrip' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nreturn"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/roundtrip' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nreturn"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/roundtrip', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nreturn'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.ok` = `true`
- `data.unknown` = `0`

### 渲染回配置文本

`POST /api/v1/render`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/render' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "sysname R1\n#\nbgp 65000\n peer 10.0.0.1 as-number 65001\n#\nreturn"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/render' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "sysname R1\n#\nbgp 65000\n peer 10.0.0.1 as-number 65001\n#\nreturn"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/render', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'sysname R1\n#\nbgp 65000\n peer 10.0.0.1 as-number 65001\n#\nreturn'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.text` = `"sysname R1\n#\nbgp 65000\n peer 10.0.0.1 as-number 65001\n#\nreturn"`

### 设备不存在

`GET /api/v1/devices/999/graph`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/devices/999/graph' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/devices/999/graph' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/devices/999/graph', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 未识别行汇总

`GET /api/v1/unknown-lines`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/unknown-lines' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/unknown-lines' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/unknown-lines', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.patterns` = `[]`

### 管理员 AI 接口列表

`GET /api/v1/ai/connections`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/ai/connections' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/ai/connections' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/ai/connections', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.connections.0.name` = `"shared"`
- `data.connections.0.public` = `true`
- `data.connections.0.api_key_set` = `true`

### 新建管理员 AI 接口

`POST /api/v1/ai/connections`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/ai/connections' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"name": "lab", "provider": "local", "base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5", "public": true}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/ai/connections' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"name": "lab", "provider": "local", "base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5", "public": true}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/ai/connections', headers={'Authorization': 'Bearer <令牌>'}, json={'name': 'lab', 'provider': 'local', 'base_url': 'http://127.0.0.1:11434/v1', 'model': 'qwen2.5', 'public': True})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.name` = `"lab"`
- `data.public` = `true`
- `data.api_key_set` = `false`

### 关闭接口的公共使用

`PUT /api/v1/ai/connections/1`（需要令牌）

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/ai/connections/1' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"public": false}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/ai/connections/1' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"public": false}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/ai/connections/1', headers={'Authorization': 'Bearer <令牌>'}, json={'public': False})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.public` = `false`

### 我的 AI：选择、个人接口（不含 Key）、可选接口与生效来源

`GET /api/v1/me/ai`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/me/ai'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/me/ai'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/me/ai')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.choice` = `"personal"`
- `data.personal.api_key_set` = `true`
- `data.options.0.name` = `"shared"`
- `data.effective.source` = `"personal"`

### 改用公共接口

`PUT /api/v1/me/ai`

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/me/ai' \
  -H 'Content-Type: application/json' \
  -d '{"choice": "connection", "connection_id": 1}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/me/ai' -ContentType 'application/json; charset=utf-8' -Body '{"choice": "connection", "connection_id": 1}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/me/ai', json={'choice': 'connection', 'connection_id': 1})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.choice` = `"connection"`
- `data.effective.connection.name` = `"shared"`

### AI 状态带生效来源

`GET /api/v1/ai/status`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/ai/status'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/ai/status'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/ai/status')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.configured` = `true`
- `data.effective.source` = `"connection"`
- `data.effective.connection.name` = `"shared"`

### AI 用量统计

`GET /api/v1/ai/usage?from=2026-10-01&to=2026-10-19`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/ai/usage?from=2026-10-01&to=2026-10-19' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/ai/usage?from=2026-10-01&to=2026-10-19' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/ai/usage?from=2026-10-01&to=2026-10-19', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.scope` = `"all"`
- `data.from` = `"2026-10-01"`
- `data.totals.calls` = `0`

### 手工标注设备角色（来源 user，优先于 AI 建议）

`PUT /api/v1/projects/alice~lab/view-annotations`

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/projects/alice~lab/view-annotations' \
  -H 'Content-Type: application/json' \
  -d '{"target_type": "device", "target": "1", "key": "role", "value": "core"}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/view-annotations' -ContentType 'application/json; charset=utf-8' -Body '{"target_type": "device", "target": "1", "key": "role", "value": "core"}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/view-annotations', json={'target_type': 'device', 'target': '1', 'key': 'role', 'value': 'core'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.item.target` = `"1"`
- `data.item.key` = `"role"`
- `data.item.value` = `"core"`
- `data.item.source` = `"user"`

### 变化解读的覆盖核对：这个范围还没有运行时为空

`GET /api/v1/projects/alice~lab/ai/suggestions/coverage?skill=diff-explain&scope=history:1:3`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/coverage?skill=diff-explain&scope=history:1:3'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/coverage?skill=diff-explain&scope=history:1:3'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/coverage?skill=diff-explain&scope=history:1:3')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.prefix` = `"c"`
- `data.total` = `0`
- `data.covered` = `[]`
- `data.uncovered` = `[]`

### 运行变化解读（版本历史的两个快照）：未配置 AI 时 409

`POST /api/v1/projects/alice~lab/ai/suggestions/run`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/run' \
  -H 'Content-Type: application/json' \
  -d '{"skill": "diff-explain", "params": {"source": "history", "device_id": 1, "a_version": 1, "b_version": 3}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/run' -ContentType 'application/json; charset=utf-8' -Body '{"skill": "diff-explain", "params": {"source": "history", "device_id": 1, "a_version": 1, "b_version": 3}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/run', json={'skill': 'diff-explain', 'params': {'source': 'history', 'device_id': 1, 'a_version': 1, 'b_version': 3}})
print(r.status_code, r.json())
```

HTTP 状态：`409`；返回中的关键字段：

- `code` = `1003`
- `data.status` = `"not_configured"`

### 问题解读与修复：运行前估计发送量（检查页的单台设备）

`POST /api/v1/projects/alice~lab/ai/suggestions/estimate`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/estimate' \
  -H 'Content-Type: application/json' \
  -d '{"skill": "finding-fix", "params": {"source": "check", "device_id": 1}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/estimate' -ContentType 'application/json; charset=utf-8' -Body '{"skill": "finding-fix", "params": {"source": "check", "device_id": 1}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/estimate', json={'skill': 'finding-fix', 'params': {'source': 'check', 'device_id': 1}})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.skill` = `"finding-fix"`
- `data.warn` = `false`

### 变更意图转脚本：未配置 AI 时 409（增量变更照常可用“目标配置”方式）

`POST /api/v1/projects/alice~lab/ai/suggestions/run`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/run' \
  -H 'Content-Type: application/json' \
  -d '{"skill": "intent-script", "device_id": 1, "params": {"intent": "把 GigabitEthernet0/2/2 的描述改为 OAM-UPLINK"}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/run' -ContentType 'application/json; charset=utf-8' -Body '{"skill": "intent-script", "device_id": 1, "params": {"intent": "把 GigabitEthernet0/2/2 的描述改为 OAM-UPLINK"}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/run', json={'skill': 'intent-script', 'device_id': 1, 'params': {'intent': '把 GigabitEthernet0/2/2 的描述改为 OAM-UPLINK'}})
print(r.status_code, r.json())
```

HTTP 状态：`409`；返回中的关键字段：

- `code` = `1003`
- `data.status` = `"not_configured"`

### 翻译结果中采纳的 AI 写法（还没有采纳时为空）

`GET /api/v1/projects/alice~lab/ai/translate-patches?device_id=1&to=cisco-iosxe-asr920-17.15`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/translate-patches?device_id=1&to=cisco-iosxe-asr920-17.15'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/translate-patches?device_id=1&to=cisco-iosxe-asr920-17.15'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/translate-patches?device_id=1&to=cisco-iosxe-asr920-17.15')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.items` = `[]`

### skill 能否在当前 AI 接口上运行：脱敏复核只允许本地模型（未配置 AI 时由“未配置”的提示处理）

`GET /api/v1/projects/alice~lab/ai/kb/gate?skill=sanitize-review`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/kb/gate?skill=sanitize-review'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/kb/gate?skill=sanitize-review'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/kb/gate?skill=sanitize-review')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.skill` = `"sanitize-review"`
- `data.local_only` = `true`
- `data.allowed` = `true`

### 本项目的脱敏补充（采纳的脱敏复核建议）

`GET /api/v1/projects/alice~lab/ai/kb/sanitize-redact`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/kb/sanitize-redact'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/kb/sanitize-redact'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/kb/sanitize-redact')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.patterns` = `[]`

### 可生成建议的 skill 与 AI 是否可用（入口按钮据此显示不可用的原因）

`GET /api/v1/projects/alice~lab/ai/suggestions/skills`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/skills'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/skills'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/skills')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.ai.configured` = `false`
- `data.ai.reason` = `"no_public"`
- `data.skills.0.id` = `"device-summary"`
- `data.skills.0.categories` = `["text_only"]`
- `data.skills.1.id` = `"topology-roles"`
- `data.skills.1.scope` = `"project"`

### 运行 skill：未配置 AI 时 409（data.reason 给出原因）

`POST /api/v1/projects/alice~lab/ai/suggestions/run`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/run' \
  -H 'Content-Type: application/json' \
  -d '{"skill": "topology-roles"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/run' -ContentType 'application/json; charset=utf-8' -Body '{"skill": "topology-roles"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/run', json={'skill': 'topology-roles'})
print(r.status_code, r.json())
```

HTTP 状态：`409`；返回中的关键字段：

- `code` = `1003`
- `data.status` = `"not_configured"`
- `data.reason` = `"no_public"`

### 建议列表：内容、引用（可跳转）、代码校验结果、状态与计数

`GET /api/v1/projects/alice~lab/ai/suggestions?skill=topology-roles`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions?skill=topology-roles'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions?skill=topology-roles'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions?skill=topology-roles')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.total` = `3`
- `data.counts.pending` = `3`
- `data.items.0.id` = `3`
- `data.items.0.check_status` = `"reject"`
- `data.items.0.check.reasons.0.code` = `"ref_not_found"`
- `data.items.1.check_status` = `"pass"`
- `data.items.1.category` = `"view_hint"`
- `data.items.1.refs.0.found` = `true`

### 某台设备的建议：设备摘要（数字与对象名由代码填入 check.display）

`GET /api/v1/projects/alice~lab/ai/suggestions?skill=device-summary&check=pass`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions?skill=device-summary&check=pass'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions?skill=device-summary&check=pass'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions?skill=device-summary&check=pass')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.total` = `1`
- `data.items.0.id` = `4`
- `data.items.0.category` = `"text_only"`
- `data.items.0.refs.0.type` = `"vrf.instance"`

### 采纳一条建议（视图标注写入项目）

`POST /api/v1/projects/alice~lab/ai/suggestions/1/adopt`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/1/adopt' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/1/adopt' -ContentType 'application/json; charset=utf-8' -Body '{}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/1/adopt', json={})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.status` = `"adopted"`
- `data.adopt_info.action` = `"annotate"`
- `data.adopt_info.key` = `"role"`
- `data.adopt_info.value` = `"access"`
- `data.decided_by` = `"alice"`

### 编辑后采纳：先重新校验，不合格 409（data.check）

`POST /api/v1/projects/alice~lab/ai/suggestions/2/adopt`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/2/adopt' \
  -H 'Content-Type: application/json' \
  -d '{"content": {"target": "d2", "key": "role", "value": "router"}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/2/adopt' -ContentType 'application/json; charset=utf-8' -Body '{"content": {"target": "d2", "key": "role", "value": "router"}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/2/adopt', json={'content': {'target': 'd2', 'key': 'role', 'value': 'router'}})
print(r.status_code, r.json())
```

HTTP 状态：`409`；返回中的关键字段：

- `code` = `1003`
- `data.check.status` = `"reject"`
- `data.check.reasons.0.code` = `"bad_hint_value"`

### 按类别批量采纳：只采纳校验通过的

`POST /api/v1/projects/alice~lab/ai/suggestions/adopt-batch`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/adopt-batch' \
  -H 'Content-Type: application/json' \
  -d '{"category": "view_hint", "skill": "topology-roles"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/adopt-batch' -ContentType 'application/json; charset=utf-8' -Body '{"category": "view_hint", "skill": "topology-roles"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/adopt-batch', json={'category': 'view_hint', 'skill': 'topology-roles'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.adopted` = `[1, 2]`
- `data.skipped.0.id` = `3`
- `data.skipped.0.check_status` = `"reject"`

### 忽略一条建议

`POST /api/v1/projects/alice~lab/ai/suggestions/4/dismiss`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/4/dismiss' \
  -H 'Content-Type: application/json' \
  -d '{"note": "outdated"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/4/dismiss' -ContentType 'application/json; charset=utf-8' -Body '{"note": "outdated"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/4/dismiss', json={'note': 'outdated'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.status` = `"dismissed"`
- `data.note` = `"outdated"`

### 一次运行：状态、计数、模式（回放）、发起人

`GET /api/v1/projects/alice~lab/ai/suggestions/batches/1`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/batches/1'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/batches/1'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/batches/1')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.status` = `"done"`
- `data.mode` = `"replay"`
- `data.skill` = `"topology-roles"`
- `data.counts.total` = `3`
- `data.counts.pass` = `2`
- `data.counts.reject` = `1`
- `data.created_by` = `"alice"`

### 采纳记录（还没有采纳时为空）

`GET /api/v1/projects/alice~lab/ai/suggestions/adoptions`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/adoptions'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/adoptions'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/ai/suggestions/adoptions')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.items` = `[]`

### 项目的视图标注（设备角色等，手工或采纳的 AI 建议）

`GET /api/v1/projects/alice~lab/view-annotations`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/alice~lab/view-annotations'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/view-annotations'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/view-annotations')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.items` = `[]`

### 设备的分析摘要（含与上一版本的变化、安全基线得分）

`GET /api/v1/devices/1/analysis?parts=summary`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/devices/1/analysis?parts=summary' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/devices/1/analysis?parts=summary' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/devices/1/analysis?parts=summary', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.parts` = `["summary"]`
- `data.device_id` = `1`
- `data.version_id` = `2`
- `data.summary.device` = `"ATN-CHANGE-01"`
- `data.summary.lines.unknown` = `0`
- `data.summary.history.previous.seq` = `1`
- `data.summary.history.current.seq` = `2`
- `data.summary.history.summary.modified` = `1`
- `data.summary.history.items.0.object` = `"interface[GigabitEthernet0/2/0]"`
- `data.summary.baseline.baseline` = `"basic"`
- `data.layer_info.layers.0.id` = `"physical"`

### TCP/IP 分层与结构化脚本（界面一次取齐配置图）

`GET /api/v1/devices/1/analysis?parts=graph,layers,script&defaults=false`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/devices/1/analysis?parts=graph,layers,script&defaults=false' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/devices/1/analysis?parts=graph,layers,script&defaults=false' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/devices/1/analysis?parts=graph,layers,script&defaults=false', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.parts` = `["graph", "layers", "script"]`
- `data.layers.layers.5.id` = `"application"`
- `data.layers.unclassified` = `[]`
- `data.script.lines.0.no` = `1`
- `data.script.defaults` = `[]`
- `data.graph.version_id` = `2`
- `data.graph.device` = `"ATN-CHANGE-01"`

### 分析一段配置文本：引用的区间、定义行与被引用处

`POST /api/v1/analysis`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/analysis' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\ninterface GigabitEthernet0/2/1\n ip binding vpn-instance RAN\n#\nreturn", "parts": ["script", "layers"]}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/analysis' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\ninterface GigabitEthernet0/2/1\n ip binding vpn-instance RAN\n#\nreturn", "parts": ["script", "layers"]}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/analysis', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\ninterface GigabitEthernet0/2/1\n ip binding vpn-instance RAN\n#\nreturn', 'parts': ['script', 'layers']})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.script.refs` = `{"vrf.instance[RAN]": [8]}`
- `data.script.defs` = `{"vrf.instance[RAN]": 3}`
- `data.script.lines.7.spans.3.t` = `"ref"`
- `data.script.lines.7.spans.3.s` = `25`
- `data.script.lines.7.layer` = `"network"`
- `data.layers.nodes.interface[GigabitEthernet0/2/1]` = `"physical"`
- `data.layers.cross_by_layers` = `[{"a": "physical", "b": "network", "count": 2}]`

### AI 查询是否可用（未配置时界面隐藏入口）

`GET /api/v1/ask/status`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/ask/status' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/ask/status' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/ask/status', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.configured` = `false`
- `data.status` = `"not_configured"`
- `data.sanitize` = `"always"`
- `data.guard_without_ai` = `true`

### 未配置 AI：自然语言查询返回“未配置”

`POST /api/v1/ask`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/ask' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"question": "哪些接口绑定了 VPN 实例？"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/ask' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"question": "哪些接口绑定了 VPN 实例？"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/ask', headers={'Authorization': 'Bearer <令牌>'}, json={'question': '哪些接口绑定了 VPN 实例？'})
print(r.status_code, r.json())
```

HTTP 状态：`409`；返回中的关键字段：

- `code` = `1003`
- `data.status` = `"not_configured"`
- `data.configured` = `false`

### 图查询（不需要 AI）：上传的配置

`POST /api/v1/query`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/query' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"query": "FIND interface WHERE mtu > 1500 RETURN name, description, mtu", "configs": [{"name": "q.cfg", "profile": "huawei-atn-v800r025", "text": "#\nsysname Q-01\n#\ninterface GigabitEthernet0/2/0\n description UPLINK\n mtu 9000\n#\ninterface GigabitEthernet0/2/1\n description ACCESS\n#\nreturn"}]}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/query' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"query": "FIND interface WHERE mtu > 1500 RETURN name, description, mtu", "configs": [{"name": "q.cfg", "profile": "huawei-atn-v800r025", "text": "#\nsysname Q-01\n#\ninterface GigabitEthernet0/2/0\n description UPLINK\n mtu 9000\n#\ninterface GigabitEthernet0/2/1\n description ACCESS\n#\nreturn"}]}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/query', headers={'Authorization': 'Bearer <令牌>'}, json={'query': 'FIND interface WHERE mtu > 1500 RETURN name, description, mtu', 'configs': [{'name': 'q.cfg', 'profile': 'huawei-atn-v800r025', 'text': '#\nsysname Q-01\n#\ninterface GigabitEthernet0/2/0\n description UPLINK\n mtu 9000\n#\ninterface GigabitEthernet0/2/1\n description ACCESS\n#\nreturn'}]})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.count` = `1`
- `data.rows.0.n` = `1`
- `data.rows.0.device` = `"Q-01"`
- `data.rows.0.cells.mtu.value` = `9000`
- `data.rows.0.cells.mtu.lines` = `[6]`
- `data.text` = `"FIND interface\nON *\nWHERE mtu > 1500\nRETURN name, description, mtu"`

### 查询的对象类型不存在

`POST /api/v1/query`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/query' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"query": "FIND nope"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/query' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"query": "FIND nope"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/query', headers={'Authorization': 'Bearer <令牌>'}, json={'query': 'FIND nope'})
print(r.status_code, r.json())
```

HTTP 状态：`422`；返回中的关键字段：

- `code` = `1001`

### 配置护栏（不需要 AI）：合并到给出的当前配置后检查

`POST /api/v1/guard`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/guard' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "interface GigabitEthernet0/2/2.105\n vlan-type dot1q 105\n ip binding vpn-instance RAN-5G\n#", "base_text": "#\nsysname G-01\n#\ninterface GigabitEthernet0/2/2\n description OAM\n#\nreturn", "profile": "huawei-atn-v800r025", "lang": "en"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/guard' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "interface GigabitEthernet0/2/2.105\n vlan-type dot1q 105\n ip binding vpn-instance RAN-5G\n#", "base_text": "#\nsysname G-01\n#\ninterface GigabitEthernet0/2/2\n description OAM\n#\nreturn", "profile": "huawei-atn-v800r025", "lang": "en"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/guard', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'interface GigabitEthernet0/2/2.105\n vlan-type dot1q 105\n ip binding vpn-instance RAN-5G\n#', 'base_text': '#\nsysname G-01\n#\ninterface GigabitEthernet0/2/2\n description OAM\n#\nreturn', 'profile': 'huawei-atn-v800r025', 'lang': 'en'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.verdict` = `"blocked"`
- `data.issues.0.rule` = `"dangling_ref"`
- `data.issues.0.line` = `3`
- `data.issues.0.text` = `"References an object that does not exist: vrf.instance RAN-5G (defined neither in the current config nor in the new lines)"`
- `data.lines.2.status` = `"bad"`
- `data.stages.deps.status` = `"bad"`

### 对一段配置跑基础基线

`POST /api/v1/baseline`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/baseline' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"baseline": "basic", "configs": [{"name": "R1", "text": "sysname R1\n#\ntelnet server enable\n#\nuser-interface vty 0 4\n authentication-mode aaa\n protocol inbound ssh\n#\nreturn"}]}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/baseline' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"baseline": "basic", "configs": [{"name": "R1", "text": "sysname R1\n#\ntelnet server enable\n#\nuser-interface vty 0 4\n authentication-mode aaa\n protocol inbound ssh\n#\nreturn"}]}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/baseline', headers={'Authorization': 'Bearer <令牌>'}, json={'baseline': 'basic', 'configs': [{'name': 'R1', 'text': 'sysname R1\n#\ntelnet server enable\n#\nuser-interface vty 0 4\n authentication-mode aaa\n protocol inbound ssh\n#\nreturn'}]})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.baseline` = `"basic"`
- `data.matrix.devices` = `["R1"]`
- `data.devices.0.results.sec.telnet_disabled` = `"fail"`
- `data.devices.0.results.sec.vty_ssh_only` = `"pass"`
- `data.devices.0.results.sec.tacacs_key` = `"na"`
- `data.devices.0.failures.0.rule` = `"sec.telnet_disabled"`
- `data.devices.0.failures.0.lines` = `[3]`
- `data.devices.0.failures.0.remedy` = `["undo telnet server enable", "undo telnet ipv6 server enable"]`
- `data.summary.has_errors` = `true`

### 严格基线的规则清单

`GET /api/v1/baseline/rules?baseline=strict`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/baseline/rules?baseline=strict' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/baseline/rules?baseline=strict' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/baseline/rules?baseline=strict', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.profile` = `"strict"`
- `data.total` = `34`
- `data.profiles.0.id` = `"basic"`
- `data.profiles.1.includes` = `["basic"]`
- `data.rules.0.id` = `"sec.telnet_disabled"`
- `data.rules.0.severity` = `"error"`

### 华为接口绑定 VPN 的变更脚本（副作用补发 IP、回滚、模拟验证）

`POST /api/v1/change`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/change' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"current": {"text": "#\ninterface GigabitEthernet0/2/2\n description OAM-LINK\n ip address 10.3.0.1 255.255.255.252\n#\nip vpn-instance OAM\n ipv4-family\n  route-distinguisher 65000:200\n#\nreturn", "profile": "huawei-atn-v800r025"}, "target": {"text": "#\ninterface GigabitEthernet0/2/2\n description OAM-LINK\n ip binding vpn-instance OAM\n ip address 10.3.0.1 255.255.255.252\n#\nip vpn-instance OAM\n ipv4-family\n  route-distinguisher 65000:200\n#\nreturn", "profile": "huawei-atn-v800r025"}, "style": "huawei", "lang": "en"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/change' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"current": {"text": "#\ninterface GigabitEthernet0/2/2\n description OAM-LINK\n ip address 10.3.0.1 255.255.255.252\n#\nip vpn-instance OAM\n ipv4-family\n  route-distinguisher 65000:200\n#\nreturn", "profile": "huawei-atn-v800r025"}, "target": {"text": "#\ninterface GigabitEthernet0/2/2\n description OAM-LINK\n ip binding vpn-instance OAM\n ip address 10.3.0.1 255.255.255.252\n#\nip vpn-instance OAM\n ipv4-family\n  route-distinguisher 65000:200\n#\nreturn", "profile": "huawei-atn-v800r025"}, "style": "huawei", "lang": "en"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/change', headers={'Authorization': 'Bearer <令牌>'}, json={'current': {'text': '#\ninterface GigabitEthernet0/2/2\n description OAM-LINK\n ip address 10.3.0.1 255.255.255.252\n#\nip vpn-instance OAM\n ipv4-family\n  route-distinguisher 65000:200\n#\nreturn', 'profile': 'huawei-atn-v800r025'}, 'target': {'text': '#\ninterface GigabitEthernet0/2/2\n description OAM-LINK\n ip binding vpn-instance OAM\n ip address 10.3.0.1 255.255.255.252\n#\nip vpn-instance OAM\n ipv4-family\n  route-distinguisher 65000:200\n#\nreturn', 'profile': 'huawei-atn-v800r025'}, 'style': 'huawei', 'lang': 'en'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.script_rows.0.kind` = `"frame"`
- `data.script_rows.1.kind` = `"enter"`
- `data.script_rows.2.kind` = `"cmd"`
- `data.script_rows.2.seq` = `1`
- `data.script_rows.4.kind` = `"quit"`
- `data.family` = `"huawei-vrp8"`
- `data.equal` = `false`
- `data.summary.ops` = `2`
- `data.summary.by_action.side_effect` = `1`
- `data.ops.0.text` = `"ip binding vpn-instance OAM"`
- `data.ops.1.action` = `"side_effect"`
- `data.ops.1.risk` = `"high"`
- `data.ops.1.after.0.kind` = `"side_effect"`
- `data.verify.ok` = `true`
- `data.rollback.verify.ok` = `true`
- `data.impact.business.0.type` = `"interface"`

### 目标没有给出配置

`POST /api/v1/change`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/change' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"current": {"text": "sysname A"}, "target": {}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/change' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"current": {"text": "sysname A"}, "target": {}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/change', headers={'Authorization': 'Bearer <令牌>'}, json={'current': {'text': 'sysname A'}, 'target': {}})
print(r.status_code, r.json())
```

HTTP 状态：`422`；返回中的关键字段：

- `code` = `1001`

### 影响分析：VPN 实例影响的接口

`POST /api/v1/impact`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/impact' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "#\ninterface GigabitEthernet0/2/2\n description OAM-LINK\n ip binding vpn-instance OAM\n ip address 10.3.0.1 255.255.255.252\n#\nip vpn-instance OAM\n ipv4-family\n  route-distinguisher 65000:200\n#\nreturn", "nodes": ["vrf.instance[OAM]"]}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/impact' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "#\ninterface GigabitEthernet0/2/2\n description OAM-LINK\n ip binding vpn-instance OAM\n ip address 10.3.0.1 255.255.255.252\n#\nip vpn-instance OAM\n ipv4-family\n  route-distinguisher 65000:200\n#\nreturn", "nodes": ["vrf.instance[OAM]"]}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/impact', headers={'Authorization': 'Bearer <令牌>'}, json={'text': '#\ninterface GigabitEthernet0/2/2\n description OAM-LINK\n ip binding vpn-instance OAM\n ip address 10.3.0.1 255.255.255.252\n#\nip vpn-instance OAM\n ipv4-family\n  route-distinguisher 65000:200\n#\nreturn', 'nodes': ['vrf.instance[OAM]']})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.direction` = `"up"`
- `data.business.0.node` = `"interface[GigabitEthernet0/2/2]"`
- `data.business.0.path` = `["vrf.instance[OAM]", "interface[GigabitEthernet0/2/2]/vrf", "interface[GigabitEthernet0/2/2]"]`
- `data.summary.business` = `1`

### 检查一段配置

`POST /api/v1/check`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/check' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn", "severity": "info"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/check' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn", "severity": "info"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/check', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn', 'severity': 'info'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.summary.total` = `3`
- `data.summary.by_severity.warning` = `3`
- `data.summary.by_rule.ref.orphan` = `2`
- `data.findings.0.rule` = `"ref.orphan"`
- `data.findings.0.node` = `"vrf.instance[RAN]"`
- `data.findings.0.lines` = `[3]`

### 设备不存在

`GET /api/v1/devices/999/check`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/devices/999/check' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/devices/999/check' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/devices/999/check', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 为一段配置生成删除脚本

`POST /api/v1/cleanup`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/cleanup' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/cleanup' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/cleanup', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.commands.0.text` = `"undo ip vpn-instance RAN"`
- `data.commands.1.text` = `"undo route-policy UNUSED node 10"`
- `data.commands.1.lines` = `[7]`
- `data.fallbacks` = `0`
- `data.verify.ok` = `true`

### 检查规则列表

`GET /api/v1/kb/rules`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/kb/rules' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/kb/rules' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/kb/rules', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.builtin` = `6`
- `data.rules.0.id` = `"ref.dangling"`
- `data.rules.0.builtin` = `true`

### 配置检查项目列表

`GET /api/v1/check-projects`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/check-projects' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/check-projects' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/check-projects', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.projects.0.id` = `1`
- `data.projects.0.name` = `"割接前检查"`
- `data.projects.0.device.name` = `"ATN-CHANGE-01"`
- `data.projects.0.scripts` = `2`
- `data.projects.0.order_check` = `true`

### 新建项目（基线设备，跟随最新版本）

`POST /api/v1/check-projects`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/check-projects' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"name": "割接前检查", "description": "OAM 接口迁入 VPN", "device_id": 1, "order_check": true}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/check-projects' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"name": "割接前检查", "description": "OAM 接口迁入 VPN", "device_id": 1, "order_check": true}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/check-projects', headers={'Authorization': 'Bearer <令牌>'}, json={'name': '割接前检查', 'description': 'OAM 接口迁入 VPN', 'device_id': 1, 'order_check': True})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.id` = `1`
- `data.device.name` = `"ATN-CHANGE-01"`
- `data.default_kind` = `"change"`
- `data.ai_check` = `false`
- `data.scripts` = `0`

### 修改项目：关闭顺序核查、开启 AI 一起校验并勾选规则

`PUT /api/v1/check-projects/1`（需要令牌）

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/check-projects/1' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"order_check": false, "ai_check": true, "ai_rules": ["style.interface_description"]}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/check-projects/1' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"order_check": false, "ai_check": true, "ai_rules": ["style.interface_description"]}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/check-projects/1', headers={'Authorization': 'Bearer <令牌>'}, json={'order_check': False, 'ai_check': True, 'ai_rules': ['style.interface_description']})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.order_check` = `false`
- `data.ai_check` = `true`
- `data.ai_rules` = `["style.interface_description"]`
- `data.name` = `"割接前检查"`

### 新建脚本（形成第一条修订）

`POST /api/v1/check-projects/1/scripts`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"name": "删除前缀列表", "content": "system-view\nundo ip ip-prefix LOOPBACKS index 10\ncommit\n"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"name": "删除前缀列表", "content": "system-view\nundo ip ip-prefix LOOPBACKS index 10\ncommit\n"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts', headers={'Authorization': 'Bearer <令牌>'}, json={'name': '删除前缀列表', 'content': 'system-view\nundo ip ip-prefix LOOPBACKS index 10\ncommit\n'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.id` = `3`
- `data.kind` = `"change"`
- `data.revisions` = `1`
- `data.lines` = `3`

### 检查变更脚本（顺序核查开启）：问题按行给出，附重排建议

`POST /api/v1/check-projects/1/scripts/1/check`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1/check' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"lang": "zh-CN"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1/check' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"lang": "zh-CN"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1/check', headers={'Authorization': 'Bearer <令牌>'}, json={'lang': 'zh-CN'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.kind` = `"change"`
- `data.summary.errors` = `3`
- `data.order.enabled` = `true`
- `data.order.violations` = `2`
- `data.order.reorder.changed` = `true`
- `data.issues.1.line` = `3`
- `data.issues.1.code` = `"side_effect_lost"`
- `data.issues.1.category` = `"order"`
- `data.issues.1.source` = `"code"`
- `data.script.saved` = `true`
- `data.ai.enabled` = `false`
- `data.baseline.device` = `"ATN-CHANGE-01"`

### 检查编辑器中未保存的内容（边写边查）

`POST /api/v1/check-projects/1/scripts/1/check`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1/check' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"content": "system-view\ninterface GigabitEthernet0/2/2\n description OAM-LINK-NEW\nquit\ncommit\n"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1/check' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"content": "system-view\ninterface GigabitEthernet0/2/2\n description OAM-LINK-NEW\nquit\ncommit\n"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1/check', headers={'Authorization': 'Bearer <令牌>'}, json={'content': 'system-view\ninterface GigabitEthernet0/2/2\n description OAM-LINK-NEW\nquit\ncommit\n'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.summary.errors` = `0`
- `data.issues.0.code` = `"override"`
- `data.issues.0.message.params.base_line` = `40`
- `data.script.saved` = `false`
- `data.line_kinds.1` = `"command"`

### 按依赖重排（预览）：新脚本、每条命令的移动与原因

`POST /api/v1/check-projects/1/scripts/1/reorder`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1/reorder' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"lang": "zh-CN"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1/reorder' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"lang": "zh-CN"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1/reorder', headers={'Authorization': 'Bearer <令牌>'}, json={'lang': 'zh-CN'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.changed` = `true`
- `data.applied` = `false`
- `data.before.order_violations` = `2`
- `data.after.order_violations` = `0`
- `data.moves.0.reasons.0.dir` = `"after"`

### 保存脚本内容（内容变化时形成修订）

`PUT /api/v1/check-projects/1/scripts/1`（需要令牌）

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"content": "system-view\ninterface GigabitEthernet0/2/2\n description OAM-LINK-NEW\nquit\ncommit\n"}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"content": "system-view\ninterface GigabitEthernet0/2/2\n description OAM-LINK-NEW\nquit\ncommit\n"}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1', headers={'Authorization': 'Bearer <令牌>'}, json={'content': 'system-view\ninterface GigabitEthernet0/2/2\n description OAM-LINK-NEW\nquit\ncommit\n'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.revision.seq` = `2`
- `data.revision.source` = `"manual"`
- `data.revisions` = `2`

### 修订记录

`GET /api/v1/check-projects/1/scripts/1/revisions`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1/revisions' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1/revisions' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1/revisions', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.revisions.0.seq` = `1`
- `data.revisions.0.source` = `"create"`
- `data.revisions.0.author` = `"tester"`
- `data.revisions.0.lines` = `15`

### 恢复到某个修订（形成一条 restore 修订）

`POST /api/v1/check-projects/1/scripts/1/revisions/1/restore`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1/revisions/1/restore' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1/revisions/1/restore' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/check-projects/1/scripts/1/revisions/1/restore', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.revision.seq` = `2`
- `data.revision.source` = `"restore"`
- `data.revision.note.from_seq` = `1`

### 对比：基线设备配置 ↔ 完整配置脚本（文本 + 语义差异）

`POST /api/v1/check-projects/diff`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/check-projects/diff' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"a": {"type": "baseline", "project_id": 1}, "b": {"type": "script", "script_id": 2}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/check-projects/diff' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"a": {"type": "baseline", "project_id": 1}, "b": {"type": "script", "script_id": 2}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/check-projects/diff', headers={'Authorization': 'Bearer <令牌>'}, json={'a': {'type': 'baseline', 'project_id': 1}, 'b': {'type': 'script', 'script_id': 2}})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.a.kind` = `"baseline"`
- `data.b.kind` = `"full"`
- `data.equal` = `false`
- `data.semantic.equal` = `false`

### 对比两段配置文本（显式默认值不算差异，MTU 改动报出）

`POST /api/v1/compare`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/compare' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"a": {"text": "hostname R1\n!\ninterface GigabitEthernet0/0/1\n mtu 1500\n no shutdown\n ip address 10.0.0.1 255.255.255.0\n!\nend"}, "b": {"text": "hostname R1\n!\ninterface Gi0/0/1\n mtu 9000\n ip address 10.0.0.1 255.255.255.0\n!\nend"}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/compare' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"a": {"text": "hostname R1\n!\ninterface GigabitEthernet0/0/1\n mtu 1500\n no shutdown\n ip address 10.0.0.1 255.255.255.0\n!\nend"}, "b": {"text": "hostname R1\n!\ninterface Gi0/0/1\n mtu 9000\n ip address 10.0.0.1 255.255.255.0\n!\nend"}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/compare', headers={'Authorization': 'Bearer <令牌>'}, json={'a': {'text': 'hostname R1\n!\ninterface GigabitEthernet0/0/1\n mtu 1500\n no shutdown\n ip address 10.0.0.1 255.255.255.0\n!\nend'}, 'b': {'text': 'hostname R1\n!\ninterface Gi0/0/1\n mtu 9000\n ip address 10.0.0.1 255.255.255.0\n!\nend'}})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.summary.total` = `1`
- `data.diffs.0.kind` = `"changed"`
- `data.diffs.0.node` = `"interface[GigabitEthernet0/0/1]/mtu"`
- `data.diffs.0.a.value` = `1500`
- `data.diffs.0.a.origin` = `"explicit"`
- `data.diffs.0.b.value` = `9000`
- `data.diffs.0.b.lines` = `[4]`

### 一边没有给出配置来源

`POST /api/v1/compare`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/compare' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"a": {"text": "sysname X"}, "b": {"profile": "huawei-atn-v800r023"}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/compare' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"a": {"text": "sysname X"}, "b": {"profile": "huawei-atn-v800r023"}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/compare', headers={'Authorization': 'Bearer <令牌>'}, json={'a': {'text': 'sysname X'}, 'b': {'profile': 'huawei-atn-v800r023'}})
print(r.status_code, r.json())
```

HTTP 状态：`422`；返回中的关键字段：

- `code` = `1001`

### 设备不存在

`POST /api/v1/compare`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/compare' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"a": {"device_id": 999}, "b": {"text": "hostname R1"}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/compare' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"a": {"device_id": 999}, "b": {"text": "hostname R1"}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/compare', headers={'Authorization': 'Bearer <令牌>'}, json={'a': {'device_id': 999}, 'b': {'text': 'hostname R1'}})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 不存在的设备的配置版本

`GET /api/v1/devices/999/versions`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/devices/999/versions' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/devices/999/versions' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/devices/999/versions', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 删除设备的预览（不删除）

`GET /api/v1/devices/1/delete-preview`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/devices/1/delete-preview' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/devices/1/delete-preview' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/devices/1/delete-preview', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.device.name` = `"ATN-CHANGE-01"`
- `data.counts.versions` = `2`
- `data.counts.imports` = `3`
- `data.counts.check_ignores` = `0`
- `data.counts.unknown_lines` = `0`
- `data.blocked` = `false`
- `data.baseline.projects` = `[]`
- `data.versions.0.seq` = `1`
- `data.versions.0.imports` = `2`
- `data.versions.1.latest` = `true`

### 删除设备

`DELETE /api/v1/devices/1`（需要令牌）

```bash
curl -X DELETE 'http://127.0.0.1:9090/api/v1/devices/1' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method DELETE -Uri 'http://127.0.0.1:9090/api/v1/devices/1' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('DELETE', 'http://127.0.0.1:9090/api/v1/devices/1', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.deleted` = `true`
- `data.device.id` = `1`
- `data.counts.versions` = `2`
- `data.counts.imports` = `3`
- `data.baseline_cleared` = `[]`

### 设备是检查项目的基线：409，data 为删除预览

`DELETE /api/v1/devices/1`（需要令牌）

```bash
curl -X DELETE 'http://127.0.0.1:9090/api/v1/devices/1' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method DELETE -Uri 'http://127.0.0.1:9090/api/v1/devices/1' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('DELETE', 'http://127.0.0.1:9090/api/v1/devices/1', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`409`；返回中的关键字段：

- `code` = `1003`
- `data.blocked` = `true`
- `data.baseline.projects.0.name` = `"割接前检查"`
- `data.baseline.scripts` = `2`

### 删除最新版本：最新版本回到上一个

`DELETE /api/v1/devices/1/versions/2`（需要令牌）

```bash
curl -X DELETE 'http://127.0.0.1:9090/api/v1/devices/1/versions/2' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method DELETE -Uri 'http://127.0.0.1:9090/api/v1/devices/1/versions/2' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('DELETE', 'http://127.0.0.1:9090/api/v1/devices/1/versions/2', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.deleted` = `true`
- `data.version.id` = `2`
- `data.version.seq` = `2`
- `data.version.latest` = `true`
- `data.latest_version_id` = `1`
- `data.versions_left` = `1`
- `data.counts.imports` = `1`

### 审计表格的预置模板（Cisco 叫法）

`GET /api/v1/export/presets?style=cisco`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/export/presets?style=cisco' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/export/presets?style=cisco' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/export/presets?style=cisco', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.presets.0.id` = `"ip-address"`
- `data.presets.0.columns.4.label.en` = `"VRF"`
- `data.presets.0.where` = `["has-ip"]`
- `data.presets.4.title.zh-CN` = `"VRF 表"`

### IP 地址表（上传的配置，JSON）：每格带来源、节点与行号

`POST /api/v1/export/table`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/export/table' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"preset": "ip", "configs": [{"name": "exp-01.cfg", "profile": "huawei-atn-v800r025", "text": "#\nsysname EXP-01\n#\ninterface GigabitEthernet0/2/0\n description UPLINK\n mtu 9000\n ip address 10.1.0.1 255.255.255.252\n#\ninterface LoopBack0\n ip address 10.255.0.1 255.255.255.255\n#\nreturn"}]}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/export/table' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"preset": "ip", "configs": [{"name": "exp-01.cfg", "profile": "huawei-atn-v800r025", "text": "#\nsysname EXP-01\n#\ninterface GigabitEthernet0/2/0\n description UPLINK\n mtu 9000\n ip address 10.1.0.1 255.255.255.252\n#\ninterface LoopBack0\n ip address 10.255.0.1 255.255.255.255\n#\nreturn"}]}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/export/table', headers={'Authorization': 'Bearer <令牌>'}, json={'preset': 'ip', 'configs': [{'name': 'exp-01.cfg', 'profile': 'huawei-atn-v800r025', 'text': '#\nsysname EXP-01\n#\ninterface GigabitEthernet0/2/0\n description UPLINK\n mtu 9000\n ip address 10.1.0.1 255.255.255.252\n#\ninterface LoopBack0\n ip address 10.255.0.1 255.255.255.255\n#\nreturn'}]})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.preset` = `"ip-address"`
- `data.summary.rows` = `2`
- `data.rows.0.device` = `"EXP-01"`
- `data.rows.0.key` = `"GigabitEthernet0/2/0"`
- `data.rows.0.cells.1.value` = `"10.1.0.1"`
- `data.rows.0.cells.1.lines` = `[7]`
- `data.rows.0.cells.3.value` = `"255.255.255.252"`
- `data.rows.0.cells.3.origin` = `"derived"`
- `data.rows.0.cells.6.origin` = `"default"`
- `data.columns.4.empty.en` = `"Global"`

### 没有给模板也没有给对象类型

`POST /api/v1/export/table`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/export/table' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"devices": "all"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/export/table' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"devices": "all"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/export/table', headers={'Authorization': 'Bearer <令牌>'}, json={'devices': 'all'})
print(r.status_code, r.json())
```

HTTP 状态：`422`；返回中的关键字段：

- `code` = `1001`

### 特性能力查询：关键词 mtu

`GET /api/v1/features?q=mtu&profile=huawei-atn-v800r025,cisco-iosxe-asr920-17.15`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/features?q=mtu&profile=huawei-atn-v800r025,cisco-iosxe-asr920-17.15' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/features?q=mtu&profile=huawei-atn-v800r025,cisco-iosxe-asr920-17.15' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/features?q=mtu&profile=huawei-atn-v800r025,cisco-iosxe-asr920-17.15', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.items.0.node` = `"interface.mtu"`
- `data.items.0.profiles.cisco-iosxe-asr920-17.15.state` = `"supported"`
- `data.items.0.profiles.huawei-atn-v800r025.default` = `1500`
- `data.profiles.0.id` = `"huawei-atn-v800r025"`

### 两个 Profile 对比：默认值不同的排在前面

`GET /api/v1/features/diff?a=huawei-atn-v800r025&b=cisco-iosxe-asr920-17.15&domain=vrf`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/features/diff?a=huawei-atn-v800r025&b=cisco-iosxe-asr920-17.15&domain=vrf' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/features/diff?a=huawei-atn-v800r025&b=cisco-iosxe-asr920-17.15&domain=vrf' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/features/diff?a=huawei-atn-v800r025&b=cisco-iosxe-asr920-17.15&domain=vrf', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.rows.0.kind` = `"default"`
- `data.rows.0.node` = `"vrf.instance.af.label_mode"`
- `data.a.family` = `"huawei-vrp8"`
- `data.b.family` = `"cisco-iosxe"`

### 快照时间线（重复导入合并显示）

`GET /api/v1/devices/1/history`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/devices/1/history' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/devices/1/history' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/devices/1/history', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.count` = `2`
- `data.imports` = `3`
- `data.keep` = `50`
- `data.snapshots.0.id` = `1`
- `data.snapshots.0.import_count` = `2`
- `data.snapshots.0.imports.0.source_kind` = `"file"`
- `data.snapshots.0.imports.1.duplicate` = `true`
- `data.snapshots.1.vs_previous.modified` = `1`
- `data.snapshots.1.latest` = `true`

### 两个快照的差异（快照用配置版本编号）

`GET /api/v1/devices/1/history/diff?a=1&b=2`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/devices/1/history/diff?a=1&b=2' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/devices/1/history/diff?a=1&b=2' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/devices/1/history/diff?a=1&b=2', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.a.id` = `1`
- `data.b.id` = `2`
- `data.summary.modified` = `1`
- `data.summary.noneff` = `0`
- `data.items.0.object` = `"interface[GigabitEthernet0/2/0]"`
- `data.items.0.changes.1.field` = `"mtu"`
- `data.items.0.changes.1.a.value` = `9000`
- `data.items.0.changes.1.b.value` = `9216`
- `data.text.hunks.0.lines.3.op` = `"del"`
- `data.kb.differs` = `false`

### 对象历史

`GET /api/v1/devices/1/history/object?node=interface[GigabitEthernet0/2/0]`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/devices/1/history/object?node=interface[GigabitEthernet0/2/0]' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/devices/1/history/object?node=interface[GigabitEthernet0/2/0]' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/devices/1/history/object?node=interface[GigabitEthernet0/2/0]', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.schema` = `"interface"`
- `data.changes` = `1`
- `data.snapshots.1.changed` = `["description", "mtu"]`

### 给快照贴标签（永久保留）

`PUT /api/v1/devices/1/history/1/tag`（需要令牌）

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/devices/1/history/1/tag' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"tag": "割接前基线"}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/devices/1/history/1/tag' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"tag": "割接前基线"}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/devices/1/history/1/tag', headers={'Authorization': 'Bearer <令牌>'}, json={'tag': '割接前基线'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.id` = `1`
- `data.tag` = `"割接前基线"`

### 回到上一个快照：增量变更脚本、回滚与模拟验证

`POST /api/v1/devices/1/history/restore`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/devices/1/history/restore' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"to": "prev", "lang": "en"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/devices/1/history/restore' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"to": "prev", "lang": "en"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/devices/1/history/restore', headers={'Authorization': 'Bearer <令牌>'}, json={'to': 'prev', 'lang': 'en'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.from.seq` = `2`
- `data.to.seq` = `1`
- `data.change.summary.ops` = `2`
- `data.change.verify.ok` = `true`
- `data.change.rollback.verify.ok` = `true`
- `data.change.script_plain` = `"system-view\ninterface GigabitEthernet0/2/0\n description UPLINK-TO-AGG\n mtu 9000\nquit\ncommit\nreturn\n"`

### 设备不存在

`GET /api/v1/devices/99/history`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/devices/99/history' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/devices/99/history' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/devices/99/history', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 没有创建权限时新建项目：403

`POST /api/v1/projects`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects' \
  -H 'Content-Type: application/json' \
  -d '{"name": "新园区"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects' -ContentType 'application/json; charset=utf-8' -Body '{"name": "新园区"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects', json={'name': '新园区'})
print(r.status_code, r.json())
```

HTTP 状态：`403`；返回中的关键字段：

- `code` = `1006`

### 我能否新建项目与我的创建权限申请

`GET /api/v1/me/create-permission`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/me/create-permission'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/me/create-permission'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/me/create-permission')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.can_create` = `false`
- `data.open` = `false`
- `data.request.status` = `"pending"`

### 申请创建项目的权限（通知管理员）

`POST /api/v1/me/create-permission/request`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/me/create-permission/request' \
  -H 'Content-Type: application/json' \
  -d '{"reason": "负责 IP RAN 扩容"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/me/create-permission/request' -ContentType 'application/json; charset=utf-8' -Body '{"reason": "负责 IP RAN 扩容"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/me/create-permission/request', json={'reason': '负责 IP RAN 扩容'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.status` = `"pending"`
- `data.username` = `"carol"`

### 创建权限的申请（管理员）

`GET /api/v1/admin/create-requests`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/admin/create-requests'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/admin/create-requests'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/admin/create-requests')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.count` = `1`
- `data.requests.0.username` = `"dave"`

### 通过创建权限的申请：给该账号单独授权

`POST /api/v1/admin/create-requests/1/approve`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/admin/create-requests/1/approve'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/admin/create-requests/1/approve'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/admin/create-requests/1/approve')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.status` = `"approved"`
- `data.decided_by` = `"admin"`

### 管理员单独授权账号创建项目

`PUT /api/v1/users/carol`（需要令牌）

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/users/carol' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"can_create_projects": true}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/users/carol' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"can_create_projects": true}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/users/carol', headers={'Authorization': 'Bearer <令牌>'}, json={'can_create_projects': True})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.user.username` = `"carol"`
- `data.user.can_create_projects` = `true`

### 发现项目：只有名称、简介、属主、设备数与我的状态

`GET /api/v1/discover?q=lab`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/discover?q=lab'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/discover?q=lab'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/discover?q=lab')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.count` = `1`
- `data.projects.0.ref` = `"alice/lab"`
- `data.projects.0.owner` = `"alice"`
- `data.projects.0.devices` = `2`
- `data.projects.0.my_status` = `"pending"`

### 申请加入可被搜索的项目

`POST /api/v1/discover/alice~lab/join-requests`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/discover/alice~lab/join-requests' \
  -H 'Content-Type: application/json' \
  -d '{"role": "edit", "reason": "负责华东分支的割接脚本"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/discover/alice~lab/join-requests' -ContentType 'application/json; charset=utf-8' -Body '{"role": "edit", "reason": "负责华东分支的割接脚本"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/discover/alice~lab/join-requests', json={'role': 'edit', 'reason': '负责华东分支的割接脚本'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.status` = `"pending"`
- `data.role` = `"edit"`
- `data.project.ref` = `"alice/lab"`
- `data.via` = `"search"`

### 我提交的加入申请

`GET /api/v1/me/join-requests`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/me/join-requests'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/me/join-requests'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/me/join-requests')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.requests.0.status` = `"pending"`
- `data.requests.0.project.ref` = `"alice/lab"`

### 等我处理的申请数（导航上的数字）

`GET /api/v1/me/notifications`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/me/notifications'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/me/notifications'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/me/notifications')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.join_requests` = `1`
- `data.by_project.0.ref` = `"alice/lab"`
- `data.create_requests` = `0`

### 项目的加入申请（“管理”成员）

`GET /api/v1/projects/alice~lab/join-requests`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/alice~lab/join-requests'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/join-requests'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/join-requests')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.requests.0.username` = `"carol"`
- `data.requests.0.reason` = `"参与割接评审"`

### 通过加入申请并改角色

`POST /api/v1/projects/alice~lab/join-requests/1/approve`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects/alice~lab/join-requests/1/approve' \
  -H 'Content-Type: application/json' \
  -d '{"role": "edit"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/join-requests/1/approve' -ContentType 'application/json; charset=utf-8' -Body '{"role": "edit"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/join-requests/1/approve', json={'role': 'edit'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.status` = `"approved"`
- `data.decided_role` = `"edit"`
- `data.decided_by` = `"erin"`

### 新建邀请链接（token 只返回这一次）

`POST /api/v1/projects/alice~lab/invites`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects/alice~lab/invites' \
  -H 'Content-Type: application/json' \
  -d '{"role": "read", "days": 7, "requires_approval": false, "note": "运维二组"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab/invites' -ContentType 'application/json; charset=utf-8' -Body '{"role": "read", "days": 7, "requires_approval": false, "note": "运维二组"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects/alice~lab/invites', json={'role': 'read', 'days': 7, 'requires_approval': False, 'note': '运维二组'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.role` = `"read"`
- `data.state` = `"active"`
- `data.uses` = `0`
- `data.created_by` = `"erin"`

### 打开邀请链接

`GET /api/v1/invites/lmi_test-invite-token-0001`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/invites/lmi_test-invite-token-0001'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/invites/lmi_test-invite-token-0001'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/invites/lmi_test-invite-token-0001')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.project.ref` = `"alice/lab"`
- `data.role` = `"read"`
- `data.requires_approval` = `false`
- `data.state` = `"active"`
- `data.my_status` = `"none"`

### 用邀请链接直接加入

`POST /api/v1/invites/lmi_test-invite-token-0001/accept`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/invites/lmi_test-invite-token-0001/accept' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/invites/lmi_test-invite-token-0001/accept' -ContentType 'application/json; charset=utf-8' -Body '{}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/invites/lmi_test-invite-token-0001/accept', json={})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.status` = `"joined"`
- `data.project` = `"alice/lab"`
- `data.role` = `"read"`

### 设置项目可被搜索（属主、“管理”成员、管理员）

`PUT /api/v1/projects/alice~lab`

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/projects/alice~lab' \
  -H 'Content-Type: application/json' \
  -d '{"discoverable": false}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/projects/alice~lab' -ContentType 'application/json; charset=utf-8' -Body '{"discoverable": false}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/projects/alice~lab', json={'discoverable': False})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.discoverable` = `false`

### Cisco 设备迁移到华为（新设备已有管理口与端口，只生成增量；端口冲突以旧设备为准）

`POST /api/v1/migrate`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/migrate' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "hostname R1\n!\ninterface GigabitEthernet0/0/1\n description UPLINK\n mtu 9000\n ip address 10.0.0.1 255.255.255.252\n!\ninterface Port-channel1\n ip address 10.0.1.1 255.255.255.252\n!\nip route 0.0.0.0 0.0.0.0 10.0.0.2\n!\nend", "to": "huawei-atn-v800r025", "target_text": "#\nsysname NEW-01\n#\ninterface Ethernet0/0/0\n ip address 192.168.1.10 255.255.255.0\n#\ninterface GigabitEthernet0/2/1\n shutdown\n#\nreturn"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/migrate' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "hostname R1\n!\ninterface GigabitEthernet0/0/1\n description UPLINK\n mtu 9000\n ip address 10.0.0.1 255.255.255.252\n!\ninterface Port-channel1\n ip address 10.0.1.1 255.255.255.252\n!\nip route 0.0.0.0 0.0.0.0 10.0.0.2\n!\nend", "to": "huawei-atn-v800r025", "target_text": "#\nsysname NEW-01\n#\ninterface Ethernet0/0/0\n ip address 192.168.1.10 255.255.255.0\n#\ninterface GigabitEthernet0/2/1\n shutdown\n#\nreturn"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/migrate', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'hostname R1\n!\ninterface GigabitEthernet0/0/1\n description UPLINK\n mtu 9000\n ip address 10.0.0.1 255.255.255.252\n!\ninterface Port-channel1\n ip address 10.0.1.1 255.255.255.252\n!\nip route 0.0.0.0 0.0.0.0 10.0.0.2\n!\nend', 'to': 'huawei-atn-v800r025', 'target_text': '#\nsysname NEW-01\n#\ninterface Ethernet0/0/0\n ip address 192.168.1.10 255.255.255.0\n#\ninterface GigabitEthernet0/2/1\n shutdown\n#\nreturn'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.target.existing` = `true`
- `data.inventory.source` = `"target_config"`
- `data.interface_map.0.source` = `"GigabitEthernet0/0/1"`
- `data.interface_map.0.target` = `"GigabitEthernet0/2/1"`
- `data.interface_map.0.basis` = `"same_index"`
- `data.interface_map.1.target` = `"Eth-Trunk1"`
- `data.verify.checked` = `true`
- `data.verify.unexplained` = `0`
- `data.merge.conflicts` = `1`
- `data.steps.1.key` = `"migrate.step.load_delta"`

### 接口映射建议（按知识库的端口清单，附依据与置信度）

`POST /api/v1/migrate/suggest-map`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/migrate/suggest-map' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "#\nsysname OLD\n#\ninterface GigabitEthernet0/2/1\n ip address 10.0.0.1 255.255.255.252\n#\ninterface Ethernet0/0/0\n ip address 192.168.1.2 255.255.255.0\n#\nreturn", "to": "cisco-iosxe-asr920-17.15", "model": "ASR-920-12CZ-A"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/migrate/suggest-map' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "#\nsysname OLD\n#\ninterface GigabitEthernet0/2/1\n ip address 10.0.0.1 255.255.255.252\n#\ninterface Ethernet0/0/0\n ip address 192.168.1.2 255.255.255.0\n#\nreturn", "to": "cisco-iosxe-asr920-17.15", "model": "ASR-920-12CZ-A"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/migrate/suggest-map', headers={'Authorization': 'Bearer <令牌>'}, json={'text': '#\nsysname OLD\n#\ninterface GigabitEthernet0/2/1\n ip address 10.0.0.1 255.255.255.252\n#\ninterface Ethernet0/0/0\n ip address 192.168.1.2 255.255.255.0\n#\nreturn', 'to': 'cisco-iosxe-asr920-17.15', 'model': 'ASR-920-12CZ-A'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.inventory.model` = `"ASR-920-12CZ-A"`
- `data.map.0.target` = `"GigabitEthernet0/0/1"`
- `data.map.0.basis` = `"same_index"`
- `data.map.0.confidence` = `0.8`
- `data.unmapped.0.source` = `"Ethernet0/0/0"`
- `data.unmapped.0.reason` = `"management"`

### 导入前识别：匹配程度、会用的 Profile、试解析推荐（不入库）

`POST /api/v1/configs/inspect`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/configs/inspect' \
  -H 'Authorization: Bearer <令牌>' \
  -F 'files=@tests/inputs/configs/ne8000/ne8000-x8-01.cfg' \
  -F 'files=@tests/inputs/configs/other/edge-mx-01.conf' \
  -F 'level=basic'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/configs/inspect' -Headers @{'Authorization'='Bearer <令牌>'} -Form @{'files'=Get-Item 'tests/inputs/configs/ne8000/ne8000-x8-01.cfg'; 'level'='basic'}
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/configs/inspect', headers={'Authorization': 'Bearer <令牌>'}, files=[('files', open('tests/inputs/configs/ne8000/ne8000-x8-01.cfg', 'rb')), ('files', open('tests/inputs/configs/other/edge-mx-01.conf', 'rb'))], data={'level': 'basic'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.files.0.device` = `"NE8000-X8-01"`
- `data.files.0.vendor` = `"huawei"`
- `data.files.0.match_level` = `"approx"`
- `data.files.0.profile` = `"huawei-atn-v800r025"`
- `data.files.0.profile_source` = `"fallback"`
- `data.files.0.recommended` = `"huawei-atn-v800r025"`
- `data.files.0.candidates.0.unknown` = `2`
- `data.files.0.suggested_rule.name_pattern` = `"NE8000-X8-*"`
- `data.files.1.device` = `"edge-mx-01"`
- `data.files.1.vendor` = `""`
- `data.files.1.match_level` = `"none"`
- `data.can_global` = `true`

### 导入时按文件指定 Profile 并记住；认不出厂商的只存原文

`POST /api/v1/configs`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/configs' \
  -H 'Authorization: Bearer <令牌>' \
  -F 'files=@tests/inputs/configs/ne8000/ne8000-x8-01.cfg' \
  -F 'files=@tests/inputs/configs/other/edge-mx-01.conf' \
  -F 'level=basic' \
  -F 'unsupported=raw' \
  -F 'choices={"ne8000-x8-01.cfg": {"profile": "huawei-atn-v800r023", "remember": {"scope": "project", "name_pattern": "NE8000-*"}}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/configs' -Headers @{'Authorization'='Bearer <令牌>'} -Form @{'files'=Get-Item 'tests/inputs/configs/ne8000/ne8000-x8-01.cfg'; 'level'='basic'; 'unsupported'='raw'; 'choices'='{"ne8000-x8-01.cfg": {"profile": "huawei-atn-v800r023", "remember": {"scope": "project", "name_pattern": "NE8000-*"}}}'}
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/configs', headers={'Authorization': 'Bearer <令牌>'}, files=[('files', open('tests/inputs/configs/ne8000/ne8000-x8-01.cfg', 'rb')), ('files', open('tests/inputs/configs/other/edge-mx-01.conf', 'rb'))], data={'level': 'basic', 'unsupported': 'raw', 'choices': '{"ne8000-x8-01.cfg": {"profile": "huawei-atn-v800r023", "remember": {"scope": "project", "name_pattern": "NE8000-*"}}}'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.files.0.profile` = `"huawei-atn-v800r023"`
- `data.files.0.profile_source` = `"rule"`
- `data.files.0.rule_created` = `1`
- `data.files.0.unknown` = `2`
- `data.files.1.ok` = `true`
- `data.files.1.raw_only` = `true`
- `data.files.1.profile_source` = `"none"`

### 设备的候选 Profile 与试解析结果

`GET /api/v1/devices/1/profile-candidates`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/devices/1/profile-candidates' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/devices/1/profile-candidates' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/devices/1/profile-candidates', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.device.name` = `"NE8000-X8-01"`
- `data.profile_source` = `"fallback"`
- `data.match_level` = `"approx"`
- `data.candidates.0.profile` = `"huawei-atn-v800r025"`
- `data.candidates.0.fallback` = `true`
- `data.candidates.1.profile` = `"huawei-atn-v800r023"`
- `data.auto.source` = `"fallback"`

### 更换 Profile 并重新解析

`PUT /api/v1/devices/1/profile`（需要令牌）

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/devices/1/profile' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"profile": "huawei-atn-v800r023"}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/devices/1/profile' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"profile": "huawei-atn-v800r023"}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/devices/1/profile', headers={'Authorization': 'Bearer <令牌>'}, json={'profile': 'huawei-atn-v800r023'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.profile` = `"huawei-atn-v800r023"`
- `data.profile_source` = `"manual"`
- `data.match_level` = `"approx"`
- `data.result.parsed` = `true`

### 申请支持此型号

`POST /api/v1/devices/1/support-request`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/devices/1/support-request' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"model": "NE8000 X8", "reason": "城域汇聚，主要用 VPN、BGP"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/devices/1/support-request' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"model": "NE8000 X8", "reason": "城域汇聚，主要用 VPN、BGP"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/devices/1/support-request', headers={'Authorization': 'Bearer <令牌>'}, json={'model': 'NE8000 X8', 'reason': '城域汇聚，主要用 VPN、BGP'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.status` = `"pending"`

### 新建本项目的型号规则

`POST /api/v1/model-rules`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/model-rules' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"scope": "project", "name_pattern": "NE8000-*", "version": "V800R022", "profile": "huawei-atn-v800r023", "reparse": true}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/model-rules' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"scope": "project", "name_pattern": "NE8000-*", "version": "V800R022", "profile": "huawei-atn-v800r023", "reparse": true}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/model-rules', headers={'Authorization': 'Bearer <令牌>'}, json={'scope': 'project', 'name_pattern': 'NE8000-*', 'version': 'V800R022', 'profile': 'huawei-atn-v800r023', 'reparse': True})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.id` = `1`
- `data.scope` = `"project"`
- `data.vendor` = `"huawei"`
- `data.conditions` = `3`
- `data.reparsed` = `1`

### 规则集列表与可改名的对象类型

`GET /api/v1/translate-rules`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/translate-rules' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/translate-rules' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/translate-rules', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.items.0.id` = `"asr920-to-atn"`
- `data.items.0.builtin` = `true`
- `data.items.0.valid` = `true`
- `data.items.1.id` = `"atn-to-asr920"`
- `data.items.1.counts.ports` = `7`

### 读取规则集：结构化内容与 YAML 原文

`GET /api/v1/translate-rules/asr920-to-atn`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/translate-rules/asr920-to-atn' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/translate-rules/asr920-to-atn' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/translate-rules/asr920-to-atn', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.id` = `"asr920-to-atn"`
- `data.builtin` = `true`
- `data.rules.names.0.match` = `"regex"`
- `data.rules.names.0.to` = `"RP_{1}"`
- `data.rules.ports.0.from` = `"Port-channel"`
- `data.rules.ports.0.to` = `"Eth-Trunk"`

### 保存我的规则集（结构化内容）

`PUT /api/v1/translate-rules/my-rules`（需要令牌）

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/translate-rules/my-rules' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"rules": {"title": {"zh-CN": "我的规则", "en": "My rules", "pt-BR": "Minhas regras"}, "names": [{"type": "vrf.instance", "match": "wildcard", "from": "RAN-*", "to": "VRF_{1}"}], "ports": [{"match": "type", "from": "Eth-Trunk", "to": "Port-channel"}]}}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/translate-rules/my-rules' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"rules": {"title": {"zh-CN": "我的规则", "en": "My rules", "pt-BR": "Minhas regras"}, "names": [{"type": "vrf.instance", "match": "wildcard", "from": "RAN-*", "to": "VRF_{1}"}], "ports": [{"match": "type", "from": "Eth-Trunk", "to": "Port-channel"}]}}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/translate-rules/my-rules', headers={'Authorization': 'Bearer <令牌>'}, json={'rules': {'title': {'zh-CN': '我的规则', 'en': 'My rules', 'pt-BR': 'Minhas regras'}, 'names': [{'type': 'vrf.instance', 'match': 'wildcard', 'from': 'RAN-*', 'to': 'VRF_{1}'}], 'ports': [{'match': 'type', 'from': 'Eth-Trunk', 'to': 'Port-channel'}]}})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.id` = `"my-rules"`
- `data.builtin` = `false`
- `data.file` = `"my-rules.yaml"`
- `data.counts.names` = `1`
- `data.counts.ports` = `1`
- `data.rules.names.0.to` = `"VRF_{1}"`

### 内置规则集只读（409）

`PUT /api/v1/translate-rules/atn-to-asr920`（需要令牌）

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/translate-rules/atn-to-asr920' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"rules": {"names": []}}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/translate-rules/atn-to-asr920' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"rules": {"names": []}}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/translate-rules/atn-to-asr920', headers={'Authorization': 'Bearer <令牌>'}, json={'rules': {'names': []}})
print(r.status_code, r.json())
```

HTTP 状态：`409`；返回中的关键字段：

- `code` = `1003`

### 规则有误：返回问题清单

`PUT /api/v1/translate-rules/bad`（需要令牌）

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/translate-rules/bad' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"rules": {"names": [{"match": "regex", "from": "(", "to": "x"}]}}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/translate-rules/bad' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"rules": {"names": [{"match": "regex", "from": "(", "to": "x"}]}}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/translate-rules/bad', headers={'Authorization': 'Bearer <令牌>'}, json={'rules': {'names': [{'match': 'regex', 'from': '(', 'to': 'x'}]}})
print(r.status_code, r.json())
```

HTTP 状态：`422`；返回中的关键字段：

- `code` = `1001`
- `data.issues.0.where` = `"names[0].from"`
- `data.issues.0.key` = `"naming.issue.regex"`

### 导入规则集（YAML 原文，可换编号）

`POST /api/v1/translate-rules/import`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/translate-rules/import' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"source": "# 导入的规则\nid: imported\nnames:\n  - {match: exact, from: A, to: B}\n", "id": "imported-2"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/translate-rules/import' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"source": "# 导入的规则\nid: imported\nnames:\n  - {match: exact, from: A, to: B}\n", "id": "imported-2"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/translate-rules/import', headers={'Authorization': 'Bearer <令牌>'}, json={'source': '# 导入的规则\nid: imported\nnames:\n  - {match: exact, from: A, to: B}\n', 'id': 'imported-2'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.id` = `"imported-2"`
- `data.builtin` = `false`
- `data.counts.names` = `1`

### 编辑器测试框：一个名称经过名称映射与命名规范

`POST /api/v1/translate-rules/match`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/translate-rules/match' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"rules": {"names": [{"type": "rp.policy", "match": "regex", "from": "(\\w+)-(IN|OUT)", "to": "RP_{1}_{2}", "ignore_case": true}], "naming": [{"type": "rp.policy", "pattern": "RP_[A-Z_]+", "fix": true, "case": "upper", "max_length": 10}]}, "kind": "name", "type": "rp.policy", "value": "bgp-in"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/translate-rules/match' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"rules": {"names": [{"type": "rp.policy", "match": "regex", "from": "(\\w+)-(IN|OUT)", "to": "RP_{1}_{2}", "ignore_case": true}], "naming": [{"type": "rp.policy", "pattern": "RP_[A-Z_]+", "fix": true, "case": "upper", "max_length": 10}]}, "kind": "name", "type": "rp.policy", "value": "bgp-in"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/translate-rules/match', headers={'Authorization': 'Bearer <令牌>'}, json={'rules': {'names': [{'type': 'rp.policy', 'match': 'regex', 'from': '(\\w+)-(IN|OUT)', 'to': 'RP_{1}_{2}', 'ignore_case': True}], 'naming': [{'type': 'rp.policy', 'pattern': 'RP_[A-Z_]+', 'fix': True, 'case': 'upper', 'max_length': 10}]}, 'kind': 'name', 'type': 'rp.policy', 'value': 'bgp-in'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.mapped` = `"RP_bgp_in"`
- `data.result` = `"RP_BGP_IN"`
- `data.rule` = `0`
- `data.naming_rule` = `0`
- `data.fixes` = `["upper"]`
- `data.problems` = `[]`

### 试运行：改名清单、引用、冲突与命名规范告警

`POST /api/v1/translate-rules/test`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/translate-rules/test' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "#\nip vpn-instance RAN-4G\n ipv4-family\n  route-distinguisher 65000:1\n#\ninterface GigabitEthernet0/2/1.100\n vlan-type dot1q 100\n ip binding vpn-instance RAN-4G\n ip address 10.0.0.1 255.255.255.0\n#\nreturn", "profile": "huawei-atn-v800r025", "to": "cisco-iosxe-asr920-17.15", "rules": {"names": [{"type": "vrf.instance", "match": "wildcard", "from": "RAN-*", "to": "VRF_{1}"}], "naming": [{"type": "vrf.instance", "pattern": "VRF_[A-Z]+"}]}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/translate-rules/test' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "#\nip vpn-instance RAN-4G\n ipv4-family\n  route-distinguisher 65000:1\n#\ninterface GigabitEthernet0/2/1.100\n vlan-type dot1q 100\n ip binding vpn-instance RAN-4G\n ip address 10.0.0.1 255.255.255.0\n#\nreturn", "profile": "huawei-atn-v800r025", "to": "cisco-iosxe-asr920-17.15", "rules": {"names": [{"type": "vrf.instance", "match": "wildcard", "from": "RAN-*", "to": "VRF_{1}"}], "naming": [{"type": "vrf.instance", "pattern": "VRF_[A-Z]+"}]}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/translate-rules/test', headers={'Authorization': 'Bearer <令牌>'}, json={'text': '#\nip vpn-instance RAN-4G\n ipv4-family\n  route-distinguisher 65000:1\n#\ninterface GigabitEthernet0/2/1.100\n vlan-type dot1q 100\n ip binding vpn-instance RAN-4G\n ip address 10.0.0.1 255.255.255.0\n#\nreturn', 'profile': 'huawei-atn-v800r025', 'to': 'cisco-iosxe-asr920-17.15', 'rules': {'names': [{'type': 'vrf.instance', 'match': 'wildcard', 'from': 'RAN-*', 'to': 'VRF_{1}'}], 'naming': [{'type': 'vrf.instance', 'pattern': 'VRF_[A-Z]+'}]}})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.summary.renamed` = `1`
- `data.summary.refs` = `1`
- `data.renames.0.from` = `"RAN-4G"`
- `data.renames.0.to` = `"VRF_4G"`
- `data.renames.0.ref_nodes.0.schema` = `"interface.vrf"`
- `data.naming.0.problem` = `"pattern"`
- `data.naming.0.name` = `"VRF_4G"`
- `data.source.profile` = `"huawei-atn-v800r025"`

### 翻译时选用规则集（rule_set），结果另有 naming

`POST /api/v1/translate`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/translate' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "hostname R1\n!\ninterface Port-channel1\n ip address 10.0.1.1 255.255.255.252\n!\nip prefix-list LOOPBACKS seq 10 permit 10.255.0.0/16 ge 32\n!\nroute-map EXPORT-LOOPBACK permit 10\n match ip address prefix-list LOOPBACKS\n!\nend", "to": "huawei-atn-v800r025", "rule_set": "asr920-to-atn"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/translate' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "hostname R1\n!\ninterface Port-channel1\n ip address 10.0.1.1 255.255.255.252\n!\nip prefix-list LOOPBACKS seq 10 permit 10.255.0.0/16 ge 32\n!\nroute-map EXPORT-LOOPBACK permit 10\n match ip address prefix-list LOOPBACKS\n!\nend", "to": "huawei-atn-v800r025", "rule_set": "asr920-to-atn"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/translate', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'hostname R1\n!\ninterface Port-channel1\n ip address 10.0.1.1 255.255.255.252\n!\nip prefix-list LOOPBACKS seq 10 permit 10.255.0.0/16 ge 32\n!\nroute-map EXPORT-LOOPBACK permit 10\n match ip address prefix-list LOOPBACKS\n!\nend', 'to': 'huawei-atn-v800r025', 'rule_set': 'asr920-to-atn'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.verify.unexplained` = `0`
- `data.interface_map.Port-channel1` = `"Eth-Trunk1"`
- `data.naming.summary.renamed` = `1`
- `data.naming.renames.0.to` = `"RP_EXPORT-LOOPBACK"`

### 本项目的网络与汇总（默认网络、颜色组、项目概览）

`GET /api/v1/projects/lab/networks`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/lab/networks'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/lab/networks'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/lab/networks')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.networks.0.slug` = `"default"`
- `data.networks.0.default` = `true`
- `data.networks.0.color` = `"slate"`
- `data.networks.0.counts.devices` = `2`
- `data.palette.1` = `"indigo"`
- `data.overview.devices` = `2`

### 新建网络并设自动加入规则（同时加入现在命中的设备）

`POST /api/v1/projects/lab/networks`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects/lab/networks' \
  -H 'Content-Type: application/json' \
  -d '{"name": "IP RAN 接入", "slug": "ipran", "rules": [{"kind": "name", "pattern": "ATN-*", "apply_existing": true}]}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects/lab/networks' -ContentType 'application/json; charset=utf-8' -Body '{"name": "IP RAN 接入", "slug": "ipran", "rules": [{"kind": "name", "pattern": "ATN-*", "apply_existing": true}]}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects/lab/networks', json={'name': 'IP RAN 接入', 'slug': 'ipran', 'rules': [{'kind': 'name', 'pattern': 'ATN-*', 'apply_existing': True}]})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.slug` = `"ipran"`
- `data.color` = `"indigo"`
- `data.counts.devices` = `1`
- `data.rules.0.kind` = `"name"`
- `data.default` = `false`

### 按网络的路径：设备列表（默认网络）与各设备在哪些网络

`GET /api/v1/projects/lab/n/default/devices`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/lab/n/default/devices'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/lab/n/default/devices'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/lab/n/default/devices')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.devices.0.name` = `"ATN-CHANGE-01"`
- `data.devices.0.networks.0.slug` = `"default"`
- `data.devices.0.network_policy` = `"follow"`

### 网络成员：本网络用的版本、还在哪些网络、怎么加入的

`GET /api/v1/projects/lab/networks/default/members`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/lab/networks/default/members'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/lab/networks/default/members'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/lab/networks/default/members')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.total` = `2`
- `data.members.0.policy` = `"follow"`
- `data.network.default` = `true`

### 建网建议：按设备名规则（预览，可作自动加入规则）

`GET /api/v1/projects/lab/network-suggestions?basis=name`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/lab/network-suggestions?basis=name'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/lab/network-suggestions?basis=name'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/lab/network-suggestions?basis=name')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.total` = `2`
- `data.suggestions.0.key` = `"name:ATN-CHANGE"`
- `data.suggestions.0.count` = `1`
- `data.suggestions.0.rule.pattern` = `"ATN-CHANGE-*"`
- `data.suggestions.0.adoptable` = `true`

### 采纳建网建议并设为自动加入规则

`POST /api/v1/projects/lab/network-suggestions/adopt`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects/lab/network-suggestions/adopt' \
  -H 'Content-Type: application/json' \
  -d '{"basis": "name", "keys": ["name:ATN-CHANGE"], "with_rules": true}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects/lab/network-suggestions/adopt' -ContentType 'application/json; charset=utf-8' -Body '{"basis": "name", "keys": ["name:ATN-CHANGE"], "with_rules": true}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects/lab/network-suggestions/adopt', json={'basis': 'name', 'keys': ['name:ATN-CHANGE'], 'with_rules': True})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.created.0.key` = `"name:ATN-CHANGE"`
- `data.created.0.network.slug` = `"atn-change"`

### Cisco 配置翻译到 Nokia（三层口换成路由器接口 + port，OSPF 写在区域下的接口里）

`POST /api/v1/translate`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/translate' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "hostname R1\n!\ninterface Loopback0\n ip address 10.255.0.1 255.255.255.255\n!\ninterface GigabitEthernet0/0/1\n description UPLINK\n ip address 10.0.0.1 255.255.255.252\n ip ospf network point-to-point\n!\nrouter ospf 10\n network 10.0.0.0 0.0.0.3 area 0\n!\nend", "to": "nokia-sros-classic-7750-25.10", "interface_map": {"GigabitEthernet0/0/1": "1/1/1", "Loopback0": "system"}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/translate' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "hostname R1\n!\ninterface Loopback0\n ip address 10.255.0.1 255.255.255.255\n!\ninterface GigabitEthernet0/0/1\n description UPLINK\n ip address 10.0.0.1 255.255.255.252\n ip ospf network point-to-point\n!\nrouter ospf 10\n network 10.0.0.0 0.0.0.3 area 0\n!\nend", "to": "nokia-sros-classic-7750-25.10", "interface_map": {"GigabitEthernet0/0/1": "1/1/1", "Loopback0": "system"}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/translate', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'hostname R1\n!\ninterface Loopback0\n ip address 10.255.0.1 255.255.255.255\n!\ninterface GigabitEthernet0/0/1\n description UPLINK\n ip address 10.0.0.1 255.255.255.252\n ip ospf network point-to-point\n!\nrouter ospf 10\n network 10.0.0.0 0.0.0.3 area 0\n!\nend', 'to': 'nokia-sros-classic-7750-25.10', 'interface_map': {'GigabitEthernet0/0/1': '1/1/1', 'Loopback0': 'system'}})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.source.profile` = `"cisco-iosxe-asr920-17.15"`
- `data.target.family` = `"nokia-sros-classic"`
- `data.verify.checked` = `true`
- `data.verify.unexplained` = `0`
- `data.lines.0.text` = `"exit all"`

### 检查 Nokia 配置：路由器接口绑定的端口缺省关闭（修复参考命令按平台族给出）

`POST /api/v1/check`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/check' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "# TiMOS-B-25.10.R1 both/x86_64 Nokia 7750 SR\nexit all\nconfigure\n    port 1/1/2\n        ethernet\n            mode network\n        exit\n    exit\n    router Base\n        interface \"to-SIDE\"\n            address 10.8.2.1/30\n            port 1/1/2\n            no shutdown\n        exit\n    exit\nexit all\n"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/check' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "# TiMOS-B-25.10.R1 both/x86_64 Nokia 7750 SR\nexit all\nconfigure\n    port 1/1/2\n        ethernet\n            mode network\n        exit\n    exit\n    router Base\n        interface \"to-SIDE\"\n            address 10.8.2.1/30\n            port 1/1/2\n            no shutdown\n        exit\n    exit\nexit all\n"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/check', headers={'Authorization': 'Bearer <令牌>'}, json={'text': '# TiMOS-B-25.10.R1 both/x86_64 Nokia 7750 SR\nexit all\nconfigure\n    port 1/1/2\n        ethernet\n            mode network\n        exit\n    exit\n    router Base\n        interface "to-SIDE"\n            address 10.8.2.1/30\n            port 1/1/2\n            no shutdown\n        exit\n    exit\nexit all\n'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.profile` = `"nokia-sros-classic-7750-25.10"`
- `data.summary.total` = `1`
- `data.findings.0.rule` = `"port.shutdown_bound"`
- `data.findings.0.node` = `"interface[to-SIDE]"`
- `data.findings.0.remedy` = `["configure port <PORT> no shutdown", "configure lag <LAG-ID> no shutdown"]`

### 我的项目与共享给我的（属主的视角）

`GET /api/v1/projects`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.mine.0.slug` = `"lab"`
- `data.mine.0.role` = `"owner"`
- `data.mine.0.counts.devices` = `2`
- `data.mine.0.counts.private` = `1`
- `data.mine.0.counts.refs` = `1`
- `data.default_project` = `"lab"`

### 新建项目（标识在自己的项目里唯一）

`POST /api/v1/projects`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects' \
  -H 'Content-Type: application/json' \
  -d '{"name": "IP RAN 扩容一期", "slug": "ipran-phase1", "description": "新增基站接入环", "settings": {"style": "huawei"}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects' -ContentType 'application/json; charset=utf-8' -Body '{"name": "IP RAN 扩容一期", "slug": "ipran-phase1", "description": "新增基站接入环", "settings": {"style": "huawei"}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects', json={'name': 'IP RAN 扩容一期', 'slug': 'ipran-phase1', 'description': '新增基站接入环', 'settings': {'style': 'huawei'}})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.slug` = `"ipran-phase1"`
- `data.owner` = `"carol"`
- `data.role` = `"owner"`
- `data.settings.style` = `"huawei"`
- `data.settings.rule_set` = `""`

### 项目详情：属主、我的角色、成员、设置、计数

`GET /api/v1/projects/lab`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/lab'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/lab'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/lab')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.slug` = `"lab"`
- `data.owner` = `"alice"`
- `data.role` = `"read"`
- `data.members` = `2`
- `data.member_list.1.username` = `"bob"`
- `data.member_list.1.role` = `"read"`

### 项目里的设备：私有设备与引用的公共设备（版本策略）

`GET /api/v1/projects/lab/devices`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/lab/devices' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/lab/devices' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/lab/devices', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.devices.0.name` = `"ATN-CHANGE-01"`
- `data.devices.0.source` = `"private"`
- `data.devices.1.name` = `"PE-CHANGE-01"`
- `data.devices.1.source` = `"public"`
- `data.devices.1.policy` = `"follow"`
- `data.devices.1.newer_available` = `false`

### 修改项目设置（属主与可编辑成员）

`PUT /api/v1/projects/lab`

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/projects/lab' \
  -H 'Content-Type: application/json' \
  -d '{"description": "割接前基线", "settings": {"style": "cisco", "baseline": "baseline-security"}}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/projects/lab' -ContentType 'application/json; charset=utf-8' -Body '{"description": "割接前基线", "settings": {"style": "cisco", "baseline": "baseline-security"}}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/projects/lab', json={'description': '割接前基线', 'settings': {'style': 'cisco', 'baseline': 'baseline-security'}})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.description` = `"割接前基线"`
- `data.settings.style` = `"cisco"`
- `data.settings.baseline` = `"baseline-security"`

### 邀请成员或改角色（属主与管理员）

`PUT /api/v1/projects/lab/members/carol`

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/projects/lab/members/carol' \
  -H 'Content-Type: application/json' \
  -d '{"role": "edit"}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/projects/lab/members/carol' -ContentType 'application/json; charset=utf-8' -Body '{"role": "edit"}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/projects/lab/members/carol', json={'role': 'edit'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.members.0.role` = `"owner"`
- `data.members.2.username` = `"carol"`
- `data.members.2.role` = `"edit"`

### 转交项目（原属主留作可编辑成员）

`POST /api/v1/projects/lab/transfer`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects/lab/transfer' \
  -H 'Content-Type: application/json' \
  -d '{"to": "bob"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects/lab/transfer' -ContentType 'application/json; charset=utf-8' -Body '{"to": "bob"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects/lab/transfer', json={'to': 'bob'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.owner` = `"bob"`
- `data.previous_owner` = `"alice"`
- `data.kept_as` = `"edit"`

### 复制为我的新项目（只读成员也可以）

`POST /api/v1/projects/lab/copy`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects/lab/copy' \
  -H 'Content-Type: application/json' \
  -d '{"name": "实验局（副本）", "slug": "lab-bob"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects/lab/copy' -ContentType 'application/json; charset=utf-8' -Body '{"name": "实验局（副本）", "slug": "lab-bob"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects/lab/copy', json={'name': '实验局（副本）', 'slug': 'lab-bob'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.slug` = `"lab-bob"`
- `data.owner` = `"bob"`
- `data.counts.private` = `1`
- `data.counts.refs` = `1`
- `data.copied.devices` = `1`

### 删除项目：私有设备一起删除，引用只解除

`DELETE /api/v1/projects/lab?confirm=lab`

```bash
curl -X DELETE 'http://127.0.0.1:9090/api/v1/projects/lab?confirm=lab'
```

```powershell
Invoke-RestMethod -Method DELETE -Uri 'http://127.0.0.1:9090/api/v1/projects/lab?confirm=lab'
```

```python
import requests
r = requests.request('DELETE', 'http://127.0.0.1:9090/api/v1/projects/lab?confirm=lab')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.deleted` = `true`
- `data.counts.private_devices` = `1`
- `data.counts.refs` = `1`

### 把引用固定到某个版本

`PUT /api/v1/projects/lab/refs/2`

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/projects/lab/refs/2' \
  -H 'Content-Type: application/json' \
  -d '{"version_id": 2}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/projects/lab/refs/2' -ContentType 'application/json; charset=utf-8' -Body '{"version_id": 2}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/projects/lab/refs/2', json={'version_id': 2})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.policy` = `"pin"`
- `data.version_id` = `2`

### 把公共设备复制为本项目的私有设备（同名时自动改名）

`POST /api/v1/projects/lab/devices/copy-in`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects/lab/devices/copy-in' \
  -H 'Content-Type: application/json' \
  -d '{"device_id": 2}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects/lab/devices/copy-in' -ContentType 'application/json; charset=utf-8' -Body '{"device_id": 2}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects/lab/devices/copy-in', json={'device_id': 2})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.name` = `"PE-CHANGE-01-2"`
- `data.renamed` = `true`
- `data.from.public` = `true`

### 本项目关闭某条规则或改级别（原因必填）

`PUT /api/v1/projects/lab/rules/ref.orphan`

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/projects/lab/rules/ref.orphan' \
  -H 'Content-Type: application/json' \
  -d '{"severity": "info", "reason": "割接期间保留旧对象"}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/projects/lab/rules/ref.orphan' -ContentType 'application/json; charset=utf-8' -Body '{"severity": "info", "reason": "割接期间保留旧对象"}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/projects/lab/rules/ref.orphan', json={'severity': 'info', 'reason': '割接期间保留旧对象'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.rule` = `"ref.orphan"`
- `data.severity` = `"info"`
- `data.enabled` = `true`

### 公共设备库：版本数与引用它的项目

`GET /api/v1/public-devices`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/public-devices' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/public-devices' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/public-devices', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.devices.0.name` = `"PE-CHANGE-01"`
- `data.devices.0.versions` = `1`
- `data.devices.0.refs.0.project` = `"lab"`
- `data.devices.0.follow` = `1`

### 导入到公共设备库（管理员）

`POST /api/v1/public-devices`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/public-devices' \
  -H 'Authorization: Bearer <令牌>' \
  -F 'files=@tests/inputs/configs/cisco/basic.cfg'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/public-devices' -Headers @{'Authorization'='Bearer <令牌>'} -Form @{'files'=Get-Item 'tests/inputs/configs/cisco/basic.cfg'}
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/public-devices', headers={'Authorization': 'Bearer <令牌>'}, files=[('files', open('tests/inputs/configs/cisco/basic.cfg', 'rb'))])
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.files.0.ok` = `true`
- `data.files.0.device` = `"ce-rio-01"`

### 所有项目（管理员）

`GET /api/v1/admin/projects`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/admin/projects' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/admin/projects' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/admin/projects', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.projects.0.slug` = `"lab"`
- `data.projects.0.owner` = `"alice"`
- `data.owners` = `1`
- `data.with_members` = `1`

### 生成个人令牌（只显示这一次；默认 90 天）

`POST /api/v1/tokens`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/tokens' \
  -H 'Content-Type: application/json' \
  -d '{"name": "Jenkins 变更流水线", "read_only": false}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/tokens' -ContentType 'application/json; charset=utf-8' -Body '{"name": "Jenkins 变更流水线", "read_only": false}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/tokens', json={'name': 'Jenkins 变更流水线', 'read_only': False})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.name` = `"Jenkins 变更流水线"`
- `data.read_only` = `false`
- `data.state` = `"active"`
- `data.owner` = `"alice"`

### 对知识库提建议：进入审核队列（类型 suggestion）

`POST /api/v1/kb/suggestions`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/kb/suggestions' \
  -H 'Content-Type: application/json' \
  -d '{"target": "l3vpn.vpn_instance.label_mode", "kind": "default", "current": "per-route", "proposed": "per-instance", "reason": "ATN 910D 在 V800R022 起默认按实例分配标签", "project": "lab"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/kb/suggestions' -ContentType 'application/json; charset=utf-8' -Body '{"target": "l3vpn.vpn_instance.label_mode", "kind": "default", "current": "per-route", "proposed": "per-instance", "reason": "ATN 910D 在 V800R022 起默认按实例分配标签", "project": "lab"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/kb/suggestions', json={'target': 'l3vpn.vpn_instance.label_mode', 'kind': 'default', 'current': 'per-route', 'proposed': 'per-instance', 'reason': 'ATN 910D 在 V800R022 起默认按实例分配标签', 'project': 'lab'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.status` = `"pending"`

### 删除账号并把项目转交给其他账号

`DELETE /api/v1/users/alice?transfer_to=bob`（需要令牌）

```bash
curl -X DELETE 'http://127.0.0.1:9090/api/v1/users/alice?transfer_to=bob' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method DELETE -Uri 'http://127.0.0.1:9090/api/v1/users/alice?transfer_to=bob' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('DELETE', 'http://127.0.0.1:9090/api/v1/users/alice?transfer_to=bob', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.deleted` = `"alice"`
- `data.projects.action` = `"transfer"`
- `data.projects.to` = `"bob"`

### 别人已有同名项目也可以新建（标识按属主唯一）

`POST /api/v1/projects`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/projects' \
  -H 'Content-Type: application/json' \
  -d '{"name": "carol 的实验局", "slug": "lab"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/projects' -ContentType 'application/json; charset=utf-8' -Body '{"name": "carol 的实验局", "slug": "lab"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/projects', json={'name': 'carol 的实验局', 'slug': 'lab'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.slug` = `"lab"`
- `data.ref` = `"lab"`
- `data.full_ref` = `"carol/lab"`
- `data.owner` = `"carol"`

### 写成 属主/标识（路径里编码为 %2F）访问别人的同名项目

`GET /api/v1/projects/carol%2Flab`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/carol%2Flab'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/carol%2Flab'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/carol%2Flab')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.owner` = `"carol"`
- `data.ref` = `"carol/lab"`
- `data.role` = `"read"`

### 只写标识而能访问的同名项目有多个：409，列出候选

`GET /api/v1/projects/lab/devices`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/projects/lab/devices'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/projects/lab/devices'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/projects/lab/devices')
print(r.status_code, r.json())
```

HTTP 状态：`409`；返回中的关键字段：

- `code` = `1003`
- `data.candidates.0` = `"alice/lab"`
- `data.candidates.1` = `"carol/lab"`

### 对比时隐藏设备身份差异（Router ID 不同不算差异）

`POST /api/v1/compare`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/compare' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"a": {"text": "hostname R1\nrouter bgp 64512\n bgp router-id 10.0.0.1\n neighbor 10.0.0.9 remote-as 64512\n", "profile": "cisco-iosxe-asr920-17.15"}, "b": {"text": "hostname R2\nrouter bgp 64512\n bgp router-id 10.0.0.2\n neighbor 10.0.0.9 remote-as 64512\n", "profile": "cisco-iosxe-asr920-17.15"}, "hide_identity": true}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/compare' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"a": {"text": "hostname R1\nrouter bgp 64512\n bgp router-id 10.0.0.1\n neighbor 10.0.0.9 remote-as 64512\n", "profile": "cisco-iosxe-asr920-17.15"}, "b": {"text": "hostname R2\nrouter bgp 64512\n bgp router-id 10.0.0.2\n neighbor 10.0.0.9 remote-as 64512\n", "profile": "cisco-iosxe-asr920-17.15"}, "hide_identity": true}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/compare', headers={'Authorization': 'Bearer <令牌>'}, json={'a': {'text': 'hostname R1\nrouter bgp 64512\n bgp router-id 10.0.0.1\n neighbor 10.0.0.9 remote-as 64512\n', 'profile': 'cisco-iosxe-asr920-17.15'}, 'b': {'text': 'hostname R2\nrouter bgp 64512\n bgp router-id 10.0.0.2\n neighbor 10.0.0.9 remote-as 64512\n', 'profile': 'cisco-iosxe-asr920-17.15'}, 'hide_identity': True})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.equal` = `true`
- `data.summary.total` = `0`
- `data.summary.hidden_identity` = `1`
- `data.hidden_diffs.0.node` = `"bgp.instance[64512]/router_id"`
- `data.options.hide_identity` = `true`

### 停用一条内置检查并调整级别

`PUT /api/v1/kb/rules/ref.orphan`（需要令牌）

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/kb/rules/ref.orphan' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"enabled": false, "severity": "info"}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/kb/rules/ref.orphan' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"enabled": false, "severity": "info"}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/kb/rules/ref.orphan', headers={'Authorization': 'Bearer <令牌>'}, json={'enabled': False, 'severity': 'info'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.id` = `"ref.orphan"`
- `data.enabled` = `false`
- `data.severity` = `"info"`
- `data.default_severity` = `"warning"`
- `data.source` = `"builtin"`

### 忽略发现必须写原因

`POST /api/v1/check/ignores`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/check/ignores' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"device_id": 1, "rule": "ref.orphan", "node": "vrf.instance[X]", "reason": "  "}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/check/ignores' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"device_id": 1, "rule": "ref.orphan", "node": "vrf.instance[X]", "reason": "  "}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/check/ignores', headers={'Authorization': 'Bearer <令牌>'}, json={'device_id': 1, 'rule': 'ref.orphan', 'node': 'vrf.instance[X]', 'reason': '  '})
print(r.status_code, r.json())
```

HTTP 状态：`422`；返回中的关键字段：

- `code` = `1001`

### 只清理选中的对象

`POST /api/v1/cleanup`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/cleanup' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn", "objects": ["rp.policy[UNUSED]", "vrf.instance[NOPE]"]}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/cleanup' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn", "objects": ["rp.policy[UNUSED]", "vrf.instance[NOPE]"]}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/cleanup', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn', 'objects': ['rp.policy[UNUSED]', 'vrf.instance[NOPE]']})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.selected` = `true`
- `data.objects.0.node` = `"rp.policy[UNUSED]"`
- `data.commands.0.text` = `"undo route-policy UNUSED node 10"`
- `data.commands.0.fallback` = `false`
- `data.skipped.0.node` = `"vrf.instance[NOPE]"`
- `data.skipped.0.reason` = `"not_orphan"`
- `data.verify.ok` = `true`

### skill 列表：启用状态、当前版本、统计；ai.configured 表示能否试运行与进化

`GET /api/v1/ai/skills`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/ai/skills' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/ai/skills' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/ai/skills', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.ai.configured` = `false`
- `data.days` = `30`
- `data.skills.0.id` = `"card-extract"`
- `data.skills.0.group` = `"kb"`
- `data.skills.2.id` = `"ask-answer"`
- `data.skills.2.active` = `"builtin"`
- `data.skills.2.stats.calls` = `0`
- `data.groups.0.id` = `"qa"`
- `data.groups.0.count` = `2`
- `data.groups.0.title.en` = `"Q&A"`

### 普通账号不能管理 skill（403）

`GET /api/v1/ai/skills`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/ai/skills'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/ai/skills'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/ai/skills')
print(r.status_code, r.json())
```

HTTP 状态：`403`；返回中的关键字段：

- `code` = `1006`

### skill 详情：生效定义、内置定义、变量说明、试运行样例

`GET /api/v1/ai/skills/config-generate`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/ai/skills/config-generate' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/ai/skills/config-generate' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/ai/skills/config-generate', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.id` = `"config-generate"`
- `data.task` = `"generate"`
- `data.model_key` = `"ai.model_generate"`
- `data.checks` = `["guard"]`
- `data.variables.0.name` = `"family"`
- `data.samples.0.index` = `0`
- `data.definition.output.format` = `"config"`

### 保存为新版本并生效

`PUT /api/v1/ai/skills/card-extract`（需要令牌）

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/ai/skills/card-extract' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"examples": [{"input": "**undo shutdown**", "output": "undo shutdown"}], "note": "加一个示例"}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/ai/skills/card-extract' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"examples": [{"input": "**undo shutdown**", "output": "undo shutdown"}], "note": "加一个示例"}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/ai/skills/card-extract', headers={'Authorization': 'Bearer <令牌>'}, json={'examples': [{'input': '**undo shutdown**', 'output': 'undo shutdown'}], 'note': '加一个示例'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.version` = `"1"`
- `data.unchanged` = `false`
- `data.skill.active` = `"1"`
- `data.skill.examples` = `1`

### 版本历史

`GET /api/v1/ai/skills/ask-answer/versions`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/ai/skills/ask-answer/versions' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/ai/skills/ask-answer/versions' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/ai/skills/ask-answer/versions', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.active` = `"builtin"`
- `data.versions.0.version` = `"builtin"`
- `data.versions.0.label` = `"builtin v1"`

### 试运行（回放，不需要 AI）：渲染提示词、代码校验样例回复

`POST /api/v1/ai/skills/ask-answer/test`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/ai/skills/ask-answer/test' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"sample": 1, "mode": "replay"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/ai/skills/ask-answer/test' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"sample": 1, "mode": "replay"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/ai/skills/ask-answer/test', headers={'Authorization': 'Bearer <令牌>'}, json={'sample': 1, 'mode': 'replay'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.mode` = `"replay"`
- `data.check.status` = `"corrected"`
- `data.check.score` = `0.0`
- `data.sent.0.step` = `"replay"`

### 统计：近 N 天合计、每日调用、按版本、最近调用

`GET /api/v1/ai/skills/ask-query/stats?days=7`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/ai/skills/ask-query/stats?days=7' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/ai/skills/ask-query/stats?days=7' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/ai/skills/ask-query/stats?days=7', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.days` = `7`
- `data.totals.calls` = `0`
- `data.runs` = `[]`

### 未配置 AI：进化返回 409

`POST /api/v1/ai/skills/ask-query/evolve`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/ai/skills/ask-query/evolve' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/ai/skills/ask-query/evolve' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/ai/skills/ask-query/evolve', headers={'Authorization': 'Bearer <令牌>'}, json={})
print(r.status_code, r.json())
```

HTTP 状态：`409`；返回中的关键字段：

- `code` = `1003`
- `data.status` = `"not_configured"`

### 模板列表

`GET /api/v1/templates`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/templates' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/templates' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/templates', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.templates.0.id` = `"cisco-asr920-efp-bdi-vrf"`
- `data.templates.0.valid` = `true`

### 一个模板：变量、块、正文

`GET /api/v1/templates/huawei-atn-l2-bd-vbdif`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/templates/huawei-atn-l2-bd-vbdif' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/templates/huawei-atn-l2-bd-vbdif' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/templates/huawei-atn-l2-bd-vbdif', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.id` = `"huawei-atn-l2-bd-vbdif"`
- `data.vars.0.name` = `"port"`
- `data.blocks.0.kind` = `"repeat"`
- `data.match.extra` = `"allow"`

### 按模板校验配置文本：符合与变量

`POST /api/v1/templates/check`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/templates/check' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"template_id": "cisco-asr920-efp-bdi-vrf", "text": "hostname PE-ASR920-11\n!\nvrf definition RAN-2G\n rd 64512:101\n !\n address-family ipv4\n  route-target export 64512:101\n  route-target import 64512:101\n exit-address-family\n!\nvrf definition MGMT\n rd 64512:10\n !\n address-family ipv4\n  route-target export 64512:10\n  route-target import 64512:10\n exit-address-family\n!\ninterface Loopback0\n ip address 10.255.0.31 255.255.255.255\n!\ninterface GigabitEthernet0/0/0\n mtu 9216\n ip address 10.1.0.22 255.255.255.252\n mpls ip\n!\ninterface GigabitEthernet0/0/1\n description RAN-SITE-011\n no ip address\n service instance 101 ethernet\n  encapsulation dot1q 101\n  rewrite ingress tag pop 1 symmetric\n  bridge-domain 101\n !\n service instance 102 ethernet\n  encapsulation dot1q 102\n  rewrite ingress tag pop 1 symmetric\n  bridge-domain 102\n !\n!\ninterface BDI101\n description RAN-2G-SITE-011\n vrf forwarding RAN-2G\n ip address 172.16.11.1 255.255.255.0\n!\ninterface BDI102\n description MGMT-SITE-011\n vrf forwarding MGMT\n ip address 172.17.11.1 255.255.255.240\n!\nrouter bgp 64512\n bgp router-id 10.255.0.31\n bgp log-neighbor-changes\n neighbor RR peer-group\n neighbor RR remote-as 64512\n neighbor RR update-source Loopback0\n neighbor 10.255.0.1 peer-group RR\n neighbor 10.255.0.2 peer-group RR\n !\n address-family vpnv4\n  neighbor RR send-community extended\n  neighbor 10.255.0.1 activate\n  neighbor 10.255.0.2 activate\n exit-address-family\n !\n address-family ipv4 vrf RAN-2G\n  redistribute connected\n exit-address-family\n !\n address-family ipv4 vrf MGMT\n  redistribute connected\n exit-address-family\n!\nend\n", "label": "PE-ASR920-11"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/templates/check' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"template_id": "cisco-asr920-efp-bdi-vrf", "text": "hostname PE-ASR920-11\n!\nvrf definition RAN-2G\n rd 64512:101\n !\n address-family ipv4\n  route-target export 64512:101\n  route-target import 64512:101\n exit-address-family\n!\nvrf definition MGMT\n rd 64512:10\n !\n address-family ipv4\n  route-target export 64512:10\n  route-target import 64512:10\n exit-address-family\n!\ninterface Loopback0\n ip address 10.255.0.31 255.255.255.255\n!\ninterface GigabitEthernet0/0/0\n mtu 9216\n ip address 10.1.0.22 255.255.255.252\n mpls ip\n!\ninterface GigabitEthernet0/0/1\n description RAN-SITE-011\n no ip address\n service instance 101 ethernet\n  encapsulation dot1q 101\n  rewrite ingress tag pop 1 symmetric\n  bridge-domain 101\n !\n service instance 102 ethernet\n  encapsulation dot1q 102\n  rewrite ingress tag pop 1 symmetric\n  bridge-domain 102\n !\n!\ninterface BDI101\n description RAN-2G-SITE-011\n vrf forwarding RAN-2G\n ip address 172.16.11.1 255.255.255.0\n!\ninterface BDI102\n description MGMT-SITE-011\n vrf forwarding MGMT\n ip address 172.17.11.1 255.255.255.240\n!\nrouter bgp 64512\n bgp router-id 10.255.0.31\n bgp log-neighbor-changes\n neighbor RR peer-group\n neighbor RR remote-as 64512\n neighbor RR update-source Loopback0\n neighbor 10.255.0.1 peer-group RR\n neighbor 10.255.0.2 peer-group RR\n !\n address-family vpnv4\n  neighbor RR send-community extended\n  neighbor 10.255.0.1 activate\n  neighbor 10.255.0.2 activate\n exit-address-family\n !\n address-family ipv4 vrf RAN-2G\n  redistribute connected\n exit-address-family\n !\n address-family ipv4 vrf MGMT\n  redistribute connected\n exit-address-family\n!\nend\n", "label": "PE-ASR920-11"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/templates/check', headers={'Authorization': 'Bearer <令牌>'}, json={'template_id': 'cisco-asr920-efp-bdi-vrf', 'text': 'hostname PE-ASR920-11\n!\nvrf definition RAN-2G\n rd 64512:101\n !\n address-family ipv4\n  route-target export 64512:101\n  route-target import 64512:101\n exit-address-family\n!\nvrf definition MGMT\n rd 64512:10\n !\n address-family ipv4\n  route-target export 64512:10\n  route-target import 64512:10\n exit-address-family\n!\ninterface Loopback0\n ip address 10.255.0.31 255.255.255.255\n!\ninterface GigabitEthernet0/0/0\n mtu 9216\n ip address 10.1.0.22 255.255.255.252\n mpls ip\n!\ninterface GigabitEthernet0/0/1\n description RAN-SITE-011\n no ip address\n service instance 101 ethernet\n  encapsulation dot1q 101\n  rewrite ingress tag pop 1 symmetric\n  bridge-domain 101\n !\n service instance 102 ethernet\n  encapsulation dot1q 102\n  rewrite ingress tag pop 1 symmetric\n  bridge-domain 102\n !\n!\ninterface BDI101\n description RAN-2G-SITE-011\n vrf forwarding RAN-2G\n ip address 172.16.11.1 255.255.255.0\n!\ninterface BDI102\n description MGMT-SITE-011\n vrf forwarding MGMT\n ip address 172.17.11.1 255.255.255.240\n!\nrouter bgp 64512\n bgp router-id 10.255.0.31\n bgp log-neighbor-changes\n neighbor RR peer-group\n neighbor RR remote-as 64512\n neighbor RR update-source Loopback0\n neighbor 10.255.0.1 peer-group RR\n neighbor 10.255.0.2 peer-group RR\n !\n address-family vpnv4\n  neighbor RR send-community extended\n  neighbor 10.255.0.1 activate\n  neighbor 10.255.0.2 activate\n exit-address-family\n !\n address-family ipv4 vrf RAN-2G\n  redistribute connected\n exit-address-family\n !\n address-family ipv4 vrf MGMT\n  redistribute connected\n exit-address-family\n!\nend\n', 'label': 'PE-ASR920-11'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.compliant` = `true`
- `data.device` = `"PE-ASR920-11"`
- `data.variables.uplink_ip` = `"10.1.0.22"`
- `data.blocks.svc.0.vlan` = `101`
- `data.summary.instances.svc` = `2`

### 提取变量：可直接作为生成参数的一行

`POST /api/v1/templates/extract`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/templates/extract' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"template": "# 测试用模板：可选块（关闭端口）与派生变量\nid: optional-demo\ntitle: {zh-CN: 可选块示例, en: Optional block demo, pt-BR: Exemplo de bloco opcional}\nprofile: cisco-iosxe-asr920-17.15\nmatch: {extra: deny, extra_scope: matched}\nvars:\n  hostname: {type: word}\n  port: {type: interface, example: GigabitEthernet0/0/5}\n  net: {type: prefix, length: 30, network: true}\n  ip: {expr: \"net|host(1)\"}\nblocks:\n  shut: {optional: true}\nbody: |\n  hostname {{hostname}}\n  !\n  interface {{port}}\n   ip address {{ip}} {{net|mask}}\n  {% optional shut %}\n   shutdown\n  {% end %}\n  !\n  end\n", "text": "hostname R1\n!\ninterface GigabitEthernet0/0/5\n ip address 10.9.0.1 255.255.255.252\n shutdown\n!\nend\n", "label": "R1"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/templates/extract' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"template": "# 测试用模板：可选块（关闭端口）与派生变量\nid: optional-demo\ntitle: {zh-CN: 可选块示例, en: Optional block demo, pt-BR: Exemplo de bloco opcional}\nprofile: cisco-iosxe-asr920-17.15\nmatch: {extra: deny, extra_scope: matched}\nvars:\n  hostname: {type: word}\n  port: {type: interface, example: GigabitEthernet0/0/5}\n  net: {type: prefix, length: 30, network: true}\n  ip: {expr: \"net|host(1)\"}\nblocks:\n  shut: {optional: true}\nbody: |\n  hostname {{hostname}}\n  !\n  interface {{port}}\n   ip address {{ip}} {{net|mask}}\n  {% optional shut %}\n   shutdown\n  {% end %}\n  !\n  end\n", "text": "hostname R1\n!\ninterface GigabitEthernet0/0/5\n ip address 10.9.0.1 255.255.255.252\n shutdown\n!\nend\n", "label": "R1"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/templates/extract', headers={'Authorization': 'Bearer <令牌>'}, json={'template': '# 测试用模板：可选块（关闭端口）与派生变量\nid: optional-demo\ntitle: {zh-CN: 可选块示例, en: Optional block demo, pt-BR: Exemplo de bloco opcional}\nprofile: cisco-iosxe-asr920-17.15\nmatch: {extra: deny, extra_scope: matched}\nvars:\n  hostname: {type: word}\n  port: {type: interface, example: GigabitEthernet0/0/5}\n  net: {type: prefix, length: 30, network: true}\n  ip: {expr: "net|host(1)"}\nblocks:\n  shut: {optional: true}\nbody: |\n  hostname {{hostname}}\n  !\n  interface {{port}}\n   ip address {{ip}} {{net|mask}}\n  {% optional shut %}\n   shutdown\n  {% end %}\n  !\n  end\n', 'text': 'hostname R1\n!\ninterface GigabitEthernet0/0/5\n ip address 10.9.0.1 255.255.255.252\n shutdown\n!\nend\n', 'label': 'R1'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.row.device` = `"R1"`
- `data.row.net` = `"10.9.0.0/30"`
- `data.row.shut` = `true`
- `data.variables.ip` = `"10.9.0.1"`

### 从两台设备的配置生成模板草稿

`POST /api/v1/templates/draft`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/templates/draft' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"template_id": "demo-draft", "configs": [{"label": "R1", "text": "hostname R1\n!\ninterface GigabitEthernet0/0/5\n ip address 10.9.0.1 255.255.255.252\n shutdown\n!\nend\n"}, {"label": "R2", "text": "hostname R2\n!\ninterface GigabitEthernet0/0/5\n ip address 10.9.0.5 255.255.255.252\n shutdown\n!\nend\n"}]}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/templates/draft' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"template_id": "demo-draft", "configs": [{"label": "R1", "text": "hostname R1\n!\ninterface GigabitEthernet0/0/5\n ip address 10.9.0.1 255.255.255.252\n shutdown\n!\nend\n"}, {"label": "R2", "text": "hostname R2\n!\ninterface GigabitEthernet0/0/5\n ip address 10.9.0.5 255.255.255.252\n shutdown\n!\nend\n"}]}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/templates/draft', headers={'Authorization': 'Bearer <令牌>'}, json={'template_id': 'demo-draft', 'configs': [{'label': 'R1', 'text': 'hostname R1\n!\ninterface GigabitEthernet0/0/5\n ip address 10.9.0.1 255.255.255.252\n shutdown\n!\nend\n'}, {'label': 'R2', 'text': 'hostname R2\n!\ninterface GigabitEthernet0/0/5\n ip address 10.9.0.5 255.255.255.252\n shutdown\n!\nend\n'}]})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.valid` = `true`
- `data.vars.0.name` = `"hostname"`
- `data.vars.1.type` = `"ipv4"`
- `data.params.1.hostname` = `"R2"`
- `data.verify.1.compliant` = `true`

### 批量生成（JSON 参数行）：每行的配置文本与验证结果

`POST /api/v1/templates/generate`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/templates/generate' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"template": "# 测试用模板：可选块（关闭端口）与派生变量\nid: optional-demo\ntitle: {zh-CN: 可选块示例, en: Optional block demo, pt-BR: Exemplo de bloco opcional}\nprofile: cisco-iosxe-asr920-17.15\nmatch: {extra: deny, extra_scope: matched}\nvars:\n  hostname: {type: word}\n  port: {type: interface, example: GigabitEthernet0/0/5}\n  net: {type: prefix, length: 30, network: true}\n  ip: {expr: \"net|host(1)\"}\nblocks:\n  shut: {optional: true}\nbody: |\n  hostname {{hostname}}\n  !\n  interface {{port}}\n   ip address {{ip}} {{net|mask}}\n  {% optional shut %}\n   shutdown\n  {% end %}\n  !\n  end\n", "rows": [{"device": "R1", "hostname": "R1", "port": "GigabitEthernet0/0/5", "net": "10.9.0.0/30", "shut": true}, {"device": "R2", "hostname": "R2", "port": "GigabitEthernet0/0/6", "net": "10.9.0.5/30"}]}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/templates/generate' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"template": "# 测试用模板：可选块（关闭端口）与派生变量\nid: optional-demo\ntitle: {zh-CN: 可选块示例, en: Optional block demo, pt-BR: Exemplo de bloco opcional}\nprofile: cisco-iosxe-asr920-17.15\nmatch: {extra: deny, extra_scope: matched}\nvars:\n  hostname: {type: word}\n  port: {type: interface, example: GigabitEthernet0/0/5}\n  net: {type: prefix, length: 30, network: true}\n  ip: {expr: \"net|host(1)\"}\nblocks:\n  shut: {optional: true}\nbody: |\n  hostname {{hostname}}\n  !\n  interface {{port}}\n   ip address {{ip}} {{net|mask}}\n  {% optional shut %}\n   shutdown\n  {% end %}\n  !\n  end\n", "rows": [{"device": "R1", "hostname": "R1", "port": "GigabitEthernet0/0/5", "net": "10.9.0.0/30", "shut": true}, {"device": "R2", "hostname": "R2", "port": "GigabitEthernet0/0/6", "net": "10.9.0.5/30"}]}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/templates/generate', headers={'Authorization': 'Bearer <令牌>'}, json={'template': '# 测试用模板：可选块（关闭端口）与派生变量\nid: optional-demo\ntitle: {zh-CN: 可选块示例, en: Optional block demo, pt-BR: Exemplo de bloco opcional}\nprofile: cisco-iosxe-asr920-17.15\nmatch: {extra: deny, extra_scope: matched}\nvars:\n  hostname: {type: word}\n  port: {type: interface, example: GigabitEthernet0/0/5}\n  net: {type: prefix, length: 30, network: true}\n  ip: {expr: "net|host(1)"}\nblocks:\n  shut: {optional: true}\nbody: |\n  hostname {{hostname}}\n  !\n  interface {{port}}\n   ip address {{ip}} {{net|mask}}\n  {% optional shut %}\n   shutdown\n  {% end %}\n  !\n  end\n', 'rows': [{'device': 'R1', 'hostname': 'R1', 'port': 'GigabitEthernet0/0/5', 'net': '10.9.0.0/30', 'shut': True}, {'device': 'R2', 'hostname': 'R2', 'port': 'GigabitEthernet0/0/6', 'net': '10.9.0.5/30'}]})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.summary.ok` = `1`
- `data.summary.failed` = `1`
- `data.rows.0.text` = `"hostname R1\n!\ninterface GigabitEthernet0/0/5\n ip address 10.9.0.1 255.255.255.252\n shutdown\n!\nend\n"`
- `data.rows.0.checks.roundtrip` = `true`
- `data.rows.1.errors.0.var` = `"net"`
- `data.rows.1.errors.0.problem` = `"template.value.not_network"`

### 新建模板：校验后写入运行时知识库并提交

`PUT /api/v1/templates/api-demo`（需要令牌）

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/templates/api-demo' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"source": "# 测试用模板：可选块（关闭端口）与派生变量\nid: api-demo\ntitle: {zh-CN: 可选块示例, en: Optional block demo, pt-BR: Exemplo de bloco opcional}\nprofile: cisco-iosxe-asr920-17.15\nmatch: {extra: deny, extra_scope: matched}\nvars:\n  hostname: {type: word}\n  port: {type: interface, example: GigabitEthernet0/0/5}\n  net: {type: prefix, length: 30, network: true}\n  ip: {expr: \"net|host(1)\"}\nblocks:\n  shut: {optional: true}\nbody: |\n  hostname {{hostname}}\n  !\n  interface {{port}}\n   ip address {{ip}} {{net|mask}}\n  {% optional shut %}\n   shutdown\n  {% end %}\n  !\n  end\n"}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/templates/api-demo' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"source": "# 测试用模板：可选块（关闭端口）与派生变量\nid: api-demo\ntitle: {zh-CN: 可选块示例, en: Optional block demo, pt-BR: Exemplo de bloco opcional}\nprofile: cisco-iosxe-asr920-17.15\nmatch: {extra: deny, extra_scope: matched}\nvars:\n  hostname: {type: word}\n  port: {type: interface, example: GigabitEthernet0/0/5}\n  net: {type: prefix, length: 30, network: true}\n  ip: {expr: \"net|host(1)\"}\nblocks:\n  shut: {optional: true}\nbody: |\n  hostname {{hostname}}\n  !\n  interface {{port}}\n   ip address {{ip}} {{net|mask}}\n  {% optional shut %}\n   shutdown\n  {% end %}\n  !\n  end\n"}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/templates/api-demo', headers={'Authorization': 'Bearer <令牌>'}, json={'source': '# 测试用模板：可选块（关闭端口）与派生变量\nid: api-demo\ntitle: {zh-CN: 可选块示例, en: Optional block demo, pt-BR: Exemplo de bloco opcional}\nprofile: cisco-iosxe-asr920-17.15\nmatch: {extra: deny, extra_scope: matched}\nvars:\n  hostname: {type: word}\n  port: {type: interface, example: GigabitEthernet0/0/5}\n  net: {type: prefix, length: 30, network: true}\n  ip: {expr: "net|host(1)"}\nblocks:\n  shut: {optional: true}\nbody: |\n  hostname {{hostname}}\n  !\n  interface {{port}}\n   ip address {{ip}} {{net|mask}}\n  {% optional shut %}\n   shutdown\n  {% end %}\n  !\n  end\n'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.id` = `"api-demo"`
- `data.file` = `"api-demo.yaml"`
- `data.blocks.0.name` = `"shut"`

### 显示风格的术语表（华为 / Cisco / Nokia）

`GET /api/v1/kb/terms`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/kb/terms' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/kb/terms' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/kb/terms', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.default` = `"huawei"`
- `data.objects.vrf.instance.huawei.label.0` = `"ip vpn-instance {name}"`
- `data.objects.vrf.instance.cisco.label.0` = `"vrf definition {name}"`
- `data.objects.vrf.instance.nokia.label.0` = `"vprn {name}"`
- `data.contexts.nokia.0.path` = `["port"]`

### 上传两台设备的配置还原拓扑

`POST /api/v1/topology`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/topology' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"configs": [{"name": "r1.cfg", "text": "!Software Version V800R025C00SPC500\nsysname R1\n#\ninterface GigabitEthernet0/2/1\n mtu 9000\n ip address 10.0.0.1 255.255.255.252\n#\nospf 1\n area 0.0.0.0\n  network 10.0.0.0 0.0.0.3\n#\nreturn"}, {"name": "r2.cfg", "text": "!Software Version V800R025C00SPC500\nsysname R2\n#\ninterface GigabitEthernet0/2/1\n ip address 10.0.0.2 255.255.255.252\n#\nospf 1\n area 0.0.0.1\n  network 10.0.0.0 0.0.0.3\n#\nreturn"}]}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/topology' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"configs": [{"name": "r1.cfg", "text": "!Software Version V800R025C00SPC500\nsysname R1\n#\ninterface GigabitEthernet0/2/1\n mtu 9000\n ip address 10.0.0.1 255.255.255.252\n#\nospf 1\n area 0.0.0.0\n  network 10.0.0.0 0.0.0.3\n#\nreturn"}, {"name": "r2.cfg", "text": "!Software Version V800R025C00SPC500\nsysname R2\n#\ninterface GigabitEthernet0/2/1\n ip address 10.0.0.2 255.255.255.252\n#\nospf 1\n area 0.0.0.1\n  network 10.0.0.0 0.0.0.3\n#\nreturn"}]}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/topology', headers={'Authorization': 'Bearer <令牌>'}, json={'configs': [{'name': 'r1.cfg', 'text': '!Software Version V800R025C00SPC500\nsysname R1\n#\ninterface GigabitEthernet0/2/1\n mtu 9000\n ip address 10.0.0.1 255.255.255.252\n#\nospf 1\n area 0.0.0.0\n  network 10.0.0.0 0.0.0.3\n#\nreturn'}, {'name': 'r2.cfg', 'text': '!Software Version V800R025C00SPC500\nsysname R2\n#\ninterface GigabitEthernet0/2/1\n ip address 10.0.0.2 255.255.255.252\n#\nospf 1\n area 0.0.0.1\n  network 10.0.0.0 0.0.0.3\n#\nreturn'}]})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.summary.devices` = `2`
- `data.summary.links` = `2`
- `data.links.0.id` = `"subnet:R1:GigabitEthernet0/2/1~R2:GigabitEthernet0/2/1"`
- `data.links.0.segment` = `"10.0.0.0/30"`
- `data.links.0.confidence` = `"high"`
- `data.links.1.type` = `"ospf"`
- `data.nodes.0.id` = `"R1"`

### 两台设备的跨设备一致性检查

`POST /api/v1/consistency`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/consistency' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"severity": "info", "configs": [{"name": "r1.cfg", "text": "!Software Version V800R025C00SPC500\nsysname R1\n#\ninterface GigabitEthernet0/2/1\n mtu 9000\n ip address 10.0.0.1 255.255.255.252\n#\nospf 1\n area 0.0.0.0\n  network 10.0.0.0 0.0.0.3\n#\nreturn"}, {"name": "r2.cfg", "text": "!Software Version V800R025C00SPC500\nsysname R2\n#\ninterface GigabitEthernet0/2/1\n ip address 10.0.0.2 255.255.255.252\n#\nospf 1\n area 0.0.0.1\n  network 10.0.0.0 0.0.0.3\n#\nreturn"}]}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/consistency' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"severity": "info", "configs": [{"name": "r1.cfg", "text": "!Software Version V800R025C00SPC500\nsysname R1\n#\ninterface GigabitEthernet0/2/1\n mtu 9000\n ip address 10.0.0.1 255.255.255.252\n#\nospf 1\n area 0.0.0.0\n  network 10.0.0.0 0.0.0.3\n#\nreturn"}, {"name": "r2.cfg", "text": "!Software Version V800R025C00SPC500\nsysname R2\n#\ninterface GigabitEthernet0/2/1\n ip address 10.0.0.2 255.255.255.252\n#\nospf 1\n area 0.0.0.1\n  network 10.0.0.0 0.0.0.3\n#\nreturn"}]}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/consistency', headers={'Authorization': 'Bearer <令牌>'}, json={'severity': 'info', 'configs': [{'name': 'r1.cfg', 'text': '!Software Version V800R025C00SPC500\nsysname R1\n#\ninterface GigabitEthernet0/2/1\n mtu 9000\n ip address 10.0.0.1 255.255.255.252\n#\nospf 1\n area 0.0.0.0\n  network 10.0.0.0 0.0.0.3\n#\nreturn'}, {'name': 'r2.cfg', 'text': '!Software Version V800R025C00SPC500\nsysname R2\n#\ninterface GigabitEthernet0/2/1\n ip address 10.0.0.2 255.255.255.252\n#\nospf 1\n area 0.0.0.1\n  network 10.0.0.0 0.0.0.3\n#\nreturn'}]})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.summary.total` = `2`
- `data.summary.by_rule.xd.ospf.area` = `1`
- `data.summary.by_rule.xd.subnet.mtu` = `1`
- `data.findings.0.rule` = `"xd.ospf.area"`
- `data.findings.0.ends.0.value` = `"0.0.0.0"`
- `data.links.1.severity` = `"error"`
- `data.links.1.issues.0` = `"xd.ospf.area@ospf:R1:GigabitEthernet0/2/1~R2:GigabitEthernet0/2/1"`

### 还没有导入任何设备

`GET /api/v1/topology`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/topology' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/topology' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/topology', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`409`；返回中的关键字段：

- `code` = `1003`

### 翻译一段 Cisco 配置到华为（接口映射表）

`POST /api/v1/translate`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/translate' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "hostname R1\n!\ninterface GigabitEthernet0/0/1\n description UPLINK\n mtu 1500\n ip address 10.0.0.1 255.255.255.252\n!\ninterface Port-channel1\n ip address 10.0.1.1 255.255.255.252\n!\nip route 0.0.0.0 0.0.0.0 10.0.0.2\n!\nend", "to": "huawei-atn-v800r025", "interface_map": {"Port-channel1": "Eth-Trunk1"}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/translate' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "hostname R1\n!\ninterface GigabitEthernet0/0/1\n description UPLINK\n mtu 1500\n ip address 10.0.0.1 255.255.255.252\n!\ninterface Port-channel1\n ip address 10.0.1.1 255.255.255.252\n!\nip route 0.0.0.0 0.0.0.0 10.0.0.2\n!\nend", "to": "huawei-atn-v800r025", "interface_map": {"Port-channel1": "Eth-Trunk1"}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/translate', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'hostname R1\n!\ninterface GigabitEthernet0/0/1\n description UPLINK\n mtu 1500\n ip address 10.0.0.1 255.255.255.252\n!\ninterface Port-channel1\n ip address 10.0.1.1 255.255.255.252\n!\nip route 0.0.0.0 0.0.0.0 10.0.0.2\n!\nend', 'to': 'huawei-atn-v800r025', 'interface_map': {'Port-channel1': 'Eth-Trunk1'}})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.source.profile` = `"cisco-iosxe-asr920-17.15"`
- `data.target.family` = `"huawei-vrp8"`
- `data.verify.checked` = `true`
- `data.verify.unexplained` = `0`
- `data.defaults.0.kind` = `"explicit_equals_default"`
- `data.defaults.0.lines` = `[5]`
- `data.unsupported.0.kind` = `"raw"`
- `data.unsupported.0.lines` = `[1]`
- `data.lines.5.text` = `"interface Eth-Trunk1"`

### 没有给出源配置

`POST /api/v1/translate`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/translate' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"to": "huawei-atn-v800r025"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/translate' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"to": "huawei-atn-v800r025"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/translate', headers={'Authorization': 'Bearer <令牌>'}, json={'to': 'huawei-atn-v800r025'})
print(r.status_code, r.json())
```

HTTP 状态：`422`；返回中的关键字段：

- `code` = `1001`

### 规范模式渲染（含默认值）

`POST /api/v1/render`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/render' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "hostname R1\n!\ninterface GigabitEthernet0/0/1\n ip address 10.0.0.1 255.255.255.252\n!\nend", "canonical": true, "with_defaults": true}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/render' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "hostname R1\n!\ninterface GigabitEthernet0/0/1\n ip address 10.0.0.1 255.255.255.252\n!\nend", "canonical": true, "with_defaults": true}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/render', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'hostname R1\n!\ninterface GigabitEthernet0/0/1\n ip address 10.0.0.1 255.255.255.252\n!\nend', 'canonical': True, 'with_defaults': True})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.mode` = `"canonical"`
- `data.with_defaults` = `true`
- `data.profile` = `"cisco-iosxe-asr920-17.15"`
- `data.lines.1.text` = `"hostname R1"`
- `data.lines.3.text` = `"interface GigabitEthernet0/0/1"`
- `data.lines.5.text` = `" ! default"`
- `data.lines.5.kind` = `"comment"`
- `data.lines.6.origin` = `"default"`

### 登录页状态：是否已配置、是否已有账号（不需要认证）

`GET /api/v1/auth/status`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/auth/status'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/auth/status'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/auth/status')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.configured` = `true`
- `data.has_users` = `true`
- `data.session_hours` = `12`

### 用户名 + 密码登录（返回 Set-Cookie: lmesh_session，HttpOnly、SameSite=Strict）

`POST /api/v1/auth/login`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/auth/login' \
  -H 'Content-Type: application/json' \
  -d '{"username": "alice", "password": "Alice-pass-1"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/auth/login' -ContentType 'application/json; charset=utf-8' -Body '{"username": "alice", "password": "Alice-pass-1"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/auth/login', json={'username': 'alice', 'password': 'Alice-pass-1'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.user.username` = `"alice"`
- `data.user.role` = `"user"`
- `data.user.locked` = `false`

### 密码错误：401，不区分用户不存在与密码错误

`POST /api/v1/auth/login`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/auth/login' \
  -H 'Content-Type: application/json' \
  -d '{"username": "alice", "password": "wrong-password"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/auth/login' -ContentType 'application/json; charset=utf-8' -Body '{"username": "alice", "password": "wrong-password"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/auth/login', json={'username': 'alice', 'password': 'wrong-password'})
print(r.status_code, r.json())
```

HTTP 状态：`401`；返回中的关键字段：

- `code` = `1002`
- `message` = `"用户名或密码不正确。连续多次错误会暂时锁定账号"`

### 我的个人偏好：账号还没保存过时 prefs 为 null（网页登录后把浏览器本地的值写入账号，REQ-047）

`GET /api/v1/me/prefs`

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/me/prefs'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/me/prefs'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/me/prefs')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.has_account` = `true`

### 保存我的个人偏好（只改给出的项）：语言、主题、显示风格、设备图标风格

`PUT /api/v1/me/prefs`

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/me/prefs' \
  -H 'Content-Type: application/json' \
  -d '{"lang": "pt-BR", "theme": "dark", "term_style": "nokia", "icon_set": "line"}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/me/prefs' -ContentType 'application/json; charset=utf-8' -Body '{"lang": "pt-BR", "theme": "dark", "term_style": "nokia", "icon_set": "line"}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/me/prefs', json={'lang': 'pt-BR', 'theme': 'dark', 'term_style': 'nokia', 'icon_set': 'line'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.prefs.lang` = `"pt-BR"`
- `data.prefs.theme` = `"dark"`
- `data.prefs.term_style` = `"nokia"`
- `data.prefs.icon_set` = `"line"`

### 清除我保存在账号里的偏好（下次登录时网页改用浏览器本地的值并写入账号）

`DELETE /api/v1/me/prefs`

```bash
curl -X DELETE 'http://127.0.0.1:9090/api/v1/me/prefs'
```

```powershell
Invoke-RestMethod -Method DELETE -Uri 'http://127.0.0.1:9090/api/v1/me/prefs'
```

```python
import requests
r = requests.request('DELETE', 'http://127.0.0.1:9090/api/v1/me/prefs')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.has_account` = `true`

### 当前调用者（API 令牌视为管理员）

`GET /api/v1/auth/me`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/auth/me' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/auth/me' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/auth/me', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.username` = `"api-token"`
- `data.role` = `"admin"`
- `data.via` = `"token"`

### 账号列表（管理员；不含密码哈希）

`GET /api/v1/users`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/users' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/users' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/users', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.count` = `2`
- `data.users.0.username` = `"admin"`
- `data.users.0.role` = `"admin"`
- `data.users.1.username` = `"alice"`
- `data.users.1.disabled` = `false`

### 新建账号（管理员）

`POST /api/v1/users`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/users' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"username": "bob", "password": "Bob-pass-123", "role": "user"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/users' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"username": "bob", "password": "Bob-pass-123", "role": "user"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/users', headers={'Authorization': 'Bearer <令牌>'}, json={'username': 'bob', 'password': 'Bob-pass-123', 'role': 'user'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.user.username` = `"bob"`
- `data.user.role` = `"user"`
- `data.user.disabled` = `false`

### 停用账号（管理员；会话立即失效）

`PUT /api/v1/users/alice`（需要令牌）

```bash
curl -X PUT 'http://127.0.0.1:9090/api/v1/users/alice' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"disabled": true}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9090/api/v1/users/alice' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"disabled": true}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9090/api/v1/users/alice', headers={'Authorization': 'Bearer <令牌>'}, json={'disabled': True})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.user.username` = `"alice"`
- `data.user.disabled` = `true`

### 重置密码（管理员；解除锁定，会话失效）

`POST /api/v1/users/alice/password`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/users/alice/password' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"password": "Alice-new-pass"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/users/alice/password' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"password": "Alice-new-pass"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/users/alice/password', headers={'Authorization': 'Bearer <令牌>'}, json={'password': 'Alice-new-pass'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.user.username` = `"alice"`
- `data.user.locked` = `false`
- `data.sessions_closed` = `0`

### 删除账号（管理员）

`DELETE /api/v1/users/alice`（需要令牌）

```bash
curl -X DELETE 'http://127.0.0.1:9090/api/v1/users/alice' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method DELETE -Uri 'http://127.0.0.1:9090/api/v1/users/alice' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('DELETE', 'http://127.0.0.1:9090/api/v1/users/alice', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.deleted` = `"alice"`

### 还没有账号：用 API 令牌创建第一个管理员并登录

`POST /api/v1/auth/bootstrap`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/auth/bootstrap' \
  -H 'Content-Type: application/json' \
  -d '{"token": "test-token-0123456789", "username": "admin", "password": "Admin-pass-1"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/auth/bootstrap' -ContentType 'application/json; charset=utf-8' -Body '{"token": "test-token-0123456789", "username": "admin", "password": "Admin-pass-1"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/auth/bootstrap', json={'token': 'test-token-0123456789', 'username': 'admin', 'password': 'Admin-pass-1'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.user.username` = `"admin"`
- `data.user.role` = `"admin"`

### 注册未开放（默认关闭）：403

`POST /api/v1/auth/register`

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/auth/register' \
  -H 'Content-Type: application/json' \
  -d '{"username": "newbie", "password": "Newbie-pass-1"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/auth/register' -ContentType 'application/json; charset=utf-8' -Body '{"username": "newbie", "password": "Newbie-pass-1"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/auth/register', json={'username': 'newbie', 'password': 'Newbie-pass-1'})
print(r.status_code, r.json())
```

HTTP 状态：`403`；返回中的关键字段：

- `code` = `1006`

### 待审核的自助注册账号（管理员）

`GET /api/v1/users?status=pending`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/users?status=pending' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/users?status=pending' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/users?status=pending', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.count` = `2`
- `data.pending` = `2`
- `data.users.0.username` = `"dave"`
- `data.users.0.status` = `"pending"`
- `data.users.0.origin` = `"register"`

### 批准待审核账号（建好默认项目）

`POST /api/v1/users/dave/approve`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/users/dave/approve' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/users/dave/approve' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/users/dave/approve', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.user.username` = `"dave"`
- `data.user.status` = `"active"`

### 拒绝待审核账号（删除，用户名可再注册）

`POST /api/v1/users/erin/reject`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9090/api/v1/users/erin/reject' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9090/api/v1/users/erin/reject' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9090/api/v1/users/erin/reject', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.rejected` = `"erin"`
- `data.deleted` = `true`

### 自助注册设置（管理员）

`GET /api/v1/auth/settings`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9090/api/v1/auth/settings' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9090/api/v1/auth/settings' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9090/api/v1/auth/settings', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.registration` = `false`
- `data.approval` = `true`
- `data.rate_per_hour` = `5`

<!-- examples:end -->
