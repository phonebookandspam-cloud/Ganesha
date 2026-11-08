import json
import os
import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.generate_sbom as sbom_module
from tools.generate_sbom import generate, validate_sbom_document


class ReleaseToolingTests(unittest.TestCase):
    def test_ci_uses_pinned_supported_toolchains_and_immutable_action_references(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn('python-version: "3.13.17"', workflow)
        self.assertIn('node-version: "22.23.4"', workflow)
        self.assertIn("npm audit --audit-level=low", workflow)
        self.assertIn("npm run build:frontend:offline", workflow)
        for line in workflow.splitlines():
            if "uses: actions/" in line:
                self.assertRegex(line, r"uses: actions/[A-Za-z0-9_-]+@[0-9a-f]{40}$", line)

    def test_license_status_notice_is_not_mispackaged_as_a_project_license(self):
        pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("license-files = []", pyproject)
        self.assertFalse((Path(__file__).resolve().parents[1] / "LICENSE").exists())
        self.assertTrue((Path(__file__).resolve().parents[1] / "docs/license-status.md").is_file())

    def test_generated_local_frontend_config_is_never_in_source_distribution(self):
        manifest = (Path(__file__).resolve().parents[1] / "MANIFEST.in").read_text(encoding="utf-8")
        self.assertIn("exclude frontend/config.js", manifest)

    def test_all_provenance_listed_frontend_wav_assets_are_in_source_distribution(self):
        manifest = (Path(__file__).resolve().parents[1] / "MANIFEST.in").read_text(encoding="utf-8")
        self.assertIn("recursive-include frontend *.wav", manifest)
        self.assertIn("include package.json", manifest)
        self.assertIn("include package-lock.json", manifest)
        self.assertIn("include requirements-test.txt", manifest)

    def test_cyclonedx_sbom_is_deterministic_and_lists_pinned_build_dependencies(self):
        previous = os.environ.get("SOURCE_DATE_EPOCH")
        os.environ["SOURCE_DATE_EPOCH"] = "1793708852"
        try:
            first = generate()
            second = generate()
        finally:
            if previous is None:
                os.environ.pop("SOURCE_DATE_EPOCH", None)
            else:
                os.environ["SOURCE_DATE_EPOCH"] = previous
        self.assertEqual(first, second)
        self.assertEqual(first["bomFormat"], "CycloneDX")
        self.assertEqual(first["specVersion"], "1.5")
        library_components = [item for item in first["components"]
                              if item["type"] == "library" and item.get("purl", "").startswith("pkg:pypi/")]
        self.assertEqual({item["name"] for item in library_components}, {
            "build", "importlib-metadata", "packaging", "pip", "pyproject-hooks", "setuptools", "tomli", "wheel", "zipp", "zstandard"
        })
        self.assertEqual({item["version"] for item in library_components}, {
            "1.4.4", "8.7.1", "26.3", "1.3.3", "84.1.0", "2.5.0", "0.48.0", "3.23.1", "0.25.0"
        })
        self.assertTrue(all(item.get("licenses", [{}])[0].get("expression")
                            for item in library_components))
        asset_components = [item for item in first["components"] if item["type"] == "file"]
        asset_manifest = json.loads((Path(__file__).resolve().parents[1] / "frontend/assets/ASSET_PROVENANCE.json").read_text(encoding="utf-8"))
        expected_assets = {item["file"]: item["sha256"] for item in asset_manifest["assets"]}
        actual_assets = {item["name"]: item.get("hashes", [{}])[0].get("content")
                         for item in asset_components}
        self.assertEqual(actual_assets, expected_assets)
        self.assertTrue(all(item.get("hashes", [{}])[0].get("alg") == "SHA-256" for item in asset_components))
        self.assertTrue(all(any(prop.get("name") == "ganesha.asset.redistribution_rights"
                                for prop in item.get("properties", [])) for item in asset_components))
        self.assertIn("shipped frontend assets", first["metadata"]["properties"][-1]["value"])
        self.assertTrue(any(prop.get("name") == "ganesha.python.test.dependencies"
                            and prop.get("value") == "requirements-test.txt"
                            for prop in first["metadata"]["properties"]))

        npm_lock = json.loads((Path(__file__).resolve().parents[1] / "package-lock.json").read_text(encoding="utf-8"))
        npm_components = [item for item in first["components"]
                          if item["type"] == "library" and item.get("purl", "").startswith("pkg:npm/")]
        self.assertEqual(len(npm_components), len(npm_lock["packages"]) - 1)
        npm_by_name = {item["name"]: item for item in npm_components}
        self.assertEqual(npm_by_name["stake-engine"]["version"], "0.1.32")
        self.assertEqual(npm_by_name["vite"]["version"], "6.4.5")
        self.assertTrue(all(item.get("hashes", [{}])[0].get("alg") == "SHA-512" for item in npm_components))
        self.assertTrue(all(item.get("licenses") for item in npm_components))
        root_dependencies = next(item["dependsOn"] for item in first["dependencies"]
                                 if item["ref"] == first["metadata"]["component"]["bom-ref"])
        self.assertIn(npm_by_name["stake-engine"]["bom-ref"], root_dependencies)
        self.assertIn(npm_by_name["vite"]["bom-ref"], root_dependencies)
        all_component_refs = {item["bom-ref"] for item in first["components"]}
        dependency_records = first["dependencies"]
        self.assertEqual(len({item["ref"] for item in dependency_records}), len(dependency_records))
        self.assertTrue(all(item["ref"] == first["metadata"]["component"]["bom-ref"]
                            or item["ref"] in all_component_refs for item in dependency_records))
        self.assertTrue(all(set(item["dependsOn"]).issubset(all_component_refs)
                            for item in dependency_records))

    def test_release_sbom_validator_rejects_incomplete_historical_inventory(self):
        complete = generate()
        self.assertTrue(validate_sbom_document(complete))

        missing_npm = copy.deepcopy(complete)
        missing_npm["components"] = [item for item in missing_npm["components"]
                                     if not item.get("purl", "").startswith("pkg:npm/")]
        with self.assertRaisesRegex(ValueError, "complete locked npm, Python build/test and shipped asset inventory"):
            validate_sbom_document(missing_npm)

        missing_audio = copy.deepcopy(complete)
        missing_audio["components"] = [item for item in missing_audio["components"]
                                        if item.get("name") != "sfx/win.wav"]
        with self.assertRaisesRegex(ValueError, "complete locked npm, Python build/test and shipped asset inventory"):
            validate_sbom_document(missing_audio)

        missing_dependency_edge = copy.deepcopy(complete)
        missing_dependency_edge["dependencies"] = missing_dependency_edge["dependencies"][:-1]
        with self.assertRaisesRegex(ValueError, "complete npm lock graph"):
            validate_sbom_document(missing_dependency_edge)

        historical = Path(__file__).resolve().parents[1] / "dist/a6e7997/sbom.cdx.json"
        if historical.is_file():
            with self.assertRaises(ValueError):
                validate_sbom_document(json.loads(historical.read_text(encoding="utf-8")))

    def test_sbom_generation_rejects_shipped_asset_missing_from_provenance(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in ("requirements-build.txt", "requirements-test.txt", "package-lock.json"):
                shutil.copy2(source / relative, root / relative)
            shutil.copytree(source / "frontend/assets", root / "frontend/assets")
            with patch.object(sbom_module, "ROOT", root), patch.object(
                sbom_module, "git", side_effect=lambda *args: "a" * 40 if args == ("rev-parse", "HEAD") else "1793708852"
            ):
                previously_valid = sbom_module.generate()
                (root / "frontend/assets/unlisted-shipped.svg").write_text("<svg/>", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "exact shipped asset inventory"):
                    sbom_module.generate()
                with self.assertRaisesRegex(ValueError, "exact shipped asset inventory"):
                    sbom_module.validate_sbom_document(previously_valid)

    def test_sbom_generation_rejects_duplicate_asset_content_identity(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in ("requirements-build.txt", "requirements-test.txt", "package-lock.json"):
                shutil.copy2(source / relative, root / relative)
            shutil.copytree(source / "frontend/assets", root / "frontend/assets")
            provenance_path = root / "frontend/assets/ASSET_PROVENANCE.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance["assets"][1]["sha256"] = provenance["assets"][0]["sha256"]
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            with patch.object(sbom_module, "ROOT", root), patch.object(
                sbom_module, "git", side_effect=lambda *args: "a" * 40 if args == ("rev-parse", "HEAD") else "1793708852"
            ):
                with self.assertRaisesRegex(ValueError, "duplicate content identity"):
                    sbom_module.generate()

    def test_sbom_generation_rejects_symlinked_shipped_asset(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in ("requirements-build.txt", "requirements-test.txt", "package-lock.json"):
                shutil.copy2(source / relative, root / relative)
            shutil.copytree(source / "frontend/assets", root / "frontend/assets")
            assets = root / "frontend/assets"
            original = assets / "a_icon_v14.svg"
            linked = assets / "a_icon_v14.link"
            original.rename(linked)
            original.symlink_to(linked.name)
            with patch.object(sbom_module, "ROOT", root), patch.object(
                sbom_module, "git", side_effect=lambda *args: "a" * 40 if args == ("rev-parse", "HEAD") else "1793708852"
            ):
                with self.assertRaisesRegex(ValueError, "contains a symlink"):
                    sbom_module.generate()

    def test_sbom_generation_rejects_missing_and_duplicate_asset_paths(self):
        source = Path(__file__).resolve().parents[1]
        for mutation, expected_error in (("missing", "exact shipped asset inventory"),
                                         ("duplicate", "duplicate asset paths")):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                for relative in ("requirements-build.txt", "requirements-test.txt", "package-lock.json"):
                    shutil.copy2(source / relative, root / relative)
                shutil.copytree(source / "frontend/assets", root / "frontend/assets")
                assets = root / "frontend/assets"
                provenance_path = assets / "ASSET_PROVENANCE.json"
                provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                if mutation == "missing":
                    (assets / provenance["assets"][0]["file"]).unlink()
                else:
                    provenance["assets"][1]["file"] = provenance["assets"][0]["file"]
                    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
                with patch.object(sbom_module, "ROOT", root), patch.object(
                    sbom_module, "git", side_effect=lambda *args: "a" * 40 if args == ("rev-parse", "HEAD") else "1793708852"
                ):
                    with self.assertRaisesRegex(ValueError, expected_error):
                        sbom_module.generate()



if __name__ == "__main__":
    unittest.main()
