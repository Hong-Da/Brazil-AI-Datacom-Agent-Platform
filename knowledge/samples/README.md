# 配置样本

往返测试（配置 → 图 → 配置）与命令频率统计用的配置样本。原始配置只保存在 `DevelopDocs/`（不入库）；放进这里的样本必须是已脱敏的，或本来就是公开的。

| 目录 | 来源 | 处理方式 | 说明 |
|---|---|---|---|
| `huawei-atn-v800r023/` | 用户提供的现网 ATN 配置（V800R023C00SPC500） | `lmesh sanitize --level strict --redact <运营商名> --redact <站点编码规则>`，并人工核对残留词 | 行数与原文一致（2266 行），行号可追溯；密文、口令、团体字、密钥块、全部 IP（前缀保持）、主机名、描述、用户名、网元 ID、SNMP 引擎 ID、运营商名称与站点编码都已替换 |
| `nokia-sros-classic-synthetic/` | 自编的 Nokia SR OS 25.10 Classic CLI 配置（M7-1 / M7-2 编写，M7-3 补业务） | 合成，不含真实设备信息（文档保留网段、私网地址，口令与团体字为 LMESH 占位符） | M7-3 起登记在总清单（Profile `nokia-sros-classic-7750-25.10`）；`tests/roundtrip/test_nokia_samples.py` 另外要求命令行都按卡的语法（含引号）原样重放 |
| `nokia-sros-md-synthetic/` | 自编的 Nokia SR OS 25.10 MD-CLI 配置（M7-4）：与 Classic 三份样本内容一一对应（`md-pe-basic` / `md-pe-services` / `md-pe-routing-mgmt`），另有 `md-pe-basic-flat`（`md-pe-basic` 的 info flat 格式） | 合成，不含真实设备信息；过了 `lmesh sanitize`：basic 级别只替换文档保留网段的地址（按公网处理），秘密、团体字已是 LMESH 占位符；样本保留原地址，便于与 Classic 版对照 | 登记在总清单（Profile `nokia-sros-md-7750-25.10`）；`tests/unit/test_nokia_md.py` 比较 Classic 版与 MD 版建出的图（列明允许的差异），并检查扁平格式与花括号格式建出的图相同 |
| `cisco-ios-public/` | Batfish 仓库（提交 cf100e56，Apache-2.0，见 `LICENSE-batfish-Apache-2.0.txt`） | 原样保留，未改动 | IOS 15.2 / 15.5 风格：BGP、peer-group、route-map、prefix-list、community-list、VRF、子接口；没有 ASR 920 特有写法（service instance、BDI、VPNv4），这部分在 M1-6 补充自编样本 |

Cisco ASR 920 配置指南中的示例版权归 Cisco，不是开源许可，只留在 `DevelopDocs/` 作内部参考，不放进本目录。

## 新增样本

1. 原始配置放在 `DevelopDocs/设备配置案例/` 下。
2. 运行 `lmesh sanitize <原文件> -o knowledge/samples/<Profile 名>/<名称>.cfg --level strict`；有客户名、站点编码等组织相关的词时，用 `--redact` 追加（可多次，支持正则）。
3. 人工检查：在输出中搜索原配置里的主机名、客户名、IP 段，确认没有残留。
4. 在上表登记来源与处理方式。
