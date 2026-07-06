"""Tests for Explore experience manager."""

from src.core.explore.experience import ExperienceManager
from src.core.explore.models import Action, ElementInfo, ExploreExperience


def _experience(exp_id="exp1", task="在京东搜索手机"):
    return ExploreExperience(
        id=exp_id,
        task=task,
        site="jd",
        url_pattern="https://www.jd.com/*",
        actions=[
            Action(action="fill", ref="e1", value="手机"),
            Action(action="click", ref="e2"),
        ],
        element_map={
            "e1": ElementInfo(selector="#kw", role="textbox", name="搜索"),
            "e2": ElementInfo(selector="#search", role="button", name="搜索"),
        },
    )


def test_save_experience(tmp_path):
    manager = ExperienceManager(tmp_path)
    exp = _experience()

    saved = manager.save(exp)

    assert saved.id == "exp1"
    assert (tmp_path / "exp1.json").exists()


def test_find_similar(tmp_path):
    manager = ExperienceManager(tmp_path)
    manager.save(_experience())

    found = manager.find_similar("在京东搜索手机壳", "jd")

    assert found is not None
    assert found.id == "exp1"


def test_upgrade_to_skill(tmp_path):
    manager = ExperienceManager(tmp_path)
    exp = _experience()
    exp.success_count = 3
    exp.confidence = 0.85
    manager.save(exp)

    skill = manager.try_upgrade_to_skill("exp1")

    assert skill is not None
    assert skill.from_explore is True
    assert "do_fill(page, ['#kw'], keyword)" in skill.source_code
    assert "do_click(page, ['#search'])" in skill.source_code


def test_confidence_update(tmp_path):
    manager = ExperienceManager(tmp_path)
    manager.save(_experience())

    manager.update_confidence("exp1", success=True)
    assert manager.find_similar("在京东搜索手机", "jd").confidence == 0.75

    manager.update_confidence("exp1", success=False)
    updated = manager.find_similar("在京东搜索手机", "jd")
    assert updated.fail_count == 1
    assert updated.confidence == 0.6
