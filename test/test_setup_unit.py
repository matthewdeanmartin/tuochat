"""Unit tests for CLI setup helpers."""

from __future__ import annotations

from unittest.mock import patch

from tuochat.cli import setup
from tuochat.config import TuochatConfig
from tuochat.constants import CLASSIFICATION_ANY, CLASSIFICATION_UNCLASSIFIED, CLASSIFICATION_UNKNOWN


def test_get_valid_classifications_prepends_unknown():
    cfg = TuochatConfig()
    cfg.classification.markings = ["PUBLIC", "SECRET"]

    assert setup.get_valid_classifications(cfg) == [
        CLASSIFICATION_UNKNOWN,
        CLASSIFICATION_UNCLASSIFIED,
        "PUBLIC",
        "SECRET",
    ]


def test_normalized_max_classifications_resolves_case_and_deduplicates():
    cfg = TuochatConfig()
    cfg.classification.markings = ["Public", "Secret"]
    cfg.classification.max_markings = [" secret ", "PUBLIC", "secret"]

    assert setup.normalized_max_classifications(cfg) == ["SECRET", "PUBLIC"]


def test_normalized_max_classifications_short_circuits_for_any():
    cfg = TuochatConfig()
    cfg.classification.markings = ["Public", "Secret"]
    cfg.classification.max_markings = ["Secret", CLASSIFICATION_ANY, "Public"]

    assert setup.normalized_max_classifications(cfg) == [CLASSIFICATION_ANY]


def test_classification_within_max_rejects_marks_above_configured_limit():
    cfg = TuochatConfig()
    cfg.classification.markings = ["PUBLIC", "INTERNAL", "SECRET"]
    cfg.classification.max_markings = ["INTERNAL"]

    assert setup.classification_within_max(cfg, "PUBLIC") is True
    assert setup.classification_within_max(cfg, "SECRET") is False


def test_classification_within_max_always_allows_unknown():
    cfg = TuochatConfig()
    cfg.classification.markings = ["PUBLIC", "SECRET"]
    cfg.classification.max_markings = ["PUBLIC"]

    assert setup.classification_within_max(cfg, CLASSIFICATION_UNKNOWN) is True


def test_classification_limit_message_lists_configured_maxima():
    cfg = TuochatConfig()
    cfg.classification.markings = ["PUBLIC", "SECRET"]
    cfg.classification.max_markings = ["PUBLIC", "SECRET"]

    assert setup.classification_limit_message(cfg) == "No classifications higher than PUBLIC (Public), SECRET (Secret)."


def test_resolve_classification_choice_accepts_index_and_case_insensitive_value():
    cfg = TuochatConfig()
    cfg.classification.markings = ["PUBLIC", "CUI", "SECRET"]

    assert setup.resolve_classification_choice(cfg, "2") == CLASSIFICATION_UNCLASSIFIED
    assert setup.resolve_classification_choice(cfg, "secret") == "SECRET"
    assert setup.resolve_classification_choice(cfg, "controlled unclassified information") == "CUI"
    assert setup.resolve_classification_choice(cfg, "99") is None


def test_resolve_classification_choice_accepts_exact_numeric_marking_before_picker_index():
    cfg = TuochatConfig()
    cfg.classification.markings = ["2", "SBU"]

    assert setup.resolve_classification_choice(cfg, "2") == "2"
    assert setup.resolve_classification_choice(cfg, "sbu") == "SBU"


def test_prompt_classification_offers_unclassified_even_when_no_markings_are_configured(capsys):
    cfg = TuochatConfig()
    cfg.classification.markings = []

    with patch("tuochat.cli.setup.prompt_input", return_value="2"):
        assert setup.prompt_classification(cfg) == CLASSIFICATION_UNCLASSIFIED

    captured = capsys.readouterr()
    assert CLASSIFICATION_UNKNOWN in captured.out
    assert CLASSIFICATION_UNCLASSIFIED in captured.out


def test_prompt_classification_retries_after_limit_message(capsys):
    cfg = TuochatConfig()
    cfg.classification.markings = ["PUBLIC", "SECRET"]
    cfg.classification.max_markings = ["PUBLIC"]

    with patch("tuochat.cli.setup.prompt_input", side_effect=["4", "3"]):
        chosen = setup.prompt_classification(cfg)

    assert chosen == "PUBLIC"
    captured = capsys.readouterr()
    assert "Document classification for this conversation:" in captured.out
    assert "PUBLIC (Public)" in captured.out
    assert "No classifications higher than PUBLIC (Public)." in captured.err
