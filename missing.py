#!/usr/bin/env python3
import ast
from pathlib import Path

TARGET_DIRS = ["tuochat", "test"]


def file_has_future_import(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"Skipping non-UTF8 file: {path}")
        return True
    except Exception as exc:
        print(f"Error reading {path}: {exc}")
        return True

    # Skip empty files or files with only whitespace/comments
    if not text.strip():
        return True

    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        print(f"Syntax error in {path}: {exc}")
        return True

    # Skip files with no executable statements (only comments/whitespace)
    if not tree.body:
        return True

    for node in tree.body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(getattr(node, "value", None), ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue

        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            return any(alias.name == "annotations" for alias in node.names)

        return False

    return False


def main() -> int:
    missing = []

    for dir_name in TARGET_DIRS:
        root = Path(dir_name)
        if not root.exists():
            print(f"Directory not found: {root}")
            continue

        for path in root.rglob("*.py"):
            if not file_has_future_import(path):
                missing.append(path)

    if missing:
        print("Files missing 'from __future__ import annotations':")
        for path in sorted(missing):
            print(path)
        return 1

    print("All checked files include 'from __future__ import annotations'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
