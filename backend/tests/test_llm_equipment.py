"""Проверка нормализации ответа модели при ИИ-разметке техники (без обращения к сети)."""

from __future__ import annotations

from app.llm import equipment

CLASSES = [
    {"class_key": "dump_truck", "label_ru": "Самосвал", "description": "", "english_hints": []},
    {"class_key": "excavator", "label_ru": "Экскаватор", "description": "", "english_hints": []},
]


def test_box_in_thousandths_is_converted_to_fractions() -> None:
    assert equipment._coerce_box([100, 200, 500, 800]) == (0.1, 0.2, 0.5, 0.8)


def test_box_already_in_fractions_is_accepted() -> None:
    assert equipment._coerce_box([0.1, 0.2, 0.5, 0.8]) == (0.1, 0.2, 0.5, 0.8)


def test_reversed_corners_are_swapped_and_out_of_range_is_clamped() -> None:
    assert equipment._coerce_box([500, 800, 100, 200]) == (0.1, 0.2, 0.5, 0.8)
    assert equipment._coerce_box([-50, 0, 400, 1200]) == (0.0, 0.0, 0.4, 1.0)


def test_degenerate_or_whole_frame_boxes_are_rejected() -> None:
    assert equipment._coerce_box([100, 100, 105, 500]) is None  # уже 1% кадра
    assert equipment._coerce_box([0, 0, 1000, 1000]) is None  # рамка на весь кадр
    assert equipment._coerce_box([1, 2, 3]) is None
    assert equipment._coerce_box("box") is None


def test_gemini_box_2d_is_y_first() -> None:
    # [ymin, xmin, ymax, xmax] -> (x1, y1, x2, y2)
    assert equipment._coerce_box([100, 200, 500, 800], y_first=True) == (0.2, 0.1, 0.8, 0.5)


def test_normalize_prefers_box_2d_over_box() -> None:
    parsed = {
        "objects": [
            {
                "class_key": "excavator",
                "confidence": 0.9,
                "box_2d": [100, 200, 500, 800],
                "box": [0, 0, 300, 300],
            }
        ]
    }
    items = equipment._normalize(parsed, CLASSES)
    assert [item.box for item in items] == [(0.2, 0.1, 0.8, 0.5)]


def test_unknown_class_is_dropped_not_remapped() -> None:
    parsed = {
        "objects": [
            {"class_key": "forklift", "confidence": 0.9, "box": [100, 100, 400, 400]},
            {"class_key": "dump_truck", "confidence": 0.8, "box": [100, 100, 400, 400]},
        ]
    }
    items = equipment._normalize(parsed, CLASSES)
    assert [item.class_key for item in items] == ["dump_truck"]
    assert items[0].label_ru == "Самосвал"


def test_duplicate_boxes_of_same_class_are_merged_but_other_classes_kept() -> None:
    parsed = {
        "objects": [
            {"class_key": "excavator", "confidence": 0.6, "box": [100, 100, 400, 400]},
            {"class_key": "excavator", "confidence": 0.9, "box": [105, 102, 402, 398]},
            {"class_key": "dump_truck", "confidence": 0.7, "box": [100, 100, 400, 400]},
        ]
    }
    items = equipment._normalize(parsed, CLASSES)
    assert sorted((item.class_key, item.confidence) for item in items) == [
        ("dump_truck", 0.7),
        ("excavator", 0.9),
    ]


def test_confidence_given_in_percent_is_rescaled() -> None:
    assert equipment._coerce_confidence(85) == 0.85
    assert equipment._coerce_confidence("bad") == 0.5
    assert equipment._coerce_confidence(0.4) == 0.4
    assert equipment._coerce_confidence(1.7) == 0.017


def test_garbage_payload_yields_empty_list() -> None:
    assert equipment._normalize({"objects": "nothing"}, CLASSES) == []
    assert equipment._normalize({}, CLASSES) == []
