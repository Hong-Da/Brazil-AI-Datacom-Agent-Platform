"""未支持型号的处理（M8-7，REQ-044）的接口权限与流程：全局型号规则只有维护员与管理员能新建、修改、删除，普通用户只能
管本项目的规则；导入时“记住”为全局规则同样受限；只读成员不能更换 Profile 但可以申请支持；维护员派生 Profile、改指向
并重新解析（跨项目）；普通用户不能处理申请。NE8000 用合成样本。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.api.test_projects_api import Client, _app, team  # noqa: F401
from tests.conftest import INPUTS, TEST_TOKEN

pytestmark = pytest.mark.api
NE1 = (INPUTS / "configs" / "ne8000" / "ne8000-x8-01.cfg").read_text(encoding="utf-8")
NE2 = (INPUTS / "configs" / "ne8000" / "ne8000-x8-02.cfg").read_text(encoding="utf-8")
R25, R23 = "huawei-atn-v800r025", "huawei-atn-v800r023"


def test_rule_permissions_and_support_flow(full_kb_root: Path, team: Path) -> None:  # noqa: F811
    app = _app()
    liwei, wang, kbm, boss = (Client(app, u) for u in ("liwei", "wang", "kbm", "boss"))
    glob = Client(app, token=TEST_TOKEN)
    assert liwei.post("/projects", json={"name": "城域", "slug": "metro"}).status_code == 200
    assert liwei.put("/projects/metro/members/wang", json={"role": "read"}).status_code == 200
    r = liwei.upload("/projects/metro/configs", "ne1.cfg", NE1)
    f = r.json()["data"]["files"][0]
    assert f["ok"] and (f["profile"], f["profile_source"], f["match_level"]) == (R25, "fallback", "approx")
    dev_id = liwei.get("/projects/metro/devices").json()["data"]["devices"][0]["id"]

    # 全局规则：普通用户 403，维护员与管理员可以
    body = {"scope": "global", "name_pattern": "NE8000-*", "profile": R23}
    assert liwei.post("/projects/metro/model-rules", json=body).status_code == 403
    r = kbm.post("/model-rules", json=body)
    assert r.status_code == 200, r.text
    gid = r.json()["data"]["id"]
    assert boss.post("/model-rules", json={**body, "name_pattern": "NE40E-*"}).status_code == 200
    assert liwei.put(f"/projects/metro/model-rules/{gid}", json={"note": "x"}).status_code == 403
    assert liwei.delete(f"/projects/metro/model-rules/{gid}").status_code == 403
    assert kbm.put(f"/model-rules/{gid}", json={"enabled": False}).status_code == 200
    # 本项目规则：属主可以，只读成员不行
    r = liwei.post(
        "/projects/metro/model-rules", json={"scope": "project", "version": "V800R022", "profile": R23, "reparse": True}
    )
    assert r.status_code == 200 and r.json()["data"]["reparsed"] == 1
    pid = r.json()["data"]["id"]
    assert (
        wang.post("/projects/metro/model-rules", json={"scope": "project", "version": "x", "profile": R23}).status_code
        == 403
    )
    lst = wang.get("/projects/metro/model-rules").json()["data"]
    assert [x["id"] for x in lst["project"]] == [pid] and lst["can_global"] is False and len(lst["global"]) == 2
    # 别的项目的规则看不到也改不了
    assert kbm.put(f"/model-rules/{pid}", json={"note": "x"}).status_code == 404

    # 导入时“记住”为全局规则：普通用户 403
    choices = '{"ne2.cfg": {"profile": "huawei-atn-v800r023", "remember": {"scope": "global"}}}'
    r = liwei.post(
        "/projects/metro/configs", files=[("files", ("ne2.cfg", NE2.encode(), "text/plain"))], data={"choices": choices}
    )
    assert r.status_code == 403
    r = liwei.post("/projects/metro/configs", files=[("files", ("ne2.cfg", NE2.encode(), "text/plain"))])
    assert r.json()["data"]["files"][0]["profile_source"] == "rule"  # 本项目规则命中

    # 更换 Profile：只读成员 403；属主可以
    assert wang.put(f"/projects/metro/devices/{dev_id}/profile", json={"profile": R25}).status_code == 403
    r = liwei.put(f"/projects/metro/devices/{dev_id}/profile", json={"profile": R25})
    assert r.status_code == 200 and r.json()["data"]["profile_source"] == "manual"
    r = liwei.put(f"/projects/metro/devices/{dev_id}/profile", json={"profile": None})
    assert r.json()["data"]["profile_source"] == "rule"

    # 申请支持：只读成员也可以（建议）；普通用户不能处理，维护员派生并改指向
    r = wang.post(
        f"/projects/metro/devices/{dev_id}/support-request", json={"model": "NE8000 X8", "reason": "城域汇聚"}
    )
    assert r.status_code == 200, r.text
    item = r.json()["data"]["id"]
    mine = wang.get("/kb/suggestions?mine=true").json()["data"]["items"]
    assert mine[0]["payload"]["kind"] == "model" and mine[0]["payload"]["device"] == "NE8000-X8-01"
    assert liwei.get(f"/kb/model-support/{item}").status_code == 403
    derive = {"id": "huawei-ne8000-v800r022", "base": R23, "version": "V800R022"}
    assert liwei.post(f"/kb/model-support/{item}/derive", json=derive).status_code == 403
    r = kbm.post(f"/kb/model-support/{item}/derive", json=derive)
    assert r.status_code == 200, r.text
    st = kbm.get(f"/kb/model-support/{item}").json()["data"]
    assert st["derived"]["profile"] == "huawei-ne8000-v800r022" and st["released"] is False
    assert {d["name"] for d in st["plan"]["devices"]} == {"NE8000-X8-01", "NE8000-X8-02"}
    assert liwei.post(f"/kb/model-support/{item}/retarget", json={}).status_code == 403
    r = kbm.post(f"/kb/model-support/{item}/retarget", json={"note": "已派生"})
    assert r.status_code == 200, r.text
    out = r.json()["data"]
    assert out["rules_changed"] == [pid] and {d["profile"] for d in out["devices"]} == {"huawei-ne8000-v800r022"}
    devs = liwei.get("/projects/metro/devices").json()["data"]["devices"]
    assert {(d["profile"], d["profile_source"]) for d in devs} == {("huawei-ne8000-v800r022", "rule")}
    assert glob.get(f"/review/{item}").json()["data"]["status"] == "approved"
    # 已处理的申请不能再派生
    assert kbm.post(f"/kb/model-support/{item}/derive", json={**derive, "id": "x-y"}).status_code == 409


def test_graph_and_change_carry_approx_flag(full_kb_root: Path, team: Path) -> None:  # noqa: F811
    app = _app()
    liwei = Client(app, "liwei")
    assert liwei.post("/projects", json={"name": "城域", "slug": "metro"}).status_code == 200
    liwei.upload("/projects/metro/configs", "ne1.cfg", NE1)
    dev_id = liwei.get("/projects/metro/devices").json()["data"]["devices"][0]["id"]
    g = liwei.get(f"/projects/metro/devices/{dev_id}/graph").json()["data"]
    assert g["profile_info"]["approx"] is True and g["profile_info"]["profile_source"] == "fallback"
    r = liwei.post(
        "/projects/metro/change",
        json={"current": {"device_id": dev_id}, "target": {"text": NE1.replace(" mtu 9600 jumbo-frame", " mtu 9216")}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["approx_profile"]["profile"] == R25
    r = liwei.post("/projects/metro/translate", json={"device_id": dev_id, "to": "cisco-iosxe-asr920-17.15"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["approx_profile"]["source"] == "fallback"
