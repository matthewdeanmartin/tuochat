"""IO stream classes used to bridge CLI output into the Tkinter GUI."""

from __future__ import annotations

import io
import queue


class TranscriptStream(io.TextIOBase):
    """Text stream that forwards writes to the GUI transcript queue."""

    def __init__(self, output_queue: queue.Queue[str]) -> None:
        self.output_queue = output_queue

    def write(self, text: str) -> int:
        if text:
            self.output_queue.put(text)
        return len(text)

    def writable(self) -> bool:
        return True


class MultiTextIO(io.TextIOBase):
    """Text stream that broadcasts writes to multiple text streams."""

    def __init__(self, *streams: io.TextIOBase) -> None:
        self.streams = streams

    def write(self, text: str) -> int:
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        for stream in self.streams:
            flush = getattr(stream, "flush", None)
            if callable(flush):
                flush()

    def writable(self) -> bool:
        return True
