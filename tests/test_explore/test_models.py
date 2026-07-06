"""Tests for Explore data models."""

from src.core.explore.models import Action, ActionBatch, ActionType, SnapshotMode


def test_action_accepts_enum_values():
    action = Action(action="click", ref="e1", snapshot_v="snapshot_v1")

    assert action.action == ActionType.CLICK
    assert action.ref == "e1"


def test_action_batch_serializes_snapshot_mode():
    batch = ActionBatch(
        actions=[
            Action(
                action=ActionType.SNAPSHOT,
                snapshot_mode=SnapshotMode.COMPACT,
            )
        ]
    )

    dumped = batch.model_dump(mode="json")

    assert dumped["actions"][0]["snapshot_mode"] == "compact"


def test_panel_action_serializes_fields():
    action = Action(
        action=ActionType.PANEL_SET_FIELDS,
        title="Need input",
        fields=[
            {
                "name": "choice",
                "label": "Choose",
                "type": "select",
                "options": ["A", "B"],
            }
        ],
    )

    dumped = action.model_dump(mode="json")

    assert dumped["action"] == "panel_set_fields"
    assert dumped["fields"][0]["options"] == ["A", "B"]
