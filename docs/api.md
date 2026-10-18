# 远程 API 调用文档

供其他系统通过 HTTP 调用透网。机器可读的定义见 [openapi.json](openapi.json)，服务运行时也可以打开 `/docs` 查看。

## 基础

- 基础地址：`http://<地址>:<端口>/api/v1`，默认端口 9000
- 认证：除 `GET /health` 和首次运行向导外，所有接口都需要请求头 `Authorization: Bearer <令牌>`。令牌在首次配置时生成，保存在 `config/config.toml` 的 `[security] api_token`
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
| 1002 | 401 | 未认证或令牌错误 |
| 1003 | 409 | 当前状态不允许此操作（例如已配置后再提交向导） |
| 1004 | 404 | 资源不存在 |
| 1005 | 502 | 外部依赖失败（数据库、网络或 AI 接口） |

## 接口

| 接口 | 认证 | 作用 |
|---|---|---|
| `GET /health` | 否 | 健康检查：版本、是否已配置、数据库、知识库、AI 接口 |
| `GET /setup` | 否（仅未配置时） | 首次运行向导的参数定义 |
| `POST /setup` | 否（仅未配置时） | 提交向导结果；`dry_run: true` 时只校验 |
| `GET /config` | 是 | 当前生效的配置，敏感值只显示是否已设置 |
| `POST /sanitize` | 是 | 脱敏一段配置文本：`{"text": "…", "level": "basic\|strict"}`；返回脱敏后的文本、厂商、各类替换数量和不含原值的替换报告 |
| `POST /configs` | 是 | 上传并导入配置（multipart：一个或多个 `files`，可以是 zip；`level` 默认 basic） |
| `GET /devices` | 是 | 已导入的设备与最新配置版本 |
| `POST /kb/validate` | 是 | 校验知识库 |
| `GET /kb/export` | 是 | 下载知识库包（zip） |
| `POST /kb/import?dry_run=false` | 是 | 上传知识库包（multipart 字段 `file`）；冲突送审核队列 |
| `GET /kb/releases` | 是 | 已发布的版本、提交历史、当前版本号 |
| `POST /kb/releases` | 是 | 发布：`{"version": null, "message": "…"}`，版本号为空时自动建议 |
| `GET /kb/diff?from=X&to=Y` | 是 | 版本对比；省略 `to` 时与工作区对比 |
| `POST /kb/rollback` | 是 | 回滚：`{"ref": "0.1.0"}` |
| `GET /kb/coverage?profile=P` | 是 | 覆盖矩阵 |
| `POST /kb/ingest` | 是 | 导入产品文档：`{"doc_dir": "服务器上的目录", "rules": "huawei-vrp8-md", "domains": null, "version": "", "use_ai": false}`；后台任务，返回 `task_id` |
| `GET /tasks/{id}` | 是 | 耗时任务的状态（queued / running / done / failed）、进度、结果 |
| `GET /review?status=pending&kind=…` | 是 | 审核队列（含各类型待审数量） |
| `GET /review/{id}` | 是 | 审核条目详情 |
| `POST /review/batch` | 是 | 批量通过：`{"kind": "card", "contains": null, "rules": null}` |
| `GET /ai/status` | 是 | AI 是否已配置、各任务使用的模型 |
| `POST /ai/test` | 是 | 测试 AI 接口（未配置时 409） |
| `GET /ai/calls?limit=100` | 是 | AI 调用记录 |
| `POST /review/{id}` | 是 | `{"action": "approve" \| "reject", "note": "", "edited": {…}}` |
| `POST /parse` | 是 | 解析配置文本：`{"text": "…", "profile": null}`；返回 Profile、各类行数、覆盖率与每一行的结果 |
| `POST /render` | 是 | 解析建图后渲染回文本：`{"text": "…", "profile": null}` |
| `POST /roundtrip` | 是 | 往返测试：给出 `text` 时同步返回差异；`{"samples": true}` 时作为后台任务跑全部样本，返回 `task_id` |
| `GET /devices/{id}/graph?domain=D&raw=false&version_id=V` | 是 | 设备最新配置版本（给出 `version_id` 时为该版本，不属于该设备时 404）的配置图：节点、边、悬空引用、统计；`raw=true` 时包含功能域外的原文节点与原始配置文本 |
| `POST /compare` | 是 | 配置对比：`{"a": {"text": "…" \| "version_id": 1 \| "device_id": 1, "profile": null}, "b": {…}, "domain": null, "include_raw": false, "interface_map": {"GE0/2/1": "Gi0/0/1"}, "rename_threshold": 1.0, "hide_identity": false}`（每边给 `text`、`version_id`、`device_id`（最新版本）之一；同时给 `device_id` 与 `version_id` 时检查版本属于该设备）；返回 `diffs`（`kind` added / removed / changed / renamed、`node_kind` object / attr / ext / raw、`node` 规范编号、`schema`、`domain`、`a` / `b` 各自的 `node` 原始编号、`value` 有效值、`origin`、`lines`，改名的 `from` / `to` / `similarity`，删除或新增对象的 `count`，`related` 关联差异）、`renames`、`summary`（`total`、`by_kind`、`by_domain`、`by_object`、`unknown`、`default_only`）、`unknown`（两边的未识别行）、`default_only`（只有一侧 Profile 有默认值、不可比的属性）、`a` / `b`（来源、设备、Profile、版本）与 `options`；`hide_identity: true` 时隐藏设备身份差异（Router ID、接口 IPv4 地址、BGP 对等体地址、IS-IS NET、主机名等，清单见 `options.hidden_identity`），被隐藏的差异放在 `hidden_diffs`，个数为 `summary.hidden_identity`；设备或版本不存在时 404 |
| `GET /devices/{id}/versions` | 是 | 设备的配置版本列表（新的在前）：`id`、`seq`（设备内序号）、`source_name`、`collected_at`、`kb_version`、`lines`、`latest`；对比界面选“变更前后”用 |
| `POST /check` | 是 | 配置检查：`{"text": "…" 或 "device_id": 1, "profile": null, "severity": "info", "domain": null}`（`text` 与 `device_id` 二选一）；返回 `findings`（`rule`、`severity`、`domain`、`node`、`nodes`、`lines`、`message` / `suggestion` 为文案键 + 参数）、`summary`（`total` 含被忽略的发现，`ignored` 被忽略的个数；按级别、规则、功能域的计数与 `has_errors` 不含被忽略的）；按设备检查时每条发现带 `ignored`、`ignore_reason`、`ignore_id`、`texts`（规则文件文案的三种语言）；规则文件写错时 409，`data.issues` 为问题清单 |
| `GET /devices/{id}/check?severity=info&domain=D&version_id=V` | 是 | 检查设备的最新配置版本（给出 `version_id` 时检查该版本，版本不属于该设备时 404），结果同上 |
| `POST /cleanup` | 是 | 冗余清理：`{"text": "…" 或 "device_id": 1, "profile": null, "objects": null}`（`objects` 给出时只清理这些对象：只被选中对象引用的级联孤儿随之删除，只选级联孤儿而引用它的对象仍在时跳过，`skipped.reason` 为 `parent_kept`（附 `via`）、`not_orphan` 或 `maybe_referenced`；结果 `selected: true`）；返回待删除对象（`reason`：orphan / cascade）、按顺序的删除命令（`text`、`context` 所在视图、`object`、`lines`、`card`、`fallback`、`fallback_reason`：`no_undo` 命令卡没有取消语法 / `undo_invalid` 取消语法写错 / `render_failed` 用原行参数渲染不出 / `match_failed` 回匹配失败）、脚本文本 `script`、未删除的对象 `skipped` 与删除后验证 `verify` |
| `GET /devices/{id}/versions/{vid}/text` | 是 | 配置版本的原文（脱敏后）：`{text, version_id, device_id, source_name}`；版本不存在或不属于该设备时 404 |
| `GET /kb/rules` | 是 | 检查规则：内置检查与知识库 `rules/` 中的规则（编号、`enabled`、`severity`、`source`（`builtin` 或规则文件名）、内置检查的 `default_severity`、适用的 Schema 节点、条件，以及三种语言的标题、说明、建议） |
| `PUT /kb/rules/{rule_id}` | 是 | 修改规则的开关与级别：`{"enabled": false, "severity": "info"}`（至少给一项）；知识库规则写回所在的规则文件，内置检查写入覆盖文件 `rules/builtin.yaml`，并提交运行时知识库；返回更新后的规则（结构同 `GET /kb/rules` 的一条）；规则不存在 404，写回后规则文件校验不通过时恢复原文件并返回 409 |
| `GET /check/ignores?device_id=1` | 是 | 忽略的检查发现：`ignores`（`id`、`device_id`、`rule`、`node`、`reason`、`created_at`）；设备不存在时 404 |
| `POST /check/ignores` | 是 | 忽略一条检查发现：`{"device_id": 1, "rule": "ref.orphan", "node": "rp.policy[X]", "reason": "…"}`，按（设备、规则、节点）唯一，重复提交时更新原因（`created: false`）；`reason` 为空时 422，设备或规则不存在时 404 |
| `DELETE /check/ignores/{id}` | 是 | 取消忽略；记录不存在时 404 |
| `POST /reports` | 是 | 导出报告，直接返回文件（`Content-Disposition: attachment`）：`{"kind": "compare" \| "check", "lang": "zh-CN" \| "en", "format": "html" \| "md", "compare": <与 POST /compare 相同>, "check": <与 POST /check 相同>}`；HTML 是自包含单文件（内联样式、明亮配色、可打印），Markdown 适合贴进工单；文件名 `compare-<A>-<B>.<lang>.<ext>`、`check-<设备>.<lang>.<ext>`；报告头写设备、配置版本、软件版本、Profile、知识库版本、生成时间与选项；对比报告按功能域分表（两侧有效值、来源、原文行号），并单列改名、不可比（default_only）、未识别行；检查报告按严重度分组，被忽略的单列，有孤儿时附清理脚本；参数错误 422，设备不存在 404 |
| `GET /unknown-lines?limit=50` | 是 | 已导入配置中的未识别行汇总 |
| `GET /unknown-lines/states` | 是 | 各未识别行模式的送审状态（pending / approved / rejected） |
| `POST /unknown-lines/review` | 是 | 把选中的模式送入审核队列：`{"patterns": ["…"]}`；已送审的跳过 |
| `GET /summary` | 是 | 首页概况：知识库版本与草稿修改数、Profile 平均覆盖率、待审数、未识别行、设备（含用旧知识库解析过的数量）、最近一次样本回归、AI 状态 |
| `POST /devices/rebuild` | 是 | 按当前知识库重新解析全部设备（后台任务，返回 `task_id`） |
| `POST /devices/{id}/rebuild` | 是 | 按当前知识库重新解析一台设备 |
| `GET /regression/last` | 是 | 最近一次样本往返回归的结果；没跑过时为 `null` |
| `GET /tasks?kind=K&limit=20` | 是 | 最近的后台任务 |
| `GET /kb/schema` | 是 | Schema：各功能域的节点、依赖规则、可用的节点类型 |
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
| `GET /ai/settings` | 是 | AI 接口设置；API Key 只返回是否已设置；`sources` 标出各项来自配置文件还是环境变量 |
| `PUT /ai/settings` | 是 | 保存 AI 设置（只改配置文件的 AI 分组）：`{"provider", "base_url", "api_key", "clear_api_key", "model", "model_extract", "model_merge", "timeout", "max_tokens"}`；`api_key` 留空保持原值，加密保存 |

## 示例

以下示例由 `tests/cases/api_cases.toml` 生成，测试通过即说明示例可用。Windows 下 curl 的引号规则不同，请使用 PowerShell 写法。

<!-- examples:begin -->

### 健康检查（不需要认证）

`GET /api/v1/health`

```bash
curl -X GET 'http://127.0.0.1:9000/api/v1/health'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/health'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/health')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.configured` = `true`

### 未配置时读取向导参数

`GET /api/v1/setup`

```bash
curl -X GET 'http://127.0.0.1:9000/api/v1/setup'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/setup'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/setup')
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`

### 向导输入即校验：端口超出范围

`POST /api/v1/setup`

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/setup' \
  -H 'Content-Type: application/json' \
  -d '{"language": "zh-CN", "dry_run": true, "values": {"server.port": 70000}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/setup' -ContentType 'application/json; charset=utf-8' -Body '{"language": "zh-CN", "dry_run": true, "values": {"server.port": 70000}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/setup', json={'language': 'zh-CN', 'dry_run': True, 'values': {'server.port': 70000}})
print(r.status_code, r.json())
```

HTTP 状态：`422`；返回中的关键字段：

- `code` = `1001`

### 提交向导结果

`POST /api/v1/setup`

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/setup' \
  -H 'Content-Type: application/json' \
  -d '{"language": "en", "values": {"server.port": 9000, "security.api_token": "my-token-123456"}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/setup' -ContentType 'application/json; charset=utf-8' -Body '{"language": "en", "values": {"server.port": 9000, "security.api_token": "my-token-123456"}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/setup', json={'language': 'en', 'values': {'server.port': 9000, 'security.api_token': 'my-token-123456'}})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.api_token` = `"my-token-123456"`
- `data.token_generated` = `false`

### 已配置时不能再提交向导

`GET /api/v1/setup`

```bash
curl -X GET 'http://127.0.0.1:9000/api/v1/setup'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/setup'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/setup')
print(r.status_code, r.json())
```

HTTP 状态：`409`；返回中的关键字段：

- `code` = `1003`

### 读取生效的配置（需要令牌）

`GET /api/v1/config`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9000/api/v1/config' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/config' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/config', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.values.security.api_token` = `true`

### 缺少令牌

`GET /api/v1/config`

```bash
curl -X GET 'http://127.0.0.1:9000/api/v1/config'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/config'
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/config')
print(r.status_code, r.json())
```

HTTP 状态：`401`；返回中的关键字段：

- `code` = `1002`

### 脱敏一段配置文本

`POST /api/v1/sanitize`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/sanitize' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "sysname PE-01\n#\nbgp 65000\n peer 203.0.113.10 password cipher %^%#Fake%^%#\n#\nreturn", "level": "basic"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/sanitize' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "sysname PE-01\n#\nbgp 65000\n peer 203.0.113.10 password cipher %^%#Fake%^%#\n#\nreturn", "level": "basic"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/sanitize', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'sysname PE-01\n#\nbgp 65000\n peer 203.0.113.10 password cipher %^%#Fake%^%#\n#\nreturn', 'level': 'basic'})
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
curl -X POST 'http://127.0.0.1:9000/api/v1/configs' \
  -H 'Authorization: Bearer <令牌>' \
  -F 'files=@tests/inputs/configs/huawei/basic.cfg' \
  -F 'files=@tests/inputs/configs/bad/notes.txt' \
  -F 'level=strict'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/configs' -Headers @{'Authorization'='Bearer <令牌>'} -Form @{'files'=Get-Item 'tests/inputs/configs/huawei/basic.cfg'; 'level'='strict'}
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/configs', headers={'Authorization': 'Bearer <令牌>'}, files=[('files', open('tests/inputs/configs/huawei/basic.cfg', 'rb')), ('files', open('tests/inputs/configs/bad/notes.txt', 'rb'))], data={'level': 'strict'})
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
curl -X GET 'http://127.0.0.1:9000/api/v1/devices' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/devices' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/devices', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.devices` = `[]`

### 校验知识库

`POST /api/v1/kb/validate`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/kb/validate' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/kb/validate' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/kb/validate', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.errors` = `0`

### 发布知识库版本

`POST /api/v1/kb/releases`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/kb/releases' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"message": "primeira versão"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/kb/releases' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"message": "primeira versão"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/kb/releases', headers={'Authorization': 'Bearer <令牌>'}, json={'message': 'primeira versão'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.version` = `"0.1.0"`

### 已发布的版本与提交历史

`GET /api/v1/kb/releases`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9000/api/v1/kb/releases' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/kb/releases' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/kb/releases', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.releases` = `[]`

### 对比不存在的版本

`GET /api/v1/kb/diff?from=9.9.9`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9000/api/v1/kb/diff?from=9.9.9' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/kb/diff?from=9.9.9' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/kb/diff?from=9.9.9', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 覆盖矩阵

`GET /api/v1/kb/coverage`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9000/api/v1/kb/coverage' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/kb/coverage' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/kb/coverage', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`

### 审核队列

`GET /api/v1/review`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9000/api/v1/review' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/review' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/review', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.total` = `0`

### 审核不存在的条目

`POST /api/v1/review/999`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/review/999' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"action": "approve"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/review/999' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"action": "approve"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/review/999', headers={'Authorization': 'Bearer <令牌>'}, json={'action': 'approve'})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 导入不存在的文档目录

`POST /api/v1/kb/ingest`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/kb/ingest' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"doc_dir": "/no/such/dir", "rules": "huawei-vrp8-md"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/kb/ingest' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"doc_dir": "/no/such/dir", "rules": "huawei-vrp8-md"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/kb/ingest', headers={'Authorization': 'Bearer <令牌>'}, json={'doc_dir': '/no/such/dir', 'rules': 'huawei-vrp8-md'})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 查询不存在的任务

`GET /api/v1/tasks/nope`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9000/api/v1/tasks/nope' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/tasks/nope' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/tasks/nope', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 批量通过

`POST /api/v1/review/batch`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/review/batch' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"kind": "card", "contains": "vpn-target"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/review/batch' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"kind": "card", "contains": "vpn-target"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/review/batch', headers={'Authorization': 'Bearer <令牌>'}, json={'kind': 'card', 'contains': 'vpn-target'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.approved` = `0`

### AI 状态

`GET /api/v1/ai/status`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9000/api/v1/ai/status' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/ai/status' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/ai/status', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.configured` = `false`

### 测试 AI 接口（未配置）

`POST /api/v1/ai/test`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/ai/test' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/ai/test' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/ai/test', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`409`；返回中的关键字段：

- `code` = `1003`

### 解析配置文本

`POST /api/v1/parse`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/parse' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "hostname R1\n!\nrouter bgp 65000\n neighbor 10.0.0.2 remote-as 65001\n!\nend"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/parse' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "hostname R1\n!\nrouter bgp 65000\n neighbor 10.0.0.2 remote-as 65001\n!\nend"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/parse', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'hostname R1\n!\nrouter bgp 65000\n neighbor 10.0.0.2 remote-as 65001\n!\nend'})
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
curl -X POST 'http://127.0.0.1:9000/api/v1/roundtrip' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nreturn"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/roundtrip' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nreturn"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/roundtrip', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nreturn'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.ok` = `true`
- `data.unknown` = `0`

### 渲染回配置文本

`POST /api/v1/render`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/render' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "sysname R1\n#\nbgp 65000\n peer 10.0.0.1 as-number 65001\n#\nreturn"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/render' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "sysname R1\n#\nbgp 65000\n peer 10.0.0.1 as-number 65001\n#\nreturn"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/render', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'sysname R1\n#\nbgp 65000\n peer 10.0.0.1 as-number 65001\n#\nreturn'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.text` = `"sysname R1\n#\nbgp 65000\n peer 10.0.0.1 as-number 65001\n#\nreturn"`

### 设备不存在

`GET /api/v1/devices/999/graph`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9000/api/v1/devices/999/graph' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/devices/999/graph' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/devices/999/graph', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 未识别行汇总

`GET /api/v1/unknown-lines`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9000/api/v1/unknown-lines' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/unknown-lines' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/unknown-lines', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.patterns` = `[]`

### 检查一段配置

`POST /api/v1/check`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/check' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn", "severity": "info"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/check' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn", "severity": "info"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/check', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn', 'severity': 'info'})
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
curl -X GET 'http://127.0.0.1:9000/api/v1/devices/999/check' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/devices/999/check' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/devices/999/check', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 为一段配置生成删除脚本

`POST /api/v1/cleanup`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/cleanup' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn"}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/cleanup' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn"}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/cleanup', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn'})
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
curl -X GET 'http://127.0.0.1:9000/api/v1/kb/rules' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/kb/rules' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/kb/rules', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`200`；返回中的关键字段：

- `code` = `0`
- `data.builtin` = `6`
- `data.rules.0.id` = `"ref.dangling"`
- `data.rules.0.builtin` = `true`

### 对比两段配置文本（显式默认值不算差异，MTU 改动报出）

`POST /api/v1/compare`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/compare' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"a": {"text": "hostname R1\n!\ninterface GigabitEthernet0/0/1\n mtu 1500\n no shutdown\n ip address 10.0.0.1 255.255.255.0\n!\nend"}, "b": {"text": "hostname R1\n!\ninterface Gi0/0/1\n mtu 9000\n ip address 10.0.0.1 255.255.255.0\n!\nend"}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/compare' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"a": {"text": "hostname R1\n!\ninterface GigabitEthernet0/0/1\n mtu 1500\n no shutdown\n ip address 10.0.0.1 255.255.255.0\n!\nend"}, "b": {"text": "hostname R1\n!\ninterface Gi0/0/1\n mtu 9000\n ip address 10.0.0.1 255.255.255.0\n!\nend"}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/compare', headers={'Authorization': 'Bearer <令牌>'}, json={'a': {'text': 'hostname R1\n!\ninterface GigabitEthernet0/0/1\n mtu 1500\n no shutdown\n ip address 10.0.0.1 255.255.255.0\n!\nend'}, 'b': {'text': 'hostname R1\n!\ninterface Gi0/0/1\n mtu 9000\n ip address 10.0.0.1 255.255.255.0\n!\nend'}})
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
curl -X POST 'http://127.0.0.1:9000/api/v1/compare' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"a": {"text": "sysname X"}, "b": {"profile": "huawei-atn-v800r023"}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/compare' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"a": {"text": "sysname X"}, "b": {"profile": "huawei-atn-v800r023"}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/compare', headers={'Authorization': 'Bearer <令牌>'}, json={'a': {'text': 'sysname X'}, 'b': {'profile': 'huawei-atn-v800r023'}})
print(r.status_code, r.json())
```

HTTP 状态：`422`；返回中的关键字段：

- `code` = `1001`

### 设备不存在

`POST /api/v1/compare`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/compare' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"a": {"device_id": 999}, "b": {"text": "hostname R1"}}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/compare' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"a": {"device_id": 999}, "b": {"text": "hostname R1"}}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/compare', headers={'Authorization': 'Bearer <令牌>'}, json={'a': {'device_id': 999}, 'b': {'text': 'hostname R1'}})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 不存在的设备的配置版本

`GET /api/v1/devices/999/versions`（需要令牌）

```bash
curl -X GET 'http://127.0.0.1:9000/api/v1/devices/999/versions' \
  -H 'Authorization: Bearer <令牌>'
```

```powershell
Invoke-RestMethod -Method GET -Uri 'http://127.0.0.1:9000/api/v1/devices/999/versions' -Headers @{'Authorization'='Bearer <令牌>'}
```

```python
import requests
r = requests.request('GET', 'http://127.0.0.1:9000/api/v1/devices/999/versions', headers={'Authorization': 'Bearer <令牌>'})
print(r.status_code, r.json())
```

HTTP 状态：`404`；返回中的关键字段：

- `code` = `1004`

### 对比时隐藏设备身份差异（Router ID 不同不算差异）

`POST /api/v1/compare`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/compare' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"a": {"text": "hostname R1\nrouter bgp 64512\n bgp router-id 10.0.0.1\n neighbor 10.0.0.9 remote-as 64512\n", "profile": "cisco-iosxe-asr920-17.15"}, "b": {"text": "hostname R2\nrouter bgp 64512\n bgp router-id 10.0.0.2\n neighbor 10.0.0.9 remote-as 64512\n", "profile": "cisco-iosxe-asr920-17.15"}, "hide_identity": true}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/compare' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"a": {"text": "hostname R1\nrouter bgp 64512\n bgp router-id 10.0.0.1\n neighbor 10.0.0.9 remote-as 64512\n", "profile": "cisco-iosxe-asr920-17.15"}, "b": {"text": "hostname R2\nrouter bgp 64512\n bgp router-id 10.0.0.2\n neighbor 10.0.0.9 remote-as 64512\n", "profile": "cisco-iosxe-asr920-17.15"}, "hide_identity": true}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/compare', headers={'Authorization': 'Bearer <令牌>'}, json={'a': {'text': 'hostname R1\nrouter bgp 64512\n bgp router-id 10.0.0.1\n neighbor 10.0.0.9 remote-as 64512\n', 'profile': 'cisco-iosxe-asr920-17.15'}, 'b': {'text': 'hostname R2\nrouter bgp 64512\n bgp router-id 10.0.0.2\n neighbor 10.0.0.9 remote-as 64512\n', 'profile': 'cisco-iosxe-asr920-17.15'}, 'hide_identity': True})
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
curl -X PUT 'http://127.0.0.1:9000/api/v1/kb/rules/ref.orphan' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"enabled": false, "severity": "info"}'
```

```powershell
Invoke-RestMethod -Method PUT -Uri 'http://127.0.0.1:9000/api/v1/kb/rules/ref.orphan' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"enabled": false, "severity": "info"}'
```

```python
import requests
r = requests.request('PUT', 'http://127.0.0.1:9000/api/v1/kb/rules/ref.orphan', headers={'Authorization': 'Bearer <令牌>'}, json={'enabled': False, 'severity': 'info'})
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
curl -X POST 'http://127.0.0.1:9000/api/v1/check/ignores' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"device_id": 1, "rule": "ref.orphan", "node": "vrf.instance[X]", "reason": "  "}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/check/ignores' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"device_id": 1, "rule": "ref.orphan", "node": "vrf.instance[X]", "reason": "  "}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/check/ignores', headers={'Authorization': 'Bearer <令牌>'}, json={'device_id': 1, 'rule': 'ref.orphan', 'node': 'vrf.instance[X]', 'reason': '  '})
print(r.status_code, r.json())
```

HTTP 状态：`422`；返回中的关键字段：

- `code` = `1001`

### 只清理选中的对象

`POST /api/v1/cleanup`（需要令牌）

```bash
curl -X POST 'http://127.0.0.1:9000/api/v1/cleanup' \
  -H 'Authorization: Bearer <令牌>' \
  -H 'Content-Type: application/json' \
  -d '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn", "objects": ["rp.policy[UNUSED]", "vrf.instance[NOPE]"]}'
```

```powershell
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:9000/api/v1/cleanup' -Headers @{'Authorization'='Bearer <令牌>'} -ContentType 'application/json; charset=utf-8' -Body '{"text": "sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn", "objects": ["rp.policy[UNUSED]", "vrf.instance[NOPE]"]}'
```

```python
import requests
r = requests.request('POST', 'http://127.0.0.1:9000/api/v1/cleanup', headers={'Authorization': 'Bearer <令牌>'}, json={'text': 'sysname R1\n#\nip vpn-instance RAN\n ipv4-family\n  route-distinguisher 65000:1\n#\nroute-policy UNUSED permit node 10\n#\nreturn', 'objects': ['rp.policy[UNUSED]', 'vrf.instance[NOPE]']})
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

<!-- examples:end -->
