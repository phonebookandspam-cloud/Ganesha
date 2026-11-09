import json
import hashlib
import ast
import io
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PublicationGateTests(unittest.TestCase):
    def test_commit_archive_digest_helper_fails_closed(self):
        source = ast.parse((ROOT / "qa_release_gate.py").read_text(encoding="utf-8"))
        function = next(node for node in source.body
                        if isinstance(node, ast.FunctionDef) and node.name == "commit_source_archive_sha256")
        archive = mock.Mock(return_value=b"deterministic git archive")
        namespace = {"re": re, "hashlib": hashlib, "subprocess": subprocess,
                     "commit_source_archive": archive}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "qa_release_gate.py", "exec"), namespace)
        digest_for = namespace["commit_source_archive_sha256"]
        commit = "a" * 40

        expected = hashlib.sha256(b"deterministic git archive").hexdigest()
        self.assertEqual(digest_for(commit), expected)
        self.assertNotEqual(digest_for(commit), "0" * 64)

        archive.reset_mock()
        self.assertIsNone(digest_for("not-a-commit"))
        archive.assert_not_called()

        archive.side_effect = subprocess.CalledProcessError(128, ["git", "archive"])
        self.assertIsNone(digest_for(commit))

    def test_publication_gate_reports_blocked_with_separate_tracks(self):
        result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(set(report["tracks"]), {"public_source_repository", "hosted_non_wagering_preview", "stake_engine_real_money_release"})
        self.assertTrue(all(track["status"] == "BLOCKED" for track in report["tracks"].values()))

    def test_source_gate_separates_filesystem_presence_from_git_tracking(self):
        result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
        report = json.loads(result.stdout)
        source = report["checks"]["source_complete_and_tracked"]
        self.assertTrue(source["filesystem_present"], source)
        self.assertTrue(source["tracking_complete"], source)
        self.assertEqual(source["tracked_missing"], [])
        self.assertEqual(source["tracked_invalid"], [])
        self.assertEqual(source["counts"]["untracked_required"], 0)
        self.assertEqual(set(source["missing"]), set(source["untracked_required"]))
        for relative in source["untracked_required"]:
            path = ROOT / relative
            self.assertTrue(path.is_file() and not path.is_symlink(), relative)

    def test_historical_qa_evidence_is_hash_verified_but_not_current_authority(self):
        result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
        report = json.loads(result.stdout)
        evidence = report["checks"]["historical_qa_evidence_integrity"]
        self.assertTrue(evidence["pass"], evidence)
        self.assertEqual(evidence["authority_status"], "SUPERSEDED_HISTORICAL_QA_EVIDENCE")
        self.assertEqual(evidence["git_tracking"], "UNTRACKED_HISTORICAL_EVIDENCE")
        self.assertIn("not current", evidence["release_use"])

    def test_offline_preview_and_accessibility_evidence_are_separate_from_external_acceptance(self):
        result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
        report = json.loads(result.stdout)
        preview = report["checks"]["offline_frontend_preview_integrity"]
        accessibility = report["checks"]["local_accessibility_reflow"]
        self.assertTrue(preview["pass"], preview)
        self.assertFalse(accessibility["pass"], accessibility)
        self.assertFalse(accessibility.get("full_wcag_aa", False))
        self.assertFalse(accessibility.get("physical_device_acceptance", False))
        self.assertFalse(report["checks"]["accessibility_and_physical_devices"]["pass"])

    def test_release_evidence_integrity_is_distinct_from_release_clearance(self):
        result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
        report = json.loads(result.stdout)
        for name in ("ci_workflow_definition", "source_path_classification_integrity"):
            self.assertTrue(report["checks"][name]["pass"], (name, report["checks"][name]))
        self.assertTrue(report["checks"]["source_path_classification_integrity"]["source_tracking_complete"])
        self.assertFalse(report["checks"]["project_license"]["pass"])
        self.assertFalse(report["checks"]["asset_redistribution_rights"]["pass"])
        self.assertFalse(report["checks"]["canonical_math_and_provider_approval"]["pass"])
        self.assertFalse(report["checks"]["production_rgs_wallet_contract"]["pass"])

    def test_generated_build_outputs_do_not_count_as_missing_source(self):
        token = uuid.uuid4().hex
        ds_store = ROOT / "frontend" / ".DS_Store"
        original_ds_store = ds_store.read_bytes() if ds_store.exists() else None
        generated = [ROOT / "dist" / ("release-artifact-" + token + ".tmp"),
                     ROOT / "build" / ("generated-" + token + ".tmp"),
                     ROOT / "src" / ("ganesha_full_scratch_v1_" + token + ".egg-info") / "SOURCES.txt",
                     ROOT / "artifacts" / ("ganesha-preview-" + token + ".png"),
                     ROOT / "artifacts" / ("qa-probe-" + token) / "browser-report.json", ds_store]
        created_parents = []
        baseline_result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
        baseline_report = json.loads(baseline_result.stdout)
        baseline_missing = set(baseline_report["checks"]["source_complete_and_tracked"]["missing"])
        generated_rel = {path.relative_to(ROOT).as_posix() for path in generated}
        try:
            for path in generated:
                if not path.parent.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    created_parents.append(path.parent)
                path.write_text("generated\n", encoding="utf-8")
            result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
            report = json.loads(result.stdout)
            after_missing = set(report["checks"]["source_complete_and_tracked"]["missing"])
            self.assertTrue(generated_rel.isdisjoint(after_missing), report["checks"]["source_complete_and_tracked"])
            self.assertEqual(after_missing, baseline_missing, report["checks"]["source_complete_and_tracked"])
        finally:
            for path in generated:
                if path == ds_store and original_ds_store is not None:
                    path.write_bytes(original_ds_store)
                elif path.exists():
                    path.unlink()
            for directory in reversed(created_parents):
                try:
                    directory.rmdir()
                except OSError:
                    pass

    def test_generated_frontend_build_and_node_modules_are_not_source_completeness_blockers(self):
        frontend_build = ROOT / "frontend-build"
        node_modules = ROOT / "node_modules"
        frontend_build_existed = frontend_build.exists()
        node_modules_existed = node_modules.exists()
        frontend_build.mkdir(parents=True, exist_ok=True)
        node_modules.mkdir(parents=True, exist_ok=True)
        baseline_result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
        baseline_report = json.loads(baseline_result.stdout)
        baseline_missing = set(baseline_report["checks"]["source_complete_and_tracked"]["missing"])
        try:
            # Use unique child directories: never overwrite or unlink a real build entrypoint.
            with tempfile.TemporaryDirectory(prefix="gate-probe-", dir=str(frontend_build)) as build_probe, \
                 tempfile.TemporaryDirectory(prefix="gate-probe-", dir=str(node_modules)) as modules_probe:
                generated = [Path(build_probe) / "index.html", Path(modules_probe) / "package.json"]
                for path in generated:
                    path.write_text("generated\n", encoding="utf-8")
                generated_rel = {path.relative_to(ROOT).as_posix() for path in generated}
                result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
                report = json.loads(result.stdout)
                after_missing = set(report["checks"]["source_complete_and_tracked"]["missing"])
                self.assertTrue(generated_rel.isdisjoint(after_missing), report["checks"]["source_complete_and_tracked"])
                self.assertEqual(after_missing, baseline_missing, report["checks"]["source_complete_and_tracked"])
        finally:
            if not frontend_build_existed:
                try:
                    frontend_build.rmdir()
                except OSError:
                    pass
            if not node_modules_existed:
                try:
                    node_modules.rmdir()
                except OSError:
                    pass

    def test_frontend_snapshot_is_excluded_from_source_but_requires_exact_integrity_manifest(self):
        snapshot = ROOT / "frontend" / "artifacts" / "FRONTEND_BUILD_V15_ART_20261104_R1"
        probe = snapshot / ("integrity-probe-" + uuid.uuid4().hex + ".tmp")
        baseline = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
        baseline_report = json.loads(baseline.stdout)
        baseline_missing = set(baseline_report["checks"]["source_complete_and_tracked"]["missing"])
        snapshot_paths = {p.relative_to(ROOT).as_posix() for p in snapshot.rglob("*")
                          if p.is_file() and p.name != ".DS_Store"}
        self.assertTrue(snapshot_paths.isdisjoint(baseline_missing), baseline_report["checks"]["source_complete_and_tracked"])
        self.assertTrue(baseline_report["checks"]["generated_frontend_snapshot_integrity"]["pass"],
                        baseline_report["checks"]["generated_frontend_snapshot_integrity"])
        try:
            probe.write_text("unmanifested generated output\n", encoding="utf-8")
            changed = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
            changed_report = json.loads(changed.stdout)
            self.assertFalse(changed_report["checks"]["generated_frontend_snapshot_integrity"]["pass"])
            changed_missing = set(changed_report["checks"]["source_complete_and_tracked"]["missing"])
            self.assertIn(probe.relative_to(ROOT).as_posix(), changed_missing)
            self.assertTrue(snapshot_paths.issubset(changed_missing), changed_report["checks"]["source_complete_and_tracked"])
        finally:
            if probe.exists():
                probe.unlink()

    def test_untracked_frontend_artifacts_content_outside_build_snapshot_remains_source(self):
        probe_dir = ROOT / "frontend" / "artifacts" / ("source-probe-" + uuid.uuid4().hex)
        probe = probe_dir / "source.py"
        try:
            probe_dir.mkdir(parents=True)
            probe.write_text("# ordinary frontend artifact namespace content is not auto-generated\n", encoding="utf-8")
            result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
            report = json.loads(result.stdout)
            self.assertIn(probe.relative_to(ROOT).as_posix(),
                          report["checks"]["source_complete_and_tracked"]["missing"])
            self.assertFalse(report["checks"]["source_complete_and_tracked"]["pass"])
        finally:
            if probe.exists():
                probe.unlink()
            if probe_dir.exists():
                probe_dir.rmdir()

    def test_untracked_source_file_is_a_completeness_blocker(self):
        probe = ROOT / "src" / "ganesha" / ("untracked_release_gate_probe_" + uuid.uuid4().hex + ".py")
        try:
            probe.write_text("# untracked source must block publication\n", encoding="utf-8")
            result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
            report = json.loads(result.stdout)
            self.assertFalse(report["checks"]["source_complete_and_tracked"]["pass"])
            self.assertIn(probe.relative_to(ROOT).as_posix(),
                          report["checks"]["source_complete_and_tracked"]["missing"])
        finally:
            if probe.exists():
                probe.unlink()

    def test_empty_asset_inventory_cannot_clear_redistribution_rights(self):
        path = ROOT / "frontend" / "assets" / "ASSET_PROVENANCE.json"
        original = path.read_bytes()
        try:
            manifest = json.loads(original)
            manifest["status"] = "CLEARED"
            manifest["assets"] = []
            path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
            report = json.loads(result.stdout)
            self.assertFalse(report["checks"]["asset_redistribution_rights"]["pass"])
            self.assertIn("empty", report["checks"]["asset_redistribution_rights"]["evidence"])
        finally:
            path.write_bytes(original)

    def test_nested_audio_assets_are_covered_by_relative_asset_inventory_paths(self):
        result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
        report = json.loads(result.stdout)
        evidence = report["checks"]["asset_redistribution_rights"]["evidence"]
        self.assertNotIn("inventory does not exactly cover", evidence)
        self.assertIn("creator is not established", evidence)

    def test_cleared_flag_without_asset_level_rights_evidence_cannot_pass(self):
        path = ROOT / "frontend" / "assets" / "ASSET_PROVENANCE.json"
        original = path.read_bytes()
        try:
            manifest = json.loads(original)
            manifest["status"] = "CLEARED"
            first = manifest["assets"][0]
            first["creator"] = "Creator"
            first["redistribution_rights"] = "cleared"
            first.pop("rights_holder", None)
            first.pop("license", None)
            first.pop("modification_permission", None)
            first.pop("redistribution_permission", None)
            first.pop("rights_evidence_ref", None)
            path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
            report = json.loads(result.stdout)
            self.assertFalse(report["checks"]["asset_redistribution_rights"]["pass"])
        finally:
            path.write_bytes(original)

    def test_build_reproducibility_evidence_is_source_bound(self):
        result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
        report = json.loads(result.stdout)
        evidence = json.loads((ROOT / "artifacts" / "BUILD_REPRODUCIBILITY_20261103.json").read_text())
        tracked = subprocess.check_output(["git", "ls-files"], cwd=str(ROOT), text=True).splitlines()
        current_manifest = {}
        for rel in tracked:
            if rel == "artifacts/BUILD_REPRODUCIBILITY_20261103.json":
                continue
            path = ROOT / rel
            if path.is_file():
                current_manifest[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        ancestors = all(subprocess.run(["git", "merge-base", "--is-ancestor", evidence[field], "HEAD"],
                                       cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
                        for field in ("tested_commit", "clean_clone_test_commit", "source_manifest_commit"))
        expected_pass = (evidence.get("source_manifest") == current_manifest and ancestors
                         and evidence.get("two_clean_clone_builds_byte_identical") is True
                         and evidence.get("toolchain") == {
                             "python": "3.13.17", "pip": "26.3", "build": "1.4.4", "importlib_metadata": "8.7.1",
                             "packaging": "26.3", "pyproject_hooks": "1.3.3", "setuptools": "84.1.0",
                             "tomli": "2.5.0", "wheel": "0.48.0", "zipp": "3.23.1"
                         }
                         and evidence.get("clean_clone_test_status") == "PASS"
                         and type(evidence.get("clean_clone_test_count")) is int
                         and evidence.get("clean_clone_test_count", 0) > 0
                         and evidence.get("clean_clone_count") == 2
                         and all(evidence.get(field) == evidence.get("tested_commit")
                                 for field in ("clean_clone_test_commit", "source_manifest_commit")))
        self.assertEqual(report["checks"]["build_reproducibility"]["pass"], expected_pass,
                         report["checks"]["build_reproducibility"])
        self.assertFalse(report["checks"]["signed_release_manifest_and_sbom"]["pass"])

    def test_ci_definition_exists_but_hosted_evidence_is_not_invented(self):
        workflow = ROOT / ".github/workflows/ci.yml"
        self.assertTrue(workflow.is_file())
        workflow_text = workflow.read_text()
        self.assertIn("actions/attest-build-provenance", workflow_text)
        self.assertIn("clean-clone-build-test:", workflow_text)
        self.assertIn("attest-release:", workflow_text)
        self.assertIn("if: github.event_name != 'pull_request' && github.ref == 'refs/heads/main'", workflow_text)
        self.assertNotIn("permissions:\n  contents: read\n  id-token: write", workflow_text)
        result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
        report = json.loads(result.stdout)
        self.assertFalse(report["checks"]["ci_workflow"]["pass"])

    def test_build_reproducibility_fails_closed_without_clean_clone_test_evidence(self):
        path = ROOT / "artifacts" / "BUILD_REPRODUCIBILITY_20261103.json"
        original = path.read_bytes()
        try:
            baseline = json.loads(original)
            mutations = (
                {"clean_clone_test_status": "PENDING_FINAL_POST_EVIDENCE_RUN"},
                {"clean_clone_test_count": 0},
                {"clean_clone_test_commit": "not-a-commit"},
                {"source_manifest_commit": "not-a-commit"},
                {"tested_commit": "f" * 40},
                {"clean_clone_count": 1},
                {"toolchain": {"python": "3.9.6"}},
                {"clean_clone_test_results": {"clone_a": {"status": "FAIL", "tests": 78}, "clone_b": {"status": "PASS", "tests": 78}}},
                {"source_manifest_entries": 1},
            )
            for mutation in mutations:
                evidence = dict(baseline)
                evidence.update(mutation)
                path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
                report = json.loads(result.stdout)
                self.assertFalse(report["checks"]["build_reproducibility"]["pass"], mutation)
        finally:
            path.write_bytes(original)

    def test_build_evidence_cannot_bind_uncommitted_source_bytes(self):
        evidence_path = ROOT / "artifacts" / "BUILD_REPRODUCIBILITY_20261103.json"
        source_path = ROOT / "docs" / "implementation-status.md"
        original_evidence = evidence_path.read_bytes()
        original_source = source_path.read_bytes()
        try:
            source_path.write_bytes(original_source + b"\n# temporary uncommitted mutation\n")
            evidence = json.loads(original_evidence)
            evidence["source_manifest"]["docs/implementation-status.md"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
            evidence["source_manifest_entries"] = len(evidence["source_manifest"])
            evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
            report = json.loads(result.stdout)
            self.assertFalse(report["checks"]["build_reproducibility"]["pass"])
        finally:
            source_path.write_bytes(original_source)
            evidence_path.write_bytes(original_evidence)

    def test_build_evidence_git_archive_digest_is_bound_to_tested_commit(self):
        with tempfile.TemporaryDirectory(prefix="publication-gate-archive-") as temporary:
            root = Path(temporary)
            (root / "tools").mkdir()
            (root / "frontend" / "assets").mkdir(parents=True)
            (root / "artifacts").mkdir()
            (root / "tools" / "__init__.py").write_text("", encoding="utf-8")
            for relative in ("qa_release_gate.py", "qa_source_completeness.py", "tools/source_path_policy.py",
                             "tools/verify_manifest_source_inventory.py"):
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT / relative).read_bytes())
            (root / "frontend" / "assets" / "ASSET_PROVENANCE.json").write_text(
                json.dumps({"schema": "ganesha-assets-provenance.v1", "status": "PENDING", "assets": []}),
                encoding="utf-8")
            (root / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
            subprocess.run(["git", "config", "user.email", "gate@example.invalid"], cwd=str(root), check=True)
            subprocess.run(["git", "config", "user.name", "Publication Gate Test"], cwd=str(root), check=True)
            subprocess.run(["git", "add", "qa_release_gate.py", "tools", "frontend", "source.py"],
                           cwd=str(root), check=True)
            subprocess.run(["git", "commit", "-qm", "publication gate fixture"], cwd=str(root), check=True)
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(root), text=True).strip()
            archive = subprocess.check_output(["git", "archive", "--format=tar", commit], cwd=str(root))
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source_tar:
                source_manifest = {
                    member.name: hashlib.sha256(source_tar.extractfile(member).read()).hexdigest()
                    for member in source_tar.getmembers() if member.isfile()
                }
            evidence = {
                "schema": "ganesha-build-reproducibility.v1",
                "tested_commit": commit,
                "clean_clone_test_commit": commit,
                "source_manifest_commit": commit,
                "source_manifest": source_manifest,
                "source_manifest_entries": len(source_manifest),
                "two_clean_clone_builds_byte_identical": True,
                "toolchain": {
                    "python": "3.13.17", "pip": "26.3", "build": "1.4.4", "importlib_metadata": "8.7.1",
                    "packaging": "26.3", "pyproject_hooks": "1.3.3", "setuptools": "84.1.0",
                    "tomli": "2.5.0", "wheel": "0.48.0", "zipp": "3.23.1",
                },
                "wheel_sha256": "1" * 64,
                "sdist_sha256": "2" * 64,
                "sbom_sha256": "3" * 64,
                "clean_clone_test_status": "PASS",
                "clean_clone_test_count": 1,
                "clean_clone_count": 2,
                "clean_clone_test_results": {
                    "clone_a": {"status": "PASS", "tests": 1},
                    "clone_b": {"status": "PASS", "tests": 1},
                },
                "git_archive_sha256": hashlib.sha256(archive).hexdigest(),
            }
            evidence_path = root / "artifacts" / "BUILD_REPRODUCIBILITY_20261103.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

            valid = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(root), capture_output=True, text=True)
            valid_report = json.loads(valid.stdout)
            self.assertTrue(valid_report["checks"]["build_reproducibility"]["pass"],
                            valid_report["checks"]["build_reproducibility"])

            evidence["git_archive_sha256"] = "0" * 64
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            forged = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(root), capture_output=True, text=True)
            forged_report = json.loads(forged.stdout)
            self.assertFalse(forged_report["checks"]["build_reproducibility"]["pass"],
                             forged_report["checks"]["build_reproducibility"])

    def test_no_license_and_asset_rights_are_explicit_blockers(self):
        self.assertFalse((ROOT / "LICENSE").exists())
        result = subprocess.run([sys.executable, "qa_release_gate.py"], cwd=str(ROOT), capture_output=True, text=True)
        report = json.loads(result.stdout)
        self.assertFalse(report["checks"]["project_license"]["pass"])
        self.assertFalse(report["checks"]["asset_redistribution_rights"]["pass"])


if __name__ == "__main__":
    unittest.main()
