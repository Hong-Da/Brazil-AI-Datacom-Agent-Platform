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
| `lmesh kb map` | 把 `knowledge/mappings/` 中的映射规则写进命令卡（手工编辑过的 `maps_manual` 卡不覆盖），并按命令卡重新汇总各 Profile 的支持情况 |
| `lmesh parse <文件> [--profile P] [--lines/--summary]` | 解析配置：每行的视图、命令卡、参数、类别（command / raw 功能域外 / unknown 未识别 / separator / comment / blank / end）；不填 `--profile` 时按厂商与版本自动选择，识别不了时退出码 2 |
| `lmesh unknown list [--limit N]` | 已导入配置中的未识别行，按归一化后的模式与出现次数汇总（用来补命令卡） |
| `lmesh graph show <文件\|设备名> [--domain D] [--profile P]` | 显示配置图：语义节点（含 Profile 补出的隐藏默认节点）、依赖边（contains / reference / prerequisite / side_effect / mutex）、悬空引用 |
| `lmesh render <文件\|设备名> [--profile P] [--canonical] [--with-defaults]` | 解析建图后按图渲染回配置文本。默认往返模式：保留原有顺序、缩进与写法；`--canonical` 规范模式：只看图中的语义节点，按平台族写法重新生成命令（按视图分块、被引用的先出现，华为 `#` 分隔、`return` 结尾，Cisco `!` 与 `end`），未映射命令与功能域外原文按原文写回原位置；`--with-defaults` 含默认值的完整配置（规范模式，Profile 默认值也写成命令，集中放在所在块的显式行之后，前面一行注释 `! default`）。`--output json` 时 `lines` 给出每一行的来源节点、`origin`（explicit / default）、`kind`（command / original 按原文写回的命令 / extra 原文行 / separator / comment / exit / end），`default_lines` 为默认值行的行号，`uncovered` 为没能写成命令的节点（在 stderr 提示个数） |
| `lmesh translate <文件\|设备名> --to <Profile> [--interface-map 文件] [-o 文件] [--profile P] [--no-verify]` | 配置翻译：按有效值把配置翻译到目标 Profile（另一个平台族），接口名按映射表改写（子接口按父接口映射，没给映射表时同名）。默认值差异：源设备依赖默认值而目标默认值不同时显式写出并告警（`default_differs`），目标没有登记默认值时只提示（`default_unknown`），两边相同时不写；源设备显式值等于目标默认值时省略（`defaults`）。目标 Profile 不支持或写不出命令的节点、跨平台族的密码类取值（需重新设置）、未映射命令、功能域外原文、未识别行列在 `unsupported`（附原文行号），人工处理；目标写法必须给出、源配置没有的取值按推导规则写出并告警（`inferred_value`）；接口类型不属于目标平台族时告警（`interface_type`）。译文再解析建图后与源图按有效值对比（`verify`），列出项之外的差异记为 `verify_diff`。不给 `-o` 时译文写到 stdout、摘要与告警写到 stderr；**校验发现没有解释的差异时退出码 1** |
| `lmesh migrate <文件\|设备名> --to <Profile> [--interface-map 文件] [--target-config 文件] [--model 型号] [--on-conflict migrate\|keep] [-o 目录] [--suggest-only] [--profile P] [--no-verify]` | 割接迁移：翻译 + 接口映射，一次完成整机迁移。接口映射表可以只给部分（CSV / JSON / YAML / 两列文本，新接口写 `-` 表示不迁移），其余自动建议：逻辑接口（聚合口、环回口、桥域三层口等）编号不变换类型写法，物理口按同名 → 同速率同端口号 → 同速率依次 → 更高速率在端口清单中分配，每条附依据（`basis`）与置信度（`confidence`）；端口清单依次取 `--model` 指定型号的知识库清单（`knowledge/migration/ports/`）、`--target-config` 中的接口、知识库默认型号（提示 `port_inventory_assumed`）。管理口不迁移；没有映射的接口连同子接口、引用它们的配置不迁移；子接口跟随主接口；聚合口编号变化时成员口跟着改。给出新设备现有配置时在其上合并，只生成需要新增 / 修改的部分（`delta.cfg`），冲突按 `--on-conflict` 处理并告警。新配置再解析与旧设备按有效值对比（`verify`）。`-o` 目录里写 `new-config.cfg`、`delta.cfg`（有现有配置时）、`interface-map.csv`（可修改后用 `--interface-map` 传回）、`warnings.csv`、`steps.txt`（割接步骤：文字 + 命令，含回退）、`migration.json`，复用增量变更模块生成的下发与回滚脚本 `script.txt`、`rollback.txt`；`--suggest-only` 只给映射建议。不给 `-o` 时新配置写到 stdout、摘要与步骤写到 stderr；**校验发现没有解释的差异时退出码 1**，型号不存在等参数错误 2，文件不存在 4 |
| `lmesh roundtrip [<文件>] [--samples] [--profile P]` | 往返测试：配置 → 图 → 配置逐字比较；`--samples` 跑 `knowledge/samples/manifest.yaml` 中的全部样本，门槛样本还要求功能域内没有未识别行；不一致时退出码 1 |
| `lmesh compare <A> <B> [--domain D] [--raw] [--interface-map 文件] [--profile-a P] [--profile-b P] [--rename-threshold 0–1] [--hide-identity]` | 配置对比（同厂商或跨厂商都按 Schema 节点比较）：A、B 是配置文件或已导入的设备名（`设备名@版本编号` 取指定配置版本，版本编号见 `GET /devices/{id}/versions` 的 `id`，省略时取最新版本）。比较有效值（显式值，否则 Profile 默认值或派生值，显式写出默认值与不写结果相同）；值按节点类型规范化后比较（掩码与长度、接口名缩写与大小写、RD / RT 写法、RT 的 `both` 等于 import + export）；可被引用的对象（路由策略、前缀列表、VRF 等）内容相同只是名字不同时判为改名，引用随之对应；`--interface-map` 为跨厂商的接口对照（JSON / YAML 的 `{A: B}`，或每行两列的文本）；`--raw` 同时按所属对象比较功能域外的原文行；未识别行单独列出；只有一侧 Profile 有默认值的属性不可比，不算差异（`default_only`）。文本输出按功能域分组（`+` 新增、`-` 删除、`~` 修改、`»` 改名），`--output json` 输出完整结果；`--hide-identity` 隐藏设备身份差异（Router ID、接口 IPv4 地址、BGP 对等体地址、IS-IS NET、主机名等），被隐藏的个数见 `summary.hidden_identity`；**有差异时退出码仍为 0**，差异数见 `summary.total` |
| `lmesh check <文件\|设备名> [--rules 目录] [--severity error\|warning\|info] [--domain D] [--profile P]` | 配置检查：悬空引用、孤儿对象（含级联孤儿）、互斥冲突，以及知识库 `rules/` 中的规则约束；每条发现带规则编号、级别、规范编号、行号、说明与修复建议，并按级别、规则、功能域汇总；目标是已导入的设备时合并该设备的忽略记录（被忽略的发现标注原因，不计入级别统计与退出码）；内置检查的开关与级别按 `rules/builtin.yaml`；`--severity` 是最低级别，`--domain` 只看一个功能域；**筛选后仍有 error 级发现时退出码 1**（便于脚本判断），规则文件写错时退出码 3 并列出文件、规则与出错位置，`--rules` 目录不存在时退出码 4 |
| `lmesh cleanup <文件\|设备名> [-o 脚本文件] [--profile P] [--object 节点]…` | 冗余清理：为孤儿对象（含级联孤儿）生成删除命令脚本（华为 `undo …`、Cisco `no …`），先删引用方再删被引用方，`!` 注释行注明删除的对象与原配置行号；命令卡缺取消语法时用取消前缀 + 原命令兜底并标注 `FALLBACK`（JSON 中 `fallback: true`），需人工确认，`fallback_reason` 说明原因（`no_undo` / `undo_invalid` / `render_failed` / `match_failed`）；名称出现在未映射行中的对象不删除（`skipped`）；`--object` 只清理选中的对象（可多次）：只被它们引用的级联孤儿随之删除，只选级联孤儿而引用它的对象仍在时跳过（`parent_kept`），不是孤儿的跳过（`not_orphan`）；生成后在图上验证删除不会产生新的悬空引用，验证不通过时退出码 1 |
| `lmesh report compare <A> <B> [--lang zh-CN\|en] [--format html\|md] [-o 文件] [--domain D] [--raw] [--hide-identity] [--interface-map 文件] [--profile-a P] [--profile-b P] [--rename-threshold 0–1]` | 导出配置对比报告：报告头写两侧的设备、配置版本、软件版本、Profile、知识库版本、生成时间与选项；按功能域分表列出差异（两侧有效值、来源、原文行号），单列改名、不可比（default_only）、未识别行；`--lang` 默认跟随界面语言（pt-BR 用英文）；HTML 是自包含单文件、可打印，Markdown 适合贴进工单；不给 `-o` 时把报告写到 stdout（`--output json` 时放在 `data.content`）；文件名建议 `compare-<A>-<B>.<lang>.<ext>`（`data.filename`） |
| `lmesh report check <文件\|设备名> [--lang zh-CN\|en] [--format html\|md] [-o 文件] [--severity S] [--domain D] [--rules 目录] [--profile P]` | 导出配置检查报告：按严重度分组列出发现（规则、功能域、节点、行号、说明、建议），被忽略的发现单列并写明原因，有孤儿时附清理脚本与验证结论；文件名建议 `check-<设备>.<lang>.<ext>`；报告只是导出，不因 error 级发现返回非零退出码 |
| `lmesh topology [文件\|目录\|设备名\|编号…] [--all] [--profile P]` | 拓扑还原：多台设备（配置文件、目录中的配置文件、已导入设备的最新版本，`--all` 为全部已导入设备）按同网段接口、OSPF / IS-IS 邻接、本地与远端 LDP、BGP 对等、伪线、BFD 会话推导三层拓扑；每条链路给出两端设备与接口、网段、推导依据与置信度；对端不在这批设备中的列为 unresolved；按 Schema 的 cross_device 规则生成跨设备依赖边；没有给出设备时退出码 2，设备不存在时退出码 4 |
| `lmesh consistency [文件\|目录\|设备名\|编号…] [--all] [--severity error\|warning\|info] [--rules 文件] [--profile P]` | 跨设备一致性检查：按 `rules/cross-device.yaml` 比较链路两端（MTU、掩码、OSPF 区域 / 网络类型 / hello / dead / 认证 / 静默、IS-IS 级别与点到点、LDP 两端使能与认证、BGP 互相配置 / AS / 地址族 / 认证、伪线 VC ID / 控制字 / MTU、BFD 描述符与参数、VRRP），另有地址冲突检查；发现挂在链路上，按级别、规则、链路、设备汇总；**有 error 级发现时退出码 1**，规则文件写错时退出码 3，`--rules` 文件不存在时退出码 4 |
| `lmesh baseline [文件\|设备名…] [--all] [--profile basic\|strict] [--rules 目录] [--parse-profile P] [--report 文件.html\|文件.md] [--report-lang zh-CN\|en] [--style huawei\|cisco]` / `lmesh baseline --list-rules [--profile P]` | 安全基线审计：对一台或多台设备（配置文件、已导入设备的最新版本，`--all` 为全部已导入设备）跑知识库 `rules/` 中的基线规则（`kind: baseline` 的文件，`lmesh check` 不加载），`--profile` 选基线（`strict` 包含 `basic`）。每条规则在每台设备上的结论为 `pass` / `fail` / `na`（没有适用的对象），文字输出给出设备 × 规则矩阵、每台设备的得分（按级别加权：error 3、warning 2、info 1）与不符合项（规则、节点、原文行号、说明、修复建议、按设备平台族写法的参考命令）；`--report` 同时导出基线报告（按扩展名 HTML / Markdown）；`--parse-profile` 是配置文件的知识库 Profile（默认自动识别）。**有 error 级规则不通过时退出码 1**，基线名写错或没有给出设备时退出码 2，规则文件写错时退出码 3，设备不存在时退出码 4 |
| `lmesh rules list` / `lmesh rules set <规则> [--enable\|--disable] [--severity S]` | 检查规则的开关、级别与来源（`builtin` 或规则文件名）；`set` 修改运行时知识库：知识库规则写回所在的规则文件（保留注释与顺序），内置检查写入覆盖文件 `rules/builtin.yaml`，并提交一次；规则不存在退出码 4，什么都没给退出码 2 |
| `lmesh ignore list [--device 设备名]` / `ignore add <设备名> <规则> <节点> --reason 原因` / `ignore remove <编号>` | 忽略的检查发现：按（设备、规则、节点）唯一，原因必填（空时退出码 2），重复添加时更新原因；设备、规则或记录不存在时退出码 4 |
| `lmesh template list` / `template show <模板>` | 参数化模板（运行时知识库 `templates/`）：编号、名称、Profile、变量与块的个数；`show` 列出变量（类型、派生表达式）与正文；`<模板>` 是模板编号或模板文件路径；模板有问题时退出码 3 并列出位置与原因，不存在时退出码 4 |
| `lmesh template check <模板> <文件\|设备名> [--profile P] [--extra allow\|deny] [--extra-scope none\|matched\|domains]` | 按模板校验配置（在图上按有效值比较）：符合与否、提取的变量与块实例，逐项原因（`missing` 缺少、`value` 取值不符、`inconsistent` 前后不一致、`constraint` 违反约束、`count` 实例个数、`extra` 模板外的配置），附配置与模板正文的行号；`--extra` / `--extra-scope` 覆盖模板的 `match` 设置；**不符合时退出码 1** |
| `lmesh template extract <模板> <文件\|设备名>… [--format json\|csv] [-o 文件]` | 按模板提取变量，每份配置一行，格式与 `generate` 的参数表相同（CSV 中块变量写成 `块名.变量`、重复块的取值用分号连接）；不符合模板时仍输出提取结果，退出码 0 |
| `lmesh template draft <文件>… [--id 编号] [-o 模板文件] [--params-out 参数表] [--profile P]` | 模板制作辅助：从一份或几份同角色设备的配置生成模板草稿（第一份为基准）；在图上对齐各设备的节点，取值不同的词作为候选变量（名字建议、类型推断），只有一份时以设备身份与描述为候选；列出可选块与重复块候选，并用草稿校验每份源配置（自检） |
| `lmesh template generate <模板> <参数表> [--format csv\|json] [--out-dir 目录] [--engine text\|canon] [--target-profile P] [--no-verify]` | 批量生成：参数表每行生成一份配置；生成后解析（未识别行为 0）、往返（逐字一致）并按模板校验（符合且提取出的变量与输入一致），失败的行给出原因；`--engine canon` 用规范渲染器输出，可配合 `--target-profile` 生成另一平台族的配置；`--out-dir` 只写成功的行（`<设备名>.cfg`）；**有失败的行时退出码 1** |
| `lmesh template save <模板文件>` | 校验（含正文解析建图）后把模板写入运行时知识库的 `templates/<编号>.yaml` 并提交 |
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

### 解析华为 ATN 配置（自动选择 Profile）

```bash
lmesh --output json parse knowledge/samples/huawei-atn-v800r023/atn-access-01.cfg
```

退出码：`0`

JSON 输出中的关键字段：

- `data.profile` = `"huawei-atn-v800r023"`
- `data.coverage` = `1.0`
- `data.counts.command` = `1151`

### 单个配置的往返测试

```bash
lmesh --output json roundtrip knowledge/samples/cisco-iosxe-asr920-synthetic/pe-asr920-01.cfg
```

退出码：`0`

JSON 输出中的关键字段：

- `data.ok` = `true`
- `data.unknown` = `0`

### 全部样本的往返回归（0.1.0 验收门槛）

```bash
lmesh --output json roundtrip --samples
```

退出码：`0`

JSON 输出中的关键字段：

- `data.failed` = `0`
- `data.samples` = `17`

### 查看配置图的 VRF 部分

```bash
lmesh --output json graph show knowledge/samples/cisco-iosxe-asr920-synthetic/pe-asr920-01.cfg --domain vrf
```

退出码：`0`

JSON 输出中的关键字段：

- `data.profile` = `"cisco-iosxe-asr920-17.15"`
- `data.summary.dangling` = `0`

### 把配置图渲染回文本

```bash
lmesh render tests/inputs/configs/cisco/basic.cfg
```

退出码：`0`

输出包含：`router bgp 65000`、`vrf definition CLIENTE-A`

### 未识别行汇总（没有导入时）

```bash
lmesh --output json unknown list
```

退出码：`0`

JSON 输出中的关键字段：

- `data.patterns` = `[]`

### 对现网 ATN 配置跑基础基线

```bash
lmesh --output json baseline knowledge/samples/huawei-atn-v800r023/atn-access-01.cfg
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.baseline` = `"basic"`
- `data.devices.0.score` = `95`
- `data.devices.0.results.sec.telnet_disabled` = `"pass"`
- `data.devices.0.results.sec.syslog_server` = `"fail"`
- `data.devices.0.failures.0.rule` = `"sec.syslog_server"`
- `data.devices.0.failures.0.remedy` = `["info-center loghost <IP>", "info-center loghost source LoopBack0"]`
- `data.summary.has_errors` = `false`

### 两台设备跑严格基线（矩阵与得分）

```bash
lmesh --lang en baseline knowledge/samples/huawei-atn-v800r023/atn-access-01.cfg knowledge/samples/cisco-iosxe-asr920-synthetic/pe-asr920-02-igp-mgmt.cfg --profile strict
```

退出码：`0`

输出包含：`Baseline strict: 2 device(s), 26 rule(s), score 87`、`sec.snmp_v3_only               ✗              ✗`、`pe-asr920-02-igp-mgmt (cisco-iosxe) score 91`、`Reference commands: line con 0 | exec-timeout 10 0`

### 同时导出 Markdown 基线报告

```bash
lmesh --output json baseline knowledge/samples/huawei-atn-v800r025-synthetic/atn-igp-mgmt-01.cfg --report out/baseline.md --report-lang en
```

退出码：`0`

JSON 输出中的关键字段：

- `data.report.format` = `"md"`
- `data.report.lang` = `"en"`
- `data.report.filename` = `"baseline-basic-atn-igp-mgmt-01.en.md"`

### 列出基线与规则

```bash
lmesh --output json baseline --list-rules --profile strict
```

退出码：`0`

JSON 输出中的关键字段：

- `data.profile` = `"strict"`
- `data.profiles.0.id` = `"basic"`
- `data.profiles.1.chain` = `["basic", "strict"]`
- `data.rules.0.id` = `"sec.telnet_disabled"`
- `data.rules.0.remedy.huawei` = `["undo telnet server enable", "undo telnet ipv6 server enable"]`

### 华为接口绑定 VPN：绑定后自动补发 IP 地址（副作用，高风险），附回滚脚本与模拟验证

```bash
lmesh --output json change knowledge/samples/change/atn-base.cfg knowledge/samples/change/atn-bind-vpn.cfg --style huawei
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.family` = `"huawei-vrp8"`
- `data.ops.0.action` = `"add"`
- `data.ops.0.text` = `"ip binding vpn-instance OAM"`
- `data.ops.0.context` = `["interface GigabitEthernet0/2/2"]`
- `data.ops.1.action` = `"side_effect"`
- `data.ops.1.text` = `"ip address 10.3.0.1 255.255.255.252"`
- `data.ops.1.after.0.seq` = `1`
- `data.ops.1.after.0.kind` = `"side_effect"`
- `data.ops.1.risk` = `"high"`
- `data.risk.level` = `"high"`
- `data.verify.ok` = `true`
- `data.rollback.verify.ok` = `true`
- `data.script_plain` = `"system-view\ninterface GigabitEthernet0/2/2\n ip binding vpn-instance OAM\n ip address 10.3.0.1 255.255.255.252\nquit\ncommit\nreturn\n"`

### 下发脚本（带说明行）写到标准输出，摘要写到标准错误

```bash
lmesh --lang zh-CN change knowledge/samples/change/atn-base.cfg knowledge/samples/change/atn-policy-rename.cfg
```

退出码：`0`

输出包含：`system-view`、`ip ip-prefix LOOPBACKS-V2 index 10`、`# [3] 修改`、`undo ip ip-prefix LOOPBACKS index 10`、`commit`

错误提示（stderr）包含：`5 条命令`、`验证通过`

### 当前与目标不是同一平台族

```bash
lmesh change knowledge/samples/change/atn-base.cfg knowledge/samples/change/asr920-base.cfg
```

退出码：`2`

### 影响分析：改前缀列表影响哪些路由策略与 BGP 对等体（含路径）

```bash
lmesh --output json impact knowledge/samples/change/atn-base.cfg --node 'rp.prefix_list[LOOPBACKS]'
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.direction` = `"up"`
- `data.seeds.0.node` = `"rp.prefix_list[LOOPBACKS]"`
- `data.business.0.node` = `"bgp.instance[65000]/bgp.af[afi=ipv4,vrf=]/peer[RR]"`
- `data.business.0.type` = `"peer"`
- `data.business.0.path` = `["rp.prefix_list[LOOPBACKS]", "rp.policy[EXPORT-LOOPBACK]/node[10]/match_prefix_list", "rp.policy[EXPORT-LOOPBACK]/node[10]", "rp.policy[EXPORT-LOOPBACK]", "bgp.instance[65000]/bgp.af[afi=ipv4,vrf=]/peer[RR]/export_policy", "bgp.instance[65000]/bgp.af[afi=ipv4,vrf=]/peer[RR]"]`

### 影响分析的文字输出（VPN 实例影响的接口与地址族）

```bash
lmesh --lang zh-CN impact knowledge/samples/change/atn-base.cfg --node 'vrf.instance[RAN]'
```

退出码：`0`

输出包含：`业务对象`、`interface[GigabitEthernet0/2/1.101]`、`vrf.instance[RAN] → interface[GigabitEthernet0/2/1.101]/vrf`

### 检查配置文件（有 error 级发现时退出码 1）

```bash
lmesh --output json check tests/inputs/configs/check/huawei-issues.cfg
```

退出码：`1`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.summary.has_errors` = `true`
- `data.summary.by_severity.error` = `4`
- `data.summary.by_rule.ref.orphan_cascade` = `1`
- `data.findings.0.severity` = `"error"`

### 只看 VRF 功能域的警告及以上

```bash
lmesh --output json check tests/inputs/configs/check/cisco-issues.cfg --severity warning --domain vrf
```

退出码：`0`

JSON 输出中的关键字段：

- `data.summary.total` = `2`
- `data.summary.has_errors` = `false`
- `data.filters.domain` = `"vrf"`
- `data.summary.by_rule.vrf.rd_without_rt` = `1`

### 检查样本配置（文字输出）

```bash
lmesh --lang en check knowledge/samples/cisco-iosxe-asr920-synthetic/pe-asr920-01.cfg
```

退出码：`0`

输出包含：`1 finding(s)`、`rp.community_list RAN-COMM is not referenced anywhere`、`Fix: `

### 生成删除脚本（先删引用方，再删级联孤儿）

```bash
lmesh cleanup tests/inputs/configs/check/huawei-issues.cfg
```

退出码：`0`

输出包含：`undo route-policy UNUSED-POLICY node 10`、`undo ip ip-prefix ONLY-UNUSED index 10`、` undo group SPARE`

### 删除脚本写到文件（JSON 中逐条列出命令与是否兜底生成）

```bash
lmesh --output json cleanup tests/inputs/configs/check/cisco-issues.cfg -o out/cleanup.txt
```

退出码：`0`

JSON 输出中的关键字段：

- `data.fallbacks` = `0`
- `data.verify.ok` = `true`
- `data.commands.0.text` = `"no vrf definition UNUSED-VRF"`
- `data.commands.3.text` = `"no route-map UNUSED-MAP permit 10"`

### 对比两份配置文件（改 MTU、删邻居、改 RT、两级改名）

```bash
lmesh --output json compare knowledge/samples/cisco-iosxe-asr920-synthetic/pe-asr920-01.cfg knowledge/samples/compare/asr920-modified.cfg
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.equal` = `false`
- `data.summary.total` = `8`
- `data.summary.by_kind.renamed` = `2`
- `data.summary.by_kind.changed` = `1`
- `data.diffs.0.kind` = `"changed"`
- `data.diffs.0.node` = `"interface[GigabitEthernet0/0/0]/mtu"`
- `data.diffs.0.a.value` = `9216`
- `data.diffs.0.b.value` = `9000`

### 等价写法（重排、接口名缩写、RT both）没有差异

```bash
lmesh --lang zh-CN compare knowledge/samples/compare/asr920-reorder.cfg knowledge/samples/compare/asr920-ifname.cfg --raw
```

退出码：`0`

输出包含：`没有差异`、`未识别行：A 0 行，B 0 行`

### 只看一个功能域

```bash
lmesh --output json compare knowledge/samples/cisco-iosxe-asr920-synthetic/pe-asr920-01.cfg knowledge/samples/compare/asr920-modified.cfg --domain vrf
```

退出码：`0`

JSON 输出中的关键字段：

- `data.summary.total` = `2`
- `data.options.domain` = `"vrf"`
- `data.diffs.0.domain` = `"vrf"`

### 跨厂商对比（华为 → Cisco，带接口映射表）

```bash
lmesh --output json compare tests/inputs/compare/hw-pe.cfg tests/inputs/compare/cs-pe.cfg --interface-map tests/inputs/compare/ifmap.txt
```

退出码：`0`

JSON 输出中的关键字段：

- `data.equal` = `true`
- `data.a.profile` = `"huawei-atn-v800r023"`
- `data.b.profile` = `"cisco-iosxe-asr920-17.15"`
- `data.options.interface_map` = `2`
- `data.options.compare_ext` = `false`

### 不存在的功能域

```bash
lmesh compare tests/inputs/compare/hw-pe.cfg tests/inputs/compare/cs-pe.cfg --domain nope
```

退出码：`2`

错误提示（stderr）包含：`nope`

### 设备不存在

```bash
lmesh compare NO-SUCH-DEVICE tests/inputs/compare/cs-pe.cfg
```

退出码：`4`

错误提示（stderr）包含：`NO-SUCH-DEVICE`

### ASR 920 迁移到 ATN（新设备有出厂配置），输出目录里放新配置、增量配置、映射表、告警与步骤

```bash
lmesh --output json migrate knowledge/samples/cisco-iosxe-asr920-synthetic/pe-asr920-01.cfg --to huawei-atn-v800r025 --target-config knowledge/samples/migration/atn-factory.cfg -o out/mig
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.source.profile` = `"cisco-iosxe-asr920-17.15"`
- `data.target.existing` = `true`
- `data.inventory.source` = `"target_config"`
- `data.verify.unexplained` = `0`
- `data.interface_map.0.source` = `"BDI101"`
- `data.interface_map.0.target` = `"Vbdif101"`
- `data.interface_map.0.basis` = `"logical"`
- `data.steps.0.key` = `"migrate.step.precheck"`
- `data.files.0` = `"delta.cfg"`
- `data.files.1` = `"interface-map.csv"`

### 新配置写到标准输出，摘要、映射表、告警与割接步骤写到标准错误（部分映射表，其余自动建议）

```bash
lmesh --lang zh-CN migrate knowledge/samples/huawei-atn-v800r023/atn-access-01.cfg --to cisco-iosxe-asr920-17.15 --model ASR-920-24SZ-M --interface-map knowledge/samples/migration/atn-to-asr920.partial.yaml
```

退出码：`0`

输出包含：`interface Port-channel1`、`interface GigabitEthernet0/0/0`、`end`

错误提示（stderr）包含：`校验通过`、`同速率、同端口号`、`管理口，不迁移`、`速率不一致`、`按接口映射表迁移`

### 只给接口映射建议

```bash
lmesh --output json migrate knowledge/samples/huawei-atn-v800r025-synthetic/atn-mpls-l2vpn-acl-01.cfg --to huawei-atn-v800r025 --target-config knowledge/samples/migration/atn-other-model.cfg --suggest-only
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.map.0.source` = `"GigabitEthernet0/2/1"`
- `data.map.0.target` = `"GigabitEthernet0/1/1"`
- `data.map.0.basis` = `"same_index"`
- `data.map.0.confidence` = `0.8`
- `data.unmapped` = `[]`

### 同角色设备对比时隐藏身份差异（主机名、Router ID、环回地址、对等体地址）

```bash
lmesh --output json compare knowledge/samples/cisco-iosxe-asr920-synthetic/pe-asr920-01.cfg tests/inputs/configs/report/pe-asr920-02.cfg --raw --hide-identity
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.summary.total` = `1`
- `data.summary.hidden_identity` = `11`
- `data.diffs.0.node` = `"interface[GigabitEthernet0/0/0]/mtu"`
- `data.options.hide_identity` = `true`
- `data.options.hidden_identity.0.schema` = `"bgp.instance.router_id"`

### 导出对比报告（英文 Markdown，写到文件）

```bash
lmesh --output json report compare knowledge/samples/cisco-iosxe-asr920-synthetic/pe-asr920-01.cfg knowledge/samples/compare/asr920-modified.cfg --lang en --format md -o out/compare.md
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.filename` = `"compare-pe-asr920-01-asr920-modified.en.md"`
- `data.lang` = `"en"`
- `data.format` = `"md"`

### 检查报告（中文 Markdown）直接写到 stdout，有孤儿时附清理脚本

```bash
lmesh report check tests/inputs/configs/check/huawei-issues.cfg --lang zh-CN --format md
```

退出码：`0`

输出包含：`# 配置检查报告`、`### 错误 (4)`、`## 清理脚本`、`undo route-policy UNUSED-POLICY`

### 停用一条内置检查（写入运行时知识库的 rules/builtin.yaml 并提交）

```bash
lmesh --output json rules set ref.orphan_unsure --disable
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.id` = `"ref.orphan_unsure"`
- `data.enabled` = `false`
- `data.source` = `"builtin"`
- `data.severity` = `"info"`

### 只清理选中的对象（级联孤儿随父对象一起删除）

```bash
lmesh --output json cleanup tests/inputs/configs/check/huawei-issues.cfg --object 'rp.policy[UNUSED-POLICY]'
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.selected` = `true`
- `data.objects.0.node` = `"rp.policy[UNUSED-POLICY]"`
- `data.objects.1.node` = `"rp.prefix_list[ONLY-UNUSED]"`
- `data.commands.0.fallback` = `false`
- `data.verify.ok` = `true`

### 列出模板

```bash
lmesh --output json template list
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.templates.0.id` = `"cisco-asr920-efp-bdi-vrf"`
- `data.templates.0.valid` = `true`
- `data.templates.0.blocks` = `1`

### 按模板校验配置：符合，并提取变量

```bash
lmesh --output json template check cisco-asr920-efp-bdi-vrf tests/inputs/templates/pe-asr920-11.cfg
```

退出码：`0`

JSON 输出中的关键字段：

- `data.compliant` = `true`
- `data.variables.loopback` = `"10.255.0.31"`
- `data.variables.uplink_net` = `"10.1.0.20/30"`
- `data.blocks.svc.1.vrf` = `"MGMT"`
- `data.summary.instances.svc` = `2`

### 不符合模板：逐项原因与行号，退出码 1

```bash
lmesh --lang zh-CN template check cisco-asr920-efp-bdi-vrf tests/inputs/templates/pe-asr920-11-bad.cfg
```

退出码：`1`

输出包含：`不符合模板：2 处错误`、`interface[{uplink}]/mtu: 取值不符：模板 9216，实际 9000`、`svc.vlan 前后不一致：应为 102，实际 103`、`配置第 36 行`

### 提取变量为参数表（CSV，可直接用于生成）

```bash
lmesh template extract cisco-asr920-efp-bdi-vrf tests/inputs/templates/pe-asr920-11.cfg --format csv
```

退出码：`0`

输出包含：`device,hostname,asn,loopback`、`101;102,RAN-2G;MGMT,101;10`

### 模板 + 参数表批量生成：每行解析、往返并按模板校验

```bash
lmesh --output json template generate huawei-atn-l3vpn-subif tests/inputs/templates/atn-l3-sites.json --out-dir out/gen
```

退出码：`0`

JSON 输出中的关键字段：

- `data.summary.total` = `2`
- `data.summary.failed` = `0`
- `data.rows.0.file` = `"ATN-SITE-21.cfg"`
- `data.rows.0.checks.roundtrip` = `true`
- `data.rows.0.checks.template.compliant` = `true`

### 从同角色设备的配置生成模板草稿

```bash
lmesh --output json template draft tests/inputs/templates/pe-asr920-11.cfg tests/inputs/templates/pe-asr920-12.cfg --id asr-draft -o out/asr-draft.yaml --params-out out/asr-draft.csv
```

退出码：`0`

JSON 输出中的关键字段：

- `data.valid` = `true`
- `data.template_id` = `"asr-draft"`
- `data.vars.0.name` = `"hostname"`
- `data.vars.0.values` = `["PE-ASR920-11", "PE-ASR920-12"]`
- `data.verify.0.compliant` = `true`
- `data.verify.1.compliant` = `true`

### Cisco 配置的对比报告按华为风格显示节点

```bash
lmesh report compare knowledge/samples/cisco-iosxe-asr920-synthetic/pe-asr920-01.cfg knowledge/samples/compare/asr920-modified.cfg --format md --lang zh-CN --style huawei
```

退出码：`0`

输出包含：`ip vpn-instance RAN-2G`、`vpn-target 64512:1 import-extcommunity`

### 从一个目录的配置文件还原拓扑

```bash
lmesh --output json topology knowledge/samples/topology
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.summary.devices` = `5`
- `data.summary.links` = `26`
- `data.summary.by_type.bgp` = `4`
- `data.summary.by_type.pw` = `2`
- `data.links.0.type` = `"subnet"`
- `data.links.0.basis.rule` = `"subnet.p2p"`
- `data.nodes.0.id` = `"TOPO-AGG-01"`

### 两台设备的拓扑（文字输出，列出不在这批设备中的对端）

```bash
lmesh --lang en topology knowledge/samples/topology/atn-a1.cfg knowledge/samples/topology/atn-a2.cfg
```

退出码：`0`

输出包含：`2 device(s), 4 link(s), 5 peer(s) outside this set`、`subnet.p2p`、`bgp peer 10.255.1.1 of TOPO-ATN-A1 is not in this set`

### 跨设备一致性检查（有 error 级发现时退出码 1）

```bash
lmesh --output json consistency knowledge/samples/topology
```

退出码：`1`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.summary.total` = `13`
- `data.summary.by_severity.error` = `10`
- `data.summary.by_rule.xd.pw.vc_id` = `1`
- `data.summary.by_rule.xd.bgp.remote_as` = `1`
- `data.findings.0.severity` = `"error"`
- `data.rules_skipped.0.id` = `"xd.vrrp.virtual_ip"`

### 一条链路的一致性检查（文字输出）

```bash
lmesh --lang zh-CN consistency knowledge/samples/topology/atn-a1.cfg knowledge/samples/topology/agg-01.cfg
```

退出码：`0`

输出包含：`2 台设备、5 条链路：1 条发现`、`xd.subnet.mtu`、`TOPO-AGG-01 GigabitEthernet0/0/1 的 MTU 是 9216，TOPO-ATN-A1 GigabitEthernet0/2/1 是 9000（含默认值）`

### Cisco 配置翻译到华为（接口映射表；显式值等于目标默认值时省略）

```bash
lmesh --output json translate tests/inputs/translate/cs-small.cfg --to huawei-atn-v800r025 --interface-map tests/inputs/translate/ifmap.yaml
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.source.profile` = `"cisco-iosxe-asr920-17.15"`
- `data.target.profile` = `"huawei-atn-v800r025"`
- `data.verify.unexplained` = `0`
- `data.stats.defaults_omitted` = `1`
- `data.defaults.0.kind` = `"explicit_equals_default"`
- `data.defaults.0.node` = `"interface[GigabitEthernet0/0/1]/mtu"`
- `data.unsupported.0.kind` = `"raw"`
- `data.unsupported.0.params.text` = `"hostname R1"`
- `data.lines.5.text` = `"interface Eth-Trunk1"`

### 译文写到标准输出，摘要与告警写到标准错误

```bash
lmesh --lang zh-CN translate tests/inputs/translate/cs-small.cfg --to huawei-atn-v800r025
```

退出码：`0`

输出包含：`interface Port-channel1`、`ip route-static 0.0.0.0 0.0.0.0 10.0.0.2`、`return`

错误提示（stderr）包含：`校验通过`、`Port-channel 不是 huawei-vrp8 的接口类型`、`已省略`

### 规范模式渲染（按视图分块，Cisco 写 exit-address-family）

```bash
lmesh --output json render knowledge/samples/cisco-iosxe-asr920-synthetic/pe-asr920-01.cfg --canonical
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.mode` = `"canonical"`
- `data.with_defaults` = `false`
- `data.profile` = `"cisco-iosxe-asr920-17.15"`
- `data.uncovered` = `[]`
- `data.default_lines` = `[]`
- `data.lines.0.text` = `"!"`

### 含默认值的完整配置（默认值行前有 ! default 注释）

```bash
lmesh render tests/inputs/translate/cs-small.cfg --with-defaults
```

退出码：`0`

输出包含：`! default`、` no shutdown`、`end`

<!-- examples:end -->
