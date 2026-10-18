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
| `GET /devices/{id}/graph?domain=D&raw=false` | 是 | 设备最新配置版本的配置图：节点、边、悬空引用、统计；`raw=true` 时包含功能域外的原文节点与原始配置文本 |
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

<!-- examples:end -->
