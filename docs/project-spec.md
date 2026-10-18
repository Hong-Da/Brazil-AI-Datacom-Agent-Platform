# 透网 LucidMesh 开发规范

> 生成日期：2026-10-17
> 读取日期：2026-10-17
> last_synced_commit：（阶段三生成初始版本记录后填写）
> 每条决定后标注【默认】【建议：原因】或【用户修改】。
> 选项记录：DevelopDocs/project-config/config.json（确认方式：网页）

## 项目概述

透网（LucidMesh，命令 `lmesh`）把不同厂商、不同版本的路由器配置解析成一张统一的配置图，翻译、对比、模板校验、配置检查都在图上完成。知识库（命令卡、Schema、Profile）以产品文档为来源，经规则或 AI 抽取、人工审核、真实配置校验逐步积累。首批平台为华为 ATN（V800R025C00SPC500）与 Cisco ASR 920（IOS-XE 17.15.x）。给网络工程师在 Windows 或 Linux 上使用，提供 Web 界面、CLI 和远程 API，可离线部署。

## 开发文档

| 文件 | 用途 | 说明 |
|---|---|---|
| `DevelopDocs/透网（LucidMesh）开发文档.md` | 任务文档 | 主文档，只读 |
| `DevelopDocs/设备配置案例/Huawei-ATN.txt` | 相关文件 | 真实 ATN 配置（V800R023C00SPC500，2266 行，未脱敏）；第一份往返样本，脱敏后才能进入 `knowledge/samples/` |
| `DevelopDocs/设备产品文档/Huawei/ATN_V800R025C00SPC500_en/` | 相关文件 | 华为 ATN 产品文档（Markdown，10176 个文件，660 MB）；其中 `12_Reference/01_Command Reference/06_Command Reference/` 共 2726 页，是命令卡抽取的来源。不纳入 DevelopDocs 的 git 仓库 |
| `DevelopDocs/review/<…>/` | 盘点 | 需求盘点结果（阶段三及之后生成） |

## 需求清单

| 编号 | 需求 | 来源 | 里程碑 | 对应功能 | 状态 | 备注 |
|---|---|---|---|---|---|---|
| REQ-001 | 知识库管理：Schema 与 Profile 编辑、覆盖矩阵、审核队列、版本发布与回滚、新软件版本接入 | 任务文档“功能需求”“知识库管理界面” | M1 | （阶段三补齐） | 待开发 | |
| REQ-002 | 结构化解析：配置文本 → 结构化 JSON，保留行号，未识别行进入待处理队列 | 任务文档“功能需求” | M1 | `core/parser.py`、`lmesh parse`、`POST /parse`、`lmesh unknown list` | 已完成（v0.0.5） |  |
| REQ-003 | 图构建与渲染：结构化 JSON ↔ 统一配置图，补全隐藏的默认与派生节点 | 任务文档“功能需求” | M1 | `core/graph.py`、`core/renderer.py`、`lmesh graph show / render / roundtrip` | 已完成（v0.0.5） |  |
| REQ-004 | 依赖记录：引用、前置、副作用、互斥、跨设备五类依赖边 | 任务文档“功能需求” | M1 | `core/graph.py` 依赖边 | 已完成（v0.0.5） | 跨设备依赖随拓扑还原（M4）上线 |
| REQ-005 | 配置脱敏：替换密码、团体字、密钥、公网 IP 等，保持引用关系 | 任务文档“功能需求” | M1 | `core/sanitize.py`、`lmesh sanitize`、`POST /sanitize` | 已完成（v0.0.2） |  |
| REQ-006 | 知识库导入导出：产品文档、配置、知识库包导入；导入校验与冲突审核 | 任务文档“功能需求”“知识库文件与导入” | M1 | `core/kbservice.py`、`core/ingest/`、`lmesh kb import/export/ingest` | 已完成（v0.0.4） |  |
| REQ-007 | 图形化查看：Schema 视图与设备配置图（对比、依赖、拓扑视图随对应功能上线） | 任务文档“功能需求”“图形界面” | M1 | | 待开发 | |
| REQ-008 | AI 接入：可配置 API、按任务选模型、调用记录、密钥加密；未配置时核心功能可用 | 任务文档“功能需求”“AI 接入” | M1 | | 待开发 | 暂无 AI 接口，先做规则抽取，接口留好 |
| REQ-009 | 配置对比：按有效值对比，改名识别、语义等价 | 任务文档“功能需求” | M2 | | 待开发 | |
| REQ-010 | 配置检查：悬空引用、孤儿对象、互斥冲突、规则约束 | 任务文档“功能需求” | M2 | | 待开发 | |
| REQ-011 | 冗余配置清理：列出未被引用的 ACL、route-policy、prefix-list 并生成删除脚本 | 任务文档“功能需求” | M2 | | 待开发 | |
| REQ-012 | 配置翻译：切换目标 Profile 渲染，不支持项和默认值差异告警 | 任务文档“功能需求” | M3 | | 待开发 | |
| REQ-013 | 配置模板：参数化模板校验并提取变量 | 任务文档“功能需求” | M3 | | 待开发 | |
| REQ-014 | 配置生成：模板 + 参数表批量生成配置 | 任务文档“功能需求” | M3 | | 待开发 | |
| REQ-015 | 增量变更脚本：按依赖拓扑排序生成下发命令和回滚脚本 | 任务文档“功能需求” | M4 | | 待开发 | |
| REQ-016 | 变更影响分析 | 任务文档“功能需求” | M4 | | 待开发 | |
| REQ-017 | 割接迁移：翻译 + 接口映射表 | 任务文档“功能需求” | M4 | | 待开发 | |
| REQ-018 | 拓扑还原 | 任务文档“功能需求” | M4 | | 待开发 | |
| REQ-019 | 跨设备一致性检查 | 任务文档“功能需求” | M4 | | 待开发 | |
| REQ-020 | 安全基线审计 | 任务文档“功能需求” | M4 | | 待开发 | |
| REQ-021 | 版本历史：图快照，按时间查看配置变化 | 任务文档“功能需求” | M5 | | 待开发 | |
| REQ-022 | 文档导出：IP 地址表、VLAN 表、BGP 邻居表、接口描述表 | 任务文档“功能需求” | M5 | | 待开发 | |
| REQ-023 | 特性能力查询 | 任务文档“功能需求” | M5 | | 待开发 | |
| REQ-024 | AI 查询与护栏 | 任务文档“功能需求” | M5 | | 待开发 | |
| REQ-025 | 报告导出：对比与检查结果导出（中英双语） | 任务文档“里程碑与版本规划”0.2.0 | M2 | | 待开发 | 里程碑图中列出，功能表中没有单列 |

## 待确认

- 配置样本数量：任务文档目标为每个平台 20～50 份、至少 3 种网络角色；目前只有 1 份 ATN 配置，Cisco 先用公开样本，工作中的配置脱敏后陆续补充。

## N 名称与标识

- N1 项目名称：中文名“透网”，英文名 LucidMesh，项目标识 `lmesh`，Python 包名 `lmesh`（任务文档中的名称）【默认】
- Logo：`assets/brand/logo.svg`，三层立体板 + 顶层三节点小图（分层对应“文本 → 结构 → 图”）；主色 #2A9D8F（松石绿，中层），配色 #2B6F9E、#F2B33D【用户修改：经四轮调整后选定】

## A 基线

- A1 版本管理：git【默认】
- A2 技术栈：Python + Node / TypeScript（细节见“技术栈”）【建议：前端 G6 / Cytoscape.js + ELK 需要 Node 构建，运行时不需要 Node】
- A9 工具链存放：依赖下载缓存放在项目内；解释器与运行时按技术栈默认（Python、Node 放在项目内）【默认】
- A3 运行平台：Windows + Linux【默认】
- A4 文本编码：UTF-8（bat 文件 UTF-8 无 BOM + chcp 65001 + CRLF）【默认】
- A5 编码行为准则：Karpathy guidelines（已安装）【默认】
- A6 一键运行脚本：`start.bat` / `start.sh`【默认】
- A7 版本号：语义化版本（用户已确认）。M1 开发期间用 `0.0.x`，M1 验收打 `0.1.0`，M2–M5 依次对应 `0.2.0`–`0.5.0`；开发阶段完成、新需求、问题修复升修订号【默认 + 第二轮 Q8】
- A8 文档语言：中文【用户修改】

## 技术栈

| 部分 | 技术栈 | 目录 | 包管理与锁文件 | 版本固定 | 主要框架与库 | 测试 | 检查与格式化 | 构建与打包 |
|---|---|---|---|---|---|---|---|---|
| 后端、CLI、API | Python 3.12 | 根目录，代码在 `src/lmesh/` | uv，`uv.lock` | `.python-version`、`requires-python` | FastAPI、Typer、SQLAlchemy 2.0 + Alembic、networkx、ruamel.yaml、tomli-w、dulwich、cryptography（Fernet）、pdfplumber、TTP；可选：anthropic、openai | pytest | Ruff + mypy | PyInstaller（one-folder） |
| 前端 | Node 24 LTS + TypeScript | `frontend/` | pnpm，`pnpm-lock.yaml` | `frontend/.nvmrc`、`packageManager` | Vue 3 + Vite、Element Plus、Cytoscape.js + elkjs、CodeMirror 6、vue-i18n、Pinia | Vitest + Playwright | ESLint + Prettier | Vite 构建，产物复制到 `src/lmesh/web/static/` |

各项取舍（第二轮全部采用推荐）：

- 配置解析：命令卡驱动的自研解析器，TTP 作补充——命令卡已有命令格式和视图，可直接生成匹配规则并保留行号。
- 文档预处理：Markdown 按标题直接切分；PDF 用 pdfplumber（MIT，避开 PyMuPDF 的 AGPL）；CHM 先解包为 HTML。
- 知识库 YAML：ruamel.yaml，写回时保留注释和字段顺序，避免每次保存产生大段无关 diff。
- 知识库 Git：dulwich（纯 Python），离线机器不需要系统 git。
- API Key：cryptography Fernet 加密，密钥文件在 `config/`，不写入用户目录；后续可对接 KeyStash。
- 图渲染：Cytoscape.js 复合节点 + expand-collapse 对应“设备 → 功能域 → 对象 → 属性”的层级折叠，elkjs 做层级布局。
- 组件库：Element Plus 自带巴西葡萄牙语语言包和暗色模式。

- `scripts/env` 中设置的变量：`UV_CACHE_DIR`、`UV_PYTHON_INSTALL_DIR`、`UV_PYTHON_PREFERENCE=only-managed`、`UV_TOOL_DIR`、`PYTHONUTF8=1`、`npm_config_cache`、`COREPACK_HOME`、`PATH` 前置 `.toolchain/runtime/node`；pnpm store 写在 `frontend/pnpm-workspace.yaml`（`storeDir: ../.toolchain/cache/pnpm-store`；pnpm 12 不再读取 .npmrc 中的这项）；`UV_INSTALL_DIR`（start 脚本安装 uv 时装到 `.toolchain/bin/`）
- 需要系统安装的工具：无。uv 没有时 start 脚本询问后安装到 `.toolchain/bin/`；Node 由 start 脚本按 `frontend/.nvmrc` 下载到 `.toolchain/runtime/node/` 并核对 SHA256；前端构建产物带源码指纹，没变化时不重复构建
- 版本号文件：`pyproject.toml`（以此为准），`frontend/package.json` 保持一致

## B 项目形态

- B1 项目类型：Web 应用（同时提供 CLI 与远程 API）【默认】
- B2 Web 框架：FastAPI + Vue 3【默认：按技术栈推荐】

## C 界面与输出

- C1 界面语言：中文 / English / Português (Brasil)，可切换，首次跟随浏览器，无法匹配时中文【默认】
- C2 报告语言：中英双语，分别提供下载【默认】
- C3 界面主题：自动 / 明 / 暗三态切换，初始自动【默认】
- C4 页面设计 skill：frontend-design（已安装）【默认】

## D 数据与运行

- D1 数据存储：SQLite（`data/lmesh.db`）为默认，同一套 SQLAlchemy 代码支持 PostgreSQL（JSONB），在配置中切换；测试在两种数据库上都运行【默认 + 第一轮 Q3】
- D2 配置文件：`config/config.toml`，仓库只提交 `config/config.example.toml`【默认】。所有配置项定义在 `src/lmesh/core/config.py` 的 `FIELDS` 一处，向导、示例配置、校验都从它生成；环境变量 `LMESH_<分组>__<名称>` 优先
- D3 默认监听：`0.0.0.0:9000`，局域网可访问【用户修改】
- D4 首次运行向导：Web 向导；引导配置：界面语言、监听地址、数据库类型与连接、API 令牌、AI 接口（可跳过）【默认】
- D5 日志：INFO，按日期轮转，保留 14 天，写入 `logs/` 并输出到控制台；不记录密码、令牌、API Key 和未脱敏配置【默认】

## E 调用接口

- E1 CLI：开发，命令名 `lmesh`，默认输出文本，支持 `--output json`【默认】
- E2 远程 API：开发，前缀 `/api/v1`，API 令牌认证（`Authorization: Bearer <token>`）【默认】

### 已确认的能力清单

| 能力 | CLI 命令 | API 接口 | 调用场景 | 版本 |
|---|---|---|---|---|
| 健康检查与版本 | `lmesh status` | `GET /api/v1/health` | 监控、Docker 健康检查 | 0.1.0 |
| 耗时任务状态 | — | `GET /api/v1/tasks/{id}` | 文档抽取、批量往返测试的轮询 | 0.1.0 |
| 配置脱敏 | `lmesh sanitize <文件\|目录> -o <输出>` | `POST /api/v1/sanitize` | 工作配置带出做样本 | 0.1.0 |
| 配置导入 | `lmesh config import <文件\|目录\|zip>` | `POST /api/v1/configs` | 识别厂商 → 脱敏 → 解析 → 入图 | 0.1.0 |
| 解析为结构化 JSON | `lmesh parse <文件> [--profile]` | `POST /api/v1/parse` | 调试解析器、提供结构化数据 | 0.1.0 |
| 查看设备配置图 | `lmesh graph show <设备> [--domain]` | `GET /api/v1/devices/{id}/graph` | 脚本、AI、前端图视图 | 0.1.0 |
| 按 Profile 渲染 | `lmesh render <设备> [--profile]` | `POST /api/v1/render` | 往返检查，以后翻译复用 | 0.1.0 |
| 往返测试 | `lmesh roundtrip [<文件>\|--samples]` | `POST /api/v1/roundtrip` | 回归测试、0.1.0 门槛 | 0.1.0 |
| 未识别配置行 | `lmesh unknown list` | `GET /api/v1/unknown-lines` | 找知识库缺口 | 0.1.0 |
| 知识库校验 | `lmesh kb validate` | `POST /api/v1/kb/validate` | 改 YAML 后检查 | 0.1.0 |
| 文档导入与命令卡抽取 | `lmesh kb ingest <目录> --vendor --version` | `POST /api/v1/kb/ingest` | 接入新厂商、新版本 | 0.1.0 |
| 知识库包导入导出 | `lmesh kb export` / `lmesh kb import <包>` | `GET /api/v1/kb/export` | 备份、迁移、分享 | 0.1.0 |
| 审核队列 | `lmesh review list / approve / reject` | `GET /api/v1/review`、`POST /api/v1/review/{id}` | 批量审核抽取结果 | 0.1.0 |
| 知识库发布、对比与回滚 | `lmesh kb release / diff / rollback` | `POST /api/v1/kb/releases` | 发布知识库版本 | 0.1.0 |
| 覆盖矩阵查询 | `lmesh kb coverage [--profile]` | `GET /api/v1/kb/coverage` | 看 Profile 覆盖缺口 | 0.1.0 |
| AI 接口连通性测试 | `lmesh ai test` | `POST /api/v1/ai/test` | 配置 AI 后验证 | 0.1.0 |
| 配置对比 | `lmesh diff <A> <B>` | `POST /api/v1/diff` | 主备、变更前后 | 0.2.0 |
| 配置检查 | `lmesh check <设备>` | `POST /api/v1/check` | 巡检、预检 | 0.2.0 |
| 冗余配置清理 | `lmesh cleanup <设备>` | `POST /api/v1/cleanup` | 生成删除脚本 | 0.2.0 |
| 报告导出 | `lmesh report <diff\|check> --format html\|xlsx` | `POST /api/v1/reports` | 结果交给他人 | 0.2.0 |
| 配置翻译 | `lmesh translate <设备> --to <profile>` | `POST /api/v1/translate` | 多厂商迁移 | 0.3.0 |
| 模板校验与变量提取 | `lmesh template check <设备> --template <名>` | `POST /api/v1/templates/{name}/check` | 新设备上线核查 | 0.3.0 |
| 模板批量生成 | `lmesh generate --template <名> --params <表格>` | `POST /api/v1/generate` | 按 IP 规划表生成 | 0.3.0 |
| 增量变更与回滚脚本 | `lmesh change plan <旧> <新>` | `POST /api/v1/changes` | 下发与回滚 | 0.4.0 |
| 变更影响分析 | `lmesh impact <设备> <对象>` | `GET /api/v1/devices/{id}/impact` | 改前看影响 | 0.4.0 |
| 割接迁移 | `lmesh migrate <设备> --to <profile> --map <映射表>` | `POST /api/v1/migrations` | 整机换厂商 | 0.4.0 |
| 拓扑还原与跨设备一致性 | `lmesh topo build / check` | `POST /api/v1/topology` | 全网拼图、链路核查 | 0.4.0 |
| 安全基线审计 | `lmesh audit <设备\|全部>` | `POST /api/v1/audit` | 安全检查 | 0.4.0 |
| 版本历史 | `lmesh history <设备>` | `GET /api/v1/devices/{id}/history` | 按时间看变化 | 0.5.0 |
| 审计表格导出 | `lmesh export tables --type ip\|vlan\|bgp\|desc` | `GET /api/v1/exports/{type}` | IP、VLAN、BGP 表 | 0.5.0 |
| 特性能力查询 | `lmesh feature <关键词>` | `GET /api/v1/features` | 查支持情况与默认值 | 0.5.0 |
| 自然语言查询 | `lmesh ask "<问题>"` | `POST /api/v1/ask` | 需要配置 AI | 0.5.0 |

32 项全部开发（第二轮确认，8 项建议 / 可选能力由用户勾上）。每项能力在对应里程碑实现。

## 实现方案

### 技术选型

见“技术栈”。图计算在内存中用 networkx 完成，数据库只负责存储与查询；v1 不引入图数据库（全网大图后期再考虑 PostgreSQL + AGE 或 Neo4j）。

### 模块划分

`src/lmesh/` 下：

| 模块 | 职责 |
|---|---|
| `core/config`、`core/logging`、`core/i18n` | 配置加载（TOML + 默认值 + 环境变量覆盖）、日志、多语言文案 |
| `core/store` | SQLAlchemy 模型与访问：devices、config_versions、nodes、edges，以及 review_items、unknown_lines、tasks、ai_calls、kb_releases |
| `core/kb` | 知识库 YAML 加载、校验、Profile 继承展开、版本（dulwich）、知识库包导入导出 |
| `core/ingest` | 文档切分（Markdown / PDF / CHM）、命令卡抽取：通用抽取器读取 `knowledge/extractors/<厂商>.yaml` 的规则（规则通道），规则覆盖不了时走可选的 AI 通道；接入新厂商一般只需新增一份规则文件 |
| `core/sanitize` | 厂商识别、保持引用关系的脱敏（同一原值始终映射到同一替换值） |
| `core/parser` | 命令卡驱动的解析器：按视图（view）识别层级，输出带行号的结构化 JSON、未识别行、原文节点 |
| `core/graph` | 图构建：Schema 节点、Profile 默认值生成隐藏节点、派生节点、五类依赖边 |
| `core/renderer` | 按 Profile 渲染：往返模式按原始顺序与格式输出；规范模式按依赖拓扑排序输出 |
| `core/engine` | 对比、检查、模板、翻译、变更、拓扑等运算（随里程碑加入） |
| `core/review` | 审核队列：AI / 规则抽取的命令卡、新节点、未识别行映射、导入冲突 |
| `core/ai` | 可配置的 AI 接口（Anthropic / OpenAI 兼容 / 本地）、按任务选模型、调用记录、降级 |
| `cli/` | Typer 命令，只做参数解析与输出格式化 |
| `api/` | FastAPI 路由，只做校验与序列化；同时提供 `web/static/` 中的前端 |

CLI、API、Web 都只调用 `core`，不重复实现业务逻辑。

### 关键流程

1. **导入**：读取文件 → 按特征识别厂商（华为 `#` 分隔与 `sysname`、IOS-XE `!` 与 `hostname`）→ 脱敏 → 选择 Profile（ATN 配置头部的 `!Software Version V800R023C00SPC500` 映射到 `huawei-atn-v800r023`）。
2. **解析**：按视图切分层级（华为以缩进与 `#` 界定，IOS-XE 以缩进与 `!` 界定）；缩进只作参考，以命令卡的视图知识为准——真实采集的配置里有终端分页留下的异常缩进（ATN 样本中 `                  import-route direct …`），这类行归入当前视图，原始空白原样保留用于往返→ 每行用命令卡生成的模式匹配 → 输出结构化 JSON（含行号）；功能域外的行成为“原文节点”，完全不认识的行进入未识别队列。
3. **建图**：结构化 JSON 映射到 Schema 节点 → 按 Profile 补全默认（隐藏）节点、派生节点 → 生成依赖边。
4. **渲染**：往返模式按原始顺序、缩进和分隔符输出，用于验证“配置 → 图 → 配置”文本一致；规范模式按依赖拓扑排序，供翻译和变更脚本使用。
5. **知识库构建**：华为命令参考页结构固定（Function / Format / Parameters / Views / Default / Usage Guidelines），规则抽取为命令卡 draft → 归并到 Schema → 汇总 Profile → 审核 → 往返测试回归 → 发布。

Profile 规划：`huawei-atn-v800r025`（以产品文档为准）、`huawei-atn-v800r023`（继承 R025，只写差异，用于现有配置样本）、`cisco-iosxe-asr920-17.15`。

### 风险与难点

| 风险 | 应对 |
|---|---|
| ASR 920 的 EFP / BDI 与 ATN 子接口模型差异大 | 抽象统一的“业务接入点”节点，映射必须人工审核（M1-6） |
| 往返文本一致要求保留原始格式 | 节点记录原始顺序、缩进、分隔符；往返模式与规范模式分开渲染 |
| 默认值是条件化的 | Profile 的 `default` 支持表达式；暂无设备，默认值以文档为准标为 `reviewed` |
| 样本只有 1 份 ATN 配置，Cisco 没有真实配置 | 补充产品文档中的配置举例与公开样本（如 Batfish 测试用例）；工作中的配置脱敏后陆续补充 |
| 没有 AI 接口 | 华为命令参考格式固定，规则抽取即可覆盖；Cisco 公开命令参考结构不同，规则抽取覆盖率可能偏低，需要更多人工审核 |
| ATN 样本与文档版本不一致（R023 / R025） | R023 Profile 继承 R025，只记录差异 |

### 知识库文件格式

| 文件 | 内容 |
|---|---|
| `kb.yaml` | 知识库版本 `kb_version`、功能域列表 |
| `commands/<平台族>/views.yaml` | 平台族的书写习惯（块分隔符 `#` / `!`、结尾 `return` / `end`、缩进单位）与视图树（父视图、进入视图的命令卡、显式退出命令） |
| `commands/<平台族>/<功能域>.yaml` | 命令卡：`id`、`syntax`、`view`、`enters_view`、`params`（类型、范围、可选值）、`default`、`maps`（参数 → Schema 节点，`@` 表示整条命令对应的开关节点）、`depends_on`、`side_effects`、`source`、`status` |
| `schema/<功能域>.yaml` | 统一节点：`parent`、`type`、`semantic`（按语义归并）、`key`、`range`、`ordered`、`ref`、`deprecated` / `replaced_by`；以及 `deps` 依赖规则 |
| `profiles/<Profile>.yaml` | `match`（厂商、版本正则、`fallback`）、`inherits`、`entries`（各节点的支持情况、默认值、显示规则、对应命令卡、来源与可信度；人工条目 `manual: true`）、`side_effects` |

命令语法（厂商无关）：关键字直接写，参数 `<名称>`，可选 `[ ]`，多选一 `{ a | b }`；参数类型 `integer`（带 `range`）、`ipv4`、`mask`、`wildcard`、`prefix`、`mask-length`、`asn`、`rd`、`community`、`interface`、`word`、`text`（吃掉行尾全部内容，含空格）。匹配时记录每个可选组是否出现、多选组选了哪一支，渲染时按同样的选择重放，保证往返逐字一致；多种匹配时取关键字最多的一种。

Profile 匹配：版本正则匹配上的优先；都不匹配时用标了 `fallback` 的 Profile（华为 → `huawei-atn-v800r025`，Cisco → `cisco-iosxe-asr920-17.15`）。

### 命令卡抽取（M1-5 结果）

通用抽取器读取 `knowledge/extractors/<规则>.yaml`：带“格式”小节（华为 Format、Cisco Syntax）的标题即一条命令，不论标题层级；规则定义小节名、视图映射、参数类型推断（按参数名与取值说明，枚举取值说明里的每一项）、进入子视图的命令、各功能域对应的文件与章节。HTML、PDF（按字体还原粗体 / 斜体，按字号推断标题）、CHM（需要 7z）先转换成 Markdown 再抽取。

| 平台族 | 扫描 | 命令卡 | 跳过 |
|---|---|---|---|
| huawei-vrp8（命令参考 V800R025C00SPC500） | 2589 个文件、3272 条命令 | 2054（M1-5 时 1994，M1-6 按样本补规则后；bgp 1402、interface 364、routing-policy 146、vrf 54、static-route 28） | 视图不在 0.1.0 范围 1374、查看 / 调试类 444、文档语法本身有错 60、无配置形式 5、重复 8 |
| cisco-iosxe（公开命令参考 96 条） | 96 个文件 | 244（含 `cisco-iosxe-md.patches.yaml` 补充的 64 张） | 文档语法有错 7、视图不在范围 2、重复 5 |

全部以 draft 写入程序自带的 `knowledge/commands/`。运行时知识库首次创建时为每张 draft 卡生成审核记录；在审核完成前，解析器同样使用 draft 卡（审核状态只表示可信度，不影响能否解析），每个结果都能看到所依据命令卡的状态。

### 映射、解析、建图与往返（M1-6～M1-8 结果）

**Schema**：`knowledge/schema/` 下 5 个功能域共 93 个节点（interface 含业务接入点 access、vrf 含地址族与 RT、static-route、bgp 含实例 / 地址族 / 对等体 / 组、routing-policy 含 route-policy / prefix-list / community-filter 等），每个域带 `deps` 依赖规则。

**映射规则**：`knowledge/mappings/<平台族>.yaml` 按命令卡语法写“参数 → Schema 节点”的表达式，`lmesh kb map` 写进命令卡（卡上标了 `maps_manual: true` 的不覆盖）。表达式：

| 写法 | 含义 |
|---|---|
| `$p` | 参数 p 的值 |
| `$a\|\|$b\|\|字面量` | 依次取第一个有值的 |
| `fmt:{ip}/{mask\|len}` | 拼接；`{a\|b}` 取第一个有值的参数 |
| `kw:import\|export\|both:both`、`kw:single=pop 1` | 按行中出现的关键字取值（可带缺省值、可改写） |
| `if:<关键字>:<表达式>` | 行中有该关键字时才取值 |
| `flag` | 开关：有这一行为 true，否定形式为 false |
| 目标 `a.b{k=v}.c`、`x \| y` | `{k=v}` 固定对象键；`\|` 分支按取值是 IP 还是名称选择 |

取值按节点类型规范化（掩码 → 长度、`ip/mask` → 前缀等）；一张卡没有用到的可选参数对应的属性不写入。

**Profile 生成**：`core/kb/profilegen.py` 按已映射的命令卡汇总各节点的支持情况与对应命令卡；人工条目（`manual: true`，如缺省值、副作用、隐式对象）保留不覆盖。

**解析器**（`core/parser.py`）：逐行判断类别——separator / end / comment / blank / command（匹配到命令卡）/ raw（功能域外但属于已知命令前缀，原文保留）/ unknown（功能域内却匹配不到，进入待处理队列）。按视图树跟踪当前视图：显式退出命令（`exit-address-family`、`quit` 等）先于缩进处理；异常缩进（终端分页痕迹）仍归在上一行的视图；否定形式（`undo` / `no`）先按卡上的 `undo` 语法匹配，再按“否定 + 原命令”匹配。

**建图**（`core/graph.py`）：语义节点编号形如 `interface[Vbdif101]/vrf`、`bgp.instance[65000]/bgp.af[afi=ipv4,vrf=]/peer[RR]`；对象节点、属性节点、功能域外的 raw 节点和 unknown 节点都入图；Profile 的缺省值补成隐藏的默认节点（`origin: default`），隐式对象（如 Cisco 服务实例引用的桥域）补成派生节点（`origin: derived`）。依赖边 contains / reference / prerequisite / side_effect / mutex 按 Schema 的 `deps` 与 Profile 的 `side_effects` 生成；引用目标不存在时记入悬空引用（属于 M2 配置检查的发现，不影响往返）。

**渲染与往返**（`core/renderer.py`、`core/roundtrip.py`）：往返模式按图中各语句记录的原始写法（命令卡的可选组与多选分支选择、原始缩进）重放，与原文逐字比较。`knowledge/samples/manifest.yaml` 列出全部样本，`gate: true` 的样本还要求功能域内没有未识别行；`lmesh roundtrip --samples` 与测试分类 roundtrip 都跑这份清单。

| 样本 | 结果 |
|---|---|
| 华为 ATN 真实配置（严格脱敏，720 条命令） | 逐字一致，覆盖率 100%，未识别 0；图 2464 个节点、30 条副作用边 |
| 全部 13 个样本（门槛样本 11 个） | 全部逐字一致；门槛样本未识别行 0 |

**已知限制（留给 M2 处理）**：条件缺省值（例如 Cisco 的 `negotiation auto` 只对物理口有效，却同样补到了 Loopback）目前按节点类型统一补，配置对比时可能产生假差异；M2 在 Profile 缺省值上增加适用条件。

### Web 界面（M1-9 结果）

按 `DevelopDocs/ui-preview/M1/` 的 13 个预览页实现（预览尚未经用户评审，见决策记录 D-0012）。设计系统（配色、字体、面板、表格等样式类）从预览移植到 `frontend/src/styles/app.css`，Element Plus 的变量跟随它；页面文案按页放在 `frontend/src/i18n/pages/<页>.json`（三语键一致由单元测试检查）。

| 页面 | 路由 | 主要接口 |
|---|---|---|
| 首页 | `/` | `/summary`、`/kb/profiles`、`POST /roundtrip {samples}` |
| 设备与导入 | `/devices` | `/devices`、`POST /configs`、`/devices/rebuild` |
| 设备配置图 | `/graph/:id` | `/devices/{id}/graph?raw=true`、`/kb/schema`、`/devices/{id}/rebuild`、`POST /roundtrip` |
| 未识别行 | `/unknown-lines` | `/unknown-lines`、`/unknown-lines/states`、`/unknown-lines/review` |
| Schema 视图 / 管理 | `/schema`、`/schema/edit` | `/kb/schema`、`/kb/coverage`、`/kb/profile-compare`、`/kb/schema/nodes/*`、`/kb/draft` |
| Profile 管理 / 覆盖矩阵 | `/profiles`、`/coverage` | `/kb/profiles*`、`/kb/profile-compare`、`/kb/coverage` |
| 审核队列 | `/review` | `/review*`、`/review/batch`、`/kb/extractors` |
| 知识库版本 | `/releases` | `/kb/draft`、`/kb/releases`、`/kb/diff`、`/kb/rollback`、`/regression/last` |
| 文档与知识库包 | `/ingest` | `/kb/ingest`、`/tasks`、`/kb/export`、`/kb/import` |
| AI 接口 | `/ai` | `/ai/settings`、`/ai/test`、`/ai/calls` |
| 向导 / 令牌页 | `/setup`、`/login` | `/setup`、`/config` |

设备配置图：cytoscape + ELK 分层布局；首屏按节点预算逐层展开（大图只展开到功能域），点节点展开下一层，子节点过多时收成“还有 N 个”；原文按对象收起；图、详情、原文三块联动（选节点高亮行，点行反选节点）。

**与预览页的差异**（预览中没有后端支撑的部分，按实际能力简化或去掉，不做假数据）：AI 只支持一个接口 + 按任务选模型（预览是多接口）；文档导入填服务器上的目录（不上传文件，格式自动识别）；配置导入一步完成识别与脱敏（没有逐文件指定厂商和脱敏前后对照）；审核队列只能按条件批量通过（不能按勾选批量、不能批量驳回）；Schema 管理的依赖规则只读；未识别行没有映射建议；设备图没有跨设备边。

**留给后续的后端增强**（界面已按现有接口做到最好）：未识别行返回涉及设备与位置、映射建议接口；审核列表的关键字 / 规则 / 来源筛选与按 id 批量；schema_node、mapping、profile_entry 的审核通过动作；依赖规则的编辑接口；Schema 节点 `unit` 字段；单个 Profile 导出与删除；抽取任务取消与参数记录；配置导入的预检模式；样本回归的进度上报；图接口返回每行分类。

**并发安全**（联调中发现并修正）：知识库 YAML 读取改为每线程一个实例；写入原子化（临时文件 + 替换）并用进程内写锁串行；数据库迁移每个进程每个地址只做一次。

### 知识库的存放

仓库中的 `knowledge/` 是程序自带的知识库，随版本发布；首次启动时复制到 `data/knowledge/`（独立的 dulwich 仓库），管理界面的修改提交到那里；需要合回程序自带的知识库时，用知识库包导出再导入开发仓库。部署后的机器不需要代码仓库也能维护知识库。

## 里程碑与开发阶段

> 规划来源：开发文档中已有（5 个版本、3 道门槛），开发阶段按 1.5 节细化；项目规模：大

### 里程碑

| 编号 | 目标 | 包含需求 | 交付物 | 验收方式 |
|---|---|---|---|---|
| M1 | 0.1.0 知识库与往返：0.1.0 功能域（接口、VRF、静态路由、BGP、路由策略）在 ATN 和 ASR 920 上往返一致 | REQ-001–008 | 知识库、解析器、图、渲染器、脱敏、知识库管理界面、Schema 视图与设备配置图、CLI 与 API | 门槛“往返文本一致”：全部样本往返一致，功能域内无未识别行；本机与 Linux 测试通过；用户验收 |
| M2 | 0.2.0 对比与检查 + IGP、BFD、管理面 | REQ-009–011、REQ-025 | 有效值对比、配置检查、冗余清理、对比视图、报告导出 | 门槛“真实配置无假差异”；本机与 Linux 测试通过；用户验收 |
| M3 | 0.3.0 翻译与模板 + MPLS、L2VPN、ACL | REQ-012–014 | 翻译与告警、模板校验与变量提取、批量生成 | 门槛“翻译结果审核通过”；本机与 Linux 测试通过 |
| M4 | 0.4.0 变更与分析 + 高级特性 | REQ-015–020 | 变更与回滚脚本、影响分析、割接迁移、拓扑、一致性、基线 | 用例通过；本机与 Linux 测试通过；用户验收 |
| M5 | 0.5.0 扩展功能 | REQ-021–024 | 版本历史、表格导出、特性查询、AI 查询与护栏 | 用例通过；本机与 Linux 测试通过；用户验收 |

### 开发阶段

| 编号 | 内容 | 完成标准 | 对应测试 | 依赖 | 规模 |
|---|---|---|---|---|---|
| M1-1 | 项目骨架：uv + pnpm、scripts/env、配置、日志、数据库（SQLite / PostgreSQL）、多语言与主题框架、start / test / cli 脚本、CLI 与 API 骨架、图标导出 | start 可启动并显示首页，test 在两种数据库上都通过 | 单元：配置加载、多语言键；CLI：status；API：health；文档测试 | — | L |
| M1-2 | 界面预览与评审：知识库管理、审核队列、Schema 视图、设备配置图（左图、右详情、下原文三栏联动） | 用户逐页通过 | — | M1-1 | M |
| M1-3 | 配置导入与脱敏：厂商识别、文件 / 目录 / zip 导入、保持引用关系的脱敏；ATN 配置作为第一份样本 | ATN 配置脱敏后无密钥、团体字、真实 IP，同一对象替换一致 | 单元：脱敏规则；CLI：sanitize、config import | M1-1 | M |
| M1-4 | 知识库文件格式：命令卡 / Schema / Profile 的 YAML 结构、加载、校验、Profile 继承展开、知识库包导入导出 | 示例知识库校验通过，继承展开正确 | 单元：校验与继承；CLI：kb validate / export / import | M1-1 | M |
| M1-5 | 命令卡抽取：抽取规则按厂商写成 YAML（`knowledge/extractors/<厂商>.yaml`，描述文档中命令格式、参数、视图、缺省值所在的章节与写法），通用抽取器按规则执行；华为命令参考与 Cisco 公开命令参考各一份规则；AI 通道（可选）；审核队列后端 | 0.1.0 功能域两个平台的命令卡生成为 draft 并可审核 | 单元：抽取器；CLI：kb ingest、review | M1-4 | L |
| M1-6 | Schema 归并与 Profile 生成：0.1.0 功能域统一节点，含业务接入点抽象 | 两个 Profile 覆盖功能域，跨厂商映射经用户审核 | 单元：归并与汇总；kb coverage | M1-5 | L |
| M1-7 | 结构化解析器：命令卡驱动，保留行号，未识别行入队，功能域外行成为原文节点 | 样本中功能域内的行全部识别 | 单元：解析器；CLI：parse、unknown list | M1-6 | L |
| M1-8 | 图构建与渲染：隐藏默认 / 派生节点、五类依赖边、往返模式渲染、往返测试工具（规范模式渲染并入 M3 配置翻译，见决策记录） | 全部样本往返文本一致 | 单元：建图与渲染；CLI：graph show、render、roundtrip | M1-7 | L |
| M1-9 | Web 界面实现：知识库管理（编辑、覆盖矩阵、审核、发布回滚）、Schema 视图、设备配置图、AI 接入设置 | 按评审通过的预览页实现，端到端测试通过 | API 全量；Playwright 端到端 | M1-2、M1-8 | L |
| M2-1 | 界面预览与评审：对比视图、检查结果、报告 | 用户逐页通过 | — | M1 | S |
| M2-2 | 功能域扩展：IGP、BFD、管理面 | 样本中这些行全部识别且往返一致 | 往返回归 | M1 | L |
| M2-3 | 有效值对比、改名识别、语义等价 | 对比基准用例通过 | 单元、CLI、API | M2-2 | L |
| M2-4 | 配置检查与冗余清理脚本 | 检查用例通过 | 单元、CLI、API | M2-2 | M |
| M2-5 | 对比视图、检查界面、报告导出（中英双语） | 端到端测试通过 | 端到端 | M2-1、M2-3、M2-4 | M |
| M3-1 | 界面预览与评审：翻译结果与告警、模板编辑与校验 | 用户逐页通过 | — | M2 | S |
| M3-2 | 功能域扩展：MPLS LDP、L3VPN 完善、VPWS / VPLS、ACL | 样本往返一致 | 往返回归 | M2 | L |
| M3-3 | 配置翻译与告警 | 双向翻译用例通过 | 单元、CLI、API | M3-2 | L |
| M3-4 | 参数化模板：约束匹配、变量提取 | 模板用例通过 | 单元、CLI、API | M3-2 | M |
| M3-5 | 模板制作辅助与批量生成 | 参数表生成配置并可往返 | 单元、CLI、API | M3-4 | M |
| M3-6 | 翻译与模板界面 | 端到端测试通过 | 端到端 | M3-1、M3-3、M3-5 | M |
| M4-1 | 界面预览与评审：依赖分析视图、拓扑视图、变更脚本 | 用户逐页通过 | — | M3 | S |
| M4-2 | 功能域扩展：SR-MPLS、EVPN、VRRP、QoS、时钟同步 | 样本（含 ATN 大量 QoS）往返一致且不再依赖原文节点 | 往返回归 | M3 | L |
| M4-3 | 增量变更：图 diff、依赖拓扑排序、副作用补发、回滚脚本 | 变更用例通过 | 单元、CLI、API | M4-2 | L |
| M4-4 | 变更影响分析 | 用例通过 | 单元、CLI、API | M4-2 | S |
| M4-5 | 割接迁移：翻译 + 接口映射表 | 整机迁移用例通过 | 单元、CLI、API | M4-3 | M |
| M4-6 | 拓扑还原与跨设备一致性检查 | 多设备样本拓扑正确 | 单元、CLI、API | M4-2 | L |
| M4-7 | 安全基线审计 | 基线用例通过 | 单元、CLI、API | M4-2 | M |
| M4-8 | 依赖分析视图、拓扑视图与相关界面 | 端到端测试通过 | 端到端 | M4-1、M4-3–M4-7 | M |
| M5-1 | 界面预览与评审 | 用户逐页通过 | — | M4 | S |
| M5-2 | 版本历史 | 用例通过 | 单元、CLI、API | M4 | M |
| M5-3 | 审计表格导出 | 用例通过 | 单元、CLI、API | M4 | S |
| M5-4 | 特性能力查询 | 用例通过 | 单元、CLI、API | M4 | S |
| M5-5 | AI 自然语言查询与生成配置护栏 | 未配置 AI 时隐藏；配置后用例通过 | 单元、CLI、API | M4 | M |

## 已确认的待确认点

| 问题 | 结论 | 确认日期 |
|---|---|---|
| 运行环境 | 开发机可联网；目标机器需要离线使用；Web 界面需局域网访问 | 2026-10-17 |
| 产品文档是否纳入 DevelopDocs 仓库 | 忽略不提交 | 2026-10-17 |
| ATN 版本差异 | R025 为主 Profile，R023 继承 | 2026-10-17 |
| Cisco 资料 | 先用公开资料；IOS-XE 按 17.15.x 建 Profile | 2026-10-17 |
| 配置样本来源 | 用户给的 ATN 配置 + 产品文档配置举例 + 公开样本，工作中的配置脱敏后补充 | 2026-10-17 |
| 数据库 | 默认 SQLite，同一套代码支持 PostgreSQL，测试两种都跑 | 2026-10-17 |
| 脱敏样本是否入主仓库 | 提交；原始配置只留在 DevelopDocs/ | 2026-10-17 |
| AI 接口 | 暂时没有；先做规则抽取，AI 接口留好 | 2026-10-17 |
| 功能域外的配置行 | 作为原文节点原样保留，整份配置往返一致；单独统计功能域覆盖率 | 2026-10-17 |
| M1 期间的版本号 | 0.0.x，M1 验收打 0.1.0 | 2026-10-17 |
| 命令卡抽取范围 | 只抽 0.1.0 功能域相关命令，其余按需 | 2026-10-17 |
| 能力清单 | 32 项全部开发 | 2026-10-17 |
| Linux 登录 | 用密码装一次本项目专用密钥，之后用密钥登录 | 2026-10-17 |
| 版本检查钩子 | 加上（SessionStart → scripts/version-status.sh） | 2026-10-17 |
| 知识库的存放 | 程序自带 knowledge/ + 运行时副本 data/knowledge/ | 2026-10-17 |
| 文档抽取规则 | 每个厂商一份 YAML 抽取规则，加入 M1-5 | 2026-10-17 |
| PostgreSQL 测试环境 | 在 Linux 测试机上用 Docker 临时起 PostgreSQL，用完删除 | 2026-10-17 |
| M1 推进方式 | 自动推进到 M1 完成；界面预览照常生成并打开，等用户回来评审 | 2026-10-17 |

## T 测试

- T1 测试框架：pytest（后端）；Vitest + Playwright（前端）【默认】
- T2 测试范围：单元、CLI、API、文档；另加“往返回归”（全部样本的 roundtrip）【默认】
- T3 一键测试脚本：`test.bat` / `test.sh`【默认】
- T4 在线测试：需要【默认】
- 规则见 `tests/README.md`。

## L Linux 开发与测试环境

- L1 Linux 环境：提供 Linux 机器（用户确认）【默认】
- L2 用途：开发、测试【默认】
- L3 开发方式：本机编写，同步到 Linux 运行【默认】
- 地址与端口：linux-test-host:22
- 用户名：root【用户修改；警告：建议改用专门的用户】，认证方式：本项目专用 SSH 密钥 `~/.ssh/lmesh_dev_ed25519`（由一次性密码安装，密码不记录）
- 工作目录：`~/lmesh/`，允许 sudo：是（每次使用前仍先说明并征得同意）【用户修改】
- L4 在本机查看 Web 界面：SSH 端口转发【默认】
- 环境信息：Ubuntu 26.04 LTS，x86_64，4 核，16 GB 内存，磁盘可用 174 GB，可访问外网；已有 python3、git、curl、rsync，没有 uv、node（由 start.sh 安装到工作目录内）；连接检查日期 2026-10-17
- 端口：Linux 上 9000 已被 docker-proxy 占用，在 Linux 上开发和测试时临时用 9001 运行（只覆盖运行参数，不改默认值 D3）；端口转发 `ssh -i ~/.ssh/lmesh_dev_ed25519 -N -L 9001:127.0.0.1:9001 root@linux-test-host`

## G 远程仓库

- G1 同步到：不同步【默认】
- `DevelopDocs/` 是单独的本地仓库，不推送

## 进度与版本提醒

- 进度：`DevelopDocs/progress/progress.json`；R1 进度网页：生成；R2 自动打开：里程碑验收时【默认】
- 版本检查钩子：`.claude/settings.json` 的 SessionStart → `scripts/version-status.sh`（用户已同意）

## U 界面评审

- U1：先做预览页确认再编码；U2 预览范围：每个里程碑涉及的页面；预览页位置：`DevelopDocs/ui-preview/`【默认】

## 项目记忆

- `CLAUDE.md` 中由 `gen_memory.py` 生成的区块，当前 30 条（含 4 条本项目约定：开发期版本号、代码与 AI 的分工、知识库来源与原文节点、样本脱敏）。

## 目录结构

```
lmesh/
├── README.md                   项目说明
├── CHANGELOG.md                版本变更记录（阶段三生成）
├── CLAUDE.md                   项目记忆
├── pyproject.toml / uv.lock    Python 依赖与锁文件
├── .python-version             Python 版本
├── .gitignore / .gitattributes
├── start.bat / start.sh        一键运行
├── cli.bat / cli.sh            CLI 包装脚本
├── test.bat / test.sh          一键测试
├── package.bat / package.sh    分发打包（阶段三）
├── migrate-pack.bat            一键打包迁移（阶段三）
├── docker-build.bat / .sh      一键构建镜像（阶段三）
├── Dockerfile / compose.yaml / .dockerignore（阶段三）
├── config/
│   └── config.example.toml     配置示例
├── src/lmesh/                  Python 包
│   ├── core/                   业务逻辑：config、logging、i18n、store、kb、ingest、sanitize、parser、graph、renderer、engine、review、ai
│   ├── cli/                    Typer 命令
│   ├── api/                    FastAPI 路由
│   ├── locales/                后端文案（zh-CN、en、pt-BR）
│   └── web/static/             前端构建产物（不入库，由 start 脚本构建）
├── frontend/                   Vue 3 + Vite 前端（package.json、pnpm-lock.yaml、.nvmrc、pnpm-workspace.yaml、src/）
├── knowledge/                  程序自带的知识库
│   ├── sources/                原始资料来源记录
│   ├── extractors/             各厂商文档的命令卡抽取规则（YAML）
│   ├── commands/               命令卡（按厂商版本与功能域分文件）
│   ├── schema/                 统一 Schema（按功能域分文件）
│   ├── profiles/               厂商 + 版本 Profile
│   ├── templates/              配置模板
│   └── samples/                已脱敏的配置样本与往返期望结果
├── assets/brand/               Logo 源文件与导出的图标
├── docs/
│   ├── project-spec.md         项目规范
│   ├── cli.md / api.md / openapi.json
│   ├── migration.md / docker.md（阶段三）
│   └── changelog/              更新记录（阶段三）
├── scripts/
│   ├── env.bat / env.sh        工具链与缓存位置
│   ├── version-status.sh       版本检查（SessionStart 钩子）
│   └── build_icons.py          从 logo.svg 导出图标
├── tests/                      测试（见 tests/README.md）
├── .claude/
│   ├── settings.json           SessionStart 钩子
│   └── skills/                 项目专属 skill（阶段三）
├── DevelopDocs/                开发文档（单独的本地仓库，主仓库忽略）
├── data/ logs/ cache/ tmp/     运行时文件（不入库）
├── .toolchain/                 依赖缓存与项目内的 Python、Node（不入库）
├── .venv/ frontend/node_modules/（不入库）
└── dist/                       打包结果（不入库）
```

## 不适用的维度

- G2–G4 仓库地址、认证方式、推送时机：G1 为“不同步”。

## F 收尾辅助

（开发完成后填写。第一轮初选：F1 打包迁移脚本需要，默认包含数据、配置；F2 离线部署【建议：目标机器需要离线使用】；F3 Docker 完整）

## P 分发方式

（开发完成后填写。第一轮初选：便携压缩包）

## K 项目专属 skill

（开发完成后填写。第一轮初选：CLI、API、测试、更新 skill 全部生成）

已生成（开发中按用户要求提前生成）：

| skill | 位置 | 用途 |
|---|---|---|
| `lmesh-docs-to-graph` | `.claude/skills/lmesh-docs-to-graph/SKILL.md` | 从厂商产品文档到统一配置图的完整流程：文档转换、抽取规则与补丁、命令卡抽取与审核、Schema 与映射、Profile、样本检验与补漏、往返回归与发布（2026-10-17 用户要求总结） |
