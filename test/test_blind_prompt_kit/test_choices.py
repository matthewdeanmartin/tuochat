"""Tests for choice and multi-select components."""

from __future__ import annotations

from tuochat.cli.blind_prompt_kit import ChoiceInput, InteractionContext, MultiSelectInput

from .test_support import FakeIO


def test_choice_input_filters_matches_and_selects_by_number():
    options = [
        "San Antonio",
        "San Diego",
        "San Francisco",
        "San Jose",
        "Santa Ana",
        "Seattle",
    ]
    io = FakeIO(["san", "3"])
    context = InteractionContext(io=io)

    result = ChoiceInput("City.", options).run(context)

    assert result == "San Francisco"
    assert any("5 matches." in line for line in io.outputs)
    assert any("San Francisco selected." == line for line in io.outputs)


def test_multi_select_adds_removes_and_finishes_with_summary():
    io = FakeIO(["1", "3", "remove 1", "done"])
    context = InteractionContext(io=io)

    result = MultiSelectInput("Notifications.", ["Email", "SMS", "Push", "Phone call"]).run(context)

    assert result == ["Push"]
    assert "Email added. 1 selected." in io.outputs
    assert "Push added. 2 selected." in io.outputs
    assert "Email removed. 1 selected." in io.outputs
    assert "Selected: Push." in io.outputs
