# Context: Server-side vs Client-side

There are two completely different things called "context" in tuochat, and they travel through the
system in different ways. This document explains the distinction and maps every relevant command to
the correct bucket.

______________________________________________________________________

## The two buckets

### 1. additionalContext — server-side, invisible to you

`additionalContext` is a field in the GraphQL `aiAction` mutation that tuochat sends to the GitLab
Duo backend on every chat turn. It is a list of structured objects:

```json
[
  { "category": "FILE", "name": "README.md", "content": "# Hello\n..." },
  { "category": "MERGE_REQUEST", "name": "MyProject!mr-10", "content": "Title: ..." }
]
```

Duo receives these alongside your question and can use them to inform its answer — but they are
**not** part of the conversation transcript that tuochat stores, and you do not see them echoed back
to you in the chat window. The GitLab VS Code extension uses the same mechanism to inject open
files and editor state; tuochat is doing the same thing over the API.

In tuochat this list lives in `state.server_context`. Everything in that list is forwarded on
every single turn until you clear it. Think of it as a **persistent side-channel** from your
client to the Duo model.

### 2. Conversation messages — client-side, visible to you

The conversation itself is a list of `(role, content)` message pairs that tuochat assembles and
sends as the `content` / chat history field of the request. When you paste text into a prompt, or
attach a file with `/include`, the content goes into the next user message. It shows up in the
chat window, it is saved in the conversation history, and it scrolls past as the conversation grows.

This is the **normal** way to give Duo information: you write it out, Duo reads it, responds, and
the exchange is recorded.

______________________________________________________________________

## Which commands use which bucket

### Commands that write into `additionalContext` (server-side, invisible)

| Command | What it stores | Category label |
|---|---|---|
| `/server-add <category> <name>` | Arbitrary text you type or paste | Whatever you specify |
| `/gl issue <iid>` | Issue title + description fetched from GitLab API | `GitLabArtifact` |
| `/gl mr <iid>` | MR title + description + branch info | `GitLabArtifact` |
| `/gl file <path> [ref]` | Raw file content fetched from repo | `GitLabArtifact` |

These commands call the GitLab API, format the result into a structured block, and push it into
`state.server_context`. On every subsequent turn Duo receives that block quietly alongside your
message. You never see it in the chat window.

To inspect what is currently loaded: `/gl current` or `/server-current-items`.\
To remove one entry: `/gl remove <name>` or `/server-remove <name>`.\
To wipe everything: `/server-clear`.

### Commands that write into conversation messages (client-side, visible)

| Command | What it adds | Where it appears |
|---|---|---|
| `/include <path>` | File contents | Prepended to your next user message |
| `/map [glob]` | Directory listing | Queued for your next user message |
| `/code-map [glob]` | File tree + contents bundle | Queued for your next user message |
| Typing text and sending | Your prompt | New user message in history |

When you use `/include`, the file content is bundled into the user turn that you send next. It is
visible in the chat, counted in token estimates, and saved in the conversation markdown.

______________________________________________________________________

## The resource ID — a third concept, not context

`/resource pick` and `/resource set` do not put content anywhere. They record a GitLab project GID
(e.g. `gid://gitlab/Project/42`) that is sent as the `resourceId` field in the GraphQL request.
This tells Duo which project's code index to search when answering code-related questions. It is
not content — it is a **scope selector**. Duo uses it server-side to limit search; tuochat never
sees the results of that search.

______________________________________________________________________

## Mental model

```
Your prompt (typed)
   +
Queued attachments from /include, /map, /code-map
   |
   v
  [user message]  ──────────────────────────────┐
                                                 │
  [conversation history]                         │  GraphQL aiAction mutation
                                                 │
  [system prompt]                                │    resourceId   ← /resource
                                                 │    content      ← messages above
  state.server_context  (from /gl, /server-add)  │    additionalContext ← this list
   └─ item 0: { category, name, content }        │
   └─ item 1: { category, name, content }        │
   ...                                           │
                                                 ▼
                                           GitLab Duo API
                                                 │
                                                 ▼
                                         streamed response
```

The key asymmetry: conversation messages accumulate turn-by-turn and you see them all.
`additionalContext` items persist for the whole session at a fixed size and are invisible to you.
Both arrive at Duo in the same request.

______________________________________________________________________

## Practical guidance

**Use `additionalContext` (`/gl`, `/server-add`) when:**

- You want something available on every turn without re-pasting it.
- The content is reference material (an issue description, a config file) that you want Duo to
  be aware of but that does not need to be part of the visible conversation.
- You want to swap it out mid-session without cluttering the chat history.

**Use `/include` / typed text when:**

- You are sending a one-off snippet you want to discuss in this turn only.
- You want the content to appear in the saved transcript.
- You are building up a conversation where the history itself matters to the answer.

**A common pattern for GitLab work:**

1. `/resource set group/myrepo` — scope Duo to the right project code index.
1. `/gl issue 42` — load the issue description silently into `additionalContext`.
1. Type your question — Duo sees both the issue and your question, answers in that context.
1. `/gl file src/auth.py` — add a relevant source file to `additionalContext`.
1. Continue asking questions — Duo now has the issue and the file on every turn.
1. `/server-clear` when switching to a different topic.
