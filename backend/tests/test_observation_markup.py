import uuid

import pytest
from app import observation_markup
from app.llm.equipment import EquipmentBox, EquipmentLocation


@pytest.fixture
def markup_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(observation_markup.config, "UPLOADS_DIR", tmp_path)
    return tmp_path


def test_markup_round_trip_preserves_normalized_boxes_and_groups_counts(markup_dir):
    observation_id = uuid.uuid4()
    location = EquipmentLocation(
        available=True,
        model="vision-test",
        items=[
            EquipmentBox("excavator", "Экскаватор", 0.9, (0.1, 0.2, 0.4, 0.8)),
            EquipmentBox("excavator", "Экскаватор", 0.8, (0.5, 0.2, 0.8, 0.8)),
        ],
    )
    observation_markup.save_markup(observation_id, "a" * 64, location)
    result = observation_markup.read_markup(observation_id, "a" * 64)
    assert result["items"][0]["box"] == [0.1, 0.2, 0.4, 0.8]
    assert result["counts"] == [
        {
            "class_key": "excavator",
            "label_ru": "Экскаватор",
            "count": 2,
            "max_confidence": 0.9,
        }
    ]
    assert result["source"] == "aitunnel"
    assert result["model"] == "vision-test"


def test_markup_for_different_photo_is_not_returned(markup_dir):
    key = uuid.uuid4()
    observation_markup.save_markup(key, "a" * 64, EquipmentLocation(available=True))
    assert observation_markup.read_markup(key, "b" * 64) is None
    assert observation_markup.read_markup(uuid.uuid4(), "a" * 64) is None


def test_successful_empty_analysis_stays_distinct_from_missing_markup(markup_dir):
    key = uuid.uuid4()
    observation_markup.save_markup(key, "a" * 64, EquipmentLocation(available=True))
    result = observation_markup.read_markup(key, "a" * 64)
    assert result["available"] is True
    assert result["items"] == []


def test_failed_analysis_does_not_overwrite_previous_result(markup_dir):
    key = uuid.uuid4()
    observation_markup.save_markup(
        key, "a" * 64, EquipmentLocation(available=True, model="good")
    )
    with pytest.raises(ValueError):
        observation_markup.save_markup(
            key, "a" * 64, EquipmentLocation(available=False, error="offline")
        )
    assert observation_markup.read_markup(key, "a" * 64)["model"] == "good"


def test_corrupt_file_and_invalid_identifier_are_ignored(markup_dir):
    key = uuid.uuid4()
    observation_markup.save_markup(key, "a" * 64, EquipmentLocation(available=True))
    next(markup_dir.rglob("*.json")).write_text("{broken", encoding="utf-8")
    assert observation_markup.read_markup(key, "a" * 64) is None
    assert observation_markup.read_markup("../../other", "a" * 64) is None


def test_invalid_geometry_is_rejected_before_saving(markup_dir):
    with pytest.raises(ValueError):
        observation_markup.save_markup(
            uuid.uuid4(),
            "a" * 64,
            EquipmentLocation(
                available=True,
                items=[
                    EquipmentBox("excavator", "Экскаватор", 0.9, (0.8, 0.2, 0.1, 0.7)),
                ],
            ),
        )
    assert not list(markup_dir.rglob("*.json"))
