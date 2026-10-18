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
| `domains` | 功能域 → 文档文件（相对文档根，可用 `*`） |

- 文档自身的错误写进同名 `.patches.yaml`：`set`（改某张卡的字段）、`add`（文档缺的命令），每条必须写 `reason`。不要直接手改抽取出的卡，重新抽取会被覆盖。

命令语法记法：关键字直接写；`<参数>`；`[ 可选 ]`（内部 `|` 为可选多选一）；`{ a | b }` 必选多选一；`&<1-N>` 重复。

## 3. 抽取命令卡

```
lmesh kb ingest <文档目录> --rules <规则名> [--domain bgp]… [--version V800R025] [--ai]
```

- 结果以 draft 写入 `knowledge/commands/`，每张卡生成审核记录；重复抽取时没变化的跳过，已审核的卡有变化只生成“更新”审核。
- 看输出里的跳过统计：“视图不在范围”多 → 补 `views_map`；“文档语法有错”多 → 补 `syntax_rewrites` 或 patches；参数类型不对 → 补 `param_types`。改规则后再抽一次，直到跳过的都是该跳过的。
- `--ai` 只处理规则失败的命令，结果必须能通过语法解析；AI 未配置时不用。

## 4. 审核

```
lmesh review list --kind card
lmesh review show <编号> / approve <编号> [--note] / reject <编号>
lmesh review approve-all --kind card --rules <规则名> [--contains 文字]   # 批量，需确认
```

draft 卡同样参与解析（状态只表示可信度），所以可以先跑通第 7 步再回头审核。界面：审核队列页。

## 5. Schema 与映射（语义归并）

- **Schema** `knowledge/schema/<功能域>.yaml`：厂商无关的节点（`parent`、`type`、`key`、`semantic` 三语描述、`range` / `choices`、`ref` 指向被引用的对象类型）和 `deps` 依赖规则（reference / prerequisite / mutex；副作用写在 Profile）。按语义归并：例如 RD 华为在 ipv4-family 下、Cisco 在 vrf 下，统一挂在 `vrf.instance.af.rd`。改节点后跑 `lmesh kb validate`。删除节点前看使用情况（界面 Schema 管理会检查），用过的节点改为 `deprecated` + `replaced_by`。
- **映射** `knowledge/mappings/<平台族>.yaml`：按 `view` 正则 + 卡的 `syntax` 正则（第一条命中生效）写“Schema 节点: 表达式”：

| 表达式 | 含义 |
|---|---|
| `$p` | 参数值 |
| `$a\|\|$b\|\|字面量` | 第一个有值的（参数名在不同命令变体里不同时用，可定义 YAML 锚点复用） |
| `fmt:{ip}/{mask\|len}` | 拼接 |
| `kw:import\|export\|both:both`、`kw:single=pop 1` | 按行中关键字取值、可带缺省、可改写 |
| `if:<关键字>:<表达式>` | 有该关键字时才取 |
| `flag` | 开关：出现为 true，否定形式为 false |
| 目标 `a.b{k=v}.c`、`x \| y` | 固定对象键；按值是 IP 还是名称选分支 |

然后 `lmesh kb map`：把规则写进命令卡（`maps_manual: true` 的卡不覆盖），并按命令卡汇总各 Profile 的 `entries`。输出里的 `unused_rules` 是没命中任何卡的规则，要查。

## 6. Profile：`knowledge/profiles/<Profile>.yaml`

- `match`（vendor、版本正则、`fallback`）、`inherits`（新版本继承旧版本，只写差异）、`platform`、`software`。
- `entries` 由 `kb map` 生成；人工条目写 `manual: true`（缺省值 `default`、显示规则 `show_rule`、`supported: false` 等），重新汇总时保留。
- `side_effects`（如华为接口绑定 VPN 会清掉接口 IP）、`implicit`（被引用时隐式存在的对象，如 ASR 920 的桥域）。
- 检查：`lmesh kb coverage --profile <P>`（支持 / 不支持 / 未填写）。界面：Profile 管理、覆盖矩阵。

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
