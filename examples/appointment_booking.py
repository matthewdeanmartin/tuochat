"""Book a follow-up appointment with a realistic mini workflow."""

from __future__ import annotations

from tuochat.cli.blind_prompt_kit import (
    ChoiceInput,
    DateInput,
    FormField,
    InteractionCancelled,
    InteractionContext,
    LargeTextInput,
    MultiSelectInput,
    SequentialForm,
    TimeInput,
)


def main() -> None:
    """Run the example."""
    context = InteractionContext()
    form = SequentialForm(
        title="Follow-up appointment booking",
        fields=[
            FormField(
                name="visit_type",
                label="Visit type",
                component=ChoiceInput("Visit type.", ["Annual physical", "Follow-up", "Lab review", "Telehealth"]),
            ),
            FormField(name="appointment_date", label="Appointment date", component=DateInput("Appointment date?")),
            FormField(name="appointment_time", label="Appointment time", component=TimeInput("Appointment time?")),
            FormField(
                name="reminders",
                label="Reminders",
                component=MultiSelectInput("Reminder methods.", ["Text message", "Email", "Phone call"]),
                optional=True,
                renderer=lambda values: ", ".join(values) if values else "blank",
            ),
            FormField(name="notes", label="Notes", component=LargeTextInput("Clinical notes.", terminator="DONE"), optional=True),
        ],
    )
    try:
        result = form.run(context)
    except InteractionCancelled:
        context.say("Booking cancelled.")
        return

    context.say("Booking saved.")
    for key, value in result.items():
        rendered = "blank" if value is None or value == "" else value
        context.say(f"{key.replace('_', ' ').title()}: {rendered}")


if __name__ == "__main__":
    main()
