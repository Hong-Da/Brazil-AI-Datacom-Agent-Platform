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
| `--project <项目>` / `-P` | 命令作用于哪个项目（M6）：项目标识、`属主/标识` 或项目编号；不给时用默认项目；项目不存在退出码 4。标识只在属主内唯一：只写标识时先找 `--as` 账号自己的项目，没有时在他能访问的项目里找，有多个同名时退出码 2（提示写成 `属主/标识`，`--output json` 的 `error.data.candidates` 列出候选） |
| `--network <网络>` / `-N` | 命令作用于项目（`--project`，不给时默认项目）里的哪个网络（M9）：网络标识或编号；不给时为默认网络（包含全部设备），所以已有脚本照常运行；网络不存在退出码 4。拓扑、检查、忽略、规则调整、脚本、AI 建议等按网络的命令只看这个网络的设备与数据 |
| `--as <账号>` | 以哪个账号的身份：默认项目、新建项目与个人令牌的属主，调用 AI 时按这个账号的 AI 选择（REQ-040）；默认第一个启用的管理员（还没有账号时等同全局令牌，用第一个可用的管理员 AI 接口） |
| `--version` | 显示版本 |

命令行直接操作本机数据库，权限等同管理员（不按项目角色限制）；设备相关的命令（导入、列表、配置图、对比、检查、版本历史、拓扑、导出……）都只看当前项目里的设备（私有设备与引用的公共设备），给了 `--network` 时只看该网络的成员（M9）；在网络里导入的设备同时加入该网络。

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
| `lmesh user list [--pending]` | 网页登录账号列表：用户名、角色、状态（启用 / 待审核 / 锁定至 / 已停用）、最后登录（REQ-030）；`--pending` 只列自助注册后待审核的账号（REQ-039） |
| `lmesh user approve <名称>` / `lmesh user reject <名称>` | 批准（可以登录，建好默认项目）/ 拒绝（删除，用户名可再注册）自助注册的待审核账号；不是待审核退出码 1，账号不存在退出码 4；记入审计。注册开关等设置项见配置文件 `[auth]`（`auth.registration`、`auth.registration_approval`、`auth.registration_rate_per_hour`），也可以在网页账号管理里改 |
| `lmesh user add <名称> [--role admin\|maintainer\|user] [--password-stdin]` | 新建账号（默认普通用户）；密码从提示读取（不回显、输入两次），或用 `--password-stdin` 从标准输入读第一行，不接受命令行明文；没有终端又没给 `--password-stdin` 时退出码 2；用户名已存在退出码 1 |
| `lmesh user disable <名称>` / `lmesh user enable <名称>` | 停用（该账号的会话立即失效）/ 启用（同时解除锁定）；最后一个启用的管理员不能停用（退出码 1） |
| `lmesh user reset-password <名称> [--password-stdin]` | 重置密码：同时解除锁定，该账号的会话全部失效 |
| `lmesh user set-role <名称> admin\|maintainer\|user` | 改角色（maintainer 为知识库维护员）；最后一个启用的管理员不能改成其他角色 |
| `lmesh user delete <名称> [--transfer-to 账号 \| --delete-projects]` | 删除账号（需要确认，`--yes` 跳过）；账号不存在退出码 4；拥有非空项目时必须选择转交（项目、私有模板与规则集）或一并删除，否则退出码 1 |
| `lmesh config show` | 当前生效的配置及来源（default / file / env），敏感值只显示是否已设置 |
| `lmesh config example [--check]` | 生成 `config/config.example.toml` |
| `lmesh config get <键>` | 一个配置项的当前值、来源、默认值、是否需重启（`restart`）、能否修改（`readonly`：env 环境变量指定 / ai 在 AI 接口页管理 / secret 敏感值）；没有这个配置项时退出码 4（REQ-049） |
| `lmesh config set <键=值>…` | 修改配置项并写入 `config/config.toml`，与网页“系统设置”同一套校验（端口占用、取值范围、可选值）；敏感值、环境变量指定的项、AI 接口项不能改；不合格时退出码 2、不写入；结果里 `restart_required` 列出要重启服务才生效的项（监听地址、端口、数据库、知识库目录、日志），不会自动重启 |
| `lmesh db upgrade` | 把数据库升级到最新结构 |
| `lmesh sanitize <文件\|目录\|zip> -o <输出> [--level basic\|strict] [--redact 词或正则]… [--map-out 文件]` | 配置脱敏，行数不变；`basic` 替换密文、口令、团体字、密钥块、公网 IP，`strict` 另外替换全部 IP（前缀保持）、主机名、描述、用户名、网元 ID；`--redact` 追加客户名、站点编码等组织相关的词；`--map-out` 把原值与替换值的对照写到本机文件（敏感） |
| `lmesh config import <文件\|目录\|zip> [--level basic\|strict] [--profile P] [--keep-unsupported] [--remember project\|global [--match-name 模式] [--match-version 正则] [--match-feature 正则]]` | 导入配置：识别厂商与版本 → 选 Profile → 脱敏 → 按设备保存为新的配置版本。Profile 的选择顺序（REQ-044）：`--profile` 手工指定（只允许同厂商 / 同平台族，认不出厂商时任意）→ 设备之前的手工选择 → 型号规则 → 版本规则 → 厂商默认（fallback）；结果里 `profile_source` 为 auto / fallback / rule / manual / none、`match_level` 为 exact / approx / none。`--remember` 把 `--profile` 记住为型号规则（不写条件时按设备名与版本预填）。认不出厂商的文件默认不导入（单独报告），`--keep-unsupported` 时只存原文（不解析，标为不支持的厂商） |
| `lmesh config list` | 已导入的设备、软件版本、Profile 与配置版本数 |
| `lmesh kb validate` | 校验知识库：YAML 格式、编号唯一、引用完整、语法、继承无环；有错误时退出码 1 |
| `lmesh kb export -o <zip>` | 导出知识库包 |
| `lmesh kb import <zip> [--dry-run]` | 导入知识库包：先校验；新文件直接加入，内容不同的文件作为冲突送审核队列，不直接覆盖 |
| `lmesh kb release [--version X] [-m 说明]` | 发布知识库版本：校验 → 回归测试 → 写入版本号 → 打标签 `kb-v<版本>`；不填版本号时按差异建议（删除节点或改语义升主版本，新增升次版本，修正默认值升修订号） |
| `lmesh kb releases` / `lmesh kb history` | 已发布的版本 / 提交历史 |
| `lmesh kb diff <版本> [<版本>]` | 两个版本之间新增、删除、修改的节点与命令卡、默认值变化；只给一个时与当前工作区对比 |
| `lmesh kb rollback <版本>` | 回滚到某个已发布版本（恢复文件后再提交一次，历史保留；需要确认，`--yes` 跳过） |
| `lmesh kb upgrade [--dry-run] [--rollback]` | 升级后合并程序自带的知识库（REQ-046）：与 `builtin` 分支上次的自带快照三方比较，用户没改过的文件采用新版本，双方都改过的保留用户版本并作为冲突（来源 `kb-upgrade`）送审核队列，结果记一条发布记录；没有基准的旧安装把与新版本不同的文件全部送审核；`--dry-run` 只列出，`--rollback` 回滚最近一次升级合并（需要确认，`--yes` 跳过）；`lmesh serve` 启动时也会自动合并，详见 [deploy.md](deploy.md#升级时知识库如何合并) |
| `lmesh kb coverage [--profile P]` | 覆盖矩阵：各 Profile（继承展开后）对 Schema 节点支持、不支持、未填写的数量 |
| `lmesh kb ingest <文档> --rules <规则> [--domain D]… [--version V] [--ai]` | 导入产品文档（Markdown / HTML / PDF / CHM），按 `knowledge/extractors/` 中的规则抽取命令卡，以 draft 写入知识库并送审核队列；重复导入时没变化的卡跳过，已审核的卡有变化时只生成“更新”审核记录；`--ai` 把规则抽取失败的命令交给 AI 修正（结果必须能通过语法解析） |
| `lmesh review list [--kind K] [--status S]` / `review show <编号>` | 审核队列 |
| `lmesh review approve <编号>… [--note]` / `review reject <编号>…` | 通过或驳回；通过时写回知识库并提交 |
| `lmesh review approve-all [--kind card] [--contains 文字] [--rules 规则]` | 批量通过符合条件的待审条目（需要确认，`--yes` 跳过） |
| `lmesh kb map [--family F]…` | 把 `knowledge/mappings/` 中的映射规则写进命令卡（手工编辑过的 `maps_manual` 卡不覆盖），并按命令卡重新汇总各 Profile 的支持情况；`--family`（可重复）只处理这些平台族的命令卡与 Profile，接入新平台族时不重写其他平台族的文件 |
| `lmesh parse <文件> [--profile P] [--lines/--summary]` | 解析配置：每行的视图、命令卡、参数、类别（command / raw 功能域外 / unknown 未识别 / separator / comment / blank / end）；不填 `--profile` 时按厂商与版本自动选择，识别不了时退出码 2 |
| `lmesh unknown list [--limit N]` | 已导入配置中的未识别行，按归一化后的模式与出现次数汇总（用来补命令卡） |
| `lmesh graph show <文件\|设备名> [--domain D] [--profile P]` | 显示配置图：语义节点（含 Profile 补出的隐藏默认节点）、依赖边（contains / reference / prerequisite / side_effect / mutex）、悬空引用 |
| `lmesh analyze <文件\|设备名> [--part summary\|layers\|script]… [--profile P]` | 设备配置分析（REQ-034，默认 `summary` 与 `layers`）：`summary` 为各功能域对象数、行的分类计数与覆盖率、配置检查发现（按级别）、安全基线（basic）得分与不符合项、依赖默认值的关键配置（取值来自 Profile 默认值、而其他平台族默认值不同的属性）、悬空引用数，目标是已导入的设备时另有与上一版本相比的变化；`layers` 按 `knowledge/layers.yaml` 把节点归到 TCP/IP 各层（物理、数据链路、2.5 层 MPLS、网络、传输、应用，QoS 与时钟同步为跨层特性）并列出跨层依赖；`script` 为结构化脚本（每行的层级、所属节点、功能域与层、关键字 / 参数 / 引用的字符区间、被引用处、隐藏的默认值行）。`--part` 写错时退出码 2 |
| `lmesh render <文件\|设备名> [--profile P] [--canonical] [--with-defaults]` | 解析建图后按图渲染回配置文本。默认往返模式：保留原有顺序、缩进与写法；`--canonical` 规范模式：只看图中的语义节点，按平台族写法重新生成命令（按视图分块、被引用的先出现，华为 `#` 分隔、`return` 结尾，Cisco `!` 与 `end`），未映射命令与功能域外原文按原文写回原位置；`--with-defaults` 含默认值的完整配置（规范模式，Profile 默认值也写成命令，集中放在所在块的显式行之后，前面一行注释 `! default`）。`--output json` 时 `lines` 给出每一行的来源节点、`origin`（explicit / default）、`kind`（command / original 按原文写回的命令 / extra 原文行 / separator / comment / exit / end），`default_lines` 为默认值行的行号，`uncovered` 为没能写成命令的节点（在 stderr 提示个数） |
| `lmesh translate <文件\|设备名> --to <Profile> [--interface-map 文件] [-o 文件] [--profile P] [--no-verify] [--rules 规则集]` | 配置翻译：按有效值把配置翻译到目标 Profile（另一个平台族），接口名按映射表改写（子接口按父接口映射，没给映射表时同名）。默认值差异：源设备依赖默认值而目标默认值不同时显式写出并告警（`default_differs`），目标没有登记默认值时只提示（`default_unknown`），两边相同时不写；源设备显式值等于目标默认值时省略（`defaults`）。目标 Profile 不支持或写不出命令的节点、跨平台族的密码类取值（需重新设置）、未映射命令、功能域外原文、未识别行列在 `unsupported`（附原文行号），人工处理；目标写法必须给出、源配置没有的取值按推导规则写出并告警（`inferred_value`）；接口类型不属于目标平台族时告警（`interface_type`）。译文再解析建图后与源图按有效值对比（`verify`），列出项之外的差异记为 `verify_diff`。不给 `-o` 时译文写到 stdout、摘要与告警写到 stderr；**校验发现没有解释的差异时退出码 1**；`--rules <规则集编号或文件>` 先按翻译规则集改名（REQ-032，对象与引用一起改、端口按规则映射，显式映射表优先），结果另有 `naming` |
| `lmesh migrate <文件\|设备名> --to <Profile> [--interface-map 文件] [--target-config 文件] [--model 型号] [--on-conflict migrate\|keep] [-o 目录] [--suggest-only] [--profile P] [--no-verify] [--rules 规则集]` | 割接迁移：翻译 + 接口映射，一次完成整机迁移。接口映射表可以只给部分（CSV / JSON / YAML / 两列文本，新接口写 `-` 表示不迁移），其余自动建议：逻辑接口（聚合口、环回口、桥域三层口等）编号不变换类型写法，物理口按同名 → 同速率同端口号 → 同速率依次 → 更高速率在端口清单中分配，每条附依据（`basis`）与置信度（`confidence`）；端口清单依次取 `--model` 指定型号的知识库清单（`knowledge/migration/ports/`）、`--target-config` 中的接口、知识库默认型号（提示 `port_inventory_assumed`）。管理口不迁移；没有映射的接口连同子接口、引用它们的配置不迁移；子接口跟随主接口；聚合口编号变化时成员口跟着改。给出新设备现有配置时在其上合并，只生成需要新增 / 修改的部分（`delta.cfg`），冲突按 `--on-conflict` 处理并告警。新配置再解析与旧设备按有效值对比（`verify`）。`-o` 目录里写 `new-config.cfg`、`delta.cfg`（有现有配置时）、`interface-map.csv`（可修改后用 `--interface-map` 传回）、`warnings.csv`、`steps.txt`（割接步骤：文字 + 命令，含回退）、`migration.json`，复用增量变更模块生成的下发与回滚脚本 `script.txt`、`rollback.txt`；`--suggest-only` 只给映射建议。不给 `-o` 时新配置写到 stdout、摘要与步骤写到 stderr；**校验发现没有解释的差异时退出码 1**，型号不存在等参数错误 2，文件不存在 4；`--rules` 按翻译规则集改名并把端口映射规则并入映射表（用户映射表 > 规则集 > 自动建议，REQ-032） |
| `lmesh naming list` | 翻译规则集（REQ-032）列表：内置示例（`knowledge/translate-rules/`，只读）与我的（`data/translate-rules/`），三类规则的条数；规则集有问题时列出问题数 |
| `lmesh naming show <规则集>` | 显示规则集的 YAML 原文（编号或文件）；规则集不存在退出码 4 |
| `lmesh naming test <规则集> <文件\|设备名> [--to Profile] [--target-config 文件] [--profile P]` | 试运行：按规则集在图上改名，列出改名清单（原名 → 新名、命中的规则、整理动作、同步改的引用）、端口映射（子接口随主接口）、冲突（多对一、与未改名的同类对象重名、与目标设备已有名称重名：都不执行）、命名规范告警、原文行中的旧名、知识缺口（目标平台没有登记名称长度上限）；**有冲突时退出码 1** |
| `lmesh naming match <规则集> <名称> [--type 对象类型] [--port] [--to Profile]` | 测试一个名称（或 `--port` 接口名）经过规则后的结果：命中的规则、映射后、整理后的名称与告警 |
| `lmesh naming import <文件> [--id 编号] [--overwrite]` | 导入规则集到 `data/translate-rules/`；规则有误退出码 3（列出问题），编号已存在（不加 `--overwrite`）或与内置规则集同编号退出码 1 |
| `lmesh naming delete <编号>` | 删除我的规则集；内置规则集只读（退出码 1），不存在退出码 4 |
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
| `lmesh template generate <模板> <参数表> [--format csv\|json] [--out-dir 目录] [--engine text\|canon] [--target-profile P] [--no-verify] [--rules 规则集]` | 批量生成：参数表每行生成一份配置；生成后解析（未识别行为 0）、往返（逐字一致）并按模板校验（符合且提取出的变量与输入一致），失败的行给出原因；`--engine canon` 用规范渲染器输出，可配合 `--target-profile` 生成另一平台族的配置；`--out-dir` 只写成功的行（`<设备名>.cfg`）；**有失败的行时退出码 1**；`--rules` 只能与 `--engine canon` 一起用：生成的图按规则集改名后再渲染（改过名的行不按模板校验） |
| `lmesh template save <模板文件>` | 校验（含正文解析建图）后把模板写入运行时知识库的 `templates/<编号>.yaml` 并提交 |
| `lmesh ai test` / `lmesh ai calls [--user 账号]` | 测试当前生效的 AI 接口 / 最近的 AI 调用记录（发起人、接口、功能、模型、token 用量、成功与否） |
| `lmesh ai connections list` | 管理员 AI 接口（REQ-040）：名称、类型、模型、允许公共使用、启用、选用人数、本月 token；`*` 标出默认接口 |
| `lmesh ai connections add <名称> --provider P [--base-url U] [--api-key K \| --api-key-stdin] --model M [--model-extract/--model-merge/--model-ask/--model-generate M] [--public/--private] [--enabled/--disabled]` | 新建管理员 AI 接口（API Key 加密保存；建议用 `--api-key-stdin`，不进 shell 历史）；名称重复退出码 1，填写不完整退出码 2 |
| `lmesh ai connections set <名称\|编号> [--name N] [同上各项] [--clear-api-key]` / `remove <名称\|编号>` / `test <名称\|编号>` | 修改 / 删除（选用它的账号随后提示改选）/ 测试；不存在退出码 4，AI 出错退出码 5 |
| `lmesh ai use <personal\|接口名\|none\|auto>` | 选择 AI 来源（作用于 `--as` 账号，不给时第一个管理员）：个人 API、某个管理员接口（普通账号只能选允许公共使用的）、不使用、自动；不可选时退出码 2 |
| `lmesh ai status` | 当前账号的选择与生效来源（不可用时给出原因） |
| `lmesh ai personal show\|set\|remove\|test` | 个人 AI 接口（作用于 `--as` 账号）：`set` 的选项同 `connections add`，`--use` 同时改为使用它；只显示 Key 是否已设置 |
| `lmesh ai usage [--from D] [--to D] [--group day\|user\|connection\|feature\|model] [--user 账号] [--csv 文件]` | AI 用量统计：范围（UTC 日期，默认最近 30 天）内的调用次数、失败与 token，按分组列出；`--csv` 导出这一组 |
| `lmesh history list <设备>` | 版本历史时间线：每个快照的导入记录（内容相同的重复导入不存新快照，只记导入记录，显示 ×N）、行数、节点数、解析用的知识库版本、内容指纹、标签、相对上一快照的变化（+新增 ~修改 -删除）；保留最近 `history.keep` 个（默认 50），贴标签的永久保留 |
| `lmesh history diff <设备> [--from 快照] [--to 快照] [--rebuild] [--show-noneff] [--domain D] [--no-text] [--report 文件.html\|.md] [--report-lang zh-CN\|en]` | 两个快照之间的变化（默认上一个 → 最新）：按对象归并的图差异、只是写法不同的变化（默认只计数）、配置原文差异；默认用快照当时保存的图，`--rebuild` 两侧都按当前知识库重新解析。快照写法：数字是序号（同 `#3`），`v<编号>` 是配置版本编号，另有 `latest`、`prev`、`tag:<标签>` |
| `lmesh history object <设备> <对象规范编号> [--rebuild]` | 一个对象在每个快照中的取值与变化 |
| `lmesh history tag <设备> <快照> <标签>` / `--remove` | 给快照贴标签（永久保留）或去掉标签 |
| `lmesh history restore <设备> --to <快照> [--from 快照] [-o 脚本] [--rollback 文件] [--plain] [--report 文件]` | 回到某个快照：当前（默认最新）→ 目标快照的增量变更脚本，附回滚脚本与模拟验证（复用 `lmesh change`） |
| `lmesh device delete <设备> [--force] [--yes]` | 删除设备（REQ-038，设备写名称或编号）：连带删除全部配置版本（含快照）、图的节点与边、未识别行、导入记录、检查忽略项；在终端里先提示确认（列出将删除的版本、导入记录、忽略项个数），`--yes` 跳过（标准输入不是终端时不提示）；设备是配置检查项目的基线时拒绝并列出项目与脚本（退出码 1，`--output json` 的 `error.data` 为删除预览），`--force` 时删除并清空这些项目的基线（脚本与修订保留，结果中 `baseline_cleared`）；设备不存在退出码 4；删除记入日志（操作者、设备、版本个数），不记录配置内容 |
| `lmesh device delete-version <设备> <版本> [--force] [--yes]` | 删除设备的一个配置版本（版本写法同 `lmesh history`：数字是序号，`v<编号>` 是配置版本编号，另有 `latest`、`prev`、`tag:<标签>`）：连带删除该版本的快照、图、未识别行、导入记录；最后一个版本不能单独删除（退出码 1，请删除设备）；删除最新版本后上一个版本成为最新，跟随最新版本的检查项目随之改用它（`baseline_moved`）；删除较早的版本后，下一个版本相对上一快照的变化计数重算（`recomputed`）；版本被检查项目固定为基线时拒绝（退出码 1），`--force` 时这些项目改为跟随最新版本（`baseline_cleared`）；版本不存在退出码 4 |
| `lmesh device profiles <设备>` | 更换 Profile 的候选（REQ-044）：当前 Profile、来源与匹配程度、未识别比例；同厂商 / 同平台族的候选各试解析一次，按识别出的命令行比例排序（不用 AI），`*` 标出当前 |
| `lmesh device set-profile <设备> [<Profile>] [--auto] [--remember project\|global] [--match-name 模式] [--match-version 正则] [--match-feature 正则]` | 更换 Profile 并重新解析最新版本（之后的导入与重新解析沿用手工选择）；`--auto` 改回自动选择；`--remember` 同时记住为型号规则（命中这台设备时来源记为 rule）；跨厂商的 Profile 退出码 2 |
| `lmesh device request-support <设备> --model 型号 [--reason 说明]` | 申请支持此型号：附设备信息与未识别行的前 20 种写法，进审核队列（类型“建议”） |
| `lmesh model-rule list [--scope all\|project\|global]` | 型号规则（REQ-044），按生效顺序：本项目规则在前、全局在后；同一范围内条件多的优先，一样多时先建的优先 |
| `lmesh model-rule add --profile P [--match-name 模式] [--match-version 正则] [--match-feature 正则] [--vendor V] [--scope project\|global] [--note 说明] [--disabled]` / `update <编号> […] [--enable\|--disable]` / `remove <编号>` | 新建 / 修改 / 删除型号规则：至少一个条件，正则有效，只能指向同厂商的 Profile（否则退出码 2）；不存在退出码 4 |
| `lmesh model-rule test --profile P [--match-name 模式] [--match-version 正则] [--match-feature 正则]` | 试匹配（不保存）：本项目里会命中的设备，以及被更早的规则抢先的 |
| `lmesh model-support show <审核编号>` / `derive <审核编号> --id 新编号 --base 基础Profile [--title] [--platform] [--software] [--version-rule 正则]` / `retarget <审核编号> [--note]` | 处理型号支持申请（维护员）：查看状态与改指向预演 / 从现有 Profile 派生（继承，只写差异，写入草稿区）/ 匹配申请设备的型号规则改指向派生的 Profile（没有规则时新建全局规则），相关设备（所有项目，手工选择的不动）重新解析，申请标为通过 |
| `lmesh export presets [--style huawei\|cisco]` | 审计表格的预置模板（`knowledge/export/tables.yaml`）：IP 地址表、VLAN / 桥域表、BGP 邻居表、接口描述表、VPN 实例表、静态路由表 |
| `lmesh export table [文件\|目录\|设备名…] [--all] --preset P \| --object O [--fields 路径,…] [--where 筛选,…] [--filter '字段 运算符 取值']… [--no-defaults] [--canonical-names] [--format csv\|xlsx\|json] [--sheets per-device\|single] [--table-lang zh-CN\|en\|pt-BR] [--style] [-o 文件]` | 导出审计表格：每行一个对象、每格可追溯到图节点与配置行；CSV 为 UTF-8 带 BOM，另有“来源”列标出来自默认值的格子；XLSX 有“说明”工作表，默认值格子加批注；表头三语；敏感字段只写“已配置 / 未配置” |
| `lmesh feature [关键词] [--profile P]… [--family F] [--domain D] [--state supported\|unsupported\|unfilled] [--include-same] [--detail 节点]` | 特性能力查询（由知识库计算）：各 Profile 是否支持、默认值（↑ 表示继承）、命令写法、命令卡、来源；不带关键词浏览全部时各 Profile 完全相同的只计数 |
| `lmesh feature-diff <Profile A> <Profile B> [--domain D] [--include-same]` | 两个 Profile 对比：默认值不同的排在前面，其次只有一边支持、一边未填写；相同的默认只计数 |
| `lmesh query "<查询>" [文件\|目录\|设备名…]` | 执行图查询（受限的只读查询语言，不需要 AI）：`FIND <对象> [ON <设备>,…\|*] [WHERE <字段> <运算符> <取值> [AND …]] [RETURN <字段>,…] [WITH DEFAULTS] [LIMIT n]`；运算符 `=` `!=` `~`（正则）`!~` `>` `<` `>=` `<=` `IN (…)` `EXISTS` `NOT EXISTS`；不给目标时查全部已导入设备 |
| `lmesh ask "<问题>" [设备名…] [--show-sent]` | AI 自然语言查询（需要配置 AI，未配置时退出码 3）：AI 写图查询 → 代码校验并执行 → AI 只根据结果回答 → 代码逐句核对（通过 / 已按图更正 / 无法校验）；发给 AI 的内容先脱敏，`--show-sent` 打印实际发送的内容；AI 写不出合法查询时退出码 1 |
| `lmesh guard <配置片段> [--device 设备名\|当前配置文件] [--profile P] [--template T] [--no-cross-device] [--no-script]` | 配置护栏（不需要 AI）：片段合并到目标设备当前配置后解析、入图、依赖（悬空引用、互斥、前置、副作用顺序）、模板约束、冲突（地址、RD 跨设备查重，dot1q 重复）检查，逐行标出通过 / 拦截 / 注意；被拦截时退出码 1，通过时附增量变更脚本 |
| `lmesh generate "<需求>" --device <设备> [--profile P] [--template T] [--rounds 2] [-o 文件]` | AI 生成配置（需要配置 AI）：生成后经护栏检查，被拦截时把问题交回 AI 修改，最多 `--rounds` 轮；最终仍被拦截时退出码 1 |
| `lmesh ai suggest run <skill> [--device 设备] [--devices a,b] [--replay 文件]` | 运行 skill 生成 AI 建议（M8-2，作用于当前项目，同步执行）：代码校验后入库，列出每条的校验结果与原因；`--replay` 用文件里的回复代替真实 AI（仍经过代码校验）；未配置 AI 退出码 3，设备不存在退出码 4，回复无法解析（已重试一次）或 AI 出错退出码 5 |
| `lmesh ai suggest list [--skill S] [--status pending\|adopted\|dismissed\|reverted] [--check pass\|warn\|reject] [--category C] [--device D] [--batch N]` / `show <编号>` | 建议列表 / 详情：`✓` 通过、`!` 警告、`✕` 被拒绝，附代码校验原因；参数不合法退出码 2 |
| `lmesh ai suggest adopt <编号…> [--edit 文件]` / `adopt --category C [--skill S] [--batch N]` | 采纳（`--edit` 给出编辑后的内容 JSON，先重新校验）/ 按类别批量采纳校验通过的；被拒绝或编辑后不合格退出码 1，不存在退出码 4 |
| `lmesh ai suggest dismiss <编号…> [--note 说明]` / `revert <编号…>` / `annotations` | 忽略 / 撤销（30 天内）/ 项目的视图标注 |
| `lmesh skill list [--days N]` | 内置 AI skill（REQ-033）列表：编号、名称、启用、生效版本（builtin / vN）、近 N 天调用数、代码校验通过率、被拦截比例、评价、回归集条数；需要数据库（未配置退出码 3） |
| `lmesh skill show <skill> [--version builtin\|N]` | 显示 skill 的定义：任务与模型配置键、工具、代码校验、系统提示词、提示模板、示例数；不存在退出码 4 |
| `lmesh skill test <skill> [--sample N \| --case 编号] [--replay [--reply 文本]] [--version V]` | 试运行：渲染提示词 → 调用 AI → 代码校验，输出状态、得分与逐项结果；`--replay` 不调用 AI，用样例 / 案例记下的回复（或 `--reply`）走一遍校验；真实调用而未配置 AI 时退出码 3 |
| `lmesh skill versions <skill>` | 版本历史（`*` 为生效版本）：来源（内置 / 编辑 / 加入示例 / 进化批准）、作者、时间、说明 |
| `lmesh skill rollback <skill> <版本号\|builtin>` | 回滚到某个版本，`builtin` 恢复内置版本；版本不存在退出码 4 |
| `lmesh skill evolve <skill> [--limit N]` | 发起进化：AI 根据回归集提出候选版本，回归集上新旧版本对比打分，结果待批准（不自动上线）；未配置 AI 退出码 3，回归集为空退出码 1，候选没有通过代码检查退出码 1 |
| `lmesh skill approve <skill> <进化编号> [--reject] [--note 说明]` | 批准进化的候选版本并发布为新版本（`--reject` 放弃）；不存在退出码 4，已处理过退出码 1 |
| `lmesh script-check <脚本> [--device 设备名[@版本]\|配置文件] [--version N] [--kind change\|full] [--order/--no-order] [--reorder [-o 文件]] [--rules 目录] [--profile P]` | 检查变更脚本 / 完整配置（REQ-031）：变更脚本逐行跟踪视图、在基线上模拟执行（取消匹配、覆盖、副作用），执行后的配置跑配置检查规则并查地址 / RD 冲突；顺序核查开启时报出“引用了后面才创建的对象”“删除时引用方在后面才处理”“先配的值被后面命令的副作用删除”，并附按依赖重排的建议；`--no-order` 只看按依赖顺序执行后的结果；完整配置检查未识别行、规则并与基线按有效值对比；`--reorder` 输出重排后的脚本与每条命令移动的原因；有 error 时退出码 1，变更脚本没有基线退出码 2 |
| `lmesh script-diff <a> <b> [--ignore-order] [--kind full\|change] [--device 基线] [--format text\|unified\|html] [--report-lang zh-CN\|en] [--no-semantic] [-o 文件]` | 脚本 / 配置的文本差异：逐行对比、行内字符级标记，位置变化识别为移动（第几行 → 第几行），`--ignore-order` 按视图路径 + 内容只看内容差异；同时给出语义差异（按有效值比较；`--kind change` 时比较两份脚本在基线上执行后的结果）；可输出统一 diff 或中 / 英 HTML 报告 |
| `lmesh project list [--all] [--owner 账号]` | 项目列表（M6）：我的项目与共享给我的（`--as` 账号的视角，`*` 为默认项目；第一列是规范引用：自己的项目写标识，别人的写 `属主/标识`）；`--all` 同时列出不是自己参与的项目（管理员） |
| `lmesh project show [项目]` | 项目详情：属主、我的角色、成员、设备（私有 / 引用）与脚本计数；不给项目时为当前项目 |
| `lmesh project create <名称> [--slug 标识] [--description 说明]` | 新建项目，属主为 `--as` 账号；标识在属主自己的项目里唯一（别人可以有同名项目）；标识不合法退出码 2，自己已有同名项目退出码 1；没有创建权限（M9-8：配置 `auth.user_create_projects` 关闭且没有单独授权）退出码 1 |
| `lmesh project delete <项目>` | 删除项目：私有设备与它们的全部版本一起删除，引用的公共设备只解除引用；终端里要输入项目标识确认，`--yes` 跳过 |
| `lmesh project members <项目> [--add 账号 --role manage\|edit\|read] [--remove 账号]` | 成员列表；添加或改角色、移除（属主、“管理”成员与管理员，否则退出码 1） |
| `lmesh project transfer <项目> <新属主> [--keep-as manage\|edit\|read\|none] [--slug 新标识]` | 转交项目（只限属主与管理员，“管理”成员退出码 1）；原属主默认留作可编辑成员；项目用到的原属主私有规则集复制一份给新属主；新属主已有同名标识时退出码 1（`error.data.suggested` 给出可用的标识），用 `--slug` 同时改名 |
| `lmesh project copy <项目> <新名称> [--slug 标识] [--no-devices] [--no-scripts]` | 复制为新项目（属主为 `--as` 账号）：设置、规则调整、私有设备（当前版本）、引用、脚本 |
| `lmesh project default <项目>` | 设置 `--as` 账号的默认项目 |
| `lmesh project can-create` / `request-create [--reason]` | `--as` 账号能否新建项目（原因：管理员 / 总开关 / 单独授权）与创建权限申请的状态 / 向管理员申请创建权限（M9-8）；已经能创建或已有待处理的申请退出码 1 |
| `lmesh project discover [搜索词]` | 可被搜索的项目：编号、`属主/标识`、名称、属主、设备数、我的状态（只有这些，不显示设备名、配置与成员） |
| `lmesh project join <编号或属主/标识> [--role read\|edit] [--reason 理由]` | 申请加入可被搜索的项目；不可被搜索或不存在退出码 4，已是成员或已有待审批的申请退出码 1 |
| `lmesh project my-requests` / `cancel-request <编号>` | 我提交的加入申请 / 撤回待审批的申请 |
| `lmesh project requests <项目> [--all]` / `approve <项目> <编号> [--role manage\|edit\|read]` / `decline <项目> <编号> [--note 说明]` | 项目的加入申请（属主、“管理”成员、管理员，否则退出码 1）/ 通过（可改角色）/ 拒绝 |
| `lmesh project discoverable <项目> on\|off` | 设置项目是否可被搜索（属主、“管理”成员、管理员） |
| `lmesh project invite <项目> [--role read] [--days 7] [--approval] [--note 备注]` / `invites <项目>` / `revoke-invite <项目> <编号>` | 新建邀请链接（令牌只显示这一次，服务器只存它的 SHA-256；`--approval` 打开后仍需审批；有效 1–90 天）/ 列表 / 撤销 |
| `lmesh project accept-invite <令牌或链接> [--reason 留言]` | 用邀请链接加入：直接成为成员，或（链接要求审批时）提交加入申请；链接无效退出码 4，已过期或已撤销退出码 1 |
| `lmesh project ref <公共设备> [--pin 版本编号] [--remove]` | 在当前项目（`--project`）引用公共设备（跟随最新，或 `--pin` 固定版本），`--remove` 解除引用 |
| `lmesh token create <用途> [--read-only] [--days 90]` | 为 `--as` 账号生成个人令牌（`lmp_` 开头，只显示这一次）；`--days 0` 不过期；还没有账号时退出码 1 |
| `lmesh token list` | `--as` 账号的个人令牌：前 8 个字符、权限、过期时间、最后使用、状态 |
| `lmesh token revoke <编号>` | 撤销令牌；不存在退出码 4 |
| `lmesh network list` | 本项目的网络（M9）与汇总：设备数、共用设备、脚本、错误 / 警告；`*` 为默认网络 |
| `lmesh network show <网络>` / `update <网络> [--name] [--slug] [--color]` | 网络详情 / 改名、标识、识别色（8 色之一，否则退出码 2） |
| `lmesh network create <名称> [--slug] [--color] [--devices 1,2] [--name-rule 模式]… [--subnet-rule CIDR]…` | 新建网络；规则同时加入现在命中的设备 |
| `lmesh network delete <网络> --confirm <名称>` / `--preview` | 删除网络与它的工作数据（不删设备）；默认网络退出码 1；`--preview` 只列出会删除的内容 |
| `lmesh network copy <网络> --name <名称> [--slug]` | 复制网络（连同工作数据，已采纳的 AI 结果注明复制自） |
| `lmesh network members <网络>` / `add <网络> <设备编号,…> [--pin]` / `remove <网络> <设备编号,…>` | 成员与本网络用的版本 / 从项目设备池加入 / 移出（记为排除；默认网络退出码 1） |
| `lmesh network pin <网络> <设备编号,…> [--version 编号]` / `follow <网络> <设备编号,…>` | 在本网络固定版本（不给版本时固定在当前最新）/ 改为跟随最新 |
| `lmesh network rules <网络>` / `rule-add <网络> name\|subnet <模式> [--apply]` / `rule-preview …` / `rule-delete <网络> <编号>` | 自动加入规则：列表 / 添加（`--apply` 同时加入现在命中的设备）/ 命中预览 / 删除 |
| `lmesh network folder-add <名称>` / `folder-delete <编号>` | 文件夹（只整理列表；删除时网络移到最外层） |
| `lmesh network suggest components\|igp\|bgp\|name\|subnet\|ai [--regex] [--prefix 24] [--protocol all\|isis\|ospf] [--all-links]` | 建网建议（代码计算，预览）；依据不合格退出码 2 |
| `lmesh network adopt <依据> [--key K]… [--with-rules] [同上参数]` | 采纳建网建议（不给 `--key` 时采纳全部可采纳的）；`--with-rules` 把设备名 / 管理网段规则设为新网络的自动加入规则 |
| `lmesh user grant-create <账号> [--revoke]` | 单独授权账号创建项目（M9-8）/ 收回 |
| `lmesh user create-requests [--all]` / `approve-create <编号>` / `decline-create <编号> [--note 说明]` | 创建权限的申请 / 通过（即单独授权）/ 拒绝 |
| `lmesh public-device list` | 公共设备库：版本数、引用它的项目（跟随 / 固定） |
| `lmesh public-device import <文件、目录或 zip> [--level basic\|strict]` | 导入到公共设备库（同名设备作为新版本） |
| `lmesh public-device delete <设备> [--force]` | 删除公共设备；还有项目引用时退出码 1（`--force` 一并解除引用） |

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

### 查看一个配置项：值、来源、是否需重启、能否修改（REQ-049）

```bash
lmesh --output json config get server.port
```

退出码：`0`

JSON 输出中的关键字段：

- `data.key` = `"server.port"`
- `data.source` = `"file"`
- `data.restart` = `true`

### 修改配置项并写入配置文件（与网页“系统设置”同一套校验；需要重启的项会列出）

```bash
lmesh --output json config set history.keep=80 log.level=DEBUG
```

退出码：`0`

JSON 输出中的关键字段：

- `data.changed.0` = `"history.keep"`
- `data.changed.1` = `"log.level"`
- `data.restart_required.0` = `"log.level"`

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
- `data.counts.profiles` = `5`

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
- `data.counts.command` = `1745`

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
- `data.samples` = `26`

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

### 管理员 AI 接口列表

```bash
lmesh --output json ai connections list
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.connections.0.name` = `"shared"`
- `data.connections.0.public` = `true`
- `data.connections.0.is_default` = `true`
- `data.connections.1.name` = `"internal"`
- `data.connections.1.public` = `false`

### 新建允许公共使用的接口，API Key 从标准输入读取

```bash
lmesh --output json ai connections add lab --provider local --base-url http://127.0.0.1:11434/v1 --model qwen2.5 --api-key-stdin --public
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.name` = `"lab"`
- `data.public` = `true`
- `data.api_key_set` = `true`

### 关闭公共使用

```bash
lmesh --output json ai connections set shared --private
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.name` = `"shared"`
- `data.public` = `false`

### 账号 bob 改用公共接口 shared

```bash
lmesh --output json --as bob ai use shared
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.choice` = `"connection"`
- `data.effective.configured` = `true`
- `data.effective.connection.name` = `"shared"`

### 设置个人接口并改为使用它

```bash
lmesh --output json --as bob ai personal set --provider openai --base-url http://127.0.0.1:9/v1 --model bob-model --use
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.choice` = `"personal"`
- `data.personal.model` = `"bob-model"`
- `data.effective.source` = `"personal"`

### AI 用量统计（按接口）

```bash
lmesh --output json ai usage --group connection
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.totals.calls` = `0`

### 问题解读与修复（检查问题，回放回复）：编造的问题被拒绝

```bash
lmesh --output json --project alice/lab ai suggest run finding-fix --device ATN-CHANGE-01 --params '{"source": "check"}' --replay tests/inputs/ai-suggest/finding-explain.json
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.batch.status` = `"done"`
- `data.batch.counts.pass` = `1`
- `data.batch.counts.reject` = `1`
- `data.batch.params.source` = `"check"`

### 手工标注设备角色（优先于 AI 建议）

```bash
lmesh --output json --project alice/lab ai suggest annotate ATN-CHANGE-01 --key role --value access
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.item.key` = `"role"`
- `data.item.value` = `"access"`
- `data.item.source` = `"user"`

### 导出设备交接文档（含已采纳的 AI 设备摘要）

```bash
lmesh --lang en --project alice/lab ai suggest handover ATN-CHANGE-01 --doc-lang en --format md
```

退出码：`0`

输出包含：`# Device handover note · ATN-CHANGE-01`、`Device summary`

### 变更意图转脚本（回放）：改动应用到目标图，代码生成脚本并模拟执行

```bash
lmesh --output json --project alice/lab ai suggest run intent-script --device ATN-CHANGE-01 --params '{"intent": "Set the description of GigabitEthernet0/2/2"}' --replay tests/inputs/ai-change/intent-desc.json
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.batch.status` = `"done"`
- `data.items.0.category` = `"graph_edit"`
- `data.items.0.check_status` = `"pass"`
- `data.items.0.check.result.summary.verify` = `true`

### 割接方案文档（回放）：中英双语的一节通过，直接写出命令的一节被拒绝

```bash
lmesh --output json --project alice/lab ai suggest run cutover-plan --device ATN-CHANGE-01 --params '{"to": "cisco-iosxe-asr920-17.15"}' --replay tests/inputs/ai-change/cutover-overview.json
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.batch.counts.pass` = `1`
- `data.batch.counts.reject` = `1`

### 翻译未支持项（回放）：用目标平台的命令卡解析验证

```bash
lmesh --output json --project alice/lab ai suggest run translate-gap --device ATN-CHANGE-01 --params '{"to": "cisco-iosxe-asr920-17.15"}' --replay tests/inputs/ai-change/translate-gap.json
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.batch.counts.pass` = `1`
- `data.batch.counts.warn` = `1`

### 命名映射建议（回放）：代码列出映射表，冲突的规则被拒绝

```bash
lmesh --output json --project alice/lab ai suggest run naming-map --device ATN-CHANGE-01 --params '{"to": "cisco-iosxe-asr920-17.15"}' --replay tests/inputs/ai-change/naming-vrf.json
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.batch.counts.pass` = `1`
- `data.batch.counts.reject` = `1`

### 模板提取（回放）：用设备自己的取值渲染须与原配置等价

```bash
lmesh --output json --project alice/lab ai suggest run template-extract --devices ATN-CHANGE-01 --replay tests/inputs/ai-change/template-loopback.json
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.batch.counts.pass` = `1`
- `data.batch.counts.reject` = `1`

### 规范转规则：读入规范文件（--doc），规则草稿过规则引擎并在样本上试跑

```bash
lmesh --output json --project alice/lab ai suggest run rule-draft --doc tests/inputs/ai-kb/std.md --replay tests/inputs/ai-kb/rule-draft.json
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.batch.status` = `"done"`
- `data.batch.scope_key` = `"rules:standard"`
- `data.batch.counts.pass` = `1`
- `data.batch.counts.reject` = `1`
- `data.items.0.check.reasons.0.code` = `"rule_invalid"`
- `data.items.1.check_status` = `"pass"`
- `data.items.1.refs.0.label` = `"4.2.1"`

### 脱敏复核：标出的文字在该行，补规则重新脱敏后消失

```bash
lmesh --output json --project alice/lab ai suggest run sanitize-review --device ATN-CHANGE-01 --replay tests/inputs/ai-kb/sanitize.json
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.items.0.category` = `"sanitize_rule"`
- `data.items.0.check_status` = `"pass"`
- `data.items.0.check.result.pattern` = `"RAN\\-SITE"`

### 报告摘要：中英文两段，数字由代码填入

```bash
lmesh --output json --project alice/lab ai suggest run report-summary --device ATN-CHANGE-01 --params '{"kind": "check"}' --replay tests/inputs/ai-kb/report-summary.json
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.batch.counts.pass` = `2`
- `data.items.0.kind` = `"en"`

### 运行设备摘要（回放回复，代码校验后入库）

```bash
lmesh --output json --project alice/lab ai suggest run device-summary --device ATN-CHANGE-01 --replay tests/inputs/ai-suggest/summary.json
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.batch.status` = `"done"`
- `data.batch.mode` = `"replay"`
- `data.batch.counts.pass` = `1`
- `data.items.0.category` = `"text_only"`
- `data.items.0.check_status` = `"pass"`
- `data.items.0.refs.0.found` = `true`

### 建议列表（按 skill 过滤）

```bash
lmesh --output json --project alice/lab ai suggest list --skill topology-roles
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.total` = `3`
- `data.items.0.id` = `3`
- `data.items.0.check_status` = `"reject"`
- `data.items.2.content.value` = `"access"`

### 采纳一条建议

```bash
lmesh --output json --project alice/lab ai suggest adopt 1
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.items.0.status` = `"adopted"`
- `data.items.0.adopt_info.action` = `"annotate"`
- `data.items.0.adopt_info.value` = `"access"`

### 编辑后采纳（重新校验）

```bash
lmesh --output json --project alice/lab ai suggest adopt 2 --edit tests/inputs/ai-suggest/role-edit.json
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.items.0.status` = `"adopted"`
- `data.items.0.edited` = `true`
- `data.items.0.adopt_info.value` = `"aggregation"`
- `data.items.0.original.content.value` = `"pe"`

### 按类别批量采纳（只采纳校验通过的）

```bash
lmesh --output json --project alice/lab ai suggest adopt --category view_hint
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.adopted` = `[1, 2]`
- `data.skipped.0.id` = `3`

### 忽略建议

```bash
lmesh --output json --project alice/lab ai suggest dismiss 4 --note outdated
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.items.0.status` = `"dismissed"`
- `data.items.0.note` = `"outdated"`

### 项目的视图标注（还没有采纳时为空）

```bash
lmesh --output json --project alice/lab ai suggest annotations
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.items` = `[]`

### 分析现网 ATN 配置：摘要与 TCP/IP 分层

```bash
lmesh --output json analyze knowledge/samples/huawei-atn-v800r023/atn-access-01.cfg
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.parts` = `["summary", "layers"]`
- `data.summary.lines.total` = `2267`
- `data.summary.lines.raw` = `180`
- `data.summary.lines.unknown` = `0`
- `data.summary.domains.0.domain` = `"qos"`
- `data.summary.check.summary.by_severity.warning` = `65`
- `data.summary.baseline.score` = `95`
- `data.summary.defaults.total` = `229`
- `data.layers.layers.0.id` = `"physical"`
- `data.layers.layers.2.id` = `"mpls"`
- `data.layers.unclassified` = `[]`

### 结构化脚本：关键字、参数与引用的字符区间

```bash
lmesh --output json analyze tests/inputs/configs/huawei/analysis-small.cfg --part script
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.parts` = `["script"]`
- `data.script.refs` = `{"vrf.instance[RAN]": [9]}`
- `data.script.defs` = `{"vrf.instance[RAN]": 3}`
- `data.script.lines.8.spans.3.t` = `"ref"`
- `data.script.lines.8.spans.3.ref` = `["vrf.instance[RAN]"]`
- `data.script.lines.3.depth` = `1`
- `data.script.lines.11.layer` = `"datalink"`

### 图查询（不需要 AI）：绑定了 VPN 实例的接口及其地址与 MTU（含默认值）

```bash
lmesh --output json query 'FIND interface WHERE vrf EXISTS RETURN name, vrf, ipv4.address, mtu WITH DEFAULTS' knowledge/samples/change/atn-base.cfg
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.count` = `1`
- `data.object` = `"interface"`
- `data.rows.0.node` = `"interface[GigabitEthernet0/2/1.101]"`
- `data.rows.0.cells.vrf.value` = `"RAN"`
- `data.rows.0.cells.vrf.lines` = `[36]`
- `data.rows.0.cells.mtu.value` = `1500`
- `data.rows.0.cells.mtu.origin` = `"default"`

### 查询写法不对

```bash
lmesh query 'SELECT * FROM interface' knowledge/samples/change/atn-base.cfg
```

退出码：`2`

### 未配置 AI：自然语言查询返回“未配置”（核心功能照常）

```bash
lmesh --output json ask '哪些接口绑定了 VPN 实例？'
```

退出码：`3`

JSON 输出中的关键字段：

- `ok` = `false`
- `error.code` = `3`
- `error.data.status` = `"not_configured"`

### 配置护栏（不需要 AI）：合并到当前配置后检查，标出被拦截的行与原因

```bash
lmesh --output json guard tests/inputs/guard/atn-bad.cfg --device knowledge/samples/change/atn-base.cfg
```

退出码：`1`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.verdict` = `"blocked"`
- `data.summary.bad` = `4`
- `data.stages.parse.status` = `"bad"`
- `data.stages.deps.status` = `"bad"`
- `data.stages.conflict.status` = `"bad"`
- `data.stages.template.status` = `"skipped"`
- `data.lines.0.status` = `"skip"`
- `data.lines.4.status` = `"bad"`

错误提示（stderr）包含：`被拦截`

### 配置护栏：目标是已导入设备，通过后附增量变更脚本

```bash
lmesh --output json guard tests/inputs/guard/atn-good.cfg --device ATN-CHANGE-01
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.verdict` = `"passed"`
- `data.device` = `"ATN-CHANGE-01"`
- `data.issues.0.rule` = `"side_effect_ok"`
- `data.script.available` = `true`
- `data.script.verify_ok` = `true`

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

输出包含：`Baseline strict: 2 device(s), 34 rule(s), score 86`、`sec.snmp_v3_only               ✗              ✗`、`pe-asr920-02-igp-mgmt (cisco-iosxe) score 91`、`Reference commands: line con 0 | exec-timeout 10 0`

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

### 删除设备（连带配置版本、导入记录等）

```bash
lmesh --output json device delete ATN-CHANGE-01 --yes
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.deleted` = `true`
- `data.device.name` = `"ATN-CHANGE-01"`
- `data.counts.versions` = `2`
- `data.counts.imports` = `3`
- `data.counts.check_ignores` = `0`
- `data.baseline_cleared` = `[]`

### --force：删除并清空检查项目的基线

```bash
lmesh --output json device delete ATN-CHANGE-01 --force --yes
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.deleted` = `true`
- `data.baseline_cleared.0.id` = `1`
- `data.baseline_cleared.0.scripts.1.name` = `"完整配置"`

### 删除最新版本（序号 2）：最新版本回到上一个

```bash
lmesh --output json device delete-version ATN-CHANGE-01 2 --yes
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.version.id` = `2`
- `data.version.seq` = `2`
- `data.version.latest` = `true`
- `data.latest_version_id` = `1`
- `data.versions_left` = `1`
- `data.counts.imports` = `1`

### 列出预置模板

```bash
lmesh --output json export presets
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.presets.0.id` = `"ip-address"`
- `data.presets.0.object` = `"interface"`
- `data.presets.0.title.pt-BR` = `"Tabela de endereços IP"`
- `data.presets.2.id` = `"bgp-peer"`

### IP 地址表：一个目录中的配置，导出 CSV（UTF-8 BOM，英文表头）

```bash
lmesh --output json export table knowledge/samples/topology --preset ip --format csv --table-lang en -o out/ip.csv
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.format` = `"csv"`
- `data.preset` = `"ip-address"`
- `data.object` = `"interface"`
- `data.summary.devices` = `5`
- `data.summary.columns` = `7`
- `data.columns.3.key` = `"derive:mask"`

### BGP 邻居表（JSON）：每格带来源、节点与行号；认证密码只给出是否配置

```bash
lmesh --output json export table knowledge/samples/topology/rr-01.cfg --preset bgp --format json
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.summary.secret_columns` = `1`
- `data.columns.9.key` = `"password"`
- `data.columns.9.secret` = `true`
- `data.rows.0.cells.9.secret` = `true`
- `data.rows.0.cells.2.value` = `"iBGP"`

### CSV 没有给输出文件

```bash
lmesh export table knowledge/samples/change/atn-base.cfg --preset ip --format csv
```

退出码：`2`

### 按关键词查特性：各 Profile 的支持情况、默认值与命令写法

```bash
lmesh --output json feature mtu --profile huawei-atn-v800r025 --profile cisco-iosxe-asr920-17.15
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.items.0.node` = `"interface.mtu"`
- `data.items.0.profiles.huawei-atn-v800r025.state` = `"supported"`
- `data.items.0.profiles.huawei-atn-v800r025.default` = `1500`
- `data.profiles.1.family` = `"cisco-iosxe"`

### 两个 Profile 对比：默认值不同的排在前面

```bash
lmesh --output json feature-diff huawei-atn-v800r025 cisco-iosxe-asr920-17.15 --domain vrf
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.rows.0.kind` = `"default"`
- `data.rows.0.node` = `"vrf.instance.af.label_mode"`
- `data.rows.0.a.default` = `"per-instance"`
- `data.rows.0.b.default` = `"per-route"`

### Profile 不存在

```bash
lmesh feature mtu --profile nope
```

退出码：`4`

### 快照时间线：重复导入只记导入记录，相对上一快照的变化计数

```bash
lmesh --output json history list ATN-CHANGE-01
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.device.name` = `"ATN-CHANGE-01"`
- `data.count` = `2`
- `data.imports` = `3`
- `data.keep` = `50`
- `data.snapshots.0.seq` = `1`
- `data.snapshots.0.import_count` = `2`
- `data.snapshots.0.imports.1.duplicate` = `true`
- `data.snapshots.0.imports.0.actor` = `"tester"`
- `data.snapshots.1.vs_previous.modified` = `1`
- `data.snapshots.1.latest` = `true`
- `data.snapshots.1.graph_stored` = `true`

### 两个快照的差异：按对象归并（接口描述与 MTU 的修改）

```bash
lmesh --output json history diff ATN-CHANGE-01 --from 1 --to 2 --no-text
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.a.seq` = `1`
- `data.b.seq` = `2`
- `data.equal` = `false`
- `data.summary.modified` = `1`
- `data.summary.added` = `0`
- `data.summary.noneff` = `0`
- `data.items.0.object` = `"interface[GigabitEthernet0/2/0]"`
- `data.items.0.kind` = `"modified"`
- `data.items.0.changes.0.field` = `"description"`
- `data.items.0.changes.0.b.value` = `"UPLINK-TO-AGG-01"`
- `data.kb.differs` = `false`

### 对象历史：接口在每个快照中的取值

```bash
lmesh --output json history object ATN-CHANGE-01 'interface[GigabitEthernet0/2/0]'
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.schema` = `"interface"`
- `data.changes` = `1`
- `data.snapshots.1.changed` = `["description", "mtu"]`
- `data.snapshots.1.values.mtu.value` = `9216`
- `data.snapshots.0.values.mtu.value` = `9000`

### 给第一个快照贴标签（永久保留）

```bash
lmesh --output json history tag ATN-CHANGE-01 1 '割接前基线'
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.tag` = `"割接前基线"`
- `data.id` = `1`

### 回到第一个快照：生成增量变更脚本（不带说明行）

```bash
lmesh --lang en history restore ATN-CHANGE-01 --to 1 --plain
```

退出码：`0`

输出包含：`system-view`、`interface GigabitEthernet0/2/0`、` description UPLINK-TO-AGG`、` mtu 9000`、`commit`、`From snapshot #2 back to #1: 2 command(s)`

### 设备不存在

```bash
lmesh history list NOPE
```

退出码：`4`

### 能否新建项目

```bash
lmesh --output json --as dave project can-create
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.can_create` = `false`
- `data.request.status` = `"pending"`

### 申请创建项目的权限

```bash
lmesh --output json --as carol project request-create --reason '负责 IP RAN 扩容'
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.status` = `"pending"`
- `data.username` = `"carol"`

### 通过创建权限的申请

```bash
lmesh --output json user approve-create 1
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.status` = `"approved"`
- `data.username` = `"dave"`

### 单独授权账号创建项目

```bash
lmesh --output json user grant-create carol
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.username` = `"carol"`
- `data.can_create_projects` = `true`

### 申请加入可被搜索的项目

```bash
lmesh --output json --as dave project join alice/lab --role edit --reason '负责割接脚本'
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.status` = `"pending"`
- `data.role` = `"edit"`

### 通过加入申请并改角色

```bash
lmesh --output json --as erin project approve alice/lab 1 --role edit
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.status` = `"approved"`
- `data.decided_role` = `"edit"`

### 新建邀请链接（令牌只显示这一次）

```bash
lmesh --output json --as alice project invite lab --role read --days 3 --approval
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.role` = `"read"`
- `data.requires_approval` = `true`
- `data.state` = `"active"`

### 用邀请链接加入（可以贴整个链接）

```bash
lmesh --output json --as dave project accept-invite http://127.0.0.1:9090/invite/lmi_test-invite-token-0001
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.status` = `"joined"`
- `data.project` = `"alice/lab"`

### 预览升级时知识库的合并（自带知识库没变时无需合并）

```bash
lmesh --output json kb upgrade --dry-run
```

退出码：`0`

JSON 输出中的关键字段：

- `data.changed` = `false`
- `data.has_base` = `true`

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

### 导入时手工指定 Profile 并记住为本项目的型号规则

```bash
lmesh --output json config import tests/inputs/configs/ne8000/ne8000-x8-02.cfg --profile huawei-atn-v800r023 --remember project
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.files.0.device` = `"NE8000-X8-02"`
- `data.files.0.profile` = `"huawei-atn-v800r023"`
- `data.files.0.profile_source` = `"rule"`
- `data.files.0.match_level` = `"approx"`
- `data.files.0.rule_created` = `1`
- `data.files.0.rule_id` = `1`

### 认不出厂商的配置只存原文（--keep-unsupported）

```bash
lmesh --output json config import tests/inputs/configs/other/edge-mx-01.conf --keep-unsupported
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.files.0.device` = `"edge-mx-01"`
- `data.files.0.vendor` = `""`
- `data.files.0.raw_only` = `true`
- `data.files.0.profile_source` = `"none"`
- `data.files.0.match_level` = `"none"`

### 候选 Profile 与试解析结果（近似：厂商默认）

```bash
lmesh --output json device profiles NE8000-X8-01
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.profile` = `"huawei-atn-v800r025"`
- `data.profile_source` = `"fallback"`
- `data.match_level` = `"approx"`
- `data.approx` = `true`
- `data.recommended` = `"huawei-atn-v800r025"`
- `data.candidates.0.profile` = `"huawei-atn-v800r025"`
- `data.candidates.0.unknown` = `2`
- `data.candidates.1.profile` = `"huawei-atn-v800r023"`
- `data.suggested_rule.name_pattern` = `"NE8000-X8-*"`
- `data.suggested_rule.version` = `"V800R022"`

### 更换 Profile 并重新解析（手工选择）

```bash
lmesh --output json device set-profile NE8000-X8-01 huawei-atn-v800r023
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.profile` = `"huawei-atn-v800r023"`
- `data.profile_source` = `"manual"`
- `data.approx` = `true`
- `data.result.parsed` = `true`
- `data.result.unknown` = `2`

### 只允许同厂商 / 同平台族：选 Cisco 的 Profile 被拒绝，退出码 2

```bash
lmesh device set-profile NE8000-X8-01 cisco-iosxe-asr920-17.15
```

退出码：`2`

错误提示（stderr）包含：`cisco-iosxe-asr920-17.15`、`同厂商`

### 申请支持此型号（进审核队列，类型“建议”）

```bash
lmesh --output json device request-support NE8000-X8-01 --model 'NE8000 X8' --reason '城域汇聚'
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.status` = `"pending"`

### 新建全局型号规则

```bash
lmesh --output json model-rule add --profile huawei-atn-v800r023 --match-name 'NE8000-*' --match-version V800R022 --scope global --note 'NE8000 暂用 ATN R023'
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.id` = `1`
- `data.scope` = `"global"`
- `data.vendor` = `"huawei"`
- `data.conditions` = `3`
- `data.profile` = `"huawei-atn-v800r023"`

### 试匹配型号规则（不保存）

```bash
lmesh --output json model-rule test --profile huawei-atn-v800r023 --match-version V800R022
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.count` = `1`
- `data.devices.0.name` = `"NE8000-X8-01"`
- `data.devices.0.source` = `"fallback"`

### 规则集列表（内置示例）

```bash
lmesh --output json naming list
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.0.id` = `"asr920-to-atn"`
- `data.0.builtin` = `true`
- `data.1.id` = `"atn-to-asr920"`

### 试运行：改名清单、同步改的引用与端口映射

```bash
lmesh --output json naming test tests/inputs/naming/l3vpn-rules.yaml knowledge/samples/translate/atn-l3vpn-synth.cfg --to cisco-iosxe-asr920-17.15
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.summary.renamed` = `3`
- `data.summary.ports` = `2`
- `data.summary.conflicts` = `0`
- `data.renames.0.type` = `"rp.policy"`
- `data.renames.0.from` = `"EXPORT-LOOPBACK"`
- `data.renames.0.to` = `"RP_EXPORT_LOOPBACK"`
- `data.renames.0.rule.index` = `1`
- `data.renames.0.refs` = `1`
- `data.ports.1.from` = `"GigabitEthernet0/2/1"`
- `data.ports.1.to` = `"GigabitEthernet0/0/2"`
- `data.ports.1.subinterfaces` = `1`

### 多个源名映射到同一个新名：报冲突、不改名，退出码 1

```bash
lmesh --output json naming test tests/inputs/naming/conflict-rules.yaml knowledge/samples/translate/atn-l3vpn-synth.cfg
```

退出码：`1`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.conflicts.0.kind` = `"many_to_one"`
- `data.conflicts.0.to` = `"SAME"`
- `data.conflicts.0.from` = `["OAM", "RAN"]`
- `data.summary.renamed` = `0`

### 测试一个名称：命中的规则与整理结果

```bash
lmesh --output json naming match tests/inputs/naming/l3vpn-rules.yaml BGP-IN --type rp.policy
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.result` = `"RP_BGP_IN"`
- `data.rule` = `1`
- `data.problems` = `[]`

### 导入规则集到 data/translate-rules/

```bash
lmesh --output json naming import tests/inputs/naming/l3vpn-rules.yaml
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.id` = `"l3vpn-rules"`
- `data.builtin` = `false`
- `data.counts.names` = `2`

### 翻译时按规则集改名（对象与引用一起改，端口按规则映射）

```bash
lmesh --output json translate knowledge/samples/translate/atn-l3vpn-synth.cfg --to cisco-iosxe-asr920-17.15 --interface-map tests/inputs/naming/loopback.yaml --rules tests/inputs/naming/l3vpn-rules.yaml
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.verify.unexplained` = `0`
- `data.naming.summary.renamed` = `3`
- `data.naming.renames.2.to` = `"VRF_RAN"`
- `data.interface_map.GigabitEthernet0/2/1` = `"GigabitEthernet0/0/2"`

### 网络列表：默认网络包含全部设备

```bash
lmesh --output json --project alice/lab network list
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.networks.0.slug` = `"default"`
- `data.networks.0.default` = `true`
- `data.networks.0.counts.devices` = `2`
- `data.overview.devices` = `2`

### 新建网络并按设备名规则加入现有设备

```bash
lmesh --output json --project alice/lab network create '接入' --slug access --name-rule 'ATN-*'
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.slug` = `"access"`
- `data.counts.devices` = `1`
- `data.rules.0.pattern` = `"ATN-*"`
- `data.color` = `"indigo"`

### 全局 --network：命令作用于该网络（默认网络有全部设备）

```bash
lmesh --output json --project alice/lab --network default config list
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.devices.0.name` = `"ATN-CHANGE-01"`
- `data.devices.1.name` = `"PE-CHANGE-01"`

### 建网建议：按设备名规则

```bash
lmesh --output json --project alice/lab network suggest name
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.total` = `2`
- `data.suggestions.0.key` = `"name:ATN-CHANGE"`
- `data.suggestions.0.rule.pattern` = `"ATN-CHANGE-*"`

### Nokia 规范模式渲染（exit all / configure 开头，echo 段落，每块 exit，名称加引号）

```bash
lmesh --output json render knowledge/samples/nokia-sros-classic-synthetic/classic-pe-basic.cfg --canonical
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.mode` = `"canonical"`
- `data.profile` = `"nokia-sros-classic-7750-25.10"`
- `data.family` = `"nokia-sros-classic"`
- `data.uncovered` = `[]`
- `data.lines.0.text` = `"exit all"`
- `data.lines.1.text` = `"configure"`

### Nokia 配置翻译到华为（路由器接口并到端口，基本实例 0 → 进程 1）

```bash
lmesh --output json translate knowledge/samples/nokia-sros-classic-synthetic/classic-pe-basic.cfg --to huawei-atn-v800r025 --interface-map knowledge/samples/translate/nokia-to-atn.ifmap.yaml
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.source.profile` = `"nokia-sros-classic-7750-25.10"`
- `data.target.family` = `"huawei-vrp8"`
- `data.verify.checked` = `true`
- `data.verify.unexplained` = `0`

### 只为一个平台族套用映射规则并汇总 Profile（不重写其他平台族的命令卡与 Profile）

```bash
lmesh --output json kb map --family nokia-sros-classic
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.families.nokia-sros-classic.unused_rules` = `[]`
- `data.profiles.nokia-sros-classic-7750-25.10.manual` = `55`

### Nokia MD-CLI 规范模式渲染（configure { 开头，块写成 name { … }，字符串加引号，叶子列表写成 [ … ]）

```bash
lmesh --output json render knowledge/samples/nokia-sros-md-synthetic/md-pe-basic.cfg --canonical
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.mode` = `"canonical"`
- `data.profile` = `"nokia-sros-md-7750-25.10"`
- `data.family` = `"nokia-sros-md"`
- `data.uncovered` = `[]`
- `data.lines.0.text` = `"configure {"`

### Nokia MD-CLI 配置翻译成 Classic CLI（同一设备的两种格式，按名称的引用换成编号）

```bash
lmesh --output json translate knowledge/samples/nokia-sros-md-synthetic/md-pe-services.cfg --to nokia-sros-classic-7750-25.10
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.source.profile` = `"nokia-sros-md-7750-25.10"`
- `data.target.family` = `"nokia-sros-classic"`
- `data.verify.checked` = `true`
- `data.verify.unexplained` = `0`

### 检查 Nokia 配置：端口缺省关闭、SDP、业务与 SAP 的管理状态、客户、VPRN 的 RD / vrf-target

```bash
lmesh --output json check tests/inputs/configs/check/nokia-classic-issues.cfg
```

退出码：`1`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.summary.total` = `14`
- `data.summary.has_errors` = `true`
- `data.summary.by_rule.port.shutdown_bound` = `1`
- `data.summary.by_rule.sdp.far_end_missing` = `1`
- `data.summary.by_rule.service.epipe_shutdown` = `1`
- `data.summary.by_rule.ref.dangling` = `3`

### 对 Nokia MD-CLI 配置跑基础基线（修复参考命令是 MD-CLI 写法）

```bash
lmesh --output json baseline knowledge/samples/nokia-sros-md-synthetic/md-pe-routing-mgmt.cfg
```

退出码：`1`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.baseline` = `"basic"`
- `data.devices.0.family` = `"nokia-sros-md"`
- `data.devices.0.results.sec.telnet_disabled` = `"fail"`
- `data.devices.0.results.sec.ssh_v2` = `"pass"`
- `data.devices.0.results.sec.vty_ssh_only` = `"na"`
- `data.devices.0.results.sec.mgmt_access_filter` = `"fail"`
- `data.devices.0.failures.0.rule` = `"sec.telnet_disabled"`
- `data.devices.0.failures.0.remedy` = `["/configure system security telnet-server false", "/configure system security telnet6-server false"]`

### Nokia Classic 与 MD-CLI 两台设备的跨设备一致性（OSPF 计时器、伪线 VC ID）

```bash
lmesh --output json consistency tests/inputs/configs/nokia/topo-pe-a.cfg tests/inputs/configs/nokia/topo-pe-b.cfg
```

退出码：`1`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.summary.topology.devices` = `2`
- `data.summary.topology.links` = `5`
- `data.summary.total` = `3`
- `data.summary.by_rule.xd.pw.vc_id` = `1`

### 项目列表（--as 账号的视角）

```bash
lmesh --output json --as alice project list
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.mine.0.slug` = `"lab"`
- `data.mine.0.role` = `"owner"`
- `data.default_project` = `"lab"`

### 全局 --project：命令作用于该项目

```bash
lmesh --output json --project lab config list
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.devices.0.name` = `"ATN-CHANGE-01"`
- `data.devices.1.name` = `"PE-CHANGE-01"`

### 新建项目（属主为 --as 账号）

```bash
lmesh --output json --as carol project create '测试环境' --slug testbed
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.slug` = `"testbed"`
- `data.owner` = `"carol"`

### 邀请成员并列出成员

```bash
lmesh --output json project members lab --add carol --role edit
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.members.0.username` = `"alice"`
- `data.members.2.username` = `"carol"`
- `data.members.2.role` = `"edit"`

### 转交项目

```bash
lmesh --output json project transfer lab bob
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.owner` = `"bob"`
- `data.previous_owner` = `"alice"`
- `data.kept_as` = `"edit"`

### 复制为新项目

```bash
lmesh --output json --as bob project copy lab '我的副本' --slug lab-bob
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.slug` = `"lab-bob"`
- `data.owner` = `"bob"`
- `data.copied.devices` = `1`

### 删除项目（--yes 跳过确认）

```bash
lmesh --output json --yes project delete lab
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.deleted` = `true`
- `data.counts.private_devices` = `1`
- `data.counts.refs` = `1`

### 生成个人令牌（只读、不过期）

```bash
lmesh --output json --as alice token create '巡检脚本' --read-only --days 0
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.owner` = `"alice"`
- `data.read_only` = `true`
- `data.state` = `"active"`

### 公共设备库

```bash
lmesh --output json public-device list
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.devices.0.name` = `"PE-CHANGE-01"`
- `data.devices.0.refs.0.project` = `"lab"`

### 导入到公共设备库

```bash
lmesh --output json public-device import tests/inputs/configs/cisco/basic.cfg
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.files.0.ok` = `true`
- `data.files.0.device` = `"ce-rio-01"`

### 只写标识而能访问的同名项目有多个：退出码 2，列出 属主/标识

```bash
lmesh --output json --as bob --project lab config list
```

退出码：`2`

JSON 输出中的关键字段：

- `ok` = `false`
- `error.data.candidates.0` = `"alice/lab"`
- `error.data.candidates.1` = `"carol/lab"`

### 写成 属主/标识：精确找到别人的同名项目

```bash
lmesh --output json --as bob project show carol/lab
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.owner` = `"carol"`
- `data.ref` = `"carol/lab"`
- `data.role` = `"read"`

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

### 检查变更脚本（顺序核查开启）：有错误时退出码 1

```bash
lmesh --output json script-check tests/inputs/scripts/atn-change-order.txt --device knowledge/samples/change/atn-base.cfg
```

退出码：`1`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.kind` = `"change"`
- `data.summary.errors` = `3`
- `data.order.violations` = `2`
- `data.issues.1.code` = `"side_effect_lost"`
- `data.issues.1.line` = `3`
- `data.order.reorder.changed` = `true`
- `data.baseline.device` = `"atn-base"`

### 按依赖重排并写到文件：移动的命令与原因

```bash
lmesh --output json script-check tests/inputs/scripts/asr-change-order.txt --device knowledge/samples/change/asr920-base.cfg --reorder -o out/reordered.txt
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.changed` = `true`
- `data.before.order_violations` = `1`
- `data.after.order_violations` = `0`
- `data.moves.0.reasons.0.dir` = `"after"`

### 两份脚本的文本差异：重排造成的位置变化是移动；语义相同

```bash
lmesh --output json script-diff tests/inputs/scripts/atn-change-order.txt tests/inputs/scripts/atn-change-good.txt --kind change --device knowledge/samples/change/atn-base.cfg --ignore-order
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.equal` = `false`
- `data.stats.move` = `4`
- `data.stats.change` = `1`
- `data.semantic.equal` = `true`
- `data.unordered.only_b` = `[]`

### skill 列表：按功能分组，启用状态、当前版本、近 30 天调用与校验通过率

```bash
lmesh --output json skill list
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.days` = `30`
- `data.groups.0.id` = `"qa"`
- `data.groups.0.count` = `2`
- `data.skills.0.id` = `"ask-query"`
- `data.skills.0.group` = `"qa"`
- `data.skills.0.active` = `"builtin"`
- `data.skills.0.enabled` = `true`
- `data.skills.0.model_key` = `"ai.model_ask"`
- `data.skills.0.stats.calls` = `0`
- `data.skills.3.id` = `"device-summary"`
- `data.skills.3.group` = `"analysis"`
- `data.skills.18.id` = `"card-extract"`
- `data.skills.23.id` = `"skill-evolve"`

### 只列一个功能分组的 skill

```bash
lmesh --output json skill list --group kb
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.skills.0.id` = `"card-extract"`
- `data.groups.5.id` = `"kb"`

### 显示 skill 的生效定义：系统提示词、提示模板、工具、代码校验

```bash
lmesh --output json skill show ask-query
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.id` = `"ask-query"`
- `data.task` = `"ask"`
- `data.active` = `"builtin"`
- `data.checks` = `["gquery.validate"]`
- `data.definition.templates.retry` = `"Your previous query was rejected by the validator: {error}\nWrite a corrected query."`
- `data.variables.0.name` = `"syntax"`

### 试运行（回放，不需要 AI）：用样例记下的回复走一遍渲染与代码校验

```bash
lmesh --output json skill test card-extract --replay
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.mode` = `"replay"`
- `data.version` = `"builtin"`
- `data.check.status` = `"passed"`
- `data.check.score` = `1.0`

### 版本历史：只有内置版本

```bash
lmesh --output json skill versions ask-answer
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.versions.0.version` = `"builtin"`
- `data.versions.0.active` = `true`
- `data.versions.0.source` = `"builtin"`

### 未配置 AI：进化不可用

```bash
lmesh --output json skill evolve ask-query
```

退出码：`3`

JSON 输出中的关键字段：

- `ok` = `false`
- `error.data.status` = `"not_configured"`

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
- `data.rules_skipped` = `[]`

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

### 账号列表

```bash
lmesh --output json user list
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.count` = `2`
- `data.users.0.username` = `"admin"`
- `data.users.0.role` = `"admin"`
- `data.users.1.username` = `"alice"`
- `data.users.1.role` = `"user"`

### 新建管理员，密码从标准输入读取

```bash
lmesh --output json user add ops --role admin --password-stdin
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.user.username` = `"ops"`
- `data.user.role` = `"admin"`
- `data.user.disabled` = `false`

### 停用账号

```bash
lmesh user disable alice
```

退出码：`0`

输出包含：`已停用账号 alice`

### 重置密码（会话失效、锁定解除）

```bash
lmesh --output json user reset-password alice --password-stdin
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.user.username` = `"alice"`
- `data.sessions_closed` = `0`

### 改角色

```bash
lmesh user set-role alice admin
```

退出码：`0`

输出包含：`alice 的角色已改为 管理员`

### 删除账号（--yes 跳过确认）

```bash
lmesh --yes --output json user delete alice
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.deleted` = `"alice"`

### 只看待审核的自助注册账号

```bash
lmesh --output json user list --pending
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.count` = `2`
- `data.users.0.username` = `"dave"`
- `data.users.0.status` = `"pending"`
- `data.users.0.origin` = `"register"`

### 批准待审核账号（建好默认项目）

```bash
lmesh --output json user approve dave
```

退出码：`0`

JSON 输出中的关键字段：

- `ok` = `true`
- `data.user.username` = `"dave"`
- `data.user.status` = `"active"`

<!-- examples:end -->
