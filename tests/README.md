# 测试说明

后端用 pytest，前端用 Vitest（单元，写在 `frontend/src/**/*.test.ts`）与 Playwright（端到端，放在 `frontend/e2e/`，依赖前端的 node_modules）。所有测试都能用根目录的 `test.bat` / `test.sh` 一键运行。

## 目录

```
tests/
├── README.md            本说明
├── conftest.py          公共夹具：临时配置、临时数据库（SQLite 与 PostgreSQL）、测试用令牌
├── inputs/              测试输入（入库，只读）
│   ├── README.md        每个输入文件的用途与来源
│   ├── configs/         小型配置片段（已脱敏），按厂商分子目录
│   ├── kb/              测试用的最小知识库
│   ├── docs/            命令参考页样例（用于抽取器测试）
│   ├── cli/             CLI 用例用到的文件
│   └── api/             API 用例的请求体与上传文件
├── expected/            期望输出：结构化 JSON 快照、渲染结果
├── cases/
│   ├── cli_cases.toml   CLI 用例，同时生成 docs/cli.md 的示例
│   └── api_cases.toml   API 用例，同时生成 docs/api.md 的示例
├── unit/                单元测试
├── cli/                 CLI 测试（启动子进程执行真实命令）
├── api/                 API 测试（离线用 TestClient，在线用 --live）
├── roundtrip/           往返回归：knowledge/samples/ 中全部样本“配置 → 图 → 配置”
├── docs/                文档测试
└── output/              运行时产生的文件（不入库）
```

目录随功能开发逐步创建，未开发的部分不建目录。

## 测试分类

| 标记 | 内容 |
|---|---|
| `unit` | `core` 的业务逻辑；配置加载（默认值、环境变量优先级）；三种语言文案的键是否齐全 |
| `cli` | 子进程执行 `cli.bat` / `cli.sh`：退出码、stdout（`--output json` 按字段检查）、出错时 stderr 有提示；至少一条用例分别用 `--lang zh-CN / en / pt-BR` 执行 |
| `api` | 每个接口至少一条正常用例和一条错误用例；需要认证的接口额外测无令牌和错误令牌 |
| `roundtrip` | 全部样本往返文本一致；功能域覆盖率不低于基准 |
| `e2e` | `frontend/e2e/*.spec.ts`：`scripts/e2e_server.py` 在 `tests/output/e2e-root` 建临时项目（全量知识库 + 样本）并启动服务，浏览器逐页操作；Windows 用系统 Edge，其他系统用项目内的 Playwright Chromium（`PLAYWRIGHT_BROWSERS_PATH`）。报告在 `tests/output/e2e-report/` |
| `docs` | 文档示例与用例数据一致、`docs/openapi.json` 最新、README 目录结构与实际一致、多语言键一致、相对链接有效 |
| `live` | 对运行中的实例执行 `live = true` 的 API 用例 |
| `pg` | 需要 PostgreSQL 的用例；没有可用的 PostgreSQL 时跳过并在结果中注明 |

## 测试输入规则

- 输入文件入库、只读；测试产生的文件写到 `tests/output/` 或临时目录。
- **不放真实设备配置**：配置样本必须先用 `lmesh sanitize` 脱敏，原始配置只留在 `DevelopDocs/`。
- 覆盖正常、边界（空文件、单行、超长行、特殊字符）、错误（格式错误、未知厂商）三类输入。
- 至少一份输入包含中文和葡萄牙语字符（ã、ç、é），例如接口描述。
- 单个文件尽量不超过 1 MB；固定时间与随机种子；文本为 UTF-8 无 BOM。
- `tests/inputs/README.md` 逐个说明文件的用途、来源和使用它的用例。

## 运行

| 命令 | 作用 |
|---|---|
| `test.bat` / `./test.sh` | 全部离线测试（后端 + 前端单元） |
| `--unit` / `--cli` / `--api` / `--docs` / `--roundtrip` / `--e2e` | 只运行某一类 |
| `--live --base-url <地址> --token <令牌>` | 在线 API 测试 |
| `--changed [REF]` | 增量测试：按改动的文件挑选类别（默认对比 HEAD，即未提交的改动；`--changed main` 对比分支分叉点），逐个文件打印去向 |
| `-n N` / `--serial` / `--max-workers N` | 后端测试的并行进程数；默认 CPU 核数、上限 16（也可用环境变量 `LMESH_TEST_MAX_WORKERS`）；`--serial` 即 `-n 0` |

结束时输出每类通过 / 失败 / 跳过数量，有失败时退出码非 0；报告写入 `tests/output/report.html` 与 `tests/output/junit.xml`（并行时由主进程汇总，统计与串行相同）。

**测试时机**：开发阶段完成后跑增量测试（`--changed`）；提交前加跑 `--e2e`；里程碑验收与打版本前在 Windows 与 Linux 上跑全量。

### 并行

- 后端用 pytest-xdist（`--dist worksteal`）。每个 worker 有自己的临时目录（`tmp/os/pytest-of-*/pytest-N/popen-gwK/`）。
- PostgreSQL：每个用例一个 schema，名字是 `t_<worker>_<随机串>`；SSH 隧道由主进程建一次、所有 worker 共用。
- 测试不监听端口（API 用 TestClient）；需要写文件的都写各自的 `tmp_root`，不写 `tests/output/`（只有主进程写报告）。
- 直接用 pytest 时：`python -m pytest -n 16 --dist worksteal`；串行就不加 `-n`。

### 增量测试的映射

`scripts/run_tests.py` 里的 `CHANGE_RULES`，按顺序取第一条匹配的规则，宁宽勿窄：

| 改动的路径 | 选中的类别 |
|---|---|
| `frontend/src/i18n/` | frontend、docs |
| `frontend/` | frontend（前端单元） |
| `src/lmesh/api/` | api、cli、docs |
| `src/lmesh/cli/` | cli、docs |
| `src/lmesh/core/` 的 parser、graph、canon、translate、change | unit、roundtrip（含翻译与变更回归） |
| `src/lmesh/core/` 的 kb、kbservice、renderer、roundtrip、graphstore、analysis、compare、migration、topology、sanitize、features、layers | unit、roundtrip、cli、api |
| `src/lmesh/core/` 的其他模块 | unit、cli、api |
| `src/lmesh/locales/` | unit、docs |
| `knowledge/` | unit、roundtrip |
| `tests/cases/` | cli、api、docs |
| `tests/<类别>/` | 该类别 |
| `scripts/gen_docs.py`、`docs/`、`*.md` | docs |
| 其他（`tests/conftest.py`、`pyproject.toml`、`uv.lock`、`src/lmesh/paths.py` 等） | 全部离线测试 |

另外有新增或删除的文件时加 docs（README 目录结构检查）。

### 知识库副本

- `tmp_root/knowledge`（程序自带的知识库）默认是链接，指向每个测试进程共用的只读副本（不带命令卡、带全部命令卡各一份，在 `tmp/os/pytest-of-*/…/kb-shared/`）。Windows 用目录联接，其他系统用符号链接；建不了链接时退回复制。
- 会写入 `tmp_root/knowledge` 的用例加 `@pytest.mark.kb_write`（CLI / API 用例在 toml 里写 `kb_write = true`），改为复制一份自己的。运行时知识库（`data/knowledge`，首次配置时复制）每个用例本来就是自己的，不受影响。
- 每个用例结束时比对共用副本的快照：被改动就恢复，并让该用例报错、提示加标记，后面的用例不受影响。
- `LMESH_TEST_KB_COPY=1` 时每个用例都复制（排查问题时用）。

## Linux 开发与测试

- 机器：地址写在 `config/linux.env`（`LMESH_LINUX_HOST=用户@地址`，不入库），SSH 端口 22，本项目专用密钥（`LMESH_LINUX_KEY`，默认 `~/.ssh/lmesh_dev_ed25519`）；工作目录 `~/lmesh/`。密码不记录在任何文件中。
- 这台机器必须是可以随意改动的测试机或虚拟机，不能是生产服务器。所有操作限定在工作目录内；需要 sudo、安装系统软件、开放端口时先说明并征得同意。
- 开发方式：本机编写，同步到 Linux 运行。同步时排除 `.venv/`、`.toolchain/`、`frontend/node_modules/`、`data/`、`logs/`、`dist/`、`tests/output/`、`config/config.toml`、`DevelopDocs/`；Linux 上的 `config/`、`data/` 不被覆盖。
- 端口：默认 9090；Linux 测试机上 9090 已被其他 Docker 服务占用，在 Linux 上运行时临时用 9091（不改默认值）。
- 查看 Web 界面：SSH 端口转发 `ssh -i "$LMESH_LINUX_KEY" -N -L 9091:127.0.0.1:9091 "$LMESH_LINUX_HOST"`，本机打开 `http://127.0.0.1:9091`。
- 测试时机：每个里程碑结束、阶段三全量测试、用户要求时。步骤：同步代码 → `./start.sh --check` → `./test.sh` → 启动服务跑 `--live` → 取回 `tests/output/` 报告；与 Windows 结果不一致的用例单独列出。
