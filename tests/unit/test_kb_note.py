"""知识库依赖 / 副作用说明（note）三语：写法兼容、回退、校验、仓库内齐全、各输出按语言取值。"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import pytest

from lmesh.core import analysis, change, checks, compare, i18n
from lmesh.core import graph as graphmod
from lmesh.core.kb import load
from lmesh.core.kb.model import NOTE_LANGS, Note
from lmesh.core.kb.validate import validate

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parent.parent.parent
KB_ROOT = ROOT / "knowledge"
CHG = KB_ROOT / "samples" / "change"
FULL = {"zh-CN": "接口引用 ACL", "en": "Interface references the ACL", "pt-BR": "A interface referencia a ACL"}


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return analysis.load_kb(KB_ROOT)


def test_note_forms_and_fallback() -> None:
    n = Note.of("只有中文")
    assert n == {"zh-CN": "只有中文", "en": "只有中文", "pt-BR": "只有中文"}
    assert n.missing() == ["en", "pt-BR"] and n.raw() == "只有中文"
    n = Note.of({"zh-CN": "中", "en": "E"})
    assert n["pt-BR"] == "E" and n.missing() == ["pt-BR"] and n.raw() == {"zh-CN": "中", "en": "E"}
    n = Note.of(FULL)
    assert n == FULL and n.missing() == [] and n.text("pt-BR") == FULL["pt-BR"] and n.text("fr") == FULL["en"]
    assert Note.of(None) == {} and Note.of("") == {} and not Note.of({}) and Note.of("").missing() == []
    assert Note.of(n) is n


def test_note_behaves_as_text_and_json() -> None:
    n = Note.of(FULL)
    assert str(n) == FULL["zh-CN"] and f"{n}" == FULL["zh-CN"]  # 旧的按字符串使用的代码取中文
    assert json.loads(json.dumps(n, ensure_ascii=False)) == FULL
    assert len({n, Note.of(dict(FULL))}) == 1  # 可哈希，可放进集合
    assert pickle.loads(pickle.dumps(n)).given == n.given


def test_i18n_localizes_text_params() -> None:
    n = Note.of(FULL)
    assert i18n.pick(n, "en") == FULL["en"] and i18n.pick("x", "en") == "x" and i18n.pick(None, "en") == ""
    assert FULL["pt-BR"] in i18n.t("guard.mutex", "pt-BR", a="a", b="b", note=n)
    assert FULL["en"] in i18n.t("guard.mutex", "en", a="a", b="b", note=n)
    assert i18n.localize({"note": {}, "k": {"name": "x"}}, "en") == {"note": "", "k": {"name": "x"}}
    ref = {"key": "x", "params": {"note": n}}
    assert checks.render_text(ref, "en", {"x": {"zh-CN": "{note}", "en": "{note}"}}) == FULL["en"]


def test_repo_notes_have_three_languages(kb) -> None:  # type: ignore[no-untyped-def]
    rules = list(kb.deps) + [s for p in kb.profiles.values() for s in p.side_effects]
    noted = [r for r in rules if r.note]
    assert len(noted) >= 50
    bad = [f"{r.src} → {r.dst}: {r.note.missing()}" for r in noted if r.note.missing()]
    assert not bad, "依赖说明缺少语言：\n" + "\n".join(bad)
    assert all(set(r.note) == set(NOTE_LANGS) and all(r.note.values()) for r in noted)
    assert not [i for i in validate(kb) if "note_lang" in i.code]


def test_validate_warns_missing_language(tmp_path: Path) -> None:
    (tmp_path / "kb.yaml").write_text("kb_version: 0.0.1\ndomains: [x]\n", encoding="utf-8")
    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "x.yaml").write_text(
        "domain: x\nnodes:\n  a: {type: object}\n  b: {type: object}\n"
        "deps:\n  - {kind: reference, from: a, to: b, note: 只有中文}\n"
        "  - {kind: reference, from: b, to: a, note: {zh-CN: 中, en: E, pt-BR: P}}\n",
        encoding="utf-8",
    )
    issues = [i for i in validate(load(tmp_path)) if i.code == "dep.note_lang"]
    assert len(issues) == 1 and issues[0].level == "warning" and "en, pt-BR" in issues[0].message


def test_graph_edges_carry_three_language_note(kb) -> None:  # type: ignore[no-untyped-def]
    side = compare.side_from_text((CHG / "atn-add-vrf.cfg").read_text(encoding="utf-8"), kb, None, "x")
    edges = graphmod.to_json(side.graph)["edges"]
    deps = [e for e in edges if e["kind"] in ("reference", "prerequisite") and e["note"]]
    assert deps and all(set(e["note"]) == set(NOTE_LANGS) for e in deps)
    assert all(e["note"] == {} for e in edges if e["kind"] == "contains")


def test_change_after_note_is_three_language(kb) -> None:  # type: ignore[no-untyped-def]
    a = compare.side_from_text((CHG / "atn-base.cfg").read_text(encoding="utf-8"), kb, None, "a")
    b = compare.side_from_text((CHG / "atn-bind-vpn.cfg").read_text(encoding="utf-8"), kb, None, "b")
    r = change.change(a, b, kb, rollback=False)
    side = next(d for d in r["ops"] if d["action"] == "side_effect")
    notes = [x["note"] for x in side["after"] if x["kind"] == "side_effect"]
    assert notes and "vpn-instance" in notes[0]["en"] and notes[0]["pt-BR"].startswith("No Huawei")
    # 整个结果可以序列化成 JSON，note 是对象
    data = json.loads(json.dumps(r, ensure_ascii=False, default=str))
    assert all(isinstance(x["note"], dict) for d in data["ops"] for x in d["after"])
