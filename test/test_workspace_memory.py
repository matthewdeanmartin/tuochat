from __future__ import annotations

from tuochat.discovery.shared import bundled_custom_instructions_dir
from tuochat.workspace_memory import (
    COMPACT_PROMPT,
    MEMORY_PROMPT,
    TODO_PROMPT,
    extract_fence_content,
)


def test_workspace_memory_prompts_require_tilde_fences_for_nested_markdown_examples():
    for prompt in (MEMORY_PROMPT, COMPACT_PROMPT, TODO_PROMPT):
        assert "use tildes (`~~~`) for those inner fences" in prompt
        assert "outer extractable fence stays parseable" in prompt


def test_extract_fence_content_preserves_tilde_fenced_examples_inside_outer_block():
    text = """```MEMORY
# Notes

Example:

~~~bash
echo hello
~~~
```"""

    extracted = extract_fence_content(text, "MEMORY")

    assert extracted == "# Notes\n\nExample:\n\n~~~bash\necho hello\n~~~"


def test_bundled_custom_instruction_files_describe_tilde_fences_for_nested_markdown():
    root = bundled_custom_instructions_dir()
    for name in ("INSTRUCTIONS.md", "INSTRUCTIONS_headless.md", "INSTRUCTIONS_gui.md"):
        text = (root / name).read_text(encoding="utf-8")
        assert "If you emit a Markdown document inside an outer triple-backtick fence" in text
        assert "use tildes instead" in text
        assert "This keeps the outer extractable fence parseable" in text
