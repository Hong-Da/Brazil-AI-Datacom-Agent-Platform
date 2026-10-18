"""知识库：语法解析 / 匹配 / 渲染、加载与校验、继承展开、Profile 匹配、知识库包、发布 / 对比 / 回滚、审核队列。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lmesh.core import kb as kbmod
from lmesh.core import kbservice, review, store
from lmesh.core.kb import package, repo
from lmesh.core.kb import syntax as syn
from lmesh.core.kb.validate import validate

pytestmark = pytest.mark.unit
TEST_KB = Path(__file__).resolve().parent.parent / "inputs" / "kb"
REAL_KB = Path(__file__).resolve().parent.parent.parent / "knowledge"


# ---------- 语法 ----------


@pytest.mark.parametrize("text", ["a [ b", "a { b | c", "a ] b", "", "a | b"])
def test_syntax_errors(text: str) -> None:
    with pytest.raises(syn.SyntaxErrorKB):
        syn.parse(text)


def test_syntax_params_and_groups() -> None:
    s = syn.parse("ip route-static [ vpn-instance <vrf> ] <ip> { <mask> | <len> } <nh> [ preference <pref> ]")
    assert s.params() == ["vrf", "ip", "mask", "len", "nh", "pref"]
    assert s.first_keyword() == "ip"


ROUTE = "ip route-static [ vpn-instance <vrf> ] <ip> { <mask> | <len> } <nh> [ preference <pref> ]"
ROUTE_P = {
    "vrf": {"type": "word"},
    "ip": {"type": "ipv4"},
    "mask": {"type": "mask"},
    "len": {"type": "mask-length"},
    "nh": {"type": "ipv4"},
    "pref": {"type": "integer", "range": [1, 255]},
}


@pytest.mark.parametrize(
    "line",
    [
        "ip route-static 0.0.0.0 0.0.0.0 10.0.0.1",
        "ip route-static vpn-instance GERÊNCIA 10.1.0.0 255.255.0.0 10.0.0.1 preference 70",
        "ip route-static 10.2.0.0 16 10.0.0.1",
    ],
)
def test_match_and_render_roundtrip(line: str) -> None:
    s = syn.parse(ROUTE)
    m = syn.match(s, line, ROUTE_P)
    assert m is not None
    assert syn.render(s, m) == line


def test_match_rejects_bad_types() -> None:
    s = syn.parse(ROUTE)
    assert syn.match(s, "ip route-static 10.2.0.0 99 10.0.0.1", ROUTE_P) is None  # 掩码长度超范围
    assert syn.match(s, "ip route-static 10.2.0.0 255.0.255.0 10.0.0.1", ROUTE_P) is None  # 不连续掩码
    assert syn.match(s, "ip route-static 10.0.0.1", ROUTE_P) is None


def test_text_param_keeps_spacing() -> None:
    s = syn.parse("description <text>")
    m = syn.match(s, "description Ligação  para  São João", {"text": {"type": "text"}})
    assert m is not None and m.values["text"] == "Ligação  para  São João"
    assert syn.render(s, m) == "description Ligação  para  São João"


def test_prefers_more_keywords() -> None:
    s = syn.parse("peer <a> { <b> | group <g> }")
    m = syn.match(s, "peer 1.1.1.1 group Client", {"a": {"type": "ipv4"}})
    assert m is not None and m.values == {"a": "1.1.1.1", "g": "Client"}


# ---------- 加载、校验、继承 ----------


def test_load_test_kb() -> None:
    kb = kbmod.load(TEST_KB)
    assert kb.version == "1.2.3" and len(kb.cards) == 4 and len(kb.nodes) == 6
    assert not [i for i in validate(kb) if i.level == "error"]


def test_real_kb_is_valid() -> None:
    kb = kbmod.load(REAL_KB)
    errors = [i for i in validate(kb) if i.level == "error"]
    assert not errors, [e.message for e in errors]


def test_inheritance() -> None:
    kb = kbmod.load(TEST_KB)
    r = kb.resolve_profile("t-child")
    assert r.entries["bgp.peer.keepalive"].default == 30 and r.entries["bgp.peer.keepalive"].origin == "t-child"
    assert r.entries["bgp.peer.hold"].default == 180 and r.entries["bgp.peer.hold"].origin == "t-base"
    assert r.entries["bgp.peer.description"].supported is False
    assert kb.lineage("t-child") == ["t-child", "t-base"]


def test_match_profile() -> None:
    kb = kbmod.load(TEST_KB)
    assert kb.match_profile("huawei", "V800R023C00SPC500") == "t-child"
    assert kb.match_profile("huawei", "V800R025C00") == "t-base"
    assert kb.match_profile("huawei", "") == "t-base"  # fallback
    assert kb.match_profile("cisco", "17.15") is None


def _copy_kb(tmp_path: Path) -> Path:
    dst = tmp_path / "kb"
    shutil.copytree(TEST_KB, dst)
    return dst


@pytest.mark.parametrize(
    ("edit", "code"),
    [
        (
            lambda r: (r / "schema/bgp.yaml").write_text(
                "domain: bgp\nnodes: {x: {parent: nope, type: integer, semantic: s}}\n", encoding="utf-8"
            ),
            "node.parent_missing",
        ),
        (
            lambda r: (r / "profiles/child.yaml").write_text(
                "profile: t-child\nfamily: huawei-vrp8\ninherits: t-child\n", encoding="utf-8"
            ),
            "profile.cycle",
        ),
        (
            lambda r: (r / "profiles/base.yaml").write_text(
                "profile: t-base\nfamily: huawei-vrp8\nentries: {no.such: {}}\n", encoding="utf-8"
            ),
            "profile.node_missing",
        ),
        (lambda r: (r / "kb.yaml").write_text("kb_version: [1\n", encoding="utf-8"), "yaml.syntax"),
        (
            lambda r: (r / "commands/huawei-vrp8/bgp.yaml").write_text(
                "domain: bgp\ncards:\n  - {id: bad, syntax: 'peer [ <a>', view: bgp}\n", encoding="utf-8"
            ),
            "card.syntax",
        ),
        (
            lambda r: (r / "commands/huawei-vrp8/bgp.yaml").write_text(
                "domain: bgp\ncards:\n  - {id: bad, syntax: 'peer <a>', view: bgp, maps: {bgp.peer: $b}}\n",
                encoding="utf-8",
            ),
            "card.map_param",
        ),
        (
            lambda r: (r / "commands/huawei-vrp8/bgp.yaml").write_text(
                "domain: bgp\ncards:\n  - {id: bad, syntax: 'peer <a>', view: nowhere}\n", encoding="utf-8"
            ),
            "card.view_missing",
        ),
    ],
)
def test_validate_catches(tmp_path: Path, edit, code: str) -> None:  # type: ignore[no-untyped-def]
    root = _copy_kb(tmp_path)
    edit(root)
    codes = {i.code for i in validate(kbmod.load(root)) if i.level == "error"}
    assert code in codes, codes


# ---------- 包、发布、对比、回滚、审核 ----------


def test_release_diff_rollback(tmp_root: Path) -> None:
    root = _copy_kb(tmp_root)
    repo.ensure_repo(root)
    r1 = kbservice.release(root, None, "first")
    assert r1["version"] == "1.3.0"  # 首次发布：从 1.2.3 按新增内容升次版本
    with pytest.raises(kbservice.ReleaseError) as e:
        kbservice.release(root, None, "nothing")
    assert e.value.key == "kb.release_nothing"
    # 修改默认值 → 修订号
    f = root / "profiles/base.yaml"
    f.write_text(f.read_text(encoding="utf-8").replace("default: 60", "default: 45"), encoding="utf-8")
    d = kbservice.diff(root, "1.3.0")
    assert d["defaults_changed"][0]["new"] == 45 and d["suggested_bump"] == "patch"
    assert kbservice.release(root, None, "fix default")["version"] == "1.3.1"
    # 删除节点 → 主版本
    s = root / "schema/bgp.yaml"
    s.write_text(
        s.read_text(encoding="utf-8").replace(
            "  bgp.peer.description: {parent: bgp.peer, type: text, semantic: {zh-CN: 对等体描述}}\n", ""
        ),
        encoding="utf-8",
    )
    assert kbservice.diff(root, "1.3.1")["suggested_bump"] == "major"
    # 回滚到 1.3.0：默认值恢复
    repo.rollback(root, "1.3.0")
    assert "default: 60" in f.read_text(encoding="utf-8")
    assert [r["version"] for r in kbservice.releases(root)][:2] == ["1.3.1", "1.3.0"]


def test_package_roundtrip_and_conflict(tmp_root: Path, db_url: str) -> None:
    store.upgrade(db_url)
    src = _copy_kb(tmp_root)
    data = package.export(src)
    dst = tmp_root / "kb2"
    dst.mkdir()
    repo.ensure_repo(dst)
    res = kbservice.import_package(dst, data, db_url)
    assert res["applied"] and len(res["added"]) == 6 and not res["conflicts"]
    # 再导入一份改过的包：变化的文件成为冲突，进审核队列，不直接覆盖
    (src / "kb.yaml").write_text("kb_version: 9.9.9\ndomains: [bgp]\n", encoding="utf-8")
    res2 = kbservice.import_package(dst, package.export(src), db_url)
    assert res2["conflicts"] == ["kb.yaml"] and len(res2["review_items"]) == 1
    assert "1.2.3" in (dst / "kb.yaml").read_text(encoding="utf-8")
    review.decide(db_url, dst, res2["review_items"][0], approve=True)
    assert "9.9.9" in (dst / "kb.yaml").read_text(encoding="utf-8")
    with pytest.raises(review.ReviewError):
        review.decide(db_url, dst, res2["review_items"][0], approve=True)


def test_package_rejects_invalid_and_unsafe(tmp_root: Path, db_url: str) -> None:
    import io
    import zipfile

    store.upgrade(db_url)
    dst = tmp_root / "kb3"
    dst.mkdir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("knowledge/profiles/x.yaml", "profile: x\ninherits: nope\n")
    res = kbservice.import_package(dst, buf.getvalue(), db_url)
    assert res["issues"] and not res["applied"] and not (dst / "profiles").exists()
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w") as z:
        z.writestr("knowledge/../evil.yaml", "x: 1")
    with pytest.raises(package.PackageError):
        kbservice.import_package(dst, buf2.getvalue(), db_url)


def test_coverage() -> None:
    cov = kbservice.coverage(TEST_KB)
    assert cov["totals"]["t-child"] == {"supported": 3, "unsupported": 1, "unfilled": 2}
    assert cov["matrix"]["bgp.peer.description"]["t-child"] == "unsupported"


def test_concurrent_loads_are_consistent() -> None:
    """Web 服务多个线程同时读知识库时结果一致（YAML 读取器不能跨线程共用）。"""
    import concurrent.futures as cf

    from lmesh.core.kb import load

    root = Path(__file__).resolve().parent.parent / "inputs" / "kb"

    def one(_: int) -> tuple[int, int, int]:
        kb = load(root)
        return len(kb.nodes), len(kb.cards), len(kb.load_issues)

    with cf.ThreadPoolExecutor(8) as ex:
        results = set(ex.map(one, range(32)))
    assert len(results) == 1 and next(iter(results))[2] == 0
