"""从测试用例数据生成调用文档的示例部分，并导出 OpenAPI 定义。

- docs/cli.md：<!-- examples:begin --> 与 <!-- examples:end --> 之间由 tests/cases/cli_cases.toml 生成
- docs/api.md：同上，由 tests/cases/api_cases.toml 生成（curl、PowerShell、Python 三种写法）
- docs/openapi.json：从应用导出
其余说明文字手写。用法：uv run python scripts/gen_docs.py [--check]（--check 只检查是否最新）
"""

from __future__ import annotations

import json
import shlex
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
CASES = ROOT / "tests" / "cases"
BEGIN, END = "<!-- examples:begin -->", "<!-- examples:end -->"
BASE = "http://127.0.0.1:9000"


def cases(name: str) -> list[dict[str, Any]]:
    """主文件 + 按功能拆分的 <名>.<功能>.toml，主文件在前。"""
    stem = name.removesuffix(".toml")
    out: list[dict[str, Any]] = []
    for f in [CASES / name, *sorted(CASES.glob(f"{stem}.*.toml"))]:
        with f.open("rb") as fh:
            out += [c for c in tomllib.load(fh)["case"] if c.get("in_docs")]
    return out


def _expect_lines(expect: dict[str, Any]) -> list[str]:
    return [f"- `{k}` = `{json.dumps(v, ensure_ascii=False)}`" for k, v in expect.items()]


def cli_examples() -> str:
    out = []
    for c in cases("cli_cases.toml"):
        env = " ".join(f"{k}={v}" for k, v in c.get("env", {}).items())
        args = [
            a.replace("{inputs}", "tests/inputs").replace("{out}", "out").replace("{samples}", "knowledge/samples")
            for a in c["args"]
        ]
        cmd = (env + " " if env else "") + "lmesh " + " ".join(shlex.quote(a) for a in args)
        out += [f"### {c['title']['zh-CN']}", "", "```bash", cmd, "```", "", f"退出码：`{c['expect_exit']}`"]
        if c.get("expect_json"):
            out += ["", "JSON 输出中的关键字段：", "", *_expect_lines(c["expect_json"])]
        if c.get("expect_stdout"):
            out += ["", "输出包含：" + "、".join(f"`{s}`" for s in c["expect_stdout"])]
        if c.get("expect_stderr"):
            out += ["", "错误提示（stderr）包含：" + "、".join(f"`{s}`" for s in c["expect_stderr"])]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def api_examples() -> str:
    out = []
    for c in cases("api_cases.toml"):
        url = BASE + c["path"]
        headers = dict(c.get("headers", {}))
        if c.get("auth"):
            headers["Authorization"] = "Bearer <令牌>"
        body = json.dumps(c["body"], ensure_ascii=False) if c.get("body") is not None else None
        curl = [f"curl -X {c['method']} '{url}'"] + [f"  -H '{k}: {v}'" for k, v in headers.items()]
        files = [f"tests/inputs/{f}" for f in c.get("files", [])]
        if body:
            curl += ["  -H 'Content-Type: application/json'", f"  -d '{body}'"]
        curl += [f"  -F 'files=@{f}'" for f in files] + [f"  -F '{k}={v}'" for k, v in c.get("form", {}).items()]
        ps_headers = "; ".join(f"'{k}'='{v}'" for k, v in headers.items())
        ps = f"Invoke-RestMethod -Method {c['method']} -Uri '{url}'"
        if headers:
            ps += f" -Headers @{{{ps_headers}}}"
        if body:
            ps += f" -ContentType 'application/json; charset=utf-8' -Body '{body}'"
        if files:
            form = "; ".join(
                [f"'files'=Get-Item '{f}'" for f in files[:1]] + [f"'{k}'='{v}'" for k, v in c.get("form", {}).items()]
            )
            ps += f" -Form @{{{form}}}"
        py = ["import requests", f"r = requests.request({c['method']!r}, {url!r}"]
        if headers:
            py[-1] += f", headers={headers!r}"
        if body:
            py[-1] += f", json={c['body']!r}"
        if files:
            py[-1] += ", files=[" + ", ".join(f"('files', open({f!r}, 'rb'))" for f in files) + "]"
            if c.get("form"):
                py[-1] += f", data={c['form']!r}"
        py[-1] += ")"
        py.append("print(r.status_code, r.json())")
        out += [
            f"### {c['title']['zh-CN']}",
            "",
            f"`{c['method']} {c['path']}`" + ("（需要令牌）" if c.get("auth") else ""),
            "",
            "```bash",
            " \\\n".join(curl),
            "```",
            "",
            "```powershell",
            ps,
            "```",
            "",
            "```python",
            *py,
            "```",
            "",
            f"HTTP 状态：`{c['expect_status']}`；返回中的关键字段：",
            "",
            *_expect_lines(c.get("expect_json", {})),
            "",
        ]
    return "\n".join(out).rstrip() + "\n"


def splice(path: Path, generated: str) -> str:
    text = path.read_text(encoding="utf-8")
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{BEGIN}\n\n{generated}\n{END}{tail}"


def openapi_text() -> str:
    import os

    os.environ.setdefault("LMESH_ROOT", str(ROOT / "tests" / "output" / "openapi-root"))
    from lmesh.api import create_app

    spec = create_app().openapi()
    return json.dumps(spec, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    targets = {
        DOCS / "cli.md": splice(DOCS / "cli.md", cli_examples()),
        DOCS / "api.md": splice(DOCS / "api.md", api_examples()),
        DOCS / "openapi.json": openapi_text(),
    }
    if "--check" in sys.argv:
        stale = [
            str(p.relative_to(ROOT)) for p, t in targets.items() if not p.exists() or p.read_text(encoding="utf-8") != t
        ]
        if stale:
            print("不是最新，运行 uv run python scripts/gen_docs.py：" + "、".join(stale))
            return 1
        print("调用文档已是最新")
        return 0
    for p, t in targets.items():
        p.write_text(t, encoding="utf-8")
        print(f"已生成 {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
