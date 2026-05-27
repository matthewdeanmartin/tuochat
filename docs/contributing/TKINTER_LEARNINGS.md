# Tkinter + SQLite threading learnings

The crash came from mixing **Tkinter background worker threads** with a **SQLite connection that was created on the Tk main thread**.

## What happened

The GUI starts a worker thread in `tuochat\gui\app.py` for each submission so the window stays responsive while a request is in flight.

That worker thread eventually calls:

- `process_repl_submission()`
- `send_chat_turn()`
- `state.store.save_conversation()`

`state.store` was a `ConversationStore` created earlier on the Tk main thread. Its SQLite connection was opened once in `ConversationStore.__init__()`, then reused everywhere.

Python's sqlite3 module rejects that by default:

> SQLite objects created in a thread can only be used in that same thread.

So the first background-thread write crashed with `sqlite3.ProgrammingError`.

## Root cause

The persistence layer assumed one store instance implied one safe connection.

That assumption works in the CLI REPL because almost everything runs on one thread. It breaks in Tkinter because:

1. Tk widgets must stay on the main thread.
1. Long-running chat work is better on a worker thread.
1. The worker thread still needs persistence.

The bug was not really "Tkinter is broken". The bug was **sharing a thread-bound SQLite connection across threads**.

## Fix

`ConversationStore` now opens **one SQLite connection per thread** instead of one connection per store instance.

Details:

- the store keeps a small connection map keyed by thread id
- each thread lazily gets its own connection
- every connection still enables WAL mode and foreign keys
- `close()` closes all tracked connections and marks the store closed

This keeps the existing `ConversationStore` API intact while making GUI worker-thread writes safe.

## Why this approach

Using `check_same_thread=False` on one shared connection would remove the immediate exception, but it still leaves multiple threads touching the same connection object. That is a much shakier design.

Per-thread connections are a better fit because:

- they match sqlite3's thread model more naturally
- they avoid cross-thread connection reuse
- they keep the GUI fix inside the persistence layer instead of scattering GUI-specific workarounds around the app

## Prevention guidance

When Tkinter is involved:

1. **Keep widget operations on the main thread only.**
1. **Assume background workers need their own database resources.**
1. **Do not cache thread-bound objects globally unless the abstraction is explicitly thread-aware.**
1. **Add regression tests that actually cross thread boundaries**, not just tests that instantiate the objects.

## Regression tests added

The persistence tests now cover:

- saving a conversation and message from a worker thread when the store was created on the main thread
- closing the store after another thread has opened its own connection
