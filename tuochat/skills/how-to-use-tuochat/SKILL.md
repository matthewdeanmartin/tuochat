______________________________________________________________________

## name: how-to-use-tuochat description: Teach the assistant how to guide a human through tuochat's local workflow, slash commands, attachments, and conversation management.

# How To Use Tuochat

Use this skill when the user needs help operating `tuochat` itself rather than solving an external coding problem.

## Goal

This app is a chat client, not a fully agentic shell operator. When the user asks how to do something in `tuochat`, explain which local command or workflow they should use and what will happen next.

## Core Guidance

- Prefer teaching the user the smallest next action.
- Mention the exact slash command when one exists.
- Tell the user whether an action affects only the current session or is saved for future sessions.
- If a feature is interactive, say that the app will prompt them for the next selection.
- When a task needs local files, point them to `/include`, `/map`, or `/code-map` instead of implying the assistant can automatically inspect their filesystem.

## Common Workflows

### Start or reset a conversation

- Use `/new` to start a fresh conversation while keeping the current session open.
- Use `/clear` to clear the current chat and begin again.
- Use `/resume` to reopen a saved conversation.
- Use `/search` to find an older conversation by text and resume it.

### Add context

- Use `/include path/to/file` to attach one file to the next request.
- Use `/files` to browse candidate files first.
- Use `/map` to attach a recursive file map.
- Use `/code-map` to attach matching text files as one code bundle.
- Use `/detach` if the user attached the wrong file before sending.

### Skills and custom instructions

- Use `/skills` to list available skills.
- Use `/skill` to load one skill into the current conversation.
- Use `/custom` to choose custom instructions for the next new conversation.
- Explain that loaded skills become chat context for the conversation after selection.

### Session controls

- Use `/stream on|off` to toggle streaming for the current session.
- Use `/timeout` to inspect or temporarily override request timeouts.
- Use `/mask on|off` to control on-screen masking of sensitive values.
- Use `/verbose on|off` for extra prompt-budget diagnostics.

### Setup and troubleshooting

- Use `/config` to inspect the active redacted config.
- Use `/env` to inspect relevant environment variables.
- Use `/doctor` to run local config and path checks.
- Use `/setup` to re-run the interactive configuration flow.
