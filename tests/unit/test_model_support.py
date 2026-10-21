"""未支持型号的处理（M8-7，REQ-044）：匹配程度、只允许同厂商 / 同平台族、试解析排序、型号规则的优先级、
导入时手工选择与“记住”、重新解析沿用手工选择、认不出厂商只存原文（文本对比）、申请支持 → 派生 Profile → 规则改指向并
重新解析、迁移 0011。NE8000 用合成样本（tests/inputs/configs/ne8000/，华为写法，版本 V800R022 不匹配任何 Profile 的版本规则）。"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from sqlalchemy import select, text

from lmesh.core import analysis, history, importer, model_support, review, store, workbench
from lmesh.core.kb.model import Profile, ProfileEntry
from lmesh.core.store.models import Device, ModelRule, Project, ReviewItem

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parent.parent.parent
KB_ROOT = ROOT / "knowledge"
INPUTS = ROOT / "tests" / "inputs" / "configs"
NE1 = (INPUTS / "ne8000" / "ne8000-x8-01.cfg").read_text(encoding="utf-8")
NE2 = (INPUTS / "ne8000" / "ne8000-x8-02.cfg").read_text(encoding="utf-8")
OTHER = (INPUTS / "other" / "edge-mx-01.conf").read_text(encoding="utf-8")
ATN = (KB_ROOT / "samples" / "change" / "atn-base.cfg").read_text(encoding="utf-8")
ASR = (KB_ROOT / "samples" / "change" / "asr920-base.cfg").read_text(encoding="utf-8")
R25, R23, ASR_P = "huawei-atn-v800r025", "huawei-atn-v800r023", "cisco-iosxe-asr920-17.15"


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


@pytest.fixture
def url(db_url: str) -> str:
    store.upgrade(db_url)
    return db_url


def _imp(url: str, name: str, text_: str, root: Path = KB_ROOT, **kw):  # type: ignore[no-untyped-def]
    return importer.import_sources([(name, text_.encode())], url, "basic", root, actor="tester", keep=50, **kw)[0]


def _dev(url: str, name: str) -> Device:
    with store.session(url) as s:
        d = s.scalar(select(Device).where(Device.name == name))
        assert d is not None
        s.expunge(d)
        return d


# ---------------------------------------------------------------- 纯逻辑


def test_match_level_of_samples(kb) -> None:  # type: ignore[no-untyped-def]
    ne = model_support.choose(kb, NE1, "NE8000-X8-01")
    assert (ne.profile, ne.source, ne.level) == (R25, "fallback", "approx")  # 只按厂商套用 fallback
    atn = model_support.choose(kb, ATN, "ATN-CHANGE-01")
    assert (atn.profile, atn.source, atn.level) == (R25, "auto", "exact")  # 版本规则命中
    other = model_support.choose(kb, OTHER, "edge-mx-01")
    assert (other.profile, other.source, other.level, other.vendor) == ("", "none", "none", "")
    assert model_support.level_of("manual") == model_support.level_of("rule") == "approx"


def test_only_same_vendor_and_family(kb) -> None:  # type: ignore[no-untyped-def]
    det = model_support.detect(NE1)
    assert model_support.candidates(kb, det) == [R23, R25]
    assert not model_support.allowed(kb, det, ASR_P)
    with pytest.raises(model_support.ModelError) as e:
        model_support.choose(kb, NE1, "NE8000-X8-01", override=ASR_P)
    assert e.value.key == "import.profile_not_allowed"
    # 认不出厂商：可在全部 Profile 中选，厂商记为所选 Profile 的厂商
    unk = model_support.detect(OTHER)
    assert model_support.candidates(kb, unk) == sorted(kb.profiles)
    ch = model_support.choose(kb, OTHER, "edge-mx-01", override=ASR_P)
    assert (ch.source, ch.vendor) == ("manual", "cisco")
    # Nokia 两种格式是不同平台族，不能混用
    md = (INPUTS / "nokia" / "baseline-md-hardened.cfg").read_text(encoding="utf-8")
    nd = model_support.detect(md)
    assert nd.family == "nokia-sros-md" and model_support.candidates(kb, nd) == ["nokia-sros-md-7750-25.10"]
    assert not model_support.allowed(kb, nd, "nokia-sros-classic-7750-25.10")


def test_trial_ranking(kb) -> None:  # type: ignore[no-untyped-def]
    rows = model_support.trial(kb, NE1)
    assert [r["profile"] for r in rows] == [R25, R23]  # 比例相同：fallback 在前
    assert rows[0]["unknown"] == 2 and rows[0]["ratio"] == round(rows[0]["command"] / (rows[0]["command"] + 2), 4)
    # 派生一个把 OSPF 接口开销标为不支持的 Profile：它识别出的命令更少，排在后面
    kb2 = copy.copy(kb)
    kb2.profiles = dict(kb.profiles)
    node = next(
        n for c in kb.cards.values() if c.family == "huawei-vrp8" and c.syntax.startswith("ospf cost") for n in c.maps
    )
    kb2.profiles["huawei-lab"] = Profile(
        id="huawei-lab",
        vendor="huawei",
        family="huawei-vrp8",
        inherits=R25,
        entries={node: ProfileEntry(node=node, supported=False)},
    )
    rows = model_support.trial(kb2, NE1)
    assert [r["profile"] for r in rows] == [R25, R23, "huawei-lab"]
    lab = rows[-1]
    assert lab["unsupported"] >= 1 and lab["ratio"] < rows[0]["ratio"]
    # 版本规则命中的排在 fallback 之前
    assert [r["profile"] for r in model_support.trial(kb, ATN.replace("V800R025", "V800R023"))][:1] == [R23]


def test_suggest_rule() -> None:
    assert model_support.suggest_rule("NE8000-X8-01", "V800R022C10SPC300") == {
        "name_pattern": "NE8000-X8-*",
        "version": "V800R022",
        "feature": "",
    }
    assert model_support.suggest_rule("asr920", "16.12.04")["version"] == r"^16\.12"
    assert model_support.suggest_rule("core", "")["name_pattern"] == "core"


def test_rule_priority(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    with store.session(url) as s:
        p = Project(name="p", slug="p")
        s.add(p)
        s.flush()
        pid = p.id
    g_old = model_support.create_rule(url, kb, None, {"name_pattern": "NE8000-*", "profile": R23}, "m")
    g_more = model_support.create_rule(
        url, kb, None, {"name_pattern": "NE8000-*", "version": "V800R022", "profile": R25}, "m"
    )
    det = model_support.detect(NE1)
    with store.session(url) as s:
        rules = model_support.ordered_rules(s, pid)
        assert [r.id for r in rules] == [g_more["id"], g_old["id"]]  # 条件多的优先
        assert model_support.match_rule(kb, rules, "NE8000-X8-01", det, NE1).id == g_more["id"]
    proj = model_support.create_rule(url, kb, pid, {"feature": r"^ ospf cost maximum$", "profile": R23}, "u")
    with store.session(url) as s:
        rules = model_support.ordered_rules(s, pid)
        assert rules[0].id == proj["id"]  # 本项目规则优先于全局规则（即使条件少）
        ch = model_support.choose(kb, NE1, "NE8000-X8-01", rules)
        assert (ch.profile, ch.source, ch.rule_id) == (R23, "rule", proj["id"])
        assert model_support.match_rule(kb, rules, "ATN-1", model_support.detect(ATN), ATN) is None
    # 停用的规则不生效；全局规则不能被普通用户改（can_global=False）
    model_support.update_rule(url, kb, proj["id"], pid, {"enabled": False}, can_global=False)
    with pytest.raises(model_support.ModelError) as e:
        model_support.update_rule(url, kb, g_old["id"], pid, {"note": "x"}, can_global=False)
    assert e.value.kind == "forbidden"
    with store.session(url) as s:
        assert (
            model_support.choose(kb, NE1, "NE8000-X8-01", model_support.ordered_rules(s, pid)).rule_id == g_more["id"]
        )
    # 校验：至少一个条件、正则有效、只能指向同厂商的 Profile
    for body, key in (
        ({"profile": R25}, "model.rule_no_condition"),
        ({"version": "(", "profile": R25}, "model.regex_invalid"),
        ({"vendor": "cisco", "name_pattern": "x", "profile": R25}, "import.profile_not_allowed"),
        ({"name_pattern": "x", "profile": "nope"}, "model.profile_unknown"),
    ):
        with pytest.raises(model_support.ModelError) as e:
            model_support.create_rule(url, kb, pid, body, "u")
        assert e.value.key == key
    listed = model_support.list_rules(url, pid)
    assert [r["id"] for r in listed["global"]] == [g_more["id"], g_old["id"]] and listed["project"][0][
        "enabled"
    ] is False


# ---------------------------------------------------------------- 导入与重新解析


def test_import_manual_remember_and_reparse(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    auto = _imp(url, "ne1.cfg", NE1)
    assert (auto.profile, auto.profile_source, auto.match_level) == (R25, "fallback", "approx")
    # 手工选 R023 并“记住”为本项目规则：规则命中这台设备，来源记为 rule
    r = _imp(
        url,
        "ne1b.cfg",
        NE1 + "\n",
        choices={"ne1b.cfg": {"profile": R23, "remember": {"scope": "project"}}},
    )
    assert r.ok and (r.profile, r.profile_source) == (R23, "rule") and r.rule_created == r.rule_id
    with store.session(url) as s:
        rule = s.get(ModelRule, r.rule_id)
        assert (rule.name_pattern, rule.version, rule.vendor) == ("NE8000-X8-*", "V800R022", "huawei")
    # 第二台按规则自动选
    r2 = _imp(url, "ne2.cfg", NE2)
    assert (r2.profile, r2.profile_source, r2.rule_id) == (R23, "rule", r.rule_id)
    # 跨厂商的手工选择被拒绝
    bad = _imp(url, "ne3.cfg", NE2.replace("NE8000-X8-02", "NE8000-X8-03"), profile=ASR_P)
    assert not bad.ok and bad.error == "import.profile_not_allowed"
    # 设备页手工更换：之后的重新解析与导入沿用手工选择
    dev = _dev(url, "NE8000-X8-02")
    out = model_support.set_device_profile(url, KB_ROOT, kb, dev.id, R25, "tester")
    assert (out["profile"], out["profile_source"], out["approx"]) == (R25, "manual", True)
    workbench.rebuild_all(url, KB_ROOT)
    assert (_dev(url, "NE8000-X8-02").profile, _dev(url, "NE8000-X8-02").profile_source) == (R25, "manual")
    again = _imp(url, "ne2-again.cfg", NE2 + "\n#\n")
    assert (again.profile, again.profile_source) == (R25, "manual")
    # 改回自动：规则重新生效
    back = model_support.set_device_profile(url, KB_ROOT, kb, dev.id, None, "tester")
    assert (back["profile"], back["profile_source"]) == (R23, "rule")
    # 设备列表带来源与未识别比例；近似设备的变更 / 翻译下发前提示
    rows = {d["name"]: d for d in workbench.device_rows(url, kb.version)}
    assert rows["NE8000-X8-02"]["match_level"] == "approx" and rows["NE8000-X8-02"]["unknown_ratio"] > 0
    assert model_support.approx_note(url, dev.id)["profile"] == R23
    cand = model_support.device_candidates(url, kb, dev.id)
    assert cand["recommended"] == R25 and [c["profile"] for c in cand["candidates"]] == [R25, R23]
    assert cand["auto"]["source"] == "rule"


def test_unknown_vendor_raw_only(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    skipped = _imp(url, "edge.conf", OTHER)
    assert not skipped.ok and skipped.error == "import.unknown_vendor"
    r = _imp(url, "edge.conf", OTHER, keep_unsupported=True)
    assert r.ok and r.raw_only and (r.vendor, r.profile, r.profile_source, r.match_level) == ("", "", "none", "none")
    assert r.device == "edge-mx-01"
    dev = _dev(url, "edge-mx-01")
    with store.session(url) as s:
        ver = max(s.get(Device, dev.id).versions, key=lambda v: v.id)
        assert ver.structured is None and "FakeHashValueForTests" not in ver.raw_text  # 按通用规则脱敏
    rows = {d["name"]: d for d in workbench.device_rows(url, kb.version)}
    assert rows["edge-mx-01"]["unsupported"] and rows["edge-mx-01"]["profile_source"] == "none"
    # 重新解析仍只存原文；第二个版本可以做文本对比（没有图差异）
    assert workbench.rebuild_all(url, KB_ROOT, device_ids=[dev.id])["parse_failed"] == 1
    _imp(url, "edge2.conf", OTHER.replace("mtu 9192", "mtu 9216"), keep_unsupported=True)
    d = history.diff(url, dev.id, kb)
    assert d["raw_only"] and d["items"] == [] and d["text"]["stats"]["added"] == 1
    # 认不出厂商时也可以手工选一个 Profile
    m = _imp(url, "edge3.conf", OTHER.replace("edge-mx-01", "edge-mx-02"), choices={"edge3.conf": {"profile": ASR_P}})
    assert m.ok and (m.profile, m.profile_source, m.vendor) == (ASR_P, "manual", "cisco")


def test_devices_from_db_skips_raw_only(url: str, kb) -> None:  # type: ignore[no-untyped-def]
    """AI 查询、表格导出、生成配置查重取全部设备时跳过只存原文的设备；点名时按找不到报告（不再 500）。"""
    _imp(url, "atn.cfg", ATN)
    _imp(url, "edge.conf", OTHER, keep_unsupported=True)
    found, missing = history.devices_from_db(url, kb, None)
    assert [d.name for d in found] != [] and "edge-mx-01" not in [d.name for d in found] and missing == []
    found, missing = history.devices_from_db(url, kb, ["edge-mx-01"])
    assert found == [] and missing == ["edge-mx-01"]


# ---------------------------------------------------------------- 申请支持与派生


@pytest.mark.kb_write
def test_request_derive_retarget(url: str, full_kb_root: Path) -> None:
    root = full_kb_root / "knowledge"
    kb = analysis.load_kb(root)
    r1 = _imp(url, "ne1.cfg", NE1, root, choices={"ne1.cfg": {"profile": R25, "remember": {"scope": "project"}}})
    r2 = _imp(url, "ne2.cfg", NE2, root)
    assert r1.profile_source == r2.profile_source == "rule"
    dev = _dev(url, "NE8000-X8-01")
    req = model_support.request_support(url, dev.id, "liwei", "NE8000 X8", "城域汇聚")
    with store.session(url) as s:
        item = s.get(ReviewItem, req["id"])
        assert item.kind == "suggestion" and item.payload["kind"] == "model"
        assert item.payload["unknown"] == 2 and item.payload["patterns"] and item.payload["profile_source"] == "rule"
    with pytest.raises(model_support.ModelError) as e:
        model_support.retarget(url, root, kb, req["id"], "kbmaint")
    assert e.value.key == "model.not_derived"
    d = model_support.derive(
        url,
        root,
        req["id"],
        {"id": "huawei-ne8000-v800r022", "base": R25, "title": "华为 NE8000 V800R022", "version": "V800R022"},
        "kbmaint",
    )
    assert d["profile"] == "huawei-ne8000-v800r022"
    kb = analysis.load_kb(root)
    assert kb.profiles["huawei-ne8000-v800r022"].inherits == R25
    st = model_support.support_status(url, root, kb, req["id"])
    assert st["derived"]["profile"] == "huawei-ne8000-v800r022"
    assert [x["name"] for x in st["plan"]["devices"]] == ["NE8000-X8-01", "NE8000-X8-02"] and st["plan"]["rules"][0][
        "change"
    ]
    out = model_support.retarget(url, root, kb, req["id"], "kbmaint")
    assert out["rules_changed"] == [r1.rule_id] and out["rule_created"] is None and len(out["devices"]) == 2
    for name in ("NE8000-X8-01", "NE8000-X8-02"):
        dv = _dev(url, name)
        # 派生 Profile 的版本规则命中，但型号规则仍优先：来源为 rule，指向派生的 Profile
        assert (dv.profile, dv.profile_source) == ("huawei-ne8000-v800r022", "rule")
    assert review.get(url, req["id"])["status"] == "approved"


@pytest.mark.kb_write
def test_retarget_creates_rule_when_none(url: str, full_kb_root: Path) -> None:
    root = full_kb_root / "knowledge"
    kb = analysis.load_kb(root)
    _imp(url, "ne1.cfg", NE1, root)  # fallback，没有型号规则
    dev = _dev(url, "NE8000-X8-01")
    req = model_support.request_support(url, dev.id, "liwei", "NE8000 X8", "")
    model_support.derive(url, root, req["id"], {"id": "huawei-ne8000-lab", "base": R25}, "kbmaint")
    kb = analysis.load_kb(root)
    out = model_support.retarget(url, root, kb, req["id"], "kbmaint")
    assert out["rule_created"]["scope"] == "global" and out["rule_created"]["name_pattern"] == "NE8000-X8-*"
    assert _dev(url, "NE8000-X8-01").profile == "huawei-ne8000-lab"
    with pytest.raises(model_support.ModelError) as e:
        model_support.derive(url, root, req["id"], {"id": "x-y", "base": R25}, "kbmaint")
    assert e.value.key == "review.already_decided"


def test_migration_0011_from_0010(db_url: str) -> None:
    from tests.unit.test_project_refs import _upgrade_to

    _upgrade_to(db_url, "0010")
    with store.get_engine(db_url).begin() as c:
        c.execute(
            text(
                "INSERT INTO devices (id, name, vendor, platform, sw_version, profile, created_at, origin) VALUES "
                "(1, 'a', 'huawei', '', 'V800R025', 'huawei-atn-v800r025', :n, 'import'), "
                "(2, 'b', 'nokia', '', '', '', :n, 'import')"
            ),
            {"n": "2026-10-19 00:00:00"},
        )
    store._UPGRADED.discard(db_url)
    store.upgrade(db_url)
    assert "model_rules" in store.table_names(db_url)
    with store.session(db_url) as s:
        got = {d.name: (d.profile_source, d.profile_rule_id) for d in s.scalars(select(Device))}
    assert got == {"a": ("auto", None), "b": ("none", None)}
