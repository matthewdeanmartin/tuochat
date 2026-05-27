"""Browse a tiny author directory."""

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

AUTHORS = [
    {
        "name": "Jane Austen",
        "born": 1775,
        "country": "United Kingdom",
        "known_for": "Sharp social comedy and marriage plots.",
        "books": [
            {"title": "Pride and Prejudice", "year": 1813, "role": "Novel"},
            {"title": "Emma", "year": 1815, "role": "Novel"},
        ],
    },
    {
        "name": "Toni Morrison",
        "born": 1931,
        "country": "United States",
        "known_for": "Lyrical novels about memory, family, and Black American life.",
        "books": [
            {"title": "Beloved", "year": 1987, "role": "Novel"},
            {"title": "Song of Solomon", "year": 1977, "role": "Novel"},
        ],
    },
    {
        "name": "Ursula K. Le Guin",
        "born": 1929,
        "country": "United States",
        "known_for": "Anthropological science fiction and fantasy.",
        "books": [
            {"title": "A Wizard of Earthsea", "year": 1968, "role": "Novel"},
            {"title": "The Left Hand of Darkness", "year": 1969, "role": "Novel"},
        ],
    },
]


def main() -> None:
    """Run the example."""
    context = InteractionContext()
    try:
        author = ChoiceInput(
            "Author search.",
            [Choice(label=item["name"], value=item, aliases=(item["country"],), description=item["known_for"]) for item in AUTHORS],
        ).run(context)
    except InteractionCancelled:
        context.say("Author search cancelled.")
        return

    KeyValueViewer(
        title="Author record.",
        fields=[
            SummaryField("Name", author["name"]),
            SummaryField("Born", author["born"]),
            SummaryField("Country", author["country"]),
            SummaryField("Known for", author["known_for"]),
        ],
    ).show(context)
    TableViewer(
        title=f'{author["name"]} bibliography',
        rows=author["books"],
        columns=[TableColumn("title", "Title"), TableColumn("year", "Year"), TableColumn("role", "Role")],
    ).run(context)


if __name__ == "__main__":
    main()
