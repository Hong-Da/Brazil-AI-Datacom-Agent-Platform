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

- 项目路径：设备相关接口（导入、设备列表、配置图、对比、检查、清理、忽略项、翻译、变更、影响分析、拓扑与一致性、割接迁移、基线、版本历史、表格导出、报告、图查询与 AI 查询、配置检查项目与脚本、首页概况）写成 `/api/v1/projects/{project}/…`，例如 `GET /api/v1/projects/oam-vpn/devices`。`{project}` 是项目标识（全站唯一），也可以写 `属主/标识` 或项目编号。下表中“项目”一栏为“是”的接口都有项目路径版本
- 兼容别名（已弃用）：旧的无项目路径（例如 `GET /api/v1/devices`）仍然可用，落到调用者的默认项目（全局令牌为第一个管理员的默认项目）；响应头带 `Deprecation: true` 与 `Link: </api/v1/projects/<默认项目>/…>; rel="successor-version"`，OpenAPI 中标为 deprecated
- 项目里的设备：项目私有设备（导入或复制而来）与引用的公共设备（`source`：`private` / `public`）。引用的公共设备跟随公共库最新版本（`policy: follow`）或固定在某个版本（`policy: pin`，`pinned_version_id`，公共库有更新版本时 `newer_available: true`）；设备列表、对比、检查等用到“最新版本”的地方都按项目的版本策略取当前版本
- 项目角色：属主（owner）、可编辑成员（edit）、只读成员（read）；管理员访问不是自己参与的项目时角色为 admin，拥有完全权限，访问写入审计（`GET /admin/audit`、`logs/audit.log`）
- 权限：查看（GET）与计算（不修改数据的 POST：对比、检查、清理脚本生成、翻译、变更脚本生成、影响分析、拓扑、导出、报告、图查询、模板校验与生成……）对所有项目角色开放；修改数据（导入、删除、忽略、规则调整、脚本保存、重新解析本项目）只限属主、可编辑成员与管理员；成员管理、转交、删除项目只限属主与管理员；退出项目、复制项目或把设备复制到自己的项目只需能查看。不是成员的普通账号访问项目返回 404（不暴露项目是否存在）
- 只读的个人令牌只能调用查看与计算接口，其他接口返回 403（code 1006）

## 接口

| 接口 | 认证 | 作用 |
|---|---|---|
| `GET /health` | 否 | 健康检查：版本、是否已配置、数据库、知识库、AI 接口 |
| `GET /setup` | 否（仅未配置时） | 首次运行向导的参数定义 |
| `POST /setup` | 否（仅未配置时） | 提交向导结果；`dry_run: true` 时只校验；`admin: {"username", "password"}` 同时创建第一个管理员并登录（设置会话 Cookie），错误键为 `admin.username` / `admin.password` |
| `GET /auth/status` | 否 | 登录页需要的状态：`configured`、`has_users`（还没有账号时登录页改为用 API 令牌创建管理员）、`session_hours`；已配置且还没有账号时另返回 `config_file`（实例实际读取的配置文件绝对路径）与 `token_set`（是否设置了 API 令牌，布尔，不返回令牌内容），有账号后不返回这两项 |
| `POST /auth/login` | 否 | 用户名 + 密码登录：`{"username", "password"}`；成功返回 `user` 与 `expires_at` 并设置会话 Cookie；用户名或密码错误 401（不区分用户不存在），账号停用 403，连续失败 `security.login_max_failures` 次（默认 5）锁定 `security.login_lock_minutes` 分钟（默认 15），锁定期间 429 |
| `POST /auth/bootstrap` | 否（仅没有任何账号时） | 用 API 令牌创建第一个管理员并登录：`{"token", "username", "password"}`；已有账号时 409，令牌不对 401 |
| `POST /auth/logout` | 否 | 登出：删除会话、清除 Cookie；`data.logged_out` 表示是否确实结束了一个会话 |
| `GET /auth/me` | 是 | 当前调用者：`username`、`role`（admin / maintainer / user）、`via`（session / token / pat；全局令牌调用时 username 为 `api-token`，个人令牌为本人账号）、`expires_at`、`read_only`（只读的个人令牌）、`token_prefix`（个人令牌的前 8 个字符） |
| `POST /auth/password` | 是（会话） | 修改自己的密码：`{"old_password", "new_password"}`（至少 8 个字符）；当前会话保留，其他会话失效（`sessions_closed`）；旧密码不对 422；用令牌调用 409 |
| `GET /users` | 管理员 | 账号列表：`username`、`role`（admin / maintainer / user）、`projects`（拥有的非空项目数）、`tokens`（有效的个人令牌数）、`disabled`、`locked`、`locked_until`、`last_login_at`、`password_changed_at`、`created_at`（不含密码哈希） |
| `POST /users` | 管理员 | 新建账号：`{"username", "password", "role": "user\|maintainer\|admin"}`；用户名 2–64 个字符（字母、数字、点、下划线、短横线），不区分大小写唯一 |
| `PUT /users/{username}` | 管理员 | 改角色、停用 / 启用、解除锁定：`{"role", "disabled", "unlock"}`；停用时会话立即失效；最后一个启用的管理员不能停用或降级、不能停用或降级自己（409） |
| `POST /users/{username}/password` | 管理员 | 重置密码：`{"password"}`；同时解除锁定，该账号的会话全部失效 |
| `DELETE /users/{username}?transfer_to=&delete_projects=false` | 管理员 | 删除账号；不能删除自己和最后一个启用的管理员（409）；拥有非空项目时必须 `transfer_to`（项目、私有模板与规则集转交给该账号）或 `delete_projects=true`（一并删除），否则 409（`data.projects`）；自动建的空默认项目直接删除 |
| `GET /config` | 管理员 | 当前生效的配置，敏感值只显示是否已设置 |
| `POST /sanitize` | 是 | 脱敏一段配置文本：`{"text": "…", "level": "basic\|strict"}`；返回脱敏后的文本、厂商、各类替换数量和不含原值的替换报告 |
| `POST /configs` | 是 | 上传并导入配置（multipart：一个或多个 `files`，可以是 zip；`level` 默认 basic） |
| `GET /devices` | 是 | 已导入的设备与最新配置版本 |
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
| `GET /ai/status` | 是 | AI 是否已配置、各任务使用的模型 |
| `POST /ai/test` | 管理员 | 测试 AI 接口（未配置时 409） |
| `GET /ai/calls?limit=100` | 是 | AI 调用记录 |
| `POST /review/{id}` | 是 | `{"action": "approve" \| "reject", "note": "", "edited": {…}}` |
| `POST /parse` | 是 | 解析配置文本：`{"text": "…", "profile": null}`；返回 Profile、各类行数、覆盖率与每一行的结果 |
| `POST /render` | 是 | 解析建图后渲染回文本：`{"text": "…", "profile": null, "canonical": false, "with_defaults": false}`；默认往返模式（`mode: roundtrip`）；`canonical: true` 规范模式，`with_defaults: true` 含默认值的完整配置（默认值行前有 `! default` 注释），返回 `text`、`lines`（`no`、`text`、`kind`、`origin` explicit / default、`nodes`、`card`）、`default_lines`、`uncovered`、`skipped_extras` |
| `POST /translate` | 是 | 配置翻译：`{"text": "…" 或 "version_id": 1 或 "device_id": 1, "profile": null, "to": "<目标 Profile>", "interface_map": {"Port-channel1": "Eth-Trunk1"}, "verify": true}`；返回 `text` 译文、`lines`（同 `/render`）、`warnings`（`default_differs` / `default_unknown` / `inferred_value` / `implicit_object` / `interface_type` / `verify_diff` / `verify_unknown`）、`unsupported`（`kind` node / ext / raw / unknown / negated，`params.reason` 为 `profile_unsupported` / `no_render` / `secret` / `not_translated`）、`defaults`（`explicit_equals_default` 省略的默认值）、`stats` 与 `verify`（`checked`、`equal`、`diffs`、`unexplained`）；每一项都有 `kind`、`key`（文案键）、`params`（文案参数）、`node`（源图中的节点）、`schema`、`lines`（原文行号）；目标 Profile 不存在或没有给出源配置时 422，设备或版本不存在时 404；`rule_set`（规则集编号）或 `rules`（规则集内容）选用翻译规则集（REQ-032），结果另有 `naming`（同 `POST /translate-rules/test`），不给时结果不变 |
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
| `POST /change` | 是 | 增量变更脚本：`{"current": {"text" 或 "version_id" 或 "device_id", "profile"}, "target": {…}, "rollback": true, "verify": true, "impact": true, "style": null, "lang": null}`（当前与目标同一平台族）；返回 `ops`（逐条命令：`seq`、`action` add / modify / delete / side_effect / mutex、`text`、`context`、`view`、`depth`、`object`、`label`、`domain`、`risk` low / medium / high、`risk_reasons`、`after`（排在哪些命令之后：`seq`、`kind`、`node`、`label`、`note` 三语说明对象）、`fallback`、`lines`）、`script`（带说明）、`script_plain`、`script_rows`（按视图分块的脚本行：`kind` frame / enter / cmd / quit、`depth`、`text`、`seq`（cmd 行对应的命令序号），与 `script_plain` 逐行对应）、`risk`、`summary`、`unsupported`、`warnings`、`verify`（模拟执行：`ok`、`equal`、`diff_count`、`new_dangling`、`order_violations`、`issues`、`unknown`）、`rollback`（同样结构）、`impact`（`seeds`、`objects`、`business`、`by_domain`、`by_business`、`summary`）；平台族不同或没有给出配置时 422，设备或版本不存在时 404 |
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
| `GET /devices/{id}/graph?domain=D&raw=false&version_id=V` | 是 | 设备最新配置版本（给出 `version_id` 时为该版本，不属于该设备时 404）的配置图：节点、边（`note` 为三语说明对象 `{zh-CN, en, pt-BR}`，没有时为 `{}`）、悬空引用、统计；`raw=true` 时包含功能域外的原文节点与原始配置文本 |
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
| `GET /kb/profiles/{id}` | 是 | 继承展开后的全部条目（每个 Schema 节点一行，含来源 Profile 与可信度） |
| `PUT /kb/profiles/{id}/entries/{node}` | 是 | 人工修改条目：`{"supported", "default", "show_rule", "source", "verified", "note"}`，标记 `manual`，重新汇总时保留 |
| `DELETE /kb/profiles/{id}/entries/{node}` | 是 | 删除 Profile 自己的条目（继承来的条目在父 Profile 中修改） |
| `GET /kb/profile-compare?a=A&b=B` | 是 | 两个 Profile 逐节点对比：same / only_a / only_b / default（默认值不同）/ unfilled |
| `GET /kb/draft` | 是 | 草稿区：上次发布以来的修改（与 `/kb/diff` 相同结构）与提交记录 |
| `GET /kb/extractors` | 是 | 可用的命令卡抽取规则 |
| `GET /ai/settings` | 管理员 | AI 接口设置；API Key 只返回是否已设置；`sources` 标出各项来自配置文件还是环境变量 |
| `PUT /ai/settings` | 管理员 | 保存 AI 设置（只改配置文件的 AI 分组）：`{"provider", "base_url", "api_key", "clear_api_key", "model", "model_extract", "model_merge", "timeout", "max_tokens"}`；`api_key` 留空保持原值，加密保存 |
| `GET /projects?all=false&owner=U` | 是 | 我的项目（`mine`，属主）与共享给我的（`shared`，成员）；管理员 `all=true` 时另列出其他人的项目（`others`）。每个项目：`slug`、`name`、`owner`、`role`、`members`、`settings`（`style` 显示风格、`rule_set` 翻译规则集、`baseline` 安全基线）、`counts`（`devices`、`private`、`refs`、`scripts`、`scripts_with_errors`）、`last_activity`、`migrated_from`；`default_project` 为我的默认项目 |
| `POST /projects` | 是 | 新建项目：`{"name", "slug", "description", "settings"}`；`slug` 全站唯一（2–64 个小写字母、数字、短横线），不给时由名称生成；已被使用 409，不合法 422；还没有默认项目时它成为默认项目 |
| `GET /workspace` | 是 | 我的工作空间：默认项目、项目数、私有模板与规则集数、有效的个人令牌数 |
| `PUT /workspace/default-project` | 是 | 设置默认项目：`{"project"}`（旧的无项目接口与命令行不带 `--project` 时用它） |
| `GET /projects/{p}` | 项目成员 | 项目详情：另含 `member_list`（`username`、`role`、`since`）与 `overrides`（本项目的规则调整） |
| `PUT /projects/{p}` | 属主 / 可编辑 | 修改名称、说明、设置：`{"name", "description", "settings", "slug"}`；改标识只限属主与管理员 |
| `GET /projects/{p}/delete-preview` | 项目成员 | 删除项目的影响：私有设备与版本数、引用数（只解除）、检查项目与脚本数、忽略项、成员数 |
| `DELETE /projects/{p}?confirm=<标识>` | 属主 / 管理员 | 删除项目：私有设备与它们的全部版本一起删除，引用的公共设备只解除引用；`confirm` 必须等于项目标识（否则 422） |
| `GET /projects/{p}/members` | 项目成员 | 成员：属主与成员（`edit` / `read`），加入时间 |
| `PUT /projects/{p}/members/{username}` | 属主 / 管理员 | 邀请成员或改角色：`{"role": "edit\|read"}`；账号不存在 404，已停用 409 |
| `DELETE /projects/{p}/members/{username}` | 属主 / 管理员；本人 | 移除成员；成员移除自己即退出项目 |
| `POST /projects/{p}/transfer` | 属主 / 管理员 | 转交：`{"to", "keep_as": "edit\|read\|null"}`；原属主默认留作可编辑成员；项目设置中用到的、原属主私有的翻译规则集复制一份给新属主（`rule_set_copied`） |
| `POST /projects/{p}/copy` | 项目成员 | 复制为我的新项目：`{"name", "slug", "devices", "scripts"}`；复制设置、规则调整、私有设备（各复制当前版本）、引用（同样的版本策略）、脚本（当前内容）；不复制成员 |
| `GET /projects/{p}/refs` | 项目成员 | 本项目引用的公共设备：`policy`、`pinned_version_id`、`public_latest_version_id`、`newer_available` |
| `POST /projects/{p}/refs` | 属主 / 可编辑 | 引用公共设备：`{"device_id", "version_id"}`（不给版本时跟随最新）；项目里已有同名设备 409 |
| `PUT /projects/{p}/refs/{device_id}` | 属主 / 可编辑 | 改版本策略：`{"version_id": 编号 \| null}`（null 为跟随最新） |
| `DELETE /projects/{p}/refs/{device_id}` | 属主 / 可编辑 | 解除引用（本项目对它的忽略项一并删除，以它为基线的检查项目基线置空）；`DELETE /projects/{p}/devices/{id}` 对引用的公共设备也是解除引用 |
| `POST /projects/{p}/devices/copy-in` | 属主 / 可编辑 | 把公共设备或自己能查看的其他项目的设备复制为本项目的私有设备：`{"device_id", "version_id", "name"}`；只复制一个版本（默认来源中的当前版本），同名时自动加 `-2`、`-3`（`renamed`），`from` 记录来源 |
| `GET /projects/{p}/rules` | 项目成员 | 检查规则在本项目中的设置：共享的级别与开关、本项目的调整（`override`）、生效值（`effective`） |
| `PUT /projects/{p}/rules/{rule}` | 属主 / 可编辑 | 本项目关闭某条规则或改级别：`{"enabled", "severity", "reason"}`，原因必填；只影响本项目的检查（`checks` 结果中带 `project_override`） |
| `DELETE /projects/{p}/rules/{rule}` | 属主 / 可编辑 | 恢复为共享规则的设置 |
| `GET /projects/{p}/scripts?kind=&device_id=` | 项目成员 | 本项目全部脚本（平铺）：所在的检查项目（`group`）、基线设备与版本策略、最近一次检查、顺序核查、AI、修订数、最后修改人 |
| `POST /projects/{p}/scripts` | 属主 / 可编辑 | 新建脚本：`{"name", "kind", "device_id", "version_id", "content", "order_check", "ai_check"}`；同时建一个保存基线与检查设置的检查项目，返回 `group` 与 `script` |
| `POST /projects/{p}/devices/rebuild` | 属主 / 可编辑 | 按当前知识库重新解析本项目的设备（后台任务）；旧路径 `POST /devices/rebuild` 为全部设备，只限管理员 |
| `GET /public-devices` | 是 | 公共设备库：版本数、最新版本、引用它的项目（普通账号只看到自己能访问的项目）、跟随 / 固定的引用数 |
| `GET /public-devices/{id}/versions` | 是 | 公共设备的版本（新的在前） |
| `POST /public-devices` | 管理员 | 导入到公共设备库（multipart `files`、`level`）；同名设备作为新版本，跟随最新的项目随之更新 |
| `DELETE /public-devices/{id}?force=false` | 管理员 | 删除公共设备；还有项目引用时 409（`data.projects`），`force=true` 一并解除引用 |
| `DELETE /public-devices/{id}/versions/{vid}` | 管理员 | 删除公共设备的一个版本；固定在该版本的引用改为跟随最新 |
| `POST /public-devices/rebuild` | 管理员 | 按当前知识库重新解析公共设备库（后台任务） |
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
- `data.total` = `30`
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

### 新建项目（标识全站唯一）

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
- `data.skills.2.id` = `"ask-answer"`
- `data.skills.2.active` = `"builtin"`
- `data.skills.2.stats.calls` = `0`

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

### 显示风格的术语表（华为 / Cisco）

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

<!-- examples:end -->
