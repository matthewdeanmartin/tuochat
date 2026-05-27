from __future__ import annotations

from scripts import gen_tamper_manifest
from tuochat.security import tamper_manifest


def test_embedded_manifest_contains_expected_entries():
    assert "cli/commands/auth_cmd.py" in tamper_manifest.MANIFEST
    assert "provider/oauth.py" in tamper_manifest.MANIFEST
    assert "sandbox/worker.py" in tamper_manifest.MANIFEST


def test_manifest_builder_hashes_python_files_without_touching_checked_in_manifest(tmp_path, monkeypatch):
    package_dir = tmp_path / "samplepkg"
    security_dir = package_dir / "security"
    security_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text('"""sample"""', encoding="utf-8")
    module_path = package_dir / "module.py"
    module_path.write_text("value = 1\n", encoding="utf-8")
    (security_dir / "tamper_manifest.py").write_text("MANIFEST = {}\n", encoding="utf-8")

    monkeypatch.setattr(gen_tamper_manifest, "PACKAGE_DIR", package_dir)
    monkeypatch.setattr(gen_tamper_manifest, "SKIP_RELATIVE_PATH", "security/tamper_manifest.py")

    manifest = gen_tamper_manifest.build_manifest()

    assert manifest == {
        "__init__.py": gen_tamper_manifest.sha256_file(package_dir / "__init__.py"),
        "module.py": gen_tamper_manifest.sha256_file(module_path),
    }


def test_render_manifest_module_round_trips_python_source():
    rendered = gen_tamper_manifest.render_manifest_module({"module.py": "digest-1"})
    namespace: dict[str, object] = {}

    exec(rendered, namespace)

    assert '"""Generated fallback manifest for package tamper checks."""' in rendered
    assert namespace["MANIFEST"] == {"module.py": "digest-1"}


def test_manifest_main_writes_to_monkeypatched_output_path(tmp_path, monkeypatch):
    package_dir = tmp_path / "samplepkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("value = 1\n", encoding="utf-8")
    output_path = tmp_path / "generated_manifest.py"

    monkeypatch.setattr(gen_tamper_manifest, "PACKAGE_DIR", package_dir)
    monkeypatch.setattr(gen_tamper_manifest, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(gen_tamper_manifest, "SKIP_RELATIVE_PATH", "security/tamper_manifest.py")

    gen_tamper_manifest.main()

    assert output_path.is_file()
    assert "__init__.py" in output_path.read_text(encoding="utf-8")
