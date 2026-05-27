# Searching Conversations

Tuochat saves every conversation to a local SQLite database so you can search and resume past
work.

______________________________________________________________________

## Quick search

From within a chat session:

```
/search authentication
```

From the command line:

```bash
tuochat search "database migration"
```

______________________________________________________________________

## Search options

```bash
tuochat convo search QUERY [options]
```

| Option | Description |
|---|---|
| `--limit N` | Maximum results to show (default: 20) |
| `--title TEXT` | Filter results to conversations whose title matches TEXT |
| `--after ISO_DATE` | Only include conversations updated after this date (e.g. `2024-01-01`) |
| `--before ISO_DATE` | Only include conversations updated before this date |

Examples:

```bash
tuochat convo search "refactor" --limit 5
tuochat convo search "auth" --title "login"
tuochat convo search "" --after 2024-06-01 --before 2024-07-01   # browse a date range
```

______________________________________________________________________

## What is searched

Search matches against the text of all messages in the database — both your messages and Duo's
responses. Results show:

- Conversation ID
- Conversation title
- Last updated date
- Role that matched (you or Duo)
- A short snippet around the match

______________________________________________________________________

## Resuming from search results

After a search you are shown a numbered list. Enter a number to resume that conversation, or
press Enter to cancel.

```
Results:
  1. 2024-06-15 — Refactor auth module  (you: "...refactor the authentication...")
  2. 2024-05-20 — API design review     (Duo: "...authentication layer...")
Resume conversation (number, or Enter to skip):
```

Resuming loads the conversation history and continues from where you left off.

______________________________________________________________________

## Browsing without a query

```bash
tuochat convo list              # most recent 20 conversations
tuochat convo list --limit 50   # more results
tuochat convo list --archived   # show archived conversations
```

______________________________________________________________________

## Limitations

- Search is disabled when `/no-write` mode is active (no database is maintained).
- Search is local only — it does not search GitLab issues, MRs, or the Duo server.
- Full-text search uses SQLite's built-in FTS; very short queries (one or two characters) may
  return many matches.
