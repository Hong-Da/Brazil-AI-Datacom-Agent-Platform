<p align="center"><img src="assets/brand/logo.png" width="96"></p>

# 透网 LucidMesh

把不同厂商、不同版本的路由器配置转换成一张统一的配置图，翻译、对比、模板校验和配置检查都在图上完成。命令名 `lmesh`。

> 当前状态：开发中（M1 · 0.1.0 知识库与往返）。

## 功能

- 配置解析：华为 ATN（V800R025 / R023）与 Cisco ASR 920（IOS-XE 17.15）配置 → 带行号的结构化 JSON → 统一配置图
- 往返渲染：配置 → 图 → 配置文本一致；隐藏的默认值、派生值在图中以“有效值”参与运算
- 知识库：命令卡、Schema、Profile 以产品文档为来源，规则或 AI 抽取、人工审核、版本发布与回滚
- 配置脱敏：替换密码、团体字、密钥、公网 IP，保持引用关系不变
- 后续版本：对比与检查（0.2.0）、翻译与模板（0.3.0）、变更与分析（0.4.0）、扩展功能（0.5.0）

## 快速开始

不需要预先安装任何工具：`start` 脚本会检查 [uv](https://docs.astral.sh/uv/)，没有时询问后安装到项目内的 `.toolchain/bin/`；Python 与 Node 也由脚本自动下载到 `.toolchain/`。

其他参数：`--check` 只检查不启动，`--setup` 重新进入配置向导（加 `--defaults` 不提问），`--reinstall` 重装依赖，`--port <端口>` 临时换端口。

- Windows：双击 `start.bat`
- Linux：`./start.sh`

首次运行会进入 Web 配置向导。默认监听 `0.0.0.0:9090`，局域网内可访问。

## 部署

面向最终用户的部署不需要源码和联网，有四种形式（构建与安装、升级、卸载、改用 PostgreSQL、端口与防火墙、备份详见 [docs/deploy.md](docs/deploy.md)）：

| 形式 | 安装 |
|---|---|
| Docker 镜像 + compose | `docker load -i lmesh_<版本>_docker-image.tar.gz`，再用 `compose.yaml`（SQLite）或 `compose.postgres.yaml`（PostgreSQL）启动 |
| Linux 离线安装包 | 解压 `lmesh_<版本>_linux-x86_64.tar.gz`，`sudo ./install.sh --user lmesh --create-user`（systemd 服务） |
| Windows 离线包 | 解压 `lmesh_<版本>_windows-x64.zip`，双击 `start.bat`；`service-install.bat` 注册为 Windows 服务 |
| Windows 安装程序 | 运行 `lmesh_<版本>_windows-x64_setup.exe` |

各形式都自带 Python 运行时与依赖；数据库默认 SQLite，可在配置中改为 PostgreSQL。升级时保留配置与数据，自动迁移数据库，并把新版本自带的知识库合并进运行时知识库（双方都改过的文件进审核队列）。发布包由 `scripts/build_release.bat`（Windows：zip、exe）与 `scripts/build_release.sh`（Linux：tar.gz、Docker 镜像）生成到 `dist/<版本>/`（每个版本一个文件夹）。

## 使用方式

- Web 界面：浏览器打开 `http://<地址>:9090`
- CLI：`lmesh --help`，见 [docs/cli.md](docs/cli.md)
- 网页登录：用户账号（管理员 / 知识库维护员 / 普通用户），首次运行向导创建第一个管理员；命令行管理账号用 `lmesh user`
- 项目：每个账号有自己的工作空间与项目（私有设备、引用的公共设备、脚本、规则调整），可以邀请成员（可编辑 / 只读）；命令行用 `lmesh project`、`--project <项目>`
- 远程 API：前缀 `/api/v1`，设备相关接口在项目路径 `/api/v1/projects/{项目}/…` 下（旧的无项目路径保留为兼容别名，落到默认项目）；脚本用个人 API 令牌（`lmp_` 开头，权限同本人账号，可只读）或全局令牌（视为管理员）认证，网页用会话 Cookie，见 [docs/api.md](docs/api.md)

## 项目结构

```
lmesh/
├── README.md                   项目说明
├── CLAUDE.md                   项目记忆
├── pyproject.toml / uv.lock    Python 依赖与锁文件
├── .python-version             Python 版本
├── .gitignore / .gitattributes
├── start.bat / start.sh        一键运行
├── cli.bat / cli.sh            CLI 包装脚本
├── test.bat / test.sh          一键测试
├── Dockerfile / .dockerignore  Docker 镜像（多阶段：Node 构建前端、Python 运行）
├── packaging/                  发布包的模板（由 scripts/build_release.py 使用）
│   ├── docker/                 compose.yaml（SQLite）、compose.postgres.yaml、env.example
│   ├── linux/                  install.sh、uninstall.sh、start.sh、bin/lmesh 启动器、README.txt
│   └── windows/                start.bat、lmesh.bat、Windows 服务（WinSW 配置与注册脚本）、installer.nsi（NSIS）、README.txt
├── config/
│   └── config.example.toml     配置示例（实际配置 config.toml 不入库）
├── src/lmesh/                  Python 包
│   ├── core/                   业务逻辑：config、logging、i18n、setup、status、store（数据库与迁移）
│   ├── cli/                    Typer 命令
│   ├── api/                    FastAPI 路由
│   ├── locales/                后端文案（zh-CN、en、pt-BR）
│   └── web/static/             前端构建产物（不入库，由 start 脚本构建）
├── frontend/                   Vue 3 + Vite 前端（package.json、pnpm-lock.yaml、.nvmrc、pnpm-workspace.yaml、src/）
│   ├── src/views/              各页面（每页一个 *View.vue，子组件与纯逻辑放同名目录）
│   ├── src/project/            当前项目：接口路径改写（/projects/<项目>/…）、项目页面路由 /p/<项目>/…（M6）
│   ├── src/stores/             共享状态：账号、当前项目、当前网络、外壳计数、偏好
│   ├── src/i18n/pages/         各页面的三语文案
│   └── e2e/                    Playwright 端到端测试
├── knowledge/                  程序自带的知识库（M1-4 起）
│   ├── sources/                原始资料来源记录（M1-4 起）
│   ├── extractors/             各厂商文档的命令卡抽取规则（M1-5 起）
│   ├── commands/               命令卡（M1-5 起）
│   ├── schema/                 统一 Schema（M1-6 起）
│   ├── mappings/               命令卡参数 → Schema 节点的映射规则（M1-6 起）
│   ├── profiles/               厂商 + 版本 Profile（M1-4 起）
│   ├── rules/                  配置检查规则（写在统一 Schema 上，与厂商无关；M2-4 起）
│   ├── render/                 规范渲染的平台族书写习惯（退出命令、推导规则、接口类型；M3-3 起）
│   ├── change/                 增量变更脚本的平台族下发习惯（开头 / 结尾命令、补充的副作用与取消写法、先删后建、高风险节点；M4-3 起）
│   ├── migration/              割接迁移的平台族操作命令、管理口识别与各型号端口清单（ports/；M4-5 起）
│   ├── export/                 审计表格导出的预置模板（tables.yaml：IP 地址表、VLAN / 桥域表、BGP 邻居表等；M5-3 起）
│   ├── templates/              配置模板（M3-4 起）
│   ├── translate-rules/        翻译规则集的内置示例（名称映射、命名规范、端口映射；只读；REQ-032 起）
│   ├── ai-skills/              内置 AI skill 定义（提示词、提示模板、示例、工具、代码校验、试运行样例；只读；REQ-033 起）
│   ├── layers.yaml             Schema 对象 → TCP/IP 层（含 2.5 层与跨层特性 QoS、时钟同步），设备配置分析用（REQ-034 起）
│   └── samples/                已脱敏的配置样本与往返期望结果（M1-3 起）
│       ├── compare/            配置对比基准：由样本派生的变体与期望差异（manifest.yaml；M2-3 起）
│       ├── translate/          配置翻译回归：用例、接口映射表与合成样本（manifest.yaml；M3-3 起）
│       └── migration/          割接迁移回归：用例、部分接口映射表、新设备现有配置（manifest.yaml；M4-5 起）
├── assets/brand/               Logo 与图标
├── docs/
│   ├── project-spec.md         项目规范
│   ├── cli.md / api.md         CLI 与远程 API 调用文档
│   ├── deploy.md               部署指南（Docker、Linux、Windows 的安装、升级、卸载、PostgreSQL、备份）
│   └── openapi.json            API 定义（由 scripts/gen_docs.py 导出）
├── scripts/
│   ├── env.bat / env.sh        工具链与缓存位置，所有脚本先加载它
│   ├── version-status.sh       版本检查（SessionStart 钩子）
│   ├── ensure_node.py          准备项目内的 Node（只用于构建前端）
│   ├── build_frontend.py       按需构建前端
│   ├── run_tests.py            一键测试的实际逻辑
│   ├── gen_docs.py             从测试用例生成调用文档示例、导出 OpenAPI
│   ├── build_release.py        生成发布包到 dist/<版本>/（外层 build_release.bat / .sh；REQ-046）
│   ├── linux_sync.sh           开发辅助：把代码同步到 Linux 测试机
│   ├── e2e_server.py           端到端测试用的临时服务（全量知识库 + 样本）
│   └── build_icons.py          从 logo.svg 导出图标
├── tests/                      测试（见 tests/README.md）
├── .claude/settings.json       SessionStart 钩子
├── .claude/skills/             项目专属 skill（lmesh-docs-to-graph：产品文档 → 配置图）
├── data/ logs/ cache/ tmp/     运行时文件（不入库；用户的翻译规则集在 data/translate-rules/，我的模板在 data/user-templates/，管理员修改的 AI skill 版本在 data/ai-skills/，访问审计在 logs/audit.log）
├── .toolchain/                 依赖缓存与项目内的 Python、Node，以及打包用的 NSIS 便携版、WinSW（不入库）
└── dist/<版本>/                发布包，每个版本一个文件夹（不入库，不推送远程）
```

`DevelopDocs/` 是开发文档的本地仓库，不随主仓库发布。

## 测试

- Windows：`test.bat`；Linux：`./test.sh`
- 后端测试默认并行（pytest-xdist，进程数 = CPU 核数，上限 16）；`--serial` 串行，`-n N` 指定进程数
- 开发中的增量测试：`--changed`（只跑与未提交改动相关的类别，`--changed main` 对比分支），会打印选了哪些
- 只运行某一类：`--unit` / `--cli` / `--api` / `--docs` / `--roundtrip` / `--frontend`；端到端测试 `--e2e` 单独运行（需要浏览器：Windows 用系统 Edge，Linux 先在 frontend 目录运行 `corepack pnpm exec playwright install chromium`，浏览器装在项目内）
- 规则见 [tests/README.md](tests/README.md)

## 许可证

[Apache-2.0](LICENSE)。`knowledge/samples/cisco-ios-public/` 中的样本来自 Batfish 项目，同样使用 Apache-2.0，许可证随样本附带。
