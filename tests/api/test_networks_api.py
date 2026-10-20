"""项目内的网络（M9，REQ-045）的接口：网络管理（新建、改名、复制、删除、文件夹、成员与版本、自动加入规则、建网建议）、
按网络的路径 /projects/{p}/n/{net}/…（设备范围、隔离、在网络里导入、网络外的对端、检查汇总）、不带网络的项目路径与旧路径
落到默认网络、权限（只读成员、非成员、只读令牌）、项目层接口不挂网络路径。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lmesh.core import checks
from tests.api.test_projects_api import Client, _app, team  # noqa: F401
from tests.conftest import TEST_TOKEN

pytestmark = pytest.mark.api
TOPO = Path(__file__).resolve().parent.parent.parent / "knowledge" / "samples" / "topology"
FILES = ["atn-a1.cfg", "atn-a2.cfg", "agg-01.cfg", "agg-02.cfg", "rr-01.cfg"]


def _upload(c: Client, path: str, files: list[str]) -> Any:
    return c.post(path, files=[("files", (f, (TOPO / f).read_bytes(), "text/plain")) for f in files])


def _ids(c: Client, path: str) -> dict[str, int]:
    return {d["name"]: d["id"] for d in c.get(path).json()["data"]["devices"]}


def test_network_flow(full_kb_root: Path, team: Path) -> None:  # noqa: F811
    app = _app()
    liwei, zhang, wang = (Client(app, u) for u in ("liwei", "zhang", "wang"))
    glob = Client(app, token=TEST_TOKEN)
    assert liwei.post("/projects", json={"name": "Lab", "slug": "lab"}).status_code == 200
    assert liwei.put("/projects/lab/members/zhang", json={"role": "read"}).status_code == 200
    r = _upload(liwei, "/projects/lab/configs", FILES[:4])
    files = r.json()["data"]["files"]
    assert all(f["ok"] for f in files) and all(f["joined_networks"][0]["slug"] == "default" for f in files)
    ids = _ids(liwei, "/projects/lab/devices")
    assert len(ids) == 4

    # 网络列表：升级 / 新建项目时的默认网络
    d = liwei.get("/projects/lab/networks").json()["data"]
    assert [n["slug"] for n in d["networks"]] == ["default"] and len(d["palette"]) == 8
    assert d["networks"][0]["counts"]["devices"] == 4 and d["overview"]["devices"] == 4

    # 新建网络（带设备与规则）；只读成员不能建，非成员看不到
    body = {
        "name": "汇聚",
        "slug": "agg",
        "device_ids": [ids["TOPO-AGG-01"], ids["TOPO-AGG-02"]],
        "rules": [{"kind": "name", "pattern": "TOPO-RR-*"}],
    }
    assert zhang.post("/projects/lab/networks", json=body).status_code == 403
    assert wang.get("/projects/lab/networks").status_code == 404
    r = liwei.post("/projects/lab/networks", json=body)
    assert r.status_code == 200, r.text
    agg = r.json()["data"]
    assert agg["counts"]["devices"] == 2 and agg["color"] == "indigo" and agg["rules"][0]["pattern"] == "TOPO-RR-*"
    assert liwei.post("/projects/lab/networks", json={"name": "x", "slug": "agg"}).status_code == 409
    assert liwei.post("/projects/lab/networks", json={"name": "x", "slug": "Bad Slug"}).status_code == 422

    # 按网络的路径：设备只看成员；不存在的网络 404；只读成员可以查看
    assert sorted(_ids(liwei, "/projects/lab/n/agg/devices")) == ["TOPO-AGG-01", "TOPO-AGG-02"]
    assert sorted(_ids(zhang, "/projects/lab/n/agg/devices")) == ["TOPO-AGG-01", "TOPO-AGG-02"]
    assert liwei.get(f"/projects/lab/n/agg/devices/{ids['TOPO-ATN-A1']}/versions").status_code == 404
    r = liwei.get("/projects/lab/n/nope/devices")
    assert r.status_code == 404 and r.json()["code"] == 1004
    assert len(_ids(liwei, "/projects/lab/n/default/devices")) == 4
    assert len(_ids(glob, "/projects/liwei~lab/n/agg/devices")) == 2  # 全局令牌

    # 在网络里导入：进项目设备池、默认网络、当前网络；规则命中的网络也提示
    r = _upload(liwei, "/projects/lab/n/agg/configs", ["rr-01.cfg"])
    joined = [(x["slug"], x["via"]) for x in r.json()["data"]["files"][0]["joined_networks"]]
    assert joined == [("default", "default"), ("agg", "current")]
    ids = _ids(liwei, "/projects/lab/devices")
    assert len(ids) == 5

    # 隔离：在 agg 忽略的发现，在默认网络（不带网络的项目路径、旧路径）看不到
    rule = sorted(checks.BUILTIN)[0]
    ig = {"device_id": ids["TOPO-AGG-01"], "rule": rule, "node": "x", "reason": "只在汇聚网络"}
    assert zhang.post("/projects/lab/n/agg/check/ignores", json=ig).status_code == 403
    assert liwei.post("/projects/lab/n/agg/check/ignores", json=ig).status_code == 200
    assert len(liwei.get("/projects/lab/n/agg/check/ignores").json()["data"]["ignores"]) == 1
    assert liwei.get("/projects/lab/check/ignores").json()["data"]["ignores"] == []
    assert liwei.get("/projects/lab/n/default/check/ignores").json()["data"]["ignores"] == []

    # 规则调整、脚本、视图标注按网络
    r = liwei.put(f"/projects/lab/n/agg/rules/{rule}", json={"enabled": False, "reason": "汇聚不看"})
    assert r.status_code == 200, r.text
    agg_rules = {x["id"]: x for x in liwei.get("/projects/lab/n/agg/rules").json()["data"]["rules"]}
    def_rules = {x["id"]: x for x in liwei.get("/projects/lab/rules").json()["data"]["rules"]}
    assert agg_rules[rule]["override"] and not def_rules[rule].get("override")
    r = liwei.post("/projects/lab/n/agg/scripts", json={"name": "s.txt", "device_id": ids["TOPO-AGG-01"]})
    assert r.status_code == 200, r.text
    assert len(liwei.get("/projects/lab/n/agg/scripts").json()["data"]["scripts"]) == 1
    assert liwei.get("/projects/lab/scripts").json()["data"]["scripts"] == []
    # 基线只能选本网络的设备
    r = liwei.post("/projects/lab/n/agg/scripts", json={"name": "t.txt", "device_id": ids["TOPO-ATN-A1"]})
    assert r.status_code == 404
    an = {"target": str(ids["TOPO-AGG-01"]), "key": "role", "value": "pe"}
    assert liwei.put("/projects/lab/n/agg/view-annotations", json=an).status_code == 200
    assert len(liwei.get("/projects/lab/n/agg/view-annotations").json()["data"]["items"]) == 1
    assert liwei.get("/projects/lab/view-annotations").json()["data"]["items"] == []

    # 检查结果记到网络：汇总里能看到
    r = liwei.get(f"/projects/lab/n/agg/devices/{ids['TOPO-AGG-01']}/check")
    assert r.status_code == 200
    nets = {n["slug"]: n for n in liwei.get("/projects/lab/networks").json()["data"]["networks"]}
    assert nets["agg"]["counts"]["findings"]["devices_checked"] == 1
    assert nets["agg"]["counts"]["scripts"] == 1 and nets["agg"]["counts"]["ignores"] == 1
    assert nets["agg"]["last_activity"]["actor"] == "liwei"

    # 拓扑：只画本网络；outside=true 给出网络外的对端
    t = liwei.get("/projects/lab/n/agg/topology", params={"outside": "true"}).json()["data"]
    assert sorted(n["id"] for n in t["nodes"]) == ["TOPO-AGG-01", "TOPO-AGG-02", "TOPO-RR-01"]
    assert t["network"]["slug"] == "agg" and t["outside"]["count"] > 0
    assert {lk["peer"]["device"] for lk in t["outside"]["links"]} <= {"TOPO-ATN-A1", "TOPO-ATN-A2"}
    t0 = liwei.get("/projects/lab/topology").json()["data"]
    assert len(t0["nodes"]) == 5 and "outside" not in t0

    # 成员：版本策略、移出（排除）
    r = liwei.put("/projects/lab/networks/agg/members", json={"device_ids": [ids["TOPO-AGG-01"]], "policy": "pin"})
    assert r.status_code == 200 and r.json()["data"]["updated"][0]["policy"] == "pin"
    m = liwei.get("/projects/lab/networks/agg/members").json()["data"]["members"]
    assert {x["name"]: x["policy"] for x in m}["TOPO-AGG-01"] == "pin"
    assert all("mgmt_address" in x for x in m)
    r = liwei.post("/projects/lab/networks/agg/members/remove", json={"device_ids": [ids["TOPO-RR-01"]]})
    assert r.status_code == 200
    assert (
        liwei.post(
            "/projects/lab/networks/default/members/remove", json={"device_ids": [ids["TOPO-RR-01"]]}
        ).status_code
        == 409
    )
    assert liwei.get("/projects/lab/networks/agg/join-rules").json()["data"]["excluded"][0]["name"] == "TOPO-RR-01"
    pv = liwei.post("/projects/lab/networks/agg/join-rules/preview", json={"kind": "name", "pattern": "TOPO-A*"})
    assert pv.json()["data"]["matches"] == 4 and pv.json()["data"]["not_in_network"] == 2

    # 建网建议与采纳
    s = liwei.get("/projects/lab/network-suggestions", params={"basis": "name"}).json()["data"]
    assert {g["key"] for g in s["suggestions"]} == {"name:TOPO-AGG", "name:TOPO-ATN", "name:TOPO-RR"}
    s = liwei.get("/projects/lab/network-suggestions", params={"basis": "components"}).json()["data"]
    assert s["suggestions"][0]["count"] == 5
    assert zhang.post("/projects/lab/network-suggestions/adopt", json={"basis": "name"}).status_code == 403
    r = liwei.post(
        "/projects/lab/network-suggestions/adopt", json={"basis": "name", "keys": ["name:TOPO-ATN"], "with_rules": True}
    )
    assert r.status_code == 200 and r.json()["data"]["created"][0]["network"]["slug"] == "topo-atn"

    # 文件夹、改名、复制、删除
    f = liwei.post("/projects/lab/network-folders", json={"name": "IP RAN"}).json()["data"]
    r = liwei.put("/projects/lab/networks/topo-atn", json={"name": "接入", "folder_id": f["id"], "color": "green"})
    assert r.status_code == 200 and r.json()["data"]["folder"] == "IP RAN"
    assert liwei.put("/projects/lab/networks/topo-atn", json={"color": "pink"}).status_code == 422
    cp = liwei.post("/projects/lab/networks/agg/copy", json={"name": "汇聚副本", "slug": "agg2"}).json()["data"]
    assert cp["copied_from"]["slug"] == "agg" and cp["copied"]["ignores"] == 1 and cp["copied"]["scripts"] == 1
    assert len(liwei.get("/projects/lab/n/agg2/check/ignores").json()["data"]["ignores"]) == 1
    pv = liwei.get("/projects/lab/networks/agg/delete-preview").json()["data"]
    assert pv["deletable"] and pv["counts"]["scripts"] == 1
    assert liwei.delete("/projects/lab/networks/agg", params={"confirm": "错的"}).status_code == 422
    assert zhang.delete("/projects/lab/networks/agg", params={"confirm": "汇聚"}).status_code == 403
    assert liwei.delete("/projects/lab/networks/agg", params={"confirm": "汇聚"}).status_code == 200
    assert liwei.get("/projects/lab/n/agg/devices").status_code == 404
    assert liwei.delete("/projects/lab/networks/default", params={"confirm": "默认网络"}).status_code == 409
    assert len(_ids(liwei, "/projects/lab/devices")) == 5  # 设备不删
    assert liwei.delete(f"/projects/lab/network-folders/{f['id']}").json()["data"]["moved"] == ["topo-atn"]


def test_project_level_routes_and_legacy(full_kb_root: Path, team: Path) -> None:  # noqa: F811
    app = _app()
    liwei = Client(app, "liwei")
    liwei.post("/projects", json={"name": "Lab", "slug": "lab"})
    _upload(liwei, "/projects/lab/configs", FILES[:1])
    did = next(iter(_ids(liwei, "/projects/lab/devices").values()))
    # 项目层的操作不挂网络路径
    assert liwei.delete(f"/projects/lab/n/default/devices/{did}").status_code in (404, 405)
    assert liwei.get("/projects/lab/n/default/model-rules").status_code == 404
    assert liwei.get("/projects/lab/n/default/members").status_code == 404
    # 旧路径（默认项目）落到默认网络
    r = liwei.get("/topology")
    assert r.headers.get("Deprecation") == "true"
    # 只读令牌只能查看
    tok = liwei.post("/tokens", json={"name": "ro", "read_only": True}).json()["data"]["token"]
    ro = Client(app, token=tok)
    assert ro.get("/projects/lab/networks").status_code == 200
    assert ro.post("/projects/lab/networks", json={"name": "x"}).status_code == 403
