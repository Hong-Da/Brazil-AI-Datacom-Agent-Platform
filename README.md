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

首次运行会进入 Web 配置向导。默认监听 `0.0.0.0:9000`，局域网内可访问。

## 使用方式

- Web 界面：浏览器打开 `http://<地址>:9000`
- CLI：`lmesh --help`，见 [docs/cli.md](docs/cli.md)
- 远程 API：前缀 `/api/v1`，令牌认证，见 [docs/api.md](docs/api.md)

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
├── config/
│   └── config.example.toml     配置示例（实际配置 config.toml 不入库）
├── src/lmesh/                  Python 包
│   ├── core/                   业务逻辑：config、logging、i18n、setup、status、store（数据库与迁移）
│   ├── cli/                    Typer 命令
│   ├── api/                    FastAPI 路由
│   ├── locales/                后端文案（zh-CN、en、pt-BR）
│   └── web/static/             前端构建产物（不入库，由 start 脚本构建）
├── frontend/                   Vue 3 + Vite 前端（package.json、pnpm-lock.yaml、.nvmrc、pnpm-workspace.yaml、src/）
├── knowledge/                  程序自带的知识库（M1-4 起）
│   ├── sources/                原始资料来源记录（M1-4 起）
│   ├── extractors/             各厂商文档的命令卡抽取规则（M1-5 起）
│   ├── commands/               命令卡（M1-5 起）
│   ├── schema/                 统一 Schema（M1-6 起）
│   ├── profiles/               厂商 + 版本 Profile（M1-4 起）
│   ├── templates/              配置模板（M3-4 起）
│   └── samples/                已脱敏的配置样本与往返期望结果（M1-3 起）
├── assets/brand/               Logo 与图标
├── docs/
│   ├── project-spec.md         项目规范
│   ├── cli.md / api.md         CLI 与远程 API 调用文档
│   └── openapi.json            API 定义（由 scripts/gen_docs.py 导出）
├── scripts/
│   ├── env.bat / env.sh        工具链与缓存位置，所有脚本先加载它
│   ├── version-status.sh       版本检查（SessionStart 钩子）
│   ├── ensure_node.py          准备项目内的 Node（只用于构建前端）
│   ├── build_frontend.py       按需构建前端
│   ├── run_tests.py            一键测试的实际逻辑
│   ├── gen_docs.py             从测试用例生成调用文档示例、导出 OpenAPI
│   ├── linux_sync.sh           开发辅助：把代码同步到 Linux 测试机
│   └── build_icons.py          从 logo.svg 导出图标
├── tests/                      测试（见 tests/README.md）
├── .claude/settings.json       SessionStart 钩子
├── data/ logs/ cache/ tmp/     运行时文件（不入库）
├── .toolchain/                 依赖缓存与项目内的 Python、Node（不入库）
└── dist/                       打包结果（不入库）
```

`DevelopDocs/` 是开发文档的本地仓库，不随主仓库发布。

## 测试

- Windows：`test.bat`；Linux：`./test.sh`
- 只运行某一类：`--unit` / `--cli` / `--api` / `--docs`
- 规则见 [tests/README.md](tests/README.md)
