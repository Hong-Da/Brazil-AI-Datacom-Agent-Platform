透网 LucidMesh —— Windows 离线包
=================================

运行：双击 start.bat。首次启动后用浏览器打开 http://127.0.0.1:9090 完成配置向导
（也可以运行 start.bat --setup 在命令行里配置）。包内自带 Python 运行时与全部依赖，不需要联网。

- 命令行：lmesh.bat <命令>，例如 lmesh.bat status、lmesh.bat --help
- 注册为 Windows 服务：右键“以管理员身份运行” service-install.bat；移除用 service-uninstall.bat
  （服务包装器 service\lmesh-service.exe 是 WinSW 2.12，MIT 许可证，见 service\WinSW-LICENSE.txt）
- 配置 config\、数据 data\、日志 logs\ 都在本目录内；备份时复制这三个目录
- 升级、改用 PostgreSQL、端口与防火墙：见 docs\deploy.md

LucidMesh — Windows offline package
Run start.bat, then open http://127.0.0.1:9090 to finish the setup wizard. No internet needed.
CLI: lmesh.bat <command>. Windows service: run service-install.bat as administrator. Details: docs\deploy.md

LucidMesh — pacote offline para Windows
Execute start.bat e abra http://127.0.0.1:9090 para concluir o assistente. Não precisa de internet.
CLI: lmesh.bat <comando>. Serviço do Windows: execute service-install.bat como administrador. Detalhes: docs\deploy.md
