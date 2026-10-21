# 透网 LucidMesh 部署指南

本文说明四种可部署形式的安装、升级、卸载，以及改用 PostgreSQL、端口与防火墙、备份。所有形式都可以离线安装：包内自带 Python 运行时、全部依赖、已构建的界面和程序自带的知识库，目标机器不需要联网，也不需要安装 Python、Node 或 Git。

| 形式 | 文件（`dist/<版本>/`） | 适用 |
|---|---|---|
| Docker 镜像 + compose | `lmesh_<版本>_docker-image.tar.gz`、`lmesh_<版本>_docker-compose.tar.gz` | 已有 Docker 的 Linux 服务器 |
| Linux 离线安装包 | `lmesh_<版本>_linux-x86_64.tar.gz` | x86_64 Linux（glibc 2.28 以上，如 RHEL 8、Ubuntu 20.04、Debian 10 及更新），systemd 服务 |
| Windows 离线包 | `lmesh_<版本>_windows-x64.zip` | 解压即用，可注册为 Windows 服务 |
| Windows 安装程序 | `lmesh_<版本>_windows-x64_setup.exe` | 安装向导、开始菜单、卸载程序 |

每次构建还会生成 `lmesh_<版本>_SHA256SUMS.txt`，拷贝到目标机器后可用 `sha256sum -c`（Linux）或 `Get-FileHash`（Windows）核对。

## 共同约定

- **默认监听 `0.0.0.0:9090`**，局域网可访问。只允许本机访问时，在向导或 `config/config.toml` 中把 `[server] host` 改为 `127.0.0.1`。
- **首次运行**：没有 `config/config.toml` 时，启动后用浏览器打开 `http://<主机>:9090` 按向导完成配置（界面语言、监听地址、数据库、API 令牌、第一个管理员、AI 接口可跳过）；也可以在命令行运行 `lmesh setup`。API 令牌只在完成配置时显示一次，请妥善保存；令牌和密码不写入日志。
- **目录**：配置 `config/`、数据 `data/`（SQLite 数据库 `data/lmesh.db`、运行时知识库 `data/knowledge/`）、日志 `logs/`（按日期轮转，保留 14 天），都在程序目录内（Docker 中是卷）。
- **配置优先级**：环境变量 `LMESH_<分组>__<名称>`（例如 `LMESH_SERVER__PORT=9091`）> `config/config.toml` > 默认值。
- **数据库**：默认 SQLite，不需要额外安装；可改用 PostgreSQL（见下文）。启动时自动执行数据库迁移，也可手动运行 `lmesh db upgrade`。

## Docker

### 安装

```bash
# 1. 导入镜像（离线）
docker load -i lmesh_0.9.0_docker-image.tar.gz        # 得到 lmesh:0.9.0
# 2. 解压 compose 文件
tar xzf lmesh_0.9.0_docker-compose.tar.gz && cd lmesh-0.9.0-docker
cp .env.example .env                                   # 按需修改 LMESH_PORT 等
# 3a. SQLite（默认）
docker compose up -d
# 3b. 或者 PostgreSQL：先把 .env 里的 POSTGRES_PASSWORD 改成自己的强密码
docker compose -f compose.postgres.yaml up -d
```

PostgreSQL 版用到 `postgres:17-alpine` 镜像，离线机器需要事先 `docker save postgres:17-alpine` 再导入。

- 镜像以非 root 用户（uid 10001）运行，带健康检查（`/api/v1/health`），`docker ps` 中显示 healthy。
- 数据、配置、日志是命名卷 `<项目名>_lmesh-data`、`_lmesh-config`、`_lmesh-logs`（容器内 `/app/data`、`/app/config`、`/app/logs`）；PostgreSQL 数据在 `_lmesh-pgdata`。改用宿主机目录时，先 `chown -R 10001:10001 <目录>`。
- `.env` 里有数据库密码，不要提交到代码仓库或发给别人；`POSTGRES_PASSWORD` 只用字母、数字、`-`、`_`，避免需要 URL 转义。
- 命令行：`docker compose exec lmesh lmesh status`。想在命令行完成首次配置而不用网页向导时，在 `up` 之前运行 `docker compose run --rm lmesh lmesh setup`（PostgreSQL 版加 `-f compose.postgres.yaml`）；服务已在运行时同一端口被占用，命令行向导会报“端口已被占用”。环境变量提供的数据库连接串（含密码）不会写进 `config.toml`。
- 日志：`docker compose logs -f lmesh`，以及卷里的 `logs/`。

### 升级

```bash
docker load -i lmesh_<新版本>_docker-image.tar.gz
# 修改 .env 中的 LMESH_VERSION=<新版本>
docker compose up -d          # PostgreSQL 版加 -f compose.postgres.yaml
```

容器启动时自动迁移数据库，并把新版本自带的知识库合并进运行时知识库（见“升级时知识库如何合并”）。升级前建议先备份（见“备份”）。

### 卸载

`docker compose down` 停止并删除容器，卷保留；连同数据一起删除用 `docker compose down -v`。最后可 `docker image rm lmesh:<版本>`。

## Linux 离线安装包

### 安装

```bash
tar xzf lmesh_0.9.0_linux-x86_64.tar.gz && cd lmesh-0.9.0
sudo ./install.sh --user lmesh --create-user           # 装到 /opt/lmesh，注册并启动 systemd 服务 lmesh
```

`install.sh` 的选项：

| 选项 | 作用 |
|---|---|
| `--prefix DIR` | 安装目录，默认 `/opt/lmesh`；不用 root 时指定自己有写权限的目录（例如 `~/.local/opt/lmesh`） |
| `--user NAME` / `--create-user` | 以专用系统用户运行服务（`--create-user` 在用户不存在时创建，不能登录）；不给时用当前用户 |
| `--no-systemd` | 不注册 systemd 服务（默认 root 且有 systemd 时注册） |
| `--no-link` | 不建立 `/usr/local/bin/lmesh` 命令链接 |
| `--setup` | 安装后在命令行完成首次配置（`lmesh setup`），不加时在浏览器中完成向导 |
| `--yes` | 不提问 |
| `--dry-run` | 只列出将要执行的操作（含 systemd 单元内容），不做改动 |

安装后：`systemctl status lmesh`、`journalctl -u lmesh`，日志也在 `/opt/lmesh/logs/`。不想安装时，也可以在解压目录直接运行 `./start.sh`（前台运行，配置与数据写在解压目录内）。

### 升级

解压新版本的安装包，再运行一次 `sudo ./install.sh`（参数与首次相同）。脚本识别已安装的版本后按升级处理：

1. 停止服务；
2. 备份 SQLite 数据库到 `backup/lmesh-<旧版本>-<时间>.db`，配置打包到 `backup/config-<旧版本>-<时间>.tar.gz`（PostgreSQL 请另行 `pg_dump`）；
3. 替换程序文件（`runtime/`、`src/`、`knowledge/` 等），保留 `config/`、`data/`、`logs/`、`backup/`；
4. 执行数据库迁移 `lmesh db upgrade`；
5. 合并新版本自带的知识库 `lmesh kb upgrade`；
6. 启动服务。

同一版本再次运行时询问是否修复安装；安装比已装版本旧的版本时提示降级风险。需要回到旧版本时：用旧版本的安装包重新运行 `install.sh`，再把 `backup/` 里对应的数据库文件复制回 `data/lmesh.db`。

### 卸载

```bash
sudo /opt/lmesh/uninstall.sh            # 询问是否保留配置与数据（默认保留）
sudo /opt/lmesh/uninstall.sh --purge --yes   # 连同配置与数据全部删除
```

注册了 systemd 服务时先停止并移除；创建的系统用户不删除，需要时自行 `userdel lmesh`。

## Windows 离线包（zip）

### 安装与运行

解压到任意目录（路径中最好不含空格以外的特殊字符），双击 `start.bat`，再用浏览器打开 `http://127.0.0.1:9090` 完成向导。`start.bat --setup` 在命令行里配置，`start.bat --check` 只做检查，`start.bat --port 9091` 临时换端口。命令行：`lmesh.bat <命令>`。

### 注册为 Windows 服务

右键“以管理员身份运行” `service-install.bat`（不是管理员时会弹出 UAC 请求）。服务名 `LucidMesh`，开机自动启动，崩溃后自动重启；用 `services.msc` 或 `sc start|stop LucidMesh` 管理；`service-uninstall.bat` 移除服务（不删除程序与数据）。服务包装器是包内的 `service\lmesh-service.exe`，即 [WinSW](https://github.com/winsw/winsw) 2.12（MIT 许可证，见 `service\WinSW-LICENSE.txt`），需要 .NET Framework 4.6.1 以上（Windows 10 / 11 自带）。服务以 LocalSystem 身份运行，包装器输出写在 `logs\lmesh-service.*.log`。

### 升级与卸载

升级：停止 LucidMesh（服务用 `sc stop LucidMesh`），把新版本解压到新目录，把旧目录的 `config\`、`data\`、`logs\` 复制过去，运行一次 `start.bat`（自动迁移数据库、合并知识库）；注册过服务时在新目录重新运行 `service-install.bat`。卸载：先 `service-uninstall.bat`（如注册过），再删除目录。

## Windows 安装程序（.exe）

- 双击运行，选择语言（中文 / English / Português (Brasil)）→ 安装目录（默认 `%LOCALAPPDATA%\Programs\LucidMesh`，不需要管理员权限）→ 组件：程序（必选）、开始菜单快捷方式、桌面快捷方式、注册为 Windows 服务（会请求管理员权限）。
- 静默安装：`lmesh_<版本>_windows-x64_setup.exe /S /D=D:\Apps\LucidMesh`（`/D` 必须放最后、不加引号）。
- **升级**：直接运行新版本的安装程序。会先停止从安装目录运行的 LucidMesh（服务需要管理员权限才能停止，必要时先手动 `sc stop LucidMesh`），把 SQLite 数据库备份到 `backup\lmesh-<旧版本>.db`，替换程序文件，保留 `config\`、`data\`、`logs\`，然后执行数据库迁移和知识库合并。同一版本询问是否修复。
- **卸载**：开始菜单“卸载 LucidMesh”或“设置 → 应用”。注册过服务时先移除服务；询问是否保留配置与数据（静默卸载 `uninstall.exe /S` 时保留）。
- 安装程序由 NSIS 3.11 生成；构建用的 NSIS 是放在项目 `.toolchain/nsis/` 的便携版，不安装到系统。

## 升级时知识库如何合并

程序自带的知识库（程序目录的 `knowledge/`）随版本更新；首次启动时它被复制到运行时知识库 `data/knowledge/`（一个独立的 Git 仓库，知识库管理界面、审核、`kb map` 等的修改都提交在那里）。升级后两者需要合并，规则如下：

- 运行时知识库仓库里有一个 `builtin` 分支：首次复制时把自带知识库的快照提交到这个分支作为基准；之后每个版本合并时把新的自带知识库快照提交到该分支（提交信息含程序版本）。
- 合并按三方比较，比较的是 Git 历史与文件内容，不看文件时间：
  - 用户没改过的文件（与上一次自带快照相同）：直接采用新版本，包括新增和删除；
  - 只有用户改过、新版本没变的文件：保留用户版本；
  - 双方都改了同一文件：**不自动覆盖**，保留用户版本，把冲突送进审核队列（类型“冲突”，来源 `kb-upgrade`），由维护员在审核页面选用新版本（可先编辑）或保留当前版本；新版本删除了而用户改过的文件，选用新版本即删除。同一文件已有待审的升级冲突时，更新那一条。
- 合并后提交一次，并记一条知识库发布记录（在最新发布号上加一个修订号，说明里记下升级前的提交）。回滚：`lmesh kb upgrade --rollback` 把知识库恢复到升级前的内容（再提交一次，历史保留）；回滚后不会在下次启动时再自动合并。
- **旧安装的首次升级**（运行时知识库还没有 `builtin` 分支，无法知道上一个自带版本）：采用保守做法，与本次自带版本不同的文件（包括用户那里缺少的自带文件）全部当作冲突送审核；只在用户知识库里有的文件保留。之后的升级就有了基准。
- 何时合并：`lmesh serve` 启动时检测到自带知识库变化就自动合并（失败不影响启动，可稍后重试）；`install.sh` 与 Windows 安装程序升级后也会执行。手动：`lmesh kb upgrade --dry-run` 预览将采用、冲突、保留的文件，`lmesh kb upgrade` 执行。
- 检查项目规则、渲染、变更等直接读程序自带目录的内容，随程序一起升级，不需要合并。

## 改用 PostgreSQL

1. 准备数据库：`CREATE USER lmesh WITH PASSWORD '<密码>'; CREATE DATABASE lmesh OWNER lmesh;`（PostgreSQL 14 以上）。
2. 在向导的数据库一项，或 `config/config.toml` 中填写：

   ```toml
   [database]
   url = "postgresql+psycopg://lmesh:<密码>@<主机>:5432/lmesh"
   ```

   也可以不写进文件，改用环境变量 `LMESH_DATABASE__URL`（Docker 的 PostgreSQL 版就是这样，systemd 可写在 `systemctl edit lmesh` 的 `Environment=` 中）。
3. 运行 `lmesh db upgrade` 建表（启动时也会自动执行），再启动。
4. 从 SQLite 切换时，原有数据不会自动搬过去；需要保留的配置与设备可重新导入，知识库在 `data/knowledge/` 中不受数据库切换影响。

## 端口与防火墙

- 默认端口 9090，改端口：向导、`config/config.toml` 的 `[server] port`、环境变量 `LMESH_SERVER__PORT`，或临时用 `start --port`；Docker 改 `.env` 的 `LMESH_PORT`（容器内仍是 9090）。
- 放行端口：
  - Ubuntu / Debian：`sudo ufw allow 9090/tcp`
  - RHEL / CentOS / openEuler：`sudo firewall-cmd --permanent --add-port=9090/tcp && sudo firewall-cmd --reload`
  - Windows（管理员）：`netsh advfirewall firewall add rule name="LucidMesh" dir=in action=allow protocol=TCP localport=9090`
- 只允许本机访问：`host = "127.0.0.1"`；Docker 把端口映射写成 `127.0.0.1:9090:9090`。需要 HTTPS 时在前面加反向代理（Nginx、Caddy 等）。

## 备份

需要备份的是 `config/`（配置与密钥文件 `secret.key`、`sanitize.key`，丢失后已加密的 AI Key 无法解密、脱敏结果不再一致）、`data/`（SQLite 数据库与运行时知识库）；`logs/` 按需。

- **SQLite**：先停止服务，再复制 `config/` 与 `data/`；不停服务时用 `sqlite3 data/lmesh.db ".backup backup/lmesh.db"`。
- **PostgreSQL**：`pg_dump -Fc -U lmesh lmesh > lmesh.dump`，恢复用 `pg_restore -d lmesh lmesh.dump`；另外备份 `config/` 与 `data/knowledge/`。
- **Docker**：

  ```bash
  docker compose stop lmesh
  docker run --rm -v lmesh_lmesh-data:/d -v lmesh_lmesh-config:/c -v "$PWD":/b busybox \
    tar czf /b/lmesh-backup.tar.gz -C / d c
  docker compose start lmesh
  # PostgreSQL 版另外：docker compose -f compose.postgres.yaml exec db pg_dump -Fc -U lmesh lmesh > lmesh.dump
  ```

- 恢复：停止服务，把备份的 `config/`、`data/` 放回原处（或解压回卷），再启动；启动时会按需迁移数据库。

## 构建发布包（开发者）

```bash
# Windows（生成 zip 与安装程序 exe）
scripts\build_release.bat 0.9.0
# Linux（生成离线安装包与 Docker 镜像）
scripts/build_release.sh 0.9.0
# 只生成部分：--targets win-zip | win-exe | linux | docker（可用逗号组合）；版本号可加后缀，如 0.9.0-rc
```

版本号必须与 `pyproject.toml` 一致（可加后缀）。构建会先按需构建前端，复制项目内 `.toolchain/` 中 uv 管理的 Python 运行时，按 `uv.lock` 把依赖装进运行时，再打包；NSIS（3.11 便携版）和 WinSW 按固定的 SHA256 下载到 `.toolchain/`。Docker 镜像多阶段构建（Node 构建前端、Python 运行），基础镜像版本固定；代理与镜像源用环境变量 `HTTP_PROXY`、`HTTPS_PROXY`、`UV_INDEX_URL`、`NPM_CONFIG_REGISTRY` 传入。产物只放在本机 `dist/<版本>/`（每个版本一个文件夹），发布前须经用户同意。
