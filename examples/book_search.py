"""Search a tiny library catalog."""

from __future__ import annotations

from tuochat.cli.blind_prompt_kit import (
    Choice,
    ChoiceInput,
    InteractionCancelled,
    InteractionContext,
    KeyValueViewer,
    LongTextReader,
    SummaryField,
)

BOOKS = [
    {
        "title": "Pride and Prejudice",
        "author": "Jane Austen",
        "year": 1813,
        "genre": "Classic romance",
        "summary": "Elizabeth Bennet navigates class, family pressure, and Mr. Darcy.",
        "excerpt": "It is a truth universally acknowledged.\n\nHowever little known the feelings or views of such a man may be...",
    },
    {
        "title": "The Left Hand of Darkness",
        "author": "Ursula K. Le Guin",
        "year": 1969,
        "genre": "Science fiction",
        "summary": "An envoy must build trust on a world that challenges his assumptions.",
        "excerpt": "I'll make my report as if I told a story.\n\nThe soundest fact may fail in the style of its telling.",
    },
    {
        "title": "Beloved",
        "author": "Toni Morrison",
        "year": 1987,
        "genre": "Historical fiction",
        "summary": "Sethe and her family confront memory, love, and haunting after slavery.",
        "excerpt": "124 was spiteful.\n\nFull of a baby's venom.",
    },
]


def main() -> None:
    """Run the example."""
    context = InteractionContext()
    try:
        choice = ChoiceInput(
            "Book search.",
            [
                Choice(
                    label=book["title"],
                    value=book,
                    aliases=(book["author"], book["genre"]),
                    description=f'{book["author"]}, {book["year"]}',
                )
                for book in BOOKS
            ],
        ).run(context)
    except InteractionCancelled:
        context.say("Book search cancelled.")
        return

    KeyValueViewer(
        title="Book details.",
        fields=[
            SummaryField("Title", choice["title"]),
            SummaryField("Author", choice["author"]),
            SummaryField("Year", choice["year"]),
            SummaryField("Genre", choice["genre"]),
            SummaryField("Summary", choice["summary"]),
        ],
    ).show(context)
    if context.ask_yes_no("Read excerpt?", default=True):
        LongTextReader(title=choice["title"], text=choice["excerpt"], summary=choice["summary"]).run(context)


if __name__ == "__main__":
    main()
