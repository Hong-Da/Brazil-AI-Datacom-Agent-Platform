透网 LucidMesh —— Linux 离线安装包（x86_64）
=============================================

包内自带 Python 运行时与全部依赖、已构建的界面和知识库，不需要联网。

安装为系统服务（推荐）：
  sudo ./install.sh --user lmesh --create-user
  然后用浏览器打开 http://<本机地址>:9090 完成配置向导（或安装时加 --setup 在命令行配置）
不安装，直接在本目录运行：./start.sh
命令行：bin/lmesh <命令>（安装后为 lmesh）
升级：解压新版本的安装包，再运行一次 sudo ./install.sh（配置与数据保留，自动迁移数据库、合并知识库）
卸载：sudo /opt/lmesh/uninstall.sh（默认保留配置与数据；--purge 全部删除）
详见 docs/deploy.md

LucidMesh — Linux offline package (x86_64). Install: sudo ./install.sh --user lmesh --create-user,
then open http://<host>:9090 for the setup wizard. Run in place: ./start.sh. Details: docs/deploy.md

LucidMesh — pacote offline para Linux (x86_64). Instalação: sudo ./install.sh --user lmesh --create-user,
depois abra http://<host>:9090 para o assistente. Executar no local: ./start.sh. Detalhes: docs/deploy.md
