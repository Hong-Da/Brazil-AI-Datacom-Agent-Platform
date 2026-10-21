"""AI 查询会话（REQ-052）、附件（REQ-053）、下载与 AI 报告（REQ-054）的接口：AI 一律用假的客户端（替换 ai.provider_hook），
记下发给 AI 的提示与图片，核对上下文、参考资料、图片确认与临时设备。"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from lmesh.core import ai
from tests.conftest import TEST_TOKEN, prepare

pytestmark = pytest.mark.api
H = {"Authorization": f"Bearer {TEST_TOKEN}"}
ROOT = Path(__file__).resolve().parent.parent.parent
ATN = (ROOT / "knowledge" / "samples" / "change" / "atn-base.cfg").read_text(encoding="utf-8")
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
Q1 = '{"query": "FIND interface WHERE mtu = 9216 RETURN name, description, mtu"}'
A1 = json.dumps(
    {"statements": [{"text": "MTU 是 9216。", "cites": [1], "facts": [{"row": 1, "field": "mtu", "value": "9216"}]}]}
)


class FakeAI:
    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.images: list[int] = []

    def __call__(self, conn: Any, model: str, system: str, prompt: str) -> ai.Reply:
        self.prompts.append(prompt)
        self.images.append(len(ai.pending_images()))
        return ai.Reply(self.replies.pop(0), model, 10, 5)


@pytest.fixture
def setup(tmp_root: Path, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    prepare("configured-fullkb-history", request)
    monkeypatch.setenv("LMESH_AI__PROVIDER", "openai")
    monkeypatch.setenv("LMESH_AI__BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("LMESH_AI__MODEL", "fake-model")

    def make(replies: list[str], images: bool = False):  # type: ignore[no-untyped-def]
        from fastapi.testclient import TestClient

        from lmesh.api import create_app

        if images:
            monkeypatch.setenv("LMESH_AI__ASK_IMAGES", "true")
        fake = FakeAI(replies)
        monkeypatch.setattr(ai, "provider_hook", fake)
        return TestClient(create_app()), fake

    return make


def _new(c: Any) -> int:
    r = c.post("/api/v1/ask/sessions", headers=H, json={})
    assert r.status_code == 200, r.text
    return int(r.json()["data"]["id"])


def test_session_follow_up_versions_archive(setup) -> None:  # type: ignore[no-untyped-def]
    c, fake = setup([Q1, A1, Q1, A1, Q1, A1])
    sid = _new(c)
    r = c.post(
        f"/api/v1/ask/sessions/{sid}/turns", headers=H, json={"question": "哪个接口 MTU 是 9216？", "lang": "en"}
    )
    assert r.status_code == 200, r.text
    t1 = r.json()["data"]
    assert t1["versions"][0]["result"]["status"] == "answered" and t1["versions"][0]["context"] == 0
    assert "Earlier questions" not in fake.prompts[0]
    # 追问：AI 看到前一轮的问题与查询
    r = c.post(f"/api/v1/ask/sessions/{sid}/turns", headers=H, json={"question": "只看描述呢？"})
    assert r.status_code == 200 and r.json()["data"]["versions"][0]["context"] == 1
    assert "Earlier questions" in fake.prompts[2] and "mtu = 9216" in fake.prompts[2]
    # 改问重答第一轮：追加版本，上下文为它之前的轮次（没有）
    r = c.post(
        f"/api/v1/ask/sessions/{sid}/turns/{t1['id']}/versions", headers=H, json={"question": "MTU 9216 的接口有哪些？"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["current"] == 1 and len(r.json()["data"]["versions"]) == 2
    assert "Earlier questions" not in fake.prompts[4]
    assert (
        c.put(f"/api/v1/ask/sessions/{sid}/turns/{t1['id']}", headers=H, json={"current": 0}).json()["data"]["current"]
        == 0
    )
    assert c.put(f"/api/v1/ask/sessions/{sid}/turns/{t1['id']}", headers=H, json={"current": 5}).status_code == 422
    d = c.get(f"/api/v1/ask/sessions/{sid}", headers=H).json()["data"]
    assert d["title"] == "哪个接口 MTU 是 9216？" and d["mine"] and len(d["turn_list"]) == 2
    # 重命名、分享、归档后不能再提问
    c.patch(f"/api/v1/ask/sessions/{sid}", headers=H, json={"title": "MTU", "shared": True, "archived": True})
    ls = c.get("/api/v1/ask/sessions?which=archived", headers=H).json()["data"]
    assert [s["title"] for s in ls["sessions"]] == ["MTU"] and ls["sessions"][0]["shared"]
    assert ls["counts"] == {"active": 0, "archived": 1, "shared": 0}
    r = c.post(f"/api/v1/ask/sessions/{sid}/turns", headers=H, json={"question": "再问"})
    assert r.status_code == 409 and r.json()["message"]
    assert c.delete(f"/api/v1/ask/sessions/{sid}", headers=H).status_code == 200
    assert c.get(f"/api/v1/ask/sessions/{sid}", headers=H).status_code == 404


def test_attachments_config_doc_and_images(setup) -> None:  # type: ignore[no-untyped-def]
    c, fake = setup(['{"query": "FIND interface RETURN name"}', A1])
    sid = _new(c)
    files = [
        ("files", ("edge.cfg", ATN.replace("ATN-CHANGE-01", "EDGE-NEW-01").encode(), "text/plain")),
        ("files", ("plan.csv", "接口,地址\nGE0/2/0,10.1.1.1/30\n".encode(), "text/csv")),
    ]
    r = c.post(f"/api/v1/ask/sessions/{sid}/attachments", headers=H, files=files)
    assert r.status_code == 200, r.text
    kinds = {a["name"]: a for a in r.json()["data"]["attachments"]}
    assert kinds["edge.cfg"]["kind"] == "config" and kinds["edge.cfg"]["meta"]["vendor"] == "huawei"
    assert kinds["plan.csv"]["kind"] == "doc" and kinds["plan.csv"]["meta"]["rows"] == 2
    # 图片默认关闭
    r = c.post(f"/api/v1/ask/sessions/{sid}/attachments", headers=H, files=[("files", ("t.png", PNG, "image/png"))])
    assert r.status_code == 409
    r = c.post(f"/api/v1/ask/sessions/{sid}/turns", headers=H, json={"question": "哪个接口 MTU 是 9216？"})
    assert r.status_code == 200, r.text
    res = r.json()["data"]["versions"][0]["result"]
    devices = {row["device"] for row in res["result"]["rows"]}
    assert "EDGE-NEW-01" in devices  # 附件里的配置作为临时设备加入了范围
    assert "### plan.csv" in fake.prompts[1] and "Reference material" in fake.prompts[1]
    assert r.json()["data"]["versions"][0]["attachments"] == [a["id"] for a in kinds.values()]
    # 临时设备不进设备库
    names = [d["name"] for d in c.get("/api/v1/devices", headers=H).json()["data"]["devices"]]
    assert "EDGE-NEW-01" not in names
    aid = kinds["plan.csv"]["id"]
    assert c.delete(f"/api/v1/ask/sessions/{sid}/attachments/{aid}", headers=H).status_code == 200
    bad = c.post(f"/api/v1/ask/sessions/{sid}/attachments", headers=H, files=[("files", ("x.exe", b"MZ\x00\x00", "x"))])
    assert bad.status_code == 422


def test_images_need_confirmation(setup) -> None:  # type: ignore[no-untyped-def]
    c, fake = setup([Q1, A1], images=True)
    sid = _new(c)
    r = c.post(f"/api/v1/ask/sessions/{sid}/attachments", headers=H, files=[("files", ("t.png", PNG, "image/png"))])
    assert r.status_code == 200 and r.json()["data"]["attachments"][0]["kind"] == "image"
    r = c.post(f"/api/v1/ask/sessions/{sid}/turns", headers=H, json={"question": "图里是什么？"})
    assert r.status_code == 409 and r.json()["data"]["images"]
    r = c.post(
        f"/api/v1/ask/sessions/{sid}/turns", headers=H, json={"question": "图里是什么？", "confirm_images": True}
    )
    assert r.status_code == 200, r.text
    assert fake.images == [1, 1]  # 两次调用都带上了图片


def test_downloads_and_ai_report(setup) -> None:  # type: ignore[no-untyped-def]
    md_ok = "## 概要\n本会话共 <<turns>> 轮，围绕 [[q1]]。\n## 发现\n- [[d1]] 上有 <<t1.rows>> 个接口。"
    md_bad = "## 发现\n- [[d1]] 上有 3 个接口的 MTU 为 9000。"
    c, _ = setup([Q1, A1, md_ok, md_bad])
    sid = _new(c)
    t = c.post(f"/api/v1/ask/sessions/{sid}/turns", headers=H, json={"question": "哪个接口 MTU 是 9216？"}).json()[
        "data"
    ]
    r = c.get(f"/api/v1/ask/sessions/{sid}/report?lang=zh-CN&format=html", headers=H)
    assert r.status_code == 200 and "AI 查询会话报告" in r.text and "mtu = 9216" in r.text
    assert "ask-session-" in r.headers["content-disposition"]
    r = c.get(f"/api/v1/ask/sessions/{sid}/report?lang=en&format=md", headers=H)
    assert r.status_code == 200 and r.text.startswith("# AI Query Session Report")
    r = c.get(f"/api/v1/ask/sessions/{sid}/turns/{t['id']}/table?format=csv", headers=H)
    assert r.status_code == 200 and r.content.startswith(b"\xef\xbb\xbf#,object,node")
    r = c.get(f"/api/v1/ask/sessions/{sid}/turns/{t['id']}/table?format=xlsx", headers=H)
    from openpyxl import load_workbook

    ws = load_workbook(io.BytesIO(r.content)).active
    assert ws is not None and ws["B1"].value == "object" and ws.max_row >= 2
    r = c.post(f"/api/v1/ask/sessions/{sid}/ai-report", headers=H, json={"lang": "zh-CN"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["unverified"] == 0 and d["verified"] == 2 and "ATN-CHANGE-01" in d["markdown"]
    assert d["filename"].endswith(".zh-CN.md")
    d = c.post(f"/api/v1/ask/sessions/{sid}/ai-report", headers=H, json={"lang": "zh-CN"}).json()["data"]
    assert d["unverified"] == 1 and "（未经核对）" in d["markdown"]
