"""Attachment recipes — named file-glob bundles for common project contexts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tuochat.context.attachments import is_probably_binary, read_safe_text_file
from tuochat.context.ignore_rules import build_context_ignore_matcher
from tuochat.estimation import estimate_tokens

RECIPE_FILE_COUNT_THRESHOLD = 30
RECIPE_TOKEN_THRESHOLD = 40_000


@dataclass
class Recipe:
    """A named set of file globs that form a reusable attachment bundle."""

    name: str
    display_name: str
    description: str
    globs: list[str]
    exclude_globs: list[str] = field(default_factory=list)
    per_file_cap_chars: int | None = None
    total_token_budget: int = RECIPE_TOKEN_THRESHOLD
    flavor: str = "debug"  # "overview" | "core" | "debug"


@dataclass
class RecipeMatch:
    """The result of expanding a recipe against a working directory."""

    recipe: Recipe
    matched_paths: list[Path]
    skipped_paths: list[Path]
    rendered: str
    estimated_tokens: int

    @property
    def requires_preview(self) -> bool:
        return len(self.matched_paths) > RECIPE_FILE_COUNT_THRESHOLD or self.estimated_tokens > RECIPE_TOKEN_THRESHOLD


BUILTIN_RECIPES: list[Recipe] = [
    Recipe(
        name="python-overview",
        display_name="Python — Overview",
        description="Config files, README, and top-level structure for a Python project.",
        flavor="overview",
        globs=[
            "pyproject.toml",
            "uv.lock",
            "requirements*.txt",
            "tox.ini",
            "pytest.ini",
            "setup.cfg",
            "setup.py",
            "README*",
        ],
    ),
    Recipe(
        name="python-core",
        display_name="Python — Core Code",
        description="Primary Python source files only.",
        flavor="core",
        globs=["**/*.py"],
        exclude_globs=["test/**/*.py", "tests/**/*.py", "**/test_*.py"],
    ),
    Recipe(
        name="python-debug",
        display_name="Python — Debug",
        description="Source, tests, and relevant config for a Python project.",
        flavor="debug",
        globs=[
            "pyproject.toml",
            "uv.lock",
            "requirements*.txt",
            "tox.ini",
            "pytest.ini",
            "README*",
            "docs/**/*.md",
            "**/*.py",
        ],
    ),
    Recipe(
        name="java-overview",
        display_name="Java — Overview",
        description="Build files, README, and config for a Java project.",
        flavor="overview",
        globs=[
            "pom.xml",
            "build.gradle*",
            "settings.gradle*",
            "gradle.properties",
            "README*",
        ],
    ),
    Recipe(
        name="java-core",
        display_name="Java — Core Code",
        description="Primary Java source files.",
        flavor="core",
        globs=["src/main/java/**/*.java", "src/main/resources/**"],
    ),
    Recipe(
        name="java-debug",
        display_name="Java — Debug",
        description="Source, tests, and resources for a Java project.",
        flavor="debug",
        globs=[
            "pom.xml",
            "build.gradle*",
            "settings.gradle*",
            "gradle.properties",
            "README*",
            "src/main/java/**/*.java",
            "src/test/java/**/*.java",
            "src/main/resources/**",
            "src/test/resources/**",
        ],
    ),
    Recipe(
        name="angular-overview",
        display_name="Angular — Overview",
        description="Config, README, and top-level structure for an Angular project.",
        flavor="overview",
        globs=[
            "angular.json",
            "package.json",
            "package-lock.json",
            "yarn.lock",
            "tsconfig*.json",
            "README*",
        ],
    ),
    Recipe(
        name="angular-core",
        display_name="Angular — Core Code",
        description="Primary TypeScript/HTML/CSS source for an Angular project.",
        flavor="core",
        globs=["src/**/*.ts", "src/**/*.html", "src/**/*.css", "src/**/*.scss"],
        exclude_globs=["src/**/*.spec.ts"],
    ),
    Recipe(
        name="angular-debug",
        display_name="Angular — Debug",
        description="Source, specs, and config for an Angular project.",
        flavor="debug",
        globs=[
            "angular.json",
            "package.json",
            "tsconfig*.json",
            "README*",
            "src/**/*.ts",
            "src/**/*.html",
            "src/**/*.css",
            "src/**/*.scss",
        ],
    ),
    Recipe(
        name="yaml-bash-overview",
        display_name="YAML + Shell — Overview",
        description="YAML and shell/PowerShell config and script files.",
        flavor="overview",
        globs=[
            "*.yaml",
            "*.yml",
            "*.sh",
            "*.ps1",
            "*.bat",
            "README*",
            ".github/**/*.yml",
            ".github/**/*.yaml",
        ],
    ),
    Recipe(
        name="yaml-bash-core",
        display_name="YAML + Shell — Core",
        description="All YAML, shell, and PowerShell files.",
        flavor="core",
        globs=["**/*.yaml", "**/*.yml", "**/*.sh", "**/*.ps1"],
    ),
    Recipe(
        name="yaml-bash-debug",
        display_name="YAML + Shell — Debug",
        description="YAML, shell, PowerShell, and README for debugging pipelines.",
        flavor="debug",
        globs=[
            "**/*.yaml",
            "**/*.yml",
            "**/*.sh",
            "**/*.ps1",
            "**/*.bat",
            "README*",
            "docs/**/*.md",
        ],
    ),
]

RECIPE_BY_NAME: dict[str, Recipe] = {r.name: r for r in BUILTIN_RECIPES}


def list_recipes() -> list[Recipe]:
    """Return all built-in recipes."""
    return list(BUILTIN_RECIPES)


def get_recipe(name: str) -> Recipe | None:
    """Return a recipe by name, or None if not found."""
    return RECIPE_BY_NAME.get(name)


def expand_recipe(recipe: Recipe, cwd: Path | None = None) -> RecipeMatch:
    """Expand a recipe's globs against the working directory and return a match result."""
    working_directory = cwd or Path.cwd()
    matcher = build_context_ignore_matcher(working_directory)
    exclude_resolved: set[Path] = set()
    for exclude_glob in recipe.exclude_globs:
        for path in working_directory.glob(exclude_glob):
            exclude_resolved.add(path.resolve())

    seen: set[Path] = set()
    matched: list[Path] = []
    skipped: list[Path] = []

    for glob in recipe.globs:
        for path in sorted(working_directory.glob(glob)):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if resolved in exclude_resolved:
                skipped.append(path)
                continue
            if matcher.is_ignored(path):
                skipped.append(path)
                continue
            try:
                raw_bytes = path.read_bytes()
            except OSError:
                skipped.append(path)
                continue
            if is_probably_binary(raw_bytes):
                skipped.append(path)
                continue
            matched.append(path)

    rendered, total_tokens = render_recipe_bundle(
        matched,
        working_directory=working_directory,
        per_file_cap=recipe.per_file_cap_chars,
    )

    return RecipeMatch(
        recipe=recipe,
        matched_paths=matched,
        skipped_paths=skipped,
        rendered=rendered,
        estimated_tokens=total_tokens,
    )


def render_recipe_bundle(
    paths: list[Path],
    *,
    working_directory: Path,
    per_file_cap: int | None = None,
) -> tuple[str, int]:
    """Render matched files into a fenced bundle. Returns (rendered, token_estimate)."""
    from tuochat.context.attachments import code_fence_language

    parts: list[str] = []
    total_tokens = 0

    for path in paths:
        result = read_safe_text_file(path)
        if result is None:
            continue
        text = result[0]
        if per_file_cap is not None and len(text) > per_file_cap:
            text = text[:per_file_cap] + f"\n... (truncated at {per_file_cap} chars)"
        try:
            rel = path.relative_to(working_directory)
        except ValueError:
            rel = path
        lang = code_fence_language(path)
        block = f"# {rel}\n```{lang}\n{text}\n```"
        parts.append(block)
        total_tokens += estimate_tokens(text)

    return "\n\n".join(parts), total_tokens
