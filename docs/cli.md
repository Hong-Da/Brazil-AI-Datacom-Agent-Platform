# CLI 调用文档

命令名 `lmesh`。供脚本、定时任务和其他 AI 工具调用；所有业务逻辑与 Web 界面、远程 API 共用。

## 调用方式

| 场景 | 写法 |
|---|---|
| 项目目录内（已运行过 start 脚本） | `uv run lmesh <参数>` |
| 任意目录（Windows） | `<项目目录>\cli.bat <参数>` |
| 任意目录（Linux） | `<项目目录>/cli.sh <参数>` |

包装脚本会先加载 `scripts/env`（工具链与缓存都在项目内）并处理中文编码。

## 全局参数

| 参数 | 作用 |
|---|---|
| `--config <路径>` | 指定配置文件（默认 `config/config.toml`） |
| `--lang zh-CN\|en\|pt-BR` | 输出语言，默认取配置中的 `ui.language` |
| `--output text\|json` | 输出格式，默认 `text`；`json` 供程序解析 |
| `--quiet` / `-q` | 只输出结果 |
| `--verbose` / `-v` | 同时把日志打印到 stderr |
| `--yes` / `-y` | 跳过所有确认提示（非终端调用时自动开启） |
| `--version` | 显示版本 |

每个命令都有 `--help`。

## JSON 输出

成功：

```json
{"ok": true, "data": { … }}
```

失败（同时把提示写到 stderr）：

```json
{"ok": false, "error": {"code": 3, "message": "…", "data": null}}
```

结构不随 `--lang` 变化；正常结果只写 stdout，不混入进度提示。

## 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 一般错误 |
| 2 | 参数错误 |
| 3 | 配置错误或未初始化 |
| 4 | 资源不存在 |
| 5 | 外部依赖失败（网络、数据库等） |

## 命令

| 命令 | 作用 |
|---|---|
| `lmesh status` | 运行状态：版本、是否已配置、数据库、知识库、AI 接口 |
| `lmesh serve [--host] [--port]` | 启动 Web 界面与远程 API；`--host`、`--port` 只临时覆盖，不改配置文件 |
| `lmesh setup [--defaults] [--force]` | 命令行版首次运行向导；`--defaults` 不提问，采用默认值与环境变量（Docker、自动化部署用） |
| `lmesh config show` | 当前生效的配置及来源（default / file / env），敏感值只显示是否已设置 |
| `lmesh config example [--check]` | 生成 `config/config.example.toml` |
| `lmesh db upgrade` | 把数据库升级到最新结构 |
| `lmesh sanitize <文件\|目录\|zip> -o <输出> [--level basic\|strict] [--redact 词或正则]… [--map-out 文件]` | 配置脱敏，行数不变；`basic` 替换密文、口令、团体字、密钥块、公网 IP，`strict` 另外替换全部 IP（前缀保持）、主机名、描述、用户名、网元 ID；`--redact` 追加客户名、站点编码等组织相关的词；`--map-out` 把原值与替换值的对照写到本机文件（敏感） |
| `lmesh config import <文件\|目录\|zip> [--level basic\|strict]` | 导入配置：识别厂商与版本 → 脱敏 → 按设备保存为新的配置版本；无法识别的文件单独报告 |
| `lmesh config list` | 已导入的设备、软件版本、Profile 与配置版本数 |
| `lmesh kb validate` | 校验知识库：YAML 格式、编号唯一、引用完整、语法、继承无环；有错误时退出码 1 |
| `lmesh kb export -o <zip>` | 导出知识库包 |
| `lmesh kb import <zip> [--dry-run]` | 导入知识库包：先校验；新文件直接加入，内容不同的文件作为冲突送审核队列，不直接覆盖 |
| `lmesh kb release [--version X] [-m 说明]` | 发布知识库版本：校验 → 回归测试 → 写入版本号 → 打标签 `kb-v<版本>`；不填版本号时按差异建议（删除节点或改语义升主版本，新增升次版本，修正默认值升修订号） |
| `lmesh kb releases` / `lmesh kb history` | 已发布的版本 / 提交历史 |
| `lmesh kb diff <版本> [<版本>]` | 两个版本之间新增、删除、修改的节点与命令卡、默认值变化；只给一个时与当前工作区对比 |
| `lmesh kb rollback <版本>` | 回滚到某个已发布版本（恢复文件后再提交一次，历史保留；需要确认，`--yes` 跳过） |
| `lmesh kb coverage [--profile P]` | 覆盖矩阵：各 Profile（继承展开后）对 Schema 节点支持、不支持、未填写的数量 |
| `lmesh kb ingest <文档> --rules <规则> [--domain D]… [--version V] [--ai]` | 导入产品文档（Markdown / HTML / PDF / CHM），按 `knowledge/extractors/` 中的规则抽取命令卡，以 draft 写入知识库并送审核队列；重复导入时没变化的卡跳过，已审核的卡有变化时只生成“更新”审核记录；`--ai` 把规则抽取失败的命令交给 AI 修正（结果必须能通过语法解析） |
| `lmesh review list [--kind K] [--status S]` / `review show <编号>` | 审核队列 |
| `lmesh review approve <编号>… [--note]` / `review reject <编号>…` | 通过或驳回；通过时写回知识库并提交 |
| `lmesh review approve-all [--kind card] [--contains 文字] [--rules 规则]` | 批量通过符合条件的待审条目（需要确认，`--yes` 跳过） |
| `lmesh ai test` / `lmesh ai calls` | 测试 AI 接口 / 最近的 AI 调用记录（任务、模型、token 用量、成功与否） |

知识库命令操作的是运行时知识库（默认 `data/knowledge/`，首次使用时从程序自带的 `knowledge/` 复制，并作为独立的 Git 仓库管理）。

同一台机器上，脱敏使用 `config/sanitize.key` 中的密钥：同一原值在不同批次里替换成同一个值，跨设备的引用关系保持。

配置也可以用环境变量覆盖：`LMESH_<分组>__<名称>`，例如 `LMESH_SERVER__PORT=9001`。

## 示例

以下示例由 `tests/cases/cli_cases.toml` 生成，测试通过即说明示例可用。

<!-- examples:begin -->

### 查看版本

```bash
lmesh --version
```

退出码：`0`

输出包含：`lmesh `

### 查看运行状态（JSON）

```bash
lmesh --output json status
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.configured` = `true`
- `data.database.backend` = `"sqlite"`
- `data.database.ok` = `true`

### 错误的输出格式

```bash
lmesh --output xml status
```

退出码：`2`

错误提示（stderr）包含：`--output`

### 非交互地完成首次配置（采用默认值与环境变量）

```bash
LMESH_SERVER__PORT=9123 lmesh --output json setup --defaults
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.token_generated` = `true`

### 已配置时再次运行向导

```bash
lmesh setup --defaults
```

退出码：`3`

错误提示（stderr）包含：`--force`

### 查看生效的配置（敏感值只显示是否已设置）

```bash
lmesh --output json config show
```

退出码：`0`

JSON 输出中的关键字段：

- `data.values.security.api_token` = `true`
- `data.sources.server.port` = `"file"`

### 升级数据库结构

```bash
lmesh --output json db upgrade
```

退出码：`0`

JSON 输出中的关键字段：

- `data.backend` = `"sqlite"`

### 脱敏单个配置文件（严格模式）

```bash
lmesh --output json sanitize tests/inputs/configs/huawei/basic.cfg -o out/basic.cfg --level strict
```

退出码：`0`

JSON 输出中的关键字段：

- `data.files.0.vendor` = `"huawei"`
- `data.files.0.ok` = `true`

### 输入文件不存在

```bash
lmesh sanitize tests/inputs/configs/no-such.cfg -o out/x.cfg
```

退出码：`4`

错误提示（stderr）包含：`no-such.cfg`

### 导入整个目录（无法识别的文件单独报告）

```bash
lmesh --output json config import tests/inputs/configs
```

退出码：`0`

JSON 输出中的关键字段：

- `data.files.0.ok` = `false`
- `data.files.2.vendor` = `"cisco"`
- `data.files.3.profile` = `"huawei-atn-v800r023"`

### 校验知识库

```bash
lmesh --output json kb validate
```

退出码：`0`

JSON 输出中的关键字段：

- `data.errors` = `0`
- `data.counts.profiles` = `3`

### 发布知识库版本（版本号按差异自动建议）

```bash
lmesh --output json kb release -m 'primeira versão'
```

退出码：`0`

JSON 输出中的关键字段：

- `data.version` = `"0.1.0"`
- `data.tag` = `"kb-v0.1.0"`

### 查看覆盖矩阵

```bash
lmesh --output json kb coverage --profile huawei-atn-v800r023
```

退出码：`0`

JSON 输出中的关键字段：

- `data.profiles` = `["huawei-atn-v800r023"]`

### 对比不存在的版本

```bash
lmesh kb diff 9.9.9
```

退出码：`4`

错误提示（stderr）包含：`9.9.9`

### 列出审核队列

```bash
lmesh --output json review list
```

退出码：`0`

JSON 输出中的关键字段：

- `data.total` = `0`

### 导入产品文档并抽取命令卡

```bash
lmesh --output json kb ingest tests/inputs/docs/huawei --rules tests/inputs/docs/rules-huawei-test.yaml --version V800R025C00SPC500
```

退出码：`0`

JSON 输出中的关键字段：

- `data.merge.new` = `4`
- `data.review_items` = `4`
- `data.skipped.excluded` = `1`

### 抽取规则不存在

```bash
lmesh kb ingest tests/inputs/docs/huawei --rules no-such-rules
```

退出码：`4`

错误提示（stderr）包含：`no-such-rules`

### 批量通过命令卡（无可通过的条目时）

```bash
lmesh --output json --yes review approve-all --kind card
```

退出码：`0`

JSON 输出中的关键字段：

- `data.approved` = `0`

### 测试 AI 接口（未配置）

```bash
lmesh ai test
```

退出码：`3`

错误提示（stderr）包含：`AI`

<!-- examples:end -->
