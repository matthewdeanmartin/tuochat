"""Search and review a tiny appointment schedule."""

from __future__ import annotations

from tuochat.cli.blind_prompt_kit import (
    Choice,
    ChoiceInput,
    InteractionCancelled,
    InteractionContext,
    KeyValueViewer,
    SummaryField,
    TableColumn,
    TableViewer,
)

APPOINTMENTS = [
    {
        "id": "A-104",
        "patient": "Maya Lee",
        "clinician": "Dr. Gomez",
        "date": "April 14, 2026",
        "time": "9:30 AM",
        "status": "Confirmed",
        "reason": "Follow-up migraine visit",
    },
    {
        "id": "A-105",
        "patient": "Jon Patel",
        "clinician": "Dr. Gomez",
        "date": "April 14, 2026",
        "time": "11:00 AM",
        "status": "Pending",
        "reason": "Medication review",
    },
    {
        "id": "A-106",
        "patient": "Rosa Kim",
        "clinician": "Dr. Hart",
        "date": "April 15, 2026",
        "time": "2:15 PM",
        "status": "Confirmed",
        "reason": "Initial physical therapy consult",
    },
]


def main() -> None:
    """Run the example."""
    context = InteractionContext()
    TableViewer(
        title="Appointments",
        rows=APPOINTMENTS,
        columns=[
            TableColumn("id", "ID"),
            TableColumn("patient", "Patient"),
            TableColumn("clinician", "Clinician"),
            TableColumn("date", "Date"),
            TableColumn("time", "Time"),
            TableColumn("status", "Status"),
        ],
    ).run(context)
    try:
        appointment = ChoiceInput(
            "Appointment search.",
            [
                Choice(
                    label=f'{item["patient"]} on {item["date"]} at {item["time"]}',
                    value=item,
                    aliases=(item["id"], item["clinician"], item["status"]),
                    description=item["reason"],
                )
                for item in APPOINTMENTS
            ],
        ).run(context)
    except InteractionCancelled:
        context.say("Appointment search cancelled.")
        return

    KeyValueViewer(
        title="Appointment details.",
        fields=[
            SummaryField("ID", appointment["id"]),
            SummaryField("Patient", appointment["patient"]),
            SummaryField("Clinician", appointment["clinician"]),
            SummaryField("Date", appointment["date"]),
            SummaryField("Time", appointment["time"]),
            SummaryField("Status", appointment["status"]),
            SummaryField("Reason", appointment["reason"]),
        ],
    ).show(context)


if __name__ == "__main__":
    main()
