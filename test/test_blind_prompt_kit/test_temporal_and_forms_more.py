"""Additional tests for temporal helpers and form flows."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from tuochat.cli.blind_prompt_kit import DateRangeInput, DateTimeInput, DurationInput, FormField, InteractionContext
from tuochat.cli.blind_prompt_kit.forms import NonlinearForm, SequentialForm, Wizard, WizardSection
from tuochat.cli.blind_prompt_kit.temporal import (
    parse_date_text,
    parse_duration_text,
    parse_time_text,
    render_date,
    render_time,
)

from .test_support import FakeIO, ScriptedComponent


def test_temporal_helpers_parse_direct_values():
    parsed_date, date_error = parse_date_text("04/05/2026")
    noon, noon_error = parse_time_text("noon")
    duration, duration_error = parse_duration_text("1 hour 15 minutes")

    assert parsed_date is None
    assert "ambiguous" in (date_error or "")
    assert noon == time(hour=12)
    assert noon_error is None
    assert duration == timedelta(hours=1, minutes=15)
    assert duration_error is None
    assert render_date(date(2026, 4, 11)) == "April 11, 2026"
    assert render_time(time(hour=15, minute=30)) == "3:30 PM"


def test_datetime_input_composes_date_and_time():
    io = FakeIO(["2026-04-11", "3pm"])
    context = InteractionContext(io=io)

    result = DateTimeInput("Meeting time?").run(context)

    assert result == datetime(2026, 4, 11, 15, 0)
    assert "Meeting time?" in io.outputs
    assert "April 11, 2026 at 3 PM." in io.outputs


def test_duration_input_supports_step_mode():
    io = FakeIO(["step", "1", "30"])
    context = InteractionContext(io=io)

    result = DurationInput("How long?").run(context)

    assert result == timedelta(hours=1, minutes=30)
    assert "Duration: 1 hours 30 minutes." in io.outputs


def test_date_range_input_supports_open_bounds_and_step_retry():
    direct = DateRangeInput(
        "Window?",
        reference_date=date(2026, 4, 10),
        allow_open_end=True,
        allow_open_start=True,
    )

    assert direct.parse_direct("open end").render() == "From April 10, 2026 onward."
    assert direct.parse_direct("open start").render() == "Through April 10, 2026."

    io = FakeIO(["step", "2026-04-10", "2026-04-09", "2026-04-12"])
    context = InteractionContext(io=io)

    result = DateRangeInput("Travel dates?", reference_date=date(2026, 4, 10)).run(context)

    assert result.render() == "April 10, 2026 through April 12, 2026."
    assert "End date must be after start date." in io.errors


def test_sequential_form_supports_confirmation_change_loop():
    io = FakeIO(["no", "change 1", "yes"])
    context = InteractionContext(io=io)
    form = SequentialForm(
        title="Trip details",
        fields=[
            FormField(name="destination", component=ScriptedComponent(["Boston", "Chicago"]), label="Destination"),
            FormField(name="seat", component=ScriptedComponent(["Window", "Aisle"]), label="Seat"),
        ],
        confirm=True,
    )

    result = form.run(context)

    assert result == {"destination": "Chicago", "seat": "Aisle"}
    assert any(line.startswith("Summary.\n") for line in io.outputs)
    assert any("Destination: Chicago" in line for line in io.outputs)
    assert any("Seat: Aisle" in line for line in io.outputs)


def test_nonlinear_form_and_wizard_cover_menu_paths():
    io = FakeIO(["summary", "field destination", "done"])
    context = InteractionContext(io=io)
    form = NonlinearForm(
        title="Booking",
        fields=[
            FormField(name="destination", component=ScriptedComponent(["Berlin"]), label="Destination"),
            FormField(name="notes", component=ScriptedComponent(["Late arrival"]), label="Notes"),
        ],
    )

    result = form.run(context)

    wizard_io = FakeIO([])
    wizard_context = InteractionContext(io=wizard_io)
    wizard = Wizard(
        title="Setup wizard",
        sections=(
            WizardSection(
                title="Basics",
                form=SequentialForm(
                    title="Basics",
                    fields=[FormField(name="name", component=ScriptedComponent(["Ada"]))],
                    confirm=False,
                ),
            ),
        ),
    )
    wizard_result = wizard.run(wizard_context)

    assert result == {"destination": "Berlin"}
    assert any(line.startswith("Booking.\n") for line in io.outputs)
    assert wizard_result == {"name": "Ada"}
    assert "Setup wizard" in wizard_io.outputs
    assert "Section complete: Basics." in wizard_io.outputs
