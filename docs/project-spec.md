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
| REQ-020 | 安全基线审计 | 任务文档“功能需求” | M4 | `core/baseline.py`、`core/report_baseline.py`、`knowledge/rules/baseline-security.yaml`、`lmesh baseline`、`POST /baseline`、`GET /baseline/rules`、`POST /baseline/report` | 后端完成（M4-7） | 界面待做；SSH 算法、RADIUS、SNMPv3 已在 M4-2 补齐 |
| REQ-021 | 版本历史：图快照，按时间查看配置变化 | 任务文档“功能需求” | M5 | `core/history.py`、`core/report_history.py`、`lmesh history`、`GET /devices/{id}/history` 等 | 后端与界面完成（M5-2） | 界面完成（见“M5 界面结果”），待用户评审 |
| REQ-022 | 文档导出：IP 地址表、VLAN 表、BGP 邻居表、接口描述表 | 任务文档“功能需求” | M5 | `core/export_tables.py`、`knowledge/export/tables.yaml`、`lmesh export table`、`POST /export/table` | 后端与界面完成（M5-3） | 界面完成（见“M5 界面结果”），待用户评审；另有 VPN 实例表、静态路由表 |
| REQ-023 | 特性能力查询 | 任务文档“功能需求” | M5 | `core/features.py`、`lmesh feature` / `feature-diff`、`GET /features` | 后端与界面完成（M5-4） | 界面完成（见“M5 界面结果”），待用户评审 |
| REQ-024 | AI 查询与护栏 | 任务文档“功能需求” | M5 | `core/gquery.py`、`core/guard.py`、`core/ask.py`、`lmesh query / guard / ask / generate`、`POST /query`、`/guard`、`/ask`、`/generate` | 后端与界面完成（M5-5） | 界面完成（见“M5 界面结果”），待用户评审 |
| REQ-025 | 报告导出：对比与检查结果导出（中英双语） | 任务文档“里程碑与版本规划”0.2.0 | M2 | `core/report.py`、`lmesh report`、`POST /reports` | 已完成（v0.2.0） | 中文 / English × HTML / Markdown（决策 D-0016） |
| REQ-026 | 显示风格：华为 / Cisco 两套叫法与命令写法，统一 Schema 以华为为基准，图按视图层级展示，界面、报告随时切换（默认华为） | 用户 2026-10-18 | M2 补充（0.2.1） | `knowledge/terms.yaml`、`core/terms.py`、`GET /kb/terms`、配置 `ui.term_style`、报告 `style` | 已完成（v0.2.1） | M7-5 加第三种风格 Nokia（REQ-037） |
| REQ-027 | 关系图谱视图：类似笔记软件的关系图，每个对象一个圆点、连线表示引用与依赖、力导向布局、可拖动缩放 | 用户 2026-10-18 | M2 补充（0.2.1） | Web 设备配置图 | 已完成（v0.2.1） | |
| REQ-028 | 隐藏配置的区分：默认值、派生值在各处有统一的样式与图例，可开关显示；配置翻译时处理不同厂商的默认值差异 | 用户 2026-10-18 | M2 补充（0.2.1）；翻译部分 M3 | Web 各视图；M3 翻译 | 已完成（v0.2.1） | 含默认值的完整配置文本随 M3 渲染器实现 |
| REQ-029 | 默认监听端口改为 9090（先由 9000 改为 9080，用户随后再改为 9090） | 用户 2026-10-18 | M4 补充 | `core/config.py` 的 `server.port`、config.example、文档 | 已完成 | Linux 测试机 9090 被其他 Docker 服务占用，在 Linux 上测试时临时用 9091 |
| REQ-030 | 用户账号管理，网页用用户账号登录：管理员管理账号（新建、停用、重置密码、改角色、删除），用户自己改密码；API 令牌继续用于脚本调用 | 用户 2026-10-18 | M4 补充 | `core/users.py`、`/api/v1/auth/*`、`/api/v1/users`、CLI `lmesh user`、登录页与账号管理页、首次运行向导创建管理员 | 进行中 | 设计见“用户账号（REQ-030）”一节 |
| REQ-031 | 配置检查项目：用户创建项目（一台设备 + 多份脚本，脚本可以是下发用的变更脚本或完整配置），在页面编辑器中边写边查，问题标在对应行；可开启 / 关闭配置顺序核查 | 用户 2026-10-18 | M4 补充 | `core/script_check.py`、`/api/v1/check-projects`、CLI `lmesh script-check`、配置检查项目页 | 进行中 | 设计见“配置检查项目（REQ-031）”一节 |
| REQ-032 | 配置翻译自定义规则：命名规范、名称映射（支持模糊规则）、端口映射规则；翻译、割接迁移、批量生成共用 | 用户 2026-10-18 | M4 补充 | `core/naming.py`、规则集文件、`/api/v1/translate-rules`、CLI `--rules`、翻译页规则编辑与预览 | 进行中 | 设计见“翻译自定义规则（REQ-032）”一节 |
| REQ-033 | 内置 AI skill：内置 AI 的能力以 skill 形式管理；管理员有 skill 管理界面；提供 skill 学习进化功能 | 用户 2026-10-18 | M5 补充 | `core/skills.py`、`knowledge/ai-skills/`、`data/ai-skills/`、`/api/v1/ai/skills`、CLI `lmesh skill`、skill 管理页 | 进行中 | 设计见“内置 AI skill（REQ-033）”一节 |
| REQ-034 | 设备配置分析：结构化脚本显示、配置分层视图、TCP/IP 模型视图、配置关系视图（图结构）与分析摘要，集中在一个页面 | 用户 2026-10-18 | M5 补充 | `core/layers.py`、`core/config_analysis.py`、`knowledge/layers.yaml`、`/api/v1/devices/{id}/analysis`、`POST /api/v1/analysis`、`lmesh analyze`、设备配置分析页 | 已实现（预览待评审） | 设计与实现结果见“设备配置分析（REQ-034）”一节 |
| REQ-035 | 用户工作空间与项目：每个账号有独立的工作空间，可创建项目，每个项目有自己的设备与脚本；公共设备库；项目成员；个人 API 令牌 | 用户 2026-10-19 | M6（0.6.0） | 数据库（工作空间、项目、成员、公共设备库）、所有设备相关接口按项目隔离、项目切换器 | 已完成（M6） | 设计见“用户工作空间与项目（REQ-035）”一节，经用户确认 |
| REQ-036 | 权限模型：新增“知识库维护员”角色；知识库与共享的规则、基线、模板只有管理员和维护员可改，普通用户只读并可提交建议；用户可建私有模板、在项目中调整规则；全部设备重新解析仅管理员 | 用户 2026-10-19 | M6（0.6.0） | 角色、权限检查、审核队列“建议”、项目级规则覆盖 | 已完成（M6） | 设计见“权限模型（REQ-036）”一节，经用户确认 |
| REQ-037 | 接入 Nokia 7750 SR（SR OS）：Classic CLI 与 MD-CLI 两种格式，映射到统一 Schema，支持解析、往返、对比、检查、翻译等 | 用户 2026-10-19 | M7（0.7.0） | `knowledge/` 新平台族、解析器 MD-CLI 分块扩展、Profile | 进行中 | 文档与知识准备先行，与 M6 并行 |
| REQ-038 | 删除设备与单个配置版本（确认对话列出连带删除的内容；被配置检查项目作基线时提示；最后一个版本不能单独删除）；CLI `lmesh device delete`、`DELETE /api/v1/devices/{id}`；所有登录账号都可删除（删除记入日志），M6 起项目属主与“可编辑”成员可删除项目内的设备与配置（只读成员不可，公共设备库仅管理员，引用的公共设备为解除引用） | 用户 2026-10-19 | M5 补充（问题修复） | 设备接口、设备列表与版本历史页 | 已完成 | 用户确认现在做；用户随后要求每个用户都可以删除项目下的配置；现阶段所有登录账号都可删除，M6 项目权限另做；实现见“删除设备与配置版本（REQ-038）”一节 |
| REQ-039 | 用户自助注册：设置中开启 / 关闭注册（默认关闭）；可选注册后直接生效或需管理员审核（默认需审核）；注册频率限制 | 用户 2026-10-19 | M6（0.6.0） | 设置项、登录页注册入口、注册接口、账号管理“待审核”、注册后自动建工作空间与默认项目 | 待开发 | 设计见“用户自助注册（REQ-039）”一节，经用户确认 |
| REQ-040 | AI 接口：管理员配置一个或多个 AI 接口并设定是否允许公共使用；每个用户可选用个人 API 或允许的公共 API | 用户 2026-10-19 | M6（0.6.0） | AI 接口表、设置页、账号设置“我的 AI”、AI 调用按用户选择的接口 | 已完成（M6-8） | 设计见“AI 接口：公共与个人（REQ-040）”一节 |
| REQ-041 | AI 增强：为各功能新增内置 AI skill（日常分析、变更与割接、规范与合规、知识库构建、报告共 21 个），AI 只给建议，代码验证后由用户确认生效 | 用户 2026-10-19 | M8（0.8.0） | `knowledge/ai-skills/`、各功能页的 AI 入口、审核与采纳流程 | 待开发 | 设计见“AI 增强（REQ-041）”一节 |
| REQ-042 | 网元拓扑视图的设备图标：按设备角色与类型设计图标，显示厂商与平台 | 用户 2026-10-19 | M8（0.8.0） | 拓扑视图、关系图谱、图标资源 | 已完成（M8-3，0.8.0） | 设计见“拓扑设备图标（REQ-042）”一节；实现见“M8-3 结果” |
| REQ-043 | 所有视图可以全屏显示与操作（配置图、关系图谱、拓扑、设备分析各视图、对比、脚本编辑器等） | 用户 2026-10-19 | M7（0.7.0） | 前端通用全屏组件 | 已完成（M7-7） | 设计见“视图全屏（REQ-043）”一节 |
| REQ-044 | 未支持型号的处理：导入时可手工选择 Profile（同厂商 / 同平台族）、试解析推荐、型号规则记住选择、近似标记与下发前提示、申请支持与派生 Profile、认不出的厂商只存原文 | 用户 2026-10-19 | M8（0.8.0） | 导入、设备页、Profile、审核队列 | 已完成（M8-7，0.8.0；2026-10-20 预览评审 5 页全部通过，3 个设计问题按推荐） | 设计见“未支持型号的处理（REQ-044）”一节，经用户确认；实现结果见该节 |
| REQ-045 | 项目内划分网络：网络是独立的工作区，设备可在多个网络中；拓扑还原、一致性、检查、基线、脚本、变更、迁移、AI 建议、报告等操作按网络独立 | 用户 2026-10-19 | M9（0.9.0） | 数据模型、网络切换器、所有按项目的页面与操作数据按网络隔离 | 已完成（M9，0.9.0；用户 2026-10-21 验收） | 设计见“项目内的网络（REQ-045）”一节，经用户确认 |
| REQ-046 | M8 完成后发布可部署版本：Docker 镜像 + compose（SQLite / PostgreSQL）、Linux 离线安装包、Windows 离线安装包、Windows 安装程序（.exe）；全部离线可装；只生成在本机 dist/ | 用户 2026-10-19 | M8（发布 0.8.0） | 打包脚本、Dockerfile、安装脚本、部署文档 | 已完成（M8-8，0.8.0 起每个版本生成发布包） | 用户确认：默认 SQLite 可配 PostgreSQL；不推送远程；实现见“M8-8 结果”，含升级时知识库合并 |
| REQ-047 | 个人偏好按账号保存：语言、明暗主题、显示风格、设备图标风格随账号保存，换浏览器登录后沿用；语言切换改为图标按钮，点击后选择语言 | 用户 2026-10-20 | M9（M9-7 评审修改） | 前端偏好、账号接口 | 已完成（M9-7，0.9.0；用户 2026-10-21 验收） | 未登录时仍用浏览器本地值；登录后以账号保存的值为准 |
| REQ-048 | 界面问题修复：首次运行向导的表格居中、界面优化、厂商名称首字母大写、AI 接口加“测试连接”；切换显示风格后 Schema 视图与 Profile 管理没有变化；打开网页时先闪过主界面再跳到登录页 | 用户 2026-10-20 | M9（M9-7 评审修改） | 向导、Schema 视图、Profile 管理、路由 | 已完成（M9-7，0.9.0；用户 2026-10-21 验收） | 问题修复 |
| REQ-049 | 系统设置页：管理员在界面中修改服务监听地址与端口（以及向导中的其他配置项），写入 config/config.toml，提示重启后生效 | 用户 2026-10-20 | M9（M9-7 评审修改） | 系统设置页、设置接口 | 已完成（M9-7，0.9.0；用户 2026-10-21 验收） | 现在只有首次运行向导能改，配置完成后只能手改配置文件；复用向导的参数定义与校验 |
| REQ-050 | 创建项目的权限与加入项目：系统设置里“普通用户可以创建项目”总开关（默认关），管理员可给个别用户单独授权，管理员始终可建；已有项目保留照常使用。加入方式：属主按用户名添加（现有）、搜索“可被搜索”的项目并申请（审批后加入）、邀请链接（有效期、角色，可选仍需审批）。审批人：属主、系统管理员、新增成员角色“管理”（可审批、加减成员，不能删除或转交项目）。可被搜索的项目对外只显示名称、简介、属主、设备数。没有项目的用户登录后提示等人邀请，可一键申请创建权限 | 用户 2026-10-20 | M9（M9-8） | 项目、成员、用户管理、系统设置、通知 | 已完成（M9-8，0.9.0；用户 2026-10-21 验收） | 用户在对话中逐项确认；结果见“M9-8 结果” |
| REQ-051 | AI 查询页优化：范围可按网络选择（默认当前网络，也可选全部设备），设备多时可搜索、按厂商筛选、全选 / 清空，设备区可折叠；只存原文的设备在范围中置灰、不参与查询；顶部 AI 接口、模型、脱敏信息条与说明卡可折叠，折叠状态按账号记住 | 用户 2026-10-21 | M9 之后的修订（0.9.x） | AI 查询页（AskView）、按网络的 /ask 接口 | 已完成（2026-10-21；预览评审修改后通过） | 同时修复：范围含只存原文的设备时提问报 500；见“REQ-051 结果” |
| REQ-052 | AI 查询会话：问答按会话保存；同一会话可带上下文追问、任一轮改问题重新回答（旧回答保留为历史版本）；会话可重命名、归档、恢复、删除；会话只有本人可见，可分享给同项目成员只读查看；会话属于项目并记下网络与设备范围 | 用户 2026-10-21 | 0.9.2 | AI 查询页、会话数据表与迁移、会话 API、CLI | 已完成（0.9.2；预览评审通过） | 设计见“AI 查询会话（REQ-052）”一节，经用户确认 |
| REQ-053 | AI 查询附件：会话中可添加配置文件（解析入图、作为本会话的临时设备加入范围）、文档（txt/md/csv/pdf/docx/xlsx，提取文字脱敏后作为参考资料）、图片（管理员开启后可用，发送前确认，不经脱敏，只作参考） | 用户 2026-10-21 | 0.9.2 | AI 查询会话、附件表、AI 调用支持图片、系统设置 | 已完成（0.9.2；预览评审通过） | 设计见“AI 查询附件与下载（REQ-053、REQ-054）”一节 |
| REQ-054 | AI 查询下载：会话报告 HTML / Markdown（中英双语各一份，可打印为 PDF）、结果表 CSV / Excel、AI 撰写的 Markdown 报告（代码核对数字与名称） | 用户 2026-10-21 | 0.9.2 | AI 查询会话、报告生成、新 skill ask-report | 已完成（0.9.2；预览评审通过） | 设计见“AI 查询附件与下载（REQ-053、REQ-054）”一节 |
| REQ-055 | 问题修复：Huawei-SI 现网配置演示与功能示例运行中发现的问题（基线页文案键、BGP 对等体组误报、规则说明占位符、配置图定位、脱敏 ACL 通配符、脚本检查漏计悬空引用等，逐项见“REQ-055 问题清单”） | 演示中发现 2026-10-28 | 0.9.4 | 安全基线、配置检查、配置图、脱敏、脚本检查、模板生成、CLI 输出、增量变更、割接迁移、翻译、影响分析、拓扑、设备配置分析 | 已完成（055-34 中 PTP、EVPN send-community 留作知识库缺口） | 用户 2026-10-28 要求全部修复；结果见“REQ-055 修复结果” |
| REQ-056 | 问题修复：REQ-055 修复后重拍 Huawei-SI 演示与 AI 功能截图时发现的问题（IS-IS 改号后割接校验仍拦截导出、校验文案占位符、影响分析关系图谱挤成细柱、行数口径不一致等，逐项见“REQ-056 问题清单”） | 演示中发现 2026-10-29 | 0.9.4 | 割接迁移、翻译、影响分析、设备配置分析、增量变更、拓扑、AI 报告摘要 | 已完成 | 用户 2026-10-29 要求修复并重拍割接截图；结果见“REQ-056 修复结果” |

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
- A7 版本号：语义化版本（用户已确认）。M1 开发期间用 `0.0.x`，M1 验收打 `0.1.0`，M2–M9 依次对应 `0.2.0`–`0.9.0`（M6–M9 为用户 2026-10-19 新增）；开发阶段完成、新需求、问题修复升修订号【默认 + 第二轮 Q8】
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
- D3 默认监听：`0.0.0.0:9090`，局域网可访问【用户修改：2026-10-18 由 9000 改为 9080，随后改为 9090】
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
| 版本历史 | `lmesh history list\|diff\|object\|tag\|restore <设备>` | `GET /api/v1/devices/{id}/history` 等 | 按时间看变化 | 0.5.0 |
| 审计表格导出 | `lmesh export table --preset ip-address\|bridge-domain\|bgp-peer\|interface-description\|vrf\|static-route` | `POST /api/v1/export/table` | IP、VLAN、BGP 表（M5-3 按预览页定为预置模板 + 自定义列） | 0.5.0 |
| 特性能力查询 | `lmesh feature <关键词>`、`lmesh feature-diff <A> <B>` | `GET /api/v1/features`、`GET /api/v1/features/diff` | 查支持情况与默认值 | 0.5.0 |
| 自然语言查询 | `lmesh ask "<问题>"`（另有不需要 AI 的 `lmesh query`、`lmesh guard`） | `POST /api/v1/ask`（另有 `/query`、`/guard`、`/generate`） | 需要配置 AI | 0.5.0 |

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

**依赖 / 副作用说明三语**：Schema `deps` 与 Profile `side_effects` 的 `note` 写成 `{zh-CN: …, en: …, pt-BR: …}`（仍兼容纯字符串，视为 zh-CN）。加载时统一成三个键齐全的字典（`Note`，en 缺用 zh-CN，pt-BR 缺用 en），`kb validate` 对文件里缺少的语言给出警告（`dep.note_lang`、`profile.side_effect_note_lang`），单元测试保证仓库内齐全。API 输出（图的边、`change` 的 `after`、`/kb/schema` 的 `deps`、功能清单、拓扑跨设备边等）中 `note` 为三语对象（没有说明时为 `{}`），不随请求语言变化，也不另给 `note_text`；界面用 `noteText`（`frontend/src/i18n/note.ts`）按当前语言取值，CLI、报告与文案参数（`i18n.t`、`checks.render_text`）按各自语言取值。

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

### 变更与分析的 Web 界面（M4-8 结果）

按预览页 `DevelopDocs/ui-preview/M4/` 实现（评审前按预览编码，决策 D-0084；去掉没有后端支持的部分见 D-0086）。导航新增“变更”（增量变更、割接迁移）与“分析”（影响分析、拓扑视图、跨设备一致性、安全基线）两组；共用样式 `frontend/src/styles/m4.css`（变更原因、风险、链路状态、脚本视图、基线矩阵，明 / 暗两套颜色），后端文案键的三语渲染 `views/m4/texts.ts`（`backend-texts.json` 由 locales 抽出，规则文件文案随结果返回），纯逻辑在 `views/m4/*.ts`（vitest `m4.test.ts`）。

| 页面 | 路由 | 接口 | 要点 |
|---|---|---|---|
| 增量变更 | `/change?device=&cv=&tv=` 或 `mode=paste` | `POST /change`、`POST /change/report` | 当前（设备 + 版本）→ 目标（同平台族设备的版本，或粘贴）；带原因着色的分块脚本（`script_rows`），选中一条显示动作说明、风险原因、“排在谁之后”（`after` 的依赖类型与说明，可展开完整依赖链，槽内画弧线）、依赖它的命令与对应的回滚命令；回滚脚本按对象与下发命令对应（同一对象及下级，否则上级）；复检（与目标一致、悬空引用、顺序、执行问题、回滚复原）；影响摘要与“分析这次变更的影响”；下载下发 / 带说明 / 回滚脚本与中英报告（HTML / Markdown） |
| 影响分析 | `/impact?device=&node=…&dir=` | `POST /impact` | 起点可搜索加入、常用对象（VPN 实例、前缀列表、路由策略、对等体组、Loopback0）、从设备配置图节点详情或增量变更跳转；方向 up / down / both、深度、只列对象；cytoscape 关系图（起点 / 1 跳 / 间接 / 业务对象，按依赖类型着色，可按距离分层），列表按类型 / 距离 / 功能域分组并给出从起点出发的路径 |
| 拓扑与一致性 | `/topology`、`/consistency` | `POST /consistency` | 设备集（已导入设备多选，可加上传的配置文件，不入库）；同一对接口上的同网段链路与其上的 OSPF / IS-IS / LDP / 接口 BFD 合成一条线，BGP、伪线、远端 LDP、静态 BFD 各自成线，状态取最高级别；点线看推导依据与置信度、两端事实对比、问题、两端配置块（问题行标红）；一致性列表按级别 / 设备筛选，点问题回到拓扑图并高亮两端设备与链路；导出发现 CSV |
| 割接迁移 | `/migration?device=&to=` | `POST /migrate` | 旧设备 → 目标 Profile、型号、新设备现有配置（无 / 已导入设备 / 粘贴）与冲突处理；五步：翻译告警（与旧配置行联动）、接口映射表（依据、置信度、状态，可改写，改过的行作为 `interface_map` 重新生成，CSV 导入导出与 CLI 同列）、新设备配置（完整 / 增量 / 增量下发脚本 / 回滚）、割接步骤（执行与回退，标出会断业务的步骤）、验证与割接包 ZIP（与 `lmesh migrate -o` 的输出文件相同，校验通过后可导出） |
| 安全基线 | `/baseline?baseline=&devices=` | `POST /baseline`、`GET /baseline/rules`、`POST /baseline/report` | 基线 basic / strict、设备多选；概况（总分、不符合项、通过 / 适用、涉及设备、按级别）；规则 × 设备矩阵（列头得分）；设备详情（得分环、不符合项按规则归组、证据行取配置原文、参考命令按平台族、全部参考命令）；规则详情（说明、建议、华为 / Cisco 参考命令、各设备结果）；中英报告与矩阵 CSV |

**后端追加**：`change` 结果（下发与回滚）增加 `script_rows`（`kind` frame / enter / cmd / quit、`depth`、`text`、`seq`），与 `script_plain` 逐行对应；`script_lines` 改为由 `script_rows` 渲染，文本输出不变（`tests/unit/test_change_rows.py`、API 用例 `change-text`）。

**显示风格**：对象名（命令说明、影响分析节点、证据节点、拓扑未解析对端）用 `useTerms().describe` 按华为 / Cisco 写法显示，切换即时生效；脚本与参考命令是设备自己的语法，不随风格变化；变更与报告请求带上当前风格。

**已知限制**：拓扑没有中英报告接口（改为导出 CSV）；影响分析只在单台设备内，不跨设备追踪；割接验证只有计数与 `verify_*` 告警，没有链路 / BGP 复算表；基线没有“例外”与“按默认值判断”的标记（后端结果中没有对应字段）。

### 版本历史、审计表格导出、特性能力查询、AI 查询与护栏（M5 后端结果）

REQ-021～REQ-024。界面在 M5 界面阶段单独做；后端返回结构按 `DevelopDocs/ui-preview/M5/` 的四个预览页设计。决策 D-0089～D-0093 与本节新增的 D-0094 起。

| 功能 | 模块 | CLI / API |
|---|---|---|
| 版本历史 | `core/history.py`、`core/report_history.py`、表 `config_imports` 与 `config_versions` 新列（迁移 `0003_history`） | `lmesh history list / diff / object / tag / restore`；`GET /devices/{id}/history`、`/history/diff`、`/history/object`、`PUT` / `DELETE /history/{version_id}/tag`、`POST /history/restore`、`POST /history/report` |
| 审计表格导出 | `core/objtable.py`（按对象类型取格子，导出与查询共用）、`core/export_tables.py`、`knowledge/export/tables.yaml`（新建） | `lmesh export presets / table`；`GET /export/presets`、`GET /export/fields`、`POST /export/table` |
| 特性能力查询 | `core/features.py` | `lmesh feature`、`lmesh feature-diff`；`GET /features`、`/features/detail`、`/features/diff` |
| 图查询语言 | `core/gquery.py` | `lmesh query`；`POST /query`（不需要 AI） |
| 配置护栏 | `core/guard.py` | `lmesh guard`；`POST /guard`（不需要 AI） |
| AI 查询与生成 | `core/ask.py`（复用 `core/ai.py`，任务模型 `ai.model_ask`、`ai.model_generate`） | `lmesh ask`、`lmesh generate`；`GET /ask/status`、`POST /ask`、`POST /generate` |

**版本历史**（D-0090、D-0091）：快照就是一个配置版本——原文、当时的图（`graph_gz`：去掉解析器语句对象后的 node-link JSON，gzip 压缩，ATN 现网配置约 66 KB）、解析用的知识库版本、内容指纹（`content_hash`，行尾空白不计的 SHA-256）。导入时与设备最新快照指纹相同则不存新快照，只在 `config_imports` 记一条（`duplicate`、`source_kind` file / dir / zip / api、`actor`：CLI 为系统用户名，API 为 `api`，不记录令牌）。导入后计算相对上一个快照的变化计数（`change_summary`，旧数据在查看时间线时补算）并按 `history.keep`（新配置项，默认 50，0 不限，向导与 `config.example.toml` 已同步）清理：保留最近 keep 个、贴标签的、最新的。快照引用：配置版本编号 / `v<编号>`、`#<序号>`（CLI 中纯数字是序号）、`latest`、`prev`、`tag:<标签>`；清理后序号会重排，长期引用用版本编号或标签。差异：两张快照图用 `compare.compare` 逐节点比较后按对象归并（属性、未映射命令归到最近的对象，跳过编号为 `_` 的参数容器；对象增删、改名单独成项）；另用对比的规范化找出“只是写法不同”（有效值相同而显式 / 默认不同 `default_explicit`，或原始写法不同 `spelling`，例如掩码与前缀长度），默认只计数（D-0092）；原文差异用 difflib 分块，每行带两侧行号与所属节点，缩进、空白、位置变化的行标为 `fmt`。默认用保存的图，两侧知识库版本不同时 `kb.differs` 提示，`rebuild=true` 两侧都按当前知识库重新解析；没有保存图的旧版本自动重建（`graph: rebuilt`）。对象历史按规范编号逐快照取子属性的有效值并标出变化。回到 A：两侧按当前知识库重新解析后调用 `change.change`（脚本要用当前命令卡渲染）。报告复用 `core/report.py` 的排版（中文 / English，HTML / Markdown）。其他模块取已导入设备的最新快照用 `history.devices_from_db`：保存的图与当前知识库版本一致时直接用（不再重新解析），否则重建。

**审计表格导出**（D-0092、D-0094）：一张表 = 一类 Schema 对象的全部实例；列是相对路径（`ipv4.address`、`af.rd`、键字段 `name`）或代码计算的派生列（`mask`、`peer_remote_as`、`peer_type`、`peer_afs`、`peer_import` / `peer_export`、`vrf_rt_import` / `vrf_rt_export`、`vrf_interfaces`、`bd_members`、`bd_l3_interface`）。每格 `value`、`origin`（explicit / default / derived / none / unsupported）、`nodes`、`lines`；敏感字段（Schema `secret`）的值只是 true / false，文件中写“已配置 / 未配置”。预置模板与命名筛选条件放在 `knowledge/export/tables.yaml`（运行时知识库没有时用程序自带的）：IP 地址表（`where: has-ip`）、VLAN / 桥域表、BGP 邻居表（认证密码列）、接口描述表、VPN 实例表、静态路由表，表头三语，叫法可按华为 / Cisco 风格；也可以自定义对象类型、列与临时筛选（运算符与图查询相同，按有效值比较，接口名缩写等价）。CSV：UTF-8 带 BOM、CRLF，第一列设备，最后是“来源”（这一行中来自默认值 / Profile 不支持的列）、节点、行号；XLSX（openpyxl，`uv add` 已更新锁文件）：“说明”工作表（生成时间、知识库版本、每台设备的配置版本与 Profile、列与 Schema 路径、筛选条件、说明）+ 每台设备一个工作表或全部一张表，默认值格子灰色斜体并加批注，不支持的格子加批注，冻结表头、自动筛选。

**特性能力查询**：关键词匹配节点编号（完全相同 100、末段相同 80、包含 60）、Schema 语义与两种显示风格的叫法 / 命令关键字（40）、命令卡语法（30）、分词都命中（20）。每个 Profile 一格：`state`、`default`、`cards`、`syntax`、`undo`、`views`、`credibility`（命令卡最高审核状态）、`source`、`inherited` / `origin`（继承来源）。`kind`：same / differs / gap（有 Profile 未填写）；不带关键词浏览全部时 same 只计数（D-0093），带关键词时照常列出。Profile 对比在 `edit.profile_compare` 的分类上补了命令写法与排序：默认值不同 → 只有 A → 只有 B → 一边未填写，相同的只计数，两边都未填写的不列。Profile 条目没有“部分支持”的字段，预览页的 p 状态暂不提供（遗留）。

**图查询语言**（D-0095）：`FIND <对象> [ON <设备>,… | *] [WHERE <字段> <运算符> <取值> [AND …]] [RETURN <字段>,…] [WITH DEFAULTS] [LIMIT n]`，也可用等价的 JSON。只读、只有 AND、不做连接（一次一类对象）。代码校验对象类型、字段路径、运算符、正则、设备名与行数（1–1000）后执行；WHERE 按有效值（含默认值）比较，取值按字段类型规范化；RETURN 默认只给配置了的值，WITH DEFAULTS 时给出默认值。每行有引用编号 `n`、设备、节点、子树行号，每格有来源、节点与行号。

**配置护栏**（D-0096）：去掉会话命令（system-view、configure terminal、commit、return、end）与代码块围栏后，片段接在目标设备当前配置（最新快照原文）之后整体解析建图，每行对应到图节点。parse：功能域内匹配不到命令卡 → 拦截，功能域外 → 注意（无法校验）；deps：新内容带来的悬空引用、互斥 → 拦截，缺少前置 → 注意，Profile 副作用（华为绑定 VPN 实例删除接口地址）：新内容在其后重新配置 → 已核对的要点（ok），先配地址再绑定 → 拦截，现有地址会被删除 → 注意；template（可选）：模板校验的发现落在新内容行上 → 注意；conflict：接口地址与本机其他接口或其他已导入设备重复（同一 VRF）、RD 被另一个 VPN 实例使用、同一主接口下 dot1q 重复 → 拦截。有拦截时 `verdict: blocked`，不能交给增量变更；通过时附当前 → 合并后的增量变更脚本（`change.change`，含模拟验证）。

**AI 查询与生成**（D-0089、D-0097）：未配置 AI 时 `GET /ask/status` 为 not_configured，`POST /ask`、`POST /generate` 返回 409（`data.status: not_configured`），CLI 退出码 3；图查询与护栏不需要 AI。查询：第一次调用让 AI 只写一条查询（提示中有查询语法、设备列表与 Schema 目录，不含配置），代码校验不通过时把错误交回 AI 再写一次（`attempts` 默认 2）；第二次调用只给问题、查询与结果行（敏感字段写 configured / not configured，默认值标 default），要求每句话给出 `cites`（引用编号）与 `facts`（行、字段、取值）或 `count`；代码逐句核对：全部相符为 passed，有不符（取值、行数、引用不存在）为 corrected——原句不作为结论，由代码按图上的取值写出更正文字（三语文案），既没有 facts 也没有 count 的为 unverifiable。生成：上下文只给目标设备各类对象的名字清单，AI 返回的配置先经护栏，被拦截时把拦截原因交回 AI，最多 `rounds` 轮（默认 2）。发给 AI 的系统提示与正文一律先经 `Sanitizer("basic")`（与导入同一密钥，同一原值替换成同一个值）再发送，`sent` 中返回实际发送的内容与回复，`question_sent` / `request_sent` 是脱敏后的问题；每次调用照常记入 AI 调用记录。测试全部用假的 AI 客户端（替换 `ai.provider_hook`）。

**测试**：单元 `tests/unit/test_history.py`（SQLite 与 PostgreSQL 都跑，含迁移）、`test_export_tables.py`、`test_features.py`、`test_ask_guard.py`；CLI 用例 `tests/cases/cli_cases.history|export|feature|ask.toml`；API 用例 `tests/cases/api_cases.history|export|ask.toml`（特性查询的用例在 export 文件中）与 `tests/api/test_m5_api.py`（假的 AI、文件下载、经 API 的重复导入）。新的测试准备方式 `configured-fullkb-history`（`tests/conftest.py`）：设备 ATN-CHANGE-01 导入基准、重复、修改三次。`tests/unit/test_sanitize.py` 中“同一文件再导入一次追加版本”的断言按 D-0091 改为重复导入不存新快照、内容不同才追加。

**已知限制**：快照之间的改名只在一次对比内识别，对象历史按规范编号追踪，改名后的对象不连续；序号随保留策略清理重排；XLSX 不做单元格级的节点批注（节点与行号在每行最后两列）；“我的模板”（用户保存的自定义表格）没有做，可用 API 的 `columns` / `filters` 组合；特性查询没有“部分支持”状态；护栏的合并是把片段接在当前配置之后解析，片段里的 `undo` / `no` 只按解析结果处理，没有逐条模拟下发（增量变更脚本的模拟验证覆盖了这部分）；AI 回答的核对只覆盖 facts / count 写出的事实，句子里没有声明的数字不核对。

### 版本历史、表格导出、特性查询、AI 查询的界面（M5 界面结果）

按 `DevelopDocs/ui-preview/M5/` 四个预览页实现（用户尚未评审，自动模式下先编码，决策 D-0089～D-0093 与本节新增决策）。四个页面：`HistoryView.vue`（路由 `history`，`/history/:id?`，导航“设备配置”组，设备列表的“N 个版本”也链接到这里）、`ExportView.vue`（`export`，“分析”组）、`FeaturesView.vue`（`features`，“知识库”组）、`AskView.vue`（`ask`，“工作台”组，未配置 AI 时导航不显示，正在该页时保留）。纯逻辑在 `views/m5/history.ts`、`exportTable.ts`、`features.ts`、`ask.ts`（单元测试 `views/m5/m5.test.ts`），子组件 `views/m5/HistoryTimeline.vue`、`GuardResult.vue`；共用样式 `styles/m5.css`（版本 A / B、校验状态、AI 标记、引用角标、支持格子；明暗两套颜色），新增图标 table、feature、chat、send。文案 `i18n/pages/history|export|features|ask.json`（三语），功能域名称放在 `features.dom.*` 供各页共用。

| 页面 | 实现要点 |
|---|---|
| 版本历史 | SVG 时间轴按时间比例排列、相邻点至少隔开一段距离（同一天多次导入不会叠在一起）；点大小与柱高来自 `vs_previous`，×N 为合并的重复导入，旗标为标签；单击 / Shift 单击 / 拖动 A、B 标记。差异请求带 `show_noneff=true&context=100000`：图差异默认只看有效值变化，取消勾选后把“只是写法不同”的项按对象列为“等值”；配置差异用整份原文在前端配成并排行、折叠相同的行（变化前后各留 3 行，可展开），点任意行选中对应对象，选中对象时其行高亮。知识库版本不同提示与“按当前知识库重建”（`rebuild=true`）。对象历史：对象列表取最新配置图中的显式对象，属性 × 快照矩阵（同值连段、变化琥珀、新出现绿色、默认值虚线、不存在斜线）与变化记录。快照表可加 / 去标签。“生成回到 A 的变更脚本”调用 `POST /history/restore`，弹窗显示脚本并可跳到增量变更页（`change?device&cv=B&tv=A&run=1`）。报告中文 / English（HTML）。 |
| 表格导出 | 预置模板来自 `/export/presets`（表头叫法随显示风格），也可选任意对象类型自定义；列清单 = 模板列 + 对象的全部字段 + 派生列，勾选与拖动排序；命名筛选条件 + 临时条件（字段 / 运算符 / 取值）；预览每次改动后防抖请求 `POST /export/table`（json），格子按来源显示（默认值虚线、不支持斜纹、敏感字段只显示已配置 / 未配置）；点格子显示设备、节点、取值来源与配置原文（按需取设备原文，敏感行打码）。下载 CSV / XLSX，表头中文、English、Português 三个按钮（D-0092），附等价 CLI 与 API。 |
| 特性能力查询 | `GET /features`（浏览全部时相同的只计数，可“也列出相同的”）；Profile 勾选、平台族筛选在前端按列隐藏，“只看差异”按可见列重新判断；搜索时顶部一句话结论由前端从知识库结果汇总（标“由知识库计算，非 AI”）；格子“↑ + 默认值”表示继承（D-0093）；详情显示命令写法、取消写法、命令卡与可信度、视图、默认值来源与文档出处、适用条件、依赖规则，可跳到 Schema 视图与 Profile 管理。Profile 对比用 `/features/diff`，搜索词同时过滤对比行，“也列出只有写法不同的项”用 `include_same=true` 中 `syntax_differs` 的行；对比表 CSV 在前端生成。 |
| AI 查询 | 状态来自 `/ask/status`；问配置：范围（设备勾选）、三步（AI 写的查询及被校验拒绝的尝试、代码执行的结果表、AI 的回答）、每句带引用角标与核对状态（通过 / 被更正划掉 / 无法校验斜体），更正文字单独成块，校验明细表（facts、行数），证据面板（节点属性、配置原文、代码怎么核对），“查看发送内容”显示 `sent`（系统提示、正文、回复，均为脱敏后）。生成配置：AI 生成（`/generate`，多轮可切换）或粘贴配置（`/guard`）两种来源，护栏结果组件显示五个阶段、逐行 ✓ / ✕ / !、拦截 / 注意 / 已核对分组、结论条；拦截时“交给增量变更”不可用，可让 AI 重新生成或改成粘贴后手工修改；通过时可查看护栏附带的增量变更脚本，或交给增量变更页（合并后的完整配置经会话存储传给 `ChangeView`，`change?device&mode=paste&handoff=1`，自动生成）。未配置 AI：降级说明 + 不用 AI 的替代入口 + “校验粘贴的配置”（D-0089）；接口返回 409 not_configured 时页面切到降级视图。 |

**后端追加**（都有测试与文档）：`GET /devices/{id}/history/diff` 新参数 `context`（原文差异每块前后保留的相同行数，默认 3，0–100000；界面取 100000 拿整份原文在本地折叠），`history.diff` / `_diff_graphs` 透传给 `text_diff`；`POST /guard` 与 `POST /generate` 新参数 `merged`（默认 false，为 true 时返回合并后的完整配置 `merged_text`，供“交给增量变更”）。测试：API 用例 `history-diff-full-text`，`tests/api/test_m5_api.py` 的 `test_history_diff_context`、`test_guard_merged_text`、`test_generate_merged_text`。

**测试**：前端单元 `views/m5/m5.test.ts`（时间轴、A / B 规则、差异分组、并排配对与折叠、对象矩阵、列清单与请求体、CLI 写法、特性差异判断与一句话结论、查询着色、护栏阶段、交接暂存）；端到端 `e2e/m5.spec.ts`（导航、版本历史主流程、表格导出、特性查询与对比、未配置 AI 的降级页与护栏拦截 / 通过 / 交给增量变更、用拦截请求返回假 AI 结果的问答流程，假结果在 `e2e/fixtures/m5-ask.json`，来自假 AI 客户端的真实接口输出）。

**与预览页的差异**：没有“我的模板”（保存自定义表格，后端没有）；特性没有“有限制”（p）状态、对比没有“取值范围不同 / 一侧有限制”分类（后端只有默认值不同、只有 A / B、未填写、只是写法不同）；对比不提供中英报告下载（只有前端生成的 CSV）；AI 状态条不显示“本月调用次数 / tokens”（没有按月统计的接口，改为链接到调用记录）；护栏问题没有“建议修改”的具体写法（后端 `fix` 为空时不显示）；交换 A / B 只提示“A 总是较早的一侧”（后端总把较早的作为 A，反方向用回到 A 的变更脚本）；表格导出的格子来源用设备最新配置原文显示（版本与表格一致）；特性矩阵的列标题用 Profile 编号与软件版本，不另写中文名。

**已知限制**：对象历史的对象列表只来自最新快照（已删除的对象从图差异的“查看此对象的历史”进入）；时间轴在快照很多（上百个）时点会很密；证据面板与格子来源按设备取一次原文（`/devices/{id}/graph?raw=true`），大配置首次点击稍慢。

### 功能域扩展与知识库补缺（M4-2 结果）

两部分：补齐 M4-3～M4-7 各模块报告的知识库缺口（并去掉模块里的绕行），新增 VRRP、SR-MPLS、EVPN、QoS、时钟同步五个功能域（决策 D-0099～D-0105）。知识库功能域 12 → 17 个（`kb.yaml`），Schema 新增约 230 个节点（vrrp 17、sr 27、evpn 25、qos 77、clock 47、mgmt 等补充 30）；命令卡华为 3740 → 约 4840 张（qos 288、evpn 316、clock 161、sr 77、vrrp 54），Cisco 505 → 约 640 张。

**知识库缺口**：

| 模块 | 缺口 | 做法 |
|---|---|---|
| 安全基线 | SSH 服务端算法 | `mgmt.ssh.ciphers` / `hmacs` / `kex`（华为 `ssh server cipher / hmac / key-exchange`，Cisco `ip ssh server algorithm encryption / mac / kex`，公开文档缺页，修正文件补卡）；严格基线新增 `sec.ssh_strong_algorithms`（弱算法正则在文件级 vars：CBC / 3DES / RC4、MD5 / SHA1、SHA1 密钥交换），现网 ATN 报出第 2221–2223 行 |
| | 明文团体字、SNMPv3、RADIUS | 华为 `snmp-agent community read <团体字>` 映射（团体字即键）；新对象 `mgmt.snmp.group`（安全级别 noauth / auth / priv）、`mgmt.snmp.user`（组、认证 / 加密算法）、`mgmt.radius` + `.server`（华为 RADIUS 服务器组、Cisco `radius server` 与旧写法 `radius-server host`）、`mgmt.aaa.domain.radius`；严格基线新增 `sec.snmp_v3_priv`、`sec.snmp_v3_user_strong`，基础基线新增 `sec.radius_key`，`sec.aaa_server` 改为按 RADIUS 服务器判断 |
| | `no aaa new-model` | 新节点 `mgmt.aaa.enabled`（Cisco `aaa new-model` 为 flag，取消形式为 false；华为 Profile 缺省 true、Cisco 缺省 false）；`sec.aaa_enabled` 要求开启且有方案 |
| | 缺省值与 `family` 分支 | Profile 缺省：`mgmt.line.protocols`（华为 VTY all、Cisco VTY none）、`mgmt.ssh.version`（华为 2、Cisco 1.99；类型改为字符串）、`mgmt.ssh.compat_v1`（华为 `ssh server compatible-ssh1x enable`）、`mgmt.line.auth`（华为 none）、SSH 算法缺省（华为）；Cisco 的 `mgmt.telnet.enabled`、`mgmt.ssh.enabled`、`mgmt.ssh.compat_v1` 标 `supported: false`。规则引擎新增条件 `supported: <Schema 节点>`（设备 Profile 支持该节点），基线文件里的 4 处 `family` 全部去掉；华为 `mgmt.ssh.enabled` 缺省按命令参考更正为 true |
| 增量变更 | 按键删除的取消写法 | 修正文件把文档另列的写法与原 undo 合并：华为 `undo rule { <rule-id> [ to <end-rule-id> ] \| … }`，Cisco `no interface <接口>`、`no neighbor X [ remote-as … ]`、ACL 条目 `no { <序号> \| permit … }`；修正文件支持 `add_params`（只补参数）。`knowledge/change/*.yaml` 的 `undo_extra` 清空；`change.py` 的模拟执行在取消命令按另一张卡的取消语法也能匹配时删除该行（`no 10` 可以删 permit / deny / remark 卡的条目） |
| | Cisco `vrf forwarding` 副作用 | 移入 Profile `side_effects`，变更知识的 `side_effects` 清空 |
| | 华为 ACL `destination-port` | M3 收尾已映射，确认 |
| 拓扑 / 一致性 | VRF 下的 BGP 对等体 | `bgp.af.peer.remote_as` / `description` / `password` / `update_source`（华为 `ipv4-family vpn-instance` 下 `peer … as-number`，Cisco `address-family ipv4 vrf` 下 `neighbor … remote-as`）；`topology.py` 的 BGP 链路带 VRF（按 VRF 查对端地址），链路的 `vrf` 字段有值 |
| | Cisco IS-IS `passive-interface` | `isis.process.passive`（键接口）+ `passive_default`，拓扑按进程缺省 + 接口例外计算静默 |
| | Cisco `bfd … min_rx` | 修正同名参数后映射 `interface.bfd.min_rx` |

**新功能域**（两个平台族都做；Cisco 公开命令参考缺页的命令按 ASR 920 配置指南由修正文件补卡，原文问题与缺口记在 `DevelopDocs/设备产品文档/Cisco/…/README.md` 第四批）：

| 功能域 | 主要对象 | 华为 | Cisco |
|---|---|---|---|
| vrrp | `interface.vrrp`（键组号）、`.virtual_ip`（键地址）、`priority`、`preempt`、`preempt_delay`、`advertise_interval` / `advertise_msec`、`auth_mode`、`.track`（`reduce` / `increase`）、`vrrp.global.version` | `vrrp vrid …`（可靠性一章 VRRP 节） | VRRPv2 `vrrp N ip …` 与 VRRPv3 `vrrp N address-family ipv4` 子模式（新视图 `vrrp`，`exit-vrrp`） |
| sr | `sr.global`（SRGB / SRLB、隧道优选）、`sr.global.conn_map.af.prefix`（Cisco connected-prefix-sid-map）、`sr.prefix_sid_map`（华为 mapping-server）、`isis/ospf.process.sr_mpls / srgb_* / ti_lfa / microloop_avoidance`、`interface.prefix_sid` | `segment-routing` 视图、IGP 下 `segment-routing mpls / global-block`、Loopback `isis / ospf prefix-sid`、`frr` 下 `ti-lfa` | `segment-routing mpls` 及其子模式、`router isis / ospf` 下 `segment-routing mpls`、`fast-reroute ti-lfa` |
| evpn | `evpn.instance`（mode、rd、rt、auto_rt）、`evpn.global`、`bridge_domain.evpn_instance`、`interface.evpn_instance`、`evpn.evpl`（VPWS-EVPN）、`bgp.af{afi=evpn}` | `evpn vpn-instance … [ bd-mode \| vpws ]`、`evpl instance`、`l2vpn-family evpn`（新视图 `bgp-af-evpn`） | `l2vpn evpn`、`l2vpn evpn instance N vlan-based …`、`member evpn-instance`、`address-family l2vpn evpn`；ASR 920 只支持单归属，ESI / 多归属不收 |
| qos | `qos.classifier`（`.match` 键 field + value）、`qos.behavior`、`qos.policy` + `.rule`、`interface.qos_policy` / `qos_profile` / `port_queue`、`qos.profile.user_queue`、`qos.flow_queue.queue`、`qos.flow_wred` / `port_wred` | 流分类 / 流行为 / 流策略、HQoS（qos-profile、flow-queue、flow-wred、port-wred）、端口队列 | class-map / policy-map / class 下的 set、police、shape、bandwidth、priority、queue-limit、random-detect、子策略，接口 service-policy |
| clock | `clock.ptp`（类型、域、priority1/2、profile、`.port`）、`interface.ptp`、`clock.ptp_adaptive`（1588 ACR）、`clock.sync`（SSM、ESMC、WTR）+ `.source`、`interface.clock` | `ptp …`、`ptp-adaptive …`、`clock source … / clock synchronization enable` | `ptp clock … domain N [hybrid]` → `clock-port`、`network-clock …`、`esmc process`、接口 `synchronous mode` |

结构差异按“Schema 以华为为基准”处理（D-0102）：Cisco 没有独立的流行为，class 下的动作记在 `qos.policy.rule` 上（节点名与流行为相同）；华为 HQoS、1588 ACR、Cisco PTP clock-port 与 connected-prefix-sid-map 只在一家有，跨平台族翻译报不支持。映射表达式新增 `unless:关键字:表达式`（行里没有该关键字时才取值，规范渲染反解时禁止出现该关键字）。抽取规则：华为 `param_types` 新增 VRRP 组号（`virtual-router-id` 以 router-id 结尾，原先被推断成 IPv4）；SR 一章丢弃 MPLS 视图下的命令（`mpls te path verification` 会让范围外的 `mpls te` 行变成未识别）。`terms.yaml` 为 43 类新对象登记了两种显示风格。跨设备一致性新增 `xd.vrrp.advertise`、`xd.vrrp.auth`，原有的 `xd.vrrp.virtual_ip`、`xd.vrrp.one_side` 不再跳过。

**样本与回归**：

| 项 | 结果 |
|---|---|
| 现网 ATN（atn-access-01） | 命令行 1151 → 1745，原文行 774 → 180，未识别 0，往返逐字一致；剩下的原文行是 MPLS TE、PIM、CFM、DHCP 中继、BGP MVPN / VPNv6 等范围外内容。配置检查新报 7 个没有接口应用的流策略与 7 个 QoS 模板（逐个在原文核对过）及其独占的流分类 / 流行为 / 流队列（级联孤儿） |
| 新增门槛样本 | `huawei-atn-v800r025-synthetic/atn-advanced-01.cfg`、`cisco-iosxe-asr920-synthetic/pe-asr920-04-advanced.cfg`（五个新功能域 + 管理面补充，合成），往返一致、未识别 0，规范渲染（含默认值）重新解析等价 |
| 翻译回归 | 原有用例全部 `verify.unexplained = 0`；ATN 现网 → ASR 920 写出 2128 / 3035（分母增加的约 770 个是华为特有的 QoS / 时钟节点，原有功能域写不出的约 146 个，与 M3 收尾 142 基本相同，下限调为 0.69）；新增两个高级特性用例（122 / 222、107 / 170）。翻译校验对“源 Profile 标了 supported: false、目标取缺省值”的差异不再计为未解释 |
| 安全基线基准 | 现网 ATN 严格基线 84 → 81 分（新增 SSH 弱算法）；合成 ATN MPLS 样本基础基线 69 → 66 分（SSHv2 规则在没有 SSH 服务时不适用，失败项不变） |

**遗留**：Cisco SSH 算法、SNMPv3 用户在 IOS 运行配置中不显示（用户），算法缺省值随版本变化，Profile 没有登记；Cisco `snmp-server user` 的认证 / 加密算法只记关键字（sha-2、aes，不带位数）；华为 DiffServ 域映射表、Cisco table-map 不建模；Cisco EVPN-VPWS（`vpws context`）未收；IS-IS 进程级被动的缺省只用于拓扑静默判断，接口的 `interface.isis.passive` 缺省值仍是 false；`kb map` 不会清除命令卡上已不再命中规则的 maps（本次删除 DiffServ 域映射时手工清理，应改为汇总时清除）。

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
- 测试时机【用户 2026-10-19】：开发阶段完成后跑增量测试（按改动范围挑选：只改前端 / 项目权限时跑前端单元与相关 API、CLI 用例；动了解析器、建图、渲染、翻译或知识库时再加往返与翻译 / 变更回归）；提交前加跑 e2e；里程碑验收与打版本前在 Windows 与 Linux 上跑全量。全量测试并行执行提速（pytest-xdist）。
  - 实现：`test.bat` / `test.sh --changed [REF]` 是增量入口，`scripts/run_tests.py` 用 `git diff`（相对 REF 与 HEAD 的分叉点，默认 HEAD，含未提交与未跟踪的文件）列出改动，按其中的映射表 `CHANGE_RULES` 选类别并逐个打印去向；规则宁宽勿窄，未登记的路径跑全部离线测试，有新增或删除文件时加 docs。
  - 实现：后端测试默认用 pytest-xdist 并行（`-n` = CPU 核数，上限 16，可用 `--max-workers` 或 `LMESH_TEST_MAX_WORKERS` 改；`--dist worksteal`），`--serial` 或 `-n 0` 串行。并行时 SSH 隧道由主进程建一次、各 worker 共用；PostgreSQL 用例的 schema 名带 worker 名；junit 与 HTML 报告由主进程汇总，分类统计不变。
  - 实现：每个测试进程共用一份只读的程序自带知识库（不带命令卡、带全部命令卡各一份），用例的 `tmp_root/knowledge` 是指向它的链接（Windows 目录联接，其他系统符号链接）；会写入它的用例加 `@pytest.mark.kb_write`（CLI / API 用例在 toml 里写 `kb_write = true`）改为自己复制。每个用例结束时比对共用副本的快照，被改动就恢复并让该用例报错，用例之间不会互相污染；`LMESH_TEST_KB_COPY=1` 恢复为每个用例都复制。
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
- 端口：默认 9090（2026-10-18 起）；Linux 测试机上 9090 被 docker-proxy（其他服务）占用，不动它，在 Linux 上开发和测试时临时用 9091 运行（只覆盖运行参数，不改默认值 D3）；端口转发 `ssh -i ~/.ssh/lmesh_dev_ed25519 -N -L 9091:127.0.0.1:9091 root@linux-test-host`

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
│   ├── export/                 审计表格导出的预置模板
│   ├── templates/              配置模板
│   ├── translate-rules/        翻译规则集的内置示例（用户的在 data/translate-rules/）
│   ├── ai-skills/              内置 AI skill 定义（管理员修改的版本在 data/ai-skills/；REQ-033）
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

（第一轮初选：便携压缩包。M8-8 按 REQ-046 确定：Docker 镜像 + compose（SQLite / PostgreSQL）、Linux 离线安装包、Windows 离线包、Windows 安装程序（NSIS），见“M8-8 结果”与 `docs/deploy.md`）

## K 项目专属 skill

（开发完成后填写。第一轮初选：CLI、API、测试、更新 skill 全部生成）

已生成（开发中按用户要求提前生成）：

| skill | 位置 | 用途 |
|---|---|---|
| `lmesh-docs-to-graph` | `.claude/skills/lmesh-docs-to-graph/SKILL.md` | 从厂商产品文档到统一配置图的完整流程：文档转换、抽取规则与补丁、命令卡抽取与审核、Schema 与映射、Profile、样本检验与补漏、往返回归与发布（2026-10-17 用户要求总结） |


## 用户账号（REQ-030）

用户 2026-10-18 提出：添加用户账号管理，使用用户账号登录网页。自动模式下按以下推荐做法实现（决策记录 D-0094 起），用户回来后可改。

- 角色：管理员（账号管理、系统设置、AI 接口、知识库发布）与普通用户（其余全部功能）两种；只读角色作为备选，暂不做。
- 密码：只在数据库中保存 scrypt 哈希（标准库 `hashlib.scrypt`，带随机盐）；不写入日志、配置文件和任何其他文件；最短 8 位。CLI 从提示或 `--password-stdin` 读取，不接受命令行明文参数。
- 网页会话：登录后发放随机会话令牌，放在 HttpOnly、SameSite=Strict 的 Cookie 中；数据库只存其哈希；有效期配置项 `security.session_hours`（默认 12）；登出或停用账号立即失效。
- 防暴力破解：连续失败 `security.login_max_failures`（默认 5）次锁定 `security.login_lock_minutes`（默认 15）分钟；登录、登出、失败、锁定写入日志（不含密码）。
- API 令牌：`security.api_token` 保留，脚本与 CLI 远程调用照常用 `Authorization: Bearer`，视为管理员权限；网页不再要求输入令牌。
- 第一个管理员：首次运行向导中创建；已经配置过的旧安装没有账号时，登录页允许用 API 令牌登录一次并要求立即创建管理员；也可以用 `lmesh user add <名称> --role admin`。
- 管理员至少保留一个启用的账号（不能停用或删除最后一个管理员）。

### 实现结果（REQ-030）

- 数据：表 `users`（用户名唯一、角色、停用、scrypt 哈希 `scrypt$N$r$p$盐$哈希`、连续失败次数、锁定截止、最后登录、改密时间）与 `user_sessions`（会话令牌的 SHA-256、过期时间，账号删除时级联删除）；Alembic 迁移 `0004`（接在 `0003` 版本历史之后，SQLite 与 PostgreSQL 都测过）。
- 核心：`core/users.py`，CLI 与 API 共用。scrypt 参数 N=2^14、r=8、p=1，16 字节随机盐；用户名 2–64 个字符（字母、数字、点、下划线、短横线，字母或数字开头），新建时不区分大小写查重；密码 8–256 个字符。用户名不存在时也计算一次哈希，响应时间不暴露账号是否存在；登录失败的提示不区分“用户不存在”和“密码错”，日志里也不记录不存在的用户名（可能是误填的密码）。锁定期间正确密码同样拒绝；锁定到期自动解除，管理员“解除锁定”、重置密码、`lmesh user enable` 也会解除。
- 会话：登录成功后发放 32 字节随机令牌，只放在 Cookie `lmesh_session`（HttpOnly、SameSite=Strict、Path=/，HTTPS 访问时加 Secure，Max-Age = `security.session_hours` 小时），数据库只存 SHA-256；固定有效期，不滑动续期。停用账号、重置密码时该账号全部会话失效；自己改密码时除当前会话外全部失效；创建新会话时顺便清理过期会话。
- 认证依赖：`api/common.py` 的 `require_token` 同时接受 Bearer 令牌（视为管理员，显示名 `api-token`）与会话 Cookie，带了 `Authorization` 头时以令牌为准（令牌错误直接 401，不再看 Cookie）；`require_admin` 用于管理员接口：`/users*`、`GET /config`、`GET|PUT /ai/settings`、`POST /ai/test`、`POST /kb/releases`、`POST /kb/rollback`，普通用户返回 403（新错误码 1006）。知识库包导入、审核、Schema 与 Profile 编辑仍对普通用户开放。
- 第一个管理员：Web 向导在确认页之前新增“管理员账号”一步（`POST /setup` 的 `admin` 字段，校验错误键 `admin.username` / `admin.password`），提交后直接以该管理员登录；没有账号的旧安装，登录页（`GET /auth/status` 的 `has_users` 为 false 时）改为“API 令牌 + 管理员用户名与密码”，调用 `POST /auth/bootstrap` 一次创建并登录，已有账号后该接口返回 409；也可用 `lmesh user add <名称> --role admin`。命令行向导 `lmesh setup` 不创建账号，完成后用 `lmesh user add`。
- 第一个管理员的提示（用户 2026-10-18 反馈修复，决策 D-0166）：还没有账号时 `GET /auth/status` 另返回 `config_file`（实例实际读取的配置文件绝对路径，受 `LMESH_ROOT` 与 `--config` 影响）与 `token_set`（是否设置了 API 令牌，不返回令牌内容），有账号后不再返回；登录页在提示中显示实际路径，`token_set` 为 false 时不显示令牌输入框，改为说明在服务器上运行 `lmesh user add <用户名> --role admin`，或在该配置文件中设置 `security.api_token` 后重启服务再刷新本页。
- 管理员保护：最后一个启用的管理员不能停用、降级、删除（409 / 退出码 1）；网页会话不能停用、降级或删除自己（409）。
- 新配置项（`[security]`，向导“安全”一步与 `config/config.example.toml` 同步）：`session_hours = 12`（1–720）、`login_max_failures = 5`（1–100）、`login_lock_minutes = 15`（1–1440）。
- 日志：`lmesh.auth` 记录登录成功、失败（含第几次）、锁定、被拒（停用 / 锁定中）、登出、创建 / 停用 / 启用 / 改角色 / 重置密码 / 删除账号、用令牌创建第一个管理员，带客户端地址；不记录密码与令牌。
- CLI：`lmesh user list|add|disable|enable|reset-password|set-role|delete`，直接操作本机数据库；密码从提示（不回显、输入两次）或 `--password-stdin` 读取；退出码：参数不合格 2、账号不存在 4、状态不允许（已存在、最后一个管理员）1、未配置 3。
- 网页：登录页改为用户名 + 密码（显示 / 隐藏、锁定提示、会话过期说明，`next` 只接受站内路径）；浏览器不再保存 API 令牌（旧版本留下的 `lmesh-token` 会被清除），请求靠同源 Cookie；任何接口返回 401 时跳回登录页并带 `expired=1`。顶栏右侧新增当前用户菜单（修改密码、账号管理、退出登录）；“系统”分组（AI 接口、账号管理）只对管理员显示，普通用户直接打开 `/ai`、`/users` 时回到首页；知识库版本页对普通用户隐藏发布、回滚、放弃草稿按钮并说明原因。新页面 `/users`（账号管理）与 `/password`（修改密码），文案三语，明暗主题。
- 与预览页的差异：向导的“管理员账号”一步放在 AI 接口之后、确认之前（预览页原在“安全”之后），因为向导步骤由服务端的配置分组生成，管理员一步不是配置项，放在固定位置更简单；预览页已同步调整。登录失败不显示“还可以再试几次”，避免泄露账号是否存在。
- 测试：单元 `tests/unit/test_users.py`（SQLite 与 PostgreSQL）；API 用例 `tests/cases/api_cases.users.toml`（用例新增 `login = ["用户名", "密码"]`：先登录再带 Cookie 请求；准备方式 `configured-users`）与多步用例 `tests/api/test_users_api.py`（Cookie 属性、锁定与解除、登出与停用后会话失效、令牌优先、普通用户 403、向导创建管理员）；CLI 用例 `tests/cases/cli_cases.users.toml`（用例新增 `stdin` 字段）；前端 `src/views/account/account.test.ts`；e2e `frontend/e2e/accounts.spec.ts`，已有 e2e 改为用账号登录（`scripts/e2e_server.py` 建好 `e2e-admin` 与 `e2e-user`）。


## 配置检查项目（REQ-031）

用户 2026-10-18 提出“检查脚本配置”的新场景，并在对话中确认：脚本可以是下发用的变更脚本，也可以是完整配置；一个项目 = 一台设备（或它的某个版本）作为基线 + 多份脚本；“实时”指在页面编辑器中边写边查，问题直接标在对应行；关闭顺序核查时只查内容不查顺序。

- 变更脚本：在基线配置上模拟执行（复用 `core/change.py` 的模拟执行），检查命令能否识别、进入的视图是否正确、引用的对象是否存在、取消命令能否匹配到现有配置、与现网冲突或被覆盖的值、副作用（例如绑定 VPN 会删除接口 IP），执行后的配置再跑配置检查规则（新增的悬空引用、孤儿配置等）。
- 完整配置：解析、未识别行、配置检查规则，并与基线设备的当前配置对比，给出差异摘要。
- 顺序核查开启：命令先后必须满足依赖（被引用的先建、删除时先删引用方、子命令在进入对象视图之后），顺序错误报为错误，并给出按依赖重排的建议脚本；关闭：只看最终结果，内容正确即可。
- 实时：编辑器输入停顿后自动提交检查（防抖），结果按行显示；项目和脚本保存在数据库中，属于创建它的用户（REQ-030）。
- AI 一起校验（用户 2026-10-18 补充）：配置了 AI 时，项目可以开启“AI 一起校验”，并按规则选择哪些检查交给 AI 参与（例如命名与描述规范、最佳实践建议这类代码难以完全判断的规则；规则文件中用 `ai: true` 标出可由 AI 参与的规则）。AI 的发现先入图、由代码校验后再显示，标明来源为 AI 和校验状态（通过 / 无法校验）；发给 AI 的配置先脱敏；未配置 AI 时这一开关隐藏，其余检查照常。
- 顺序重排（用户 2026-10-18 补充）：一键按依赖重排脚本；重排前后的版本都保留为脚本的修订记录，可以并排对比每条命令移动的位置和原因，可以恢复到任一版本；用户手动编辑保存也形成修订记录。
- 文本差异对比（用户 2026-10-18 补充）：配置文件 / 脚本提供 diff 对比，用于配置修改后、顺序重排后核对。可以对比任意两个修订、项目内任意两份脚本、脚本与基线设备配置；并排与上下两种视图，行内标出改动的字符；重排造成的位置变化识别为“移动”（标出从第几行移到第几行），不算成删除加新增；可以切换“忽略顺序”只看内容差异；同时给出语义差异（复用配置对比，按有效值比较）。对比结果可下载（统一 diff 格式与中英 HTML 报告）。

### 实现结果（REQ-031 后端）

代码：`core/script_check.py`（检查、模拟执行、重排）、`core/script_check_ai.py`（AI 一起校验）、`core/textdiff.py`（文本差异与报告）、`core/checkproj.py`（项目、脚本、修订的存储与入口，CLI 与 API 共用）、`cli/cmd_script_check.py`（`lmesh script-check`、`lmesh script-diff`）、`api/routes_check_projects.py`（`/api/v1/check-projects`）；表 `check_projects`、`check_scripts`、`check_revisions`（迁移 `0005_check_projects`，接在账号的 `0004` 之后）；`core/rules.py` 增加规则字段 `ai`。决策 D-0111（先预览后编码）与 D-0121～D-0130。

**变更脚本**：

1. 逐行跟踪视图：会话命令（system-view、configure terminal、commit、return、end）与 quit / exit / 视图的退出命令（exit-address-family）只改变视图；脚本有缩进时先按缩进退出视图；当前视图匹配不到时逐级退回上层视图（华为给出 info 提示“建议先写 quit”）；所有视图都匹配不到但属于别的视图时报“视图错误”（error，例如在系统视图写 `peer … as-number`）；功能域内匹配不到命令卡为“未识别”（error），功能域外为 info（无法校验）。
2. 合并图：脚本行带着跟踪出的视图直接构造成解析行，接在基线配置的解析结果之后建图（不重新解析基线文本），得到每行的规范编号、新建的对象（基线中没有的对象）、引用的对象（`impact.links` 的依赖，只算有配置行的对象）。
3. 模拟执行：包装 `change._Sim`（取消语法匹配、同一属性覆盖、Profile 副作用都沿用），另记每个行树节点的来源（基线行号 / 脚本行号），对象与引用按计数增量维护；执行后的行树直接写成解析结果建图（不重新解析文本）。取消形式的设置命令（`undo shutdown`，命令卡只有关键字且对应属性）按设置处理，其余取消命令匹配不到时报 `undo_no_match`（warning）。重复下发与现有配置完全相同的命令不触发副作用。
4. 每行的问题：覆盖基线的现有配置（info，标出基线行与原文）/ 与基线相同（info）/ 被脚本后面的行覆盖（warning）；副作用删除了基线行（warning；脚本后面在同一对象下重新配置时为 info `side_effect_ok`）；执行后的配置跑配置检查规则，与基线的检查结果比较，新出现的发现落到产生它的脚本行（发现只在基线行上时，标到改动了同一对象的第一条脚本行），已消除的列在 `findings_fixed`；新内容与现网的冲突（同一 VRF 内接口地址重复、RD 被另一个 VPN 实例使用，复用护栏的取值函数）。
5. 顺序核查开启：按书写顺序执行，报出能靠重排解决的顺序错误（error，类别 order）——引用的对象在后面的行才创建（`order_missing_reference`）、删除对象时引用方在后面的行才处理（`order_still_referenced`）、先配的值被后面命令的副作用删除（`side_effect_lost`，例如先配地址再绑定 VPN）；有顺序错误时结果附上重排建议。关闭：按依赖重排后的顺序执行，只看内容（用户确认的“内容正确即可”）。完整配置不适用顺序核查（`order.applicable = false`）。
6. 按依赖重排：约束——子命令在它的视图之后、被引用的对象先建、删除对象前先删除或改写引用方、副作用的触发命令之后再配会被删除的值、同一属性 / 同一行的多条命令保持原顺序、未识别等行跟随原来前面的命令；约束之外保持原顺序，刚进入的视图里能排的命令优先接着排（块尽量不拆开）；只进入已有对象视图的行随子命令重新写出（不留空块）；出现循环时按优先级断开并告警。输出按视图分块（与增量变更的脚本格式相同：华为 system-view … quit … commit / return，Cisco configure terminal … exit … end）。移动的命令按“新顺序中原序号的最长递增子序列之外”判定，原因列出它必须排在谁之后（after）或谁依赖它（before），与依赖类型、对象（按显示风格）、说明；重排后自动复检（`before` / `after` 的顺序错误数）。
7. 性能：基线（文本指纹 + Profile + 知识库对象）的解析、图与检查结果缓存，命令卡索引缓存；2266 行的现网 ATN 配置作基线、400 行脚本，一次检查约 0.5 秒（`test_check_is_fast_enough_for_live_editing`）。

**完整配置**：按基线的 Profile 解析（没有基线时自动识别），未识别行（error）、配置检查规则（全部发现，按行），有基线时与基线按有效值对比（`compare.compare`）给出差异摘要；功能域外的行只计数（`result.raw`），不逐行提示。

**AI 一起校验**：只把规则文件中 `ai: true` 且勾选了的规则交给 AI（`ai` 规则可以没有 `assert`，代码不求值）；发送的脚本经 `ask.sanitize_text` 脱敏、带行号，调用复用 `ask._Session`（记录 AI 调用、`sent` 中返回实际发送的内容）。AI 的每条发现由代码校验：规则必须是勾选的、行必须是脚本中真实的命令行、该行在执行后的图上有节点（先入图）、属于规则适用的对象、规则也有代码断言时代码必须同样判定不符合（代码判定符合 → 拦截 `code_disagrees`；代码也报出 → 记为 confirmed，不重复显示）、引用的证据必须是该行（脱敏后）原文的一部分；通过的标 `source: ai`、`status: passed`，没有给出证据的为 `unverifiable`，其余拦截（`rejected` 只列原因，不作为结论展示）。同一份脱敏后的请求在进程内缓存回复。实时检查默认不带 AI（防抖后的每次调用都请求 AI 代价太大），界面在保存与点击“AI 校验”时带上（D-0122）。未配置 AI 时 `ai.status = not_configured`，其余检查照常。

**项目、脚本、修订**：项目属于创建它的账号（`user_id`，API 令牌与命令行创建的为空）；普通账号只能看到自己的项目，管理员与 API 令牌看到全部（别人的项目返回 404）。修订：创建脚本、手动保存（内容与最新修订不同）、按依赖重排（重排前的内容未保存时先存一条 manual，再存 reorder 修订，`note` 记录移动与原因）、恢复（restore，`note.from_seq`）各形成一条；检查保存的内容时摘要记在脚本上（项目列表显示错误 / 警告数）。

**文本差异**：`difflib` 逐行对比；删除与新增中文本相同的行配成“移动”（a 第几行 → b 第几行），结构行（quit、exit、会话命令、分隔符）不参与移动配对、不计入统计；同一改动块中剩下的行按位置配对为“修改”，给出两侧改动的字符区间；忽略顺序时每行带上按缩进找到的视图路径，按多重集合比较。语义差异复用 `compare.compare`：基线与完整配置直接比较，变更脚本比较的是在基线上（按依赖顺序）执行后的结果。下载：统一 diff（文件头用对比对象的名称）与中 / 英 HTML 报告（复用报告的样式，相同的行只保留前后 3 行上下文）。

**测试**：单元 `tests/unit/test_script_check.py`（视图跟踪、两种脚本、顺序开 / 关、重排前后、Cisco、完整配置、AI 结果被代码拦截的各种情况与缓存、未配置 AI、文本差异与报告、项目 / 脚本 / 修订存储与归属，SQLite 与 PostgreSQL）；CLI 用例 `tests/cases/cli_cases.script_check.toml`；API 用例 `tests/cases/api_cases.check_projects.toml`（新的准备方式 `configured-fullkb-checkproj`）与 `tests/api/test_check_projects_api.py`（差异下载、按账号的归属、经接口的假 AI）；测试输入 `tests/inputs/scripts/`。

**AI 规则**：`knowledge/rules/style-ai.yaml`（M4-2 完成后新建）——接口描述、BGP 对等体描述、VPN 实例 / 路由策略 / 前缀列表命名规范，都是 `ai: true` 且没有 assert；`lmesh check` 不对它们求值、不计入 `rules_loaded`，规则列表与开关（`rule_edit`）照常可用。`canon.load_style` 按文件与修改时间缓存（增量变更与重排每个视图块都要取退出命令）。

**已知限制**：模拟执行的行树建立复制了 `change._Sim.__init__` 的逻辑（另记来源），`change._Sim` 的建树逻辑改动时需要同步；`implicit_exit` 对华为只是提示（VRP 是否自动回退到上层视图执行因版本而异）；冲突检查只查同一设备内的地址与 RD，不跨设备。


## 翻译自定义规则（REQ-032）

用户 2026-10-18 提出：配置翻译可以自定义命名规范、名称映射（支持模糊规则映射）、端口映射规则等。自动模式下按以下推荐做法实现（决策记录见 D-0131～D-0133），用户回来后可改。

- 规则集：一个规则集包含三类规则，按对象类型分组（VPN 实例、路由策略、前缀列表、ACL、团体属性列表、对等体组、桥域、QoS 策略等，取 Schema 中被引用的对象类型）。规则集保存为 YAML 文件：内置示例在 `knowledge/translate-rules/`，用户的规则集在 `data/translate-rules/`；可导入导出；翻译、割接迁移、批量生成都可以选用。
- 名称映射：按顺序匹配，第一条命中生效；匹配方式有精确、通配符（`*`、`?`）、正则（可用捕获组 `` 或 `{1}` 组成新名称）、大小写不敏感选项；没有命中的名称保持原样。
- 命名规范：每种对象类型可以设目标命名规则（正则）与自动整理动作（大小写、加前后缀、替换字符、截断到目标平台允许的最大长度）；映射后的名称不符合规范时告警，开启自动整理时按动作整理后再检查。
- 端口映射：精确映射、模式映射（如 `GigabitEthernet0/2/{n}` → `GigabitEthernet0/0/{n}`，`{n}` 可加偏移和范围）、按类型 / 速率映射；子接口随主接口一起映射（`.N` 保留）；与割接迁移的接口映射表合并，用户规则优先于自动建议。
- 在图上执行：改名在翻译前对源图进行，对象本身和所有引用它的地方一起改，由代码保证一致；结果中逐条列出“原名 → 新名、命中的规则”；两个不同的源名映射到同一个目标名、或映射到目标设备上已有的名称时报冲突，不静默合并。
- 预览：规则编辑时可以对选定的设备配置试运行，显示改名清单、冲突与命名规范告警，再正式用于翻译。

### 实现结果（REQ-032）

| 功能 | 模块 | CLI / API |
|---|---|---|
| 规则集模型、读写、匹配、在图上改名 | `core/naming.py`（`parse`、`load`、`save`、`delete`、`list_sets`、`map_name`、`resolve_name`、`map_port`、`test_input`、`run`、`port_map`） | `lmesh naming list\|show\|test\|match\|import\|delete`；`/api/v1/translate-rules`（列表、读取、`PUT` 保存、`DELETE`、`/{id}/export`、`/import`、`/match`、`/test`） |
| 接入翻译 | `translate.translate(…, rules=, target_graph=)`、`translate_text(…, rules=)` | `lmesh translate --rules`；`POST /translate` 的 `rule_set` / `rules` |
| 接入割接迁移 | `migration.migrate(…, rules=)` | `lmesh migrate --rules`（`--suggest-only` 也用端口规则）；`POST /migrate`、`POST /migrate/suggest-map` 的 `rule_set` / `rules` |
| 接入批量生成（只用于 `engine: canon`） | `template_gen.generate(…, rules)` | `lmesh template generate --rules`；`POST /templates/generate` 的 `rule_set` / `rules` |
| 内置示例 | `knowledge/translate-rules/atn-to-asr920.yaml`、`asr920-to-atn.yaml` | 用户的在 `data/translate-rules/` |
| 界面 | `views/TranslateRulesView.vue`（“模板与生成”组的“翻译规则”，`/translate-rules`）、`components/rule-set-picker.vue`、`views/translate-rules/NamingReportPanel.vue` | 翻译页、割接迁移页、批量生成页（canon）都有规则集选择框 |

**规则集文件**（YAML，ruamel 往返写回，保留注释与顺序；`PUT` 给结构化内容时合并进已有文件，给 `source` 时原样写入）：

```yaml
id: atn-to-asr920
title: {zh-CN: …, en: …, pt-BR: …}
from: huawei-vrp8            # 适用方向（可省）
to: cisco-iosxe
names:                       # 名称映射：按顺序，第一条命中生效
  - {type: vrf.instance, match: regex, from: "_+(.*?)_+", to: "{1}"}
  - {type: "*", match: wildcard, from: "OLD-*", to: "NEW-{1}", enabled: false}
naming:                      # 命名规范：每种对象类型第一条启用的规则
  - {type: rp.policy, pattern: "[A-Z0-9_]+", fix: true, case: upper, replace: [{from: "-", to: "_"}]}
  - {type: vrf.instance, pattern: "[A-Za-z0-9_-]+", max_length: 32}
ports:                       # 端口映射：按顺序，第一条命中生效
  - {match: type, from: Eth-Trunk, to: Port-channel}
  - {match: exact, from: Ethernet0/0/0, to: GigabitEthernet0}
  - {match: pattern, from: "GigabitEthernet0/2/{n}", to: "GigabitEthernet0/0/{n+1}", range: [0, 23]}
```

| 环节 | 做法 |
|---|---|
| 对象类型 | 被 Schema 中 `ref` 属性引用的单键对象（VPN 实例、路由策略、前缀列表、团体属性列表、ACL、对等体组、桥域、QoS 策略 / 行为 / 流分类、隧道策略、伪线模板、VSI、EVPN 实例等），`*` 表示全部；接口由端口映射处理 |
| 名称映射 | 精确；通配符（每个 `*`、`?` 是一个捕获组）；正则（整串匹配）；新名称用 `{1}`、`\1`、`{名字}` 引用捕获组，`{0}` 是整个原名；`ignore_case` 对三种都生效；校验时检查正则与引用的捕获组是否存在 |
| 命名规范 | 开启 `fix` 时依次 替换（正则）→ 大小写 → 前缀（已有时不加）→ 后缀 → 截断（保留后缀），再检查 `pattern`（整串匹配）与长度；长度上限取规则的 `max_length`，没写时取目标平台族 `knowledge/render/<族>.yaml` 的 `name_limits`（`{对象类型: 最大长度}`），都没有时不截断、不检查，结果 `gaps` 列出 `name_limit_unknown`（D-0137）。不符合时告警（`naming[]`：`problem` = `pattern` / `length`），不阻止改名 |
| 端口映射 | 按主接口的统一写法匹配：精确；模式（`{n}` 是数字，改为里可写 `{n+1}`、`{n-24}`，`range` 限定 n）；按类型（`from` 是接口类型，编号不变只换类型，`to` 含 `{` 时可用 `{rest}`、`{n}`；`speed` 按类型推出的速率过滤）；子接口随主接口（`.N` 保留，由翻译的接口映射完成） |
| 在图上改名 | 复制源图；对象的键、引用它的属性取值（Schema 的 `ref` 类型 + 图上的引用边，列表取值逐项）、复合键中引用它的字段（`bgp.af` 的 `vrf`、`static.route` 的 `vrf`）一起改；键改过的对象与子树重新编号，语句里的节点编号同步；源图不变 |
| 冲突（D-0138） | `many_to_one`（多个源名 → 同一新名）、`exists`（新名与未改名的同类对象重名）、`target_exists`（新名在目标设备现有配置中已有，迁移或给了 `target_text` 时）、`port_many_to_one`、`port_exists`：涉及的改名都不执行（保持原名），列在 `conflicts` |
| 原文行 | 未映射命令、功能域外原文、未识别行中出现的旧名不改，列在 `text_refs`（附行号与原文），人工处理 |
| 优先级（D-0139） | 翻译：显式 `interface_map` > 端口规则；迁移：用户映射表 > 端口规则 > 自动建议；不选规则集时结果与原来完全一致（没有 `naming` 字段） |
| 结果 `naming` | `renames[]`（`type`、`from`、`to`、`mapped`、`rule` {`section`, `index`}、`naming_rule`、`fixes`、`refs`、`ref_nodes`、`applied`、`conflict`、`node` / `new_node`、`lines`）、`ports[]`（`from`、`to`、`rule`、`subinterfaces`、`applied`）、`conflicts[]`、`naming[]`、`text_refs[]`、`gaps[]`、`summary` |
| 存放与权限（D-0135） | 内置规则集只读（保存 / 删除 409，可另存为）；登录用户都可以保存、删除 `data/translate-rules/` 中的规则集；编号规则同模板（字母数字开头，可含 `_ . -`） |
| 编辑器（D-0136、D-0140） | 规则集列表（内置 / 我的）、三个页签的有序表格（上移下移、启用开关、行内问题标记）、测试框（防抖调用 `/translate-rules/match`，不在前端复刻匹配）、试运行（设备或粘贴配置 + 目标 Profile → `/translate-rules/test`）、YAML 原文、导入导出 |

**回归**：内置 `atn-to-asr920` 用于现网 ATN → ASR 920：端口规则得到的映射表与 `samples/translate/atn-to-asr920.ifmap.yaml` 相同（16 个接口），另改名 3 个（`PERMITE-GMC` → `PERMITE_GMC` 等），`verify.unexplained = 0`；`asr920-to-atn` 用于 ASR 920 → ATN，`verify.unexplained = 0`。测试：`tests/unit/test_naming.py`、`tests/cases/cli_cases.naming.toml`、`tests/cases/api_cases.naming.toml`、`tests/api/test_naming_api.py`、`frontend/src/views/translate-rules/logic.test.ts`、`frontend/e2e/req032.spec.ts`。

**已知限制**：知识库还没有 `name_limits`（`knowledge/render/*.yaml` 是已有文件，本需求不改；建议补：华为 VPN 实例 31、路由策略 200、IP 前缀列表 169，Cisco VRF 32 等），在此之前长度检查只用规则里写的 `max_length`；名称按类型全局改，同名对象在不同父对象下（例如两个 BGP 实例的同名对等体组）一起改；端口映射不用于批量生成；预览页里的“只在不符合规范时整理”“备注保存为 YAML 注释”“删除移到回收站”“命中数统计”“端口不在目标清单时告警”没有实现（备注存为 `note` 字段）。

### 实现结果（REQ-031 界面）

按预览页 `DevelopDocs/ui-preview/REQ-031/` 实现（评审前先编码，D-0111）。导航在“变更”组：`/check-projects`（项目列表）与 `/check-projects/:id`（项目工作区，query `script` 当前脚本、`view=reorder|revisions|diff` 子页、`a` / `b` 对比两侧）。代码：`frontend/src/views/CheckProjectsView.vue`、`CheckProjectView.vue`、`views/check-projects/`（编辑器 `ScriptEditor.vue` 用 CodeMirror 6，D-0124；问题、模拟执行、重排、修订、差异各一个组件，纯逻辑 `logic.ts` 与 vitest），样式 `styles/req031.css`（规则加 `.r31` 前缀），文案 `i18n/pages/check-projects.json`（三语）。

- 编辑器：输入停顿 500ms 自动检查（新请求取消旧请求、丢弃过期结果），行号槽按级别画点（AI 来源空心），问题行波浪下划线（后端只给行号，整行标），顺序核查开启时另一列标出重排去向（↓13），点问题跳到行。
- 工具条：脚本类型、顺序核查（完整配置时置灰）、AI 一起校验与规则勾选（`ai-rules.configured=false` 时隐藏；保存与点“AI 校验”时带 AI，D-0122）、检查状态、保存（形成修订）、按依赖重排、修订记录、对比。
- 重排：前后并排与连线，每条移动“第 a 行 → 第 b 行”与原因，复检结果，“采用”保存为修订；修订记录：来源、作者、问题计数、预览、恢复、勾选两条对比；文本差异：A / B 选修订 / 脚本（含未保存内容）/ 基线，并排与上下视图、行内字符标记、移动标紫、忽略顺序、语义差异标签页，下载 .diff 与中 / 英 HTML 报告。
- 与预览页的差异：去掉一键修复按钮与行尾简短说明（后端没有修复建议与短标签）、列表概况的脚本类型分类计数（列表接口只给总数）、“隐藏了 N 条顺序问题”的计数（关闭时后端不返回）。
- 测试：vitest `views/check-projects/logic.test.ts`；e2e `frontend/e2e/req031.spec.ts`（导入基线 → 建项目 → 输入脚本出现行内问题 → 关闭顺序核查顺序问题消失 → 重排并采用 → 对比 → 修订恢复）。默认 `playwright.config.ts` 用构建后的静态页面，正式构建前用 `playwright.req031.config.ts`（e2e 后端 9311 + Vite 开发服务 5311）跑当前源码。


## 内置 AI skill（REQ-033）

用户 2026-10-18 提出：需要内置 skill，说明内置 AI 有哪些内置 skill，管理员有管理界面，并提供 skill 学习进化功能。自动模式下按以下推荐做法实现（决策 D-0146 起），用户回来后可改。

- 现状：内置 AI 有四项能力，提示词写在代码里——命令卡抽取（`core/ingest/service.py`）、配置问答（`core/ask.py` 的查询与回答两段）、配置生成（`core/ask.py`，经护栏）、脚本审查（`core/script_check_ai.py`，按 `ai: true` 规则）。
- skill 定义：编号、三语名称与说明、任务类型与模型配置键、系统提示词与提示模板、示例（few-shot）、允许使用的工具（图查询、护栏、规则等）、输出格式、输出必须通过的代码校验、启用状态、版本。内置 skill 放在 `knowledge/ai-skills/*.yaml`（只读）；管理员修改后的版本放在 `data/ai-skills/`，每次保存形成一个版本，可回滚到任一版本或恢复内置版本。上述四项能力全部改为从 skill 读取提示词，行为与现在一致（回归测试保证）。
- 管理界面（仅管理员，“系统”组）：skill 列表（启用 / 停用、当前版本、调用次数、代码校验通过率、被拦截比例、用户评价）、编辑（提示词、示例、工具、校验）、试运行（选样例，未配置 AI 时用假客户端演示流程）、版本历史与对比、回滚。
- 学习进化：
  - 收集：每次调用记录结果（代码校验通过 / 被更正 / 被拦截 / 无法校验）与用户反馈（点赞、点踩、更正）；记录与发给 AI 的内容一律先脱敏；只存数据库，可按天数清理（配置项 `ai.skill_log_days`，默认 90）。
  - 积累：校验通过且用户认可的案例成为候选示例，管理员可一键加入示例；失败案例自动进入该 skill 的回归测试集。
  - 进化：管理员发起“进化”，AI 根据失败案例与评价提出改进的提示词 / 示例，生成候选版本；系统用回归测试集分别运行新旧版本，按代码校验结果打分并并排展示；管理员批准后才发布，不自动上线。
- 未配置 AI 时：管理界面仍可查看与编辑，试运行与进化不可用并说明原因；核心功能照常。


### 实现结果（REQ-033 后端）

代码：`core/skills.py`（skill 模型、内置定义与管理员版本、保存 / 回滚 / 恢复内置、渲染、调用记录、反馈、回归集与候选示例、统计、进化记录）、`core/skill_runners.py`（每个 skill 的运行器：渲染 + 代码校验；试运行、回归运行、进化）、`api/routes_skills.py`（`/api/v1/ai/skills`）、`cli/cmd_skill.py`（`lmesh skill list|show|test|versions|rollback|evolve|approve`）；表 `skill_runs`、`skill_cases`、`skill_evolutions`（迁移 `0006_ai_skills`，接在 `0005` 之后）；新配置项 `ai.skill_log_days = 90`（1–3650，向导“AI 接口”一步与 `config/config.example.toml` 已同步）。预览页 `DevelopDocs/ui-preview/REQ-033/`（评审前先编码，D-0146）。实现中的取舍见决策 D-0153～D-0159。

**内置 skill**（`knowledge/ai-skills/*.yaml`，只读，D-0147）：

| 编号 | 能力 | 任务（模型配置键） | 必须通过的代码校验 |
|---|---|---|---|
| `card-extract` | 文档导入时修正命令卡语法（`core/ingest/service.py`） | `extract`（`ai.model_extract`） | 命令语法解析器能解析 |
| `ask-query` | 问答第一步：写图查询（`core/ask.py`） | `ask`（`ai.model_ask`） | 查询语法、对象类型、字段路径、设备名 |
| `ask-answer` | 问答第二步：只根据结果组织回答 | `ask`（`ai.model_ask`） | 逐句核对 facts / count |
| `config-generate` | 配置生成（经护栏） | `generate`（`ai.model_generate`） | 护栏：解析、入图、依赖、冲突 |
| `script-review` | 配置检查项目的 AI 一起校验（`core/script_check_ai.py`） | `script_check`（默认模型） | 规则、行、入图、适用对象、代码断言、证据 |
| `skill-evolve` | 进化用的元 skill | `merge`（`ai.model_merge`） | 回复是规定的 JSON，候选保留全部变量 |

**定义**：`id`、`version`（内置版本号）、三语 `title` / `description`、`task`、`used_by`、`enabled`、`system`、`prompt`、`templates`（附加模板：问答与生成的 `retry`）、`variables`（变量名、所在模板、三语说明）、`examples`（few-shot）、`tools`（gquery / schema / guard / rules / syntax / sanitize，说明性）、`output`（`format` json / text / config、`schema`）、`checks`（只读，由代码实现）、`samples`（试运行样例：输入 + 示例回复，每个 skill 一条通过、一条被拦截 / 被更正）。提示词里 `{变量}` 由代码填入，只替换登记过的变量名，其余花括号原样保留，`{{` / `}}` 是字面花括号；取值中的花括号不再展开。示例不为空时以 `Examples:` 块附在系统提示词之后。

**行为一致**：四项能力的提示词全部改为从生效的 skill 读取；内置定义由改造前的代码常量生成，`tests/unit/test_skills.py::test_builtin_prompts_identical_to_previous_code` 用逐字复制的旧常量与旧拼接函数比对系统提示与正文（含重试、空脚本等边界），原有测试全部通过。生成内置文件后，四个模块里的提示词常量删除（`_Q_SYSTEM`、`_A_SYSTEM`、`_G_SYSTEM`、`script_check_ai.SYSTEM`、`ingest.AI_SYSTEM`）。

**版本**：管理员保存 → `data/ai-skills/<编号>/versions/0001.yaml …`（只存可编辑字段 + `meta`：版本号、时间、作者、来源 edit / example / evolution、说明、基于哪个版本、进化编号），并设为生效；内容与生效版本相同时不新建版本。生效状态 `state.yaml`（`active`、`enabled`）；回滚只改指针、不新增版本，恢复内置 = 指向 builtin，版本文件不删除；生效的版本文件丢失时退回内置版本并写日志。保存时校验：系统提示与模板非空且不超过 50000 字、模板名与内置一致（不能增删）、不能出现未登记的变量（422 列出问题）；去掉了原来用到的变量只提醒（`warnings`，AI 会少一部分上下文）。停用 skill：问答与生成返回 409（`data.status: skill_disabled`），脚本审查 `ai.status = skill_disabled`，命令卡抽取跳过 AI；其余功能不受影响。

**调用记录与反馈**（D-0149）：每次实际调用 AI 记一条 `skill_runs`——skill、版本、来源（ask / generate / ingest / script_check；test 试运行、regression 回归、evolve 进化不计入统计）、调用者（网页账号编号与用户名，令牌为 `api-token`，命令行为 `cli:<系统用户>`）、代码校验结论（passed 通过 / corrected 被更正 / rejected 被拦截 / unverifiable 无法校验 / error 调用失败）、输入（重建提示所需的变量）、回复、校验明细、模型与 token；输入与回复写入前经 `ask.sanitize_text` 脱敏（同一密钥，脱敏是幂等的，回归运行再发送时不会二次变形）。结论的取法：查询每次尝试一条（校验通过 / 拦截）；回答按核对汇总（有被更正 → corrected，有通过 → passed，否则 unverifiable）；生成每轮一条（护栏通过 / 拦截）；脚本审查有被拦截的发现 → rejected，只有无法校验的 → unverifiable，其余 passed；命令卡抽取按能否解析。结果中 `skill_runs`（问答、生成）与 `ai.skill_run`（脚本审查；进程内缓存命中时沿用上次的记录）给出记录编号。反馈 `POST /ai/skills/feedback`：点赞 / 点踩 / 更正，`rating` 为空且没有更正时撤销；普通账号只能评价自己发起的调用（令牌发起的调用任何账号都可评价）。超过 `ai.skill_log_days` 天的调用记录在写入时顺带清理（每个数据库每小时最多一次）。

**回归集与候选示例**：线上调用被拦截或被更正时自动加入该 skill 的回归集；点踩、用户更正也加入（更正写在 `expect`）；校验通过且点赞的成为候选示例；同样的输入只留一条（按输入的哈希），每种最多 200 条；案例保存输入、回复与明细的副本，不随调用记录清理。案例“加入示例”：输入为当前版本渲染出的正文（脱敏后），输出取更正、没有时取原回复，形成来源为 example 的新版本。

**试运行**：样例 / 回归案例 / 手填输入，可带未保存的草稿定义（版本显示 `draft`）或指定版本；`mode: ai` 真实调用（未配置 AI 时 409），`mode: replay` 用样例或案例记下的回复（或给出的回复）走一遍渲染与代码校验，不需要 AI（“未配置 AI 时用假客户端演示流程”按回放实现）。回归运行不重新建图：问答查询按当前知识库与数据库中的设备校验；回答按记下的查询结果核对；生成按设备名取数据库中该设备的最新配置作为护栏基准（没有时按空配置）；脚本审查按记下的行类型、勾选的规则、调用时与图有关的拦截结论（not_in_graph / target_mismatch / code_disagrees，代码同样报出的记为 confirmed）与证据核对。

**进化**（D-0148）：管理员发起（需要配置 AI，回归集至少 1 条，skill-evolve 本身不能进化）→ skill-evolve 读取当前定义与最近 N 条回归案例（输入、回复、校验结论、更正，均为脱敏后）→ 返回候选的 system / prompt / templates / examples 与改动说明 → 代码检查候选保留了原模板中的全部变量并通过定义校验（不通过时进化记为 failed，不进入待批准）→ 回归集每条案例分别用旧版本与候选各调用一次，按代码校验打分（通过 1、无法校验 0.5、其余 0），记录每条的旧 / 新结论、得分与变好 / 变差 / 不变 → 存为 pending。管理员批准后候选保存为来源 evolution 的新版本并生效，放弃只改状态；已处理过的再次决定返回 409。API 默认后台任务（`task_id`，`GET /tasks/{id}` 轮询），`wait: true` 时同步返回；CLI 同步执行。

**测试**：单元 `tests/unit/test_skills.py`（提示词逐字回归、渲染、版本 / 回滚 / 恢复内置 / 校验、调用记录与反馈与统计与清理（SQLite 与 PostgreSQL）、脱敏、五个 skill 的回放样例、线上问答与生成的记录与停用、进化打分与批准、候选变量丢失时失败、案例加入示例，AI 都是假的客户端）；CLI 用例 `tests/cases/cli_cases.skills.toml`；API 用例 `tests/cases/api_cases.skills.toml`（普通账号 403、反馈对普通账号开放）与 `tests/api/test_skills_api.py`（假的 AI：问答 → 普通账号反馈 → 回归集与统计、试运行、同步与后台任务进化、批准、回滚，生成与停用）。

**已知限制**：`tools` 只是说明，代码按每个 skill 固定的流程调用工具，改动不影响实际行为；脚本审查的回归运行不重新建图，用调用时的结论近似；进化只改提示词与示例，不改输出格式与代码校验；统计按调用条数计，一次问答的两步分别计入两个 skill；一次进化在回归集上的调用次数是案例数的 2 倍，加 1 次提出候选。


### 实现结果（REQ-033 界面）

按预览页 `DevelopDocs/ui-preview/REQ-033/` 实现（评审前先编码，D-0146）。导航“系统”组（仅管理员）新增“AI skill”：`/ai-skills`（列表）与 `/ai-skills/:id?tab=def|test|stats|cases|versions|evolve`（详情），普通用户直接打开回到首页。代码：`frontend/src/views/AiSkillsView.vue`、`AiSkillView.vue`、`views/ai-skills/`（定义、试运行、统计、回归集、版本、进化六个标签页，变量高亮编辑器 `PromptEditor.vue`、差异 `DiffList.vue`，纯逻辑 `logic.ts` 与 vitest），反馈组件 `components/ai-feedback.vue`，样式 `styles/req033.css`（明暗两套），文案 `i18n/pages/ai-skills.json`（三语）。

- 列表：skill 数、近 30 天调用、平均通过率、待批准进化；每行启用开关（停用前确认）、生效版本、调用数、通过率条、被拦截比例、评价、回归集与候选数；未配置 AI 时顶部说明。
- 定义：系统提示词与模板编辑时高亮 `{变量}`，未登记的变量标红且不能保存；示例增删排序、工具、输出格式、只读的代码校验；保存说明写入版本历史。试运行：样例 / 回归案例 / 手填 JSON 输入，真实 AI 或回放（未配置 AI 时只能回放），显示发送内容、回复与逐项校验。统计：7 / 30 / 90 天每日堆叠条、按版本表、最近调用（详情弹窗读取单次调用）。回归集与候选：入集原因、加入示例、删除。版本：时间线、两版本逐字段对比（统一 / 并排）、回滚与恢复内置（只改生效指针）。进化：步骤条、后台任务进度、候选与基础版本差异、AI 说明（标明来自 AI）、回归集逐条新旧对比与总分、批准发布 / 放弃；未配置 AI 或回归集为空时不可用并说明原因。
- 反馈按钮（点赞 / 点踩 / 更正，可撤销）：AI 查询的回答下（记在回答一步）、AI 生成配置结果下（记在最终轮）、配置检查项目 AI 一起校验的摘要处（一次检查一组）。
- 与预览页的差异：版本与进化做成详情页的标签页；回滚不新增版本记录、没有说明框；去掉“每天生效的版本色带”（后端没有），换成按版本表；调用记录没有“问题”列（列表接口不带输入摘要），改为详情弹窗；进化不显示模型名、运行中只显示任务百分比与当前步骤；工具只显示名称；配置检查项目的反馈按次检查而不是按每条 AI 发现。
- 测试：vitest `views/ai-skills/logic.test.ts`；e2e `frontend/e2e/req033.spec.ts`（管理员：列表 → 编辑保存为 v1 → 未配置 AI 时进化不可用、试运行只能回放 → 版本对比 → 恢复内置 → 回滚；普通用户看不到入口），`playwright.req033.config.ts` 用独立端口（后端 9333、Vite 5333）与独立数据目录 `tests/output/e2e-req033-root`，后端由 `frontend/e2e/req033_server.py` 启动（`--fake-ai` 用假 AI 供本地查看“已配置”状态）。

### 评审修改：按功能分组（用户 2026-10-19 评审预览 skills.html）

- 用户意见：“skill 可以按照功能进行分组”。分组：问答（qa）、配置生成（generate）、日常分析（analysis）、变更与割接（change）、规范与合规（compliance）、知识库构建（kb）、报告（report）、skill 进化（evolve），另有“其他”（other，没写或写错 group 的 skill）；M8（REQ-041）新增的约 21 个 skill 放进已有的组。
- 定义：组编号与三语组名只在 `knowledge/ai-skills/_groups.yaml` 定义（顺序即显示顺序；`_` 开头的文件不是 skill）；每个 skill 的 `<编号>.yaml` 用 `group` 字段引用。现有 6 个：ask-query、ask-answer → qa；config-generate → generate；script-review → compliance；card-extract → kb；skill-evolve → evolve。
- 接口：`GET /ai/skills` 每个 skill 带 `group`，另返回 `groups`（`id`、三语 `title`、`count`），可用 `?group=` 只列一组；CLI `lmesh skill list` 按组排序、加“分组”列，`--group <编号>` 只列一组（不存在退出码 2）。
- 界面：列表按组显示，组可折叠、显示个数、可按组筛选，搜索跨组；预览页 `DevelopDocs/ui-preview/REQ-033/skills.html` 已同步。


## 设备配置分析（REQ-034）

用户 2026-10-18 提出：设备配置分析，结构化脚本显示，查看配置分层视图、TCP/IP 模型视图、配置关系视图（图结构）等。自动模式下按以下推荐做法实现（决策 D-0150 起），用户回来后可改。

- 一个页面、五个视图，从设备列表或设备配置图进入，视图之间选中对象联动（同一个节点在各视图中同时高亮）：
  1. 结构化脚本：配置原文按视图块折叠展开，行号；命令关键字、参数取值、对象引用分色显示；点引用跳到被引用对象的定义，可列出某个对象的全部引用处；未识别行、功能域外原文行、隐藏的默认值（可开关，按 REQ-028 的样式）分别标出；可按功能域筛选；显示风格随华为 / Cisco 切换。
  2. 配置分层视图：沿用设备配置图的视图层级（华为按视图、Cisco 按功能域），在本页与其他视图联动。
  3. TCP/IP 模型视图：按五层归类——物理层（端口、速率、光模块等）、数据链路层（链路聚合、VLAN、子接口封装、二层业务、LLDP 等）、网络层（IP 地址、VRF、静态路由与路由协议、路由策略、ACL）、传输层（BFD、TCP 相关的会话参数，如 BGP 会话与计时器）、应用层（SNMP、NTP、SSH、AAA、日志等管理面）；MPLS / SR / L2VPN / EVPN 作为“2.5 层”在数据链路层与网络层之间单列；QoS、时钟同步按其作用层标出并可跨层显示。层与 Schema 的对应关系写在知识库新文件 `knowledge/layers.yaml`，由代码按 Schema 节点归类（未登记的节点归入“未分类”并在校验中提示）；跨层依赖（例如 BGP 依赖接口地址、接口依赖物理端口）用连线显示。
  4. 配置关系视图：沿用关系图谱（力导向，可拖动），另加按 TCP/IP 层分带的布局。
  5. 分析摘要：各功能域对象数量、配置检查发现、未识别行与原文行数量、依赖默认值的关键配置、安全基线得分、与上一版本相比的变化；每项可跳到对应视图。
- 计算都在后端由代码完成（`core/layers.py` 与分析接口），前端只负责显示；不需要 AI。

### 实现结果（REQ-034）

- 层的归类（决策 D-0160、D-0161）：`knowledge/layers.yaml` 分 `layers`（自下而上 physical、datalink、mpls（2.5 层）、network、transport、application，三语名称与说明）、`features`（QoS、时钟同步：按编号前缀 `match` 标记，`span` 是作用的层）、`objects`（每个对象类型必须登记，现有 112 个全部登记）、`attrs`（作用层与所属对象不同的属性，例如 `interface.vrf` 在网络层、`interface.mtu` 在数据链路层、BGP 计时器在传输层、路由协议里的 SR 参数在 2.5 层）、`keys`（同一对象按键正则细分，不分大小写：子接口与 Eth-Trunk / Port-channel 在数据链路层，LoopBack / Vlanif / VBDIF / BDI / Tunnel 在网络层）、`domains`（功能域缺省层，只在对象没有登记时兜底）。`core/layers.py` 计算：对象按 objects + keys，属性按 attrs 否则跟随所属对象，ext / raw / unknown 跟随所属对象（不在对象下的原文行不归层，计入 `outside`）；跨层依赖 = 引用与前置依赖边两端所属的对象、以及包含关系中的父子对象，层不同的按（对象对, 边类型）合并计数，副作用与互斥不算。`lmesh kb validate` 对没有登记的对象给警告 `layers.unclassified`（运行时知识库没有 layers.yaml 时用程序自带的，此时不报“登记了不存在的节点”）。
- 接口（决策 D-0162）：`GET /api/v1/devices/{id}/analysis?parts=summary,layers,script,graph&version_id=&defaults=true` 与 `POST /api/v1/analysis`（文本），`parts` 写错 422，没有能解析该配置的 Profile 时 422；CLI `lmesh analyze <文件|设备名> [--part summary|layers|script]… --output json`（默认 summary 与 layers）。实现在 `core/config_analysis.py`（摘要、结构化脚本）与 `core/layers.py`，CLI 与 API 共用。
- 分析摘要：`lines`（各类行数与覆盖率）、`domains`（各功能域对象 / 显式属性 / 默认值 / 涉及行数）、`layers`、`cross_layer`、`dangling`、`defaults`（依赖默认值的关键配置：取值来自 Profile 默认值、而其他平台族默认值不同的属性，决策 D-0163）、`unknown_lines`、`check`（与配置检查相同的规则、内置检查覆盖与设备的忽略记录，列前 20 条）、`baseline`（basic 基线的得分与不符合项；基线文件有错时为 null）、`history`（与上一快照相比的对象级变化，第一个版本时 previous 为 null；文本分析时为 null）。
- 结构化脚本（决策 D-0164）：每行 `no`、`kind`、`text`、`depth`、`parent`、`node`（这一行产生的最深节点）、`layer`、`domain`、`card`、`spans`（`s` / `e` 字符区间、`t` kw / param / ref、`p` 参数名、`ref` 引用目标）；`refs`（目标 → 引用行）、`defs`（目标 → 定义行，隐式对象为 null）、`defaults`（隐藏的默认值：所属对象、插在哪一行之后、该平台的命令写法）。区间按命令卡匹配出的参数取值在原文中定位，不重复解析；默认值行的写法取规范渲染 include_defaults 的结果（现网 ATN 约 2 秒，`defaults=false` 时约 0.5 秒）。
- 界面（决策 D-0165，预览 `DevelopDocs/ui-preview/REQ-034/`）：导航“设备配置”组新增“设备配置分析”（`/analysis/:id`，query `view`、`node`、`line`），设备列表每行与设备配置图页头有入口。五个页签 + 右侧常驻“选中对象”面板（命令写法随显示风格、规范编号、层与跨层特性、配置行、被引用处、定义行、跨层依赖、在其他视图中查看），选中跨页签保持并自动定位。结构化脚本虚拟滚动（只渲染窗口内的行，现网 2267 行渲染约 50 行）、折叠 / 全部折叠、按功能域筛选、显示默认配置（REQ-028 样式）、点引用跳到定义并闪烁；配置分层复用设备配置图的树状图（华为按视图、Cisco 按功能域）；TCP/IP 模型六条横带（应用在上，2.5 层斜纹缩进），同层子对象由父对象代表，作用层不同的属性单独成组，跨层依赖按对象类型汇总画细线、选中对象画自己的带箭头连线并描边对端，右侧竖条是 QoS、时钟同步；配置关系复用关系图谱组件（`ForceGraph` 新增 `layout="bands"`、`bands`、`colorOf`），“按层分带”用预设位置网格与每层背景带，跨层的引用 / 前置依赖橙色加粗；分析摘要六格与各段列表都可跳到对应视图或脚本行。层的颜色 `--ly-*` 借用功能域分类色，明暗两套。
- 测试：`tests/unit/test_layers.py`（全部 Schema 对象已归层、未归层提示、按键细分、跨层边、现网样本分层、区间与引用、默认值行位置、摘要数值、跨平台默认值）、`tests/cases/cli_cases.analysis.toml`、`tests/cases/api_cases.analysis.toml`、前端 `src/views/device-analysis/*.test.ts`、端到端 `frontend/e2e/req034.spec.ts`（从设备列表进入 → 点引用跳到定义 → TCP/IP 选中与跨层描边 → 关系视图按层分带联动 → 摘要跳回脚本；现网大配置虚拟滚动、显示风格切换、暗色主题）。

### 评审修改：TCP/IP 视图合并相似（用户 2026-10-19 评审预览 analysis.html#tcpip）

- 用户意见：“相似的可以选择合并一起显示”。预览 `DevelopDocs/ui-preview/REQ-034/analysis.html#tcpip` 工具条右侧加“合并相似”开关（`?merge=0` 看不合并的样子）。
- 规则（决策 D-0258，纯函数 `frontend/src/views/device-analysis/layers.ts` 的 `mergeSimilar`、`mergedText`）：同一层同一分组（同一对象类型）内，对象的键（显示标签）去掉末尾编号后相同、且不少于 3 个的合并成一个范围格子，例如“GE0/2/1–8 ⑧”、子接口“GE0/2/1.101–108”；IPv4 / IPv6 地址（对等体、接口地址等）末尾的数字不是编号，不合并（避免被误读成连续地址段）；成员按编号排序，合并格子放在第一个成员原来的位置；属性格子与没有末尾编号的对象不合并；接口名用简写（GigabitEthernet → GE 等）。
- 合并格子代表全部成员：成员被选中或与选中对象相关时整格高亮；选中对象的跨层连线画到合并格子上，同一对格子之间只画一条；按类型汇总的细线不变。点合并格子展开逐个查看（虚线框内列出成员，末尾“⟨ N”收起）。
- 默认开启（现网 2000+ 行配置中接口、子接口、IPv4 地址等格子成百上千，合并后可读性明显更好；小配置不足 3 个不合并，几乎不受影响）；开关在 TCP/IP 视图内吸顶显示，状态记在浏览器（`lmesh-flag-analysis-tcp-merge`）。
- 测试：`layers.test.ts`（合并阈值、排序与位置、子接口与地址、属性不合并）、`frontend/e2e/req034.spec.ts`“TCP/IP 视图合并相似”（现网大配置：默认合并、展开选中成员、收起后整格高亮、关闭合并后逐个显示、刷新后保持）。


## 删除设备与配置版本（REQ-038）

用户 2026-10-19 提出：删除设备与单个配置版本，确认对话列出连带删除的内容，被配置检查项目作基线时提示，最后一个版本不能单独删除。现阶段所有登录账号（含普通用户与 API 令牌）都可删除，删除记入日志；M6 起按项目权限（属主与“可编辑”成员，见“权限模型（REQ-036）”）另做。

### 实现结果（REQ-038）

- 核心 `core/device_delete.py`（CLI 与 API 共用，决策 D-0180～D-0183）：
  - `preview`：将删除的内容计数（`versions`、`imports`、`nodes`、`edges`、`unknown_lines`、`check_ignores`）、以该设备为基线的配置检查项目与脚本（`baseline.projects`：`version_id`、`follows_latest`、`scripts`）、`blocked`、每个版本（`seq`、`latest`、`imports`、`pinned_by`）；不删除。
  - `delete_device`：一个事务内按子表到父表显式删除边、节点、未识别行、导入记录、配置版本（含快照 `graph_gz`）、检查忽略项、设备，不依赖数据库级联，SQLite 与 PostgreSQL 一致；设备是检查项目的基线时默认拒绝（data 为删除预览），`force` 时把这些项目的基线设备与版本置空（脚本与修订保留，`baseline_cleared`）。
  - `delete_version`：最后一个版本拒绝；删除最新版本后“最新”自然指向上一个版本，跟随最新版本的项目随之改用它（`baseline_moved`，只提示）；被项目固定为基线的版本默认拒绝，`force` 时这些项目改为跟随最新版本；删除较早的版本后下一个版本的变化计数置空并重算（`recomputed`，没有知识库时查看时间线再算）。
  - 删除后清空配置检查项目的基线图缓存；日志 `lmesh.devices` 记录操作者（会话账号名，令牌记为 `api-token`，CLI 为操作系统用户名）、设备名与编号、删除的版本个数，不记录配置内容。
- 接口：`GET /api/v1/devices/{id}/delete-preview`、`DELETE /api/v1/devices/{id}?force=`、`DELETE /api/v1/devices/{id}/versions/{vid}?force=`；被作基线、最后一个版本时 409（错误码 1003），设备或版本不存在、版本不属于该设备时 404。CLI `lmesh device delete <设备> [--force] [--yes]`、`lmesh device delete-version <设备> <版本> [--force] [--yes]`（版本写法同 `lmesh history`），终端里先确认，`--output json`，拒绝时退出码 1，不存在退出码 4。
- 界面（预览 `DevelopDocs/ui-preview/M6/devices.html` 的删除确认框）：共用确认框 `components/devdel-dialog.vue`（打开时取删除预览，列出连带删除 / 保留的内容与数量；作基线的项目与脚本用警告框列出，勾选“仍然删除”后才能确认；删除最新版本时提示跟随最新版本的项目将改用哪个版本；最后一个版本只显示说明）。设备列表每行末尾、设备配置图页头有“删除设备”，版本历史的“全部快照”表与 A / B 卡片有“删除此版本”（只剩一个版本时不可用）。文案三语，颜色只用主题变量。
- 测试：`tests/unit/test_device_delete.py`（级联、其他设备不受影响、基线拒绝与 force、最后一个版本、删除最新 / 中间版本与变化计数重算、固定版本、版本不属于该设备；SQLite 与 PostgreSQL 各一次）、`tests/cases/cli_cases.device_delete.toml`、`tests/cases/api_cases.device_delete.toml`、`tests/api/test_device_delete_api.py`（普通用户删除的完整流程）、前端 `src/views/devices/deleteLogic.test.ts`、端到端 `frontend/e2e/req038.spec.ts`（导入两个版本 → 版本历史删除一个版本 → 设备列表删除设备，暗色主题）；`frontend/e2e/req031.spec.ts` 结束时删除自己建的项目与导入的 ATN-CHANGE-01。

## 用户工作空间与项目（REQ-035）

用户 2026-10-19 提出：每个账号有单独的用户工作空间数据，可以创建项目，每个项目有单独的脚本。以下设计经用户在对话中确认（【用户确认】），排期为新里程碑 M6（0.6.0），M5 开发收尾后开始，先做预览页确认再编码。

- 三层结构：
  - 系统（全员共享，管理员维护）：知识库（命令卡、Schema、Profile、检查规则、术语表）、内置模板 / 翻译规则集 / AI skill、系统设置、账号、**公共设备库**。
  - 用户工作空间（每个账号一个，登录后自动拥有）：我的翻译规则集、我的模板（跨项目复用）、我的项目。
  - 项目：设备（私有设备与对公共设备的引用）、配置版本与版本历史、配置图、脚本（变更脚本与完整配置，含边写边查、修订、重排、diff、AI 校验——即现有配置检查项目并入）、检查忽略项、对比 / 检查 / 基线结果、报告与导出记录、项目设置（默认显示风格、选用的规则集、基线等）。
- 设备归属【用户确认：两者都有】：公共设备库 + 项目私有设备。项目可以引用公共设备，也可以导入自己的设备；可以把公共设备或其他项目的设备复制成项目私有的一份。
  - 公共设备库只由管理员维护（导入设备与新版本）【用户确认】；普通账号只能引用或复制。
  - 引用的版本【用户确认】：默认跟随公共库的最新版本；项目可以固定到某个版本（例如割接前的基线），公共库有新版本时提示。
- 项目共享【用户确认：可以邀请成员】：项目属主可以邀请其他账号为成员，角色为“可编辑”或“只读”；不邀请就只有自己能看。项目可以转交给其他账号。
- 管理员【用户确认：可以查看和修改】：管理员对所有工作空间和项目有完全权限；管理员访问他人项目的操作记入日志；删除账号时可以把其项目转交给别人或一并删除。
- 现有数据【用户确认】：升级时自动为第一个管理员建“默认项目”，现有设备、配置版本、导入记录、检查忽略项都移入其中（私有设备）；已有的配置检查项目按属主各自转为项目（属主为空的归第一个管理员）。
- 页面：顶栏项目切换器；设备列表、配置图、对比、检查、清理、翻译、变更、影响分析、拓扑与一致性、割接迁移、基线、版本历史、表格导出、设备配置分析等页面只看当前项目的数据；“我的项目”页（新建、成员、转交、复制、删除）；管理员的“所有项目”与“公共设备库”页。
- API 与命令行：每个账号可以生成自己的 API 令牌（只存哈希，可撤销），用它调用只能访问自己有权限的项目；原全局令牌保留，等同管理员；设备相关接口带项目参数（路径或查询参数，实现时定）；命令行加 `--project <项目>`。


### 实现结果（REQ-035，M6 后端结果）

M6-2（用户工作空间与项目）与 M6-4（个人 API 令牌）的后端；界面在 M6-5 做。决策 D-0195～D-0206（另有设计阶段的 D-0172～D-0179）。

- 数据（迁移 `0007_projects`，接在 `0006` 之后，SQLite 与 PostgreSQL 都测过从 0006 样本数据升级）：`projects`（标识 `slug`，原为全站唯一，M6-7 起按属主唯一，见下文“标识按属主唯一”、属主、设置 `settings`：`style` 显示风格 / `rule_set` 翻译规则集 / `baseline` 安全基线、`migrated_from`、`last_activity`）、`project_members`（edit / read）、`workspaces`（每个账号一个，记录默认项目）、`project_device_refs`（引用公共设备，`version_id` 为空表示跟随最新）、`project_rule_overrides`、`api_tokens`、`audit_events`、`user_assets`（我的模板 / 我的规则集的归属）；`devices` 增加 `project_id`（为空 = 公共设备库）、`origin`（import / copy / migrated）、`origin_note`，名称由全局唯一改为项目内唯一；`check_ignores` 增加 `project_id`（同一台公共设备在不同项目里的忽略互不影响）；`check_projects` 增加 `project_id`。SQLite 重建被引用的表时会级联删除子表，`store.upgrade` 在迁移期间关闭外键。
- 升级（用户确认的做法，D-0204）：每个账号建工作空间；有账号或有设备时建默认项目（标识 `default`、名称“默认项目”，属于第一个启用的管理员；没有账号时属主为空，第一个管理员创建后接管所有没有属主的项目），现有设备、配置版本、导入记录、检查忽略项移入（`origin = migrated`）；已有的配置检查项目各自转为项目（标识由名称生成，属主为空的归第一个管理员），基线设备只复制作为基线的那一个版本为该项目的私有设备（D-0175），固定的基线版本对应到复制出的版本；属主的默认项目设为他的第一个转出的项目。
- 当前项目（D-0197）：`core/projects.py` 用上下文变量保存当前项目与调用者；`importer.list_devices`、`workbench.device_rows`、`graphstore.latest_version / build_for_version`、`compare.versions / side_from_*`、`history` 的时间线与标签、`ignores`、`device_delete`、`checkproj`、`report.version_meta`、`script_check.baseline_from_db`、未识别行汇总都按它过滤；不在项目里的设备与版本一律按“不存在”处理（404）。没有当前项目时不过滤（单元测试直接调用 core、管理员的全局操作）；普通账号调用全局接口时当前项目为其默认项目（延迟解析）。引用并固定了版本的公共设备，“最新版本”取固定的版本（设备列表的 `latest_version_id`、对比 / 检查 / 拓扑 / 导出用的当前版本），版本列表另标 `current`。
- 设备归属（D-0200）：导入落到当前项目（没有当前项目时为默认项目），同名设备在项目内作为新版本；`public=True`（管理员的公共设备库导入）时落到公共设备库。项目里引用了同名公共设备时导入拒绝（`import.name_is_public_ref`）；引用时已有同名设备 409；复制为私有（`copy_device`）只复制一个版本，同名时自动加 `-2`、`-3`，`origin_note` 记录来源项目、设备与版本序号。项目里对公共设备只能查看、计算、解除引用（“删除”= 解除引用，本项目对它的忽略项一并删除、以它为基线的检查项目基线置空）；贴标签与删除版本只限管理员。公共设备还有项目引用时不能删除（409 列出项目，`force` 一并解除引用）。
- 项目操作（`core/projects.py`，CLI 与 API 共用）：新建（还没有默认项目时成为默认项目）、修改（属主与可编辑成员；改标识只限属主与管理员）、删除（属主与管理员；确认标识必须一致；私有设备与全部版本、检查项目与脚本、忽略项、规则调整、成员、引用一并删除，D-0173）、成员（邀请 / 改角色 / 移除只限属主与管理员，成员可以自己退出）、转交（原属主默认留作可编辑成员；项目设置用到的原属主私有规则集复制一份给新属主，D-0179）、复制（能查看即可，只读成员也可以：设置、规则调整、私有设备的当前版本、引用、脚本当前内容，不复制成员）、默认项目。
- 配置检查项目并入项目（D-0199）：`check_projects` 作为项目里的“脚本组”（共用基线与检查设置），原有 `/check-projects` 接口挂到项目路径下；新增 `GET/POST /projects/{p}/scripts` 平铺列出与新建脚本（新建时同时建一个只含这份脚本的组）。
- 接口与兼容（D-0195）：设备相关接口挂在 `/api/v1/projects/{project}/…`（`{project}` 为标识、`属主/标识` 或编号）；旧路径保留为兼容别名，落到调用者的默认项目，OpenAPI 标为 deprecated，响应头 `Deprecation: true` 与 `Link: <…/projects/<默认项目>/…>; rel="successor-version"`。项目管理接口只在项目路径下（`/projects/{p}`、`/members`、`/transfer`、`/copy`、`/delete-preview`、`/refs`、`/devices/copy-in`、`/rules`、`/scripts`）；全局接口：`/projects`、`/workspace`、`/public-devices`（查看所有人，导入 / 删除管理员）、`/admin/projects`、`/admin/audit`、`/tokens`、`/kb/suggestions`、`/users/{u}/projects`。`/devices/rebuild` 旧路径为全部设备（只限管理员），项目路径为本项目的设备。
- 个人令牌（`core/tokens.py`，D-0177、D-0201）：`lmp_` + 32 位字母数字，只在创建时返回一次，只存 SHA-256，列表与日志只显示前 8 个字符（日志过滤器也会截断）；可选只读（只能调用查看与计算接口）、有效期默认 90 天（0 / null 不过期，最长 3650 天）；记录最后使用时间与地址（至多每分钟写一次）；撤销立即失效，有效的令牌先撤销才能从列表移除；账号停用时不可用，删除账号时一并删除；每个账号最多 50 个有效令牌。`require_token` 认出 `lmp_` 开头的令牌，`Principal.via = "pat"`、`read_only`。
- 删除账号（D-0203）：拥有非空项目时必须 `transfer_to`（项目、私有模板与规则集转交）或 `delete_projects`；自动建的空默认项目直接删除。
- 审计（D-0202）：管理员访问不是自己参与的项目时，写操作每次记录、只读访问同一项目 30 分钟记一次“进入项目”；转交、管理员删除项目、删除账号时处理的项目也记录。写入 `audit_events`（`GET /admin/audit`）与 `lmesh.audit` 日志（`logs/audit.log`，保留天数同 `log.keep_days`），只有方法与路由，不含请求内容。
- 命令行（D-0196）：全局 `--project <项目>`（`-P`，立即解析，不存在退出码 4；不带时默认项目）与 `--as <账号>`（默认第一个启用的管理员）；`lmesh project list|show|create|delete|members|transfer|copy|default|ref`、`lmesh token create|list|revoke`、`lmesh public-device list|import|delete`；`lmesh user add/set-role` 接受 `maintainer`，`lmesh user delete --transfer-to / --delete-projects`。命令行直接操作本机数据库，权限等同管理员。
- 测试：单元 `tests/unit/test_projects.py`（迁移 0007 从 0006 样本升级、项目内可见性、引用与固定版本、复制、删除项目、成员与转交、规则调整、默认项目与第一个管理员接管、检查项目归属、个人令牌；SQLite 与 PostgreSQL 各一次）；API 用例 `tests/cases/api_cases.projects.toml`（新准备方式 `configured-projects`）与流程用例 `tests/api/test_projects_api.py`（项目流程、公共设备库与固定版本、兼容别名与响应头、个人令牌、知识库权限与建议、私有模板与规则集、删除账号、权限矩阵）；CLI 用例 `tests/cases/cli_cases.projects.toml`。
- 留给 M6-5（界面）：项目切换器与 `/p/<项目>/…` 路由（D-0172）调用项目路径接口；设备列表行的 `source` / `policy` / `newer_available` / `origin_note` 支撑“添加设备”“公共 · 跟随最新 / 固定”等标记；`GET /projects` 的 `counts` 与 `last_activity`（`action` 为“方法 路由”，界面按路由给出三语说明）支撑“我的项目”卡片；`GET /admin/projects`、`GET /admin/audit`、`GET /public-devices` 支撑管理员页面；`GET /workspace` 支撑顶栏。

- 标识按属主唯一（用户 2026-10-19 评审 M6 预览时改选“每个属主内唯一”，原先按推荐的“全站唯一”实现，决策 D-0174 已标为改回；
  M6-7 实现，决策 D-0230～D-0234）：
  - 数据：迁移 `0008`（接在 `0007` 之后，不改 0007）把 `projects` 的唯一约束从 `slug` 改为 `(owner_id, slug)`；属主为空的项目（没有账号时迁移出的默认项目）
    之间标识也不能重复（部分唯一索引 `uq_projects_ownerless_slug`）；第一个管理员接管它们时与他已有的标识重名就加编号。SQLite 与 PostgreSQL 都测过从 0007 样本数据升级。
  - 解析 `{p}` / `--project`（`core/projects._find`）：`属主/标识`（接口路径里写 `属主%2F标识` 或 `属主~标识`）精确；只写标识时先找调用者自己的
    （全局令牌与没有账号的命令行为第一个管理员的），没有时在调用者能访问的项目（成员；管理员为全部）里找，唯一匹配就用它，多个时报错
    （API 409 / code 1003，命令行退出码 2，键 `projects.ambiguous`，`data.candidates` 列出 `属主/标识`），不静默挑一个；编号仍可用。
  - 新建、复制、改标识时只在属主自己的项目里查重（“你已有同名项目”）；转交时新属主已有同名标识返回 409 并在 `data.suggested` 给出可用的标识，
    可以用 `slug`（命令行 `--slug`）同时改名；删除账号整批转交时遇到重名自动加编号。新账号的默认项目标识由 `<用户名>-default` 改为 `default`。
  - 规范引用：项目返回体增加 `ref`（自己的项目与属主为空的项目写标识，别人的写 `属主/标识`）与 `full_ref`（总是 `属主/标识`）；
    前端网址、最近用过的项目、旧路径的 `Link` 头、命令行 `project list` 都用 `ref`；公共设备库的引用列表、复制设备的来源说明用 `full_ref`。
  - 前端：项目路由改为 `/p/:project+/…`，自己的项目 `/p/<标识>/…`，别人的 `/p/<属主>/<标识>/…`（页面路径里的编号段只接受数字，两种写法不会混淆）；
    网址不是规范写法时换成规范网址；只写标识而有歧义时回到“我的项目”并列出候选；接口路径把 `属主/标识` 编码成 `%2F`（服务端在路由前还原，
    `api/scoping.add_project_ref_rewrite`）；新建项目重名提示“你已有同名项目”，转交时新属主重名在对话框里改用新标识。
  - 测试：单元 `tests/unit/test_project_refs.py`（迁移 0008、解析与歧义、改标识与转交、删除账号批量转交、属主为空的项目）；API `tests/api/test_project_refs_api.py`
    （两个用户同名项目互不影响、成员访问别人的同名项目、歧义 409、管理员与全局令牌、转交重名、Link 头）；CLI 用例 `project-same-slug-*`、`project-list-refs`
    （准备方式 `configured-samename`）；vitest（路由参数、规范引用、歧义候选）；e2e `m6.spec.ts` 的同名项目用例。

### 实现结果（M6 前端）

M6-5 的界面，按 `DevelopDocs/ui-preview/M6/` 的预览实现。决策 D-0214～D-0222。

- 当前项目（D-0214、D-0215）：`frontend/src/project/scope.ts` 保存与后端 `api/access.py` 一致的项目接口清单，`api.ts` 把旧路径自动改写为 `/api/v1/projects/<当前项目>/…`（管理员“重新解析全部设备”显式走旧路径）；`stores/project.ts` 记录当前项目、我的角色与权限（`canWrite`、`canManage`、`foreign`），最近用过的项目按账号记在浏览器，取不到时用工作空间的默认项目。
- 路由：设备、配置图、设备分析、版本历史、未识别行、对比、检查、清理、翻译、变更、项目脚本、割接迁移、影响分析、拓扑、一致性、基线、表格导出、添加设备、项目设置在 `/p/<项目>/…`；首页、AI 查询、模板、知识库等保持原地址，数据来自当前项目；旧地址（含 `/check-projects`）重定向到当前项目的对应页；项目不存在或无权访问时回到“我的项目”并说明。
- 外壳：顶栏项目切换器（搜索、我的 / 共享给我的、管理员的所有项目，进入他人项目前确认）；导航里的“当前项目”带；管理员在他人项目、只读成员、只读令牌时显示提示条；用户菜单加“我的 API 令牌”“我的项目”；管理员分组加“公共设备库”“所有项目”。
- 新页面：我的项目、项目设置（常规、默认设置、规则调整、成员、转交与删除）、添加设备（公共库引用 / 复制、其他项目复制、上传，可混合，逐条执行并报告）、项目脚本（原配置检查项目并入）、个人 API 令牌、升级说明、公共设备库、所有项目（含访问审计）。
- 改动的页面：设备页（来源与版本标记、固定版本有新版本时的提示、行尾菜单：改版本策略、复制为私有、解除引用、重新解析、复制到我的其他项目、删除）；账号管理（维护员角色、拥有的项目与令牌数、删除时转交或一并删除、权限矩阵）；模板（我的 / 共享、复制为我的、提建议）；翻译规则集（内置 / 共享 / 我的）；知识库各页对普通用户只读并可提建议，审核队列加“建议”页签，发布与回滚对维护员开放；只读成员看不到导入、重新解析、删除、忽略、贴标签、脚本保存等修改操作（以后端 403 为准）。
- 后端小补丁：设备行增加 `pinned_seq`（固定版本的序号，D-0216），API 测试已补。
- 测试：vitest（路径改写、旧网址、最近活动映射、设备行菜单、各新页面的纯逻辑）；e2e `frontend/e2e/m6.spec.ts`（新建项目 → 引用公共设备并固定版本 → 邀请只读成员 → 只读成员看不到修改按钮；旧网址重定向），`req031.spec.ts` 改为从项目脚本页新建。

## 权限模型（REQ-036）

用户 2026-10-19 询问哪些功能用户可以查看修改（如知识库）。现状：除知识库发布 / 回滚 / 放弃草稿、账号、系统设置、AI 接口与 AI skill 管理外，普通用户可以修改 Schema、Profile、审核命令卡、导入知识库包、改检查规则与模板、重新解析全部设备——共享内容会被任何人改动。以下经用户确认（【用户确认】），随 M6 实现：

- 角色：管理员、知识库维护员（新增）、普通用户。管理员可以给账号设置维护员角色。
- 知识库（Schema、Profile、命令卡审核、映射、知识库包导入、术语表）：管理员与维护员可以修改和审核；发布、回滚、放弃草稿仍为管理员与维护员（实现时确认是否只限管理员）；普通用户只读，可以提交建议（未识别行送审、对节点或默认值提修改建议），建议进入审核队列由维护员处理。
- 共享的检查规则、安全基线、内置 / 共享模板：只有管理员与维护员可以修改；普通用户可以在自己的工作空间建私有模板，在项目中关闭某条规则或调整级别（只影响该项目）。
- 重新解析：全部设备只限管理员；用户可以重新解析单台设备或本项目的设备。
- 删除设备与配置（REQ-038）：属主与“可编辑”成员可以删除项目内的设备与配置版本；只读成员不可；公共设备库只有管理员可删；项目中引用的公共设备“删除”即解除引用。
- 其余功能（设备导入、对比、检查、翻译、变更、拓扑、基线、版本历史、表格导出、AI 查询、脚本、翻译规则集）按项目权限：属主与“可编辑”成员可修改，“只读”成员只能查看。



### 实现结果（REQ-036，M6 后端结果）

M6-3（权限模型）的后端。决策 D-0178、D-0197、D-0198、D-0205、D-0206。

- 角色：`users.ROLES` 增加 `maintainer`（知识库维护员）；最后一个启用的管理员不能改成其他角色。`Principal.is_kb_editor`（管理员与维护员）。
- 权限矩阵集中在 `api/access.py`，`api/scoping.py` 挂载路由时按级别加守卫：`read`（GET）、`compute`（不修改数据的 POST：脱敏、解析、渲染、对比、检查、清理脚本生成、拓扑、一致性、割接迁移、基线、变更脚本生成、影响分析、导出、报告、翻译、模板校验 / 提取 / 草稿 / 生成、图查询、AI 查询、护栏、脚本检查与 diff、未识别行送审）、`write`（其余修改数据的接口，未列出的非 GET 接口默认按 write）、`kb`（Schema、Profile、知识库包导入、文档抽取、审核与批量审核、发布、回滚、共享检查规则的开关与级别）、`self`（项目管理中由 core 按项目角色判断：删除项目、成员、转交、复制）、`public`。只读成员与只读令牌只能 read / compute；`kb` 只限管理员与维护员（知识库发布、回滚也对维护员开放，D-0178）。
- 项目内：属主、可编辑成员、管理员可以修改；只读成员只能查看与计算；不是成员的普通账号 404。删除设备与配置版本（REQ-038）同样按项目权限。
- 重新解析：全部设备（旧路径 `POST /devices/rebuild`）只限管理员；项目路径 `POST /projects/{p}/devices/rebuild` 与单台设备重新解析为属主与可编辑成员；公共设备库 `POST /public-devices/rebuild` 管理员。
- 共享内容（D-0205）：共享检查规则（`PUT /kb/rules/{id}`）只限管理员与维护员；项目里可以关闭某条规则或改级别（`project_rule_overrides`，原因必填，只影响该项目，`checks.check` 在当前项目内套用，发现带 `project_override`）。模板分共享模板（运行时知识库，管理员与维护员修改）与我的模板（`data/user-templates/`，只有自己与管理员能看到和修改，`POST /templates/{id}/copy` 复制为我的模板）；翻译规则集按 `user_assets` 区分我的（自己与管理员）与共享（没有属主，所有人可用，管理员与维护员修改）。
- 建议（D-0206）：普通用户 `POST /kb/suggestions` 提交（审核类型 `suggestion`），维护员在审核队列通过（只记录结论，知识库由维护员修改）或驳回（`note` 为原因）；提出人 `GET /kb/suggestions` 查看结果。
- 测试：`tests/api/test_projects_api.py::test_permission_matrix`（管理员、维护员、属主、可编辑、只读、非成员 × 查看、计算、导入、改设置、规则调整、重新解析本项目、邀请成员、复制项目、全部重新解析、改共享规则、公共设备库导入、所有项目）与 `test_kb_permissions_and_suggestions`、`test_private_templates_and_rulesets`。

## 用户自助注册（REQ-039）

用户 2026-10-19 提出：设置中可以开启、关闭用户注册功能。以下做法经用户在对话中确认（【用户确认】），排期 M6（0.6.0），先做预览页再编码。

- 开关：配置项 `auth.registration`（`false` 默认关闭）；管理员在设置页开关，首次运行向导与 `config.example.toml` 同步。【用户确认：默认关闭】
- 生效方式：配置项 `auth.registration_approval`（`true` 默认需审核）。需审核时，注册后账号处于“待审核”，不能登录，管理员在账号管理中批准或拒绝；不需审核时注册后直接可用。【用户确认：可选，默认需审核】
- 限制：同一来源地址注册频率限制（默认每小时 5 次，可配置）；用户名与密码规则沿用账号管理；不设邀请码、邮箱域名限制。【用户确认：只要频率限制】
- 新账号：角色为普通用户；首次登录（或批准时）自动建工作空间与默认项目（与 REQ-035 一致）。
- 关闭注册时：登录页不显示注册入口，注册接口返回明确错误；已注册的待审核账号仍可由管理员处理。
- 审计：注册、批准、拒绝都记入审计日志（不记录密码）。

### 实现结果（REQ-039）

M6-7 实现。预览 `DevelopDocs/ui-preview/REQ-039/`（登录与注册、账号管理，`index.html` 评审入口）做好后未等评审先编码（决策 D-0235），实现中的取舍见 D-0236。

- 配置项（`[auth]`，首次运行向导放在“安全”一步，`config/config.example.toml` 同步；配置项新增开关类型 `bool`）：`registration = false`、
  `registration_approval = true`、`registration_rate_per_hour = 5`（1–1000）。管理员在账号管理页的“自助注册”面板修改（`GET / PUT /auth/settings`，
  写入配置文件并立即生效）。
- 数据：迁移 `0008`（与项目标识的修改同一个迁移）给 `users` 增加 `status`（active / pending）与 `origin`（admin / register），已有账号为 active / admin。
- 接口：`GET /auth/status` 返回 `registration: {open, approval}`（还没有任何账号时不开放）；`POST /auth/register`（不需登录）：关闭时 403
  （“注册未开放，请联系管理员”），同一来源地址超过频率 429，用户名规则与重名沿用账号管理；需要审核时账号为待审核、不能登录（登录返回 403，
  `data.reason = pending`，只在密码正确时这样提示），不需审核时直接登录并建好默认项目；管理员 `GET /users?status=pending`、
  `POST /users/{u}/approve`（批准时建工作空间与默认项目）、`POST /users/{u}/reject`（删除该账号，用户名可再注册）。
- 频率限制：按来源地址在进程内存里滑动计数（一小时窗口，被拒的尝试不计入，重启后清零）。
- 审计：注册、批准、拒绝、修改注册设置写入 `audit_events` 与 `logs/audit.log`（不含密码）。
- 命令行：`lmesh user list --pending`、`lmesh user approve|reject <名称>`（不是待审核退出码 1，不存在退出码 4）。
- 网页：登录页在注册开放时显示“没有账号？注册”，待审核账号登录时说明“正在等待管理员审核”；注册页 `/register`（规则逐条打勾、结果页：等待审核 /
  已登录进入首页 / 注册未开放）；账号管理：待审核提示条、统计里的“待审核”、“全部 / 待审核”筛选、“自助注册”来源标记、批准 / 拒绝（拒绝前确认）、
  “自助注册”设置面板。与预览的差异：导航“账号管理”旁的待审核数字没有做（需要改共享的外壳并在每页查询，改为账号管理页里的提示条与统计）。
- 测试：单元 `tests/unit/test_registration.py`；API `tests/api/test_registration_api.py`（开关、审核、频率限制、待审核不能登录、批准后能登录并有默认项目、
  拒绝、关闭时注册被拒、不需审核时注册即登录、审计）；CLI 用例 `user-list-pending`、`user-approve`、`user-reject`、`user-approve-not-pending`、
  `user-reject-missing`（准备方式 `configured-pending`）；vitest（注册表单检查、设置面板、待审核状态与计数）；e2e `frontend/e2e/req039.spec.ts`
  （管理员开启注册 → 新用户注册 → 待审核 → 管理员批准 → 新用户登录看到自己的默认项目）。

## AI 接口：公共与个人（REQ-040）

用户 2026-10-19 提出：管理员配置 API，但可以设定是否开启公共使用；每个用户可以选择使用个人 API，也可以使用允许的公共 API。做法（用户原话为准，细节为 Claude 按推荐定下，记入决策记录）：

- 管理员可配置一个或多个 AI 接口（类型、地址、API Key、各用途模型），每个接口有“允许公共使用”开关；现有 `[ai]` 配置升级后成为第一个接口，默认允许公共使用（保持现有行为）。
- 用户在账号设置中选择 AI 来源：个人 API（自己填写地址、Key、模型）或某个允许公共使用的接口；管理员关闭公共使用后，选了它的用户提示改选；都不可用时 AI 功能按“未配置”降级，核心功能照常。
- 个人 Key 加密保存，只显示是否已设置，管理员也看不到；个人接口只用于本人发起的请求（含本人发起的后台任务）。
- AI 调用记录标明用户与接口（不含 Key）；AI 设置页的连接测试对个人接口同样可用。
- 先做预览页 `DevelopDocs/ui-preview/REQ-040/` 再编码。
- 用户评审 M1 预览 ai-settings.html 时追加（2026-10-19）：AI token 用量统计（按天、用户、接口、功能、模型，管理员看全部、用户看自己的，可导出）；接口列表只做概览，每个接口点开进入单独的设置页编辑，个人接口同样单独页面编辑。

实现结果（M6-8）：

- 数据（迁移 0009）：`ai_connections`（`owner_id` 为空是管理员接口，可多个，名称在管理员接口间唯一；不为空是该账号的个人接口，每人最多一个；Key 用 Fernet 加密，`enc:` 前缀）、`ai_choices`（账号的选择 auto / connection / personal / none）、`app_meta`（标记）；`ai_calls` 加 `user_id`、`actor`、`connection_id`、`connection_name`、`source`、`feature`（skill 编号）；`tasks` 加 `created_by`。
- `[ai]` 配置的去向：接口项（provider、base_url、api_key、model*）是第一个管理员接口的初始值——迁移只拿得到数据库，所以在第一次用到 AI 时（`core/ai_connections.ensure_seeded`）导入为 `default`（允许公共使用），写标记 `ai.seeded` 后不再导入（管理员删掉它也不会被配置文件“复活”）；之后以数据库为准。`ai.timeout`、`ai.max_tokens`、`ai.skill_log_days` 仍是全局配置。没有新增配置项（向导与 config.example 只更新了说明）。
- 解析（`ai_connections.resolve`，唯一入口；`ai.complete / is_configured / model_for` 都经过它）：没有账号（全局令牌、没有账号的命令行）用第一个可用的管理员接口；auto 时管理员用第一个可用的管理员接口、其他账号用第一个可用且公共的；选了某个接口但它被关闭公共、停用或删除时不自动换，原因 `public_closed`（提示改选）；其他原因 `no_connection`、`no_public`、`personal_missing`、`disabled_by_user`。可用 = 启用且填写完整。
- 发起人：接口层的 `settings_of(request)` 绑定调用者（`Settings.for_actor`），后台任务带着提交时的 settings 运行即按发起人的选择，任务记录 `created_by`；命令行按 `--as` 账号（不给时第一个管理员，与项目一致）。
- 接口：管理员 `GET/POST /ai/connections`、`GET/PUT/DELETE /ai/connections/{id}`、`POST /ai/connections/{id}/test`；本人 `GET/PUT /me/ai`、`POST /me/ai/test`；`GET /ai/status` 加 `effective` 与 `reason`；`/ai/calls` 普通账号只看自己的；`GET /ai/usage`、`GET /ai/usage/export`（CSV）；`/summary` 的 `ai` 加 `reason`；各 AI 功能“未配置”的 409 在 `data.reason` 给出原因。旧的 `/ai/settings`、`/ai/test` 保留（deprecated，对应第一个管理员接口）。
- 命令行：`lmesh ai connections list|add|set|remove|test`、`lmesh ai use`、`lmesh ai status`、`lmesh ai personal show|set|remove|test`、`lmesh ai usage`；`lmesh ai calls` 加发起人与接口列。
- 界面：AI 接口页 `/ai`（管理员）分“接口 / 用量统计 / 调用记录”，接口列表只做概览（保留公共与启用开关），单个接口与新建走单独设置页 `/ai/connections/:id`、`/ai/connections/new`（编辑、测试、该接口用量与最近调用、删除）；账号菜单加“我的 AI”（`/me/ai`：选择、生效来源与测试、我的用量与调用；全局令牌不显示），个人接口单独页 `/me/ai/personal`；用量统计近 7 / 30 / 90 天或自定义，按天输入 / 输出堆叠柱（可切换表格），按用户 / 接口 / 功能 / 模型汇总，导出 CSV；通用组件 `components/ai-off-hint.vue` 按原因给出“未配置”提示与去处（问答、文档导入、未识别行、AI skill、进化、脚本检查）。代码：`AiSettingsView.vue`、`AiConnectionView.vue`、`MyAiView.vue`、`MyAiPersonalView.vue`、`views/ai/`（`logic.ts`、`usage.ts` 与 vitest）。
- 测试：单元 `tests/unit/test_ai_connections.py`（解析各分支、导入、加密、记录归属、后台任务、用量、迁移 0009）；API `tests/api/test_ai_connections_api.py` 与用例 `api_cases.ai.toml`；CLI 用例 `cli_cases.ai.toml`（准备方式 `configured-ai`）；vitest；e2e `frontend/e2e/req040.spec.ts`（管理员建两个接口只开放一个 → 用户只看到开放的 → 用户改用个人接口 → 管理员关闭公共接口后另一用户看到改选提示）。
- 与预览的差异：全局限制与安全说明放在“接口”分区；所选接口被删除后只能显示“已关闭”（`/me/ai` 的 `chosen_name` 在接口仍存在时给出名称）。

## AI 增强（REQ-041）

用户 2026-10-19 要求梳理内置 AI 在各功能中的用法。经用户确认：五组全部做、P1～P3 全部做、AI 结果一律先作为建议（代码验证通过后由用户逐条或批量采纳）、排期新里程碑 M8（0.8.0），M7 之后。原则：确定性结论由代码在图上计算，AI 只给建议与文字；AI 输出先入图或进审核队列，经代码校验后展示。

| 组 | skill | 应用场景 | 代码把关 | 优先级 |
|---|---|---|---|---|
| 日常分析 | 拓扑整理 | 按设备名、接口描述、角色特征推断角色（核心 / 汇聚 / 接入 / PE / P / CE）、按站点分组分层排版、推测未解析对端 | 只改视图分组、标签、布局；推测对端标“AI 推测”，代码核对地址与接口后才连线 | P1 |
| 日常分析 | 设备摘要 | 交接、巡检时一段话说明设备的角色、业务、上下联、特殊配置 | 数字与对象由代码提供，出现图中没有的对象则拒绝 | P1 |
| 日常分析 | 变化解读 | 对比、版本历史的差异归纳成变更意图并按风险排序 | 每个意图必须挂上对应差异条目 | P1 |
| 日常分析 | 问题解读与修复 | 检查、一致性问题的原因、优先级、修复脚本草稿，判断哪端更可能出错 | 修复脚本过脚本检查，在模拟图上复检问题消失 | P1 |
| 日常分析 | 影响说明 | 依赖链转为运维语言：影响业务、操作顺序、观察点 | 影响范围由代码计算 | P2 |
| 日常分析 | 能力对比说明 | 选型、迁移前解释两家特性差异与替代写法 | 写法来自命令卡 | P3 |
| 变更与割接 | 变更意图转脚本 | 对现网设备用自然语言描述变更 | AI 只改目标图，脚本由代码生成，经影响分析与模拟执行 | P1 |
| 变更与割接 | 割接方案文档 | 割接步骤、检查点、回退条件、时间窗口，中英双语 | 命令全部引用代码生成的脚本 | P2 |
| 变更与割接 | 翻译未支持项处理 | 不支持或原文保留的行给出目标平台等价写法 | 用目标平台命令卡解析验证，逐条确认 | P1 |
| 变更与割接 | 命名映射建议 | 新旧设备接口名、VPN 名风格不同时建议映射规则（REQ-032） | 应用后列出映射表，冲突与遗漏由代码报出 | P2 |
| 变更与割接 | 模板提取 | 从同类设备提取公共模板与变量 | 用各设备取值渲染须与原配置等价 | P2 |
| 规范与合规 | 规范转规则（含规则编写助手） | 公司配置规范或安全要求文字转为检查规则草稿；维护员一句话描述生成规则 | 知识库校验、样本试跑列出命中，进审核队列 | P1 |
| 规范与合规 | 基线例外说明 | 起草例外理由与补偿措施 | 只生成文字 | P3 |
| 规范与合规 | 脱敏复核 | 找出代码规则漏掉的敏感信息（描述中的客户名、电话等） | 只允许本地模型 | P2 |
| 知识库构建 | 未识别行归因 | 判断缺命令卡、版本差异或写法变体，起草命令卡 | 进审核队列，重新解析后未识别行须减少 | P1 |
| 知识库构建 | 命令卡审核助手 | 对照文档指出参数类型、默认值、取消写法可疑的卡 | 只标注，人工决定 | P2 |
| 知识库构建 | 映射建议 | 新厂商命令卡建议映射到 Schema 节点 | 知识库校验、往返、翻译回归通过才发布 | P2 |
| 报告 | 报告摘要 | 检查、基线、对比、割接报告开头的中英文摘要 | 数字由代码填入 | P2 |

另有已存在的 6 个 skill（问答 2 个、配置生成、脚本审查、命令卡语法修正、skill 进化）。每个新 skill 走 REQ-033 的管理与进化机制，使用 REQ-040 的用户 AI 接口选择。

### M8-2 结果（AI 建议框架）

所有 AI skill 共用的“建议 → 代码校验 → 采纳 / 撤销”框架，后端 + 通用前端组件，按已评审的预览 `DevelopDocs/ui-preview/M8/suggest.html` 实现。决策 D-0259～D-0264。

**数据**（迁移 `0010_ai_suggestions`，接在 0009 之后）：

- `ai_suggestion_batches`：一次运行——项目、设备、范围（`scope_key`：`device:<编号>` / `topology` …）、skill 与生效版本、模式（ai / replay）、状态（queued / running / done / failed / cancelled）、后台任务编号、skill 调用记录编号（`skill_run_id`）、AI 调用记录编号（`ai_call_ids`，含重试）、接口名称与来源、模型、token、发起人、参数、`context`（代码给出的事实，编辑后重新校验用同一份）、计数、失败原因。
- `ai_suggestions`：一条建议——批次、项目、设备、范围、skill、类别、kind、标题、内容（JSON）、编辑前的原内容、引用、代码校验结果（`check`：`status` pass / warn / reject 与 `reasons`）、状态（pending / adopted / dismissed / reverted）、AI 调用记录编号与接口、发起人、采纳人与时间、采纳信息（做了什么、原来的值）、撤销人、时间与信息。
- `view_annotations`：项目级视图标注（目标类型、目标、键 role / group / label / layer、值、来源 user / ai、建议编号）。角色取值顺序：手工标注优先，其次采纳的 AI 建议，最后按平台默认（REQ-042，M8-3 接到拓扑图标）。
- `ai_choices.no_token_warn`：个人偏好“不提示大请求”。

**流程**（`core/ai_suggest.py`；示范 skill 的上下文在 `core/ai_suggest_skills.py`）：

1. 准备上下文：skill 的 `build(env, params)` 在图上取事实——对象编号表（`d1` 设备、`n1` 对象、以后的 `c1` 差异条目、`f1` 问题……；编号由代码生成，AI 只能引用这些编号）、代码算好的数字（`numbers`）、配置行数、可在正文直接出现的名称；配置来自数据库（导入时已脱敏），发送前再经 `ask.sanitize_text` 脱敏。
2. 调用：生效版本的提示词（REQ-033 的 `skills.current`），`ask._Session` → `ai.complete`，用量按功能（skill 编号）记录；`ai.collect_call_ids()` 收集调用记录编号；按发起人的 AI 选择（REQ-040）。
3. 解析：回复必须是 `{"suggestions": [{"category", "kind", "title", "content", "refs"}]}`；不合格时用 skill 的 `retry` 模板（没有时用通用提示）重试一次，仍不合格批次记为 failed（`ai_suggest.bad_reply`）。AI 调用失败同样记为 failed，不抛出。
4. 校验：通用检查（类别必须是该 skill 允许的、内容是对象、大小、标题里不能有图中没有的对象、`refs` 都在事实里：`{"id": "n3"}` 或 `{"line": 12, "of": "d1"}`），再交给类别的校验器；同一原因只列一次。正文写法：`[[编号]]` 提到对象、`<<键>>` 引用代码填入的数字，界面把它们换成实线小块（`check.segments`、`display`、`title_display`）。
5. 入库：每条建议（被拒绝的也入库，只读展示原因）与批次；同时记一条 skill 调用记录（来源 `suggest`，计入 REQ-033 统计；有被拒绝的记为 rejected，自动进入回归集供进化）。REQ-033 的试运行与回归运行对这类 skill 用同一套校验器（`skill_runners` 的通用运行器，输入为记下的 `vars` 与 `facts`）。
6. 取消：批次标为 cancelled，AI 回复到达后丢弃（已发出的调用照常计入用量）。运行中任务进度的 `message` 依次为 sanitize / send / generate / check，对应界面的四步。

**校验器注册表**（`register_category(类别, Validator(check, adopt, revert, kb=False, batch=True))`）：

| 类别 | 校验 | 采纳 | 撤销 |
|---|---|---|---|
| `refs_exist` | 至少一个引用，引用都在事实里（防止编造） | 只记录结论 | 只记录 |
| `script_valid` | `content.script` 对 `content.device` 的当前版本过脚本检查（变更脚本，在模拟图上执行）：有 error 拒绝，有 warning 或代码无法确认的行（功能域外 / 未识别）给警告；`content.fixes`（`rule` + `node`）要求模拟后这些问题消失 | 在项目里新建一份变更脚本（基线为该设备） | 脚本没改过时删除，改过 409 |
| `kb_review` | `content.review_kind` 是审核队列支持的类型、`payload` 是对象；按类型的额外校验注册在 `KB_CHECKS` | 进审核队列（来源 ai，带建议编号）；只有维护员与管理员可以采纳与撤销 | 审核项仍待处理时撤回（标为驳回），已处理 409 |
| `view_hint` | `content.target` 是图中的设备、`key` 为 role / group / label / layer、取值合法（role：core / aggregation / access / pe / p / ce）；`reason` 里不能有图中没有的对象；会覆盖手工标注时警告 | 写入项目视图标注（记下原值） | 标注仍是这条建议写的时恢复原值（原来没有则删除），被后来的建议覆盖 409 |
| `text_only` | `[[编号]]`、`<<键>>` 都在事实里；正文中直接写出的接口名、地址、带数字的主机名必须是图中的对象或属性值，否则拒绝；对不上任何事实的数字给警告（由代码填入的数字不检查） | 只记录结论 | 只记录 |

采纳规则（M8-1 评审推荐）：reject 不能采纳；warn 可以逐条采纳；“全部采纳 / 按类别采纳”只含 pass 且待处理的；编辑后采纳先用同一份事实重新校验（不合格 409，`data.check`）；忽略后可恢复或直接采纳；采纳后 30 天内可撤销（`REVERT_DAYS`），之后或对象又被改过时提示用版本历史回退。

**权限**：接口只挂在项目路径下，沿用 M6 的项目角色——查看（列表、详情、批次、采纳记录、视图标注、skill 列表、运行前估计）所有成员；运行、取消、采纳、批量采纳、忽略、恢复、撤销需要可编辑（属主、可编辑成员、管理员）；知识库类（`kb_review`）的采纳与撤销另外要求维护员或管理员。不是成员 404。命令行等同管理员。

**大请求提示**（用户评审第 7 题）：新配置项 `ai.warn_tokens = 50000`（0 = 不提示；向导“AI 接口”一步与 `config/config.example.toml` 已同步）；“我的 AI”里的个人开关“不提示大请求”（`PUT /me/ai {"no_token_warn": true}`）优先于全局值。`POST …/ai/suggestions/estimate` 按当前上下文渲染提示词估计 token（ASCII 约 4 字符一个，其他字符各一个），超过提示线时界面提示条变黄、按钮改为“仍然生成（约 N token）”。

**接口与命令行**：`/api/v1/projects/{p}/ai/suggestions/…`（skills、estimate、run、batches/{id}、batches/{id}/cancel、列表、{id}、{id}/adopt、adopt-batch、{id}/dismiss、{id}/restore、{id}/revert、adoptions）与 `/projects/{p}/view-annotations`，见 `docs/api.md`；`lmesh ai suggest run|list|show|adopt|dismiss|revert|annotations`（`run --replay <文件>` 用文件里的回复代替真实 AI，同样经过代码校验），见 `docs/cli.md`。

**示范 skill**（`knowledge/ai-skills/`，`group: analysis`，M8-3 做完整）：`device-summary`（text_only：设备与顶层对象编号表、主要属性、代码算好的计数，3～6 句交接摘要）、`topology-roles`（view_hint：项目设备的名称、平台、链路数、接口描述与还原的链路，推断角色）。两者都带 `retry` 模板、一条通过与一条被拒绝的试运行样例，提示词要求只引用给定的编号。

**前端通用组件**（`frontend/src/components/ai-suggest/`，样式移植自预览 `m8.css`，明暗两套，文案 `i18n/pages/ai-suggest.json` 三语）：`AiEntryButton.vue`（统一的 AI 按钮 + ▾ 菜单；运行中显示进度；不可用时变灰但可点，点开是 REQ-040 的 `ai-off-hint`）、`AiSuggestPanel.vue`（未运行 / 运行中四步可取消 / 有建议 / 空 / 失败 / 已取消 / 不可用；汇总条、全部采纳与按类别采纳、筛选、采纳记录与撤销；会改脚本或知识库的采纳二次确认并勾选“已查看”）、`AiSuggestCard.vue`（通过的折叠成一行，有警告或被拒绝的展开；被拒绝的灰底红虚线、不存在的引用打删除线、不可采纳；采纳后实线并保留紫色细条；编辑后采纳）、`AiText.vue`（AI 文字紫色虚线半透明，代码填入的对象名与数字实线、可跳转）、`logic.ts`（纯逻辑与 vitest）。示范接入：设备配置分析页头（设备摘要）、拓扑页头（设备角色）。“我的 AI”页加“不提示大请求”开关。

**以后加一个 skill 的步骤**：

1. 定义 skill：`knowledge/ai-skills/<编号>.yaml`（`group` 用 `_groups.yaml` 里的组；`system` 写清只能引用给定编号、正文用 `[[编号]]` 与 `<<键>>`、只回 JSON `{"suggestions": […]}`；带 `retry` 模板与一条通过、一条被拒绝的 `samples`，样例输入为 `{vars, facts}`），并加入 `skills.ORDER`。
2. 写上下文：在 `core/ai_suggest_skills.py`（或功能自己的模块，由 `ai_suggest._load_skills` 导入）`register_skill(SkillSpec(id, build, categories, default_category, scope, prepare))`；`build` 只用代码在图上算出的事实，所有对象都编进 `facts.objects`（带 `device_id` / `node` / `line` 供跳转），数字放 `facts.numbers`。
3. 选校验器：能用现有类别就用；不够时 `register_category` 新写（校验函数返回原因列表，采纳与撤销各自用自己的数据库会话，撤销要能判断“之后被改过”）；知识库草稿按类型的额外校验注册到 `KB_CHECKS`。
4. 接入页面：在页面工具栏放 `<AiEntryButton :skills="[…]" @run="panel.start()" />` 与 `<AiSuggestPanel ref="panel" skill="…" :params="…" :scope="…" />`，按需处理 `changed`（采纳后刷新页面数据）与 `jump`（引用跳转）。
5. 测试：用假的 AI（替换 `ai.provider_hook`）覆盖正常建议、代码校验拒绝（编造对象 / 脚本校验失败）、未配置 AI 时降级；CLI 用例用 `--replay`。

**测试**：单元 `tests/unit/test_ai_suggest.py`（五类校验器的通过与拒绝、编造对象被拒并进入回归集、解析失败重试与失败、AI 调用失败、未配置 AI 降级与回放、停用 skill、批量采纳只取通过的、编辑后重新校验、手工标注优先与覆盖后不能撤销、审核队列撤回、脚本采纳与改过后不能撤销、取消、后台任务保持项目、跨项目不可见、30 天撤销期、大请求提示线与个人开关、REQ-033 回放样例、迁移 0010）；API `tests/api/test_ai_suggest_api.py`（权限矩阵：属主 / 可编辑 / 只读 / 非成员 / 维护员；后台任务；批量采纳只采纳通过的；编辑后采纳；知识库类权限；参数错误；未配置 409；个人开关）与用例 `api_cases.ai_suggest.toml`（准备方式 `configured-fullkb-suggest`）；CLI 用例 `cli_cases.ai_suggest.toml` 与 `tests/cli/test_ai_suggest_cli.py`（回放运行 → 采纳 → 标注 → 撤销）；vitest `components/ai-suggest/logic.test.ts`；e2e `frontend/e2e/m82.spec.ts`（`playwright.m82.config.ts` 用 `e2e/m82_server.py` 的假 AI：设备摘要采纳与撤销、拓扑角色编造设备被拒、全部采纳只采纳通过的；主配置下验证入口的“不可用”提示）。

**与预览的差异**：采纳记录按条撤销（没有“回退本批”）；运行中只显示四步与接口、模型，不显示逐 token 的接收进度（后端不流式）；超时由 `ai.timeout` 决定，按失败显示（重试 / 改用其他接口）；“把握”百分比没有（AI 的自评不经代码校验，不展示）；入口菜单的“本月我已用”改为“查看用量”链接。

### M8-3 结果（日常分析组的 AI skill、拓扑设备图标）

日常分析组 6 个 skill 全部按 M8-2 框架接入（`group: analysis`），拓扑设备图标（REQ-042）按评审结果实现（决策 D-0268～D-0273）。页面照预览 `DevelopDocs/ui-preview/M8/analysis.html`、`REQ-042/icons.html`、`topology.html`。代码：`core/ai_suggest_analysis.py`（skill 注册、新类别 `peer_link`、手工标注、覆盖核对、交接文档）；设备摘要的上下文仍在 `core/ai_suggest_skills.py`（事实里加了 `lang`）。公共代码的改动：`SkillSpec.check`（skill 自己的额外校验，在类别校验之后）、`script_valid` 的 `fixes` 跳过没有 `rule` 的条目（由 skill 的额外校验处理 `{"finding": "f3"}`）、`_load_skills` 导入本模块。

| skill | 类别 | 代码校验 | 入口 |
|---|---|---|---|
| `topology-roles` 拓扑整理 | `view_hint`（角色 / 分组 / 层次）、`peer_link`（新） | 角色、分组、层次同 M8-2；推测对端：两端（给出接口时只看该接口）有一对同 VRF 的接口地址同网段（一端网段包含另一端地址，掩码不同也算）才通过；对未解析对端 `u*`，设备有直连网段包含该地址才当作外部设备连上；没有同网段 `no_shared_subnet`、已有链路 `already_linked` 都拒绝 | 拓扑页 |
| `device-summary` 设备摘要 | `text_only` | 同 M8-2 | 设备配置分析页、设备列表（“设备摘要”链接打开分析页的摘要面板，不自动运行） |
| `diff-explain` 变化解读 | `refs_exist` | 每个意图至少挂上一个差异条目 `c*`（`no_diff_refs`）；风险 high / medium / low；正文对象与数字核对 | 配置对比页（两边都是导入设备的版本）、版本历史页 |
| `finding-fix` 问题解读与修复 | `refs_exist`（原因、优先级、更可能出错的一端）、`script_valid`（修复脚本） | 必须引用问题 `f*`；`suspect` 必须是问题涉及的设备；脚本设备必须是问题的一端（`fix_wrong_device`）；`fixes: [{"finding": "f3"}]` 要求复检后问题消失：检查问题看脚本检查的 `findings_fixed`，跨设备问题把该设备换成脚本执行后的模拟图重新做一致性检查（`finding_not_fixed`） | 检查页（导入设备）、跨设备一致性视图 |
| `impact-explain` 影响说明 | `text_only` | 影响范围由 `impact.analyze` 计算并编号 `n*`；正文至少提到一个受影响对象（`no_impact_refs`） | 影响分析页（设备来源） |
| `feature-compare` 能力对比说明 | `text_only` | `content.commands` 的每条命令必须能被所引命令卡（`k*`）的语法或取消语法解析（`syntax_mismatch`、`card_not_found`）；知识库里没有该卡时用事实里记下的语法（回放） | 特性能力查询页的对比标签（选中一个特性） |

**编号**：`d` 设备、`u` 未解析对端、`c` 差异条目（对比用 compare 的逐节点差异，版本历史用按对象归并的条目）、`f` 问题、`n` 对象、`k` 命令卡、`p` Profile。范围（`scope_key`）：`topology`、`device:<编号>`、`compare:<A 版本>:<B 版本>`、`history:<A 版本>:<B 版本>`、`check:<设备>`、`consistency`、`impact:<设备>:<方向>:<排序后的起点>`（截到 200 字符）、`feature:<节点>:<A>:<B>`；前端用同样的规则生成（`components/ai-suggest/logic.ts`）。

**手工标注**：`PUT /projects/{p}/view-annotations {target_type: device, target, key: role|group|label|layer, value}`（`value: null` 清除），来源 user，优先于 AI；AI 建议会覆盖手工标注时警告（逐条采纳）；采纳后又被手工改过的 AI 建议不能撤销（409）。推测对端采纳后写 `target_type: link, key: peer` 的标注（值是代码核对过的两端设备、接口与地址），撤销删除。命令行 `lmesh ai suggest annotate <设备> --key role --value core`（`--clear` 清除）。

**覆盖核对**：`GET …/ai/suggestions/coverage?skill=diff-explain&scope=…`：范围内最近一次完成的运行里，未被拒绝、未忽略、未撤销的意图引用到的条目与没被任何意图解释的条目（带 `node`、`label` 供页面对行）；命令行 `lmesh ai suggest coverage <范围>`。

**设备交接文档**：`GET …/devices/{id}/handover?lang=zh-CN|en&format=html|md`（直接返回文件）：设备信息、角色与分组标注、代码算出的对象统计、最近采纳的设备摘要（优先同语言的；只有别的语言时注明原文语言）；页面分别提供中文、English 下载；命令行 `lmesh ai suggest handover <设备> --doc-lang en --format md [-o 文件]`。命令行 `run` 加 `--params '<JSON>'` 传 skill 的其他参数。

**设备图标（REQ-042）**：`frontend/src/components/devicon/`：`sets.ts`（三套图形，从预览 `icons-cyl.js`、`icons-geo.js`、`icons-line.js` 原样移植）、`lmi.ts`（移植 `lmi.js`：尺寸分档 72 / 48 / 32 / 24 / 16、厂商标识 HW / CS / NK、状态角标按 检查 > 一致性 > 过期 > AI 取前 2 个，其余“+n”，16 px 只画一个点；待采纳的 AI 建议 ghost：紫色虚线半透明）、`logic.ts`（角色取值：手工 > 采纳的 AI > 平台外形；角色未知按平台画设备外形：ATN、ASR 920、7750 SR，其他按厂商取最接近的外形）、`DeviceIcon.vue`（页面内联 SVG，currentColor 着色，`--lmi-*` 变量明暗两套）、`IconSetSwitch.vue`。拓扑图（cytoscape）的节点用 SVG data URI：渲染前按当前主题读出颜色写进 SVG 自带的样式，切换主题或图标风格只重绘图标。图标风格是个人偏好（浏览器本地 `lmesh-icon-set`，默认 B 几何徽章），在用户菜单和拓扑工具栏切换。用在拓扑视图（分组为 compound 父节点、有标注时按“分组成列、角色分层”排版，否则仍用 cose；采纳的推测对端画灰线、外部对端加 peer 节点；待采纳的角色建议用 ghost 图标，“显示 AI 建议”可关；待采纳的推测对端画紫色虚线加“AI 推测”）、设备侧栏（72 px 图标、来源标识、角色 / 分组 / 层次编辑，只读成员不显示）、设备列表（24 px，过期与 AI 待采纳角标）、设备配置分析页与配置图页标题、关系图谱（设备根节点）。

**测试**：单元 `tests/unit/test_ai_suggest_analysis.py`（每个 skill 的通过与拒绝；推测对端的同网段、已有链路、环回地址；手工标注优先与覆盖后不能撤销；意图挂差异与覆盖核对（版本历史与对比两种来源）；修复脚本在单台检查与跨设备一致性上的复检；影响说明；命令写法核对；交接文档；未配置 AI 降级与回放；REQ-033 回放样例）；API `tests/api/test_ai_analysis_api.py` 与用例 `api_cases.ai_analysis.toml`；CLI 用例 `cli_cases.ai_analysis.toml`；vitest `components/devicon/devicon.test.ts`、`views/m4/topomarks.test.ts`、`components/ai-suggest/logic.test.ts`；e2e `frontend/e2e/m83.spec.ts`（`playwright.m83.config.ts`，`e2e/m83_server.py` 的假 AI，端口 9483；主配置下只验证图标、手工标注与“不可用”）。

**与预览的差异**：拓扑仍用 cytoscape（没有照搬预览手画的 SVG）：没有“建议位置”的幽灵复制节点与弧线，待采纳的分组显示在侧栏；名称与角色小字同一样式；“检查问题”角标暂不显示（拓扑与设备列表拿不到每台设备的检查结果）；“把握”百分比不显示（同 M8-2）；特性对比的 AI 入口在对比标签（先选中一个特性）；一致性视图里点引用只过滤列表。

### M8-4 结果（变更与割接组的 AI skill）

按已评审的预览 `DevelopDocs/ui-preview/M8/change.html` 实现 5 个 skill（`group: change`，`knowledge/ai-skills/` 下各一个 yaml，带三语标题与说明、`retry` 模板与一条通过、一条被拒绝的回放样例）。上下文构造、校验器与采纳动作都在 `src/lmesh/core/ai_suggest_change.py`（由 `ai_suggest._load_skills` 导入）。决策 D-0281～D-0284。

| skill | 类别（新） | AI 给出 | 代码校验 | 采纳 / 撤销 |
|---|---|---|---|---|
| `intent-script` 变更意图转脚本（增量变更页） | `graph_edit` | 目标图上的 `set` / `unset` / `add` / `delete`，用图中对象编号（n1…）与 Schema 节点表示，新对象用 `+1` 互相引用 | 节点在 Schema 中且设备 Profile 支持、挂在正确的父对象下、取值类型与范围（integer 范围、enum、ipv4、prefix、rd、asn、community、interface…）、键完整；应用到目标图后先在当前配置上模拟执行得到目标配置并重新解析，每条改动都要落到图上（否则 `edit_not_realized`），新出现的悬空引用拒绝（`ref_missing`）；再用增量变更（`core/change.py`）生成下发与回滚脚本、影响分析与两向模拟执行，不通过拒绝；代码补发的副作用 / 互斥命令、高风险变更给警告 | 需二次确认；同一次运行里已采纳的改动合并后重新校验（不通过 409），生成项目脚本（下发 + 回滚，同一检查项目）；之前采纳生成的脚本没被人改过时更新它，否则另建。撤销：去掉这一条重新生成（没有剩下的改动时删除），脚本被人改过 409；设备在生成后有新版本时采纳 409（`device_changed`） |
| `cutover-plan` 割接方案文档（割接迁移页） | `plan_section` | 方案的一节（overview / window / steps / checks / rollback / risks），`zh` 与 `en` 两种语言，步骤只写编号 `s3` 与说明、检查点 | 两种语言都要有；`[[编号]]`、`<<键>>` 与正文中的名称、地址按 `text_only` 的规则核对；直接写出命令拒绝（`command_in_text`：代码格式、常见运维命令写法、能被源 / 目标平台族命令卡在根视图识别为命令的片段）；引用的步骤必须是代码生成的步骤 | 写入方案（只记录）。方案由代码组装：标题、元数据、步骤清单与每步的命令来自割接迁移结果（`core/migration.build_steps`），各节只放已采纳的 AI 文字，没有采纳的写“需要人工填写”；中文版、英文版分别导出 Markdown |
| `translate-gap` 翻译未支持项（配置翻译页） | `translate_eq` | 对不支持 / 原文保留的项（u1…，附原文行）给出目标平台写法（`equivalent`，可用 `expect` 声明映射到的 Schema 节点）或“无对应”（`none`）与理由 | 用目标 Profile 解析：有未识别行拒绝，没有一行被识别为命令拒绝，部分行在功能域外给警告；必须映射到预期节点（项本身的 Schema 节点或 `expect`，与原节点不同时警告）；“无对应”时目标 Profile 其实支持该节点给警告；密码类不交给 AI | 写入翻译结果：翻译接口与 `lmesh translate <设备>` 在项目里把采纳的写法插在结尾标记前，`ai_lines` 标出来自 AI 的行，`unsupported` 对应项带 `ai`；撤销后不再写入 |
| `naming-map` 命名映射建议（翻译自定义规则页，REQ-032） | `naming_rules` | REQ-032 规则集的 `names` / `ports` / `naming` | 规则集语法（`naming.parse`）；在旧设备上试运行（`naming.run`，给了新设备时按新设备查重名），卡片列出完整映射表；冲突拒绝，遗漏、命名规范告警、没用上的规则、没映射的物理端口给警告 | 保存为我的规则集 `ai-naming-<编号>`（`data/translate-rules/`，归属记在 user_assets）；撤销时文件没被改过才删除，否则 409（`asset_modified`） |
| `template-extract` 模板提取（模板页“从设备提取”） | `template_draft` | 在代码的模板草稿（`template_draft.draft`）基础上整理变量、类型、块后的模板 YAML | 模板语法与编译；对每台设备按模板校验并提取取值，用它自己的取值渲染、解析后与原配置比较，渲染出的每个节点都必须在原配置中且取值相同（模板覆盖的部分等价），列出覆盖率；没有变量给警告 | 存为我的模板 `ai-template-<编号>`（`data/user-templates/`）；撤销同上 |

**样例回放**：上下文的事实里记下配置版本（运行时按版本重新建图）；skill 管理页的回放样例没有设备，事实里直接给出配置文本 `configs`。

**接口与命令行**：运行、采纳、撤销用通用接口与 `lmesh ai suggest run <skill> --params '{…}'`（模板提取用 `--devices`）。新接口（`routes_ai_change.py`，只挂项目路径、所有成员可看）：`GET /projects/{p}/ai/change/plan?batch_id=`（已采纳改动合并后的脚本逐行，`k` = ai / code / frame，回滚、影响、模拟）、`GET /projects/{p}/ai/cutover-plan/{batch}?lang=`（方案预览，含待采纳的段落）、`GET …/cutover-plan/{batch}/export?lang=zh-CN|en`（Markdown 下载）、`GET /projects/{p}/ai/translate-patches?device_id=&to=`；`POST /translate` 带 `device_id` 时写入采纳的 AI 写法。新命令：`lmesh ai change-plan <运行编号>`、`lmesh ai cutover-doc <运行编号> --lang zh-CN|en [--out 文件]`。

**界面**：通用组件只加了最少的东西——卡片对新类别显示说明文字与代码给出的预览行（`AiPreviewLines.vue`：紫色左条是 AI 内容，其余是代码生成或补发，红色删除线是被拒绝的部分，琥珀色是代码无法确认的行），`graph_edit` 采纳需二次确认。页面接入在 `frontend/src/views/ai-change/`：`IntentPanel.vue`（增量变更页：描述框、流程条“自然语言 → 目标图改动（AI）→ 变更脚本 / 影响分析 / 模拟执行（代码）”、合并后的脚本与回滚切换、影响数字与模拟结果、右侧建议面板）、`CutoverPlanPanel.vue`（割接迁移页“步骤”页签下：方案预览中英切换、标出 AI 部分、分别下载）、`TranslateGapPanel.vue`（配置翻译页结果下：未支持项表与采纳的写法，采纳后重新翻译）、`NamingPanel.vue`（翻译自定义规则页）、`TemplateExtractPanel.vue`（模板页从设备提取）。文案 `i18n/pages/ai-change.json` 与 `ai-suggest.json`（类别、原因、skill 说明）三语。

**测试**：单元 `tests/unit/test_ai_suggest_change.py`（意图转脚本的通过、合并采纳、项目脚本更新与撤销、人工改过不能撤销，编造对象 / 超范围 / 引用不存在 / 不在 Schema / 父对象不对被拒绝；割接方案的双语、写出命令、编造对象与中英导出；命令识别；翻译未支持项的解析校验与写入译文；命名映射的映射表、冲突、规则不合法、遗漏提醒与规则集撤销；模板提取的等价核对与我的模板；五个 skill 未配置 AI 时降级与回放；REQ-033 回放样例）；API `tests/api/test_ai_change_api.py` 与用例 `api_cases.ai_change.toml`；CLI `tests/cli/test_ai_change_cli.py` 与用例 `cli_cases.ai_change.toml`（回复在 `tests/inputs/ai-change/`）；vitest `views/ai-change/logic.test.ts`；e2e `frontend/e2e/m84.spec.ts`（`playwright.m84.config.ts`，`e2e/m84_server.py` 的假 AI，端口 9484；主配置下只验证入口“不可用”）。

**与预览的差异**：预览是一个“变更与割接”组页面加页签，实现为接入各自的真实页面（增量变更、割接迁移的步骤页签、配置翻译结果下方、翻译自定义规则、模板从设备提取）；命名映射只接在翻译自定义规则页（割接迁移与翻译页可通过规则集选用采纳后的规则）；脚本区不用预览的行号着色而用左侧紫条；翻译页的译文代码区本身没有逐行着紫，未支持项表与提示条标出 AI 写法与行数；方案中的时间窗口时长、受影响基站数等预览里的代码估算数字没有（代码没有这类数据，AI 只能引用代码给出的步骤数、接口数等）；“把握”百分比不显示（同 M8-2）。

### M8-5 结果（规范与合规、知识库构建、报告的 AI skill）

7 个 skill 按 M8-2 框架接入（`core/ai_suggest_kb.py`，报告摘要在 `core/ai_report_summary.py`；`group` 为 compliance / kb / report），决策 D-0274～D-0279。页面照预览 `DevelopDocs/ui-preview/M8/compliance.html`、`kb.html`、`report.html`。

| skill | 类别 | 代码校验 | 采纳 |
|---|---|---|---|
| `rule-draft` 规范转规则（含规则编写助手） | `kb_review`（`review_kind: rule`） | 条款由代码切分编号 `s*`；草稿 YAML 与知识库现有检查规则一起交给规则引擎加载（YAML 错误、字段 / 路径 / 编号重复都拒绝：`rule_yaml`、`rule_invalid`）；在 `knowledge/samples` 清单的样本上试跑并列出命中（`check.result.trial`），零命中提醒（`rule_no_hits`），适用实例全部命中提醒（`rule_all_hit`） | 进审核队列；通过时追加到 `rules/standards.yaml`，写后重新加载全部规则，失败恢复原文件 |
| `baseline-waiver` 基线例外说明 | `text_only` | 该设备该基线规则必须确实不符合（否则 `ai_kb.rule_not_failed`）；`kind` 为 reason / compensating；正文对象与数字核对同 M8-2 | 只记录结论 |
| `sanitize-review` 脱敏复核 | `sanitize_rule`（新） | **只允许本地模型**；代码挑出含自由文本的行（描述、名称、联系人、横幅、邮箱、长数字…）才发送；标出的文字必须原样在所标的行（`san_not_in_line`），不能是占位符，补规则（`pattern` 或按字面）重新脱敏后不再出现（`san_still_there`），规则太宽提醒 | 写进项目设置 `sanitize_redact`（项目的脱敏补充）；之后导入到该项目、发给 AI 前（`ask.sanitize_text`）都按它替换；撤销时移除 |
| `unknown-triage` 未识别行归因 | `kb_review`（`review_kind: unknown_card`） | 组 `u*`、已有卡 `k*` 由代码给出；草稿卡字段、语法、视图、参数检查；用草稿重新解析这些行所在的配置，这些行必须变成已识别（`still_unknown` 拒绝，部分识别提醒）；改已有卡（版本差异 / 写法变体）时该平台族门槛样本往返不能变差 | 进审核队列；通过时新增卡（缺命令卡）或修改已有卡，状态 reviewed |
| `card-review` 命令卡审核助手 | `text_only` / `refs_exist` | 字段编号 `f*` 与维护员粘贴的文档原文行号（`{"line": n, "of": "doc"}`）必须存在；必须引用字段（`no_field_ref`）；给出的原文摘录必须在所引的行里（`quote_not_in_doc`） | 只记录结论（只标注，不改卡） |
| `mapping-suggest` 映射建议 | `kb_review`（`review_kind: card_maps`） | 卡 `c*` 必须在事实里；目标节点存在、表达式参数在语法里；换上映射后知识库校验不新增错误、该平台族门槛样本往返不变差、翻译回归（该平台族的用例，每条最多 20 秒）不变差，否则拒绝（超时跳过的给提醒） | 进审核队列；通过时写 `maps` 并标 `maps_manual` |
| `report-summary` 报告摘要 | `text_only` | 结果由导出报告同一套 core 函数算出；数字只能写 `<<键>>`，直接写出的数字拒绝（`number_not_from_code`）；`kind` 为 zh-CN / en | 放进导出的报告（见下） |

**审核队列新增的通过动作**（`review.register_action`，`review._load_actions` 导入本模块）：`rule`（edited.yaml 可改）、`unknown_card`（edited.card）、`card_maps`（edited.maps）。只有维护员与管理员能通过（审核接口原有权限），AI 建议的采纳也只有维护员与管理员。

**本地模型限制**：`ai_suggest_kb.local_gate(env, skill)` 按发起人当前生效的 AI 接口（`ai.resolve`）判断 provider 是否为 `local`；skill 的 `prepare`（运行提交、估计）与 `build`（后台执行时再确认）都会拒绝（409，`ai_kb.local_only`，data 给出 provider 与接口），一个字也不发送；`GET /projects/{p}/ai/kb/gate?skill=sanitize-review` 给界面在运行前拦住。没有配置 AI 的回放不拦（不发送内容）。

**报告摘要的导出**：范围 `report:check:<设备>`、`report:baseline:<基线>:<设备,…>`、`report:compare:<A>:<B>`、`report:change:<当前>:<目标>`（A / B 写 `d<设备>` 或 `v<版本>`；配置文本不支持）。导出接口 `POST /reports`、`/baseline/report`、`/change/report` 加 `include_ai_summary`（默认 true），命令行 `lmesh report check|compare`、`lmesh baseline --report`、`lmesh change --report` 加 `--ai-summary/--no-ai-summary`。导出时取本项目该范围、该报告语言最近采纳的一条，用导出时的结果重新计算数字与对象名填入；采纳后数据变了（数字不同或编号不存在）时只写一行说明。HTML 中 AI 部分是紫色虚线框“摘要（AI 撰写）”，代码填入的部分加粗下划线；Markdown 为 `> [AI]` 引用块；末尾注明 AI 撰写、skill 与版本、接口与模型。“割接报告”对应变更报告（割接迁移没有报告导出）。

**新的接口与命令**：`GET /projects/{p}/ai/kb/gate`、`POST /projects/{p}/ai/kb/extract-text`（txt / md / docx → 文字，docx 用标准库读取）、`GET /projects/{p}/ai/kb/sanitize-redact`；`lmesh ai suggest run … --doc <规范文件>`、`lmesh ai suggest redact`。

**界面**（新组件在 `frontend/src/components/ai-kb/`，文案 `i18n/pages/ai-kb.json`、`kb-ai.json`；知识库与脱敏草稿的卡片内容 `components/ai-suggest/AiKbDetail.vue`）：配置检查页“规则”标签的规范转规则（上传 txt / md / docx 或粘贴、条款状态、四步步骤条、规则编写助手、已送审列表，只对维护员与管理员显示）；安全基线页设备详情里不符合规则的“申请例外”弹窗（两段文字可复制）；设备配置分析页页头“脱敏复核”（先查 gate，非本地模型不显示运行入口；已脱敏配置中标出的行、本项目的脱敏补充）；未识别行页的归因入口与“AI 归因”列；审核队列的命令卡审核助手（可粘贴文档原文）与 rule / unknown_card / card_maps 三种条目的显示、编辑后通过；Schema 视图页头“映射建议”对话框；检查、对比导出对话框与基线、变更页的报告摘要块（`ReportAiSummary.vue`，“包含 AI 摘要”默认勾选）。通用面板新增 `canEstimate`（参数不完整时不请求估计），忽略 / 恢复后也发出 `changed`。

**与预览的差异**：脱敏复核发给模型的是已按规则脱敏的行（预览写“读未脱敏原文”，与“发给 AI 的配置一律先脱敏”冲突，D-0275）；没有接口切换开关（改为去“我的 AI”切换并重新检查）与“已替换 N 处”的数字；命令卡审核助手只标注，没有“按标注修改”的效果；映射建议放在 Schema 视图的对话框里，没有未映射卡的计数；未识别行没有设备、平台列；报告页没有导出预览纸面、“标出 AI 部分”和“标注接口”两个开关（报告总会标注）与报告类型切换，摘要块放在各报告自己的导出处。

**测试**：单元 `tests/unit/test_ai_suggest_kb.py`（7 个 skill 的通过与拒绝、未配置降级、样例回放、审核队列三种动作、本地模型限制、重新脱敏、报告导出与数据变化）；API `tests/api/test_ai_kb_api.py` 与用例 `api_cases.ai_kb.toml`；CLI 用例 `cli_cases.ai_kb.toml`（回放 `tests/inputs/ai-kb/`）；vitest `components/ai-suggest/kb.test.ts`；e2e `frontend/e2e/m85.spec.ts`（`playwright.m85.config.ts` + `e2e/m85_server.py` 假的本地模型）。

### M8-8 结果（可部署版本，REQ-046）

四种可部署形式，全部离线可装，产物只生成在本机 `dist/`（`.gitignore` 已忽略），不推送远程。部署说明见 `docs/deploy.md`。决策 D-0287～D-0290（升级时知识库合并）与 D-0297～D-0303（打包）。

| 形式 | 产物 | 构建位置 | 内容 |
|---|---|---|---|
| Docker 镜像 | `lmesh_<版本>_docker-image.tar.gz`（`docker save` 后 gzip，`docker load` 导入）、`lmesh_<版本>_docker-compose.tar.gz`（`compose.yaml` SQLite、`compose.postgres.yaml`、`.env.example`、部署指南） | Linux | 根目录 `Dockerfile` 多阶段：`node:24.22.0-trixie-slim` 构建前端 → `python:3.12.13-slim-trixie` 运行（uv 0.13.1 只在构建时用，`uv sync --frozen --no-dev --no-install-project`），非 root 用户 uid 10001，`HEALTHCHECK` 调 `/api/v1/health`；`src/` 经 `.pth` 加入导入路径；数据、配置、日志是命名卷；镜像名 `lmesh:<版本>` |
| Linux 离线安装包 | `lmesh_<版本>_linux-x86_64.tar.gz` | Linux | uv 管理的 python-build-standalone 3.12 + 依赖直接装进运行时（按 `manylinux_2_28` 选 wheel）+ `src/`（含已构建前端）+ `knowledge/`；`install.sh`（默认 `/opt/lmesh`，`--user/--create-user`、systemd、`--dry-run`、升级时备份与迁移）、`uninstall.sh`（默认保留数据，`--purge`）、`start.sh`、`bin/lmesh` |
| Windows 离线包 | `lmesh_<版本>_windows-x64.zip` | Windows | 同上的 Windows 版运行时；`start.bat`、`lmesh.bat`、`service-install.bat` / `service-uninstall.bat`（WinSW 2.12 .NET 4.6.1 版，MIT 许可证随包附 `service\WinSW-LICENSE.txt`） |
| Windows 安装程序 | `lmesh_<版本>_windows-x64_setup.exe` | Windows | NSIS 3.11 便携版（`.toolchain/nsis/`，不装到系统）：三语安装向导、默认 `%LOCALAPPDATA%\Programs\LucidMesh` 不需要管理员、开始菜单与桌面快捷方式、可选注册服务、升级时停止旧进程并备份 SQLite、卸载时询问是否保留数据（静默时保留） |

- 构建：`scripts/build_release.bat <版本>`（Windows，默认 `--targets win-zip,win-exe`）、`scripts/build_release.sh <版本>`（Linux，默认 `linux,docker`）；版本号取 `pyproject.toml`，可加后缀（`0.5.0-rc`）；`--work` 指定中间目录；输出附 `lmesh_<版本>_SHA256SUMS.txt`。NSIS、WinSW 按固定 SHA256 下载到 `.toolchain/`。
- 离线包不安装项目本身：运行时 site-packages 里的 `lmesh-src.pth` 指向包内 `src/`（相对路径），程序按 `pyproject.toml` 找到根目录、读版本号（`lmesh/__init__.py` 在未安装时读 `pyproject.toml`）。去掉运行时里的 Tk、IDLE、ensurepip；Windows 包里相对路径超过 160 个字符的 `.pyc` 不打包，避免装到较深目录时超过 260 个字符。
- 升级：Docker 换镜像后启动即迁移；Linux `install.sh` 与 Windows 安装程序识别已装版本，备份 SQLite（`backup/`）、替换程序文件、保留 `config/ data/ logs/`，再执行 `lmesh db upgrade` 与 `lmesh kb upgrade`。
- 升级时知识库合并（协调方追加，`core/kb/upgrade.py`）：运行时知识库仓库的 `builtin` 分支记录每个版本的自带知识库快照（首次复制建仓时建立基准）；按 git 历史三方比较，用户没改过的文件采用新版本，双方都改过的保留用户版本、以 `conflict` 类型（`source.via = kb-upgrade`，新版本删除时 `payload.theirs_deleted`）送审核；合并后打发布标签，`lmesh kb upgrade --rollback` 回滚；没有 `builtin` 分支的旧安装把与新版本不同的文件全部送审核。`lmesh serve` 启动时自动合并（失败不影响启动）。复制自带知识库时不再带上 `knowledge/.git`。
- 安全：compose 的 PostgreSQL 密码只在 `.env`（示例为占位符，提示修改）；环境变量提供的数据库连接串不再被命令行向导写进 `config.toml`（`setup.apply`）。
- 测试：`tests/unit/test_kb_upgrade.py`（无冲突、冲突进审核与采纳 / 驳回、回滚、旧安装首次升级、建仓即建基准）、`tests/unit/test_setup_env.py`、`tests/cli/test_kb_upgrade_cli.py` 与 `tests/cases/cli_cases.kb_upgrade.toml`（文档示例）。
- 试打包 `0.5.0-rc` 验证（2026-10-19）：Windows zip 在干净目录解压后启动、向导与 health 正常；exe 静默安装到 `tmp/os/m88/exe-test`、启动、模拟从 0.4.9 升级（停止运行中的实例、备份数据库、保留配置）、静默卸载（保留数据、清除注册表与开始菜单）；Linux 包装到 `~/lmesh/tmp/install-test`（不注册 systemd、不建用户，systemd 单元用 `--dry-run` 检查）、向导与 health 正常、升级时备份并合并知识库、卸载（保留 / 全部删除）；Docker 用 SQLite 与 PostgreSQL 两份 compose 各起一次，容器 healthy、向导完成后数据库正常，验证后删除容器与卷。
- 遗留：注册 Windows 服务与 systemd 服务需要管理员 / root，本次只做了 dry-run 与脚本检查；正式出 0.8.0 由主 agent 在用户验收后用同一脚本重新构建。

## 拓扑设备图标（REQ-042）

用户 2026-10-19 提出：网元拓扑视图需要设计设备的图标。做法（Claude 按推荐，等预览评审）：

- 图标按设备角色区分：核心、汇聚、接入、PE、P、CE、未解析对端、外部网络；角色未知时按平台类型给出默认图标（例如 ATN 为接入路由器、7750 为核心 / 边缘路由器）。
- 图标上叠加厂商标识（HW / CS / NK）与状态角标（有检查问题、一致性问题、配置过期）。
- 线条风格统一、单色可着色，明暗主题两套，72 / 32 / 16 像素都可辨认；用于拓扑视图、关系图谱、设备列表。
- 角色来源：用户手工标注优先，其次 M8 的“拓扑整理”AI 建议（采纳后），最后按平台默认。
- 先在 `DevelopDocs/ui-preview/REQ-042/` 做预览页，评审后随 M8 实现。
- 评审结果（用户 2026-10-19，三页全部通过）：图标风格三套都做（A 圆柱、B 几何徽章、C 线框），可在设置中切换（个人偏好，默认 B）【用户修改】；角色未知时按平台画设备外形；状态角标最多 2 个加“+n”；全屏优先浏览器全屏、不支持时页面内最大化；待采纳的 AI 角色建议以紫色虚线半透明显示。

## 视图全屏（REQ-043）

用户 2026-10-19 提出：所有视图可以全屏显示操作。做法（Claude 按推荐）：

- 前端通用全屏组件：每个图形视图、视图页签、编辑与对比区域右上角有“全屏”按钮（快捷键 F，Esc 退出），用浏览器全屏；浏览器不支持时退回页面内最大化。
- 全屏时保留该视图的工具栏、图例、选中对象面板与右键菜单，操作与非全屏一致；退出后保持缩放、选中与滚动位置。
- 范围：设备配置图、关系图谱、拓扑与一致性、设备配置分析五个页签、依赖分析、影响分析、配置对比、翻译两侧原文、配置检查项目的脚本编辑器、版本历史、表格导出预览。
- 文案三语，明暗主题；e2e 覆盖进入、操作、退出。

**实现结果**（M7-7，2026-10-19；预览已评审通过，全屏方式按“浏览器全屏优先、不支持时页面内最大化”；决策 D-0247）：

- 组件：`frontend/src/components/FullscreenPane.vue`（容器）、`FullscreenButton.vue`（按钮，放在区域内的工具栏或页签条，tooltip 写明快捷键，按钮上显示 `F` / `Esc`）、`fullscreen.ts`（逻辑）。全屏只切换容器的显示方式、不重建内容，所以缩放、选中、滚动位置自然保持；容器带 `data-fs`（`off` / `native` / `max`）。
- 行为：先调用 Fullscreen API，不可用或被拒绝时改为页面内最大化（固定定位盖住导航与顶栏，提示条写明是哪一种）；Esc 退出（浏览器全屏由浏览器处理），再按 F 也退出；输入框、下拉框、可编辑区（CodeMirror）聚焦、带修饰键或有对话框打开时 F 不触发，对话框打开时 Esc 先关对话框。一页一个全屏区域；万一有多个，F 作用于已全屏的那个，否则作用于最后注册的可见区域。`localStorage` 的 `lmesh-fs` = `max` 强制页面内最大化（测试与不支持浏览器全屏的环境用）。
- 尺寸重算：cytoscape（配置图、关系图谱、拓扑、影响分析、配置分层）、TCP/IP 视图与结构化脚本的虚拟滚动都用 ResizeObserver 跟随容器；切换后再派发一次 `resize`，翻译页两侧连线等只监听窗口尺寸的组件也会重画。CodeMirror 自己跟随容器。
- 弹出层：区域内的下拉、建议列表、右键菜单本来就在容器里；区域外的对话框与提示在全屏时用 `<Teleport :to="fsTarget">` 挂进全屏元素（项目脚本工作区的新建 / 删除对话框与提示、翻译页的提示），Element Plus 的消息用 `appendTo: fsHost()`（设备分析页）。
- 接入：设备配置图与关系图谱（同一页，区域含图、图例、节点详情、原始配置）、拓扑与一致性（含两个页签与侧栏）、设备配置分析五个页签（含页签条与选中对象面板）、依赖与影响分析（同一页，两个方向）、配置对比（汇总、差异列表 / 差异图、详情、两侧原文）、翻译两侧原文（含告警面板）、项目脚本工作区的脚本编辑器（含脚本列表、问题与模拟结果）、版本历史的差异区（图差异、配置差异、对象历史三个页签）、表格导出预览（含来源面板）。
- 未接入：项目脚本列表页（只有表格，编辑器在工作区里已接入）；工作区的重排、修订记录、对比三个子页（独立页面，不是“编辑器”本身，后续需要时用同一组件接入）。
- 测试：`src/components/fullscreen.test.ts`（7 例：快捷键、输入框与对话框下不触发、浏览器全屏与被拒绝退回、强制开关、多区域、组件按钮与文案）；`e2e/req043.spec.ts`（拓扑：F 进入、滚轮缩放与点设备打开侧栏、按钮退出后缩放与选中保持、画布尺寸跟随；设备分析：强制页面内最大化、全屏里点引用选中与切页签、Esc 退出后选中与滚动位置保持、F 进出）。

## M1 预览评审修改（M6-9）

用户对 M1 预览页提了两条修改意见（`DevelopDocs/ui-preview/M1/review.json`）：wizard.html“优化确认页面的 UI”、schema-edit.html“数据类型变化，相应的输入框会变化吗”。按推荐做法先改预览页再编码（向导确认页未经二次评审先编码，决策 D-0248）。

### 向导确认页

- 预览：`DevelopDocs/ui-preview/M1/wizard.html?step=5`，页头“确认页”切换可对比修改前后；`?db=bad` 演示有问题时的样子。
- 按分组汇总（界面语言、各设置分组、管理员账号），每行三列：名称、取值、标记。与默认值不同的行左侧色条加浅底，标“已修改”，取值下方写“默认：…”；其余行标“默认”。
- 密码、令牌、API Key 只显示“已设置 / 未设置”（API 令牌未填时显示“完成时自动生成”）；数据库地址仍显示遮住密码的地址。
- 每组标题右侧“返回修改”直接跳到该步；从确认页跳过去的步骤，页脚多一个“回到确认页”，校验本步后直接回来。
- 进入确认页时把全部取值与管理员账号交给 `POST /setup`（dry_run）统一校验一次，顶部显示“检查通过”或“有 N 个问题”，出错的行显示原因、所在组标出问题数；有问题时“保存设置”不可用，页脚提示先处理；可“重新检查”。
- 顶部显示将写入的配置文件路径；与当前运行的监听地址、端口不同的项标“需重启”，并在页尾汇总列出。
- “全部 / 只看已修改”切换；窄屏（≤ 620px）时名称与取值上下排列，没有横向滚动。
- 后端最小补充：`GET /api/v1/setup` 增加 `config_path`（将写入的配置文件）与 `running`（`server.host`、`server.port` 的当前运行值），测试 `tests/api/test_m69_api.py`。
- 逻辑在 `frontend/src/views/wizard/wizard.ts`（`confirmRows`、`confirmStats`、`needsRestart`、`groupErrors`），单元测试在 `wizard.test.ts`。

### Schema 编辑：输入项随数据类型变化

- 预览：`DevelopDocs/ui-preview/M1/schema-edit.html`（换“数据类型”即可看到）。
- 按类型显示的设置项（`frontend/src/views/schema/typefields.ts` 的 `TYPE_FIELDS`，组件 `views/schema/TypeParams.vue`）：
  - integer：取值范围，最小值、最大值两个输入框，都是整数且最小值不大于最大值，两端都空表示不限，只填一端报错；
  - enum：可选值，标签式输入（回车或逗号添加，退格删最后一个），必填、至少 1 个、不能重复；
  - object：键字段、是否有序；
  - ref：引用目标，必填，只能选 object 节点（选了非 object 节点报错）；
  - ipv4、mask、prefix、rd、asn、community、interface：只显示格式说明与示例；
  - boolean、flag、string、text：没有额外设置项。
- 换类型后，不再适用但已填的内容在表单里用警告列出（“保存时会清掉”），提供“改回原类型”；`formToBody` 只提交当前类型适用的字段，`validateForm` 只校验适用的字段，两者同步（决策 D-0250）。现有知识库中只有 `mgmt.ssh.version`（string 带 choices）会出现这条提示。
- 后端接口不变。

### Profile 默认值输入

- 预览：`DevelopDocs/ui-preview/M1/profiles.html`。
- 按节点类型（`frontend/src/views/profiles/defaults.ts`）：boolean / flag 用“不设置 / 开启 true / 关闭 false”三态分段按钮（单个开关无法表示没有默认值，决策 D-0249）；enum 用下拉（含“不设置”）；integer 用数字框并按取值范围校验；ipv4、prefix、rd、asn、community、interface 等按格式校验；其余用文本框。有问题时不能保存。保存时布尔转 true / false、整数转数字、枚举保持文字。
- 后端最小补充：`GET /api/v1/kb/profiles/{id}` 的条目增加 `choices`（enum）与 `range`（integer），测试同上。

### 测试

- 单元：`wizard.test.ts`、`schema.test.ts`（按类型的字段规则、换类型清理、enum / ref 校验、格式校验）、`profiles.test.ts`（默认值输入方式、校验、转换）。
- 端到端：`frontend/e2e/m69.spec.ts`（向导确认页：浏览器内替换 `/health` 与 `/setup` 为未配置实例的应答，检查汇总、需重启、只看已修改、重新检查出问题后不能提交、返回修改后回到确认页、窄屏；Schema 编辑换类型）。

## 未支持型号的处理（REQ-044）

用户 2026-10-19 提出：导入的设备款型不存在怎么办，可以手工选择（例如华为 NE8000 选 ATN 的 Profile）。现状：认不出厂商时拒绝导入（提示文字漏了 Nokia）；认得厂商但版本不匹配时静默套用该厂商的 fallback Profile，界面没有提示；导入只识别厂商与软件版本，不识别硬件型号。经用户确认的做法（【用户确认】，排期 M8，M8 整合后做，先做预览页）：

1. 手工选择 Profile：导入对话框每个文件显示识别结果与匹配程度（精确：版本规则命中；近似：只按厂商套用 fallback；无：认不出厂商），可改选 Profile。**只允许同厂商 / 同平台族**【用户确认】；认不出厂商时可在全部 Profile 中选。设备记录 Profile 来源（auto / fallback / manual），之后的导入与重新解析沿用手工选择；设备页可“更换 Profile 并重新解析”。API `POST /configs` 可按文件指定 Profile，CLI `lmesh import --profile`。
2. 试解析推荐：用候选 Profile（同厂商 / 同平台族）各试解析一次，按识别出的命令行比例排序推荐（确定性，不用 AI）。
3. 型号规则：手工选择时可“记住”，生成匹配规则（设备名模式、版本、特征命令 → Profile），作用范围为项目或全局（全局由维护员管理），导入时优先按规则自动选择。
4. 近似标记：近似或手工 Profile 的设备在设备列表、配置图、报告中标出并显示未识别行比例；变更脚本、翻译结果下发前提示“基于近似 Profile，请核对”（默认值按所选 Profile 补，可能与真实型号不同）。
5. 申请支持：设备页“申请支持此型号”进入审核队列（建议）；维护员可从现有 Profile 派生（继承，只写差异）并补命令卡（可用 M8-5 未识别行归因）；派生 Profile 发布后型号规则改指向它，已导入设备一键重新解析。
6. 认不出的厂商：可只存原文、不解析（标“不支持的厂商”），可查看、文本对比、版本历史；按通用规则脱敏。提示文字补上 Nokia。

### 实现结果（M8-7）

2026-10-20 完成。预览：`DevelopDocs/ui-preview/REQ-044/`（导入识别、设备页、型号规则、审核派生、不支持厂商的原文 5 页 + 评审索引）；预览未经评审先按推荐编码（决策 D-0286），评审意见随后修改。

**选择顺序**（`core/model_support.py` 的 `choose`，导入与重新解析共用）：本次指定（导入按文件 / 设备页更换）→ 设备之前的手工选择（一直沿用，直到改回自动）→ 型号规则 → Profile 的版本规则 → 厂商默认（fallback）→ 都没有时只存原文。手工与规则只允许同厂商 / 同平台族（Nokia Classic 与 MD-CLI 是不同平台族）；认不出厂商时可在全部 Profile 中选，设备厂商记为所选 Profile 的厂商。

**数据与迁移 0011**：`devices` 加 `profile_source`（auto / fallback / rule / manual / none）与 `profile_rule_id`（按哪条型号规则选的，规则删除时置空）；新表 `model_rules`（`project_id` 为空是全局规则；`vendor`、`name_pattern` 设备名 * ? 通配不分大小写、`version` 版本正则、`feature` 特征命令正则（按行匹配）、`profile`、`note`、`enabled`）。已有设备 Profile 为空的记 none，其余记 auto，下一次重新解析时按新的顺序重新判断。型号规则选中的设备来源单独记 rule（属于近似；规则改指向后重新解析会跟着变），fallback、rule、manual 统称“近似”。

**试解析推荐**：候选 Profile 各解析一次（同一平台族只解析一次），比例 =（命令行 − 该 Profile 明确不支持的命令）/（命令行 + 未识别行）；比例相同按版本规则命中 > fallback > 编号。不用 AI。

**型号规则**：至少一个条件、正则有效、只能指向同厂商的 Profile（不写厂商时取 Profile 的厂商）。生效顺序：本项目规则 > 全局；同一范围内条件多的优先，一样多时编号小（先建）的优先；停用的不生效。“记住”不写条件时按设备名（末尾编号换成 *）与主版本（华为 VxxxRyyy、Cisco / Nokia 前两段）预填；同一批相同的规则只建一次；刚记住的规则命中这台设备时来源记为 rule，被更早的规则抢先时按手工选择。全局规则只有维护员与管理员能建、改、删（接口 403、导入时“记住为全局”同样 403）。

**近似标记**：设备列表（来源标记、未识别比例、页头提示与筛选）、配置图（提示条，`profile_info`）、对比与检查报告（Profile 一格附“近似（厂商默认 / 型号规则 / 手工选择），未识别 x%”，中英文）；增量变更与配置翻译的结果带 `approx_profile`，页面在结果上方提示“基于近似 Profile，请核对”。

**申请支持与派生**：`POST /devices/{id}/support-request` 进审核队列（类型 suggestion，`payload.kind = model`，附设备信息、当时的 Profile 与来源、未识别行前 20 种模式；只读成员也可以提交）。维护员在审核队列“建议”页签展开处理：派生（`edit.create_profile` 继承基础 Profile，写入草稿区）→ 补差异与命令卡、发布 → 改指向：匹配申请设备的启用规则（本项目或全局）改指向派生的 Profile，没有规则时按预填条件新建一条全局规则；重新解析这些规则选中的设备与会被它们命中的设备（所有项目，手工选择的不动；申请设备本身手工选的就是申请时的 Profile 时改回自动），申请标为通过。派生 Profile 未发布也允许改指向（运行时知识库已包含草稿），界面与结果提示“未发布”（`released`）。

**认不出的厂商**：导入接口默认不导入（`unsupported=skip`，提示文字补上 Nokia），`unsupported=raw` / `--keep-unsupported` / 对话框选“只存原文”时按通用规则脱敏后只存原文（厂商为空、来源 none、不解析、不建图）；设备名另外识别 `host-name X;` / `set system host-name X`；通用脱敏另外替换关键字后引号里的口令与密钥（例如 `encrypted-password "…"`）。可以看原文、版本历史；`GET /devices/{id}/history/diff` 对这类设备只给原文差异（`raw_only`），配置图接口 409（`data.raw_only`）。

**接口与命令**：`POST /configs/inspect`（导入前识别，不入库）、`POST /configs` 增加 `profile`、`choices`、`unsupported`；`GET /devices/{id}/profile-candidates`、`PUT /devices/{id}/profile`、`POST /devices/{id}/support-request`；`GET|POST /model-rules`、`POST /model-rules/test`、`PUT|DELETE /model-rules/{id}`；`GET /kb/model-support/{审核编号}`、`POST …/derive`、`POST …/retarget`（维护员）。CLI：`lmesh config import --profile / --keep-unsupported / --remember [--match-*]`（规格中写的 `lmesh import --profile` 即此命令）、`lmesh device profiles / set-profile / request-support`、`lmesh model-rule list / add / update / remove / test`、`lmesh model-support show / derive / retarget`。

**界面**：导入对话框新增第 3 步“识别与 Profile”（`devices/IdentifyStep.vue`）；设备页行菜单“更换 Profile 并重新解析”（`ProfileDialog.vue`）与“申请支持此型号”（`SupportDialog.vue`，近似或不支持厂商的设备才显示）；型号规则是项目页面 `/p/<项目>/model-rules`（导航“设备与配置”组；本项目 / 全局两个页签，全局对普通用户只读）；审核队列“建议”页签里的型号支持申请展开 `review/ModelSupportPanel.vue`；配置图、版本历史、增量变更、配置翻译的提示条。文案在 `frontend/src/i18n/pages/model.json`。

**测试**：单元 `tests/unit/test_model_support.py`（匹配程度、只允许同族、试解析排序、规则优先级、导入手工选择与记住、重新解析沿用手工、只存原文与文本对比、申请 → 派生 → 改指向并重新解析、没有规则时新建全局规则、迁移 0011）；API `tests/api/test_model_support_api.py`（全局规则只有维护员与管理员能改、导入记住为全局 403、只读成员不能更换但能申请、普通用户不能处理申请、配置图 / 变更 / 翻译带近似标记）与 `api_cases.model_support.toml`；CLI `cli_cases.model_support.toml`（准备方式 `configured-fullkb-ne8000`）；前端 `devices/model.test.ts`、`project.test.ts`；e2e `frontend/e2e/m87.spec.ts`（在单独项目里走完导入识别 → 更换 Profile → 型号规则 → 配置图提示）。NE8000 用合成样本 `tests/inputs/configs/ne8000/`（华为写法，版本 V800R022 不匹配任何版本规则），认不出厂商用 `tests/inputs/configs/other/edge-mx-01.conf`。

## 项目内的网络（REQ-045）

用户 2026-10-19 提出：每个项目里可以划分不同的网络，类似拓扑还原，操作在对应的网络中进行；每个网络是独立的，设备可以在多个网络中。经用户确认（【用户确认】）的部分：

- 网络是项目内的独立工作区，平铺、不分层【用户确认】；设备仍属于项目（导入、版本历史、删除在项目层），网络引用设备，一台设备可在多个网络中【用户确认】；权限仍按项目【用户确认】。
- 顶栏网络切换器，网址带网络（例如 `/p/<项目>/n/<网络>/topology`）【用户确认】；选“项目全部设备”时为项目层的设备管理。
- 每个网络独立：拓扑还原（只用本网络设备；角色、分组、布局、手工标注）、跨设备一致性、检查与基线、规则调整、项目脚本 / 配置检查项目、变更方案、割接迁移、AI 建议与采纳记录、报告与导出。
- 设备版本：默认跟随最新，网络内可固定版本（沿用 M6 设备引用的做法）。
- 快速建网络的建议（代码计算，预览后采纳）：连通分量、IGP 域、BGP AS；设备名规则、管理网段（也用于新导入设备自动加入）；AI 拓扑整理的分组【用户确认：三类都要】。
- 层级：平铺 + 文件夹式分组（文件夹只整理列表，不包含设备、不继承数据）；需要看全局时用默认网络【用户确认】。“汇总下层网络”的包含关系暂不做，以后需要时可在此基础上升级。
- 升级时每个项目自动建“默认网络”（包含全部设备、自动加入新导入的设备），现有拓扑标注、脚本、检查忽略、AI 建议等移入默认网络【用户确认】。
- 网络的自动加入规则命中时直接加入，并在导入结果里提示加入了哪些网络【用户确认】。
- 模板、翻译规则集仍按项目 / 个人共用，不按网络独立【用户确认】。
- 网络外的对端：拓扑上有“显示网络外的对端”开关（默认关），打开时画成灰色短线并标出对端所在的网络。
- 网络操作：新建、改名、复制（连同工作数据）、删除（只删网络与其工作数据，不删设备）。
- 接口 `/api/v1/projects/{p}/networks`（增删改、成员、建议、自动加入规则），按网络的操作 `/projects/{p}/n/{net}/…`；CLI 全局参数 `--network`；权限仍按项目。
- 排期：新里程碑 M9（0.9.0）。REQ-044 在 M8 开发的同时先做 M9 预览页，预览确认后再编码（Claude 按推荐定下，见决策记录）。
- 预览评审（用户 2026-10-20，`DevelopDocs/ui-preview/M9/` 9 页全部通过，设计问题均选推荐）：顶栏“项目 › 网络”两个切换器并排；删除网络不进回收站，确认时列出内容并输入网络名；复制网络时复制已采纳的 AI 结果与采纳记录（注明“复制自”），不复制待处理的建议；网络外对端默认关，按网络记住每个人上次的选择；默认网络可以改名、不能删除；选“全部设备”时拓扑、检查、脚本等按网络的页面显示各网络汇总（项目层网址，不带网络；升级前的旧网址落到这里），可点进各网络；网络识别色从 8 色中按创建顺序自动分配，可换成组内其他颜色。

### M9 后端结果（M9-2～M9-4）

数据模型、迁移、按网络隔离、网络管理与建网建议的后端；界面在 M9-5 做。决策记录见 DevelopDocs/decisions/（M9 后端）。

- 数据（迁移 `0012_networks`，接在 `0011` 之后，SQLite 与 PostgreSQL 都测过从 0011 样本数据升级）：
  - `networks`（项目、`slug` 项目内唯一、`name`、`description`、`color`、`folder_id`、`position`、`is_default`、`copied_from`、`stats` 按设备记下的最近检查结果、`last_activity`、`created_by`）；
  - `network_folders`（只整理列表）、`network_rules`（自动加入规则：`kind` name 设备名通配 / subnet 管理网段 CIDR）；
  - `network_members`（设备、`version_id` 为空 = 跟随最新 / 否则固定、`join_source` upgrade / default / manual / rule / suggestion / copy / import、`rule_id`、`excluded` 手工移出的排除标记、`joined_by` / `joined_at`）；
  - 工作数据表加 `network_id`：`check_ignores`、`check_projects`（脚本组，脚本与修订随它）、`project_rule_overrides`、`ai_suggestion_batches`、`ai_suggestions`、`view_annotations`；忽略项、规则调整、视图标注的唯一约束从按项目改为按网络。
  - 升级：每个项目建默认网络（标识 `default`、名称“默认网络”、颜色 `slate`），私有设备与引用的公共设备都成为成员（`upgrade`，跟随最新），上述工作数据都移进默认网络。之后新建的项目在第一次用到时自动建默认网络。
- 当前网络（`core/projects.py` 的 Scope 加 `network_id` / `network_slug` / `network_name` / `network_default` / `network_explicit`）：
  - API 的网络路径、命令行 `--network` 设置它；不带网络时为项目的默认网络。
  - 设备范围：默认网络为项目全部设备，其他网络为成员（不含排除）；不在网络里的设备与版本按“不存在”处理（404）。
  - 版本：网络里固定的版本 → 项目引用公共设备固定的版本 → 最新版本（`current_version_id`、`pins`）。
  - 工作数据按 `network_id` 读写：`ignores`、`checkproj`、规则调整（Scope 的 `overrides` 按网络载入）、AI 建议框架（`Env.network_id`，只给项目时取默认网络）、视图标注、报告摘要与翻译补丁的采纳记录。
- 隔离的范围与例外：
  - 按网络：拓扑与视图标注、一致性、检查与基线结果、检查忽略、规则调整、脚本（基线只能选本网络的设备，默认用本网络为它选的版本）、变更、割接、影响分析、对比、报告与导出、图查询与 AI 查询、AI 建议与采纳记录。变更、割接、报告不入库，按设备范围与版本隔离。
  - 项目层（不按网络）：设备与导入、版本历史与标签、删除设备与版本、型号规则（REQ-044）、项目设置（显示风格、规则集、安全基线的选择）、脱敏补充、成员与权限、模板与翻译规则集（项目 / 个人共用）。
  - 安全基线的选择仍在项目设置里，基线结果按网络的设备与版本计算。如需按网络选基线，以后在 `networks` 上加设置。
- 接口：
  - 按网络的路径 `/api/v1/projects/{p}/n/{net}/…`（`api/scoping.network_guard`），挂了项目路径的接口都有网络版本。
  - 不挂网络路径的是 `api/access.NETWORK_EXCLUDE` 中的项目设备池管理（删除设备与版本、删除预览、贴 / 删标签、型号规则），以及项目管理（设置、成员、转交、复制、引用、`/networks` 本身、`/ai/kb/sanitize-redact`）。
  - 不带网络的项目路径与旧路径作用于默认网络。按评审，“全部设备”页显示各网络汇总，汇总数据由 `GET /projects/{p}/networks` 提供（各网络的 `counts` 与 `overview`）。按网络的接口不改成返回汇总，这样现有前端与脚本照常工作（决策记录）。
  - 网络管理（只在项目路径下，`api/routes_networks.py`）：
    - `/networks`（列表含文件夹、颜色组、项目概览与各网络汇总；新建）；
    - `/networks/{net}`（详情、修改、删除需 `confirm` 网络名、`delete-preview`、`copy`）；
    - `/network-folders`；
    - `/networks/{net}/members`（列表、加入、批量改版本策略、`remove` 排除、`unexclude`）；
    - `/networks/{net}/join-rules`（增删改、`preview` 命中预览）；
    - `/network-suggestions`（预览）与 `/network-suggestions/adopt`。
  - 写操作记录网络的 `last_activity`。设备完整检查（全部级别、不限功能域）的结果按设备记到当前网络的 `stats`，汇总页的 `findings` 由它算出。
- 导入时自动加入（`networks.auto_join`）：
  - 新设备加入默认网络；在网络路径（或 `--network`）下导入时同时加入当前网络；各网络的规则命中时直接加入（设备名不分大小写；管理网段要有知识库算出管理地址）。
  - 手工移出（排除）的设备不会被规则再加入；在网络里导入或手工加入会清除排除。
  - 导入结果每个文件加 `device_id` 与 `joined_networks`（`via` default / current / rule、`rule`）。
  - 引用公共设备、复制设备到项目时同样加入默认网络与当前网络。
- 管理地址（`networks.mgmt_of_facts`，自动加入与建议共用）：依次取
  1. 管理口（MEth、MgmtEth、mgmt、fxp / em、`GigabitEthernet0`）的地址；
  2. 管理 VRF（名字含 mgmt / manage / oam）里的接口地址；
  3. LSR ID（Loopback0 / system）；
  4. 第一个 Loopback 地址。
  按版本缓存。
- 建网建议（`networks.suggest` / `adopt`）：代码在项目全部设备的配置图上计算，不入库。
  - 依据：
    - components：同网段链路的连通分量，默认不算管理口 / 管理 VRF 的链路；
    - igp：IS-IS 进程与 OSPF 进程 + 区域，一台设备可在多个建议里；
    - bgp：本地 AS；
    - name：正则第一个括号，默认 `^(.+)-[^-]+$`，给出规则 `组名-*`；
    - subnet：管理地址按前缀汇总，给出 CIDR 规则；
    - ai：当前网络里 M8 拓扑整理已采纳的 `group` 标注（来源 ai）。代码校验设备都在项目里、组内按同网段链路连通，不通过的 `check.status = reject`、不能采纳。没有配置 AI 时其他依据照常可用。
  - 每个建议给出设备数、和现有网络的重叠（不含默认网络）、与现有网络完全相同的（`same_as`，不能采纳）、和其他建议重叠的设备。
  - 采纳时按同样参数重新计算，逐个或全部采纳；每个建议建一个网络，成员加入方式 suggestion；`with_rules` 时把规则设为新网络的自动加入规则。
- 网络操作：
  - 新建：颜色按项目里已有网络数从 8 色中轮流分配，默认网络是第一个 `slate`。
  - 改名、标识、颜色、文件夹、位置：默认网络可以改名。
  - 复制：成员与版本选择、规则与排除、标注、忽略、规则调整、脚本组与脚本（含全部修订）；已采纳与已撤销的 AI 建议连同批次一起复制，`note` 与 `adopt_info.copied_from` 注明复制自哪里；不复制待处理与已忽略的建议。
  - 删除：只删网络与它的工作数据，不进回收站；`confirm` 为网络名称或标识；默认网络不能删除；默认网络的成员不能移出。
  - 复制项目时网络、文件夹、成员（按设备对应关系）、规则、标注、忽略一起复制，规则调整与脚本复制到对应网络；AI 记录不复制，与 M6 相同。
- 拓扑：
  - `GET …/topology?outside=true`（`POST` 的 `outside`）在项目全部设备上还原一次，取一端在本网络、另一端不在的链路作为 `outside.links`（`inside`、`peer` 设备与它所在的网络）；默认网络没有“网络外”。
  - 返回体另有 `network` 与节点的 `also_in`。
  - “按网络记住每个人上次的选择”由前端保存（浏览器，按账号与网络）。
- 命令行：
  - 全局 `--network`（`-N`）：在 `--project` 里找，不存在退出码 4，不给时为默认网络。
  - `lmesh network list|show|create|update|delete|copy|members|add|remove|pin|follow|rules|rule-add|rule-preview|rule-delete|folder-add|folder-delete|suggest|adopt`。
- 给 M9-5 前端的接口说明：
  - 切换器与网络页：`GET /projects/{p}/networks`（`networks[].counts`、`folders`、`palette`、`overview`）。新建、改名、移动用 `POST /networks`、`PUT /networks/{net}`（`folder_id` + `move`）；文件夹用 `/network-folders`；复制用 `POST /networks/{net}/copy`；删除先 `GET …/delete-preview`，再 `DELETE …?confirm=<名称>`。
  - 页面数据：按网络的页面把 `api.ts` 的项目路径改写为 `/projects/<项目>/n/<网络>/…`；项目层网址（“全部设备”）的设备页照常用 `/projects/<项目>/devices`。按网络的页面在项目层用 `GET /networks` 显示各网络汇总：检查页用 `counts.findings`、脚本页用 `counts.scripts` / `scripts_with_errors`、拓扑页用 `counts.annotations` / `ai_pending`。
  - 成员页：`GET /networks/{net}/members`（`policy`、`seq`、`latest_seq`、`newer_available`、`also_in`、`join_source`、`rule`、`joined_at`、`mgmt_address`）；批量操作用 `PUT …/members`、`POST …/members/remove`。“撤销本网络的自动加入”就是对这几台调用 `remove`。
  - 规则：`/join-rules` 与 `/join-rules/preview`。
  - 设备页：每行的 `networks`、`network_policy` 等字段；导入结果的 `joined_networks`；删除设备的预览（`GET …/devices/{id}/delete-preview`）另有 `networks`，即删除后会从哪些网络里一起移出。
  - 拓扑页：`?outside=true` 的 `outside.links[].peer.networks`、节点 `also_in`；节点角色与分组用该网络的 `/view-annotations`。
  - 建网建议页：`GET /network-suggestions?basis=…`（`suggestions[].devices`、`overlap_existing`、`same_as`、`overlap_suggestions`、`overlap_devices`、`check`、`adoptable`、`rule`），采纳用 `POST /network-suggestions/adopt`。
  - 识别色键到明 / 暗色值的对应由前端定义（预览 `m9.css` 的 `--n-*`）。
- 测试：
  - 单元 `tests/unit/test_networks.py`：迁移 0012、默认网络与成员、固定版本、自动加入与排除、隔离、复制与删除、复制项目、建网建议各依据与采纳、AI 分组校验、网络外的对端与管理地址；SQLite 与 PostgreSQL 各一次。
  - API 流程 `tests/api/test_networks_api.py`：权限、路径、汇总、隔离、导入加入、拓扑 outside、成员、规则、建议、文件夹、复制、删除、项目层接口不挂网络路径、只读令牌。
  - API 用例 `tests/cases/api_cases.networks.toml`。
  - CLI 用例 `tests/cases/cli_cases.networks.toml`。
- 遗留：
  - 安全基线的选择仍按项目。
  - 命令行 `lmesh check` 不写网络的检查汇总，只有接口写。
  - 管理地址是推断的，没有专门的“管理地址”配置项。
  - “汇总下层网络”按评审暂不做。

### M9-5 前端结果

按 `DevelopDocs/ui-preview/M9/` 的评审结论实现；决策记录 D-0315～D-0322。

- 路由：按网络的页面（`project/scope.ts` 的 `PROJECT_PAGES[].net`：net / both / only）另有网络层路由 `n-<页面>`，网址 `/p/<项目>/n/<网络>/…`；项目层同名网址为“全部设备”。`router.push / resolve` 按当前网络补参数（`withNetwork`，`params.network: null` 回到项目层）。
  - net（拓扑、一致性、检查、清理、基线、脚本、变更、割接、影响、分析、导出、成员）：项目层显示各网络汇总（`NetSummaryView.vue`，数据来自 `GET /networks` 的 counts）；项目只有默认网络、或网址指向具体对象（设备、脚本编号、`?device=`）时直接进默认网络。
  - both（设备、添加设备、配置图、版本历史、对比、翻译）：项目层为全部设备，网络里只有本网络的设备与本网络用的版本。
  - only：网络概览 `/p/<项目>/n/<网络>`（`NetworkHomeView.vue`）。项目层页面：网络列表 `/p/<项目>/networks`、建网建议 `/p/<项目>/networks/suggest`、未识别行、型号规则、项目设置。
  - 换网络时页面组件重建（`App.vue` 的 router-view 按网络加 key）。网址里的网络不存在时回到网络列表并说明。
- 接口：`api.ts` 按网址里的网络把当前项目的接口改走 `/projects/<项目>/n/<网络>/…`（`networkPath`，按方法排除 `NETWORK_EXCLUDE` 与项目管理接口）；需要项目层数据时 `get(path, { network: false })`。
- 状态：`stores/network.ts`（当前网络、按项目缓存的 `GET /networks` 列表）。
- 界面：
  - 顶栏网络切换器 `components/network-switcher.vue`（与项目切换器并排；全部设备 + 按文件夹列出、搜索、方向键、Alt+N）；导航按预览分为设备池 / 本网络 / 变更 / 分析，“当前网络”带；按网络的页面顶部有网络范围条。
  - 网络列表 `NetworksView.vue`：项目概览、文件夹（拖动整理、改名、删除）、新建（标识、文件夹、颜色）、改名 / 移动 / 换色、复制（列出一起复制的工作数据）、删除（列出删除内容并输入名称）、共用矩阵。
  - 成员 `NetworkMembersView.vue`：版本策略（跟随最新 / 固定，可批量）、还在哪些网络、加入方式、从设备池添加、移出（排除）、最近自动加入（可撤销）、自动加入规则（命中预览）与排除。
  - 建网建议 `NetworkSuggestView.vue`：六种依据与参数、重叠与校验、逐个或全部采纳（设备名 / 管理网段可同时设为规则）、加到已有网络、划分结果预览。
  - 拓扑：非默认网络有“显示网络外的对端”开关（默认关，按账号、项目、网络记在浏览器），对端画成灰色虚线短线，点开可跳到对端所在网络并选中；设备详情列出“还在这些网络”（`?sel=` 选中设备）。
  - 设备页：所在网络列与网络过滤；网络里显示本网络用的版本与检查结果，删除改到成员页；导入结果列出加入的网络；删除设备的确认框列出会一起移出的网络。升级说明卡片（`components/net-upgrade.vue`）在只有默认网络时显示一次。
  - 识别色 8 个键的明 / 暗色值在 `styles/m9.css`；文案在 `i18n/pages/net.json`（中文、English、Português (Brasil)）。
- 测试：单元 `project/scope.test.ts`（网络路由与接口改写）、`router.test.ts`（网络层路由优先于项目层，`:network([^/]+)` 写成自定义正则参与排序）、`views/networks/logic.test.ts`；e2e `frontend/e2e/m9.spec.ts`（新建网络、成员与规则、切换器与全部设备汇总、网络外的对端与记忆、建网建议采纳、删除网络、暗色）。`m6.spec.ts`、`req031.spec.ts` 的网址断言改为允许 `/n/<网络>/`。
- 遗留：项目设置页的“规则调整”仍作用于默认网络（项目层页面）；按网络的规则调整入口以后放到检查页。复制网络不能逐项选择复制内容（后端整体复制）。

### M9-7 结果（评审修改，REQ-047～REQ-049）

预览 `DevelopDocs/ui-preview/M9-7/`（语言按钮、向导、系统设置）；自动模式按推荐编码，评审意见随后修改。决策记录 D-0323～D-0336。

- 个人偏好随账号保存（REQ-047）：`users.prefs`（JSON，迁移 `0013_user_prefs`，接在 `0012` 之后）；`GET / PUT / DELETE /api/v1/me/prefs`（`lang`、`theme`、`term_style`、`icon_set`，PUT 只改给出的项）。前端 `stores/prefs-sync.ts`：未登录用浏览器本地值；登录时账号保存过就以账号为准，没保存过（或缺项）就把本地值写入账号；登录状态下修改约 0.5 秒后写入账号；全局 API 令牌只用本地值，只读个人令牌只读取。用户菜单显示“随账号保存”的状态。
- 语言按钮：`components/lang-menu.vue`（地球图标 + 当前语言简称，菜单列出三种语言、各用本语言书写，方向键与 Esc），外壳与登录、注册、向导的顶栏共用。
- 界面问题修复（REQ-048）：
  - 打开网页不再闪过主界面：`main.ts` 在第一次导航完成后才挂载。
  - 向导：按预览评审（“空白太多”，D-0336）改为紧凑布局——卡片加宽居中，左侧步骤栏，字段两列，确认页分组两列并排，高度随内容，窄屏时步骤栏变成顶部横条、字段一列；显示风格选项与确认页写成品牌名（`views/wizard/wizard.ts` 的 `optionKey`）；AI 一步加“测试连接”（`POST /setup/ai-test`，只在未配置时可用，不保存、不记录 Key，失败只回传异常类型与状态码，界面按状态码说明原因；参数改了旧结果作废）。设备配置图、设备分析、更换 Profile、申请支持、审核面板里的厂商改用品牌名。
  - 显示风格：Profile 条目表第一行是当前风格的写法、第二行是规范编号；Schema 视图图上的节点显示当前风格的写法，图例显示当前风格，对比列表加写法；Schema 编辑树的写法更醒目。明暗主题都检查过。
- 系统设置（REQ-049）：管理员页面 `/settings`（`SettingsView.vue`，导航“系统管理 → 系统设置”）；`GET / PUT /api/v1/settings` 与 `lmesh config get / set` 共用 `core/setup.py` 的 `settings_view`、`check_settings`、`save_settings`（与向导同一份参数定义与校验，端口与正在运行的不同时检查占用）。写入 `config/config.toml`（按参数定义重新生成，注释保留）；监听地址、端口、数据库、知识库目录、日志标“需重启”，保存后与本进程启动时的配置比较列出待重启的项，不自动重启。敏感值、[ai] 接口项（在 AI 接口页管理）、环境变量指定的项只读。记入审计 `settings.update`（只记配置键）。
- 测试：单元 `tests/unit/test_m97.py`（迁移 0013、偏好校验、测试连接、只读原因、校验汇总、待重启）；接口 `tests/api/test_m97_api.py` 与用例（`setup-ai-test-*`、`settings-*`、`me-prefs-*`）；命令行用例 `config-get*`、`config-set*`；前端单元 `stores/prefs-merge.test.ts`、`views/settings/settings.test.ts`、`views/wizard/wizard.test.ts`；e2e `frontend/e2e/m97.spec.ts`（不闪主界面、语言按钮、换浏览器沿用偏好、风格切换后表格变化、系统设置保存与待重启、普通用户看不到、向导居中与测试连接）。e2e 的 `login()` 先清掉账号里的偏好，各用例仍从浏览器本地值开始。
- 已删除不再使用的 `layouts/LangSwitch.vue`、`ThemeSwitch.vue`（用户 2026-10-20 同意，D-0335）。

### M9-8 结果（创建项目的权限与加入项目，REQ-050）

预览 `DevelopDocs/ui-preview/M9-8/`（我的项目、发现项目、项目成员、邀请链接落地页、账号管理、系统设置）；自动模式按推荐编码，评审意见随后修改。决策记录 D-0337～D-0346。

- 创建权限：配置项 `auth.user_create_projects`（“普通用户可以创建项目”，默认 false，向导“安全”一步、系统设置页、`config.example.toml`）；管理员单独授权存在 `users.can_create_projects`。`core/projects.py` 的 `can_create` / `require_create`：全局令牌、管理员始终可以，其次总开关，其次单独授权；`create_project`、`copy_project` 检查它（403 `projects.create_forbidden`）。不能创建的账号不自动建默认项目（自助注册、批准注册、旧的无项目接口、命令行默认项目都一样）：没有自己的项目时先用加入的第一个项目，都没有时 `projects.no_project`（API 409，`GET /workspace` 的 `default_project` 为 null，命令行退出码 1）。已有项目照常使用。
- 创建权限申请：`POST / DELETE /api/v1/me/create-permission/request`、`GET /me/create-permission`；管理员 `GET /admin/create-requests`、`POST …/{id}/approve|decline`，或 `PUT /users/{username}` 的 `can_create_projects`；命令行 `lmesh project can-create / request-create`、`lmesh user grant-create / create-requests / approve-create / decline-create`。
- 成员角色新增 `manage`（管理）：`Scope.can_manage`（成员、加入申请、邀请链接、可被搜索）为属主、管理、管理员；新增 `Scope.can_own`（删除、转交、改标识）只限属主与管理员；`can_write` 含管理。
- 加入项目：项目设置“可被搜索”（`projects.discoverable`）；`GET /discover`（只给名称、简介、属主、设备数与我的状态）、`POST /discover/{编号或属主~标识}/join-requests`（只读 / 可编辑，默认只读）、`GET / DELETE /me/join-requests`；审批 `GET /projects/{p}/join-requests`、`POST …/{id}/approve`（可改角色，可给管理）/ `decline`。邀请链接 `GET / POST /projects/{p}/invites`、`DELETE …/{id}`（角色、1–90 天、可选仍需审批、备注；令牌 `lmi_…` 只返回一次，只存 SHA-256 与前 6 个字符），使用 `GET /invites/{token}`、`POST /invites/{token}/accept`（joined / pending / member）。核心在 `core/joining.py`，接口 `api/routes_joining.py`，命令行 `cli/cmd_joining.py`。
- 通知：`GET /me/notifications`（我是属主或管理成员的项目里待审批的加入申请，按项目；管理员另有创建权限申请），导航“我的项目”“账号管理”显示数字，每次换页与每分钟刷新。
- 审计：`create.request / cancel / grant / revoke / decline`、`join.request / cancel / approve / decline`、`invite.create / revoke / join`、`project.discoverable`，在“所有项目 → 审计”里有文案。
- 迁移 `0014_project_joining`（接在 `0013_user_prefs` 之后）：`users.can_create_projects`、`projects.discoverable`、`project_invites`、`project_join_requests`、`project_create_requests`；删除项目时一并删除它的申请与邀请链接。
- 界面：`DiscoverView.vue`（`/discover`）、`InviteView.vue`（`/invite/:token`，没登录时先登录再回来）、`views/join/`（等人邀请的提示与创建权限申请 `WaitHero.vue`、我的加入申请 `MyRequests.vue`、接口与纯函数 `join.ts`）、项目设置的 `JoinRequestsPanel.vue` / `InvitesPanel.vue` 与“可被搜索”开关、账号管理的 `CreatePermPanel.vue` 与“可创建项目”列、`stores/notify.ts`、`styles/m98.css`（明暗主题都用变量）；文案 `i18n/pages/join.json`（中文、English、Português (Brasil)）。
- 测试：单元 `tests/unit/test_joining.py`；接口 `tests/api/test_joining_api.py` 与用例 `api_cases.joining.toml`；命令行用例 `cli_cases.joining.toml`（准备方式 `configured-joining`）；前端单元 `views/join/join.test.ts`；e2e `frontend/e2e/m98.spec.ts`（申请创建权限与授权、发现并申请加入、审批给“管理”、管理成员的危险操作锁定、邀请链接只显示一次与撤销、暗色）。测试夹具与 e2e 服务默认打开总开关（D-0345）。
- 遗留：邀请链接不限使用次数；管理员的导航数字不含全站所有项目的加入申请（D-0341）；没有项目的账号外壳仍显示项目分组（点进去回到“我的项目”）。

## 接入 Nokia 7750 SR（REQ-037）

用户 2026-10-19 提出：开始分析构建 Nokia 7750 产品配置的知识。经用户确认（【用户确认】）：Classic CLI 与 MD-CLI 两种格式都支持（先 Classic、再 MD-CLI，映射到同一套 Schema）；按公开文档里较新的稳定版本做基线 Profile，其他版本以后用继承 Profile 只写差异；产品文档由 Claude 从 Nokia 公开文档下载（需要登录的部分告知用户），放在 DevelopDocs/设备产品文档/Nokia/；没有现网样本时用合成配置做往返测试，有现网样本时先脱敏；作为新里程碑 M7（0.7.0），文档与知识准备现在开始、与 M6 并行。按项目 skill `lmesh-docs-to-graph` 的流程做。

- 平台族：`nokia-sros-classic` 与 `nokia-sros-md`（两种格式各一个平台族，共用 Schema；名称以实现为准）。
- 主要差异：Classic CLI 为缩进 + `exit` 层级、`no` 取消；MD-CLI 为花括号层级或 `/configure …` 扁平路径，需要解析器增加分块方式；很多对象默认 shutdown；服务模型（Epipe、VPLS、VPRN、SAP、SDP、客户）需要在统一 Schema 中找到对应或新增节点。


## 接入 Nokia 7750 SR（REQ-037）（M7-1 分析结果）

2026-10-19 完成 M7-1（文档准备与分析、Classic 视图树与抽取规则起步）。文档清单见 `DevelopDocs/设备产品文档/Nokia/README.md`；决策 D-0167～D-0171。

**文档**：SR OS **25.10.R1** 公开文档（documentation.nokia.com/sr/25-10/，无需登录）：Classic CLI Command Reference（54 个 HTML 页＋PDF）、MD-CLI Command Reference（PDF＋13 棵配置树 HTML）、12 本配置指南 PDF（Basic System、Interface、Router、Unicast Routing、MPLS、Segment Routing、Services Overview、Layer 2 Services and EVPN、Layer 3 Services、QoS、System Management、MD-CLI User Guide）。需要登录、未获取：Security Best Practices and Hardening Guide、Pay-as-You-Grow Licensing、发布说明列表。选 25.10 而不是 26.3 / 26.7：最近一个 .10 年度版本、发布近一年（D-0167）。

**转换**：Classic 命令参考用专用脚本 `DevelopDocs/设备产品文档/Nokia/tools/nokia_classic_to_md.py` 转 Markdown（D-0169）。原因：Nokia 的关键字是 `span.cmdname` 不是 `<b>`（通用转换器不加粗，`no shutdown` 这类无参数语法行会被抽取器丢弃）、参数表是 `<dl>`、按字母分的大页无法按功能域选文件。转换后 10 513 条命令条目，按完整上下文（Full Context 前 3 个词，`configure service …` 取 4 个）分成 1 177 个文件，并推导 `View path` 小节（Full Context 去掉命令名）。配置指南 PDF 用 `convert.py` 的 `pdf_to_md` 转换，仅供检索（PDF 转换丢失缩进）。若以后要把这种转换并入 `convert.py`，需要支持 cmdname 加粗与 dl 参数表（改 src/）。

**Classic CLI 书写习惯**：缩进 4 空格；每个块以与开头同列的 `exit` 结束；整份以 `exit all` / `configure` 开头、`exit all` 结尾；文件头 `# TiMOS-B-25.10.R1 …` 五行与文件尾 `# Finished …`；段落标记 `#--------------------------------------------------` / `echo "… Configuration"` 总在第 0 列，且会出现在上下文中间（`router Base` 与其下的 `ospf` 之间）；`no` 取消；端口、业务、SAP、SDP、协议实例等缺省 shutdown，display-config 写出 `no shutdown`；名称带引号（可含空格）；新建对象带 `create`；同一上下文会多次出现（业务先建壳、后填 SAP / SDP 绑定；`router Base` 跨多个段落）。`admin display-config` 只输出非缺省值，`info detail` 含缺省值。

**MD-CLI 书写习惯**：花括号格式（`info`、`admin show configuration`：`router "Base" {` … `}`，层级以花括号为准，叶子列表 `[ a b ]`，`#` 注释，文件头同 Classic）；扁平格式（`info flat` 相对路径、`info full-context` / `admin show configuration full-context` 每行 `/configure …` 完整路径）；另有 JSON / XML 输出。`admin-state enable | disable` 代替 shutdown；地址拆为 `address` 与 `prefix-length`；`apply-groups` 模板需展开。

**解析器要求**（M7-2 / M7-4 改 `core/parser.py`、`core/kb/syntax.py`，由协调者安排）：

1. 按平台族缩进单位（views.yaml `indent: 4`，解析器目前未使用）折算层级，再判断分页痕迹。
2. 注释前缀 `#` 与版式行（`^echo "`、`^#-+$`）不改变视图栈（当前第 0 列分隔符会清空栈）。
3. `configure` 为结构行（进入根视图），`exit all` 清空。
4. Classic 的 `exit` 关闭与它同列的块，包括原文块（当前跳过原文块、退出最近的非原文视图，导致 OSPF 等范围外块里的 `exit` 提前退出 `router`）。
5. 卡没有 `enters_view` 而下一行缩进更深时，子行按原文块保留。
6. 分词支持引号字符串，图的键与引用去引号，渲染按原文。
7. 新参数类型 `port`（`1/1/1`、`1/1/c1/1`、`lag-1`、`esat-…`、`pxc-…`）与 `sap`（`端口:VLAN[.VLAN]`、`:*`）。
8. `sanitize.detect_vendor` 识别 `^# TiMOS-` 为 nokia；`exit all` / `echo "` → Classic，`configure {` / `/configure ` → MD-CLI；版本 `TiMOS-[A-Z]-(\d+\.\d+\.R\d+)`；Nokia 密文写法 `password "…" hash2`、`authentication-key "…" hash2`、`community "…"`。
9. MD-CLI 分块扩展：花括号格式按 `{` / `}` 进出（`block: braces`，忽略缩进）；扁平格式先预处理成块树——在 `syntax.py` 加前缀匹配 `match_prefix`，从根视图逐段消耗路径（容器 / 列表项卡进入视图，剩余部分整行匹配叶子卡），相邻行公共前缀合并成块，记录来源行号，渲染时按原格式输出。

**命令条目与抽取规则**：Classic 每条命令有 Syntax（关键字 / 参数 / `[ ]` / `{ | }` / `[{ }]`）、Context、Full Context（可多行）、Description、Default、Parameters（取值写作 `Values 1 to 255`）、Platforms。规则 `knowledge/extractors/nokia-sros-classic-md.yaml`：`views` 取 `View path`，`views_map` 用 `^…$` 精确匹配；`enters` 除进入范围内子视图外，把范围内视图里进入范围外子上下文的命令（router interface 下的 `ipv6`、`icmp`、`vrrp` 等）进入 `opaque` 视图、块内按原文保留（D-0170，名单由“该命令的完整上下文又是别的命令的 View path”自动得出）；`param_types` 中 `virtual-router-id` 放在 `router-id` 前；`syntax_rewrites` 把三种前缀写法合成一个参数。文档错误修正 2 条（port ethernet `mode` 缺 access、lag `lacp` 的 active / passive 被标成关键字）。MD-CLI 命令参考每个 YANG 元素一条（Synopsis、Context、Range / Options、Default、键 / 必选），嵌套到第 9 层而标题只到 h6，只能按 Context 路径建树；建议 M7-4 从 Nokia 公开 YANG 模型（github.com/nokia/7x50_YangModels）生成命令卡（新增抽取器）。

**平台族与视图树**：`knowledge/commands/nokia-sros-classic/views.yaml`（D-0168）：`separator` 为 50 个连字符的分隔行、`end: exit all`、`indent: 4`、`negative: no`、`root_view: configure`；视图：configure、opaque、port、port-ethernet、lag、router、router-if、static-route-entry / static-nh / static-indirect / static-bh，以及后续功能域先定好编号的 system / NTP / security / SNMP / SSH / user / TACACS+ / RADIUS / log / sync-if-timing / PTP、OSPF / IS-IS / BGP / policy-options、MPLS / RSVP / LDP、service / customer / sdp / epipe / vpls / vprn / ies 及其 SAP / SDP 绑定、qos / filter，共 90 余个。

**试抽取**（D-0171：用 `LMESH_KNOWLEDGE__DIR` / `LMESH_DATABASE__URL` 把运行时知识库与审核库指向 `tmp/nokia-m71/`，结果复制到 `knowledge/commands/nokia-sros-classic/`）：

| 功能域 | 命令条目 | 命令卡 | 按视图 | 跳过 |
|---|---|---|---|---|
| interface | — | 158 | router-if 59、port-ethernet 48、lag 29、port 17、configure 3、router 2 | — |
| static-route | — | 45 | static-nh 16、static-indirect 12、static-bh 9、static-route-entry 7、router 1 | — |
| 合计 | 759（52 个文件） | 203 | | 视图不在范围 581（全部为范围外子上下文：efm-oam、ipsec、port access、eth-cfm、ipv6、dot1x、TDM / OTU 等）；语法错误 0 |

重复抽取全部 unchanged；`lmesh kb validate` 0 错误（新增警告仅 203 条 card.unmapped）。用合成样本检验：按当前解析器视图跟踪全部错位（4 空格缩进被当作分页痕迹）；预处理模拟上面第 1～3 条改动后，`classic-pe-basic.cfg` 的端口、LAG、路由器接口、静态路由 92 行全部识别为命令、0 行未识别，剩下第 4 条（原文块里的 `exit`）的问题。合成样本草稿在 `DevelopDocs/设备产品文档/Nokia/samples-draft/`（`classic-pe-basic.cfg`、`classic-pe-services.cfg`），暂不进 `knowledge/samples/`。

**服务模型与统一 Schema 的对应**（不改已有 Schema 文件，M7-3 统一加）：

| Nokia 对象 | 现有 Schema | 需要新增 |
|---|---|---|
| customer | 无 | `service.customer`（新文件 `schema/service.yaml`；业务对象加 customer 引用；华为 / Cisco Profile 标 `supported: false`） |
| SDP | 语义 = PW 对端＋隧道选择（`tunnel_policy` / `l2vpn.pw_class.preferred_path`） | `service.sdp`（far_end、delivery、transport ldp / lsp / sr、keep_alive、path_mtu）；翻译时 far-end 展开到每条伪线的 peer |
| Epipe | `l2vpn.xconnect`；SAP → `xconnect.ac`；spoke-sdp `S:V` → `xconnect.pw`（peer 取 SDP far-end） | — |
| VPLS | `l2vpn.vsi`；mesh-sdp → `vsi.peer`；SAP → `interface.access`＋桥域（VPLS 隐式桥域，Profile `implicit`） | `l2vpn.vsi.peer.role`（mesh / spoke） |
| VPRN | `vrf.instance`；RD → `af.rd`；vrf-target → `af.rt`；vrf-import / export → `af.import/export_policy`；auto-bind-tunnel → `af.tunnel_policy`；maximum-routes → `af.prefix_limit` | — |
| VPRN / IES / 路由器接口 | `interface`（逻辑名）＋`interface.vrf`＋`interface.ipv4`＋`dot1q_termination`（取 SAP 的 VLAN） | `interface.bind_port`；render 增加三层接口形态 `logical / subinterface`（翻译成华为 / Cisco 子接口） |
| SAP | `interface.access`（父接口＋VLAN） | `interface.access.inner_vlan`、`qos_in/out`、`acl_in/out` |
| 端口 / LAG | `interface`（LAG 名规范为 `lag-1`）、`mtu`、`shutdown`、`lag`、`lag_mode` | `interface.port_mode`（access / network / hybrid）、`interface.encap_type`；LAG 下的成员 `port` 方向与华为 / Cisco 相反 |
| 静态路由 | `static.route`（black-hole → nexthop `NULL0`） | `static.route.metric`、`static.route.bfd`、`static.route.recursive`（indirect） |
| OSPF / IS-IS | `ospf.process`、`area`、`interface.ospf.*`；`isis.process`、`interface.isis.*` | `ospf.process.export_policy`（Nokia 用 export 策略代替 redistribute）；`isis.process.area_id`、`system_id`（翻译时拼 NET）；IS-IS 分级别 metric |
| BGP | `bgp.instance`（ASN 在 `router autonomous-system`）、`peer_group`、`peer`、`af.peer.*` | `bgp.peer_group.family` |
| 路由策略 | `rp.policy` / `node`（accept / reject）/ `prefix_list` / `community_list` | `rp.policy.default_action`、`rp.policy.node.match_protocol`、`rp.prefix_list.entry.match_type`（exact / longer / through） |
| MPLS / SR | `interface.mpls(.ldp)`、`mpls.ldp.remote_peer`、`sr.global.srgb_*`、`isis.process.ti_lfa`、`interface.prefix_sid.index` | RSVP-TE LSP / path（`mpls.te_lsp`、`mpls.te_path`，或先记原文） |
| QoS | 基本无法直接对应（分类近似 classifier＋service_class） | `qos.sap_ingress`、`qos.sap_egress`、`qos.network_policy`、`qos.network_queue`、`interface.qos_network` |
| ACL | `acl.instance`（ip-filter）、`rule`（forward / drop → permit / deny） | `acl.instance.default_action` |
| 管理面 | `mgmt.ntp / snmp / syslog / ssh / telnet / ftp / aaa / tacacs / radius / line` | `mgmt.system.name`（主机名，三家都未建模）、`mgmt.syslog.stream`（log-id 来源→目标）、`mgmt.aaa.user.profile` |
| BFD / VRRP / 时钟 | `interface.bfd.*`、`interface.vrrp.*`、`clock.sync / ptp` 基本可直接映射 | `interface.vrrp.owner` |

新对象类型还要登记 `knowledge/terms.yaml` 与 `knowledge/layers.yaml`（与 REQ-034 协调）。

**映射表达式需要的扩展**（M7-3）：`ctx:<参数>` 取父上下文行的参数（静态路由 next-hop 的键要带父行前缀、OSPF 接口的 area、SAP 所属业务）；目标对象键取自参数（LAG 下 `port 1/1/2` → `interface{1/1/2}.lag`）；拆分 SAP（`1/1/4:1001` → 接口＋VLAN）。渲染需要 `knowledge/render/nokia-sros-classic.yaml`：每块写 `exit`、按段落顺序与 `echo` 标题输出、业务两遍顺序、`create`、引号。

**后续**：M7-2 解析器改动（上面 1～8）＋补 system / mgmt、OSPF / IS-IS / BGP / 路由策略、MPLS / LDP / SR 的抽取；M7-3 Schema 新节点、映射规则、Profile `nokia-sros-classic-7750-25.10`、render 与往返、合成样本进门槛；M7-4 MD-CLI 分块扩展与 YANG 抽取器。

## 接入 Nokia 7750 SR（REQ-037）（M7-2 结果）

2026-10-19 完成 M7-2（Classic CLI 的解析器支持与命令卡补抽取）。决策 D-0184～D-0190。

**解析器开关**（D-0184）：平台族 `views.yaml` 新增 5 个键，缺省值等于华为 / Cisco 的现状，所以这两个平台族的解析循环一行未改（改动前后对 78 个华为 / Cisco 配置做逐行解析、图、往返文本的哈希比较，完全相同）。

| 键 | 缺省 | Nokia Classic | 作用 |
|---|---|---|---|
| `block` | `indent` | `exit` | `exit` 时 `parser.parse` 走 `_parse_exit_blocks`：缩进按 `indent`（4）折算层级；`exit` 关闭与它同列的块（原文块也一样，OSPF 等范围外块里的 `exit` 不会提前退出 `router`）；没有进入视图的命令下面若有更深缩进的子行，子行按原文保留；多余的 `exit` 原文保留 |
| `comment` | 空 | `["#"]` | 注释前缀：文件头、`# Finished …` 不改变视图栈 |
| `layout` | 空 | `['^echo "']` | 版式行正则：按注释处理；分隔行 `#-----…` 在 `block: exit` 下也不清空视图栈（段落标记出现在 `router Base` 与其下的 `ospf` 之间） |
| `begin` | 空 | `[configure]` | 结构行：进入根视图、清空视图栈（行类型记为 separator）；`end`（`exit all`）同样清空 |
| `quotes` | `false` | `true` | 分词识别引号字符串（名称可含空格）；参数取值去掉引号（图的键与引用不带引号），`Match.quoted` 记录原文带引号的参数，渲染时写回（D-0185）；`text` 参数整段是一个引号串时同样去引号 |

**参数类型**：`port`（`1/1/1`、`1/1/c1/1`、`1/1/1.1`、`lag-1`、`esat-1/1/1`、`esat-1/1/u1`、`pxc-1.a`、`aps-1`、`ccag-1.a`、`eth-tunnel-1`、`A/1`）与 `sap`（端口、`端口:VLAN`、`端口:外层.内层`、`:*`）。抽取规则按参数名 `port-id` → port、`sap-id` / `port-name` → sap（路由器接口的 `port` 写作 端口[:封装]）。

**识别与脱敏**：`detect_vendor` 遇到 `# TiMOS-` 文件头直接判为 nokia，没有文件头时看 `exit all`、`echo "`、50 个连字符的分隔行、`configure {`、`/configure `、`router "Base"` 等特征（至少 2 项且多于华为 / Cisco 的特征数）；`detect_version` 取 `TiMOS-B-25.10.R1` 中的 `25.10.R1`；新增 `detect_format`（classic / md）与 `family_of`（nokia → `nokia-sros-classic` / `nokia-sros-md`）。脱敏（D-0189）对 nokia 只用专用规则：`password` / `*-key` / `secret` 后的引号值或带 `hash` / `hash2` / `crypto` 标记的值、SNMP `community "…" r|rw|rwa|mgmt|vpls-mgmt`（策略里的 `community "名称"` 不替换）、`user "…"`、文件头 `by 用户名`、`configure > system > name` 为主机名；描述替换后保留引号。导入（D-0190）：`guess_profile` 对 nokia 按格式给 `nokia-sros-classic-7750-25.10` / `nokia-sros-md-7750-25.10`，`match_profile` 增加可选的 `family` 参数；设备名取 `system > name`；Profile 还不存在时导入只存原文（现有机制）。

**抽取**（隔离环境 `tmp/nokia-m72/`：`LMESH_KNOWLEDGE__DIR`、`LMESH_DATABASE__URL` 指过去，结果复制回 `knowledge/commands/nokia-sros-classic/`；没有运行 `kb map`）。规则新增功能域与视图（D-0187）：SR 单独成域（`mpls-labels` 的 `sr-labels`、OSPF / IS-IS 下的 `segment-routing`），路由器级的 `autonomous-system` / `router-id` / `confederation` 放 bgp 域；新增视图 `security-password`、`isis-if-level`、`policy-default`、`mpls-lsp-primary` / `mpls-lsp-secondary`、`rsvp-if`、`ldp-if-ipv4`、`ldp-targeted-peer`、`mpls-labels`、`ospf-sr`、`isis-sr`（共 99 个视图）；范围外子上下文的 opaque 名单按“命令的完整上下文又是别的命令的视图路径”重新生成。

| 功能域 | 命令卡 | 按视图 | 其中进入范围外子上下文（opaque） |
|---|---|---|---|
| mgmt | 223 | system 47、system-security 31、log 17、log-id 15、security-ssh 14、security-tacplus 13、security-radius 12、security-password 12、system-ntp 11、login-control 9、security-user 9、log-syslog 9、security-snmp 7、system-snmp 7、system-time 5、security-maf 3、configure 2 | 86 |
| ospf | 89 | ospf 42、ospf-if 33、ospf-area 12、router 2 | 13 |
| isis | 144 | isis 78、isis-if 31、isis-level 20、isis-if-level 14、router 1 | 13 |
| bgp | 245 | bgp 92、bgp-group 75、bgp-neighbor 74、router 4 | 31 |
| routing-policy | 167 | policy-from 48、policy-action 47、policy-default 46、policy-options 12、policy-entry 8、policy-statement 4、router 1、prefix-list 1 | 9 |
| mpls | 269 | mpls 60、mpls-lsp 56、ldp 40、rsvp 23、rsvp-if 16、mpls-lsp-secondary 15、mpls-lsp-primary 13、ldp-targeted 11、ldp-targeted-peer 8、ldp-if-ipv4 7、mpls-if 6、ldp-if 5、mpls-path 3、router 3、ldp-if-params 3 | 57 |
| sr | 41 | ospf-sr 19、isis-sr 17、mpls-labels 4、router 1 | 13 |
| interface（重抽） | 158 | 不变；`port-id` 改为 port、`port-name` 改为 sap，lag 的成员端口列表改成重复组 | 46 |
| static-route（重抽） | 45 | 不变 | 7 |
| 合计 | 1 381（133 个文件、3 300 条命令条目） | | 275 |

跳过：视图不在范围 2 226 条（全部为范围外子上下文，例如 system 的 management-interface / pki / grpc、log 的 accounting-policy、BGP 的 next-hop-resolution / add-paths、MPLS 的 forwarding-policies / lsp-template、OSPF / IS-IS 的 flexible-algorithms / loopfree-alternates；sr 域里同一文件的非 SR 视图按设计丢弃），语法错误 0（10 条文档括号错误用 `syntax_rewrites` 修正），重复 1、排除 1。重复抽取全部 unchanged；`lmesh kb validate` 0 错误（新增警告只有 card.unmapped）。

文档错误修正（D-0188）：`syntax_rewrites` 处理转换痕迹——`[no]` 前缀、拆开的关键字（`s ecurity-level`、`p refix -match`、`n o view`）、语法里带了完整上下文、斜体的 `<|>`、括号不配对（attempts、lsp-refresh-interval、cluster、export / import、route-target-list）、“命令 <值> | <参数名>” 少花括号、参数名带空格被拆开（`default-preference ebgp <ebgp preference>`、`default-metric <ipv4 metric>`）、`hold-time <seconds> [ min <seconds> ]` 同名参数、列表 `<p> [ <p> ]` / `[ <p> ...(up to 5 max) ]` 改成重复组（每个取值单独记录，渲染不会把同名参数重复成同一个值）、`<ip-prefix> / <mask>` 合成一个参数；`area-id`、`system-id`、`length1-length2` 按 word（取值说明里的 “Values 0.0.0.0 to …” 会被误判为整数）。修正文件补 5 条：新增 configure 下的 `system`（命令参考没有单列）、`ospf [ <instance> [ <router-id> ] ]`（实例号可省略、可为 0）、OSPFv2 接口的 `shutdown`（原文只列了 ospf3）、LSP 的 `cspf [ use-te-metric ]`（25.10 命令参考漏收）、`begin [ exclusive ]`。

**样本**（D-0186）：`knowledge/samples/nokia-sros-classic-synthetic/`（自带 `manifest.yaml`，Profile 在 M7-3 建立前不进总清单；`tests/roundtrip/test_nokia_samples.py` 用临时内存 Profile 解析、建图、往返）。

| 样本 | 行数 | command | raw | unknown | 往返 |
|---|---|---|---|---|---|
| classic-pe-basic.cfg（M7-1 草稿） | 214 | 158 | 11（card / mda 块、sntp 等范围外子上下文） | 0 | 逐字一致 |
| classic-pe-services.cfg（M7-1 草稿） | 149 | 18 | 101（filter、qos、service 范围外，M7-3 补） | 0 | 逐字一致 |
| classic-pe-routing-mgmt.cfg（M7-2 新写） | 294 | 239 | 4 | 0 | 逐字一致 |

三份都是合成配置（地址取自文档保留网段与私网，口令、团体字已是 LMESH 占位符），不含真实设备信息。往返按原文重放即逐字一致：命令行全部按卡的语法（含引号）重放，没有一行需要原文兜底（fmt 为 0）。

**留给 M7-3 / M7-4**：
- Schema / 映射 / Profile：1 381 张卡全部 card.unmapped；`nokia-sros-classic-7750-25.10` 建好后把合成样本移进总清单并删除自己的清单与 `test_samples.py`、`roundtrip.manifest()` 里的目录排除。
- 规范渲染（翻译、变更脚本）需要 `knowledge/render/nokia-sros-classic.yaml`：每块写 `exit`、`echo` 段落、两遍业务顺序、`create`、引号（`Match.quoted` 已记录原文引号；新值含空格时要加引号）。往返本身不需要这些。
- `core/canon.py`、`change.py`、`cleanup.py`、`script_check.py`、`config_analysis.py` 里的 `syn.match` / `tokenize_line` 调用还没有传 `quotes`，按缩进差 1 拼块的代码（canon、change）也不认识 `block: exit`；这些功能接入 Nokia 时要改。映射表达式里的 `tokens = ln.text.split()`（`kw:`、`tail:`）对带空格的引号名称会拆开。
- 待真机核实的写法：policy-statement 的 `action accept` 块里能否写 `local-preference` 等动作（命令参考把这些动作挂在 `entry` / `default-action` 下）、用户口令是否带 `hash2`（25.x 文档写作 `password [ <password> ]`）。
- 仍有同名参数的卡（`prefix-limit … hold-excess`、`summary-address … tag`、`prefix-list` 的 `prefix … to <前缀>`、`class-type-bw`、`router-if qos … redirect-group`、`renumber from … to` 等 9 张）：取值会互相覆盖，往返靠原文兜底；用到时补 `syntax_rewrites`。
- M7-4：MD-CLI 分块（`block: braces`、扁平路径的前缀匹配）；`detect_format` 已能区分 md。

## 接入 Nokia 7750 SR（REQ-037）（M7-3 结果）

2026-10-19 完成 M7-3（Classic CLI 的 Schema 归并与映射、Profile、规范渲染，以及建图、往返、对比、检查、翻译、变更、清理）。决策 D-0192～D-0194（子任务：业务 / 过滤器 / VRRP / QoS 抽取与同名参数修正）、D-0207～D-0213。

**抽取补充**（子任务，隔离环境 `tmp/nokia-m73/`）：新功能域 `service`（846 张：客户、SDP、Epipe、VPLS、VPRN（含 25.x 的 bgp-ipvpn mpls 写法）、IES 及其 SAP / spoke-sdp / mesh-sdp、SAP 的 ingress / egress）、`acl`（136 张：ip-filter、entry、match、action 两种写法）、`vrrp`（21 张）、`qos`（5 张：sap-ingress / sap-egress 入口与描述）；新增视图 sdp-keep-alive、各业务 SAP 的 *-sap-ingress / *-sap-egress、vprn-abt / vprn-abt-rf、vprn-bgp-ipvpn / vprn-ipvpn-mpls / vprn-ipvpn-abt / vprn-ipvpn-abt-rf；router interface 下的 vrrp 改为进入 router-if-vrrp。M7-2 留下的 9 张同名参数卡用抽取规则的 `syntax_rewrites` 改名（hold-excess、qos 的 redirect-group、summary-address 的 tag、home-directory、snmp-trap-group、class-type-bw、prefix … to、renumber），不再需要原文兜底。修正文件补 next-hop 的取消写法（修正按抽取批次的编号匹配：service 与 static-route 两个功能域要分开抽取）。平台族共 2 389 张卡，映射 289 张（其中容器卡 37 张）。

**Schema 新增节点**（统一 Schema 仍以华为为基准，已有节点语义不变；“有对应写法”表示华为 / Cisco 有命令但现有映射未归并，为保持现有基准暂不映射）：

| 功能域 | 新节点 | 华为 / Cisco |
|---|---|---|
| interface | `interface.bind_port`（三层逻辑接口绑定的端口，类型 interface）、`port_mode`（access / network / hybrid）、`encap_type`、`loopback` | 平台特有 |
| interface | `interface.access.inner_vlan`、`acl_in` / `acl_out`、`vsi`、`qos_in` / `qos_out`（SAP） | 内层 VLAN、子接口过滤、l2 binding vsi 有对应写法；QoS 策略平台特有 |
| static-route | `static.route.metric`、`recursive`（indirect）、`shutdown` | 平台特有；`bfd` 有对应写法 |
| ospf / isis | `ospf.process.export_policy`、`te`、`shutdown`；`interface.ospf.shutdown`；`isis.process.area_id`、`system_id`、`export_policy`、`te`、`shutdown`；`interface.isis.level`（按级别的 metric）、`interface.isis.shutdown` | export 用策略代替引入、管理状态为平台特有；area-id / system-id 在华为 / Cisco 写在 NET 里（翻译时拼 / 拆）；TE、按级别 metric 有对应写法 |
| bgp | `bgp.instance.family`、`shutdown`；`bgp.peer_group.family`、`description`、`import_policy` / `export_policy`；`bgp.peer.import_policy` / `export_policy` | family 与组 / 对等体级策略平台特有（华为 / Cisco 按地址族写）；组描述有对应写法 |
| routing-policy | `rp.policy.default_action`、`rp.policy.node.match_protocol`、`rp.prefix_list.entry.match_type` | default-action、exact / longer 平台特有；from protocol 有对应写法 |
| mpls | `mpls.global.shutdown`、`mpls.ldp.shutdown`、`interface.mpls.shutdown` | 平台特有 |
| mgmt | `mgmt.system`（`name`、`router_id`）、`mgmt.syslog.host.target_id` / `level`、`mgmt.ntp.shutdown` | sysname / hostname、router id、loghost level 有对应写法；其余平台特有 |
| service（新文件 `schema/service.yaml`） | `service.customer`、`service.sdp`（far_end、delivery、ldp、lsp、path_mtu、keep_alive、shutdown）、`service.ies`、`qos.sap_ingress` / `sap_egress`；`l2vpn.xconnect.service_id` / `customer` / `description` / `mtu` / `shutdown`、`l2vpn.xconnect.pw.sdp`、`l2vpn.vsi.service_id` / `customer` / `shutdown`、`l2vpn.vsi.peer.role`（mesh / spoke）/ `sdp`、`vrf.instance.service_id` / `customer` / `shutdown`、`acl.instance.default_action`、`interface.vrrp.owner`、`interface.ies` | 平台特有 |

新对象都登记了 `terms.yaml`（华为 / Cisco 两种写法）与 `layers.yaml`（`service` 功能域归 2.5 层）；新的引用依赖（策略、客户、SDP、VSI、QoS 策略、过滤器）写在 `schema/service.yaml` 的 deps，配置检查与清理能识别。`terms.yaml` 增加可选的第三种风格 `nokia`（对象另写 `nokia: {name, label}`，没写时按华为风格；`core/terms.py` 的 `REQUIRED_STYLES` 只要求华为与 Cisco），界面的风格切换在 M7-5 做（D-0213）。

**映射规则** `knowledge/mappings/nokia-sros-classic.yaml`（238 条）与表达式扩展（`core/kb/mapping.py`，D-0207；华为 / Cisco 的映射文件与 `lmesh kb map` 结果逐字不变）：

| 写法 | 作用（Nokia 用例） |
|---|---|
| `ctx:<参数>` | 父上下文行的参数（由近到远第一个有该参数的祖先行）：static-route-entry 的前缀、OSPF area、lag 编号、group 名称、syslog 编号；规范渲染时由块头行或容器行给出 |
| 目标 `a{k=$参数}.b` | 对象键取自参数：lag 下 `port 1/1/2` 写到成员口的 `interface.lag`；OSPF / IS-IS / MPLS / LDP 块里的 `interface "x"` 写到该接口的 OSPF / IS-IS / MPLS 参数；SAP 写到端口上的接入点 |
| `sap:port\|vlan\|inner\|tag\|encap:` | 拆 SAP（`1/1/4:3001.10`）；spoke-sdp 的 `12:1001` 也按它拆成 SDP 与 VC ID |
| `pfx:addr\|len\|wild:`、`pre:<词>:`、`via:<类型>:<属性>:`、`!flag` | 拆 地址/长度（及反掩码）；去掉 `target:` 前缀；按键取别的对象的属性（伪线对端 = SDP 的 far-end）；no shutdown → 启用 |
| `"@container"`、`"@share"`、`"@frame"` | 容器卡（system、router Base、static-route-entry、bgp、policy-options、service、filter、qos、ingress / egress…）不产生节点也不算未映射；本行对象对后续兄弟行可见（autonomous-system 是 bgp 块的 BGP 实例，syslog 下 address 建立的服务器；同一容器另起的块也可见）；编辑会话的 begin / commit |

`lmesh kb map` 增加 `--family`（只处理这些平台族的卡与 Profile）；全量运行同样不改华为 / Cisco 的文件（已核对）。映射表达式里的分词按平台族的 `quotes`（引号名称不再按空格拆开）。

**Profile** `knowledge/profiles/nokia-sros-classic-7750-25.10.yaml`：252 个条目，其中人工条目 40 个（命令参考的缺省值：静态路由 preference 5 / metric 1、BGP keepalive 30 / hold 90 / family ipv4、OSPF hello 10 / dead 40 / priority 1、IS-IS level-1/2、窄度量、metric 10、syslog facility local7 / level info 等）。两个新机制（D-0209）：`when.else`（条件不满足时的缺省值：端口与 LAG 缺省 shutdown，路由器接口缺省 no shutdown）；`assume`（源平台族没有该节点时按此理解，用于协议实例、接口协议参数、NTP、静态路由、业务的管理状态：翻译成 Nokia 时显式写 `no shutdown` 并告警 default_differs；Nokia 的 `no shutdown` 翻译成华为 / Cisco 时省略并说明）。implicit 为空（VPLS 的 SAP 直接绑定 VSI）。importer 的缺省 Profile 名称（M7-2）已能用上。

**规范渲染**（`knowledge/render/nokia-sros-classic.yaml`、`core/canon.py`，D-0211）：`exit_all`（每块 exit）、`root_depth: 1`、开头 `exit all` / `configure`、结尾 `exit all`；顶层块按开头一路进入的视图归到 echo 段落（System、Log、Filter、QoS、Port、LAG、Router、Static Route、Service、OSPF、ISIS、MPLS、RSVP、LDP、Policy、BGP…）；`containers`（`router Base`、IS-IS `level 2`）与按容器卡语法生成的容器行（`static-route-entry <前缀>` 的前缀由 `ctx:` 要求给出）；同一段落里相邻的同一容器合并；名称、描述加引号（`quote_params`），新建对象带 `create`；`wrap`（policy-options 的 begin … commit）；固定键取自参数的卡与用 `ctx:` 写对象的卡在所属块里写别的对象上的节点（OSPF 区域块写接口的 OSPF 参数，VPRN 块写接口与静态路由），只能写在外层块里的对象推迟到那里写；块头在多张卡间选择时先看 render 的 `prefer`（lag-1 用 `lag 1`），再看块内能写出的节点。业务按依赖排序一遍写完，没有做 display-config 的两遍顺序（不影响解析与执行）。`change.py` / `cleanup.py` / `config_analysis.py` 调用 `syntax.match` / `tokenize_line` 按平台族传 quotes；`script_check.py` 认 Nokia 的 # 注释、echo、exit all / configure 与 begin / commit。

**变更与清理**：`knowledge/change/nokia-sros-classic.yaml`（开头 / 结尾、exit、注释 #、`before_delete`：删除业务、SDP、SAP、接口前先 shutdown）；变更脚本的块按 render 的 wrap 包 begin … commit；清理脚本按平台族的开头结尾、缩进与 wrap 输出（华为 / Cisco 不变）。

**样本与回归**：三份 Nokia 合成样本并入 `knowledge/samples/manifest.yaml`（gate: true），删除它们自己的清单与 `test_samples.py`、`roundtrip.manifest()` 里的目录排除；往返逐字一致、未识别 0、没有 fmt 兜底，建图无悬空引用，关键对象（端口、LAG、接口、路由、协议、策略、业务、SAP、SDP 绑定、过滤器、VRRP）都映射到 Schema（RSVP-TE 的 rsvp / lsp / path 还没有 Schema 对象，按未映射命令保留）；规范渲染等价（含默认值的完整配置同样等价）。变更回归加 4 个 Nokia 用例（修改、删除邻居、新增 VPRN、前缀列表改名 + 黑洞路由 + 端口关闭），下发与回滚都通过模拟执行。翻译回归加 5 个用例（未解释差异都是 0，写出比例写进清单下限）：

| 用例 | 写出 / 要写出 | 下限 | 主要不支持项 |
|---|---|---|---|
| nokia-basic-to-atn | 81 / 102 | 0.79 | 端口模式与封装、indirect / bfd-enable、syslog 编号与级别 |
| nokia-routing-mgmt-to-atn | 91 / 122 | 0.74 | RSVP-TE、组级 export、Nokia 特有节点 |
| nokia-services-to-atn | 79 / 155 | 0.50 | 客户、SDP、Epipe 伪线、IES、SAP 的 QoS 策略 |
| asr920-to-nokia | 90 / 137 | 0.65 | BGP 地址族、业务实例（EFP）、BDI 的桥域、prefix-list ge |
| asr920-igp-mgmt-to-nokia | 64 / 132 | 0.48 | IS-IS 区域标签（CORE 不是实例编号）、AAA 方法列表、登录线路、TACACS+、SSH 参数 |

翻译的换结构（`core/translate.py`）：三层接口（render 的 `l3_form`：Nokia logical ↔ 其他 physical；Nokia 的逻辑接口并到 port 绑定的端口或子接口，反向时三层属性移到逻辑接口 `if-<源接口名>`）、OSPF network 宣告换成接口所在区域、IS-IS area-id + system-id（不写时按 Router ID 推出）↔ NET、协议基本实例 0 ↔ 进程 1（`instance_keys`）；业务编号、客户、syslog 编号按 `infer`（`seq` 顺序编号、`write` 即使语法可选也写出）补出并告警 inferred_value。华为 / Cisco 的往返、规范等价、对比基准、检查、翻译、变更、迁移回归全部不变。

**留给 M7-4 / M7-5**：
- M7-4（MD-CLI）：`block: braces` 与扁平路径；映射规则按 MD-CLI 的视图另写（表达式与本节相同），`admin-state enable / disable` 对应本节的 `*.shutdown`（`!flag` 写法），`address` 与 `prefix-length` 分开（不需要 `pfx:`）；render 另写一份（花括号、无 exit）。
- M7-5 显示风格：界面的风格切换加 Nokia（`terms.yaml` 已有 nokia 写法与回退规则，前端 `STYLES` 常量要加）；补齐更多对象的 nokia 写法。
- M7-5 检查规则与基线：现有规则多按华为 / Cisco 的节点写，要检查 Nokia 特有节点（端口缺省关闭、SDP keep-alive、业务 shutdown、SAP 的过滤器 / QoS）；安全基线（telnet-server、ftp-server、SNMP 团体字、口令策略）按 Nokia 的节点补条目与修复命令（`rules` 的 remedy 现在允许 nokia 风格）。
- 待补：RSVP-TE 的 LSP / path（Schema 新对象）、VPRN 下的 BGP / OSPF（现在进 opaque）、SAP 的 shutdown 与 description 之外的属性、vrf-target 的 `export X import Y` 只记了 export、L3 SAP 的内层 VLAN（graph 只记外层）、`router management` 等非 Base 路由器实例（现在当 Base）、IS-IS 级别 metric 与华为 / Cisco 的对应、BGP 地址族与 Nokia family 的互译、display-config 的两遍业务顺序；待真机核实：删除前 shutdown 的范围、policy-statement action 块里的动作。
- 运行 `lmesh kb map` 会在 `knowledge/.git`（知识库自己的版本库）提交一次，属正常行为。

## 接入 Nokia 7750 SR（REQ-037）（M7-4 结果）

2026-10-19 完成 M7-4（MD-CLI 格式：命令卡、解析、映射、Profile、规范渲染、往返，以及翻译与变更回归）。决策 D-0223～D-0229。

**命令卡**（D-0223、D-0224）：来源是已下载的 MD-CLI Command Reference 25.10.R1 的 13 棵配置树 HTML，没有另下 YANG 模型。新转换脚本 `DevelopDocs/设备产品文档/Nokia/tools/nokia_md_to_md.py` 按范围文件 `tools/md-scope.txt`（去掉键的上下文路径，与 Classic 的功能域对应，共 175 个）把每个 YANG 元素转成一条命令：标题是去掉 configure 与键的完整路径（卡编号由它生成，同名元素不撞号），叶子 `name <name>`、列表 `name <键1> 键2名 <键2>`（与 info 输出一致，第一个键不写键名）、加密叶子带 `[ hash | hash2 | custom ]`，另加 `delete name [<键>]` 作取消形式；参数表的取值列写 YANG 类型、选项、范围、叶子列表上限、是否字符串。抽取规则 `knowledge/extractors/nokia-sros-md-md.yaml` 的 `views_map` / `enters` 与 `views.yaml` 的视图都由脚本生成（视图编号 = 路径用 . 连接，例如 `router.interface.ipv4.primary`；范围内上下文里的范围外容器进入 `opaque`，块内原文保留）。隔离环境 `tmp/nokia-m74/` 抽取后复制到 `knowledge/commands/nokia-sros-md/`：

| 功能域 | 命令卡 | 功能域 | 命令卡 |
|---|---|---|---|
| service | 798 | isis | 145 |
| bgp | 343 | acl | 101 |
| mgmt | 298 | ospf | 88 |
| mpls | 245 | qos | 66 |
| interface | 175 | static-route | 59 |
| routing-policy | 170 | sr | 50 |
| vrrp | 24 | 合计 | 2 562（其中进入 opaque 的 863） |

重复抽取全部 unchanged；修正文件 `nokia-sros-md-md.patches.yaml` 4 条（configure port 的键排除 lag-、configure lag 的键限定 lag-…、ntp server 的 router-instance 与 prefix-list prefix 的 type 规范渲染缺省值）；`lmesh kb validate` 0 错误（警告只有 card.unmapped）。

**解析器**（D-0225）：`views.yaml` 新增 `block: braces`（华为 / Cisco / Classic 的解析循环未改）。`parser._parse_brace_blocks` 按花括号进出块，行尾的 ` {` / ` { }` 记在 `Line.tail`；`configure {` 是结构行（其下的行仍是顶层行）；范围外的块整块原文保留。扁平格式（info flat 相对路径、info full-context 与 admin show configuration full-context 的 `/configure …`）在当前视图整行匹配不上时，按命令卡逐段消耗路径（进入视图的卡，最长匹配，多个键的列表也能消耗），每段补一行 `virtual` 的块头（编号接在最后一行之后，相邻行的公共前缀共用同一行），原文行记 `prefix`；往返时跳过 virtual 行，原文行按 prefix + 命令 + tail 重放，所以扁平格式与花括号格式建出的图相同、往返逐字一致。新参数类型 `leaflist`（叶子列表 `[ "a" "b" ]` 整段一个取值）与 `string`；参数可写 `pattern`（附加正则）与 `fill`（规范渲染缺省值）。`detect_format`：没有 exit 而有花括号块或 info flat 路径的识别为 md。脱敏补 MD-CLI 写法：`security snmp` 块里的 `community "…" {`（按所在块区分策略里的 community 名称）、扁平格式的团体字、用户、主机名。

**映射**（D-0226、D-0228）：`knowledge/mappings/nokia-sros-md.yaml` 261 条规则，写入 367 张卡（其中容器 103 张），与 Classic 映射到同一套 Schema。admin-state 写成 `kw:disable=true|enable=false`（shutdown）或 `kw:enable=true|disable=false`；地址与前缀长度分两行（address 建立接口地址对象，`@share` 给 prefix-length）。新表达式与指令（`core/kb/mapping.py`）：

| 写法 | 作用（MD-CLI 用例） |
|---|---|
| `list:<表达式>` | 叶子列表拆成列表（export-policy、backup、area-address、prefix-list） |
| `by:<类型>:<属性>:<表达式>` | `via:` 的反向：属性等于取值的对象的键，没有时取值本身（业务与 SAP 按名称引用客户、QoS 策略、过滤器，图里仍以编号为键，同 Classic） |
| `scale:<倍数>:<表达式>` | 单位换算（VRRP message-interval 的 0.1 秒 → 秒） |
| `strip:<文字>:<表达式>` | 去前缀（LAG 名 lag-1 → Classic 的编号 1） |
| `"@first"` | 这一行先于兄弟行建图（MD-CLI 按字母序输出，customer-id / filter-id / policy-id 写在描述与子块之后） |

`via:` / `by:` 引用的对象在后面才出现时（epipe 的 spoke-sdp 在 sdp 之前），建图记下后用第一遍的图再建一次。Schema 新增 `acl.instance.filter_name`（过滤器名称，alias）。

**Profile**（D-0227）：`knowledge/profiles/nokia-sros-md-7750-25.10.yaml` 用新键 `defaults_from: nokia-sros-classic-7750-25.10` 复用 Classic 的人工条目（缺省值、when / else、assume），本 Profile 的 247 个条目由 `kb map --family nokia-sros-md` 汇总（只有支持情况与命令卡），缺省值只维护一份。importer 的缺省 Profile 名称（M7-2）与按格式选平台族（`match_profile` 的 family）照常起作用。

**规范渲染与变更**（D-0229）：`knowledge/render/nokia-sros-md.yaml`（`open: " {"`、`exit_all: "}"`、`configure {` … `}`、`container_depth: 5`、容器模板 `route {ip-prefix} route-type unicast`、`infer` 新选项 `key: true` 用对象自己的键作名称）与 `knowledge/change/nokia-sros-md.yaml`（`edit-config private` … `commit` / `quit-config`，块写成 `name { … }`，删除用 `delete <元素>`，删除前先 `admin-state disable`）。`core/canon.py`：进入视图的行加行尾、字符串参数加引号、叶子列表写成 `[ … ]`，顶层块按元素名排序并合并同一容器（含不相邻的），原文写回只在原来的视图里写，lag 下的成员口块只写原来在块里的原文；同一行顺带建立的不在链上的对象（Epipe 的 sap 同时建立接入电路）可以写出（这一改动对 Classic 目标同样生效，现有回归结果不变）。`core/change.py`：脚本块头加 ` {`、模拟执行按花括号写出、取消命令的取值按原文写回引号；`core/cleanup.py`：清理脚本用同样的编辑会话与花括号，容器里由编号行建立的对象删除整个容器（`delete customer "ACME"`），验证时去掉被删块的 `}` 与扁平格式的路径行；`core/script_check.py`：认 MD-CLI 的块头花括号、`}` 与 `edit-config` / `quit-config`。`core/translate.py`：两边协议实例编号习惯相同（Classic ↔ MD-CLI）时不改编号。

**样本与回归**：`knowledge/samples/nokia-sros-md-synthetic/` 四份合成样本登记进总清单（gate: true）：`md-pe-basic` / `md-pe-services` / `md-pe-routing-mgmt` 与 Classic 三份一一对应，`md-pe-basic-flat` 是 basic 的 info flat 格式；过了 `lmesh sanitize`（basic 级别只替换文档保留网段的地址，样本保留原地址以便对照）。四份往返逐字一致、未识别 0、没有 fmt 兜底、无悬空引用，规范渲染等价（含默认值）。Classic 版与 MD-CLI 版建出的图直接比较（`tests/unit/test_nokia_md.py`），basic 无差异，允许的差异只有：

| 差异 | 原因 |
|---|---|
| `acl.instance.filter_name`（MD 有） | Classic 的映射不记 ip-filter 的 name（M7-3 结果不能变） |
| 过滤器条目的 `dst-port range 161 162` | MD-CLI 拆成 range { start end } 两个叶子，暂不归并 |
| `bgp.instance.family` | MD-CLI 的 family 是逐个地址族的布尔叶子，暂不归并（MD 取缺省值 ipv4） |
| VPRN 3002 的 import RT | Classic 的 `vrf-target export X import Y` 只记了 export（M7-3 已知限制） |
| 本地用户的 `service_type` | MD-CLI 的 access 是逐个布尔叶子，暂不归并 |

翻译回归加 6 个用例（未解释差异都是 0）：

| 用例 | 写出 / 要写出 | 下限 |
|---|---|---|
| nokia-md-services-to-classic | 152 / 153 | 0.99 |
| nokia-md-flat-to-classic | 103 / 103 | 0.99 |
| nokia-classic-routing-mgmt-to-md | 117 / 122 | 0.95 |
| nokia-md-routing-mgmt-to-atn | 91 / 120 | 0.75 |
| nokia-md-services-to-atn | 82 / 157 | 0.52 |
| asr920-to-nokia-md | 88 / 137 | 0.64 |

变更回归加 3 个用例（`md-base.cfg` → 修改 / 删除邻居 / 新增 VPRN，下发与回滚都通过模拟执行）。

**华为 / Cisco / Classic 结果不变**：改动前后对 22 份样本（解析结果、图 JSON、往返文本、规范渲染与含默认值的规范渲染）、20 个翻译用例、20 个变更用例共 150 项输出做比较，逐字节相同（`tmp/os/m74/baseline.py`）。

**测试**：单元 `tests/unit/test_nokia_md.py`（花括号 / 扁平 / full-context 解析与往返、叶子列表、格式识别、新表达式、@first 与第二遍建图、Classic 与 MD 的图等价、Profile 复用缺省值、规范渲染、变更脚本、清理与脚本检查、脱敏）；`tests/roundtrip/test_nokia_samples.py` 覆盖两个样本目录；CLI 用例 `nokia-md-render-canonical`、`nokia-md-translate-to-classic`；Profile 计数断言 4 → 5（`tests/api/test_workbench.py`、`cli_cases.toml` 的 kb-validate）。

**留给 M7-5**：
- 显示风格与检查规则同 M7-3 的说明（MD-CLI 的节点与 Classic 相同，规则不用分格式）。
- 暂不归并的写法：BGP family 与用户 access 的布尔叶子、过滤器端口范围（range start / end）、VPRN 下的 BGP / OSPF（同 Classic 进 opaque）、RSVP-TE 的 LSP / path。
- 规范渲染里同一对象的属性行先后按图中的顺序，不完全是 info 的字母序（不影响解析与执行）。

**待真机核实**：info / info flat / full-context 的细节（空列表项写 `{ }` 还是换行的 `{` `}`、叶子列表单个取值是否总带括号、字符串取值什么时候加引号）、`edit-config private` 脚本在 `[pr:/configure]` 下按相对路径粘贴的写法、删除业务前是否必须 `admin-state disable`、VRRP message-interval 的单位（文档缺省值 10 推断为 0.1 秒）。

## 接入 Nokia 7750 SR（REQ-037）（M7-5 结果）

2026-10-19 完成 M7-5（第三种显示风格 Nokia、Nokia 的检查规则与安全基线、跨设备一致性适配、补齐写法）。决策 D-0237～D-0243。

**显示风格 Nokia**（D-0237）：`terms.yaml` 为全部 119 类对象登记 nokia 写法（以 Classic CLI 为准；MD-CLI 元素名相同、层级用花括号；Nokia 没有对应对象的写成全角括号说明，例如 HQoS 模板、1588 ACR），97 个属性中 82 个补了 nokia 关键字，另为 Nokia 特有属性（SAP 的 ingress qos / filter、spoke-sdp、far-end、keep-alive、family 等）单独登记；`core/terms.py` 的 `REQUIRED_STYLES` 加入 nokia（`terms.check` 要求三种都登记），属性没有 nokia 关键字时按华为写法显示。label 候选的条件支持 `字段~正则`（接口：端口写 `port 1/1/4`、LAG 写 `lag-1`、路由器接口写 `interface "to-CE1"`）。新增 `contexts` 段：按视图层级显示时 Nokia 的顶层对象按配置上下文分组（port、lag、router Base、router Base › policy-options、service、service › vprn X、filter、qos、log、system），`Terms.context()` 与前端 `terms.ts` 逐条一致（`scripts/terms_golden.py` 加了 4 份 Nokia 样本与上下文，golden 测试覆盖三种风格）。后端各接口的 `style` 参数、配置项 `ui.term_style`（向导与 `config.example.toml` 同步）、CLI 的 `--style` 都接受 nokia；特性查询的关键词也匹配 Nokia 写法。

**检查规则**（D-0238，`knowledge/rules/service.yaml`，17 条，Classic 与 MD-CLI 共用节点）：

| 规则 | 级别 | 判断 |
|---|---|---|
| `port.shutdown_with_sap` | error | 接入点（SAP）所在的端口 / LAG 关闭（按有效值：Nokia 端口缺省关闭，只因 SAP 出现的端口也按关闭） |
| `port.shutdown_bound` | error | 路由器接口绑定的端口 / LAG 关闭（路径 `bind_port=>shutdown`） |
| `port.lag_member_shutdown` | warning | LAG 成员口关闭（通用语义，华为 / Cisco 样本没有命中） |
| `sdp.far_end_missing`、`sdp.keep_alive_disabled` | error / warning | SDP 没有 far-end；启用的 SDP 没有开保活（缺省关闭） |
| `service.pw_sdp_shutdown`、`service.vpls_sdp_shutdown` | error | Epipe 伪线、VPLS mesh / spoke-sdp 使用的 SDP 关闭（SDP 缺省关闭） |
| `service.{epipe,vpls,vprn,ies}_shutdown` | warning | 业务关闭（缺省关闭，没写 no shutdown / admin-state enable 也算） |
| `service.sap_shutdown` | warning | SAP 被关闭（新节点 `interface.access.shutdown`，SAP 缺省启用） |
| `service.{epipe,vpls,vprn,ies}_customer_missing` | error | 业务没有客户 |
| `vprn.no_rd_rt` | warning | VPRN 既没有 RD 也没有 vrf-target（有一缺一由 common.yaml 原有两条报出） |

SAP 引用的过滤器 / QoS 策略、业务引用的客户不存在由内置 `ref.dangling` 报出（Schema 的 reference 依赖），不另写规则，避免同一问题两条发现。规则引擎扩展（`core/rules.py`，向后兼容）：路径 `属性=>`（按取值找同类对象：Schema 类型为 interface 的属性找接口、ref 属性找被引用类型，用于没有引用边的 bind_port）；条件 `default: {node, value}`（设备 Profile 中该节点的缺省值，`supported: false` 的条目也可登记，只用于“没有配置时的行为”）；`remedy` 的键可以是风格名或平台族名（`nokia-sros-md` 为 MD-CLI 写法，按设备平台族优先、再按风格选，`baseline.remedy_for`）。检查规则写了 remedy 时，发现带 `remedy`（按平台族选好写法；没写 remedy 的规则发现结构不变）。

缺省值（D-0239，Classic Profile 人工条目，MD-CLI 经 `defaults_from` 复用）：Epipe / VPLS / VPRN / IES 与 SDP 缺省 shutdown（业务另写 `assume: false`）、SDP keep-alive 缺省关闭、SAP 缺省启用（`assume: false`，翻译到华为时省略）。

**安全基线**（D-0240，`baseline-security.yaml`）：原有 30 条中 Nokia 适用的 20 条都补了 `nokia`（Classic）与 `nokia-sros-md`（MD-CLI）两种修复命令；VTY / 登录线路类规则对 Nokia 不适用（na）。按 Nokia 的“没有配置时的行为”补分支（都用 `not supported` 限定，华为 / Cisco 结论不变）：不写 ssh 块时 SSH 缺省开启、SSH 只支持 v2、AAA（本地认证）恒开启、NTP / syslog / SNMP 告警缺省以 system 地址为源（`supported: false` + `default` 条目，不生成默认节点）；SNMP 团体字 ACL 接受管理访问过滤器。新增 4 条（基线共 34 条，basic 26 条）：`sec.mgmt_access_filter`（基础）、`sec.password_lockout`（基础，锁定前失败次数 ≤ 5，缺省 3）、`sec.password_aging`（严格，≤ 90 天）、`sec.login_idle_timeout`（基础，≤ 15 分钟，Nokia 缺省 30）。新 Schema 节点 `mgmt.maf`（对象，含 `ipv4`）、`mgmt.aaa.password_aging` / `login_attempts` / `lockout_time`、`mgmt.system.idle_timeout`；Classic 映射 `management-access-filter`、`ip-filter`、`authentication-check`、`password aging` / `attempts`、`login-control idle-timeout`，MD-CLI 映射 `management-access-filter`（块内为范围外原文，只记已配置）、`authentication-check`、`idle-timeout`（MD 的口令策略在 user-params 下、命令卡范围外：口令有效期不适用，失败次数按缺省值）。

样本结论：加固后的合成配置（`tests/inputs/configs/nokia/baseline-*-hardened.cfg`）基础基线 Classic / MD 都是 100 分，严格基线只剩 SNMPv2c 团体字；`classic-pe-routing-mgmt` 基础 70 分（Telnet、FTP、团体字无 ACL 且无管理访问过滤器、用户允许 FTP、NTP 未认证），MD 版 74 分（用户 access 布尔叶子未归并）。

**跨设备一致性**（D-0241）：`cross-device.yaml` 的 28 条链路规则对 Nokia 全部适用（没有被跳过的），只补了 `core/topology.py` 的事实提取：设备名取 `system name`、`system` 与 loopback 接口当 Loopback、LSR ID 取 system 地址（其次 router-id）、路由器接口绑定的端口关闭视为接口关闭、BGP `local-address` 直接写地址、BGP 地址族取 family（MD-CLI 的 family 未归并时记为未知、不比较）、IS-IS 区域取 area-id。合成样本 `tests/inputs/configs/nokia/topo-pe-{a,b}.cfg`（Classic + MD-CLI）推出 subnet / ospf / ldp / bgp / pw 五条链路，报出故意放的 OSPF hello、dead、伪线 VC ID 三处不一致，没有多报。华为 / Cisco 拓扑样本的链路与发现逐字节不变。

**补齐写法**（D-0242）：
- `vrf-target export X import Y`：Classic 映射另建 import 的 RT 对象（目标写法 `rt{value=…,direction=…}`，固定键取自参数的对象与本行另一个同类对象并存）；`core/graph.py` 只把属性写给各自的对象，`core/canon.py` 把这类对象当作“本行的另一个实例”，规范渲染时每个 RT 单写一行。Classic 与 MD-CLI 的图对照测试去掉了这一项允许差异。
- BGP 地址族 ↔ Nokia family（`translate.reshape_bgp_family`，只换公网地址族）：华为 / Cisco → Nokia 时全局地址族写成 `family ipv4 vpn-ipv4`，组启用的地址族与全局不同时写组的 family，已表达的 `peer … enable` / `activate` 不再报不支持；Nokia → 华为 / Cisco 时 family 换成地址族视图与组的 `peer … enable`。MD-CLI 的 family 布尔叶子仍未归并。
- `!flag`（`no shutdown` 表示启用）的节点不再标为取消形式（原来 LDP 接口、SDP 保活、SSH 服务等节点取值为 true 却标了 negated，检查与拓扑按“未生效”处理）。

翻译回归（未解释差异都是 0）：

| 用例 | M7-4 | M7-5 | 下限 |
|---|---|---|---|
| nokia-basic-to-atn | 81 / 102 | 81 / 103（登录空闲超时华为无对应） | 0.78 |
| nokia-routing-mgmt-to-atn | 91 / 122 | 97 / 131（family 互译；口令策略与空闲超时无对应） | 0.74 |
| nokia-services-to-atn | 79 / 155 | 85 / 155 | 0.54 |
| asr920-to-nokia | 90 / 137 | 93 / 131 | 0.70 |
| asr920-igp-mgmt-to-nokia | 64 / 132 | 66 / 128 | 0.51 |
| nokia-md-services-to-classic | 152 / 153 | 150 / 151 | 0.99 |
| nokia-classic-routing-mgmt-to-md | 117 / 122 | 118 / 125（MD 口令策略在范围外） | 0.94 |
| nokia-md-routing-mgmt-to-atn | 91 / 120 | 91 / 121 | 0.75 |
| nokia-md-services-to-atn | 82 / 157 | 82 / 152 | 0.53 |
| asr920-to-nokia-md | 88 / 137 | 90 / 131 | 0.68 |

**华为 / Cisco 结果不变**：改动前后对 20 份样本（解析、图 JSON、往返、规范渲染与含默认值的规范渲染、检查）、拓扑样本（拓扑与一致性）、两套基线、15 个翻译用例、16 个变更用例共 150 项做比较（`tmp/os/m75/baseline.py`、`cmp.py`）：除检查结果里的已加载规则数（8 → 25，新规则文件）与基线的规则清单（新增 4 条、对华为 / Cisco 都是 na）外逐字节相同；原有规则的结论、不符合项、修复命令、分数完全一致。

**界面**：顶栏的显示风格切换多了 Nokia（三语）；项目设置、Schema 查看、导出、特性查询、检查项目的平台筛选都列出 Nokia。厂商标识统一成 `frontend/src/vendor.ts` + `components/vendor-badge.vue`（NK，明暗两套 Nokia 蓝），设备列表、导入、添加设备、公共设备库、配置图、设备分析、检查目标条、首页、Profile、拓扑图、回归面板等不再把 Nokia 显示成 CS / ?。项目脚本与检查项目的空脚本骨架按格式给出 Nokia 写法（Classic `exit all` / `configure` … `exit all`，MD-CLI `edit-config private` … `commit` / `quit-config`）。配置图组织方式“自动”时华为与 Nokia 都按视图层级，Nokia 风格下顶层对象按 `contexts` 插入配置上下文分组（`buildModel` 的 `contextOf`；同名的 `service › vprn X` 分组并到该 VPRN 对象下），设备分析的配置分层树同样生效。检查页的发现带 `remedy` 时显示修复参考命令（可复制）；基线页的规则信息列出华为、Cisco、Nokia Classic、Nokia MD-CLI 四种修复命令，复制全部时注释前缀按平台族。翻译页在配置原文里找不到 `interface` 行时按配置图列出接口（Nokia）。端到端 `frontend/e2e/m7.spec.ts`：上传 Nokia Classic 样本 → 检查页报出端口关闭与修复参考命令 → 切到 Nokia 风格，配置图显示 `port 1/1/4` 并按 router Base / service 分组（暗色截图）→ 翻译到华为 ATN。

**测试**：单元 `tests/unit/test_nokia_m75.py`（三种风格登记、Nokia 写法与上下文、`=>` / `default` / 平台族 remedy、Classic 与 MD 的检查结论相同、干净样本不误报、新规则对华为 / Cisco 样本不产生发现、加固 / 未加固的基线结论与修复命令写法、Classic + MD 的拓扑与一致性、vrf-target、`!flag`、BGP family 双向翻译）；`test_nokia_md.py` 的允许差异收紧（去掉 import RT，加上 MD 口令策略两项）；`test_nokia_m73.py` 的风格断言按新行为更新；CLI 用例 `nokia-check-services`、`nokia-baseline-md`、`nokia-consistency`、`nokia-terms-style`；API 用例 `nokia-check-port`、`kb-terms`（加 nokia 与 contexts）、`baseline-rules`（规则数 34）。

**遗留**：
- VPRN 下的 BGP / OSPF（仍进 opaque）：要扩大命令卡范围、在 Schema 中表达 VRF 内的协议实例并补翻译，工作量超出本阶段（D-0242）。
- vrf-target 的 export 与 import 两个方向在规范渲染时各写一行（设备上后一条可能覆盖前一条），没有合成一行；MD-CLI 的 BGP family、用户 access 仍是未归并的布尔叶子；MD-CLI 的口令策略（user-params）在命令卡范围外。
- `source-address`（NTP / syslog / SNMP 告警源地址）、SSH 算法列表（server-cipher-list 等）、SNMP src-access-list 未建模：基线按缺省值或管理访问过滤器判断。
- 检查规则的修复命令里端口、业务编号用尖括号占位（SAP 的键不是端口），报告（`lmesh report check`）还没有列出修复参考命令；发现说明里的节点是规范编号，界面按显示风格另行显示。
- Nokia 风格的部分对象写法带上下文前缀（`router Base bgp …`、`qos sap-ingress …`），放在上下文分组下略显重复；模板（REQ-024）的新模板骨架对 Nokia 仍写 `hostname`。
- 路由器接口的 ip-mtu 与端口 MTU 没有区分，链路 MTU 一致性对 Nokia 只比较接口上写了的值。

**待真机核实**：SAP / 端口 / 业务 / SDP 的缺省管理状态（以命令参考为准）、SR OS 25.x SSH 只支持 v2、不配置 source-address 时 NTP / syslog 以 system 地址为源、`vrf-target export X` 与随后单独的 `vrf-target import Y` 是否互相覆盖、Classic `password attempts` 的缺省值（3 / 5 / 10）、MD-CLI 的 `management-access-filter` 与 `authentication-check` 写法、修复命令的 MD-CLI 绝对路径写法（`/configure …`、`delete /configure …`）能否直接粘贴执行。

### REQ-051 结果（2026-10-21）

- 预览：`DevelopDocs/ui-preview/REQ-051/ask.html`（自动模式按推荐先编码，决策 D-0347～D-0350）。
- 范围：下拉选网络（默认当前网络，没有时为默认网络；默认网络标“全部设备”），设备从 `/projects/<项目>/n/<网络>/devices` 取，提问走 `/projects/<项目>/n/<网络>/ask`；设备多于 6 台时有按名筛选和按厂商筛选，超过 14 台默认收起两行、可展开；全选 / 清空，显示“已选 n / m 台”；只存原文的设备（没有 Profile）置灰、标“只存原文”、不能选，并在下方说明不参与查询。清空范围后不能提问。
- 顶部 AI 接口信息与三栏说明可收起成一行，状态作为个人偏好 `ask_intro`（open / folded）随账号保存（`PUT /api/v1/me/prefs`），未登录时存在浏览器。
- 前端 `api.ts` 的请求可以显式指定网络（`{ network: <网络> }`），不在网络页面也能按网络调用。
- 同时修复：AI 查询、表格导出、生成配置查重取“全部设备”时遇到只存原文的设备报 500（`history.devices_from_db` 跳过这类设备，点名时按找不到报告）；API 层对没处理到的“解析不了”错误兜底返回 409 `model.raw_only`（或 422），不再报 500。
- 评审修改（用户 2026-10-21，D-0351～D-0353）：加“反选”；有筛选条件时全选 / 清空 / 反选只作用于筛出来的设备；有只存原文的设备时可勾选“隐藏只存原文的设备（n）”（本浏览器记住）；设备区与“展开全部”行固定高度，按厂商筛选后下方内容不再跳动。
- 测试：单元测试 `test_devices_from_db_skips_raw_only`、API 偏好用例加 `ask_intro`、vitest `ask-scope.test.ts`、e2e `m5.spec.ts`“AI 查询（REQ-051）”。

### AI 查询会话（REQ-052）

用户 2026-10-21 询问 AI 查询的会话能否保存、能否在一个会话里反复追问修改、能否归档、每个人的记录是否独立。现状：问答只在页面内存中，刷新即丢；每次提问相互独立，AI 看不到之前的问题；只有 AI 调用用量（谁、模型、token）按人记录。经用户确认（【用户确认】）：

- 可见范围：会话只有本人可见；可以把某个会话分享给同项目成员只读查看（可随时取消分享）。系统管理员不因身份查看他人未分享的会话。
- 追问：同一会话中追问时，AI 能看到本会话前几轮的问题与图查询（同样先脱敏，条数有上限）；结论仍由代码在图上计算与核对。
- 改问重答：任一轮可以修改问题重新回答，旧的回答保留为该轮的历史版本，可切换查看。
- 归档：会话列表分“进行中 / 已归档”，可以重命名、归档、恢复、删除；不自动清理。
- 归属：会话属于项目，记录提问时选的网络与设备范围；在项目里打开即是该项目的会话；离开项目（被移出）后看不到该项目的会话。
- 范围：先做“问配置”；“生成配置（护栏）”保持现状。

### AI 查询附件与下载（REQ-053、REQ-054）

用户 2026-10-21 询问 AI 查询能否上传图片或文档附件、生成的结果能否下载报告（HTML / Markdown、结果表 CSV / Excel、PDF、AI 写的 Markdown 报告），要求与 REQ-052 一起放进 0.9.2。以下细节按自动模式决定（D-0354～D-0359），等用户回看：

- 附件属于会话（只有会话主人能添加或删除；分享的会话里成员只读可见附件名），删除会话时一起删除；每个会话最多 10 个，单个不超过 10 MB。
- 配置文件：能识别厂商的文本（含 zip 中的多份）作为本会话的“临时设备”，导入时同样按 basic 级别脱敏，解析入图后加入范围，结论照样由代码核对；不进入设备库，也不出现在其他会话。
- 文档：txt、md、csv、log（认不出厂商时）、pdf、docx、xlsx 提取文字（最多 3 万字），发给 AI 前先脱敏，作为“参考资料”放进提示；回答中依据参考资料的陈述代码无法核对，标为“无法校验”。
- 图片：png、jpg、webp；新配置项 `ai.ask_images`（默认 false，管理员在系统设置与首次运行向导中开启）。图片无法自动脱敏，开启后每次发送前在界面勾选确认；只作参考，相关陈述标为“无法校验”；接口不支持看图时报错提示。
- 下载（代码生成，不需要 AI）：会话报告 HTML（自包含、可打印，“打印为 PDF”用浏览器打印）与 Markdown，中英双语各一份；任一轮的结果表 CSV 与 Excel（带设备、节点、配置行号）。服务器端不另外生成 PDF（离线包不带中文字体）。
- AI 报告：新内置 skill `ask-report` 根据会话中已核对的陈述与结果写一份 Markdown 报告；代码核对报告中的数字与设备名、对象名都能在会话结果中找到，找不到的片段标出“未经核对”；下载为 .md。

### REQ-052～054 结果（2026-10-21）

- 数据：迁移 `0015_ask_sessions` 新增 `ask_sessions`（项目、本人、标题、网络与范围、归档、分享）、`ask_turns`（各版本的问题与结果、当前版本、上下文轮数）、`ask_attachments`（配置 / 文档 / 图片）。
- core：`ask_sessions`（权限：本人可改；分享后同项目成员只读；不是本人也没分享按不存在处理）、`ask_docs`（Excel 按表带行号、PDF 按页、Word 段落与表格、CSV，代码提取不经 AI）、`ask_report`（会话报告 HTML / Markdown 中英文、结果表 CSV / Excel、AI 报告占位符核对）；`ask.ask` 增加 history（最近 5 轮问题与图查询）、references（附件文档文字，最多 3 万字）、images（用户确认的图片，`ai.with_images`）。
- skill：`ask-query` 增加 context 模板，`ask-answer` 增加 references 模板（管理员改过的旧版本没有时用内置写法），新增 `ask-report`（数字写 `<<键>>`、对象写 `[[编号]]`，由代码填入；有 AI 自己写的数字或未知键的句子标“未经核对”）。
- 接口：`/api/v1/projects/{p}[/n/{net}]/ask/sessions…`（列表与计数、新建、查看、PATCH 改名 / 归档 / 分享 / 范围、删除、提问、改问重答、切换版本、附件上传与删除、会话报告、结果表、AI 报告）；会话操作按 compute 级别，只读成员也能管理自己的会话。
- 命令行：`lmesh ask-session list / new / show / ask / reask / update / delete / attach / detach / report / table / ai-report`。
- 新配置项 `ai.ask_images`（默认 false，向导 AI 一步与 config.example.toml）；`GET /ask/status` 返回 images。
- 界面：AI 查询“问配置”改为三栏（会话列表 / 会话 / 证据）；会话头部可重命名、分享、归档、删除、下载（HTML / Markdown 中英文、打印为 PDF、AI 报告）；附件栏；每轮可修改问题重新回答、切换版本、显示追问带了几轮上下文；结果表上 CSV / Excel 下载；图片附件发送前确认；网址带 `?s=<会话>` 刷新后回到该会话。
- 同时改进：导入时脱敏自检失败（`import.sanitize_leak`）的提示附上残留所在的行号（只有行号，不含值），便于找到没认出来的命令写法。
- 测试：API `test_ask_sessions_api.py`（会话、上下文、版本、归档、附件、图片确认、下载、AI 报告）、单元 `test_ask_sessions.py`（分享权限、文档提取、报告核对）、`test_sanitize.py`（残留行号）、CLI `cli_cases.ask_sessions.toml`、vitest `ask-sessions.test.ts`、e2e `m5.spec.ts`“AI 查询会话（REQ-052～054）”。

## REQ-055 问题清单

来源：2026-10-28 用 Huawei-SI 现网配置（5 台华为 VRP V8，严格脱敏后导入独立演示环境）在 Web 界面逐场景操作，以及此前功能示例案例的 CLI 运行。复现所用数据在演示环境 tmp/si-demo/（脱敏配置），原始日志只在 DevelopDocs/设备配置案例/Huawei-SI/。

| 编号 | 严重程度 | 位置 | 现象 | 复现 |
|---|---|---|---|---|
| 055-01 | 高 | 配置检查 `bgp.peer.remote_as_missing` | 把对等体组当成没有 AS 的对等体报错：`group AGG-CSG-REGIAO-380 internal` 之后的 `peer AGG-CSG-REGIAO-380 description …` 被报“缺少 remote-as”；RMD01 的 4 个错误、RMC02 的 5 个错误全部来自这条 | 演示环境 /check?device=1（第 1719～1722 行）、/check?device=4（第 6291～6292 行） |
| 055-02 | 高 | 脚本检查 | 脚本删除仍被引用的 route-policy 时，ref.dangling 只出现在 JSON 的 findings_new，没有计入 issues 和错误数 | 功能示例 script-check 案例 |
| 055-03 | 中 | 安全基线页 AI 摘要框 | 显示未翻译的文案键 `kb-ai.ra.include`、`kb-ai.ra.note`（中英文都有）；`ReportAiSummary.vue` 用了前缀 `kb-ai.`，文案在 `ai-kb.json`，应为 `ai-kb.` | 打开 /baseline |
| 055-04 | 中 | 模板生成 | `template generate huawei-atn-l2-bd-vbdif` 对只有 1 个 svc 实例的行校验失败 | 功能示例 template 案例 |
| 055-05 | 中 | 脱敏 | strict 级把 ACL 通配符对应的网络地址替换成带主机位的地址（`10.95.0.0 0.0.255.255` → `x.x.121.144 0.0.255.255`），网段语义被破坏 | 对含 `rule … source <网络> <通配符>` 的配置执行 `lmesh sanitize --level strict` |
| 055-06 | 低 | 安全基线规则详情 | `sec.vty_ssh_only` 的“不通过时”说明显示未替换的 `{key}`（中英文都有）；逐设备的行正常 | /baseline 点击规则名 |
| 055-07 | 低 | 设备配置图 | 带 `?node=` 打开时详情面板选中了节点，但画布停在设备根节点，看不到该节点 | /graph/1?node=interface[GigabitEthernet0/1/0] |
| 055-08 | 低 | 设备配置图 | 原文面板显示 2,766 行，设备列表为 2,767 行；Gi0/1/0 引用了 traffic-policy，节点详情的“依赖”却为 0 | /graph/1 |
| 055-09 | 低 | CLI 输出 | `parse --lines` 文本模式只打印汇总，逐行明细只在 `--output json` 中出现 | 功能示例 parse 案例 |
| 055-10 | 低 | CLI 输出 | guard 与 consistency 的汇总行打印两次；英文 change 输出含全角冒号 | 功能示例 guard、consistency、change 案例 |
| 055-11 | 低 | 界面文案 | 冗余清理英文单数写成 “1 lines”；英文界面里项目名“默认项目”未翻译；未识别行详情面板第一列右侧被截断 | /cleanup、页头项目选择、/unknown-lines |
| 055-12 | 低 | 网络切换 | 打开配置检查、冗余清理、安全基线时，网络选择器从“全部设备”变成“默认网络”（网址变为 /n/default/…） | 在“全部设备”下进入这三个页面 |
| 055-13 | 低 | 导出 | bgp-peer 导出时，从对等体组继承的 Connect interface 为空 | 功能示例 export-table 案例 |
| 055-14 | 待核实 | 翻译 | ASR 920 翻译的警告说默认是 per-route，翻译结果里却是 `mpls label mode … per-vrf` | 功能示例 translate 案例 |

| 055-15 | 高 | 增量变更 | 新子接口里的 ` statistic enable` 没有进入下发脚本，模拟复检报“新增 interface[…]/ext[huawei-vrp8.statistic-enable]”不通过 | /change?device=1&mode=paste，目标配置的新子接口带 statistic enable |
| 055-16 | 高 | 增量变更 | `ip address` 与 `ip binding vpn-instance` 之间没有顺序依赖（只依赖所在对象）；华为上绑定 VPN 会清掉 IP，顺序必须是先绑定后配地址，目前只是碰巧按原文顺序 | 新子接口同时带两行时查看命令依赖 |
| 055-17 | 中 | 影响分析 / 配置图 | `connect-interface LoopBack100` 没有引用边指向接口，LoopBack100 的影响分析两个方向都是 0（所有对等体组都靠它建连） | /impact 选 interface[LoopBack100] |
| 055-18 | 中 | 影响分析 | GE0/1/9“受影响”为 0：接口自身的 OSPF、MPLS、LDP 设置没有算作受影响 | /impact 选 interface[GigabitEthernet0/1/9] |
| 055-19 | 中 | 跨设备一致性 | xd.ip_duplicate 行的“链路 / 会话”列显示未翻译的 `topology.type.null`（link_type 为空） | /consistency |
| 055-20 | 低 | 增量变更 | 修改类命令（#9 mtu 9208）显示“当前配置第 — 行”，实际在第 1287 行；脚本窗格长行被截断；带 ?device= 打开时设备下拉在列表加载完前为空 | /change?device=1 |
| 055-21 | 低 | 影响分析 | 96 个节点时力导向布局标签重叠，“按距离分层”挤成一列无法阅读 | /impact 选 route-policy AGG-CSG-PREFIXOS-IPV4-REGIAO-380 |
| 055-22 | 低 | 拓扑视图侧栏 | “两端配置”加载时先显示“没有找到这一端的配置块”且无加载提示；BGP 链路的 local/peer 地址镜像行被标成不一致；片段长行截断；点击问题后地图不重新适配到所选链路；cose 布局每次不同 | /topology 选 BGP 链路 |
| 055-23 | 低 | 跨设备一致性 | subnet.mtu 问题记录的是接口头所在行（1285），不是 mtu 所在行 | /consistency 点 RMD01 GE0/1/9 MTU 问题 |

| 055-24 | 高 | 设备配置分析 | 21k 行设备分析很慢：`/devices/3/analysis?parts=graph,layers,script` 并发负载下 433 秒、返回 24.7 MB，`parts=summary` 47 秒；页面长时间停在“正在分析配置…” | 演示环境打开 RMC01（21,305 行）的设备配置分析 |
| 055-25 | 中 | 设备配置分析 | 大设备“配置分层”树从根节点散出几十个 flow-queue 节点无法阅读，“折叠到功能域”无明显变化；结构化脚本“全部折叠”只折叠一个块（华为顶层是平的） | 同上 |
| 055-26 | 中 | 配置翻译 | 跨厂商翻译（华为 → Cisco）时接口映射默认“保持原名”，输出里留下 `100GE0/2/24` 这类华为接口名；割接迁移能正确映射 | /translate 选 RMP01 → cisco-iosxe-asr920 |
| 055-27 | 低 | 配置翻译 | 英文汇总最后一格文字截断（“…compared with the sour”）；页面显示 1,513 行，设备列表为 1,514 行（与 055-08 同类，行数统计差 1） | /translate 英文界面 |
| 055-28 | 低 | 表格导出 | BGP 对等体导出第一行是对等体组（地址 CSG-AGG、无 remote AS），与“对等体”表语义不符；点单元格后原文片段有时只显示行号 | /export 选 BGP 对等体模板 |
| 055-29 | 低 | 设备配置分析 | 结构化脚本工具栏“显示默认配置3311”数字前缺空格 | /analysis/3 |
| 055-30 | 高 | 翻译 / 割接迁移（Cisco → 华为） | VRRP 抢占翻译反了：Cisco `vrrp 10 … preempt delay minimum 30` 译成 `vrrp vrid 10 preempt-mode disable` 加 `preempt-mode timer delay 30`；割接校验报“旧 true、新 false”并拦下割接包 | 源 PE-ASR920-04（knowledge/samples/cisco-iosxe-asr920-synthetic/pe-asr920-04-advanced.cfg）翻译到 huawei-atn-v800r025 |
| 055-31 | 高 | 割接迁移 | 合并到已有配置时新增第二个 BGP 进程（`bgp 65000` 并入已运行 `bgp 65019` 的 RMP01），华为只允许一个 BGP 实例，下发会失败，且没有报为冲突 | 源 PE-ASR920-04，目标现有配置 = RMP01，查看增量配置与割接步骤 10、12 |
| 055-32 | 中 | 翻译 / 割接迁移 | 接口映射没有作用到 `clock source`：输出仍为 `clock source GigabitEthernet0/0/1 priority 1` | 同 055-30，接口映射 Gi0/0/1 → GigabitEthernet0/2/1 |
| 055-33 | 中 | 配置翻译 | 网址带 `?device=` 打开时源配置显示 0 个接口，从下拉框重新选设备才加载（源图只在 deviceId 的 watch 中加载，初始值不触发） | /translate?device=6&to=huawei-atn-v800r025 |
| 055-34 | 中 | 知识库 | 华为 ATN Profile 没有 IS-IS 写出命令（`router isis` 报“目标平台族没有能写出它的命令”）；PTP hybrid / port / profile、BGP EVPN 对等体 send-community 也不支持 | 同 055-30，看“目标不支持”告警 |
| 055-35 | 低 | 配置翻译 | 接口映射里只改大小写（Loopback0 → LoopBack0）被当作同名，输出仍为 `interface Loopback0`；割接迁移会改名 | /translate 手填 LoopBack0 |
| 055-36 | 低 | 割接迁移 | 英文单复数：“1 differences are unexplained” | /migration 英文界面校验卡片 |

## REQ-055 修复结果

全部 36 项都已处理；除 055-34 的两项知识库缺口外都已修复，并补了测试。按根因归类如下：

| 编号 | 根因与修法 | 测试 |
|---|---|---|
| 055-01、055-28 | 华为 `peer <组> description`、Cisco `neighbor <组> description` 的映射只写对等体，组名被当成一个没有 AS 的对等体；映射改成 `bgp.peer \| bgp.peer_group`（按取值是不是地址区分），重新汇总命令卡与 Profile | 单元 `test_checks.py`、`test_export_tables.py` |
| 055-02 | 引用方在基线里、被删的是脚本里的对象时，发现找不到脚本行，不计入问题；改为标到删除被引用对象的那一行 | 单元 `test_script_check.py` |
| 055-03 | `ReportAiSummary.vue` 用错了文案前缀（`kb-ai.` → `ai-kb.`） | 类型检查 |
| 055-04 | 只在重复块里出现的基础变量（`{{port}}`）只在块有 2 个以上实例时才绑定；改为有实例就绑定 | 单元 `test_template.py` |
| 055-05 | 前缀保持的地址替换会翻转主机位；地址后面跟掩码、反掩码或前缀长度、且原地址主机位全 0 时，替换后也清零主机位 | 单元 `test_sanitize.py` |
| 055-06 | 规则详情显示的是说明模板；没有具体对象时占位符显示为 `…` | 类型检查 |
| 055-07 | 首次布局完成后画布重新适配到根节点，覆盖了定位；首次布局后居中到已选中的节点 | 类型检查 |
| 055-08、055-27（行数） | 行数按“换行数 + 1”计算，末尾换行多算一行；统一用 `parser.line_count`。依赖数只算节点自身的边；改为算上子树里的边（接口的 traffic-policy 引用挂在子节点上） | vitest `model.test.ts` |
| 055-09 | `parse --lines` 文本模式补逐行明细（行号、类别、视图、命令卡、原文） | 手工核对 |
| 055-10 | 摘要同时写 stdout 与 stderr；两者是同一个终端时不再重复写 stderr（`output.err_summary`）；英文冒号用 `common.colon` | CLI 用例 |
| 055-11、055-36 | 英文单复数改用复数文案；默认项目名按界面语言显示（`projectLabel`）；未识别行详情面板允许换行 | 类型检查 |
| 055-12 | 只有默认网络时按设计进默认网络；切换器此时显示“全部设备”，不再像是被切换了 | e2e `m9.spec.ts` |
| 055-13 | 新增计算列 `peer_update_source`、`peer_password`：对等体没配时取对等体组的（密码仍只导出“已配置”） | 单元 `test_export_tables.py` |
| 055-14 | 核实为正确行为：源设备依赖华为默认 per-instance，目标默认 per-route，所以显式写出 per-vrf（Cisco 对 per-instance 的写法）；告警文案改为说明“按目标平台写法显式写出” | — |
| 055-15 | 整体新增的对象，规范渲染不写未映射命令（ext），ext 比较又跳过了它；改为只跳过整体删除的对象 | 单元 `test_change.py` |
| 055-16 | 副作用规则（绑定 VPN 会清掉地址）对新建对象完全跳过；现在新建对象也加“先绑定后配地址”的顺序约束（不补发） | 单元 `test_change.py` |
| 055-17、055-18 | Schema 增加 BGP 源接口 → 接口的引用（接口名统一写法匹配；Nokia 的 local-address 是 IP，不算引用；接口不算孤儿对象）；影响分析的起点自身里属于别的功能域的设置（接口上的 OSPF、MPLS）算作受影响 | 单元 `test_change.py`、`test_topology.py` |
| 055-19 | 链路类型为空时不显示类型文案 | 类型检查 |
| 055-20 | 修改类命令补上当前配置行号；脚本窗格文字列不再被压缩（可横向滚动）；设备列表加载前下拉框显示“加载中” | 单元 `test_change.py` |
| 055-21 | 按距离分层改为固定位置布局，一列超过 18 个节点折成多列；关系图谱按节点数加大斥力与边长，标签计入节点大小 | 类型检查 |
| 055-22 | 两端配置加载中显示“加载中”；BGP 两端视角互为镜像的事实（本端 / 对端地址、本端 / 对端 AS）交叉一致不算不一致；选中的线不在视野里时地图移到它的两端；布局起始位置按编号排在圆上，结果稳定 | vitest `m4.test.ts` |
| 055-23 | 比较的属性写在配置里时，发现定位到该属性的行（mtu 行），不是接口头 | 单元 `test_topology.py` |
| 055-24 | 规范渲染排序依赖时每次遍历全图的边（平方级），改为只看子树出边；隐藏默认值行只渲染默认值节点；接口响应开启 gzip 压缩。2 万行设备：结构化脚本 116 秒 → 2 秒，整页接口约 7 秒 | 全量测试 |
| 055-25 | 按视图层级时没有上下文的顶层对象（flow-queue 等）超过 40 个按功能域收成组，顶层未映射命令超过 8 个收成一组；“全部折叠”后滚到原先所在块的块头 | 类型检查 |
| 055-26 | 跨平台族翻译时，没有给出映射的接口按目标平台写法换名、编号不变（割接迁移的建议，不用端口清单），结果 `interface_map_auto` 列出；CLI 报告列出自动换名 | 单元 `test_translate.py` |
| 055-27 | 校验格说明允许换行 | 类型检查 |
| 055-29 | 数字与文字之间用外边距（父元素为 flex 时开头空格会被吞掉） | 类型检查 |
| 055-30 | 合并到现有配置时没带默认值节点，VRRP 抢占缺节点被写成 `preempt-mode disable`；合并时默认值节点一起带过去（不计入新增） | 单元 `test_migration.py` |
| 055-31 | `knowledge/migration/<平台族>.yaml` 增加 `single: [bgp.instance]`：合并时编号不同也并入现有进程，告警 `target_single`（error 级），割接步骤用新设备的进程号 | 单元 `test_migration.py` |
| 055-32 | 键字段可能是接口名的对象（时钟源）：取值正好是映射表里的接口时按接口改名（翻译与对比一致） | 单元 `test_migration.py` |
| 055-33 | 源配置只在设备变化时加载，网址带的初始值不触发；监听改为立即执行 | 类型检查 |
| 055-34 | IS-IS：Cisco 进程名是标签（CORE），华为进程号必须是整数，所以写不出；翻译时自动编号（引用一起改，告警 `key_renumbered`）。PTP hybrid / port / profile（两家结构不同）与 EVPN send-community both（华为标准 / 扩展团体是两条命令，当前 Schema 不能拆成两张卡）留作知识库缺口 | 手工核对 |
| 055-35 | 接口映射表只差大小写的行也传给后端 | vitest `compare.test.ts` |

## REQ-056 问题清单

来源：2026-10-29 用 REQ-055 修复后的代码（提交 5341fe4）在演示环境 tmp/si-demo/ 重拍 Huawei-SI 场景截图，并用模拟 AI 回复（tmp/si-demo/fake_ai.py，不调用真实模型）拍 AI 功能截图。

| 编号 | 严重程度 | 位置 | 现象 | 复现 |
|---|---|---|---|---|
| 056-01 | 高 | 割接迁移验证 `migration.verify` | 翻译时 IS-IS 进程自动改号（`key_renumbered`，CORE → 1）后，迁移验证不把这项改动算作已说明，留下 2 项未解释差异（`interface[GE0/2/1]/isis[_]/process` 旧 CORE、新 1；`isis.process[1]` added），割接包导出被拦；只做翻译时同样的差异算已说明。规则集的 names 也不允许给 isis.process 改名（“不是可改名的类型”），用户无法绕过 | 割接迁移页选 PE-ASR920-04，目标 huawei-atn-v800r025，已导入的设备选 RMP01，生成后验证；CLI：`lmesh migrate <cfg> --profile cisco-iosxe-asr920-17.15 --to huawei-atn-v800r025` 未解释 3 项 |
| 056-02 | 中 | 迁移验证告警文案 | verify_diff 告警没有旧值时显示原样占位符 `旧 {src_value}` / `old {src_value}` | 同 056-01，验证页第二行 |
| 056-03 | 中 | 影响分析关系图谱 | 约 96 个节点时力导向布局仍挤成一条细柱，标签看不清（055-21 未修完）；按距离分层正常 | 影响分析选路由策略（影响 95 个对象）后切到关系图谱 |
| 056-04 | 低 | 设备配置分析“结构化脚本”页签 | 行数仍按旧口径（RMC01 显示 21,305 行，设备列表为 21,304 行），055-08 的修正未覆盖 | 打开 RMC01 的设备配置分析 |
| 056-05 | 低（待确认） | 增量变更 AI 意图 | 连续采纳两条建议后，脚本与模拟只含第一条，重新获取计划后才完整（接口已返回全部 9 个操作） | /change?device=1 运行意图，依次采纳“开启 GigabitEthernet0/2/5”和“…OSPF 与 MPLS LDP” |
| 056-06 | 低 | 拓扑角色卡、AI 报告摘要 | 角色卡里 “PE” 未翻译，其他角色显示译名；英文界面下报告摘要标题仍是中文“检查结论” | AI 拓扑角色采纳后看角色卡；英文界面生成报告摘要 |

| 056-07 | 低 | 割接方案文档标题 | 合并到已有设备时标题仍写“PE-ASR920-04 替换为 ORG-CD09F3H8-RMP01”，应体现“并入” | 割接迁移选 PE-ASR920-04 → RMP01（合并现有配置），生成割接方案 |
| 056-08 | 中（待确认） | 割接迁移 BGP 合并 | 并入 RMP01 现有的 `bgp 65019` 后，原 Cisco 侧 AS 65000 的 iBGP 对等体在新设备上变成跨 AS，步骤 s10 只写 `undo peer 10.255.0.4 ignore`，没有提示对等关系类型改变 | 同 056-07，看割接步骤 s10 与合并告警 |

## REQ-056 修复结果

8 项全部修复。修复后在演示环境重拍割接迁移截图：PE-ASR920-04 并入 RMP01，差异 268 项全部有原因、未解释 0，校验通过，可以导出割接包。

| 编号 | 根因与修法 | 测试 |
|---|---|---|
| 056-01 | 翻译前在源图副本上给 IS-IS 进程改号，迁移验证却拿没改号的旧图比较；验证时旧图按同样的编号改过再比（有原因的节点编号跟着改，改号告警本身不覆盖新对象下的差异）。另补上翻译校验已有的两条：源平台没有的开关（`supported: false`，如 SSH 服务）、按 `assume` 显式写出的管理状态，迁移校验同样算已说明 | 单元 `test_migration.py` |
| 056-02 | 校验差异没有旧值 / 新值时参数为空，文案显示原样占位符；翻译与迁移的校验差异都改为显示“—” | 单元 `test_migration.py` |
| 056-03 | 节点按标签计算大小后又宽又扁，力导向布局把对等体组下的约 90 个对等体排成一列；布局范围改为与画布同比例、面积按节点数计算 | 截图核对（明 / 暗） |
| 056-04 | 解析时按换行切分，末尾换行多出一个空行；结构化脚本去掉末尾的空行，与 `parser.line_count` 一致 | 单元 `test_layers.py` |
| 056-05 | 连续采纳时先发出的计划请求可能后返回，覆盖新的结果；加请求序号，只采用最新一次的结果 | vitest `intent.test.ts` |
| 056-06 | 角色卡的 PE / P / CE 保留行业术语并加说明（如“PE（运营商边缘）”），与设备图标的角色名一致；报告摘要的段落标题改用界面语言的文案（“报告摘要 · 中文报告用”等），不再显示 AI 写的标题 | vitest `card.test.ts` |
| 056-07 | 割接方案文档在选了新设备现有配置时标题写“并入”（`Cutover plan: merge … into …`） | API `test_ai_change_api.py` |
| 056-08 | BGP 并入 AS 不同的现有进程时，逐个找出 remote-as 等于原本地 AS 的对等体，告警 `ibgp_to_ebgp`（error 级，三语文案） | 单元 `test_migration.py` |

另：主工作区的运行时知识库（data/knowledge）还是 REQ-055 之前的版本，CLI 直接运行时没有 `single: [bgp.instance]`；`lmesh serve` 启动时会自动合并，也可以手动 `lmesh kb upgrade`。

