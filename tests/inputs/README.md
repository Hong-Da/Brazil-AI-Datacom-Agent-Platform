# 测试输入

全部是为测试编写的合成配置，不含真实设备信息；其中的密文、口令都是虚构的。

| 文件 | 用途 | 使用者 |
|---|---|---|
| `configs/huawei/basic.cfg` | 华为 VRP 配置：密文、明文口令、团体字、密钥块、公网与私网 IP、葡语与中文描述，以及容易误判的行（ssh server cipher、community complexity-check、password-force-change） | 单元测试 `test_sanitize.py`；CLI 用例 `sanitize-file`、`import-dir`；API 用例 `import-upload` |
| `configs/cisco/basic.cfg` | Cisco IOS 配置：enable secret、username secret、7 型口令、SNMP 团体字、vty 明文口令、VRF、BGP | 单元测试 `test_sanitize.py`；CLI 用例 `import-dir` |
| `configs/bad/empty.cfg` | 空文件（边界输入） | CLI 用例 `import-dir` |
| `configs/bad/notes.txt` | 不是路由器配置（错误输入：无法识别厂商） | CLI 用例 `import-dir`；API 用例 `import-upload` |
