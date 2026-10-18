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
| REQ-001 | 知识库管理：Schema 与 Profile 编辑、覆盖矩阵、审核队列、版本发布与回滚、新软件版本接入 | 任务文档“功能需求”“知识库管理界面” | M1 | Web：Schema 管理、Profile 管理、覆盖矩阵、审核队列、知识库版本；`core/kb/edit.py` | 已完成（v0.0.6） | 界面预览待用户评审 |
| REQ-002 | 结构化解析：配置文本 → 结构化 JSON，保留行号，未识别行进入待处理队列 | 任务文档“功能需求” | M1 | `core/parser.py`、`lmesh parse`、`POST /parse`、`lmesh unknown list` | 已完成（v0.0.5） |  |
| REQ-003 | 图构建与渲染：结构化 JSON ↔ 统一配置图，补全隐藏的默认与派生节点 | 任务文档“功能需求” | M1 | `core/graph.py`、`core/renderer.py`、`lmesh graph show / render / roundtrip` | 已完成（v0.0.5） |  |
| REQ-004 | 依赖记录：引用、前置、副作用、互斥、跨设备五类依赖边 | 任务文档“功能需求” | M1 | `core/graph.py` 依赖边 | 已完成（v0.0.5） | 跨设备依赖随拓扑还原（M4）上线 |
| REQ-005 | 配置脱敏：替换密码、团体字、密钥、公网 IP 等，保持引用关系 | 任务文档“功能需求” | M1 | `core/sanitize.py`、`lmesh sanitize`、`POST /sanitize` | 已完成（v0.0.2） |  |
| REQ-006 | 知识库导入导出：产品文档、配置、知识库包导入；导入校验与冲突审核 | 任务文档“功能需求”“知识库文件与导入” | M1 | `core/kbservice.py`、`core/ingest/`、`lmesh kb import/export/ingest` | 已完成（v0.0.4） |  |
| REQ-007 | 图形化查看：Schema 视图与设备配置图（对比、依赖、拓扑视图随对应功能上线） | 任务文档“功能需求”“图形界面” | M1 | Web：Schema 视图、设备配置图 | 已完成（v0.0.6） | 对比、依赖、拓扑视图随 M2–M4 上线 |
| REQ-008 | AI 接入：可配置 API、按任务选模型、调用记录、密钥加密；未配置时核心功能可用 | 任务文档“功能需求”“AI 接入” | M1 | Web：AI 接口设置；`/ai/settings` | 已完成（v0.0.6） | 暂只支持一个接口 + 按任务选模型 |
| REQ-009 | 配置对比：按有效值对比，改名识别、语义等价 | 任务文档“功能需求” | M2 | `core/compare.py`、`lmesh compare`、`POST /compare`、Web 配置对比 | 已完成（v0.1.1） | 对比视图 v0.2.0 |
| REQ-010 | 配置检查：悬空引用、孤儿对象、互斥冲突、规则约束 | 任务文档“功能需求” | M2 | `core/checks.py`、`core/rules.py`、`lmesh check`、`POST /check`、Web 配置检查 | 已完成（v0.1.1） | 忽略发现、规则开关 v0.2.0 |
| REQ-011 | 冗余配置清理：列出未被引用的 ACL、route-policy、prefix-list 并生成删除脚本 | 任务文档“功能需求” | M2 | `core/cleanup.py`、`lmesh cleanup`、`POST /cleanup`、Web 冗余清理 | 已完成（v0.1.1） | 按选中对象清理 v0.2.0 |
| REQ-012 | 配置翻译：切换目标 Profile 渲染，不支持项和默认值差异告警 | 任务文档“功能需求” | M3 | `core/canon.py`、`core/translate.py`、`lmesh translate`、`lmesh render --canonical --with-defaults`、`POST /translate`、`POST /render` | 已完成（v0.3.0） | 含默认值的完整配置（用户 2026-10-18 要求）共用规范渲染器 |
| REQ-013 | 配置模板：参数化模板校验并提取变量 | 任务文档“功能需求” | M3 | `core/template.py`、`core/template_match.py`、`core/template_draft.py`、`lmesh template check / extract / draft`、`POST /templates/check / extract / draft` | 已完成（v0.3.0） | |
| REQ-014 | 配置生成：模板 + 参数表批量生成配置 | 任务文档“功能需求” | M3 | `core/template_gen.py`、`lmesh template generate`、`POST /templates/generate` | 已完成（v0.3.0） | |
| REQ-015 | 增量变更脚本：按依赖拓扑排序生成下发命令和回滚脚本 | 任务文档“功能需求” | M4 | | 待开发 | |
| REQ-016 | 变更影响分析 | 任务文档“功能需求” | M4 | | 待开发 | |
| REQ-017 | 割接迁移：翻译 + 接口映射表 | 任务文档“功能需求” | M4 | `core/migration.py`、`lmesh migrate`、`POST /migrate`、`POST /migrate/suggest-map` | 后端完成（M4-5） | 界面待做；增量下发脚本复用 `core/change.py` |
| REQ-018 | 拓扑还原 | 任务文档“功能需求” | M4 | | 待开发 | |
| REQ-019 | 跨设备一致性检查 | 任务文档“功能需求” | M4 | | 待开发 | |
| REQ-020 | 安全基线审计 | 任务文档“功能需求” | M4 | `core/baseline.py`、`core/report_baseline.py`、`knowledge/rules/baseline-security.yaml`、`lmesh baseline`、`POST /baseline`、`GET /baseline/rules`、`POST /baseline/report` | 后端完成（M4-7） | 界面待做；SSH 算法、RADIUS、SNMPv3 用户等待知识库补节点 |
| REQ-021 | 版本历史：图快照，按时间查看配置变化 | 任务文档“功能需求” | M5 | | 待开发 | |
| REQ-022 | 文档导出：IP 地址表、VLAN 表、BGP 邻居表、接口描述表 | 任务文档“功能需求” | M5 | | 待开发 | |
| REQ-023 | 特性能力查询 | 任务文档“功能需求” | M5 | | 待开发 | |
| REQ-024 | AI 查询与护栏 | 任务文档“功能需求” | M5 | | 待开发 | |
| REQ-025 | 报告导出：对比与检查结果导出（中英双语） | 任务文档“里程碑与版本规划”0.2.0 | M2 | `core/report.py`、`lmesh report`、`POST /reports` | 已完成（v0.2.0） | 中文 / English × HTML / Markdown（决策 D-0016） |
| REQ-026 | 显示风格：华为 / Cisco 两套叫法与命令写法，统一 Schema 以华为为基准，图按视图层级展示，界面、报告随时切换（默认华为） | 用户 2026-10-18 | M2 补充（0.2.1） | `knowledge/terms.yaml`、`core/terms.py`、`GET /kb/terms`、配置 `ui.term_style`、报告 `style` | 已完成（v0.2.1） | |
| REQ-027 | 关系图谱视图：类似笔记软件的关系图，每个对象一个圆点、连线表示引用与依赖、力导向布局、可拖动缩放 | 用户 2026-10-18 | M2 补充（0.2.1） | Web 设备配置图 | 已完成（v0.2.1） | |
| REQ-028 | 隐藏配置的区分：默认值、派生值在各处有统一的样式与图例，可开关显示；配置翻译时处理不同厂商的默认值差异 | 用户 2026-10-18 | M2 补充（0.2.1）；翻译部分 M3 | Web 各视图；M3 翻译 | 已完成（v0.2.1） | 含默认值的完整配置文本随 M3 渲染器实现 |

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
| 报告导出 | `lmesh report <compare\|check> --lang zh-CN\|en --format html\|md` | `POST /api/v1/reports` | 结果交给他人（中英双语；格式由 xlsx 改为 Markdown，见决策 D-0016） | 0.2.0 |
| 配置翻译 | `lmesh translate <设备> --to <profile>` | `POST /api/v1/translate` | 多厂商迁移 | 0.3.0 |
| 模板校验与变量提取 | `lmesh template check <模板> <设备>`、`lmesh template extract`、`lmesh template draft` | `POST /api/v1/templates/check`、`/extract`、`/draft` | 新设备上线核查、从现网配置做模板 | 0.3.0 |
| 模板批量生成 | `lmesh template generate <模板> <参数表>` | `POST /api/v1/templates/generate` | 按 IP 规划表生成 | 0.3.0 |
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

**已知限制（已在 M2-2 解决）**：条件缺省值（例如 Cisco 的 `negotiation auto` 只对物理口有效）——Profile 条目增加了适用条件 `when`，见“功能域扩展（M2-2 结果）”。

### 功能域扩展：IGP、BFD、管理面（M2-2 结果）

新增四个功能域：`ospf`（进程、区域、network、被动接口、FRR、BFD 联动、接口参数 `interface.ospf`）、`isis`（进程、NET、级别、开销类型、接口参数 `interface.isis`）、`bfd`（全局使能、静态会话、接口参数）、`mgmt`（NTP、SNMP、Syslog、SSH / Telnet / FTP、AAA 本地用户与方案与域、TACACS+ / HWTACACS、登录线路）。Schema 共 222 个节点（0.1.0 为 93 个）。

| 平台族 | 新增命令卡 | 资料 |
|---|---|---|
| huawei-vrp8 | 1253（ospf 233、isis 297、bfd 80、mgmt 643） | 命令参考 V800R025：OSPF、IS-IS、网络可靠性（BFD）、NTP、SNMP、信息管理、SSH、AAA、用户登录与用户界面章节 |
| cisco-iosxe | 143（含修正文件新增与改写的卡） | 公开命令参考新增 114 页（ospf 28、isis 18、bfd 5、mgmt 63），`DevelopDocs/设备产品文档/Cisco/.../README.md` 列出来源与原文问题 |

新增样本：`knowledge/samples/huawei-atn-v800r025-synthetic/atn-igp-mgmt-01.cfg`、`cisco-iosxe-asr920-synthetic/pe-asr920-02-igp-mgmt.cfg`（合成，覆盖 IS-IS、BFD 会话、OSPF 多区域、管理面）。现网 ATN 样本中这些功能域的行全部识别，全部门槛样本往返一致、无未识别行。

本阶段补充的机制：

| 机制 | 说明 |
|---|---|
| 异常缩进回退 | 分页痕迹出现在子视图块后的第一行时（例如 OSPF `frr` 块之后的 `area`），在上一行视图匹配不到就逐级往外层视图找，按匹配到的那一层计算缩进 |
| 行尾空白 | 匹配到命令卡的行也保留行尾空格，往返逐字一致 |
| 编号稳定 | 分批抽取不同功能域时，新卡避开其他功能域已有的编号；合并时先按“语法 + 视图”对上已有的卡，重复抽取结果不变 |
| 功能域的视图映射 | 抽取规则的功能域文件条目可以带自己的 `views_map`（Cisco 的 OSPF、IS-IS、BGP 文档都写 `Router configuration (config-router)`） |
| 华为修正文件 | 新增 `knowledge/extractors/huawei-vrp8-md.patches.yaml`（例如 `user-interface con 0` 的文档语法错误） |
| 映射表达式 | `tail:<关键字>` 取关键字之后的全部词（方法列表、服务类型、协议列表）；`a||b` 先拆分再逐个计算（每个候选可以是 `kw:`、`if:`、`fmt:`、`tail:`）；重复组参数只有一个值时取这个值，文本类型多值拼成一行；一行里的对象没取到值时，属于它的属性也不写 |
| 条件缺省值 | Profile 条目的 `when`：`{key: 正则}`、`{not_key: 正则}` 按所属对象编号判断，`{attr: {兄弟属性: 取值或取值列表}}` 按兄弟属性的有效值判断。解决了 0.1.0 的已知限制：Cisco `negotiation auto` 只补到物理口；OSPF hello / dead 只在广播与点到点网络上补 10 / 40 秒 |
| 对象前置依赖 | Schema 依赖规则可以是“对象 → 对象”的前置关系（BFD 会话需要先全局使能 BFD）；缺少时记入图的 `missing_prerequisites`，供配置检查使用，不算悬空引用 |

### 功能域扩展：MPLS、L2VPN、ACL（M3-2 结果）

新增三个功能域并完善 L3VPN：`mpls`（MPLS 全局与 LSR-ID、LDP 全局 / 远端对等体 / MD5 认证、接口 MPLS 与 LDP 使能及 LDP 与 IGP 同步参数）、`l2vpn`（VPWS：PW 模板 / 伪线类、接入点上的伪线、Cisco 命名的 xconnect；VPLS：VSI / VFI 与对等体、接口与桥域绑定）、`acl`（基本 / 高级 ACL 与规则，以及接口、VTY、SNMP、NTP、路由策略对 ACL 的引用）；`vrf` 补隧道策略、路由数量限制、VPN FRR、VPN 实例的路由策略与 IPv6 地址族入口。Schema 共 322 个节点（M2 为 225 个；新增 97 个：mpls 29、l2vpn 37、acl 22、vrf 9）。MPLS TE / RSVP-TE 不在范围，原文保留（决策 D-0041）。

| 平台族 | 新增命令卡 | 资料 |
|---|---|---|
| huawei-vrp8 | 429（mpls 167、l2vpn 199、acl 28、vrf 29、interface 6——桥域视图） | 命令参考 V800R025：MPLS 一章的 MPLS LDP 一节、VPWS、VPLS、ACL、VPN 隧道管理、IPv6 VPN（只取进入 IPv6 地址族的命令） |
| cisco-iosxe | 64（mpls 22、l2vpn 25、acl 14、vrf 3，含修正文件新增与改写的卡） | 公开命令参考新增 47 页（mpls 20、l2vpn 17、acl 8、vrf 2），`DevelopDocs/设备产品文档/Cisco/.../README.md` 列出来源与原文问题 |

**Schema 节点（新节点编号固定，翻译与模板可以直接引用）**：

| 功能域 | 对象 | 属性 |
|---|---|---|
| mpls | `mpls.global`（"_"） | `lsr_id`、`label_protocol` |
| | `mpls.ldp`（"_"） | `lsr_id`、`router_id_interface`、`router_id_force`、`graceful_restart`、`session_protection`、`accept_target_hello`、`send_all_loopback`、`mldp_p2mp`、`igp_sync_delay`、`igp_sync_holddown`、`holdtime`、`log_neighbor_changes` |
| | `mpls.ldp.auth`（键 peer） | `password` |
| | `mpls.ldp.remote_peer`（键 name；Cisco 名称即地址） | `remote_ip`、`description` |
| | `interface.mpls`（"_"） | `ldp`、`mtu`、`label_protocol`、`ldp_transport_address`、`ldp_local_lsr_id`、`ldp_igp_sync_delay`、`ldp_igp_sync` |
| l2vpn | `l2vpn.global`（"_"） | — |
| | `l2vpn.pw_class`（键 name） | `control_word`、`peer`、`tunnel_policy`、`mtu`、`encapsulation`、`preferred_path` |
| | `interface.access.pw`（键 role：primary / backup / bypass） | `peer`、`vc_id`、`pw_class`、`tunnel_policy`、`control_word`、`encapsulation` |
| | `l2vpn.xconnect`（键 name，Cisco 专有）、`.ac`（键 interface、instance）、`.pw`（键 peer、vc_id） | `pw.pw_class` |
| | `l2vpn.vsi`（键 name） | `description`、`vsi_id`、`signaling`、`mode`、`bd_mode`、`mtu`、`encapsulation`、`tunnel_policy` |
| | `l2vpn.vsi.peer`（键 address） | `vc_id`、`tunnel_policy`、`pw_class`、`encapsulation` |
| | `bridge_domain.member`（键 interface、instance） | 另有属性 `interface.vsi`、`bridge_domain.vsi`、`bridge_domain.description` |
| acl | `acl.instance`（键 name：编号或名称） | `type`（basic / advanced / interface / link / mpls）、`number`、`match_order`、`description`、`step` |
| | `acl.instance.rule`（键 id） | `action`、`protocol`、`source_ip`、`source_wildcard`、`destination_ip`、`destination_wildcard`、`source_port`、`destination_port`、`vrf`、`name`、`description`、`log` |
| | — | 引用：`interface.acl_in`、`interface.acl_out`、`rp.policy.node.match_acl`；`mgmt.line.acl_in`、`mgmt.snmp.community.acl`、`mgmt.ntp.access.acl` 由字符串改为 `ref: acl.instance` |
| vrf | `tunnel_policy`（键 name） | `description`、`select_seq`、`load_balance`；`vrf.instance.af` 新增 `tunnel_policy`、`prefix_limit`、`prefix_limit_threshold`、`prefix_limit_warn_only`、`vpn_frr` |

**跨厂商的归并**：

| 内容 | 华为 | Cisco | 图上的写法 |
|---|---|---|---|
| 接口 MPLS 与 LDP | `mpls` + `mpls ldp` | `mpls ip` | `interface.mpls[_]` + `ldp = true` |
| LSR ID | `mpls lsr-id` | `mpls ldp router-id <接口> [force]` | `mpls.global.lsr_id` / `mpls.ldp.router_id_interface` |
| VPWS 伪线（D-0039） | 子接口上 `mpls l2vc … [secondary]` | 业务实例（或端口）下 `xconnect` + `backup peer` | 接入点下 `interface.access[…]/pw[primary\|backup]` |
| VPLS | `vsi` + `pwsignal ldp` + `vsi-id` + `peer`；桥域 `l2 binding vsi` | `l2vpn vfi context` / `l2 vfi … manual` + `vpn id` + `member` / `neighbor`；`bridge-domain` 下 `member vfi` | `l2vpn.vsi[…]`、`bridge_domain.vsi` |
| 标签分配 | `apply-label per-instance\|per-route\|per-nexthop` | `mpls label mode vrf X protocol bgp-vpnv4 per-vrf\|per-prefix\|per-ce` | `vrf.instance.af.label_mode`（per-vrf → per-instance、per-prefix → per-route、per-ce → per-nexthop） |
| ACL 源 / 目的（D-0040） | `source X W` / `source X 0` / 不写 | `X W` / `host X` / `any` | `source_ip` + `source_wildcard`（0 与 host 记为 0.0.0.0，不写与 any 记为 any） |
| ACL 类型 | `acl number 2000–2999` / `basic`、`3000–3999` / `advance` | `standard` / `extended`、编号 ACL 按命令格式 | `acl.instance.type` basic / advanced |

**依赖规则**：引用——伪线、PW 模板、VSI、VSI 对等体对隧道策略与 PW 模板的引用，接口 / 桥域对 VSI 的引用，接口、VTY、SNMP、NTP、路由策略对 ACL 的引用，规则对 VPN 实例的引用，VPN 实例对隧道策略的引用；前置条件（只在华为 Profile 生效）——全局 MPLS 需要 LSR ID、LDP 与接口 MPLS 需要全局 MPLS、伪线与 VSI 需要 `mpls l2vpn`、`mpls l2vpn` 需要全局 MPLS；跨设备——远端 LDP 对等体与伪线的对端地址应是对端的 LSR ID。配置检查因此能发现悬空 ACL（引用了不存在的 ACL）与孤儿 ACL：现网 ATN 样本 5 个 ACL 中 4 个被 SNMP / NTP / VTY 引用，`ACL_MCAST_SSM` 只被范围外的 `pim ssm-policy` 使用，判为 `ref.orphan_unsure`（不进清理脚本）。

**Profile 人工缺省值**：华为——LDP GR / 会话保护 / mLDP P2MP / 通告全部 Loopback 为否、`igp-sync-delay` 10 秒、接口 LDP 为否、PW 模板控制字为否、VSI 封装 vlan 与 MTU 1500、ACL 步长 5 与匹配顺序 config、VPN FRR 为否；Cisco——标签分发协议 ldp、LDP GR / 会话保护为否、会话保持 180 秒、VRF 标签分配 per-route（per-prefix）。两家默认值不同的节点（如标签分配：华为 per-instance、Cisco per-route）由 Profile 对比列出，供翻译告警。

**样本**：现网 ATN 样本中 `mpls lsr-id`、`mpls`、`mpls ldp`（全局与接口）、`mpls l2vpn`、`acl number` / `acl name` 与全部规则、桥域描述都成为命令（命令行 904 → 1151，原文行 1021 → 774，未识别 0）；剩下的 `mpls te`、`mpls rsvp-te` 等按原文保留。新增合成样本 `huawei-atn-v800r025-synthetic/atn-mpls-l2vpn-acl-01.cfg`、`cisco-iosxe-asr920-synthetic/pe-asr920-03-mpls-l2vpn-acl.cfg`（四个功能域都覆盖，登记为门槛样本）。全部 17 个样本往返逐字一致，门槛样本未识别行 0；Batfish 片段中原来是原文的 ACL 与 `ip access-group` 行成为命令，其中未定义的 ACL 引用如实报为悬空引用。

本阶段的通用改动：

| 改动 | 说明 |
|---|---|
| 单关键字命令卡 | 整条语法只有一个关键字的卡（华为接口下的 `mpls`、`shutdown`）不再登记为“已知前缀”：同前缀的范围外命令（`mpls te`、`mpls rsvp-te`）按原文保留，不算未识别行（`core/parser.py`） |
| 进入子视图后的分页痕迹 | 上一行刚进入子视图、本行异常缩进时，先当作子视图的第一行；子视图里匹配不到而外层匹配得到时按外层算（ATN 样本 `ipv4-family` 之后的 `ipv6-family`） |
| 映射表达式 | `if:$参数:表达式`（参数有值时才取）、`tail:关键字:截止词`、`$序号\|\|auto`（有序号用序号，否则按出现顺序编号） |
| 抽取规则 | 功能域文件条目的 `views_map` 中 `view: null` 表示命中即丢弃（只取一页里范围内的模式）；华为 `enters` 的 `^interface\b` 收紧为 `^interface( \|$)`（`interface-mtu check-mode` 不再进入接口视图） |
| 抽取合并编号（D-0044） | 先按“语法 + 视图”认领已有卡；编号被认领而内容不同的新卡在整个平台族内改用空闲的 `~N`，不再覆盖已有的卡或与其他功能域重号 |
| 修正文件 | Cisco 新增 18 条（ACL 条目的三种格式与编号标准 ACL、`mpls ldp discovery targeted-hello accept`、业务实例下的 `xconnect`、`member vfi`、`member <接口>` 等）；华为通过 `views_map` 与 `enters` 解决，没有新增修正 |

**遗留**：华为高级 ACL 的源端口与目的端口在命令卡里是同名参数 `port-number`，端口条件暂未映射（原文保留，往返不受影响）；华为编号 ACL 的类型由命中的命令卡（编号范围）决定，`acl name X number N` 被以编号 N 引用时还对不上；Cisco 的 `ip access-list <名称>`（不写 standard / extended）、`interface pseudowire` 写法未收；Cisco PW 控制字缺省是自动协商，没有写成布尔缺省值。

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

### 配置检查与冗余清理（M2-4 结果）

**模块**：`core/rules.py`（规则文件加载、校验、求值）、`core/checks.py`（检查与汇总）、`core/cleanup.py`（删除脚本与验证）；CLI `lmesh check`、`lmesh cleanup`，API `POST /check`、`GET /devices/{id}/check`、`POST /cleanup`、`GET /kb/rules`。

**发现的结构**：`rule`、`severity`（error / warning / info）、`domain`、`node`（规范编号）、`nodes`、`lines`、`message` 与 `suggestion`（文案键 + 参数）。内置检查的文案在 locales（`check.<规则>.*`），规则文件的文案随结果放在 `texts`，结果本身不随语言变化。

**内置检查**：

| 规则 | 级别 | 判断方法 |
|---|---|---|
| `ref.dangling` | error | 引用属性的目标不存在（建图时按 reference 依赖记录；Schema 标了 `ref` 却没有依赖规则的属性也检查）；Profile 声明的隐式对象作为派生节点存在，不算悬空 |
| `ref.dangling_unsure` | warning | 同上，但目标名称出现在未映射的行（原文、未识别行、未映射的命令）中，可能在那里声明 |
| `ref.orphan` | warning | 被引用的对象类型（Schema 的 `ref` 与 reference 依赖的终点，按知识库推导）的实例没有任何引用 |
| `ref.orphan_cascade` | warning | 只被孤儿（或级联孤儿）引用的对象，迭代到不动点 |
| `ref.orphan_unsure` | info | 没有引用，但名称出现在未映射的行或已映射行中未映射的参数里（例如 `nexthop recursive-lookup route-policy X`）；清理脚本不删除 |
| `dep.mutex` | error | 图中 mutex 依赖边两端同时存在 |

孤儿判断的保守规则：被别的对象以键使用算作使用（`bgp.af[vrf=X]`、按组名写的 `bgp.af.peer[Client]`、名称为“字母前缀 + 编号”的接口 `Vbdif100` 对应桥域 100）；已映射行中名称只作为对象的键或属性的取值出现时，由图中的边判断。

**规则文件**：`knowledge/rules/*.yaml`，每条规则有 `id`、`target`（Schema 对象节点）、`when`（可省）、`assert`、`severity`、三种语言的 `title` / `message` / `suggestion`。条件写成结构化 YAML（`exists`、`count`、`equals`、`in`、`all`、`any`、`not`），不用 eval；路径按 Schema 逐段走（`af/rt`、`group->remote_as` 沿引用边、`^` 上一级对象），加载时按 Schema 校验，写错时报出文件、规则编号与出错位置（例如 `assert.all[1].not`）。CLI 退出码 3，API 返回 409 与问题清单。`common.yaml` 有 8 条通用规则：对等体缺对端 AS（考虑组的 remote-as 与 IBGP 组）、接口绑定 VRF 无地址、二层口绑定 VRF、聚合成员口有地址、VRF 有 RD 无 RT、有 RT 无 RD、策略节点匹配的前缀列表为空、匹配的团体属性列表为空。早于 M2 复制出的运行时知识库没有 `rules/` 时用程序自带的规则。

**删除脚本**：只对对象的入口命令取反（子树中每个对象第一次出现的行，且不在子树其他行的视图之内），多个入口逐个删除；用命令卡的 `undo` 语法按原行的参数渲染，只接受关键字都在原行中出现过的展开，取参数最多的写法，并用取消语法回匹配校验；渲染不出来时用平台族的取消前缀 + 原命令兜底，标注 `fallback`。顺序按对象间的引用做拓扑排序（引用方在前），同层按行号；对象在视图里时先输出进入视图的原命令、缩进一级、再退出（华为 `quit`、Cisco `exit`）；`!` 注释行注明对象与原配置行号。同一条命令删除整个对象时（`no ip community-list standard X`）只输出一次。

**验证**：去掉待删除对象子树的全部行（含入口下的子行）后重新解析建图，比较悬空引用、确认对象已不存在且没有剩下的孤儿；反例（只删被引用的前缀列表）会报出新的悬空引用。

**样本基准**（人工确认均为真问题）：

| 样本 | 发现 | 判断 |
|---|---|---|
| 华为 ATN 真实配置 | `ref.orphan bridge_domain[1500]` | 真问题：两个 `.1500` 二层子接口都没有 `bridge-domain 1500` |
| | `ref.orphan_unsure rp.policy[VERIFICA-NEXTHOP]` | 正确降级：只被 BGP 的 `nexthop recursive-lookup route-policy` 使用，这条命令还没有映射 |
| Cisco ASR 920 合成样本 | `ref.orphan rp.community_list[RAN-COMM]` | 真问题：route-map 只 `set community`，没有 `match` 这个列表 |

Batfish 公开样本中的发现（未定义的 route-map / VRF 引用、没有 RT 的 VRF、未使用的 prefix-list 与 community-list、聚合成员口有地址）逐条核对过，都是样本本身的问题。

**知识库待补**：Cisco `route-map` 卡的取消语法把两种写法合在一起（必须带 `ordering-seq`），删除 route-map 节点只能兜底；华为 `nexthop recursive-lookup route-policy`、Cisco `ip prefix-list … description` 尚未映射；`bgp.af` 的键 `vrf` 与 `bgp.af.peer` 的键 `peer` 实际引用 VRF 与对等体组，Schema 没有标注（检查按键使用的规则兜底）。

### 配置对比（M2-3 结果）

模块 `core/compare.py`，CLI `lmesh compare`、API `POST /compare` 与 `GET /devices/{id}/versions` 共用。全部按 Schema 与图结构工作，不写死功能域：

| 环节 | 做法 |
|---|---|
| 规范编号 | 沿 contains 边重算每个对象 / 属性的编号：键字段按类型规范化（类型取 `<对象>.<字段>` 子节点的类型；对象自身就是取值类型时（`interface`）按该类型；没有子节点的键字段，同名 ref 属性都指向同一类型时按引用处理，如 `bgp.af` 的 `vrf`） |
| 有效值 | 显式值，否则图中 Profile 补出的默认节点或派生节点；`undo` / `no` 取消非布尔属性时回到 Profile 默认值，没有默认值时视为未配置；两边各用自己的 Profile。只有一侧 Profile 有默认值、另一侧什么都没有的属性不可比，列入 `default_only`，不算差异 |
| 语义等价 | 掩码 → 长度、`ip/掩码` 与 `ip 掩码` → 前缀、接口名缩写与大小写（GE / Gi / gigabitethernet → GigabitEthernet，LoopBack → Loopback）、RD / RT（asdot → asplain、去前导零）、枚举不分大小写、单元素列表等同标量、无序列表排序；复合键中取值 `both` 的枚举字段（choices 恰为另外两项加 both）展开成两个对象，等同分开写的 import + export |
| 有序 | 有序列表（Schema `ordered`）按键（序号）配对，同一序号内容变化即差异，书写顺序不影响；属性的列表值只有标了 `ordered` 才比较顺序 |
| 改名 | 被 ref 指向的单键对象类型，只在一边出现、同一父对象下、除名字外内容（子树属性的相对编号与有效值、未映射命令）相同的唯一配对判为改名；有并列候选或内容为空时不判定；相似度阈值默认 1.0，可按次指定；A 侧按改名映射重算（对象名、ref 属性、引用型键字段、未映射命令中等于旧名的参数），逐轮识别引用链上的改名 |
| 未映射命令 / 原文 | ext 节点只在同一平台族时比较，按所属对象作为多重集合（一对一时报 changed）；原文行（选项开启）按所属对象比较“父原文行 > 本行”的集合，异常缩进形成的分隔行（`#` / `!`）忽略；未识别行单独列出 |
| 输出 | 只在一边出现的对象只在最上层报一次（附子节点数与整块行号）；关联差异由两边图中的引用边得出 |

**对比基准**：`knowledge/samples/compare/manifest.yaml`，16 个用例全部通过（`compare.benchmark()`，测试分类 roundtrip）——ATN 与 ASR 920 各自的自身对比、重排、显式默认值、缩进与空白、掩码写法（ATN）、接口名缩写、RT both 为 0 差异；真实修改（改 MTU、删对等体、改 RT、改名 route-policy 并更新引用，ASR 920 另有 prefix-list 的两级改名）只报预期差异。往返样本清单检查排除 `samples/compare/`（基准有自己的清单）。

**发现的建图问题**：华为 `ipv4-family mvpn`、`ipv6-family vpnv6` 两个视图未映射，其中的 `peer … enable` / `peer … group` 被记到 `bgp.af[afi=ipv4,vrf=]` 的对等体上（ATN 样本 `peer[10.0.179.30]/enabled` 的行号含 1983、2042）；这两个地址族的增删在对比中会表现为 IPv4 单播地址族的变化。ext 节点编号含行号（`ext[卡@行号]`），对比不用它配对（按所属对象与命令卡分组）。

### 对比视图、检查界面、冗余清理与报告导出的后端（M2-5 结果）

| 功能 | 模块 | CLI / API |
|---|---|---|
| 隐藏身份差异 | `core/compare.py` 的 `hide_identity` | `lmesh compare --hide-identity`；`POST /compare` 的 `hide_identity` |
| 规则开关与级别 | `core/rule_edit.py`、`core/checks.py` 的 `load_overrides` | `lmesh rules list\|set`；`GET /kb/rules`、`PUT /kb/rules/{id}` |
| 忽略检查发现 | `core/ignores.py`、数据表 `check_ignores`（迁移 `0002`） | `lmesh ignore list\|add\|remove`；`GET` / `POST /check/ignores`、`DELETE /check/ignores/{id}` |
| 按对象清理 | `core/cleanup.py` 的 `objects` 与 `select` | `lmesh cleanup --object`；`POST /cleanup` 的 `objects` |
| 报告导出 | `core/report.py` | `lmesh report compare\|check`；`POST /reports`（直接返回文件） |

**身份差异**（决策 D-0026、D-0027）：清单是 `core/compare.py` 的模块常量，Schema 中不存在的节点自动忽略，生效的清单在结果 `options.hidden_identity` 返回。属性：`bgp.instance.router_id`、`ospf.process.router_id`、`bfd.session.peer`、`mgmt.snmp.location`；对象（新增 / 删除）：`interface.ipv4`（以地址为键）、`bgp.peer`、`isis.process.net`，`bgp.af.peer` 只在键是 IPv4 地址时算；原文行：`sysname` / `hostname`。只过滤结果，不改配对与改名识别；被隐藏的差异放在 `hidden_diffs`，个数为 `summary.hidden_identity`，`equal` 与 `summary` 按剩下的差异计算。

**规则开关与级别**：知识库规则在所在的规则文件里改 `enabled` / `severity`（ruamel 往返写回，保留注释与顺序）；内置检查写入覆盖文件 `rules/builtin.yaml`（`builtin: {规则: {enabled, severity}}`，规则加载时跳过这个文件，写错时与规则文件一样报出问题清单）。修改在知识库写锁内完成，写后重新加载全部规则校验，出错时恢复原文件；成功后提交运行时知识库（提交说明“修改检查规则 <编号>：…”）。运行时知识库没有 `rules/` 时先复制程序自带的规则。规则列表每条带 `source`（`builtin` 或文件名）、`enabled`、`severity`，内置检查另有 `default_severity`；停用的内置检查不产生发现。

**忽略检查发现**（D-0028、D-0029）：表 `check_ignores`（`device_id` 外键级联删除、`rule`、`node`、`reason`、`created_at`），按（设备、规则、节点）唯一，重复提交时更新原因；原因必填。按设备检查时（API 的 `device_id`、CLI 的设备名）合并忽略记录：发现带 `ignored`、`ignore_reason`、`ignore_id`；`summary.total` 含被忽略的，`summary.ignored` 为个数，按级别、规则、功能域的计数与 `has_errors`（CLI 退出码）不含被忽略的。迁移 `0002_check_ignores` 在 SQLite（batch 模式）与 PostgreSQL 上都测试过升级。

**按对象清理**（D-0032）：`objects` 给出时只删选中的孤儿；只被选中对象引用的级联孤儿随之删除；只选级联孤儿而引用它的对象仍在时跳过（`parent_kept`，附 `via`），不是孤儿的跳过（`not_orphan`），名称出现在未映射行中的跳过（`maybe_referenced`）。验证时，删除前就是孤儿、这次没选中的对象不算新孤儿。每条命令带 `fallback_reason`：`no_undo`（命令卡没有取消语法）、`undo_invalid`（取消语法写错）、`render_failed`（用原行参数渲染不出）、`match_failed`（回匹配失败）。`GET /devices/{id}/check` 支持 `version_id` 检查指定版本。

**报告**（D-0030）：只排版 core 已算好的结果，不重新计算结论。正文只有中文与英文（文案在 `core/report.py` 的 `TEXTS` 表），界面语言是 pt-BR 时用英文。HTML 是自包含单文件（内联样式、明亮配色、`@media print` 分页时表头重复、行不拆开），Markdown 是表格（单元格中的 `|` 转义）。报告头写设备、配置版本（编号与采集时间）、软件版本、Profile、知识库版本、生成时间与选项。对比报告：概要、按功能域分表的差异（类型、节点与关联、两侧有效值 + 来源 + 原文行号；对象附子节点数），单列改名、不可比（default_only）、未识别行，隐藏身份差异时注明个数。检查报告：按严重度分组（规则、功能域、节点、行号、说明、建议），被忽略的单列并写原因，有未被忽略的孤儿时附清理脚本与验证结论。文件名 `compare-<A>-<B>.<lang>.<ext>`、`check-<设备>.<lang>.<ext>`；`Content-Disposition` 同时给 ASCII 文件名与 `filename*`（UTF-8）。

### 参数化模板与批量生成（M3-4 / M3-5 结果）

| 功能 | 模块 | CLI / API |
|---|---|---|
| 模板格式、加载与校验、取值检查、正文渲染 | `core/template.py` | `lmesh template list\|show\|save`；`GET /templates`、`GET` / `PUT /templates/{id}` |
| 约束匹配与变量提取 | `core/template_match.py` | `lmesh template check\|extract`；`POST /templates/check`、`POST /templates/extract` |
| 模板制作辅助 | `core/template_draft.py` | `lmesh template draft`；`POST /templates/draft` |
| 批量生成 | `core/template_gen.py` | `lmesh template generate`；`POST /templates/generate` |

**模板文件**（`knowledge/templates/<编号>.yaml`，运行时知识库没有 `templates/` 时用程序自带的，保存时先复制）：元数据 + 变量 + 块 + 带占位符的配置正文。

| 字段 | 说明 |
|---|---|
| `id`、`version`、`title` / `description`（三语） | 编号只能是字母数字开头、可含 `_ . -` |
| `profile` | 解析模板正文、生成配置用的 Profile；`profiles` 为适用的 Profile（省略时同一平台族都适用，不适用时结果中给出提示，不算错误） |
| `match.extra` | `allow`（模板外的配置只列出，级别 info）/ `deny`（算不符合，级别 error），默认 `allow` |
| `match.extra_scope` | `none` / `matched`（只看模板对上的对象下面，默认）/ `domains`（另外包括模板涉及的功能域中的顶层对象） |
| `vars.<名>` | `type`：`ipv4`、`prefix`、`integer`、`vlan`、`asn`、`rd`、`enum`、`interface`、`word`、`text`；可选 `default`、`example`、`min` / `max`、`choices`、`pattern`（整串匹配）、`length`（前缀长度或 `[最小, 最大]`）、`within`（必须落在这些网段内）、`network`（主机位为 0）、`title`；`expr` 为派生变量（如 `gw: {expr: "lan\|host(1)"}`） |
| `blocks.<名>` | `repeat: {min, max}`（重复块）或 `optional: true`（可选块）；块变量写在块的 `vars` 下，可加 `unique`（各实例取值不同）；`anchor` 指定识别实例用的 Schema 对象 |
| `body` | 配置正文：占位符 `{{名字}}`、`{{名字\|过滤器\|…}}`，块变量写成 `{{块名.变量}}`；块用独占一行的 `{% repeat 名 %}` / `{% optional 名 %}` 开始、`{% end %}` 结束，不能嵌套；同一个块可以出现在正文多处（每个业务既有 VRF 定义、又有子接口和 BGP 地址族），各处按同样的实例展开 |

过滤器：`ip`、`network`、`len`、`mask`、`wildcard`、`broadcast`、`host(n)`（网段第 n 个地址，负数从广播地址往回数，`host(-1)` 是最后一个可用地址）、`add(n)`（整数或 IPv4 地址加 n）、`upper`、`lower`。一行参数（生成的输入、提取的输出）：`{"device": …, "变量": 值, "重复块": [{"变量": 值}, …], "可选块": true | false | {"变量": 值}}`；CSV 的表头是 `device`、基础变量、可选块名（true / false）、`块名.变量`，重复块的取值用分号分隔。

**约束匹配**（全部在图上按有效值比较，不做文本比较）：

| 环节 | 做法 |
|---|---|
| 编译 | 每个变量按类型取互不相同的探针值（同一行中探针值与固定文字冲突时换一组），渲染整份正文（重复块一个实例、可选块都带上），解析、建图，用配置对比的规范化得到规范编号与有效值；再为每个块渲染“去掉这个块”的正文，两次结果不同的节点（不存在、只剩默认值或取值不同）属于这个块。每个显式节点变成一个模式：对象的键、属性的有效值中出现的探针值（只看该节点所在行用到的表达式，掩码、接口名缩写等写法都认）换成变量，其余是固定值；Profile 补出的默认节点不进模式。编译结果按模板内容与知识库缓存 |
| 匹配 | 沿 contains 层级：父模式对上实际对象后在它下面找子模式；属性按有效值比较（实际配置没写时用 Profile 默认值，所以模板写了等于默认值的命令、配置里不写也符合）；同一层先匹配键里未绑定变量最少的对象；一个对象模式能对上多个实际对象时（例如 `{{uplink}}`）先试探每个候选下面能对上多少模式，取最多的；并列且绑定不同时报 `ambiguous`（并列的候选最后都被别的模式对上时不报，例如两个 RR） |
| 块 | 基础部分先匹配，再按块：重复块的锚点（键里含本块变量的对象，优先 `unique` 变量、基础变量与固定文字多的，或 `anchor` 指定的）在实际配置中的每个匹配是一个实例；锚点键里有只在块中出现的基础变量（L2 模板的 `{{port}}`）时，按它的取值分组取能对上最多的一组；可选块有匹配就算出现。实例个数不在 `min`～`max` 之内报 `count` |
| 变量反推 | 捕获的是表达式的值：直接的变量取值；`prefix` 由 `host(n)` / `ip` / `network` 加 `mask` / `len` 反推；`add(n)` 反减；然后每个表达式用反推出的变量重新计算，与捕获值逐个验算（派生关系不成立报 `inconsistent`），再按类型与约束检查（报 `constraint`），`unique` 跨实例检查 |
| 模板外的配置 | 没有被任何模式对上的显式节点，只在最上层报一次（对象附子节点数与整块行号）；显式写出、等于 Profile 默认值的属性不算；未映射的命令（ext）在模板对上的对象下面才报；跨平台族时未映射的命令与原文行不比较（给出提示） |

**结果**：`compliant`、`variables`（基础变量与派生变量）、`blocks`（重复块为实例列表，含 `_node` 锚点与 `_lines` 行号；可选块为 true / false 或变量）、`row`（可直接作为生成参数的一行）、`unresolved`、`findings`、`notes`、`warnings`、`summary`（`patterns`、`matched`、`by_kind`、`by_severity`、`instances`、`extra`）。每条发现：`kind`（`missing` 缺少、`value` 取值不符、`inconsistent` 前后不一致、`constraint` 违反约束、`count` 实例个数、`ambiguous`、`extra` 模板外）、`severity`、`block` / `instance`、`node`（模板中的模式，探针值写成 `{表达式}`）、`node_kind`、`schema`、`domain`、`actual_node`、`expected`、`actual`、`actual_origin`、`var`、`problem`（约束的文案键）、`count`、`parent`（缺少时在哪个实际对象下面找的）、`lines`（实际配置行号）、`template_lines`（模板正文行号）。文案在 locales（`template.finding.*`），结果本身不随语言变化。CLI `check` 不符合时退出码 1；模板有问题时 CLI 退出码 3、API 409 与问题清单（`where`、`key`、`args`）。

**模板制作辅助**：以第一份配置为基准，按规范编号对齐其他配置的对象与属性（编号不同的对象在同一父对象、同一 Schema 下按内容相似度配对，未映射命令与原文行按所属对象与命令卡 / 首个词配对），对上的行逐词比较，取值不同的词是候选变量；各设备取值完全相同的位置归为同一个变量；接口名只去掉共同的接口类型前缀或到子接口点为止的前缀（`Vbdif1584` / `Vbdif1585` → 1584，`GE0/2/0.1584` → 1584），其余整词作为变量。变量名按所在节点的 Schema 建议，类型按取值推断。只有一份配置时，设备身份（对比的 IDENTITY 清单：主机名、Router ID、接口地址、对等体地址等）与描述作为候选。只在部分设备上出现的对象列为可选块候选，同一父对象下内容相似的兄弟对象列为重复块候选（只给建议，不改写正文）。输出模板草稿（YAML 文本）、变量表（每台设备的取值与依据的节点）、参数表，并用草稿校验每份源配置（`verify`：应当符合、提取出的变量与参数表一致）。哪些值真正应该是变量由人确认，AI 可在此基础上建议（M5 接入）。

**批量生成**：参数先按类型规范化、补默认值、检查约束（未知列、派生变量给了值、块各列个数不同、实例个数、`unique` 都报出）；`engine: text` 按正文替换，`engine: canon` 先替换再建图、交给规范渲染器 `core/canon.py` 的 `render_full` 输出（可用 `target_profile` 生成另一平台族的配置，渲染器写不出的节点作为错误报出）。每行验证：未识别行为 0、往返逐字一致、按模板校验符合且提取出的变量与输入一致（生成到另一平台族时不按模板校验）；任何一项不通过这一行算失败。文件名 `<设备名>.cfg`，重名时加序号；CLI `--out-dir` 只写成功的行，有失败的行时退出码 1。

**示例模板**：

| 模板 | 内容 | 验证 |
|---|---|---|
| `cisco-asr920-efp-bdi-vrf` | ASR 920 接入 PE：上联口（`uplink_net\|host(2)`）、Loopback（`within` 约束）、到两个 RR 的 VPNv4；每个业务一个 EFP + BDI（网关 `lan\|host(1)`）+ VRF（RD / RT = `asn:rt`）+ BGP VRF 地址族 | 合成样本 `pe-asr920-01.cfg` 报出 1 处错误（BDI102 缺描述）与 5 处模板外的配置（RAN-2G 多一条 import RT、上联口描述、EFP 描述、IPv4 单播地址族、RAN-2G 的 redistribute static） |
| `huawei-atn-l2-bd-vbdif` | ATN 二层接入：桥域 + Vbdif（网关 `lan\|host(-1)`）+ 二层子接口，`{{port}}` 只在块中出现 | 现网 ATN 样本：识别出 GE0/2/0 下 10 个业务，报出 4 个 Vbdif 没有绑定 VPN 实例、8 个网关不是最后一个可用地址（都是样本中真实存在的差异） |
| `huawei-atn-l3vpn-subif` | ATN 三层接入：VPN 实例（RD = RT）+ dot1q 子接口 + BGP VPN 地址族 | JSON 参数表生成 2 份，全部通过；`engine: canon` 生成到 ASR 920 时报出渲染器写不出的节点（`label_mode`、`dot1q_termination`） |

**已知限制**：块不能嵌套（业务下再分可选项时拆成两个块）；重复块实例之间允许共用非锚点对象（两个业务指向同一 VRF 时不报错）；模板制作辅助不自动改写为块，变量名是建议名；参数表不支持 Excel（CSV 与 JSON）；模板编辑与校验的界面随 M3-6 实现。

### 配置翻译与规范渲染（M3-3 结果）

| 功能 | 模块 | CLI / API |
|---|---|---|
| 规范模式渲染、含默认值的完整配置 | `core/canon.py`（`render`、`render_full`、`result_dict`） | `lmesh render --canonical [--with-defaults]`；`POST /render` 的 `canonical`、`with_defaults` |
| 配置翻译与告警 | `core/translate.py`（`translate`、`translate_text`） | `lmesh translate <配置\|设备> --to <Profile> [--interface-map] [-o]`；`POST /translate` |
| 平台族书写习惯 | `knowledge/render/<平台族>.yaml` | — |
| 回归 | `knowledge/samples/translate/manifest.yaml`、`tests/roundtrip/test_translate.py` | `pytest -m roundtrip` |

**生成方向的知识**（决策 D-0050～D-0056）：不另写“Schema 节点 → 命令”的模板，而是由命令卡 + 映射规则反推，生成后校验：

| 环节 | 做法 |
|---|---|
| 候选命令卡 | 目标平台族中，当前视图里映射到该 Schema 节点的命令卡（按视图 + 节点建索引；`avoid` 中的卡不用） |
| 反解表达式 | 对象的键与 anchor 自己的取值必须表达，卡上其他属性能顺带写出就写（贪心），写不出就不写；`$参数` → 参数取值（按参数类型换写法：掩码长度 ↔ 点分掩码、通配符；有空格的取值拆成重复组），`a\|\|b` → 任一备选，`fmt:` → 按模板拆开（只给了前几个占位时依次去掉末尾的占位），`kw:` → 需要出现的关键字（等于缺省值时也可以不写），`flag` → 正 / 取消形式，`if:` → 关键字出现与否，`tail:` → 关键字后的全部词，常量 → 必须相等；不在 anchor 所在链上的对象及其属性必须取不到值 |
| 按语法生成 | 可选部分：含需要的关键字或已有取值的参数时写；多选一：含需要的关键字的分支优先，其次参数有值的、纯关键字的；重复组按列表展开；重复的多选一（`[ a \| b ] &<1-N>`）每个需要的选项各写一次；enum 参数的选项正好是需要的关键字时用它；取消形式用命令卡的 undo 语法，没有时用“取消前缀 + 开头关键字” |
| 校验 | 每个候选行交给解析器在同一视图中匹配（解析器选中的卡可能不是生成用的卡），按映射规则求值：对象的键、固定键、所在父对象（必须在上下文或同一行中）、属性的有效值都与图一致才采用；顺带写出的、图中没有的取值只允许是 false 或目标 Profile 的默认值 |
| 选择 | 覆盖待写节点多的优先；其次不把默认值写成显式的、同平台族时原来用的卡、取值写全的（`route-map X permit 10` 而不是 `route-map X`）、命令卡状态高的、文本短的；`prefer` 可指定某个节点优先用的卡 |

**结构**：对象有入口命令（进入视图的卡）时写成块，块内写它的属性与子对象，块里写不出、外层视图能写的先写在块前；多张卡进入不同视图时（华为 `vpn-instance X` 与 `ipv4-family vpn-instance X`）选块内能写出最多节点的视图。没有入口命令的对象由属性行顺带给出键；有“只给键”的声明卡（Cisco `neighbor RR peer-group`、华为 `group RR internal`，判定：唯一的对象目标、键来自参数、其他目标不用参数）且一行写不全时先写声明行。属性行进入子视图时（华为 `pwsignal ldp` → VSI-LDP 视图），同一对象只能在子视图里写的属性接着写在它下面；本层写不出的子对象试着写进兄弟对象的块里（Cisco 的 `backup peer` 写在 `xconnect` 块中）。同一层按依赖排序（引用 / 前置边：被引用的先出现），其余按原始行号。华为 `#` 分隔顶层块、`return` 结尾，Cisco `!` 与 `end`；块内第一层子块前加 ` #` / ` !`；Cisco 离开 `vrf-af`、`bgp-af` 写 `exit-address-family`（`exits`）。

**同平台族**：未映射命令（ext）、功能域外原文（raw）、未识别行按原文写回原来的位置（父行是入口命令时写在对象块内；父行是生成的语义行时挂在那一行下面；父行是原文时嵌在原文下面）；只由取消形式产生、没有属性的对象（Cisco `no aaa new-model`）按原文写回。反推不出命令的节点（带密文的 `local-user … password irreversible-cipher`、`hwtacacs-server shared-key cipher`、`username … secret`）按原文写回（行的 `kind` 为 `original`），跨平台族时报不支持。

**含默认值的完整配置**（`include_defaults`）：Profile 补出的默认值节点（origin=default）也写成命令，集中放在所在块的显式行之后，前面加一行注释 `! default`（与块内缩进相同；华为、Cisco 都把 `!` 开头的行解析为注释，重新解析不影响图）；逐行结果的 `origin` 为 `default`，`default_lines` 为行号。写不出命令的默认值（例如 Cisco 没有映射 BGP 计时器）不报错，列在 `uncovered`。

**翻译**：

| 情况 | 处理 |
|---|---|
| 接口名 | 按映射表改写对象键（`interface`、键字段名为 `interface` 的对象）与接口类型的属性取值，子接口按父接口映射；映射表的值按原样写出；没给映射表时同名，接口类型不在目标平台族的 `interface_types` 中时告警 `interface_type` |
| 源依赖默认值、目标默认值不同 | 显式写出，告警 `default_differs`（`src_default`、`dst_default`） |
| 源依赖默认值、目标没有登记默认值 | 不写，提示 `default_unknown`（level info） |
| 两边默认值相同 | 不写（`stats.defaults_same`） |
| 源显式值等于目标默认值 | 省略，`defaults[]`（`explicit_equals_default`） |
| 目标 Profile 不支持 | `unsupported[]`（`reason: profile_unsupported`），对象的子树都不写 |
| 写不出命令 | `unsupported[]`（`reason: no_render`，所属对象已报时子节点不再列出，`count` 为子节点数） |
| 密码类取值（Schema 节点名为 `password` / `secret`，跨平台族） | 不写，`unsupported[]`（`reason: secret`）：源平台的密文或脱敏占位不能在另一平台直接使用，人工重新设置 |
| ext / raw / unknown / 取消形式的对象 | 不翻译，`unsupported[]`（`kind` 为 `ext` / `raw` / `unknown` / `negated`，原文块只列第一行，`lines` 为整块行号） |
| 目标写法必须给出、源配置没有的取值 | 按 `infer` 推导规则写出并告警 `inferred_value`（华为 `group <名> internal\|external`：remote-as 等于本地 AS 时 internal，否则 external） |
| 目标隐式存在的对象 | 不写（ASR 920 的桥域被引用即存在）；没有被引用时提示 `implicit_object` |

每一项都有 `kind`、`key`（文案键，三语文案在 locales 的 `translate.*`）、`params`（文案参数，含 `node`、`schema`）、`node`（源图中的节点）、`lines`（原文行号）。**校验**：译文用目标 Profile 解析建图，与源图按有效值对比（跨厂商 + 接口映射）；差异的源节点（或其祖先）不在告警 / unsupported 中时记为 `verify_diff`，译文有未识别行时记为 `verify_unknown`；CLI 在有未解释的差异时退出码 1。

**回归**（`knowledge/samples/translate/manifest.yaml`）：同平台族规范渲染等价——全部 gate 样本（ATN 现网、ASR 920 合成三份、ATN 合成两份、Batfish 九份）与 `atn-l3vpn-synth.cfg`，规范渲染与含默认值两种方式重新解析后与原图对比（含原文行）都是 0 差异、不新增未识别行；翻译 8 个用例（ATN 现网 → ASR 920、ASR 920 → ATN、ATN 合成 L3VPN → ASR 920、IGP / 管理面双向、MPLS / L2VPN / ACL 双向、Batfish → ATN）全部 `verify.unexplained = 0`、译文没有未识别行，写出比例 0.72～0.97（下限写在清单中）。

**已知限制**（多数是映射两边不对称，由知识库补映射解决，渲染器不用改；前四项已在“知识库补缺（M3 收尾）”解决）：华为二层子接口（接入点键 `_`）与 ASR 920 业务实例（按编号）结构不同，互译时接入点报不支持；Cisco 接口视图没有 `encapsulation dot1q` 的映射（`dot1q_termination` 写不出）；Cisco `set community` 只有单值语法；`mgmt.line.auth` 两边语义不同（华为认证方式、Cisco 认证列表名），图上相等但含义不同；ATN 的 `100GE` 接口名不符合 Cisco 的接口参数类型，需用映射表；同一对象只能由一张入口命令进入（华为 BGP 的 `vpn-instance X` 与 `ipv4-family vpn-instance X` 合成一个块）。

### 知识库补缺（M3 收尾）

补齐配置翻译暴露出的知识库缺口（决策 D-0073～D-0076）。翻译回归的写出比例（写出节点 / 要写出节点）：

| 用例 | 补缺前 | 补缺后 |
|---|---|---|
| ATN 现网 → ASR 920 | 1732 / 1939（0.893） | 1747 / 1889（0.925） |
| ASR 920 → ATN | 121 / 135（0.896） | 136 / 138（0.986） |
| ATN 合成 L3VPN → ASR 920 | 111 / 115（0.965） | 115 / 116（0.991） |
| ASR 920 IGP / 管理面 → ATN | 91 / 116（0.784） | 89 / 114（0.781） |
| ATN IGP / 管理面 → ASR 920 | 68 / 89（0.764） | 70 / 89（0.787） |
| ASR 920 MPLS / L2VPN / ACL → ATN | 142 / 190（0.747） | 173 / 191（0.906） |
| ATN MPLS / L2VPN / ACL → ASR 920 | 168 / 214（0.785） | 174 / 212（0.821） |
| Batfish → ATN | 84 / 91（0.923） | 86 / 91（0.945） |

全部用例 `verify.unexplained = 0`、译文没有未识别行；清单里的下限 `min_rendered` 按补缺后的结果调高。分母变化来自：接入点换结构后二层子接口的 `l2` 与描述并入接入点、SNMP 团体字按敏感取值整棵不写（IGP / 管理面用例的分子分母都少了团体字）、新增的 BGP 计时器与线路认证列表节点。

| 缺口 | 做法 |
|---|---|
| 接入点结构（华为二层子接口 ↔ Cisco 业务实例） | 映射表达式 `ctx:subif`（上下文中接口的子接口编号，主接口为 `_`）：华为接口视图的封装、rewrite、桥域、`mpls l2vc` 与 Cisco 接口视图的 `xconnect` / `backup peer` 都按它给接入点编号，Cisco 业务实例按实例编号——两家接入点编号一致。形态写在 `knowledge/render/<平台族>.yaml` 的 `access_form`（华为 `subinterface`、Cisco `instance`），翻译时 `translate.reshape_access` 换结构：二层子接口 `P.N`（或终结 VLAN 的子接口上的伪线，`vlan-type dot1q V` → 接入点 `encapsulation dot1q V`）→ 父接口 `P` 下的 `service instance N`，子接口描述 ↔ 接入点描述；反方向写成 `interface P.N mode l2`。只承载接入点的接口（只剩默认值、未映射命令或原文）一并去掉。校验时把源图按目标形态换结构后再对比（单向换，不要求互逆）。解析图仍按配置的真实层级，同平台族往返与对比不受影响 |
| 华为 `interface … mode l2` | 原文把关键字 mode 排成参数，修正文件改为 `… mode l2`（写得出二层子接口） |
| Cisco 子接口 `encapsulation dot1Q N` | 公开文档只有 QinQ 写法且模式写成 config-ifsub，修正文件补卡 `cisco-iosxe.subif-encapsulation-dot1q` → `interface.dot1q_termination` |
| Cisco `set community` 多值 | 修正文件改为 `set community { { <community-number> } &<1-32> [ additive ] \| none }` |
| BGP 计时器 | 新增 `bgp.instance.keepalive` / `hold`（华为 `timer keepalive … hold …`，Cisco `timers bgp`，两家默认 60 / 180）；Cisco `neighbor … timers` 修正排版（`<p> <eer-group-name>`）后映射到对等体 / 组的计时器 |
| `bgp log-neighbor-changes` | 华为没有实例级命令、默认记录（Profile 人工缺省 true）：Cisco 显式开启译到华为时省略并说明，华为译到 Cisco 时按默认值不同显式写出并告警 |
| 伪线承载方式 | Cisco `xconnect … encapsulation mpls \| l2tpv3` 改映射到新节点 `interface.access.pw.transport`（两家默认 mpls），`interface.access.pw.encapsulation` 只表示华为 raw / tagged |
| VRF 标签分配、NTP 服务器源接口 | 规范渲染的表达式反解支持 `if:$参数:表达式`（`mpls label mode vrf X …` 写得出）；Cisco `ntp server … source` 补映射，华为 `source-interface` 的占位名写错（`interface_number` → `interface_num`）一并改正 |
| `mgmt.line.auth` 语义 | 拆成 `auth`（认证方式：aaa / password / none / local / tacacs）与 `auth_list`（AAA 方法列表名，两家默认 default）；Cisco `login authentication X` → `auth = aaa` + `auth_list = X`，`login [ local ]` → password / local |
| 敏感取值 | Schema 节点可以标 `secret: true`（取值或对象键是敏感内容）；翻译跨平台族时与名称为 password / secret 的节点一样拦截（`unsupported[]`，`reason: secret`）。已标：`mgmt.snmp.community`（团体字是对象键，整棵子树不写，只剩空壳的 `mgmt.snmp[_]` 也不写）、BGP / LDP 密码。TACACS / RADIUS 共享密钥、NTP 认证密钥、OSPF / IS-IS 认证密码在图上只有“已设置”或编号、认证方式，没有取值，跨平台族不会带出密文 |
| 书写习惯即时生效 | `knowledge/render/` 计入知识库缓存签名（`analysis._signature`），改书写习惯后下一次请求重新加载 |
| 华为高级 ACL 端口 | 修正文件把 TCP / UDP 规则卡里同名的 `port-number` 拆成 `src-port-op`、`src-port`、`src-port-begin`、`src-port-end`（目的端口同理），映射成与 Cisco 一致的 `eq 22`、`range 1000 2000` |
| `acl name X number N` 按编号引用 | Schema 属性可以标 `alias: true`：取值登记为所属对象的另一个键，`acl.instance.number` 已标，按 N 引用不再是悬空引用 |
| Cisco `ip access-list <名称>` | 修正文件补卡（不写 standard / extended），按扩展 ACL（`type = advanced`）处理 |

**仍未解决**（结构或平台能力不对等，列为不支持）：华为 `mpls l2vc pw-template X <vc-id>`（对端地址在 PW 模板里，Cisco `xconnect` 必须写对端）；华为 VSI 的 LDP 信令 / 封装 / MTU、隧道策略、`mpls lsr-id`（Cisco 只有 LDP router-id 接口）、OSPF network 描述、桥域描述、SSH 用户、AAA 域与方案；Cisco 命名的 `l2vpn xconnect context`、IS-IS 进程名（华为要求数字）、接口下的 `mpls ldp igp sync`；接口 `speed`（Cisco 没有对应命令卡）。

### 拓扑还原与跨设备一致性（M4-6 结果）

**输入**：多台设备的配置图——已导入设备的最新配置版本（按名称或编号），或一批配置文件 / 上传的配置文本（设备名取 `sysname` / `hostname`，没有时用文件名，重名加 `#2`）。全部推导由代码在图上计算（`core/topology.py`），不用 AI。

**链路类型与推导规则**（每条链路记录两端设备、接口、地址、端点节点、事实 `facts`，以及推导依据 `basis`（规则、两端节点、说明）与置信度 high / medium / low）：

| 类型 | 规则 | 说明 |
|---|---|---|
| `subnet` | `subnet.p2p` / `subnet.same_network` / `subnet.mask_overlap` | 同网段接口（VRF 内与公网分开，排除 Loopback 与 /32）。/30、/31 且只有两端为 high；多点网段两两成链为 medium；只有一端的掩码包含对端地址为 low；任一端 shutdown 降为 low |
| `ospf` | `ospf.both_enabled` | 同网段链路两端都在 OSPF 中启用：接口下的区域，或进程（同 VRF）下 network 语句覆盖接口地址（最长匹配）；区域统一成点分写法；静默按进程缺省 + 接口例外计算 |
| `isis` | `isis.both_enabled` | 两端接口都启用 IS-IS；可用级别 = 进程级别 ∩ 电路类型 |
| `ldp` | `ldp.both_enabled` | 两端接口都使能 MPLS LDP |
| `ldp_remote` | `ldp.remote_peer_lsr_id` | 远端对等体地址是另一台设备的 LSR ID / Loopback |
| `bgp` | `bgp.peer_address` / `bgp.peer_address_one_sided` | 对等体地址落在另一台设备的接口 / Loopback 上；本端地址取 update-source / connect-interface（对等体或对等体组），没有时取同网段接口；对端 AS 取对等体、对等体组，internal 组取本地 AS；地址族取全局地址族中使能的（对等体或所属组） |
| `pw` | `pw.peer_lsr_id_vc_id` / `pw.peer_lsr_id_vc_mismatch` / `pw.peer_lsr_id_one_sided` | 伪线（华为 l2vc 含 pw-template 的 peer-address、Cisco xconnect / l2vpn xconnect、VSI / VFI 对等体）对端 = 对端设备 LSR ID；两端 VC ID 相同为 high；两台设备之间只剩一对没配上的同类伪线时按 VC ID 不一致配对（low） |
| `bfd` | `bfd.session_peer` / `bfd.interface_both` | 静态会话对端是另一台设备的接口地址（mode static）；同网段链路两端都有接口 BFD 参数（mode interface） |

对端不在这批设备中的对等体 / 伪线 / 会话列在 `unresolved`；同一 VRF 中同一地址出现在多台设备上（含 Loopback）列在 `duplicates`。LSR ID 取 `mpls lsr-id`，没有时取 LDP router-id 或其接口地址。

**跨设备依赖边**（`cross_edges`）：按 Schema deps 中 `kind: cross_device` 的规则生成（遵守规则的 `profiles`）。源与终点类型不同时，源节点取值（对象取键）等于另一台设备上终点类型节点的取值即连边（默认节点不参与）；源与终点类型相同（`interface.ospf.area`）时在同网段链路两端之间连边。目前的规则：BGP 对等体 → 接口地址、BFD 会话对端 → 接口地址、伪线对端 → LSR ID、远端 LDP → LSR ID、接口 OSPF 区域 ↔ 接口 OSPF 区域（只有接口下写了区域时才有节点）。

**一致性规则**（`knowledge/rules/cross-device.yaml`，新建；`lmesh check` 不读它——`rules.NOT_RULE_FILES` 跳过）：在 `core/rules.py` 的格式上扩展出“链路规则”：`link`（链路类型）、`compare`（`{value: 取值}` 两端同一项，或 `{a, b, symmetric}` 交叉比较）、`op`（`equal` / `same_presence` / `both` / `overlap`）、`when`（`both` / `either`）、`pair`（端点下按键配对的子对象）、`requires`（Schema 缺少这些节点时跳过，列在 `rules_skipped`）、三语文案（占位符 `{link} {a_device} {a_end} {a_value} {b_device} {b_end} {b_value}`）。取值是 `fact:名称` 或 Schema 路径（subnet / ospf / isis / ldp 的端点是 interface，bgp 是 bgp.peer，其他链路类型只能用 fact:）。规则写错时与检查规则相同的问题格式（文件、规则、字段、文案键），CLI 退出码 3、API 409。28 条规则：链路掩码、MTU、OSPF / IS-IS / LDP 只在一端启用、一端 shutdown；OSPF 区域、网络类型、hello、dead、认证（接口没有时取区域认证）、静默；IS-IS 级别无交集、点到点不一致；LDP 认证只在一端、远端 LDP 只在一端；BGP 只在一端、对端 AS 与对端设备 AS 不符（双向）、地址族不同、认证只在一端；伪线只在一端、VC ID、控制字、MTU；BFD 只在一端、静态描述符不对应（双向）、发送间隔、检测倍数；VRRP 虚拟地址、VRRP 组只在一端（`requires: interface.vrrp`，M4-2 建好 VRRP 功能域、节点名一致后自动生效）。内置检查 `xd.ip_duplicate`（地址冲突，文案在 locales）。

**结果格式**：与单台检查一致——`findings`（`id`、`rule`、`severity`、`domain`、`device`、`node`、`schema`、`nodes`、`lines`、`message` / `suggestion` 为文案键 + 参数）再加 `link`、`link_type`、`devices`、`ends`（两端的设备、端点、节点、取值、行号）；`summary` 在 `checks.summarize` 之外加 `by_link`、`by_device`、`topology`（拓扑汇总）；拓扑的每条链路带 `issues`（发现的 id）与 `severity`（最高级别），每个设备节点带 `issues` 个数；`texts` 是规则文件文案的三种语言。

**接口**：CLI `lmesh topology [文件|目录|设备名|编号…] [--all] [--profile P]`、`lmesh consistency [同上] [--severity S] [--rules 文件]`（有 error 级发现时退出码 1）；API `GET /topology?devices=`（逗号分隔的名称或编号，省略时全部已导入设备）、`POST /topology`、`POST /consistency`（`{"configs": [{"name", "text", "profile"}], "device_ids": [], "severity"}`，两者都为空时取全部已导入设备）。

**样本**：`knowledge/samples/topology/`（有自己的清单，往返回归由 `tests/roundtrip/test_topology_samples.py` 执行，`core/roundtrip.py` 与 `tests/roundtrip/test_samples.py` 的排除列表加了该目录）：2 台 ATN（华为 VRP8 V800R025）+ 2 台 ASR 920 汇聚 + 1 台 ASR 920 路由反射器，OSPF / IS-IS、BGP VPNv4、LDP（本地与远端）、两条伪线、静态与接口 BFD，故意放了 13 处不一致（清单 `expect_findings`），全部报出、没有多报。

**已知限制**：VRF 内的 BGP 对等体（PE–CE）不参与（Schema 中 VRF 对等体没有独立的对象）；IS-IS L1 邻接的区域一致性没有检查；Cisco `passive-interface` 写在 IS-IS 进程下时没有映射到接口，静默只看接口下的配置；华为 `mtu` 与 Cisco `mtu` 计法不同，按数值直接比较（规则文案中已提示）；接口 BFD 只有 Cisco 写法有映射（min_rx 未映射）。

### 割接迁移（M4-5 结果）

| 功能 | 模块 | CLI / API |
|---|---|---|
| 接口映射建议 | `core/migration.py`（`suggest_map`） | `lmesh migrate … --suggest-only`；`POST /migrate/suggest-map` |
| 整机迁移：新配置、增量配置、映射表、告警、校验、割接步骤 | `core/migration.py`（`migrate`、`build_steps`、`map_csv`、`load_map_file`） | `lmesh migrate <旧配置\|设备> --to <Profile> [--interface-map] [--target-config] [--model] [--on-conflict] [-o 目录]`；`POST /migrate` |
| 平台族操作知识（管理口、逻辑接口类型写法、割接命令、核对命令） | `knowledge/migration/<平台族>.yaml` | — |
| 端口清单（各型号的物理端口与速率） | `knowledge/migration/ports/<Profile>.yaml`（目前只有 ASR 920，`verified: false`） | — |
| 回归 | `knowledge/samples/migration/manifest.yaml`、`tests/roundtrip/test_migration.py` | `pytest -m roundtrip` |

**流程**（决策 D-0061～D-0065）：

| 环节 | 做法 |
|---|---|
| 接口映射建议 | 用户给出的优先（`-` 表示不迁移；重复的目标告警 `duplicate_target`）；逻辑接口（聚合口 / 环回口 / 桥域三层口 / VLAN 接口 / Null / Tunnel）编号不变，按 `logical_types` 换类型写法；物理口依次按同名、同速率同端口号（最后一级编号）、同速率依次、更高速率分配（置信度 0.95 / 0.8 / 0.6 / 0.4），有配置的接口优先；分配不了的列入 `unmapped`（附原因）。管理口（`management` 正则，或绑定 `management_vrf`）不迁移 |
| 端口清单 | `--model` 指定的知识库清单 → 新设备现有配置中的物理口（现有配置里已有实质配置的端口视为占用，不自动分配）→ 知识库默认型号（告警 `port_inventory_assumed`）→ 都没有时同平台族保持原名、跨平台族按速率换类型写法且编号不变（置信度 0.5 / 0.3，告警 `port_inventory_missing`） |
| 换接口前的整理 | 在旧图副本上：没有映射的接口连同子接口删除，引用它们的配置（接口型取值、键字段是接口的对象）一并删除并告警 `ref_not_migrated`；聚合口编号变化时成员口的聚合组编号跟着改（`lag_renumbered`），聚合口不迁移时成员退出聚合，成员不全迁移、速率不一致时告警；子接口跟随主接口（`subinterfaces_follow`） |
| 翻译 | 复用 `translate.translate`（不做它自己的校验），最终映射表作为接口映射 |
| 合并到现有配置 | 译文解析成图后按节点编号（接口名统一写法、不分大小写）与现有配置对应：没有的新增，取值相同的跳过，显式取值不同的为冲突（`target_conflict`，`--on-conflict migrate` 以旧设备为准，`keep` 保留现有）；迁移需要的是目标默认值、而现有配置显式改过的（例如出厂 `shutdown`），写回默认值；同一对象下现有配置有、迁移内容没有的同类子对象并存并告警 `target_coexist`。新配置 = 合并后的图规范渲染（现有配置的原文行照常写回），增量配置 = 只渲染新增 / 修改的节点 |
| 校验 | 新配置再解析，二层接入点形态不同时换回旧设备的形态（`translate.reshape_access`），与旧设备按有效值对比（接口映射）；有原因的节点（告警、不支持、删除的）与新设备原有的配置（`target_existing`）之外的差异记为 `verify_diff`，新增的未识别行记为 `verify_unknown`；CLI 有未解释的差异时退出码 1 |
| 增量下发脚本 | 复用 `core/change.py`（现有配置或空配置 → 新配置）：优先用约定的 `plan(current_graph, target_graph, kb, profile) -> {script, rollback, items, verify}`，没有时用 `change.change(current_side, target_side, kb)`（取 `script`、`rollback.script`、`ops`、`verify`）；模块不可用或出错时 `script.available = false`（`reason`），迁移结果照常输出 |
| 割接步骤 | 割接前核对 → 下发新配置 / 增量配置 → 新设备业务端口保持关闭、BGP 对等体隔离 → 旧设备隔离 BGP（VRF 先、骨干后）→ 旧设备关端口（接入先、上行后）→ 按映射表迁移线缆 → 新设备启用上行（含聚合成员）→ 核对 IGP / LDP / 聚合 → 启用接入 → 恢复 BGP（骨干先、VRF 后）→ 割接后核对；回退四步。上行 = 本身或子接口有 OSPF / IS-IS / MPLS 配置的接口（聚合口是上行时成员也是）。命令按各平台族的写法（华为 system-view … quit … commit / return，Cisco configure terminal … exit … end）；每步有 `key`（文案键）、`params`、`commands` |

**输出目录**：`new-config.cfg`、`delta.cfg`（有现有配置时）、`interface-map.csv`（列 `source,target,kind,source_speed,target_speed,basis,confidence,subinterfaces,configured`，未映射的 target 为空、basis 为原因；修改后可用 `--interface-map` 传回）、`warnings.csv`、`steps.txt`、`migration.json`，增量变更模块可用时另有 `script.txt`、`rollback.txt`。

**回归**：ATN 现网 → ASR 920（ASR-920-24SZ-M + 部分映射表）、ASR 920 → ATN（出厂配置作为现有配置，只生成增量）、同平台族换型号（槽位 2 → 槽位 1）三个用例全部 `verify.unexplained = 0`、新配置没有新增未识别行。

**已知限制**：同平台族迁移也走翻译，未映射命令与功能域外原文不写回（列在 `unsupported`）；华为 ATN 还没有端口清单（用新设备现有配置）；ASR 920 端口清单按公开资料整理，未在设备上核对；BGP 会话切换只按“VRF / 骨干”两级排序，没有按对等体角色（RR、CE）细分；`knowledge/render/cisco-iosxe.yaml` 的 `interface_types` 中 `Null` 被 YAML 读成空值（翻译时 Null0 会误报 `interface_type`），迁移用 `knowledge/migration/` 的 `logical_types` 绕开，需知识库维护者给它加引号。

### 安全基线审计（M4-7 结果）

**基线文件**：`knowledge/rules/baseline-security.yaml`（新建），文件级 `kind: baseline`——`rules.read_docs` / `load_dir(kind=…)` 按 kind 分开读取，`lmesh check` 与规则开关（`rule_edit`）不加载基线文件。文件里定义多套基线 `profiles`（`basic` 基础、`strict` 严格，`includes` 表示包含，`strict` = `basic` + 严格项），规则用 `profiles` 字段归属基线；文件级 `vars` 是可调的取值（弱团体字清单 `weak_communities`、空闲超时上限 `max_idle_seconds`、SSH 重试上限 `max_ssh_retries`），基线的 `vars` 覆盖它们（严格基线超时上限 600 秒）。规则共 26 条（basic 22 条），覆盖：Telnet / FTP 关闭、SSH 启用且只用版本 2、SSH 重试次数、VTY 只允许 SSH / 绑定入方向 ACL / 用 AAA 认证、登录线路空闲超时不为 0 且不超过上限、SNMP 团体字不弱 / 绑定 ACL / 只读、只用 SNMPv3（严格）、告警 / 日志 / NTP 源接口为 Loopback、配置 AAA 与 TACACS+ / RADIUS、TACACS+ 共享密钥、本地用户已设密码 / 不允许 Telnet / FTP 服务类型 / 最高级别提示（严格）、NTP 服务器与认证、NTP 服务器绑定密钥（严格）、日志服务器。每条规则有严重度、三语标题 / 说明 / 建议、`tags` 分类与 `remedy`（`huawei` / `cisco` 两种写法的参考命令，叫法按 `knowledge/terms.yaml`，可用 `{key}`、`{node}`）。

**规则引擎扩展**（`core/rules.py`，向后兼容，旧规则文件不变）：`target: device` 设备级规则（每台设备求值一次，用于“必须存在”“至少有一个”）；以 `/` 开头的绝对路径（从设备根节点出发，例如 `/mgmt.aaa/scheme`）；新条件 `match`（正则，可忽略大小写）、`range`（数值范围，`unit: min_sec` 把“分 秒”换算成秒）、`key`（实例或路径上节点的键在列表中 / 匹配正则，用于团体字名称 / 别名、线路类型）、`family`（平台族，只用于 Profile 缺少缺省值、必须按平台区分“没有配置时的行为”的情况：Cisco 没有 Telnet 服务开关而由线路的 transport input 决定、Cisco 开启 aaa new-model 后线路缺省用 default 方法列表、华为 VRP8 缺省不开 SSHv1 兼容）；条件取值可写 `$变量`。求值器记录证据节点：正向条件记路径上找到的节点（取值不符时看它们），取反条件只记命中的节点；`all` 不短路，以便一次列全证据。

**结论与分数**（`core/baseline.py`）：每条规则在每台设备上为 `pass`（有适用实例且全部满足）、`fail`（至少一个实例不满足，每个实例一条不符合项）、`na`（没有适用实例：对象不存在或前提都不满足）。不符合项的行号 = 实例的第一行 + 证据节点的行；参考命令按设备平台族选写法并代入实例的键。得分按级别加权（error 3、warning 2、info 1）：通过权重 ÷ 适用权重 × 100，取整；多台设备的总分按全部格子计算。

**接口**：CLI `lmesh baseline [文件|设备名…] [--all] [--profile basic|strict] [--report 文件]`（知识库 Profile 用 `--parse-profile`，因为 `--profile` 按需求用作基线名；有 error 级规则不通过时退出码 1）；API `POST /baseline`（请求里基线名用 `baseline`，`profile` 仍表示知识库 Profile，与其他接口一致）、`GET /baseline/rules`、`POST /baseline/report`；报告 `core/report_baseline.py` 复用 `core/report.py` 的排版（中英、HTML / Markdown）：概要、设备 × 规则矩阵、每台设备的不符合项（含参考命令）、规则清单。修复只给参考命令，不生成可下发脚本。

**样本基准**（`tests/unit/test_baseline.py`，结论人工核对）：现网 ATN（atn-access-01）基础基线 95 分，只缺日志服务器；严格基线另有 NTP 服务器未绑定认证密钥（启用了认证但服务器没有 authentication-keyid，同步并未认证）、仍用 SNMPv2c、VTY 空闲超时 15 分钟。合成 ASR 920（pe-asr920-02）基础 100 分。片段样本（pe-asr920-01、MPLS / ACL 合成样本）缺管理面配置，按“不符合”计。ATN 上被锁定（state block）的本地用户不检查服务类型。

**已知限制（需要知识库补的内容）**：SSH 服务端算法（华为 `ssh server cipher / hmac / key-exchange`、Cisco `ip ssh server algorithm …`）没有进入 Schema——现网 ATN 允许 3des_cbc、aes*_cbc、md5、sha1、dh_group_exchange_sha1 等弱算法，基线暂时查不到；华为 `ssh server compatible-ssh1x`、Cisco SSH 的 RSA 密钥未映射；RADIUS 服务器没有对象（方法里出现 radius 时按已配置处理）；SNMPv3 用户 / 组与 USM 安全级别未建模；华为明文团体字写法（命令卡 `snmp-agent-community.1`）未映射，只能检查密文团体字的别名；Cisco `no aaa new-model` 被映射成 mgmt.aaa 对象（没有取反），所以“配置 AAA”按认证方案 / 方法列表判断；`mgmt.line.protocols`、`mgmt.ssh.version` 在 Profile 中没有缺省值（华为未配置 protocol inbound 时允许全部协议，Cisco 缺省兼容 SSHv1）。

### 增量变更脚本与变更影响分析（M4-3 / M4-4 结果）

REQ-015、REQ-016。代码：`core/change.py`、`core/impact.py`、`core/report_change.py`、`cli/cmd_change.py`（`lmesh change`、`lmesh impact`）、`api/routes_change.py`（`POST /change`、`POST /change/report`、`POST /impact`）；变更知识 `knowledge/change/<平台族>.yaml`；回归 `knowledge/samples/change/manifest.yaml` + `tests/roundtrip/test_change.py`。

**增量变更**（当前图 + 目标图，同一平台族；目标可以来自另一个配置版本、模板生成、翻译结果或粘贴的文本）：

1. 差异：两张图用 `compare` 的规范化（`_Canonicalizer`，有效值、键的规范写法）逐节点比较；只差在默认值的不下发；**不做改名识别**——设备上改名就是“新建 + 改引用 + 删除旧的”。显式属性恢复默认 → 取消该行；属性写在对象入口行上（静态路由的 tag）→ 重写这一行（取消会删掉对象）；取消多取值的行后，目标仍要的其他取值补写（`rewrite`）。
2. 命令：新增 / 修改的节点作为 facts 交给规范渲染器 `canon.render_full`（块结构一并得到）；同平台族时，若目标配置里有同一命令卡、写出了这些节点的原文行，用原文（保留未映射的参数与用户写法）；已有对象的块头用当前配置的原文。删除用清理模块的取消语法渲染；删除对象时优先选“写出对象全部键的最短写法”（`undo rule 10`、`no neighbor X`、`no 10`），命令卡里没有的取消写法放在变更知识的 `undo_extra`（应并入命令卡）。规范渲染写不出的节点按目标原文兜底（`fallback`），仍写不出的列在 `unsupported`。未映射命令（ext）按所属对象多重集合比较。
3. 修改：默认新值覆盖；`undo_first` 中的对象（华为 `rp.policy.node`、Cisco `acl.instance.rule`）修改入口行上的取值时先删除对象再整体重建。
4. 副作用与互斥：Profile 的 `side_effects` 加变更知识补充的（Cisco `vrf forwarding` 删除接口 IP——应归入 Profile）：src 变化（绑定或解绑）时，同一对象下目标仍有的 dst 补发（`side_effect`，高风险，排在触发命令之后），要删除的 dst 排在触发命令之前；Schema `mutex` 先撤旧再配新（删除命令的动作记为 `mutex`）；`replace_first`（接口地址）同一父对象下一删一增先删旧。
5. 顺序：命令之间的约束——上下文对象由别的命令新建（`contains`）、目标图的依赖（图中的 reference / prerequisite 边、没有规则的 ref 属性、键字段引用、键别名，见影响分析）、删除时先处理引用方（删除、取消或改引用，`referenced_by`）、副作用、互斥、先删后建、补写；在约束之外保持规范渲染的顺序（新增与修改在前，视图内的删除紧跟同一顶层块，顶层对象的删除最后），`lexicographical_topological_sort`；出现循环时按优先级断开并告警。
6. 脚本：按视图分块（进入视图的命令、缩进的子命令、退出）；华为 `system-view` … `quit` … `commit`、`return`（VRP8 两阶段提交），Cisco `configure terminal` … `exit` / `exit-address-family` … `end`（退出命令取 `knowledge/render` 的 exits，否则 `exit` / `quit`）。带说明的脚本在每条命令前加一行注释（华为 `#`、Cisco `!`）：动作、对象（按显示风格）、依赖原因、风险；`script_plain` 不带说明。
7. 风险：副作用 → 高；修改或删除已有配置且命中 `risk_high`（Schema 节点前缀）→ 高；兜底命令、或影响分析从被改节点能到达业务对象 → 中；其余（纯新增）→ 低。
8. 验证（下发与回滚都做）：在当前配置的行树上模拟执行——取消命令按取消语法（含 `undo_extra`）匹配要删的行（匹配不到记 `undo_no_match`），删除对象时一并删除只属于它的行；新命令解析后插入所在视图，同一属性的旧命令被覆盖（子行移到新命令下）；副作用删除同一视图中的 dst 行；每一步检查“引用了还不存在的对象 / 删除了还被引用的对象”（`order_violations`）。结果文本重新解析建图，与目标 `compare` 无差异、没有新的悬空引用、没有未识别行才算通过。

**影响分析**：依赖关系 = 图中 reference / prerequisite 边 + Schema 中没有依赖规则的 ref 属性 + 键字段引用（键字段类型按 `compare._Schema.field_type`，如 `bgp.af` 的 `vrf`）+ 键别名（`KEY_ALIASES`：`bgp.af.peer` 的键指向 `bgp.peer` / `bgp.peer_group`，同一顶层对象内）。`up` 从节点沿 contains 向上到所属对象、再沿依赖反向到引用方，逐层 BFS（键别名双向传递，经别名到达的对象不再沿别名回到其他地址族）；`down` 沿依赖正向。业务对象 `BUSINESS`：VPN 实例（vrf）、接口（interface）、对等体（peer：BGP 对等体 / 对等体组 / 地址族对等体、LDP 远端对等体、BFD 会话）、二层业务（l2vpn）。一份变更的影响（`change.impact`）：删除 / 修改的节点在当前图上求、新增 / 修改的在目标图上求，按节点合并。

**调用入口**：`change.change(Side, Side, kb, …)`（完整结果）；`change.plan(current_graph, target_graph, kb, profile)`（给割接迁移等模块：返回 `script`、`script_plain`、`rollback`、`rollback_plain`、`items`、`verify`、`rollback_verify`、`risk`、`summary`、`result`）；`change.change_text(当前文本, 目标文本, kb)`。模拟执行中，取消形式的设置命令（`undo shutdown`）按取消语法解析。

**报告**：`core/report_change.py` 复用 `core/report.py` 的 `_Doc` 排版（中文 / English，HTML / Markdown）。

**回归**（全部通过）：华为与 Cisco 各一套合成样本——新增 VRF + 接口绑定 + BGP VPN 实例、前缀列表改名 + 路由策略修改、删除对等体、接口绑定 VPN 的副作用、ACL 规则变化、OSPF 参数变化，加华为路由策略节点 deny → permit（先删后建）与两份对比基准的真实修改（现网 ATN 脱敏配置、ASR 920 两级改名）；每个用例下发与回滚都通过模拟执行验证，没有兜底命令。

**已知限制 / 需要知识库补的**：华为 ACL `destination-port` 没有映射（改端口时差异看不出来）；`huawei-vrp8.rule`、Cisco 接口 / 邻居 / ACL 规则卡缺少按键删除的取消写法（暂放 `undo_extra`）；Cisco Profile 缺 `vrf forwarding` 的副作用（暂放变更知识）；Cisco 编号 ACL 的单条规则无法单独删除（`no access-list N …` 会删整个 ACL），目前按普通规则处理；副作用只处理同一对象下的 dst；风险等级是规则判断，不评估流量。

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
│   ├── render/                 规范渲染的平台族书写习惯
│   ├── change/                 增量变更脚本的平台族下发习惯
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
