# 测试输入

全部是为测试编写的合成配置，不含真实设备信息；其中的密文、口令都是虚构的。

| 文件 | 用途 | 使用者 |
|---|---|---|
| `configs/huawei/basic.cfg` | 华为 VRP 配置：密文、明文口令、团体字、密钥块、公网与私网 IP、葡语与中文描述，以及容易误判的行（ssh server cipher、community complexity-check、password-force-change） | 单元测试 `test_sanitize.py`；CLI 用例 `sanitize-file`、`import-dir`；API 用例 `import-upload` |
| `configs/cisco/basic.cfg` | Cisco IOS 配置：enable secret、username secret、7 型口令、SNMP 团体字、vty 明文口令、VRF、BGP | 单元测试 `test_sanitize.py`；CLI 用例 `import-dir` |
| `configs/bad/empty.cfg` | 空文件（边界输入） | CLI 用例 `import-dir`、`guard-empty` |
| `configs/bad/notes.txt` | 不是路由器配置（错误输入：无法识别厂商） | CLI 用例 `import-dir`；API 用例 `import-upload` |
| `configs/check/huawei-issues.cfg` | 华为配置，故意包含各类检查问题：悬空引用、孤儿与级联孤儿、名称只出现在未映射行中的策略、互斥（二层口配地址）、违反规则（对等体缺对端 AS、VRF 有 RD 无 RT / 有 RT 无 RD、绑定 VRF 无地址、聚合成员口有地址），以及不应误报的对象（只在 BGP 地址族中使用的 VRF、有 Vbdif 的桥域） | 单元测试 `test_checks.py`；CLI 用例 `check-*`、`cleanup-script` |
| `configs/check/cisco-issues.cfg` | Cisco 配置，同类问题的 Cisco 写法；route-map 的删除命令走兜底；被引用的前缀列表只有未映射的 description 行 | 单元测试 `test_checks.py`；CLI 用例 `check-filter`、`cleanup-out-file`；API 测试 `test_check_api.py` |
| `rules/bad/bad.yaml` | 故意写错的检查规则文件（路径不存在、级别不合法） | CLI 用例 `check-bad-rules`；API 测试 `test_check_api.py` |
| `rules/cross-device-bad.yaml` | 故意写错的跨设备一致性规则文件（链路类型不存在、伪线链路用了 Schema 路径） | CLI 用例 `consistency-bad-rules` |
| `compare/hw-pe.cfg`、`compare/cs-pe.cfg` | 内容相同的华为与 Cisco 小配置（VRF + RT、接口、环回口、VRF 静态路由），跨厂商对比时只有接口名不同；Cisco 侧显式写 `mpls label mode … per-vrf`，与华为缺省的 per-instance 标签分配一致（0.3.0 起两侧 Profile 都有这个缺省值，Cisco 缺省 per-prefix） | CLI 用例 `compare-cross-vendor`、`compare-profile-override` 等 |
| `compare/ifmap.txt` | 跨厂商对比的接口映射表（两列文本：华为接口 → Cisco 接口） | CLI 用例 `compare-cross-vendor` |
| `translate/cs-small.cfg` | Cisco 小配置（物理口 `mtu 1500` 等于华为缺省值、Port-channel 聚合口、缺省路由、`hostname` 原文行），配置翻译与含默认值渲染用 | 单元测试 `test_translate.py`；CLI 用例 `translate-*`、`render-with-defaults` |
| `translate/ifmap.yaml` | `cs-small.cfg` 翻译到华为的接口映射表（Port-channel1 → Eth-Trunk1） | CLI 用例 `translate-file` |
| `guard/atn-bad.cfg` | 要合并到 `knowledge/samples/change/atn-base.cfg` 的华为配置片段，故意包含被护栏拦截的问题：命令卡没有的写法（`vpn-target … both-direction`）、RD 与已有 VPN 实例重复、先配地址再绑定 VPN 实例（副作用顺序）、引用不存在的路由策略；描述含葡语字符 | CLI 用例 `guard-blocked`；单元测试 `test_ask_guard.py` 的同类片段 |
| `guard/atn-good.cfg` | 同一设备上能通过护栏的配置片段（绑定已有 VPN 实例后再配地址） | CLI 用例 `guard-passed-device`、`guard-empty-base` |
| `scripts/atn-change-order.txt` | 以 `knowledge/samples/change/atn-base.cfg` 为基线的华为变更脚本（REQ-031），故意包含：先配地址再绑定 VPN 实例（副作用丢值）、引用后面才创建的 VPN 实例（顺序）、取消不存在的前缀列表、在系统视图写 BGP 命令（视图错误） | 单元测试 `test_script_check.py`；CLI 用例 `script-check-*`；API 用例 `cp-*`（准备方式 `configured-fullkb-checkproj` 的脚本 1） |
| `scripts/atn-change-good.txt` | 同一变更按依赖顺序写好的版本（检查无错误；与上一份的差异是移动） | 单元测试、CLI 用例 `script-check-good`、`script-diff*` |
| `scripts/asr-change-order.txt` | 以 `asr920-base.cfg` 为基线的 Cisco 变更脚本：接口绑定的 VRF 在后面才定义 | 单元测试、CLI 用例 `script-check-reorder*` |
| `scripts/atn-full.cfg` | 基于 `atn-base.cfg` 的完整配置：改了接口描述、加了一行未识别命令（`ospf cost abc`） | 单元测试、CLI 用例 `script-check-full`；API 用例的脚本 2 |
