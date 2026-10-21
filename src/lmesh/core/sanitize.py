"""配置脱敏：替换密码、密文、团体字、密钥、IP、主机名等，保持引用关系与行号不变。

- 逐行替换，行数不变，原始行号仍然有效。
- 同一个 Sanitizer 实例内，同一原值总是替换成同一个值（一批文件共用一个实例，跨设备的引用关系也保持）。
- IP 使用前缀保持的伪随机映射（思路同 Crypto-PAn）：同一网段的地址替换后仍在同一网段；私网地址替换后仍是私网；
  掩码、反掩码、0.0.0.0/8、回环、组播地址不替换。
- 两档强度：basic 只替换秘密与公网 IP；strict 另外替换全部 IP、主机名、描述、用户名、网元 ID（入库样本用）。
- 结束时自检：输出中不能残留任何被替换的秘密原值。
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import ipaddress
import re
import secrets
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

Level = Literal["basic", "strict"]
CATEGORIES = ("secret", "community", "key_block", "ip", "hostname", "description", "user", "identifier", "custom")


@dataclass
class Replacement:
    line: int  # 1 开始
    category: str
    original: str
    replacement: str


@dataclass
class SanitizeResult:
    text: str
    vendor: str | None
    replacements: list[Replacement] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return dict(Counter(r.category for r in self.replacements))

    def public_report(self) -> list[dict[str, object]]:
        """不含原值的报告（可以写日志、返回给 API）。"""
        return [{"line": r.line, "category": r.category, "replacement": r.replacement} for r in self.replacements]


# ---------- 厂商与版本识别 ----------

_HUAWEI_HINTS = [
    re.compile(p, re.M)
    for p in (r"^sysname \S", r"^#$", r"^ ?ip vpn-instance ", r"^return$", r"V\d{3}R\d{3}C\d{2}", r"^ ?undo ")
]
_CISCO_HINTS = [
    re.compile(p, re.M)
    for p in (r"^hostname \S", r"^!$", r"^version \d+\.\d+", r"^end$", r"^ ?no ", r"^vrf definition ", r"^router bgp ")
]


# Nokia SR OS：配置文件头 “# TiMOS-B-25.10.R1 …” 一出现即可确定；没有文件头时看 Classic / MD-CLI 的版式特征
_NOKIA_HEADER = re.compile(r"^# TiMOS-", re.M)
_NOKIA_HINTS = [
    re.compile(p, re.M)
    for p in (r"^exit all$", r'^\s*echo "', r"^#-{20,}$", r"^configure \{", r"^/configure ", r'^\s+router "?Base"?')
]


def detect_vendor(text: str) -> str | None:
    """按配置特征识别厂商：huawei / cisco / nokia；分不出时返回 None。"""
    if _NOKIA_HEADER.search(text):
        return "nokia"
    h = sum(bool(p.search(text)) for p in _HUAWEI_HINTS)
    c = sum(bool(p.search(text)) for p in _CISCO_HINTS)
    n = sum(bool(p.search(text)) for p in _NOKIA_HINTS)
    if n >= 2 and n > max(h, c):
        return "nokia"
    if h == c:
        return None
    return "huawei" if h > c else "cisco"


def detect_format(text: str, vendor: str | None) -> str:
    """同一厂商的配置格式：Nokia 的 classic（缩进 + exit）/ md（MD-CLI 花括号或 /configure 扁平路径）；其他厂商为空。"""
    if vendor != "nokia":
        return ""
    if re.search(r"^(?:configure \{|/configure )", text, re.M):
        return "md"
    # M7-4：Classic 的块总以 exit 结束；没有 exit、有花括号块（info）或一行写完整路径（info flat）的是 MD-CLI
    if re.search(r"^\s*exit(?: all)?\s*$", text, re.M):
        return "classic"
    if re.search(r"\{\s*$|^\s*\}\s*$", text, re.M) or _MD_FLAT.search(text):
        return "md"
    return "classic"


# MD-CLI info flat（相对 configure 的完整路径，一行写完）：router "Base" interface …、port 1/1/1 admin-state …
_MD_FLAT = re.compile(r'^(?:router "[^"]+"|port \S+|lag "[^"]+"|service \S+|system|log|policy-options) \S', re.M)


def family_of(vendor: str, fmt: str) -> str | None:
    """同一厂商有多种配置格式时，按格式确定平台族（Nokia：classic / md）；其他厂商返回 None（不限定）。"""
    return f"nokia-sros-{fmt or 'classic'}" if vendor == "nokia" else None


_HUAWEI_VERSION = re.compile(r"(V\d{3}R\d{3}C\d{2}(?:SPC\d{3})?)")
_CISCO_VERSION = re.compile(r"^version (\d+\.\d+\S*)", re.M)
_NOKIA_VERSION = re.compile(r"TiMOS-[A-Z]+-(\d+\.\d+\.R\d+)")


def detect_version(text: str, vendor: str | None) -> str:
    pat = {"huawei": _HUAWEI_VERSION, "cisco": _CISCO_VERSION, "nokia": _NOKIA_VERSION}.get(vendor or "")
    m = pat.search(text) if pat else None
    return m.group(1) if m else ""


# ---------- 规则 ----------

_IPV4 = re.compile(r"(?<![\w.])((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})(?![\w.])")
_HW_CIPHER = re.compile(r"%\^%#.*?%\^%#|%@%@.*?%@%@|%\$%\$.*?%\$%\$")
_KEY_BLOCK_BEGIN = re.compile(
    r"^\s*(public-key-code begin|crypto pki certificate chain|certificate (?:self-signed|ca) \S+)", re.I
)
_KEY_BLOCK_END = re.compile(r"^\s*(public-key-code end|quit)\s*$", re.I)
_HEX_LINE = re.compile(r"^(\s*)([0-9A-Fa-f]{2,}(?:\s+[0-9A-Fa-f]{2,})*)\s*$")

# 整行不处理秘密规则的行：算法列表等（例如 ssh server cipher aes256_gcm …）
_SECRET_EXEMPT = re.compile(r"^\s*ssh (?:server|client) (?:cipher|hmac|key-exchange|publickey)\b", re.I)
_NOT_A_SECRET = {"cipher", "simple", "plain", "irreversible-cipher", "password", "md5", "sha", "disable", "enable"}

# (模式, 分类)：分组 v 是要替换的值
_SECRET_RULES: list[tuple[re.Pattern[str], str]] = [
    # 带编码标记的写法（华为与 Cisco 通用）：password cipher X / secret 5 X / key 7 X / authentication-key simple X
    (
        re.compile(
            r"(?<![\w-])(?:password|secret|key|key-string|authentication-key|shared-key|pre-shared-key)\s+"
            r"(?:cipher|simple|plain|irreversible-cipher|[05789])\s+(?P<v>\S+)",
            re.I,
        ),
        "secret",
    ),
    # Cisco：ip ospf message-digest-key 1 md5 [7] X、ntp authentication-key 1 md5 X [7]（密钥写在 md5 之后）
    (re.compile(r"\bmessage-digest-key\s+\d+\s+md5\s+(?:[057]\s+)?(?P<v>\S+)", re.I), "secret"),
    (re.compile(r"\bntp authentication-key\s+\d+\s+md5\s+(?P<v>\S+)", re.I), "secret"),
    # 华为：cipher X / irreversible-cipher X（例如 authentication-mode simple cipher X）
    (re.compile(r"(?<![\w-])(?:cipher|irreversible-cipher)\s+(?P<v>\S+)", re.I), "secret"),
    # Cisco：整行只有 password X / enable password X（line vty 下的明文口令）
    (re.compile(r"^\s*(?:enable\s+)?password\s+(?P<v>\S+)\s*$", re.I), "secret"),
    # 口令策略里的禁用词（往往就是常用的默认口令）
    (re.compile(r"\bforbidden word\s+(?P<v>\S+)", re.I), "secret"),
    (re.compile(r"\bsnmp-server community\s+(?P<v>\S+)", re.I), "community"),
    (re.compile(r"\bsnmp-agent community\s+(?:read|write)\s+(?P<v>\S+)", re.I), "community"),
]
# Nokia SR OS：值多写在引号里（可含空格），密文后面跟 hash / hash2 / crypto 标记；只在识别为 nokia 的配置上使用
_NOKIA_SECRET_RULES: list[tuple[re.Pattern[str], str]] = [
    # password "…" [hash|hash2]、authentication-key "…" hash2、secret "…" hash2、priv-key / auth-key、message-digest-key 1 md5 "…"
    (re.compile(r'(?<![\w-])(?:[\w-]*-)?(?:password|key|secret)(?:\s+\d+\s+md5)?\s+"(?P<v>[^"]*)"', re.I), "secret"),
    (
        re.compile(r"(?<![\w-])(?:[\w-]*-)?(?:password|key|secret)\s+(?P<v>[^\s\"]+)\s+(?:hash2?|crypto)\b", re.I),
        "secret",
    ),
    # SNMP 团体字：community "…" r / rw / rwa / mgmt / vpls-mgmt（策略里的 community "名称" members … 不是秘密）
    (re.compile(r'^\s*community\s+"(?P<v>[^"]*)"\s+(?:r|rw|rwa|mgmt|vpls-mgmt)\b', re.I), "community"),
    # MD-CLI 扁平格式（M7-4）：… security snmp community "…" access-permissions r / { }
    (re.compile(r'\bsnmp\s+(?:usm-)?community\s+"(?P<v>[^"]*)"', re.I), "community"),
]
# 认不出厂商时追加的通用规则（REQ-044）：关键字后引号里的值（例如 encrypted-password "…"、pre-shared-key "…"）
_GENERIC_EXTRA: list[tuple[re.Pattern[str], str]] = _NOKIA_SECRET_RULES[:2]
# MD-CLI 花括号格式（M7-4）：security snmp { community "…" { … } } 里的团体字（policy-options 下的 community "名称" 不是秘密，
# 按所在的块区分）
_NOKIA_MD_COMMUNITY = re.compile(r'^\s*(?:usm-)?community\s+"(?P<v>[^"]*)"', re.I)
_NOKIA_USER_DEFS = [
    re.compile(r'^\s*user\s+"(?P<v>[^"]+)"', re.I),
    re.compile(r'\blocal-user\s+user\s+"(?P<v>[^"]+)"', re.I),  # MD-CLI 扁平格式（M7-4）
    re.compile(r"^# Generated .*\bby\s+(?P<v>[\w.\-]+)\s+from\b", re.I),  # 文件头 “# Generated … by admin from Console”
]
_HOSTNAME = re.compile(r"^\s*(?:sysname|hostname)\s+(?P<v>\S+)", re.I)
_NOKIA_HOSTNAME = re.compile(r'^ {8}name\s+"?(?P<v>[^"\s]+)"?\s*$')  # configure > system > name "PE1"
# MD-CLI 扁平格式（M7-4）：system name "PE1"、/configure system name "PE1"
_NOKIA_HOSTNAME_FLAT = re.compile(r'^(?:/configure\s+)?system\s+name\s+"?(?P<v>[^"\s]+)"?\s*$')
# 行首的 description，以及行内的 … description X（例如 OSPF 的 network … description X）
_DESCRIPTION = re.compile(r"^(?P<lead>(?:\s*|.*?\s)(?:description|desc)\s+)(?P<v>.+?)\s*$", re.I)
# 用户名只在定义它的行里替换（全局替换会误伤 stp root 之类的关键字）
_USER_DEFS = [
    re.compile(r"^\s*local-user\s+(?P<v>\S+)", re.I),
    re.compile(r"^\s*ssh user\s+(?P<v>\S+)", re.I),
    re.compile(r"^\s*username\s+(?P<v>\S+)", re.I),
    re.compile(r"^!.*\bby\s+(?P<v>[\w.\-]+)\s*$", re.I),  # 华为配置头“… by 用户名”
]
_IDENTIFIERS = [
    re.compile(r"^\s*set neid\s+(?P<v>\S+)", re.I),
    re.compile(r"\bserial-number\s+(?P<v>\S+)", re.I),
    re.compile(r"\bhost-name\s+(?P<v>\S+)", re.I),
    re.compile(r"\blocal-engineid\s+(?P<v>\S+)", re.I),
    re.compile(r"\bengineID\s+(?:local\s+)?(?P<v>\S+)", re.I),
]

_SKIP_IP = (ipaddress.ip_network("0.0.0.0/8"), ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("224.0.0.0/3"))
_PRIVATE = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
)


def _is_netmask(ip: ipaddress.IPv4Address) -> bool:
    """首字节为 255 的连续掩码（255.255.255.0 等）。反掩码以 0 开头，已在 0.0.0.0/8 中跳过。"""
    v = int(ip)
    inv = (~v) & 0xFFFFFFFF
    return v >> 24 == 255 and (inv & (inv + 1)) == 0


class Sanitizer:
    def __init__(self, level: Level = "basic", key: bytes | None = None, redact: list[str] | None = None):
        """redact：组织相关的词或正则（客户名、站点编码规则等），任何强度下都全文替换成 ORG-xxxxxx。"""
        self.level = level
        self.key = key or secrets.token_bytes(32)
        self.redact = [re.compile(r, re.I) for r in (redact or [])]
        self._maps: dict[str, dict[str, str]] = {c: {} for c in CATEGORIES}
        self._snmp_ctx = False  # 当前行在 MD-CLI 的 snmp { … } 块里（M7-4）

    def _token(self, category: str, original: str, fmt: str) -> str:
        """占位符由密钥哈希得出：同一密钥下，同一原值在任何一批文件里都替换成同一个值。"""
        m = self._maps[category]
        if original not in m:
            h = hmac.new(self.key, f"{category}|{original}".encode(), hashlib.sha256).hexdigest()[:6].upper()
            m[original] = fmt.format(h=h)
        return m[original]

    def anon_ip(self, s: str) -> str:
        cached = self._maps["ip"].get(s)
        if cached:
            return cached
        ip = ipaddress.IPv4Address(s)
        if _is_netmask(ip) or any(ip in n for n in _SKIP_IP):
            return s
        private = next((n for n in _PRIVATE if ip in n), None)
        if self.level == "basic" and private is not None:
            return s
        keep = private.prefixlen if private is not None else 0
        bits = format(int(ip), "032b")
        out = list(bits[:keep])
        for i in range(keep, 32):
            # 第 i 位是否翻转只取决于前 i 位：前缀相同的地址替换后前缀仍相同
            flip = hmac.new(self.key, bits[:i].encode(), hashlib.sha256).digest()[0] & 1
            out.append(str(int(bits[i]) ^ flip))
        new = str(ipaddress.IPv4Address(int("".join(out), 2)))
        self._maps["ip"][s] = new
        return new

    def mapping(self) -> dict[str, dict[str, str]]:
        """原值 → 替换值（敏感！只在本机使用，不要写日志或入库）。"""
        return {k: dict(v) for k, v in self._maps.items() if v}

    def sanitize(self, text: str) -> SanitizeResult:
        vendor = detect_vendor(text)
        lines = text.split("\n")
        reps: list[Replacement] = []
        strict = self.level == "strict"

        # 主机名在全文中替换（对端设备名也常出现在描述等处）
        hostnames: dict[str, str] = {}
        if strict:
            host_pat = _NOKIA_HOSTNAME if vendor == "nokia" else _HOSTNAME
            for ln in lines:
                m = host_pat.match(ln) or (_NOKIA_HOSTNAME_FLAT.match(ln) if vendor == "nokia" else None)
                if m:
                    hostnames[m.group("v")] = self._token("hostname", m.group("v"), "DEVICE-{h}")
        host_re = (
            re.compile(
                r"(?<![A-Za-z0-9])("
                + "|".join(map(re.escape, sorted(hostnames, key=len, reverse=True)))
                + r")(?![A-Za-z0-9])"
            )
            if hostnames
            else None
        )

        in_block = False
        heads: list[str] = []  # MD-CLI 花括号块的块头（M7-4：区分 SNMP 团体字与策略里的 community）
        for idx, line in enumerate(lines, start=1):
            if vendor == "nokia":
                st = line.strip()
                self._snmp_ctx = "snmp" in heads
                if st == "}" and heads:
                    heads.pop()
                elif st.endswith("{") and not st.endswith("{ }"):
                    heads.append((st[:-1].split() or [""])[0])
            if in_block:
                if _KEY_BLOCK_END.match(line):
                    in_block = False
                else:
                    mh = _HEX_LINE.match(line)
                    if mh:
                        masked = mh.group(1) + re.sub(r"[0-9A-Fa-f]", "0", mh.group(2))
                        if masked != line:
                            reps.append(Replacement(idx, "key_block", line.strip(), masked.strip()))
                        lines[idx - 1] = masked
                        continue
            if _KEY_BLOCK_BEGIN.match(line):
                in_block = True
            lines[idx - 1] = self._line(idx, line, reps, strict, host_re, hostnames, vendor)

        out = "\n".join(lines)
        self._self_check(out, reps)
        return SanitizeResult(out, vendor, reps)

    def _line(
        self,
        idx: int,
        line: str,
        reps: list[Replacement],
        strict: bool,
        host_re: re.Pattern[str] | None,
        hostnames: dict[str, str],
        vendor: str | None = None,
    ) -> str:
        nokia = vendor == "nokia"

        def sub_value(m: re.Match[str], cat: str, fmt: str) -> str:
            v = m.group("v")
            if v.lower() in _NOT_A_SECRET or v.startswith(("%^%#", "%@%@", "%$%$", "LMESH-")):
                return m.group(0)
            rep = self._token(cat, v, fmt)
            reps.append(Replacement(idx, cat, v, rep))
            s, e = m.start("v") - m.start(), m.end("v") - m.start()
            return m.group(0)[:s] + rep + m.group(0)[e:]

        def cipher(m: re.Match[str]) -> str:
            rep = self._token("secret", m.group(0), "%^%#LMESH-SECRET-{h}%^%#")
            reps.append(Replacement(idx, "secret", m.group(0), rep))
            return rep

        new = _HW_CIPHER.sub(cipher, line)
        for rx in self.redact:

            def custom(m: re.Match[str]) -> str:
                r = self._token("custom", m.group(0).upper(), "ORG-{h}")
                reps.append(Replacement(idx, "custom", m.group(0), r))
                return r

            new = rx.sub(custom, new)
        if not _SECRET_EXEMPT.match(new):
            # 认不出厂商（REQ-044）：通用规则 = 两组规则都用（引号里的口令 / 密钥也替换）
            for pat, cat in (
                _NOKIA_SECRET_RULES if nokia else _SECRET_RULES + (_GENERIC_EXTRA if vendor is None else [])
            ):
                fmt = "LMESH-SECRET-{h}" if cat == "secret" else "LMESH-COMM-{h}"
                new = pat.sub(functools.partial(_apply, sub_value, cat, fmt), new)
            if nokia and self._snmp_ctx:
                new = _NOKIA_MD_COMMUNITY.sub(functools.partial(_apply, sub_value, "community", "LMESH-COMM-{h}"), new)

        if strict:
            md = _DESCRIPTION.match(new)
            if md:
                value = md.group("v")
                quoted = nokia and len(value) >= 2 and value[0] == value[-1] == '"'  # Nokia：保留引号
                if quoted:
                    value = value[1:-1]
                rep = self._token("description", value, "DESC-{h}")
                reps.append(Replacement(idx, "description", value, rep))
                new = md.group("lead") + (f'"{rep}"' if quoted else rep)
            for p in _IDENTIFIERS:
                new = p.sub(lambda m: sub_value(m, "identifier", "ID-{h}"), new)
            for p in _NOKIA_USER_DEFS if nokia else _USER_DEFS:
                new = p.sub(lambda m: sub_value(m, "user", "user-{h}"), new)
            if host_re is not None:

                def host(m: re.Match[str]) -> str:
                    reps.append(Replacement(idx, "hostname", m.group(1), hostnames[m.group(1)]))
                    return hostnames[m.group(1)]

                new = host_re.sub(host, new)

        def ip(m: re.Match[str]) -> str:
            rep = self.anon_ip(m.group(1))
            if rep != m.group(1):
                reps.append(Replacement(idx, "ip", m.group(1), rep))
            return rep

        return _IPV4.sub(ip, new)

    def _self_check(self, out: str, reps: list[Replacement]) -> None:
        leaked = [
            r for r in reps if r.category in ("secret", "community") and len(r.original) >= 4 and r.original in out
        ]
        if leaked:
            # 残留在脱敏结果的哪些行（只给行号，不给值）：用户据此找到没认出来的命令写法
            vals = {r.original for r in leaked}
            lines = [i for i, ln in enumerate(out.split("\n"), 1) if any(v in ln for v in vals)]
            err = SanitizeLeak(f"脱敏后仍残留 {len(leaked)} 处秘密值（行 {', '.join(str(n) for n in lines[:10])}）")
            err.lines = lines
            raise err


def local_key() -> bytes:
    """本机的脱敏密钥（config/sanitize.key，不入库）：导入时用它，跨批次的替换结果保持一致。"""
    from lmesh import paths

    f = paths.config_dir() / "sanitize.key"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(secrets.token_bytes(32))
    return f.read_bytes()


def _apply(fn, cat: str, fmt: str, m: re.Match[str]) -> str:  # type: ignore[no-untyped-def]
    return str(fn(m, cat, fmt))


class SanitizeLeak(RuntimeError):
    """脱敏自检发现秘密值仍然残留；lines 是残留所在的行号（不含值）。"""

    lines: list[int] = []
