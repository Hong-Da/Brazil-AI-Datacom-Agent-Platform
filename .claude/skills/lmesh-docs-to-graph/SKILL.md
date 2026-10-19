---
name: lmesh-docs-to-graph
description: 透网 LucidMesh 从厂商产品文档（命令参考）到统一配置图的完整流程：文档转换 → 抽取规则 → 命令卡 → 审核 → Schema 与映射 → Profile → 解析样本 → 补漏 → 往返测试 → 建图 → 发布。用户要接入新厂商、新平台、新软件版本、新功能域，或说“导入产品文档”“补命令卡”“未识别行太多”“往返不一致”时使用。
---

# 从产品文档到配置图

整条链路：

```
产品文档 (HTML/PDF/CHM/MD)
  └─ 转换为 Markdown ──────────────────── core/ingest/convert.py
       └─ 按抽取规则切出命令 ──────────── knowledge/extractors/<规则>.yaml  (+ .patches.yaml)
            └─ 命令卡 draft ──────────── knowledge/commands/<平台族>/<功能域>.yaml
                 └─ 审核队列 ──────────── lmesh review …
                      └─ 映射规则 ─────── knowledge/mappings/<平台族>.yaml → lmesh kb map
                           └─ Profile ─── knowledge/profiles/<Profile>.yaml（汇总 + 人工条目）
配置文本 ── 解析器（视图树 + 命令卡）── 结构化 JSON ── 建图（Schema + Profile）── 统一配置图
                                                         └─ 往返渲染，逐字比较 = 验收门槛
```

所有命令先加载 `scripts/env`，在项目根目录用 `uv run lmesh …`（或 `cli.bat` / `cli.sh`）。知识库改动默认在仓库的 `knowledge/` 做（随程序发布）；部署后的机器在运行时副本 `data/knowledge/` 改，再用知识库包合回。

## 0. 先判断要做什么

| 情况 | 从哪一步开始 |
|---|---|
| 全新厂商 / 平台族 | 第 1 步（要新建 `views.yaml`、抽取规则、映射规则、Profile） |
| 已有平台族的新软件版本 | 第 6 步：新建继承旧版的 Profile，只写差异；有新文档时再走第 2–4 步增量抽取 |
| 已有平台族加功能域 | 第 2 步：在抽取规则的 `domains` 里加文件，在 Schema 加节点，第 5 步补映射 |
| 样本里有未识别行 / 往返不一致 | 第 7、8 步 |

## 1. 平台族的书写习惯：`knowledge/commands/<平台族>/views.yaml`

写块分隔符（华为 `#`、Cisco `!`）、结尾（`return` / `end`）、缩进单位、取消前缀（`undo` / `no`），以及视图树：每个视图的 `parent`、显式退出命令 `exit`（如 `exit-address-family`、`quit`）。视图编号要与抽取规则的 `views_map`、`enters` 和映射规则的 `view` 一致。解析器靠它跟踪当前视图，写错了后面全错。

分块方式不同的平台族用这几个键驱动解析器（缺省值就是华为 / Cisco 的现状，不写即不变；Nokia Classic 见 `commands/nokia-sros-classic/views.yaml`）：

| 键 | 作用（Nokia Classic 的取值） |
|---|---|
| `block` | `indent`（缺省：层级只看缩进差，分页痕迹按上一行视图判断）；`exit`：缩进按 `indent`（4）折算层级，每个块由与开头同列的 `exit` 关闭——原文块也一样，所以范围外块（OSPF 未抽取时的 `ospf` 块）里的 `exit` 不会提前退出外层；没有进入视图的命令下面若有更深的子行，子行按原文保留；多余的 `exit` 原文保留；`braces`（M7-4，Nokia MD-CLI）：按花括号进出块（`name … {` 进入、`}` 关闭、`name { }` 空块，缩进只是排版），行尾的花括号记在 `Line.tail`；当前视图整行匹配不上时按扁平格式（info flat 相对路径、full-context 的 `/configure …`）逐段消耗路径：每段是进入视图的卡，补一行 `virtual` 的块头（编号接在最后一行之后，相邻行的公共前缀共用），原文行记 `prefix`；往返跳过 virtual 行，原文行按 prefix + 命令 + tail 重放 |
| `comment` / `layout` | 注释前缀（`#`）与版式行正则（`^echo "`）：不改变视图栈；`block: exit` 下分隔行也不清空视图栈（Nokia 的段落标记会夹在上下文中间） |
| `begin` | 结构行（`configure`）：进入根视图、清空视图栈；`end`（`exit all`）同样清空；`block: braces` 时 `configure {` 打开的块下的行仍是顶层行 |
| `quotes` | `true`：引号字符串是一个词（名称可含空格），参数取值去掉引号（图的键与引用不带引号），`Match.quoted` 记录原文引号，渲染时写回 |

参数类型另有 `port`（`1/1/1`、`lag-1`、`esat-1/1/1`…）与 `sap`（`端口:VLAN[.VLAN]`、`:*`）；M7-4 加 `leaflist`（MD-CLI 叶子列表 `[ "a" "b" ]` 整段一个取值，映射用 `list:` 拆开）与 `string`（取值总写成引号字符串）。参数可写 `pattern`（附加正则限制，MD-CLI 的 `port` 排除 `lag-`）与 `fill`（语法必填、映射不记的参数，规范渲染缺省写它：ntp server 的 `router-instance "Base"`），都用修正文件的 `set: params` 写。

## 2. 准备文档并写抽取规则：`knowledge/extractors/<规则>.yaml`

- 产品文档放 `DevelopDocs/设备产品文档/…`（不入库）。HTML、PDF、CHM 由 `convert.py` 转 Markdown（CHM 需要 7z）；目录里已有 `.md` 时直接用。
- 规则文件要点（参照 `huawei-vrp8-md.yaml`、`cisco-iosxe-md.yaml`）：

| 键 | 作用 |
|---|---|
| `family`、`negative_prefix` | 平台族、取消前缀 |
| `sections` | 文档里各小节的标题名：`syntax`（华为 Format / Cisco Syntax）、`params`、`views`、`function`、`default`… 带语法小节的标题即一条命令，不论层级 |
| `exclude_titles` | 排除查看、调试、复位类命令 |
| `views_split`、`views_map`、`view_aliases` | 文档里的视图名 → `views.yaml` 视图编号；映射不上的视图丢弃（即“不在范围”） |
| `enters` | 哪些命令进入子视图 |
| `param_types` | 按参数名、再按取值说明推断类型（integer 带 range、ipv4、mask、prefix、asn、rd、community、interface、enum、word、text） |
| `enum_marker`、`enum_item` | 从取值说明里取枚举值 |
| `default_regex` | 缺省值那句话 |
| `syntax_rewrites` | 文档语法写法的统一改写（例如 `[ … ] *` → `&<1-9>`） |
| `domains` | 功能域 → 文档文件（相对文档根，可用 `*`）；文件条目可带 `sections`（只取这些章节）和自己的 `views_map`（同一模式名在不同功能域对应不同视图时用，例如 Cisco 的 `config-router`） |

- 文档自身的错误写进同名 `.patches.yaml`（华为、Cisco 各一份）：`set`（改某张卡的字段，可以改 `enters_view`）、`add`（文档缺的命令，写明 `domain`、`view`），每条必须写 `reason`。不要直接手改抽取出的卡，重新抽取会被覆盖。修正只在抽取到那张卡的批次里生效。
- `param_types` 按顺序匹配：把更具体的规则放前面（例如 `wildcard` 要在 `mask` 之前，否则 OSPF 的反掩码会被当成子网掩码）。
- `enters` 的正则要收紧到真正进入视图的那条命令（例如 `^ospf (<|\[)` 而不是 `^ospf`，后者会把系统视图里所有 `ospf …` 命令都当成进入 OSPF 视图）。`\b` 在连字符前也算词边界：`^interface\b` 会让 `interface-mtu check-mode` 也进入接口视图，写成 `^interface( |$)`。
- 同一页同时列了范围内与范围外的模式时（Cisco `encapsulation` 页有接口模式与 pw-class 模式），在功能域文件条目自己的 `views_map` 里把不要的模式映射为 `view: null`（命中即丢弃，不再落到全局映射）。
- 给已有平台族加新视图后，别的功能域文档里同名视图的命令也会被抽进来（例如加了 `Bridge domain view`，接口功能域的 EVC 章节多出桥域视图的卡）：重新抽取受影响的功能域，确认合并结果只有新增。

命令语法记法：关键字直接写；`<参数>`；`[ 可选 ]`（内部 `|` 为可选多选一）；`{ a | b }` 必选多选一；`&<1-N>` 重复。

## 3. 抽取命令卡

```
lmesh kb ingest <文档目录> --rules <规则名> [--domain bgp]… [--version V800R025] [--ai]
```

- 结果以 draft 写入 `knowledge/commands/`，每张卡生成审核记录；重复抽取时没变化的跳过，已审核的卡有变化只生成“更新”审核。
- 可以只抽部分功能域（`--domain`）：编号会避开其他功能域已有的卡，合并时先按“语法 + 视图”对上已有的卡，所以分批抽取与整体抽取结果一致。抽完重跑一次，合并结果应全部是 unchanged。
- 看输出里的跳过统计：“视图不在范围”多 → 补 `views_map`；“文档语法有错”多 → 补 `syntax_rewrites` 或 patches；参数类型不对 → 补 `param_types`。改规则后再抽一次，直到跳过的都是该跳过的。
- `--ai` 只处理规则失败的命令，结果必须能通过语法解析；AI 未配置时不用。
- 新平台族或大批量补抽时在隔离环境里跑（M7-1 / M7-2 的 Nokia 做法）：`LMESH_KNOWLEDGE__DIR=tmp/<名>/knowledge`（不存在时自动从 `knowledge/` 复制）、`LMESH_DATABASE__URL=sqlite:///tmp/<名>/review.db`，规则改在仓库里、每次抽取前复制过去，满意后把 `commands/<平台族>/` 的卡复制回仓库；这样不往共享数据库写审核记录。`lmesh kb validate` 默认校验运行时知识库，校验仓库要加 `LMESH_KNOWLEDGE__DIR=knowledge`。抽取阶段不要运行 `kb map`；写映射时用 `kb map --family <平台族>`（M7-3 起，只处理该平台族的卡与 Profile）。
- Nokia Classic 命令参考的特殊处理：文档先用 `DevelopDocs/设备产品文档/Nokia/tools/nokia_classic_to_md.py` 转换；`View path` 一行一个上下文，`views_map` 用 `^…$` 精确匹配；同一文件要分到两个功能域时（OSPF 文件里的 segment-routing 归 sr 域），在一个域的文件条目里把这些视图映射为 `view: null`，在另一个域的条目里只映射它们、最后加 `{match: '.', view: null}`；范围内视图里进入范围外子上下文的命令进入 `opaque`（名单由“命令的完整上下文又是别的命令的视图路径”生成）；转换痕迹（`[no]` 前缀、拆开的关键字、斜体的 `<|>`、参数名带空格被拆成两个参数、括号不配对）与列表写法 `<p> [ <p> ]`（改成重复组 `<p> [ <p> ] &<1-31>`，同名参数在匹配记录里会互相覆盖）都用 `syntax_rewrites` 统一改；`Values 0.0.0.0 to …` 这类点分 / 整数两用的取值会被按整数推断，用 `param_types` 按参数名改成 word。
- Nokia MD-CLI 命令参考（M7-4）：`DevelopDocs/设备产品文档/Nokia/tools/nokia_md_to_md.py` 读 13 棵配置树 HTML（开头的 `<pre>` 树 + 每个元素的说明表），按范围文件 `tools/md-scope.txt`（去掉键的上下文路径）转成 Markdown：每个 YANG 元素一条命令，标题是去掉 configure 与键的完整路径（卡编号由它生成，不撞号），叶子 `**name** *name*`、列表 `**name** *键1* **键2名** *键2*`、加密叶子带 `[ hash | hash2 | custom ]`，另加 `**delete** **name**` 作取消形式；参数表的取值列写 `type=YANG 类型`、Options、Range、Max. instances、quoted，由抽取规则 `nokia-sros-md-md` 的 `enum_marker` / `param_types` 推断类型。视图编号 = 路径用 `.` 连接（`router.interface.ipv4.primary`），转换脚本同时生成 `views.yaml` 的视图、规则的 `views_map` 与 `enters`（范围外容器进 `opaque`）；扩大范围时改 md-scope.txt 重新转换、把生成的片段贴回去再抽取。
- 修正文件（`.patches.yaml`）按**抽取批次里的编号**匹配：同名命令在不同功能域的批次里编号都可能是 `xxx`，一起抽取时第二个变成 `xxx~2`，修正就套不上；要修正的功能域分开抽取（M7-3：Base 与 VPRN 的 next-hop 取消写法）。
- 合并时编号以内容为准：同名命令多了一个视图变体、抽取编号整体后移时，被别的卡按“语法 + 视图”认领的编号改用下一个空闲的 `~N`（在整个平台族内避让），不会覆盖已有的卡。抽完用 `lmesh kb validate` 确认没有重复编号与缺失的映射节点。

## 4. 审核

```
lmesh review list --kind card
lmesh review show <编号> / approve <编号> [--note] / reject <编号>
lmesh review approve-all --kind card --rules <规则名> [--contains 文字]   # 批量，需确认
```

draft 卡同样参与解析（状态只表示可信度），所以可以先跑通第 7 步再回头审核。界面：审核队列页。

## 5. Schema 与映射（语义归并）

- **Schema** `knowledge/schema/<功能域>.yaml`：厂商无关的节点（`parent`、`type`、`key`、`semantic` 三语描述、`range` / `choices`、`ref` 指向被引用的对象类型）和 `deps` 依赖规则（reference / prerequisite / mutex；副作用写在 Profile）。新增依赖或副作用规则时 `note` 必须写三语：`note: {zh-CN: 接口引用 ACL, en: 'Interface references the ACL', pt-BR: 'A interface referencia a ACL'}`（英文、葡语含逗号时加引号；只写中文时 `kb validate` 警告，`tests/unit/test_kb_note.py` 不通过）。按语义归并：例如 RD 华为在 ipv4-family 下、Cisco 在 vrf 下，统一挂在 `vrf.instance.af.rd`。改节点后跑 `lmesh kb validate`。删除节点前看使用情况（界面 Schema 管理会检查），用过的节点改为 `deprecated` + `replaced_by`。
- **映射** `knowledge/mappings/<平台族>.yaml`：按 `view` 正则 + 卡的 `syntax` 正则（第一条命中生效）写“Schema 节点: 表达式”：

| 表达式 | 含义 |
|---|---|
| `$p` | 参数值 |
| `$a\|\|$b\|\|字面量` | 第一个有值的（参数名在不同命令变体里不同时用，可定义 YAML 锚点复用） |
| `fmt:{ip}/{mask\|len}` | 拼接 |
| `kw:import\|export\|both:both`、`kw:single=pop 1` | 按行中关键字取值、可带缺省、可改写 |
| `if:<关键字>:<表达式>` | 有该关键字时才取 |
| `flag` | 开关：出现为 true，否定形式为 false |
| `tail:<关键字>` | 关键字之后的全部词（`authentication-mode hwtacacs local`、`service-type ftp ssh`） |
| 目标 `a.b{k=v}.c`、`x \| y` | 固定对象键；按值是 IP 还是名称选分支 |

- `a||b||c` 先拆开逐个计算，取第一个有值的；每个候选都可以是 `kw:` / `if:` / `fmt:` / `tail:` / `$参数` / 字面量。
- 每台设备只有一个的对象（SNMP 代理、SSH 服务、接口上的 OSPF 参数）用固定编号 `"_"`；同一个对象的属性分散在多条命令里时，各条命令都映射到 `"_"`，进程号等作为属性。
- 一条规则套到多张卡时，表达式引用了某张卡没有的参数，这条映射在那张卡上整条不写（`$protocol||kw:tcp|udp` 在没有 `protocol` 参数的 TCP 卡上会丢）：不同变体拆成不同规则，或只用该卡有的参数与字面量。
- 0.3.0 补充的表达式：`if:$参数:表达式`（该参数有值时才取，例如 Cisco `host X` 的反掩码记 `0.0.0.0`）、`tail:关键字:截止词`（只取到截止词之前）、`$序号||auto`（有序号用序号，否则按出现顺序编号）。
- M3 收尾补充：`ctx:subif`（上下文中接口的子接口编号，主接口为 `_`；接入点在接口视图里按它编号，与 Cisco service instance 编号对应）。Schema 节点可标 `secret: true`（取值或对象键是密码、密钥、团体字，跨平台族翻译时不写）、`alias: true`（属性取值也是所属对象的别名键，引用按它也能找到，例如 `acl.instance.number`）。两家结构形态不同的对象（接入点）在 `knowledge/render/<平台族>.yaml` 的 `access_form` 说明，翻译时换结构。
- 原来是字符串的属性实际引用了新功能域的对象时（SNMP / VTY / NTP 引用的 ACL），把 Schema 类型改成 `ref` 并在新功能域的 `deps` 里写 reference 规则，配置检查才能发现悬空 / 孤儿。
- 新的对象类型要在 `knowledge/terms.yaml` 登记华为与 Cisco 两种显示写法（`core/terms.py` 的 `check()` 与 `tests/unit/test_terms.py` 会检查）。
- 新的对象类型还要在 `knowledge/layers.yaml` 的 `objects` 归到 TCP/IP 的某一层（physical / datalink / mpls（2.5 层）/ network / transport / application）；作用层与所属对象不同的属性写在 `attrs`（例如接口的 `vrf` 在网络层），同一对象按键细分写在 `keys`，QoS、时钟同步这类跨层特性在 `features` 的 `match` 里加前缀。没有归层时 `lmesh kb validate` 给出警告 `layers.unclassified`（运行时暂按 `domains` 的功能域缺省层），`tests/unit/test_layers.py` 不通过；新功能域还要在 `domains` 加一行。
- M4-2 补充：`unless:关键字:表达式`（行里没有该关键字时才取值，例如 `timers advertise [ msec ] <间隔>` 的秒与毫秒分开记）。文档在同一页另列的取消写法（`undo rule <rule-id>`、`no <序号>`）用修正文件把它与原 undo 合并成一条多选一语法（`undo rule { <rule-id> | … }`），多出的参数用修正条目的 `add_params` 补（只补、不替换）。
- 对象的 Schema 编号要以父对象编号为前缀（`sr.global.conn_map`，不是 `sr.conn_map`），否则图里的节点编号会带上完整类型名（`sr.global[_]/sr.conn_map[_]`）。
- 一家有、另一家没有的开关（Cisco 没有 Telnet / SSH 服务开关）在 Profile 标 `supported: false`：规则用条件 `supported: <节点>` 判断平台能力（不要写 `family`），翻译校验也不把这类差异计为未解释。
- `lmesh kb map` 只写入命中规则的卡，不清除已不再命中任何规则的旧 maps：删除或改名映射规则后，要手工清掉相关卡上的 maps（否则 Profile 仍有旧节点的条目）。
- 抽取后检查样本里原来是原文（raw）的行：新功能域的卡可能让范围外的同前缀命令变成未识别（SR 一章 MPLS 视图下的 `mpls te path verification` 让 `mpls te` 变成未识别），在功能域文件条目的 `views_map` 里把该视图映射为 `view: null` 丢弃，并删除已写入的这些卡。
- `param_types` 按参数名推断时注意后缀撞车（`virtual-router-id` 以 router-id 结尾会被当成 IPv4），把更具体的规则放前面。

- M7-3（Nokia Classic）补充的写法：`ctx:<参数>`（父上下文行的参数：`static-route-entry <前缀>` 下 next-hop 的前缀、OSPF area、lag 编号）；目标固定键写表达式 `interface{name=$port-id}.lag`（对象键取自参数，用于“在 A 的块里写 B 的属性”：lag 下列成员口、协议块里列接口）；`sap:port|vlan|inner|tag|encap:`、`pfx:addr|len|wild:`、`pre:<词>:`、`via:<类型>:<属性>:`（按键取别的对象的属性，对象要先出现）、`!flag`；指令目标 `"@container"`（只进入视图的容器卡：不产生节点也不算 ext；规范渲染经容器路径写出，容器行由 `ctx:` 要求或 render 的 `containers` 模板给出）、`"@share"`（本行对象对后续兄弟行可见，同一容器的另一块也可见：Nokia 的 AS 号在 router 下、bgp 块在后面）、`"@frame"`（编辑会话 begin / commit，按 render 的 `wrap` 写出）。规则写进 YAML 时带 `{…}` 的目标要加引号、用块写法；参数名可含 `/`、`:`（`$ip-prefix/prefix-length`、`$sdp-id:vc-id`）。
- M7-4（Nokia MD-CLI）补充的写法：`list:<表达式>`（叶子列表拆成列表）、`by:<类型>:<属性>:<表达式>`（`via:` 的反向：属性等于取值的对象的键，没有时取值本身；MD-CLI 按名称引用客户、QoS 策略、过滤器，图里仍以编号为键）、`scale:<倍数>:<表达式>`（单位换算：VRRP message-interval 的 0.1 秒）、`strip:<文字>:<表达式>`（去前缀：`lag-1` → `1`）；指令 `"@first"`（这一行先于兄弟行建图：MD-CLI 按字母序输出，`customer-id` / `filter-id` / `policy-id` 在描述与子块之后）。`via:` / `by:` 引用的对象在后面才出现时，建图自动做第二遍。admin-state 写成 `kw:disable=true|enable=false`（shutdown）或 `kw:enable=true|disable=false`（启用类），布尔叶子 `kw:true=true|false=false`。同一设备的另一种配置格式（MD-CLI 之于 Classic）映射到同一套 Schema 时，对象键与取值按已有格式对齐，用回归测试直接比较两种格式建出的图（`tests/unit/test_nokia_md.py`，列明允许的差异）。
- 新平台族的三层接口形态不同（Nokia 路由器接口 + port）、IGP 写法不同（Nokia 没有 network 宣告、IS-IS 分 area-id / system-id）时，不改 Schema，而是在 render 写 `l3_form` / `instance_keys`，由 `core/translate.py` 换结构；对比校验时源图按同一函数换结构。
- 新加的引用型属性一定写 deps 的 reference 规则（Nokia 的 OSPF / BGP export 策略、SAP 绑定的 VSI），否则配置检查与清理会把被引用的对象当成孤儿。指向接口的属性用类型 `interface` 而不是 `ref: interface`（`ref` 会让接口进入孤儿检查，改变已有平台族的结果）。

然后 `lmesh kb map`：把规则写进命令卡（`maps_manual: true` 的卡不覆盖），并按命令卡汇总各 Profile 的 `entries`。输出里的 `unused_rules` 是没命中任何卡的规则，要查。接入新平台族时用 `lmesh kb map --family <平台族>`（只处理这个平台族的卡与 Profile），运行后 `git diff --stat knowledge/commands knowledge/profiles` 确认其他平台族没有变化。

## 6. Profile：`knowledge/profiles/<Profile>.yaml`

- `match`（vendor、版本正则、`fallback`）、`inherits`（新版本继承旧版本，只写差异）、`platform`、`software`。
- `entries` 由 `kb map` 生成；人工条目写 `manual: true`（缺省值 `default`、显示规则 `show_rule`、`supported: false` 等），重新汇总时保留。
- `defaults_from: <另一个 Profile>`（M7-4）：复用另一个平台族 Profile 的人工条目（缺省值、when / else、assume、show_rule），本 Profile 自动汇总的条目只提供支持情况与命令卡（Nokia MD-CLI 复用 Classic；不用 `inherits`，它会让 `kb map` 不再汇总本 Profile）。
- `when` 可带 `else`（条件不满足时的缺省值，M7-3：Nokia 端口与 LAG 缺省 shutdown、路由器接口缺省 no shutdown）。条目可写 `assume`：其他平台族没有这个节点（华为 / Cisco 的协议实例没有管理状态）时按这个取值理解，翻译成本平台时目标缺省值不同就显式写出并告警。
- 缺省值只对部分对象成立时加 `when`：`{key: 正则}` / `{not_key: 正则}` 按所属对象编号（例如只对物理口），`{attr: {network_type: [broadcast, p2p]}}` 按兄弟属性的有效值。没有条件的缺省值会补到每个同类对象上，容易造成对比的假差异。
- `side_effects`（如华为接口绑定 VPN 会清掉接口 IP）、`implicit`（被引用时隐式存在的对象，如 ASR 920 的桥域）。
- 检查：`lmesh kb coverage --profile <P>`（支持 / 不支持 / 未填写）。界面：Profile 管理、覆盖矩阵。

## 6.5 规范渲染与下发习惯：`knowledge/render/<平台族>.yaml`、`knowledge/change/<平台族>.yaml`

翻译、含默认值的完整配置、变更脚本都用规范渲染（命令卡 + 映射反推，再解析校验），新平台族要写这两份文件（字段说明见各文件开头）。块由 exit 关闭的平台族（Nokia Classic）另写：`exit_all`、`root_depth`、`prologue` / `epilogue`、`section_frame` + `sections`（echo 段落）、`containers`、`quote_params`、`create`、`wrap`（编辑会话）、`prefer`（块头优先的卡）、`avoid`（带密文的卡，同平台族按原文写回）、`infer`（`seq` 顺序编号、`write` 语法可选也写出）、`l3_form`、`instance_keys`；变更知识 `before_delete`（删除前先执行的命令）。块由花括号关闭的平台族（Nokia MD-CLI，M7-4）写 `open: " {"`、`exit_all: "}"`、`prologue: ["configure {"]` / `epilogue: ["}"]`、`container_depth`（经容器到达视图的最多层数，缺省 3）、`containers` 模板（`route {ip-prefix} route-type unicast`）、`infer` 的 `key: true`（名称取对象自己的键）；顶层块按元素名排序后合并同一容器；变更知识写 `begin: [edit-config private]`、`finish: [commit, quit-config]`、`exit: "}"`，删除命令由卡的 `delete …` 取消语法生成。检验：样本加进总清单后 `tests/roundtrip/test_translate.py` 自动做规范等价（含默认值），再在 `samples/change/manifest.yaml` 加变更用例、`samples/translate/manifest.yaml` 加双向翻译用例（未解释差异 0，写出比例写进 `min_rendered`）。

## 7. 用真实配置检验

样本必须先脱敏（`lmesh sanitize <文件> -o <输出> --level strict [--redact 客户名正则]`），真实原件只留在 `DevelopDocs/`。

```
lmesh parse <样本> [--profile P]          # 覆盖率、各类行数
lmesh unknown list                         # 已导入配置的未识别行，按模式汇总
lmesh graph show <样本> --domain vrf       # 节点、依赖边、悬空引用
lmesh roundtrip <样本>                     # 配置 → 图 → 配置逐字比较
```

行的类别：command（匹配到卡）、raw（功能域外的已知命令，原文保留，正常）、unknown（功能域内却匹配不到，要处理）。

## 8. 补漏的判断顺序

| 现象 | 通常原因 | 改哪里 |
|---|---|---|
| unknown，文档里有这条命令 | 视图没映射上 / 语法写法差异 / 参数类型太严 | 抽取规则 `views_map`、`syntax_rewrites`、`param_types`，或 patches `set`，重新抽取 |
| unknown，文档里没有 | 文档缺命令 | patches `add` |
| 视图跟踪错（后续行全错） | `enters` 或 `views.yaml` 的退出命令缺失 | 第 1、2 步 |
| 往返不一致：参数被规范化了 | 映射或渲染没保留原写法 | 检查卡的可选组 / 多选分支记录；映射只影响图，渲染用原始写法 |
| 往返不一致：多个语句被合并 | 映射成了同一个对象键 | 映射目标的 key 不够区分（例如 static route 要带下一跳） |
| 悬空引用 | 引用对象确实没配置，或隐式对象 | 是配置问题就保留（属于配置检查）；是隐式对象就加到 Profile `implicit` |
| 分页痕迹（行首一大段空格）后面的整块视图都错 | 异常缩进的行在上一行视图里匹配不到 | 解析器会逐级往外层视图找；仍然不对时检查 `enters` 与命令卡视图 |
| 新功能域加入后，原来的原文行变成未识别 | 新卡让这些行有了“已知前缀”，但写法没有对应的卡 | 补卡（patches `add`）或修语法（patches `set`）；不要删掉新功能域的卡 |
| 只有一个关键字的卡（接口下的 `mpls`）之后的 `mpls te` 等范围外命令 | 解析器不把单关键字卡当作已知前缀（0.3.0 起），这些行按原文保留 | 不需要处理；若是范围内的命令，补卡 |
| 刚进入子视图的下一行是分页痕迹缩进、却属于外层视图（`ipv4-family` 后的 `ipv6-family`） | 解析器先按子视图匹配，匹配不到再往外层找（0.3.0 起） | 外层视图缺这张卡时补卡 |
| 默认值造成假差异 | 缺省值只对部分对象成立 | Profile 人工条目；条件缺省值是已知限制（M2） |

把新样本加入 `knowledge/samples/` 并登记到 `knowledge/samples/manifest.yaml`（`gate: true` 的参与门槛）。

## 9. 回归与发布

```
lmesh roundtrip --samples      # 门槛：门槛样本全部逐字一致，且功能域内没有未识别行
lmesh kb validate
lmesh kb release -m "说明"     # 校验 → 回归 → 按差异建议版本号 → 打标签 kb-v<版本>
```

测试：`test.bat --roundtrip` / `./test.sh --roundtrip`；单元测试里有解析与建图的断言（`tests/unit/test_mapping_parser_graph.py`）。最后按项目规则补文档（`docs/project-spec.md` 的抽取结果表）、更新进度。

## 约定

- 不手改抽取出的命令卡；改规则或 patches 后重新抽取，保证可重复。
- 每个改动都要能用样本证明：改前改后跑 `roundtrip --samples` 对比。
- 发送给 AI 的内容必须先脱敏；没有 AI 时整条链路照常可用。
