# Tuochat Driver Instructions

This file mirrors `.gitlab\duo\skills\tuochat-driver\SKILL.md` so Copilot-style tooling has a direct prompt file to read.

Use this when you are the external LLM operating `tuochat` itself. You are not Duo. You are the driver that steers Duo through tuochat's CLI.

## Core rule

Act like a careful human operator using a minimally agentic chat client. Do one explicit turn at a time. Gather context yourself, choose what to attach, inspect the reply, decide what to save or run, and only then send the next turn.

## Keep the roles separate

### Driver LLM

- Reads repo files, docs, diffs, tests, and command output outside tuochat.
- Chooses the next prompt, attachments, skill, template, cwd, and conversation to use.
- Reviews extracted files, renames or moves `*.check` files, runs tests, and feeds failures back.
- Must not pretend Duo saw anything that was not attached or described.

### tuochat

- Starts or resumes conversations.
- Sends prompts, attachments, templates, skills, and resource scoping to Duo.
- Saves transcripts and extracted files.
- Adds `.check` to executable-looking extracted files.
- Does not browse the repo or decide what to run.

### Duo

- Answers only from the conversation plus any attached or server-side context.
- Can write code and prose in the reply.
- Cannot inspect local files, edit the workspace directly, or run tools.

## Preferred operating surfaces

Prefer the non-interactive CLI:

- `tuochat chat new`
- `tuochat chat send`
- `tuochat chat show`
- `tuochat chat latest`
- `tuochat context skills`
- `tuochat context templates`
- `tuochat convo list`
- `tuochat convo search`
- `tuochat convo export`
- `tuochat doctor`
- `tuochat config`

Legacy but still valid when a workflow already depends on it:

- `tuochat headless ask`
- `tuochat headless continue`

Avoid building an LLM-driven workflow around `tuochat gui` or REPL-only slash commands unless a human is actively operating the UI.

## Turn contract

1. Inspect the workspace yourself.
1. Decide what Duo actually needs for this turn.
1. Attach only the necessary context with `--include`, `--web`, `--skill`, `--template`, `--var`, `--resource-id`, and `--cwd`.
1. Prefer machine-readable output: `--format json` for `chat`, `--json` for `headless`.
1. Read the full reply before acting.
1. If tuochat saved extracted files, inspect them and deliberately rename or move any `*.check` outputs.
1. Run tests or other verification yourself.
1. Summarize only the relevant failures or requested changes back to Duo.
1. Continue the same conversation when the prior turns matter.

## Context rules

- `--include` and `--web` add visible prompt content for the turn.
- `--skill` loads a discovered skill into the visible conversation.
- `--template` expands prompt text before sending.
- `--resource-id` is only a GitLab scope selector. It is not file content.
- In interactive mode, `/gl ...` and `/server-add ...` create persistent invisible server-side context. Do not assume those REPL-only commands exist in headless workflows.
- `chat send --restore-cwd` can preserve workspace-relative behavior across resumed conversations.

## Ask Duo for usable outputs

When you want files back from Duo:

- ask for fenced code blocks with filenames
- prefer one file per block
- prefer concise updates instead of re-emitting unchanged files
- remind Duo that long responses may truncate
- tell Duo exactly where the driver will place approved files

Useful filename styles include ````  ```python:path.py ````, ````  ```python path.py ````, and `filename="path.py"`.

## File safety rules

- tuochat may write executable outputs as `name.ext.check`.
- The driver must inspect and rename or move those files before treating them as real workspace files.
- Never assume extracted files were applied to the repo automatically.
- If a file is missing a usable filename, ask Duo to re-emit it with an explicit filename.

## Human-simulation rule

The driver always simulates what a hypothetical careful human would do with a non-agentic chat client:

- no hidden tool use attributed to Duo
- no silent rewriting of Duo's code while claiming Duo authored it
- no skipped review step between extracted output and execution
- no assumptions that Duo remembers local state outside the saved conversation and attached context

## GUI note

`tuochat gui` exists, but a headless driver LLM should usually avoid it. Tkinter is an interactive human UI, while `chat`, `headless`, `convo`, and `context` are the predictable surfaces for another LLM.

## Success condition

A good tuochat-driving LLM uses tuochat as the transport and record keeper, Duo as the in-app assistant, and itself as the operator that chooses context, approves files, and runs the outside-world steps.
