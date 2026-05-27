"""Tests for ``tuochat.security.tamper``."""

from __future__ import annotations

import importlib.machinery
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from tuochat.security import tamper


class FakeDistribution:
    """Tiny distribution stub for RECORD-based verification tests."""

    def __init__(self, root_path: Path, dist_info_name: str):
        self.root_path = root_path
        self.files = [PurePosixPath(f"{dist_info_name}/RECORD")]

    def locate_file(self, file_name: PurePosixPath) -> Path:
        return self.root_path / Path(*file_name.parts)


def make_package_spec(package_name: str, package_root: Path) -> importlib.machinery.ModuleSpec:
    """Build a package spec pointing at a temporary on-disk package."""
    spec = importlib.machinery.ModuleSpec(package_name, loader=None, is_package=True)
    spec.submodule_search_locations = [str(package_root)]
    return spec


def write_record(root_path: Path, dist_info_name: str, entries: list[tuple[str, str, str]]) -> None:
    """Write a simple CSV RECORD file for tests."""
    dist_info_path = root_path / dist_info_name
    dist_info_path.mkdir(parents=True, exist_ok=True)
    lines = [",".join(entry) for entry in entries]
    (dist_info_path / "RECORD").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_verify_files_against_record_succeeds(tmp_path, monkeypatch):
    """Verification succeeds when RECORD hashes match package files."""
    package_root = tmp_path / "samplepkg"
    package_root.mkdir()
    init_path = package_root / "__init__.py"
    module_path = package_root / "module.py"
    init_path.write_text('"""sample"""', encoding="utf-8")
    module_path.write_text("value = 1\n", encoding="utf-8")

    dist_info_name = "samplepkg-1.0.dist-info"
    write_record(
        tmp_path,
        dist_info_name,
        [
            ("samplepkg/__init__.py", f"sha256={tamper.sha256_file(init_path)}", str(init_path.stat().st_size)),
            ("samplepkg/module.py", f"sha256={tamper.sha256_file(module_path)}", str(module_path.stat().st_size)),
        ],
    )

    monkeypatch.setattr(
        tamper, "find_distribution_for_package", lambda package_name: FakeDistribution(tmp_path, dist_info_name)
    )
    monkeypatch.setattr(
        tamper.importlib.util, "find_spec", lambda package_name: make_package_spec(package_name, package_root)
    )

    assert tamper.verify_files_against_record("samplepkg") == []


def test_verify_files_against_embedded_manifest_succeeds(tmp_path, monkeypatch):
    """Verification succeeds when the embedded manifest matches package files."""
    package_root = tmp_path / "samplepkg"
    package_root.mkdir()
    module_path = package_root / "module.py"
    module_path.write_text("value = 3\n", encoding="utf-8")

    manifest = {"module.py": tamper.sha256_file(module_path)}

    monkeypatch.setattr(tamper, "load_embedded_manifest", lambda package_name: manifest)
    monkeypatch.setattr(
        tamper.importlib.util, "find_spec", lambda package_name: make_package_spec(package_name, package_root)
    )

    assert tamper.verify_files_against_embedded_manifest("samplepkg") == []


def test_verify_or_die_raises_when_record_and_manifest_fail(monkeypatch):
    """Verification aborts when both mechanisms report failures."""
    monkeypatch.setattr(tamper, "verify_files_against_record", lambda package_name: ["record mismatch"])
    monkeypatch.setattr(tamper, "verify_files_against_embedded_manifest", lambda package_name: ["manifest mismatch"])

    with pytest.raises(tamper.TamperError) as exc_info:
        tamper.verify_or_die("samplepkg")

    message = str(exc_info.value)
    assert "Code tampering check failed." in message
    assert "record mismatch" in message
    assert "manifest mismatch" in message


def test_verify_or_die_allows_environment_override(monkeypatch):
    """Explicit environment override bypasses the verification checks."""
    monkeypatch.setenv("TUOCHAT_ALLOW_TAMPER", "1")
    monkeypatch.setattr(tamper, "verify_files_against_record", lambda package_name: ["record mismatch"])
    monkeypatch.setattr(tamper, "verify_files_against_embedded_manifest", lambda package_name: ["manifest mismatch"])

    tamper.verify_or_die("samplepkg", allow_env_override=True)


def test_verify_or_die_skips_source_checkout(monkeypatch):
    """Source checkouts bypass verification in development mode."""
    monkeypatch.setattr(tamper, "is_source_checkout", lambda package_name: True)
    monkeypatch.setattr(
        tamper,
        "verify_files_against_record",
        lambda package_name: (_ for _ in ()).throw(AssertionError("RECORD verification should be skipped")),
    )
    monkeypatch.setattr(
        tamper,
        "verify_files_against_embedded_manifest",
        lambda package_name: (_ for _ in ()).throw(AssertionError("Manifest verification should be skipped")),
    )

    tamper.verify_or_die("samplepkg")


def test_is_source_checkout_detects_pyproject(tmp_path, monkeypatch):
    """A package under a project root with pyproject.toml is treated as dev mode."""
    package_root = tmp_path / "samplepkg"
    package_root.mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='samplepkg'\n", encoding="utf-8")

    monkeypatch.setattr(
        tamper.importlib.util, "find_spec", lambda package_name: make_package_spec(package_name, package_root)
    )

    assert tamper.is_source_checkout("samplepkg") is True


def test_load_embedded_manifest_rejects_invalid_module(monkeypatch):
    """Manifest loading fails when the generated module shape is invalid."""
    monkeypatch.setattr(tamper.importlib, "import_module", lambda module_name: SimpleNamespace(MANIFEST=[]))

    with pytest.raises(tamper.TamperError, match="embedded manifest is missing or invalid"):
        tamper.load_embedded_manifest("samplepkg")
