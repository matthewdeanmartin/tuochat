# API Streaming Learnings

This note explains a real GitLab Duo streaming bug that caused garbled English at the beginning of saved assistant responses, why it happened, and how to keep it from coming back.

## What broke

We observed saved responses that began like this:

```text
Alphaerge request isows developers...
```

The expected beginning was:

```text
Alpha: A merge request is...
```

The corruption showed up in the persisted markdown artifact, not just on screen. That mattered because it proved the bug was in response assembly, not only in terminal rendering.

## Root cause

`tuochat.provider.duo.DuoProvider.chat_streaming()` assumed that intermediate websocket chunks were **cumulative**:

- chunk 1 = `Hello`
- chunk 2 = `Hello world`
- chunk 3 = `Hello world!`

Under that model, the client can emit `chunk_n[len(previous):]`.

During live testing, GitLab Duo instead delivered **fragment-style** chunks for at least some responses:

- chunk 1 = `Alpha`
- chunk 2 = `: A merge`
- chunk 3 = ` request`

Those chunks still had `chunkId` ordering, but they were not cumulative prefixes of the previous content. Our old logic treated them as cumulative anyway, so it trimmed valid leading characters and stitched fragments together incorrectly.

## Why unit tests missed it

Existing provider tests covered:

- cumulative streaming chunks
- out-of-order chunk arrival
- cancellation

They did **not** cover fragment-style chunks from the real API. The implementation was therefore correct for the mocked test shape but wrong for the live shape.

## How we confirmed it

The bug was reproduced with a live integration test that:

1. sends a real Duo request
1. writes the conversation through the normal session path
1. reads the saved markdown artifact back from disk
1. inspects the start of the assistant section

That was important because the corruption must be checked in the saved artifact path, not only in the terminal stream.

## Fix

`chat_streaming()` now supports both chunk shapes:

- **cumulative mode**: each chunk starts with all previously received content
- **fragment mode**: each chunk is a new fragment to append

The implementation starts in an `unknown` mode, buffers the first two sequential chunks, and decides:

- if chunk 2 starts with chunk 1, treat the stream as cumulative
- otherwise, treat it as fragment-based

It still preserves `chunkId` ordering and still supports cancellation.

## Prevention

When touching streaming code:

1. **Assume the wire format can vary.** Do not hard-code a single chunk shape unless the server contract explicitly guarantees it.
1. **Test assembly, not just transport.** Out-of-order delivery is only one dimension; cumulative vs fragment payload shape is another.
1. **Verify persisted output.** A streaming bug can hide if you only watch terminal rendering.
1. **Keep one live regression test.** Mocked websocket tests are necessary but not sufficient for API quirks.
1. **Inspect raw events when behavior changes.** `ChatDiagnostics.raw_events` is the fastest way to confirm what the server actually sent.

## Regression coverage

We added:

- a unit test for fragment-style websocket chunks in `test/test_provider_extra.py`
- a live integration suite in `tests_integration/test_response_garbling_live.py`

The live suite resets the Duo conversation between scenarios and checks the saved markdown artifact for a clean response beginning.
