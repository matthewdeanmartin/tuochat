"""Tests for temporal components and composed form flows."""

from __future__ import annotations

from datetime import date

from tuochat.cli.blind_prompt_kit import DateInput, FormField, InteractionContext, SequentialForm
from tuochat.cli.blind_prompt_kit.exceptions import StepBack

from .test_support import FakeIO, ScriptedComponent


def test_date_input_parses_relative_weekday():
    io = FakeIO(["next monday"])
    context = InteractionContext(io=io)

    result = DateInput("Start date?", reference_date=date(2026, 4, 10)).run(context)

    assert result == date(2026, 4, 13)
    assert "Start date: April 13, 2026." in io.outputs


def test_sequential_form_can_go_back_and_reenter_previous_field():
    io = FakeIO([])
    context = InteractionContext(io=io)
    form = SequentialForm(
        title="Trip details",
        fields=[
            FormField(name="destination", component=ScriptedComponent(["Boston", "Chicago"]), label="Destination"),
            FormField(
                name="start_date",
                component=ScriptedComponent([StepBack("back"), date(2026, 4, 12)]),
                label="Start date",
            ),
        ],
        confirm=False,
    )

    result = form.run(context)

    assert result == {"destination": "Chicago", "start_date": date(2026, 4, 12)}
    assert any("1 of 2. Destination" in line for line in io.outputs)
    assert any("2 of 2. Start date" in line for line in io.outputs)
