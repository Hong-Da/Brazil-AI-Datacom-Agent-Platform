"""AI 查询会话（REQ-052）、附件（REQ-053）与报告（REQ-054）的核心逻辑：会话只有本人可见、分享后同项目成员只读、
取消分享后看不到；文档文字提取（Excel、Word、CSV）；AI 报告占位符的核对。SQLite 与 PostgreSQL 各一次（会话部分）。"""

from __future__ import annotations

import io
import zipfile
from typing import Any

import pytest

from lmesh.core import ask_docs, ask_report, ask_sessions, projects, store, users

pytestmark = pytest.mark.unit
PW = "Pass-word-123"


@pytest.fixture
def url(db_url: str) -> Any:
    store.upgrade(db_url)
    for name in ("alice", "bob", "carol"):
        users.create_user(db_url, name, PW, "user")
    projects.set_create_open(True)
    yield db_url
    projects.set_create_open(None)


def _as(url: str, name: str) -> tuple[projects.Scope, projects.Identity]:
    ident = projects.cli_identity(url, name)
    return projects.resolve(url, ident, "lab"), ident


def test_private_shared_read_only(url: str) -> None:
    alice = projects.cli_identity(url, "alice")
    projects.create_project(url, alice, {"name": "lab", "slug": "lab"})
    sc = projects.resolve(url, alice, "lab")
    projects.set_member(url, sc, "bob", "read")
    with projects.use(sc, alice):
        sid = ask_sessions.create(url, "VPN")["id"]
        ask_sessions.add_turn(url, sid, "Q1?", {"query_text": "FIND interface RETURN name"}, 0, [])
        assert [s["title"] for s in ask_sessions.list_sessions(url)] == ["VPN"]
    bob_sc, bob = _as(url, "bob")
    with projects.use(bob_sc, bob):
        assert ask_sessions.list_sessions(url) == [] and ask_sessions.list_sessions(url, "shared") == []
        with pytest.raises(ask_sessions.SessionError) as e:
            ask_sessions.get(url, sid)
        assert e.value.kind == "not_found"
    with projects.use(sc, alice):
        ask_sessions.update(url, sid, {"shared": True})
    with projects.use(bob_sc, bob):
        shared = ask_sessions.list_sessions(url, "shared")
        assert [s["owner"] for s in shared] == ["alice"] and not shared[0]["mine"]
        d = ask_sessions.get(url, sid)
        assert not d["mine"] and d["turn_list"][0]["versions"][0]["question"] == "Q1?"
        assert ask_sessions.counts(url) == {"active": 0, "archived": 0, "shared": 1}
        for fn in (
            lambda: ask_sessions.update(url, sid, {"title": "x"}),
            lambda: ask_sessions.delete(url, sid),
            lambda: ask_sessions.add_turn(url, sid, "Q2", {}, 0, []),
        ):
            with pytest.raises(ask_sessions.SessionError) as e:
                fn()
            assert e.value.kind == "forbidden"
    with projects.use(sc, alice):
        ask_sessions.update(url, sid, {"shared": False})
        assert ask_sessions.history(url, sid) == [{"question": "Q1?", "query": "FIND interface RETURN name"}]
    with projects.use(bob_sc, bob):
        assert ask_sessions.list_sessions(url, "shared") == []
    # 不是项目成员：看不到项目，自然也看不到会话
    carol = projects.cli_identity(url, "carol")
    with pytest.raises(projects.ProjectError):
        projects.resolve(url, carol, "lab")


def test_extract_xlsx_docx_csv() -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "规划"
    ws.append(["接口", "地址"])
    ws.append(["GE0/2/0", "10.1.1.1/30"])
    wb.create_sheet("空表")
    buf = io.BytesIO()
    wb.save(buf)
    ex = ask_docs.extract("plan.xlsx", buf.getvalue())
    assert "## Sheet: 规划" in ex.text and "2| GE0/2/0 | 10.1.1.1/30" in ex.text
    assert ex.meta == {"format": "xlsx", "sheets": 2, "rows": 2}

    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    doc = (
        f'<w:document xmlns:w="{w}"><w:body><w:p><w:r><w:t>割接说明</w:t></w:r></w:p>'
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>设备</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>窗口</w:t></w:r></w:p></w:tc></w:tr>"
        "</w:tbl></w:body></w:document>"
    )
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        z.writestr("word/document.xml", doc)
    ex = ask_docs.extract("plan.docx", zb.getvalue())
    assert ex.text.splitlines() == ["割接说明", "## Table 1", "| 设备 | 窗口"] and ex.meta["tables"] == 1

    ex = ask_docs.extract("a.csv", b"a,b\n1,2\n")
    assert ex.text == "1| a | b\n2| 1 | 2" and ex.meta["rows"] == 2
    with pytest.raises(ask_docs.DocError):
        ask_docs.extract("x.bin", b"\x00\x01")
    with pytest.raises(ask_docs.DocError):
        ask_docs.extract("bad.xlsx", b"not a zip")
    assert ask_docs.image_type("t.png", b"\x89PNG\r\n\x1a\n...") == "image/png"
    assert ask_docs.image_type("t.png", b"GIF89a") is None


def test_ai_report_placeholders() -> None:
    sess = {
        "title": "VPN",
        "attachment_list": [],
        "turn_list": [
            {
                "current": 0,
                "versions": [
                    {
                        "question": "哪些接口绑定了 VPN？",
                        "result": {
                            "result": {
                                "count": 2,
                                "rows": [{"device": "R1", "label": "GE1"}, {"device": "R1", "label": "GE2"}],
                            },
                            "answer": {
                                "statements": [{"status": "passed"}, {"status": "corrected", "corrected_text": "X"}]
                            },
                        },
                    }
                ],
            }
        ],
    }
    facts = ask_report.facts_of(sess)
    assert (
        facts["numbers"]["t1.rows"] == 2
        and facts["numbers"]["t1.d1.rows"] == 2
        and facts["numbers"]["t1.corrected"] == 1
    )
    assert facts["objects"]["d1"]["label"] == "R1" and facts["objects"]["q1"]["type"] == "question"
    r = ask_report.check_report("## 发现\n- [[d1]] 上有 <<t1.rows>> 个接口。还有 3 个没有描述。", facts, "zh-CN")
    assert r["verified"] == 1 and r["unverified"] == 1
    assert r["markdown"] == "## 发现\n- R1 上有 2 个接口。还有 3 个没有描述。（未经核对）\n"
    r = ask_report.check_report("```markdown\n## Findings\n- [[d9]] has <<nope>> rows.\n```", facts, "en")
    assert r["unverified"] == 1 and "(unverified)" in r["markdown"] and r["blocks"][0]["type"] == "h"
