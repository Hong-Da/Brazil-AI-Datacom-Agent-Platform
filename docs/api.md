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

<!-- examples:end -->
