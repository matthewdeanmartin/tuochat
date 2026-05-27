"""Installed-package tamper detection with RECORD and embedded-manifest fallback."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib
import importlib.metadata as importlib_metadata
import importlib.util
import os
from collections.abc import Iterable
from pathlib import Path, PurePosixPath


class TamperError(RuntimeError):
    """Raised when package file verification fails."""


def urlsafe_b64_nopad(data: bytes) -> str:
    """Return URL-safe base64 without trailing padding."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def sha256_file(path: Path) -> str:
    """Hash a file with sha256 and return the RECORD-style digest."""
    hash_value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hash_value.update(chunk)
    return urlsafe_b64_nopad(hash_value.digest())


def normalize_distribution_name(name: str) -> str:
    """Normalize a package or distribution name for metadata lookups."""
    return name.lower().replace("-", "_")


def find_distribution_for_package(package_name: str) -> importlib_metadata.Distribution | None:
    """Return the installed distribution that owns ``package_name`` when available."""
    normalized_name = normalize_distribution_name(package_name)

    distribution_names: list[str] = []
    try:
        package_map = importlib_metadata.packages_distributions()
    except Exception:
        package_map = {}

    for candidate_name in (package_name, normalized_name):
        for distribution_name in package_map.get(candidate_name, []):
            if distribution_name not in distribution_names:
                distribution_names.append(distribution_name)

    distribution_names.extend(name for name in (package_name, normalized_name) if name not in distribution_names)

    for distribution_name in distribution_names:
        try:
            return importlib_metadata.distribution(distribution_name)
        except importlib_metadata.PackageNotFoundError:
            continue

    return None


def distribution_info_dir(distribution: importlib_metadata.Distribution) -> Path | None:
    """Locate the installed ``.dist-info`` directory for a distribution."""
    for file_name in distribution.files or []:
        parts = list(file_name.parts)
        if parts and parts[0].endswith(".dist-info"):
            located_path = Path(str(distribution.locate_file(file_name)))
            return located_path if located_path.name == parts[0] else located_path.parent
    return None


def load_record_hashes(distribution: importlib_metadata.Distribution) -> dict[Path, tuple[str, str]]:
    """Return absolute file paths mapped to ``(algorithm, digest)`` from RECORD."""
    dist_info_path = distribution_info_dir(distribution)
    if dist_info_path is None:
        return {}

    record_path = dist_info_path / "RECORD"
    if not record_path.is_file():
        return {}

    hashes: dict[Path, tuple[str, str]] = {}
    with record_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) < 3:
                continue
            relative_name, hash_field = row[0], row[1]
            if not hash_field or "=" not in hash_field:
                continue
            algorithm, digest = hash_field.split("=", 1)
            if algorithm.lower() != "sha256":
                continue
            hashes[(dist_info_path.parent / PurePosixPath(relative_name)).resolve()] = (algorithm.lower(), digest)
    return hashes


def package_root_paths(package_name: str) -> list[Path]:
    """Return filesystem roots for the requested package."""
    spec = importlib.util.find_spec(package_name)
    if spec is None:
        raise TamperError(f"Could not locate package {package_name!r}")

    roots: list[Path] = []
    if spec.submodule_search_locations:
        roots.extend(Path(path_text).resolve() for path_text in spec.submodule_search_locations)
    elif spec.origin:
        roots.append(Path(spec.origin).resolve().parent)
    else:
        raise TamperError(f"Could not determine filesystem path for {package_name!r}")
    return roots


def iter_relevant_package_files(package_name: str) -> Iterable[Path]:
    """Enumerate installed Python source files under the package root."""
    seen_roots: set[Path] = set()
    for root_path in package_root_paths(package_name):
        if root_path in seen_roots:
            continue
        seen_roots.add(root_path)
        for file_path in sorted(root_path.rglob("*.py")):
            if file_path.is_file():
                yield file_path.resolve()


def is_source_checkout(package_name: str) -> bool:
    """Return True when the package is running from a source checkout."""
    try:
        root_paths = package_root_paths(package_name)
    except TamperError:
        return False

    for root_path in root_paths:
        project_root = root_path.parent
        if (project_root / "pyproject.toml").is_file():
            return True
        if (project_root / ".git").exists():
            return True
    return False


def verify_files_against_record(package_name: str) -> list[str]:
    """Verify package files against installed ``.dist-info/RECORD`` hashes."""
    distribution = find_distribution_for_package(package_name)
    if distribution is None:
        return [f"distribution for package {package_name!r} not found"]

    record_hashes = load_record_hashes(distribution)
    if not record_hashes:
        return [f"RECORD not found or contained no sha256 entries for {package_name!r}"]

    failures: list[str] = []
    checked_count = 0
    for file_path in iter_relevant_package_files(package_name):
        checked_count += 1
        expected = record_hashes.get(file_path)
        if expected is None:
            failures.append(f"missing RECORD hash entry: {file_path}")
            continue
        algorithm, expected_digest = expected
        actual_digest = sha256_file(file_path)
        if algorithm != "sha256":
            failures.append(f"unsupported hash algorithm for {file_path}: {algorithm}")
            continue
        if actual_digest != expected_digest:
            failures.append(
                f"hash mismatch: {file_path}\n"
                f"  expected sha256={expected_digest}\n"
                f"  actual   sha256={actual_digest}"
            )

    if checked_count == 0:
        failures.append(f"no package files found to verify for {package_name!r}")
    return failures


def load_embedded_manifest(package_name: str) -> dict[str, str]:
    """Load the generated embedded manifest for a package."""
    module_name = f"{package_name}.security.tamper_manifest"
    manifest_module = importlib.import_module(module_name)
    manifest = getattr(manifest_module, "MANIFEST", None)
    if not isinstance(manifest, dict):
        raise TamperError("embedded manifest is missing or invalid")
    return manifest


def verify_files_against_embedded_manifest(package_name: str) -> list[str]:
    """Verify package files against the generated embedded manifest."""
    try:
        manifest = load_embedded_manifest(package_name)
    except (ImportError, TamperError) as exc:
        return [f"embedded manifest unavailable: {exc}"]

    try:
        root_paths = package_root_paths(package_name)
    except TamperError as exc:
        return [str(exc)]

    package_root = root_paths[0]
    failures: list[str] = []
    for relative_posix_path, expected_digest in sorted(manifest.items()):
        file_path = (package_root / PurePosixPath(relative_posix_path)).resolve()
        if not file_path.is_file():
            failures.append(f"missing file: {file_path}")
            continue
        actual_digest = sha256_file(file_path)
        if actual_digest != expected_digest:
            failures.append(
                f"hash mismatch: {file_path}\n"
                f"  expected sha256={expected_digest}\n"
                f"  actual   sha256={actual_digest}"
            )
    return failures


def verify_or_die(
    package_name: str = "tuochat",
    *,
    allow_env_override: bool = False,
    env_var: str = "TUOCHAT_ALLOW_TAMPER",
) -> None:
    """Verify package code before the rest of the application imports."""
    if allow_env_override and os.environ.get(env_var) == "1":
        return

    if is_source_checkout(package_name):
        return

    record_failures = verify_files_against_record(package_name)
    if not record_failures:
        return

    manifest_failures = verify_files_against_embedded_manifest(package_name)
    if not manifest_failures:
        return

    message_lines = [
        "Code tampering check failed.",
        "",
        "RECORD verification errors:",
        *[f"  - {line}" for line in record_failures],
        "",
        "Embedded manifest verification errors:",
        *[f"  - {line}" for line in manifest_failures],
    ]
    if allow_env_override:
        message_lines.extend(["", f"To bypass once, set {env_var}=1."])
    raise TamperError("\n".join(message_lines))
