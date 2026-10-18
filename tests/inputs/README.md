# 测试输入

全部是为测试编写的合成配置，不含真实设备信息；其中的密文、口令都是虚构的。

| 文件 | 用途 | 使用者 |
|---|---|---|
| `configs/huawei/basic.cfg` | 华为 VRP 配置：密文、明文口令、团体字、密钥块、公网与私网 IP、葡语与中文描述，以及容易误判的行（ssh server cipher、community complexity-check、password-force-change） | 单元测试 `test_sanitize.py`；CLI 用例 `sanitize-file`、`import-dir`；API 用例 `import-upload` |
| `configs/cisco/basic.cfg` | Cisco IOS 配置：enable secret、username secret、7 型口令、SNMP 团体字、vty 明文口令、VRF、BGP | 单元测试 `test_sanitize.py`；CLI 用例 `import-dir` |
| `configs/bad/empty.cfg` | 空文件（边界输入） | CLI 用例 `import-dir` |
| `configs/bad/notes.txt` | 不是路由器配置（错误输入：无法识别厂商） | CLI 用例 `import-dir`；API 用例 `import-upload` |
| `configs/check/huawei-issues.cfg` | 华为配置，故意包含各类检查问题：悬空引用、孤儿与级联孤儿、名称只出现在未映射行中的策略、互斥（二层口配地址）、违反规则（对等体缺对端 AS、VRF 有 RD 无 RT / 有 RT 无 RD、绑定 VRF 无地址、聚合成员口有地址），以及不应误报的对象（只在 BGP 地址族中使用的 VRF、有 Vbdif 的桥域） | 单元测试 `test_checks.py`；CLI 用例 `check-*`、`cleanup-script` |
| `configs/check/cisco-issues.cfg` | Cisco 配置，同类问题的 Cisco 写法；route-map 的删除命令走兜底；被引用的前缀列表只有未映射的 description 行 | 单元测试 `test_checks.py`；CLI 用例 `check-filter`、`cleanup-out-file`；API 测试 `test_check_api.py` |
| `rules/bad/bad.yaml` | 故意写错的检查规则文件（路径不存在、级别不合法） | CLI 用例 `check-bad-rules`；API 测试 `test_check_api.py` |
| `compare/hw-pe.cfg`、`compare/cs-pe.cfg` | 内容相同的华为与 Cisco 小配置（VRF + RT、接口、环回口、VRF 静态路由），跨厂商对比时只有接口名不同 | CLI 用例 `compare-cross-vendor`、`compare-profile-override` 等 |
| `compare/ifmap.txt` | 跨厂商对比的接口映射表（两列文本：华为接口 → Cisco 接口） | CLI 用例 `compare-cross-vendor` |
