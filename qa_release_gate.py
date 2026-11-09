"""Evidence-based release gate for source, hosted preview and Stake/real-money tracks."""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from tools.verify_manifest_source_inventory import verify_manifest_source_inventory
from tools.source_path_policy import is_excluded_artifact_path, is_excluded_source_path
from qa_source_completeness import classify_source_completeness

ROOT = Path(__file__).resolve().parent
EXPECTED_BUILD_TOOLCHAIN = {
    "python": "3.13.17", "pip": "26.3", "build": "1.4.4", "importlib_metadata": "8.7.1",
    "packaging": "26.3", "pyproject_hooks": "1.3.3", "setuptools": "84.1.0",
    "tomli": "2.5.0", "wheel": "0.48.0", "zipp": "3.23.1",
}


def run_git(*args):
    try:
        return subprocess.check_output(["git", *args], cwd=str(ROOT), stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return ""


def is_ancestor(commit):
    if re.fullmatch(r"[0-9a-f]{40}", str(commit)) is None:
        return False
    result = subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=str(ROOT),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def commit_source_archive(commit):
    """Return the exact committed source snapshot as a deterministic Git archive."""
    return subprocess.check_output(
        ["git", "archive", "--format=tar", commit], cwd=str(ROOT), stderr=subprocess.DEVNULL
    )


def commit_source_archive_sha256(commit):
    """Return the archive digest for a valid commit, failing closed on Git errors."""
    if re.fullmatch(r"[0-9a-f]{40}", str(commit)) is None:
        return None
    try:
        return hashlib.sha256(commit_source_archive(commit)).hexdigest()
    except (OSError, subprocess.CalledProcessError):
        return None


def commit_source_manifest(commit, archive=None):
    """Hash the exact committed source snapshot from one Git archive operation."""
    if archive is None:
        archive = commit_source_archive(commit)
    manifest = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source_tar:
        for member in source_tar.getmembers():
            if member.isdir():
                continue
            if member.name == "artifacts/BUILD_REPRODUCIBILITY_20261103.json":
                continue
            if member.issym() or member.islnk() or not member.isfile():
                raise ValueError("committed source snapshot contains a non-regular file")
            stream = source_tar.extractfile(member)
            if stream is None:
                raise ValueError("committed source snapshot contains an unreadable file")
            manifest[member.name] = hashlib.sha256(stream.read()).hexdigest()
    return manifest


tracked = set(run_git("ls-files").splitlines())


def validate_asset_manifest(manifest, assets_dir):
    """Require a complete, non-empty, byte-verified asset inventory and explicit rights."""
    if not isinstance(manifest, dict) or manifest.get("schema") != "ganesha-assets-provenance.v1":
        return False, "asset provenance schema is missing or unsupported"
    entries = manifest.get("assets")
    if not isinstance(entries, list) or not entries:
        return False, "asset provenance inventory is empty or malformed"
    assets_root = assets_dir.resolve()
    all_paths = list(assets_dir.rglob("*"))
    if any(path.is_symlink() for path in all_paths):
        return False, "asset directory contains a symlink"
    actual_files = {
        path.relative_to(assets_dir).as_posix() for path in all_paths
        if path.is_file() and path.suffix.lower() in {".svg", ".png", ".jpg", ".jpeg", ".webp", ".woff", ".woff2", ".mp3", ".wav"}
        and path.name != "ASSET_PROVENANCE.json"
    }
    declared_files = [item.get("file") for item in entries if isinstance(item, dict)]
    if (len(declared_files) != len(entries)
            or any(not isinstance(filename, str) or not filename for filename in declared_files)
            or len(set(declared_files)) != len(declared_files)):
        return False, "asset provenance contains malformed or duplicate entries"
    if set(declared_files) != actual_files:
        return False, "asset provenance inventory does not exactly cover current distributable assets"
    for item in entries:
        filename = item["file"]
        relative = PurePosixPath(filename) if isinstance(filename, str) else None
        if (relative is None or not filename or "\\" in filename or relative.is_absolute()
                or ".." in relative.parts or "." in relative.parts):
            return False, "asset provenance contains an unsafe asset path"
        asset_path = assets_dir.joinpath(*relative.parts)
        resolved = asset_path.resolve()
        if assets_root not in resolved.parents or not asset_path.is_file() or asset_path.is_symlink():
            return False, "asset path is missing, symlinked or escapes the asset directory for %s" % filename
        digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
        if item.get("sha256") != digest or item.get("bytes") != asset_path.stat().st_size:
            return False, "asset provenance hash or byte size does not match %s" % filename
        creator = item.get("creator")
        if (not isinstance(creator, str) or not creator.strip()
                or creator.strip().lower() in ("unknown", "not established", "not established in current evidence")):
            return False, "asset creator is not established for %s" % filename
        for field in ("rights_holder", "license", "rights_evidence_ref"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip() or value.strip().lower() in ("unknown", "not established", "not established in current evidence"):
                return False, "asset %s is not established for %s" % (field, filename)
        if (item.get("redistribution_rights") != "cleared"
                or item.get("modification_permission") != "granted"
                or item.get("redistribution_permission") != "granted"):
            return False, "asset modification/redistribution permission is not cleared for %s" % filename
    if manifest.get("status") != "CLEARED":
        return False, "asset provenance status is not CLEARED"
    return True, "all current assets are inventoried, hash-verified and rights-cleared"


def validate_historical_qa_evidence(evidence_dir):
    """Verify the historical repair report checksum without treating it as current authority."""
    expected_report = "REPAIR_AND_REVALIDATION_REPORT.md"
    expected_sums = "SHA256SUMS.txt"
    if evidence_dir.is_symlink() or not evidence_dir.is_dir():
        return {"pass": False, "evidence": "historical QA evidence directory is missing or not regular"}
    report = evidence_dir / expected_report
    sums = evidence_dir / expected_sums
    if any(path.is_symlink() or not path.is_file() for path in (report, sums)):
        return {"pass": False, "evidence": "historical QA report or checksum file is missing or unsafe"}
    actual_files = {path.name for path in evidence_dir.iterdir() if path.is_file() or path.is_symlink()}
    if actual_files != {expected_report, expected_sums}:
        return {"pass": False, "evidence": "historical QA evidence file inventory changed"}
    try:
        rows = [line.split() for line in sums.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, UnicodeError):
        return {"pass": False, "evidence": "historical QA checksum file is unreadable"}
    relative_report = report.relative_to(ROOT).as_posix()
    if (len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != relative_report
            or rows[0][0] != hashlib.sha256(report.read_bytes()).hexdigest()):
        return {"pass": False, "evidence": "historical QA report SHA-256 does not match its checksum record"}
    tracked_paths = set(run_git("ls-files").splitlines())
    relative_sums = sums.relative_to(ROOT).as_posix()
    tracked = relative_report in tracked_paths and relative_sums in tracked_paths
    return {
        "pass": True,
        "evidence": "historical repair report matches its one-entry SHA256SUMS record; integrity only",
        "authority_status": "SUPERSEDED_HISTORICAL_QA_EVIDENCE",
        "git_tracking": "TRACKED" if tracked else "UNTRACKED_HISTORICAL_EVIDENCE",
        "release_use": "not current Math, Scatter, Provider or submission authority",
    }


def validate_offline_frontend_preview(root):
    """Recompute the output/source hashes for every fail-closed offline preview."""
    integrity_files = sorted((root / "artifacts").glob("FRONTEND_BUILD_OFFLINE_*_INTEGRITY.json"))
    if not integrity_files:
        return {"pass": False, "evidence": "no offline frontend integrity evidence is present"}
    validated = []
    current_source_bound = False
    for integrity_path in integrity_files:
        try:
            record = json.loads(integrity_path.read_text(encoding="utf-8"))
            relative_output = record.get("output")
            if (record.get("schema") != "ganesha.frontend-offline-build-integrity.v1"
                    or record.get("classification") != "LOCAL_NON_WAGERING_ENGINEERING_BUILD_NOT_PROVIDER_APPROVAL"
                    or not isinstance(relative_output, str)
                    or not relative_output.startswith("artifacts/FRONTEND_BUILD_OFFLINE_")):
                return {"pass": False, "evidence": "offline frontend integrity record has invalid schema/classification"}
            output_candidate = root / relative_output
            if output_candidate.is_symlink():
                return {"pass": False, "evidence": "offline frontend output root is a symlink"}
            output = output_candidate.resolve()
            artifacts_root = (root / "artifacts").resolve()
            if artifacts_root not in output.parents or not output.is_dir() or output.is_symlink():
                return {"pass": False, "evidence": "offline frontend output path is missing, symlinked or outside artifacts"}
            declared = record.get("files")
            if not isinstance(declared, dict) or record.get("file_count") != len(declared):
                return {"pass": False, "evidence": "offline frontend file inventory is malformed"}
            actual = {}
            for path in output.rglob("*"):
                if path.is_symlink():
                    return {"pass": False, "evidence": "offline frontend output contains a symlink"}
                if path.is_file():
                    relative = path.relative_to(output).as_posix()
                    data = path.read_bytes()
                    actual[relative] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            if actual != declared:
                return {"pass": False, "evidence": "offline frontend output does not match its exact integrity manifest"}
            tree_records = "".join("%s\0%s\0%s\n" % (name, item["bytes"], item["sha256"])
                                   for name, item in sorted(actual.items()))
            tree_digest = hashlib.sha256(tree_records.encode("utf-8")).hexdigest()
            if tree_digest != record.get("tree_sha256"):
                return {"pass": False, "evidence": "offline frontend tree SHA-256 mismatch"}
            source_hashes = record.get("source_sha256")
            if not isinstance(source_hashes, dict) or not source_hashes:
                return {"pass": False, "evidence": "offline frontend source hash inventory is missing"}
            source_binding = "HISTORICAL_OR_UNBOUND_SOURCE_SNAPSHOT"
            if record.get("git_head") == run_git("rev-parse", "HEAD"):
                if (record.get("git_tree") != run_git("rev-parse", "HEAD^{tree}")
                        or not isinstance(record.get("source_worktree_dirty"), bool)
                        or re.fullmatch(r"[0-9a-f]{64}", str(record.get("source_worktree_status_sha256", ""))) is None):
                    return {"pass": False, "evidence": "offline frontend Git/source-state binding is malformed"}
                source_matches = True
                for relative, digest in source_hashes.items():
                    source = root / relative
                    if (source.is_symlink() or not source.is_file()
                            or hashlib.sha256(source.read_bytes()).hexdigest() != digest):
                        source_matches = False
                        break
                if source_matches:
                    source_binding = "CURRENT_HEAD_AND_WORKTREE_SOURCE_HASHES_MATCH"
                    current_source_bound = True
                else:
                    source_binding = "WORKTREE_SOURCE_CHANGED_AFTER_BUILD"
            elif re.fullmatch(r"[0-9a-f]{40}", str(record.get("git_head", ""))):
                source_binding = "PREVIOUS_COMMIT_SNAPSHOT"
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            if (manifest.get("package_kind") != "NON_FINANCIAL_ENGINEERING_PREVIEW"
                    or manifest.get("capabilities", {}).get("wagering") is not False
                    or manifest.get("capabilities", {}).get("bonus_buy") is not False
                    or manifest.get("capabilities", {}).get("play") is not False):
                return {"pass": False, "evidence": "offline frontend manifest does not fail closed for financial capabilities"}
            validated.append({"output": relative_output, "file_count": len(actual), "tree_sha256": tree_digest,
                              "source_binding": source_binding})
        except Exception as exc:
            return {"pass": False, "evidence": "unable to validate offline frontend preview: %s" % type(exc).__name__}
    if not current_source_bound:
        return {"pass": False, "evidence": "offline frontend outputs are byte-verified, but no build is bound to current HEAD and current source hashes"}
    return {"pass": True, "evidence": "offline frontend outputs are byte-verified and at least one build is bound to current HEAD/current source hashes",
            "classification": "LOCAL_NON_WAGERING_ENGINEERING_PREVIEW_ONLY", "builds": validated}


def validate_release_path_classification(root, source_completeness):
    """Verify the per-file source/evidence classification without hiding untracked source."""
    path = root / "artifacts/RELEASE_PATH_CLASSIFICATION_20261107_R12C.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        entries = record.get("files")
        if (record.get("schema") != "ganesha-release-path-classification.r12c"
                or record.get("git_head") != run_git("rev-parse", "HEAD")
                or not isinstance(entries, list)
                or record.get("classified_total") != len(entries)
                or record.get("all_classified_paths_present_as_regular_files") is not True):
            return {"pass": False, "evidence": "release path classification report is malformed"}
        by_path = {item.get("path"): item for item in entries if isinstance(item, dict)}
        if len(by_path) != len(entries):
            return {"pass": False, "evidence": "release path classification contains duplicate or malformed paths"}
        source_paths = {name for name, item in by_path.items() if item.get("source_completeness_required") is True}
        evidence_paths = {name for name, item in by_path.items() if item.get("source_completeness_required") is False}
        if source_paths != set(source_completeness["untracked_required"]):
            return {"pass": False, "evidence": "classified source path set does not match the live source completeness policy"}
        tracked_paths = set(run_git("ls-files").splitlines())
        for relative, item in by_path.items():
            target = root / relative
            if (target.is_symlink() or not target.is_file()
                    or item.get("sha256") != hashlib.sha256(target.read_bytes()).hexdigest()
                    or item.get("git_tracked") != (relative in tracked_paths)):
                return {"pass": False, "evidence": "classified file is missing or its hash changed: %s" % relative}
        if len(evidence_paths) != 2 or record.get("historical_qa_checksum_valid") is not True:
            return {"pass": False, "evidence": "historical QA evidence is not separately classified and checksum-verified"}
        return {"pass": True, "evidence": "all classified source/evidence paths exist and their SHA-256 values match",
                "source_path_count": len(source_paths), "historical_evidence_count": len(evidence_paths),
                "source_tracking_complete": not source_paths,
                "untracked_source_paths_remain_blocking": len(source_paths)}
    except Exception as exc:
        return {"pass": False, "evidence": "unable to validate source path classification: %s" % type(exc).__name__}


def validate_r9_frontend_candidate(root):
    """Verify the preserved R9 Frontend-only ZIP without treating it as a complete submission."""
    path = root / "artifacts/STAKE_FRONTEND_R98_PRODUCTION_ONLY_R9_20261107.zip"
    expected = "2ff26b987b7d9b5eb12fe4f0952c8756be29e7b4c623447af0daf9b1815b868c"
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with zipfile.ZipFile(path) as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            names = {item.filename for item in files}
            required = {"manifest.json", "UPLOAD_MANIFEST.json", "SDK_PROVENANCE_RECONCILIATION.json",
                        "MATH_CONTRACT_STATUS.json", "SCATTER_PAYTABLE_CONTRACT.json",
                        "REPLAY_CONTRACT_STATUS.json", "MATH_BUY_MODE_AUDIT_ADDENDUM.json"}
            missing = sorted(required - names)
        verifier = subprocess.run([sys.executable, str(root / "tools/verify_stake_package.py"),
                                   "frontend-zip", str(path)], cwd=str(root), capture_output=True, text=True)
        valid = digest == expected and len(files) == 195 and not missing and verifier.returncode == 0
        return {"pass": valid, "evidence": "R9 Frontend-only ZIP hash, 195-file inventory and structural verifier",
                "sha256": digest, "file_count": len(files), "missing_contract_files": missing,
                "verifier_exit": verifier.returncode, "complete_math_frontend_submission": False,
                "studio_uploaded": False}
    except Exception as exc:
        return {"pass": False, "evidence": "unable to validate preserved R9 Frontend ZIP: %s" % type(exc).__name__}


def validate_local_worktree_reproducibility(root):
    """Verify two-copy worktree reproducibility while explicitly withholding exact-HEAD credit."""
    try:
        report = json.loads((root / "artifacts/WORKTREE_BUILD_REPRODUCIBILITY_20261107_R12D.json").read_text())
        clones = report.get("clones", {})
        first, second = clones.get("clone-a", {}), clones.get("clone-b", {})
        first_manifest, second_manifest = first.get("source_manifest", {}), second.get("source_manifest", {})
        manifest_hash = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        manifest_matches = (isinstance(first_manifest, dict) and first_manifest == second_manifest
                            and manifest_hash(first_manifest) == first.get("source_manifest_sha256")
                            and manifest_hash(second_manifest) == second.get("source_manifest_sha256"))
        current_source_matches = bool(first_manifest)
        for relative, digest in first_manifest.items():
            source = root / relative
            if (source.is_symlink() or not source.is_file()
                    or hashlib.sha256(source.read_bytes()).hexdigest() != digest):
                current_source_matches = False
                break
        wheel_match = first.get("wheel", {}).get("sha256") == second.get("wheel", {}).get("sha256")
        sdist_match = first.get("normalized_sdist", {}).get("sha256") == second.get("normalized_sdist", {}).get("sha256")
        valid = (report.get("schema") == "ganesha-worktree-build-reproducibility.r12d"
                 and report.get("git_head") == run_git("rev-parse", "HEAD")
                 and report.get("git_head_is_clean") is False
                 and report.get("source_manifests_identical") is True
                 and report.get("wheel_hashes_identical") is True
                 and report.get("normalized_sdist_hashes_identical") is True
                 and manifest_matches and current_source_matches and wheel_match and sdist_match)
        return {"pass": valid, "evidence": "two clean filesystem copies reproduce identical wheel and normalized sdist from the current dirty worktree snapshot",
                "source_files": len(first_manifest), "wheel_sha256": first.get("wheel", {}).get("sha256"),
                "normalized_sdist_sha256": first.get("normalized_sdist", {}).get("sha256"),
                "exact_tracked_head_clone": False, "hosted_ci_attestation": False}
    except Exception as exc:
        return {"pass": False, "evidence": "unable to validate local worktree reproducibility: %s" % type(exc).__name__}


def validate_r12_dependency_security(root):
    """Validate the local Python/npm dependency scan evidence, not the whole release security posture."""
    try:
        report = json.loads((root / "artifacts/SECURITY_DEPENDENCY_AUDIT_20261107_R12.json").read_text())
        python_dependencies = report.get("pip_audit_result", {}).get("dependencies", [])
        python_vulnerabilities = sum(len(item.get("vulns", [])) for item in python_dependencies)
        npm = report.get("npm_audit_vulnerabilities", {})
        valid = (report.get("schema") == "ganesha-security-dependency-audit.r12"
                 and report.get("python") == "3.13.17"
                 and report.get("pip") == "26.3"
                 and report.get("setuptools") == "84.1.0"
                 and len(python_dependencies) == 35
                 and python_vulnerabilities == 0
                 and report.get("python_vulnerability_count") == 0
                 and isinstance(npm, dict) and npm.get("total") == 0
                 and report.get("dependency_security_status") == "PASS_FOR_SCANNED_LOCAL_BUILD_TEST_AND_NPM_DEPENDENCIES")
        return {"pass": valid, "evidence": "R12 pip-audit (35 packages) and npm audit results; dependency scans only",
                "python_packages": len(python_dependencies), "python_vulnerabilities": python_vulnerabilities,
                "npm_vulnerabilities": npm.get("total"), "whole_release_security_clearance": False}
    except Exception as exc:
        return {"pass": False, "evidence": "unable to validate R12 dependency security evidence: %s" % type(exc).__name__}


def validate_r12_sbom(root):
    """Recheck the current SBOM against pinned requirements and npm lock graph."""
    sbom_path = root / "artifacts/SBOM_STAKE_CANDIDATE_20261107_R12.cdx.json"
    verification_path = root / "artifacts/SBOM_STAKE_CANDIDATE_20261107_R12_VERIFY.json"
    try:
        sbom = json.loads(sbom_path.read_text())
        verification = json.loads(verification_path.read_text())
        digest = hashlib.sha256(sbom_path.read_bytes()).hexdigest()
        result = subprocess.run([sys.executable, str(root / "tools/verify_sbom_completeness_20261104.py"),
                                 "--sbom", str(sbom_path)], cwd=str(root), capture_output=True, text=True)
        valid = (verification.get("status") == "PASS" and verification.get("sha256") == digest
                 and verification.get("component_count") == len(sbom.get("components", []))
                 and verification.get("npm_components") == 66
                 and verification.get("python_build_components") == 9
                 and verification.get("python_test_components") == 1
                 and verification.get("asset_components") == 22
                 and verification.get("python_license_gaps") == []
                 and result.returncode == 0 and "SBOM_COMPLETENESS=PASS" in result.stdout)
        return {"pass": valid, "evidence": "R12 CycloneDX SBOM hash, lockfile, build/test requirements and 22-asset inventory revalidated",
                "component_count": len(sbom.get("components", [])), "sha256": digest,
                "legal_asset_rights_clearance": False}
    except Exception as exc:
        return {"pass": False, "evidence": "unable to validate R12 SBOM: %s" % type(exc).__name__}


def validate_r12_license_and_asset_inventories(root):
    """Validate completeness/integrity of rights inventories without treating them as clearance."""
    try:
        license_report = json.loads((root / "artifacts/THIRD_PARTY_LICENSE_INVENTORY_20261107_R12.json").read_text())
        lock_digest = hashlib.sha256((root / "package-lock.json").read_bytes()).hexdigest()
        assets = json.loads((root / "artifacts/R9_ASSET_RIGHTS_AUDIT_20261107_R12.json").read_text())
        zip_digest = hashlib.sha256((root / "artifacts/STAKE_FRONTEND_R98_PRODUCTION_ONLY_R9_20261107.zip").read_bytes()).hexdigest()
        license_valid = (license_report.get("schema") == "ganesha-third-party-license-inventory.r12"
                         and license_report.get("npm_component_count") == 66
                         and license_report.get("python_component_count") == 10
                         and license_report.get("npm_lock_sha256") == lock_digest
                         and all(item.get("license_declared") for item in license_report.get("npm", []))
                         and all(item.get("license_expression") for item in license_report.get("python", [])))
        asset_valid = (assets.get("schema") == "ganesha-r9-asset-rights-audit.r12"
                       and assets.get("candidate_sha256") == zip_digest
                       and assets.get("media_count") == len(assets.get("media", []))
                       and assets.get("media_count") == 177
                       and assets.get("redistribution_cleared_media_count") == 0)
        return {"pass": license_valid and asset_valid,
                "evidence": "66 npm/10 Python license declarations and all 177 R9 media hashes inventoried; clearance remains separate",
                "npm_components": license_report.get("npm_component_count"),
                "python_components": license_report.get("python_component_count"),
                "r9_media_count": assets.get("media_count"),
                "r9_media_cleared": assets.get("redistribution_cleared_media_count"),
                "project_license_selected": license_report.get("project_license", {}).get("status") == "SELECTED",
                "redistribution_clearance": False}
    except Exception as exc:
        return {"pass": False, "evidence": "unable to validate license/asset inventory: %s" % type(exc).__name__}


def validate_ci_workflow_definition(root):
    """Check the local CI definition's immutable action pins and required local steps."""
    try:
        workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        action_lines = [line.strip() for line in workflow.splitlines() if "uses: actions/" in line]
        pins = [re.search(r"uses: actions/[A-Za-z0-9_-]+@([0-9a-f]{40})$", line) for line in action_lines]
        valid = (bool(action_lines) and all(pins)
                 and 'python-version: "3.13.17"' in workflow
                 and 'node-version: "22.23.4"' in workflow
                 and "npm ci" in workflow and "npm audit --audit-level=low" in workflow
                 and "make test" in workflow and "build:frontend:offline" in workflow
                 and "actions/attest-build-provenance@" in workflow)
        return {"pass": valid, "evidence": "local workflow has full 40-character action pins and Python/Node/npm/Python+Node test/offline-preview/attestation steps",
                "pinned_action_count": len(action_lines), "hosted_execution_verified": False}
    except Exception as exc:
        return {"pass": False, "evidence": "unable to validate CI workflow definition: %s" % type(exc).__name__}


def validate_browser_accessibility_reflow(root):
    """Validate the local 320px browser reflow/DOM semantics report, not WCAG certification."""
    try:
        report = json.loads((root / "artifacts/BROWSER_ACCESSIBILITY_QA_20261107_R12C.json").read_text())
        metrics = report.get("metrics", {})
        viewport = metrics.get("viewport", {})
        valid = (report.get("schema") == "ganesha-browser-accessibility-reflow-qa.v1"
                 and report.get("classification") == "LOCAL_BROWSER_REFLOW_AND_DOM_SEMANTICS_CHECK_NOT_FULL_WCAG_AA_OR_PHYSICAL_DEVICE_CERTIFICATION"
                 and report.get("pass") is True
                 and viewport.get("width") == 320
                 and viewport.get("horizontalOverflow") is False
                 and metrics.get("boardCells") == 15
                 and metrics.get("brokenImages") == []
                 and metrics.get("unnamedControls") == []
                 and metrics.get("undersizedTargets") == []
                 and metrics.get("financialControlsDisabled") is True
                 and metrics.get("bonusControlsDisabled") is True
                 and metrics.get("demoSpinNonFinancialLabel") is True
                 and report.get("skipFocus", {}).get("active") == "skip-link"
                 and report.get("skipFocus", {}).get("outline") == "solid"
                 and report.get("skipFocus", {}).get("width") == "3px"
                 and report.get("consoleErrors") == []
                 and report.get("exceptions") == []
                 and report.get("failedRequests") == [])
        return {"pass": valid, "evidence": "local 320 CSS-pixel Chrome reflow/DOM semantics check; not full WCAG AA or physical-device acceptance",
                "viewport_width": viewport.get("width"), "browser": report.get("browser"),
                "full_wcag_aa": False, "physical_device_acceptance": False}
    except Exception as exc:
        return {"pass": False, "evidence": "unable to validate local browser accessibility evidence: %s" % type(exc).__name__}


def validate_generated_frontend_snapshots(snapshot_root):
    """Return only FRONTEND_BUILD snapshots whose complete bytes are independently bound."""
    if not snapshot_root.exists():
        return True, "no generated frontend snapshots are present", set()
    if snapshot_root.is_symlink() or not snapshot_root.is_dir():
        return False, "frontend artifact namespace must be a regular directory", set()
    namespace_entries = sorted(snapshot_root.iterdir())
    if any(item.is_symlink() for item in namespace_entries):
        return False, "frontend artifact namespace contains a symlink", set()
    # Do not classify arbitrary frontend/artifacts content as generated. Only
    # explicitly named build snapshots are eligible for manifest-based exclusion.
    snapshots = [item for item in namespace_entries
                 if item.is_dir() and item.name.startswith("FRONTEND_BUILD_")]
    validated_roots = set()
    for snapshot in snapshots:
        manifest_path = snapshot / "snapshot.integrity.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return False, "generated frontend snapshot is missing a readable integrity manifest: %s" % snapshot.name, set()
        if (not isinstance(manifest, dict)
                or manifest.get("schema") != "ganesha.generated-frontend-snapshot-integrity.v1"
                or manifest.get("snapshot") != snapshot.relative_to(ROOT).as_posix()
                or not isinstance(manifest.get("files"), list)):
            return False, "generated frontend snapshot integrity manifest is malformed: %s" % snapshot.name, set()
        declared = {}
        for entry in manifest["files"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                return False, "generated frontend snapshot has a malformed file entry: %s" % snapshot.name, set()
            filename = entry["path"]
            relative = PurePosixPath(filename)
            if (not filename or "\\" in filename or relative.is_absolute()
                    or ".." in relative.parts or "." in relative.parts or filename in declared):
                return False, "generated frontend snapshot has an unsafe or duplicate path: %s" % filename, set()
            path = snapshot.joinpath(*relative.parts)
            cursor = snapshot
            has_symlink = False
            for part in relative.parts:
                cursor = cursor / part
                has_symlink = has_symlink or cursor.is_symlink()
            if (has_symlink or not path.is_file() or snapshot.resolve() not in path.resolve().parents):
                return False, "generated frontend snapshot file is missing, symlinked or escapes root: %s" % filename, set()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if entry.get("sha256") != digest or entry.get("bytes") != path.stat().st_size:
                return False, "generated frontend snapshot hash/size mismatch: %s/%s" % (snapshot.name, filename), set()
            declared[filename] = (digest, path.stat().st_size)
        actual = {}
        for path in snapshot.rglob("*"):
            if path.is_symlink():
                return False, "generated frontend snapshot contains a symlink: %s" % path, set()
            if path.is_file() and path.name not in (".DS_Store", "snapshot.integrity.json"):
                rel = path.relative_to(snapshot).as_posix()
                actual[rel] = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size)
        if actual != declared:
            return False, "generated frontend snapshot inventory does not exactly match its integrity manifest: %s" % snapshot.name, set()
        validated_roots.add(snapshot.relative_to(ROOT).as_posix())
    return True, "all generated frontend snapshots have exact byte-verified inventories", validated_roots


asset_manifest = json.loads((ROOT / "frontend/assets/ASSET_PROVENANCE.json").read_text())
assets_cleared, asset_rights_note = validate_asset_manifest(asset_manifest, ROOT / "frontend/assets")
historical_qa_evidence = validate_historical_qa_evidence(ROOT / "qa/work_20261106_submission_repair_r1")
frontend_snapshots_cleared, frontend_snapshots_note, validated_frontend_snapshot_roots = validate_generated_frontend_snapshots(ROOT / "frontend/artifacts")
source_completeness = classify_source_completeness(ROOT, tracked)
path_classification = validate_release_path_classification(ROOT, source_completeness)
offline_frontend_preview = validate_offline_frontend_preview(ROOT)
r12_security = validate_r12_dependency_security(ROOT)
r12_sbom = validate_r12_sbom(ROOT)
r12_license_asset_inventory = validate_r12_license_and_asset_inventories(ROOT)
ci_workflow_definition = validate_ci_workflow_definition(ROOT)
browser_accessibility_reflow = validate_browser_accessibility_reflow(ROOT)
r9_frontend_candidate = validate_r9_frontend_candidate(ROOT)
local_worktree_reproducibility = validate_local_worktree_reproducibility(ROOT)
tracked_missing = source_completeness["tracked_missing"]
tracked_invalid = source_completeness["tracked_invalid"]
untracked_required = source_completeness["untracked_required"]
excluded_tracked_source_paths = sorted(rel for rel in tracked if is_excluded_source_path(rel))
excluded_tracked_artifact_paths = sorted(rel for rel in tracked if is_excluded_artifact_path(rel))
missing = sorted(set(tracked_missing + tracked_invalid + untracked_required))
build_evidence_path = ROOT / "artifacts/BUILD_REPRODUCIBILITY_20261103.json"
build_reproducible = False
build_evidence_note = "two-clean-clone byte-identity evidence is absent"
if build_evidence_path.is_file():
    try:
        build_evidence = json.loads(build_evidence_path.read_text())
        expected_manifest = build_evidence.get("source_manifest", {})
        current_manifest = {}
        for rel in run_git("ls-files").splitlines():
            if rel == "artifacts/BUILD_REPRODUCIBILITY_20261103.json":
                continue
            file_path = ROOT / rel
            if file_path.is_file():
                current_manifest[rel] = hashlib.sha256(file_path.read_bytes()).hexdigest()
        tested_commit = build_evidence.get("tested_commit", "")
        tested_commit_manifest = None
        tested_commit_archive_sha256 = commit_source_archive_sha256(tested_commit)
        if isinstance(expected_manifest, dict) and is_ancestor(tested_commit):
            try:
                tested_commit_manifest = commit_source_manifest(tested_commit)
            except Exception:
                tested_commit_manifest = None
        build_reproducible = (
            build_evidence.get("schema") == "ganesha-build-reproducibility.v1"
            and build_evidence.get("two_clean_clone_builds_byte_identical") is True
            and build_evidence.get("toolchain") == EXPECTED_BUILD_TOOLCHAIN
            and re.fullmatch(r"[0-9a-f]{64}", str(build_evidence.get("wheel_sha256", ""))) is not None
            and re.fullmatch(r"[0-9a-f]{64}", str(build_evidence.get("sdist_sha256", ""))) is not None
            and re.fullmatch(r"[0-9a-f]{64}", str(build_evidence.get("sbom_sha256", ""))) is not None
            and build_evidence.get("clean_clone_test_status") == "PASS"
            and type(build_evidence.get("clean_clone_test_count")) is int
            and build_evidence.get("clean_clone_test_count", 0) > 0
            and build_evidence.get("clean_clone_count") == 2
            and build_evidence.get("source_manifest_entries") == len(expected_manifest)
            and all(build_evidence.get(field) == build_evidence.get("tested_commit")
                    for field in ("clean_clone_test_commit", "source_manifest_commit"))
            and all(build_evidence.get("clean_clone_test_results", {}).get(clone, {}).get("status") == "PASS"
                    and build_evidence.get("clean_clone_test_results", {}).get(clone, {}).get("tests") == build_evidence.get("clean_clone_test_count")
                    for clone in ("clone_a", "clone_b"))
            and re.fullmatch(r"[0-9a-f]{64}", str(build_evidence.get("git_archive_sha256", ""))) is not None
            and build_evidence.get("git_archive_sha256") == tested_commit_archive_sha256
            and all(re.fullmatch(r"[0-9a-f]{40}", str(build_evidence.get(field, ""))) is not None
                    for field in ("tested_commit", "clean_clone_test_commit", "source_manifest_commit"))
            and all(is_ancestor(build_evidence.get(field, ""))
                    for field in ("tested_commit", "clean_clone_test_commit", "source_manifest_commit"))
            and expected_manifest == current_manifest
            and tested_commit_manifest is not None
            and expected_manifest == tested_commit_manifest
        )
        build_evidence_note = "two-clean-clone package hashes, clean-clone test result, commit identifiers and source-file SHA-256 manifest match" if build_reproducible else "build evidence missing, malformed, incomplete, or no longer matches tracked source"
    except Exception as exc:
        build_evidence_note = "unable to validate build evidence: %s" % type(exc).__name__
checks = {
    "source_complete_and_tracked": {
        "pass": not missing,
        "evidence": "filesystem presence and Git tracking are independently classified; no untracked required path is treated as absent",
        "missing": missing,
        "tracked_missing": tracked_missing,
        "tracked_invalid": tracked_invalid,
        "untracked_required": untracked_required,
        "filesystem_present": not (tracked_missing or tracked_invalid),
        "tracking_complete": not untracked_required,
        "excluded_tracked_source_paths": excluded_tracked_source_paths,
        "excluded_tracked_artifact_paths": excluded_tracked_artifact_paths,
        "counts": {
            "tracked_missing": len(tracked_missing),
            "tracked_invalid": len(tracked_invalid),
            "untracked_required": len(untracked_required),
        },
    },
    "source_path_classification_integrity": path_classification,
    "project_license": {"pass": (ROOT / "LICENSE").is_file(), "evidence": "LICENSE file and owner-selected terms required"},
    "asset_redistribution_rights": {"pass": assets_cleared, "evidence": asset_rights_note},
    "license_and_asset_inventory_integrity": r12_license_asset_inventory,
    "historical_qa_evidence_integrity": historical_qa_evidence,
    "generated_frontend_snapshot_integrity": {"pass": frontend_snapshots_cleared, "evidence": frontend_snapshots_note},
    "offline_frontend_preview_integrity": offline_frontend_preview,
    "sbom_completeness": r12_sbom,
    "security_dependency_scan": r12_security,
    "build_reproducibility": {"pass": build_reproducible, "evidence": build_evidence_note},
    "ci_workflow_definition": ci_workflow_definition,
    "local_accessibility_reflow": browser_accessibility_reflow,
    "r9_frontend_candidate_integrity": r9_frontend_candidate,
    "local_worktree_reproducibility": local_worktree_reproducibility,
    "signed_release_manifest_and_sbom": {"pass": False, "evidence": "SBOM/release manifest/signature/trusted owner key are not all present and verified"},
    "ci_workflow": {"pass": False, "evidence": "workflow definition may be committed, but a current successful hosted run and verified provenance evidence are required"},
    "security_contact_and_public_terms": {"pass": False, "evidence": "responsible operator, security contact and public terms are not identified"},
    "hosted_privacy_and_operations": {"pass": False, "evidence": "current privacy/security docs are local-preview scope only; no hosted controller, retention or ops proof"},
    "accessibility_and_physical_devices": {"pass": False, "evidence": "full WCAG 2.2 AA and physical-device acceptance remain unverified"},
    "canonical_math_and_provider_approval": {"pass": False, "evidence": "original raw Math, canonical generator/inputs/Golden Vectors and Provider Math approval unavailable"},
    "production_rgs_wallet_contract": {"pass": False, "evidence": "local reference only; production Provider event/ledger/idempotency contract not verified"},
    "stake_studio_approval_and_activation": {"pass": False, "evidence": "canonical Game ID, upload receipt, iframe and game-specific approval/activation unverified"},
    "real_money_legal_and_rg_controls": {"pass": False, "evidence": "jurisdiction, operator, age, self-exclusion, limits and compliance controls not approved"},
}

workflow_exists = any((ROOT / p).is_file() for p in (".github/workflows/ci.yml", ".github/workflows/ci.yaml"))
ci_evidence_path = ROOT / "dist/CI_EVIDENCE.json"
if workflow_exists and ci_evidence_path.is_file():
    try:
        ci_evidence = json.loads(ci_evidence_path.read_text())
        step_outcomes = ci_evidence.get("step_outcomes", {})
        manifest_rel = ci_evidence.get("release_manifest_path", "")
        manifest_candidate = (ROOT / manifest_rel).resolve()
        repository = ci_evidence.get("repository", "")
        run_id = ci_evidence.get("run_id", "")
        run_attempt = ci_evidence.get("run_attempt", "")
        expected_repository = os.environ.get("GANESHA_GITHUB_REPOSITORY", "")
        expected_workflow_ref = expected_repository + "/.github/workflows/ci.yml@refs/heads/main"
        manifest_data = json.loads(manifest_candidate.read_text()) if ROOT in manifest_candidate.parents and manifest_candidate.is_file() else {}
        source_inventory_valid, _ = verify_manifest_source_inventory(
            ROOT, run_git("rev-parse", "HEAD"), manifest_data.get("source_files")
        )
        evidence_shape_valid = (
            ci_evidence.get("schema") == "ganesha-ci-evidence.v1"
            and ci_evidence.get("source_commit") == run_git("rev-parse", "HEAD")
            and isinstance(run_id, str) and run_id.isdigit()
            and isinstance(run_attempt, str) and run_attempt.isdigit()
            and expected_repository != "" and repository == expected_repository
            and ci_evidence.get("workflow") == "Full Scratch CI"
            and ci_evidence.get("workflow_ref") == expected_workflow_ref
            and ci_evidence.get("event_name") in ("push", "workflow_dispatch")
            and ci_evidence.get("ref") == "refs/heads/main"
            and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is not None
            and ci_evidence.get("run_url") == "https://github.com/%s/actions/runs/%s" % (repository, run_id)
            and ROOT in manifest_candidate.parents and manifest_candidate.is_file()
            and manifest_data.get("schema") == "ganesha-release-manifest.v1"
            and manifest_data.get("source_commit") == run_git("rev-parse", "HEAD")
            and manifest_data.get("source_tree") == run_git("rev-parse", "HEAD^{tree}")
            and source_inventory_valid
            and any("sbom" in path.lower() for path in manifest_data.get("artifacts", {}))
            and all(step_outcomes.get(name) == "success" for name in ("tests", "package", "sbom", "manifest"))
            and ci_evidence.get("manifest_attestation_verification") == "VERIFIED_BY_GITHUB"
        )
        if evidence_shape_valid and shutil.which("gh"):
            manifest_attestation = subprocess.run(["gh", "attestation", "verify", str(manifest_candidate), "--repo", repository],
                                                  cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ci_attestation = subprocess.run(["gh", "attestation", "verify", str(ci_evidence_path), "--repo", repository],
                                            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            checks["ci_workflow"]["pass"] = manifest_attestation.returncode == 0 and ci_attestation.returncode == 0
        else:
            checks["ci_workflow"]["pass"] = False
    except Exception:
        checks["ci_workflow"]["pass"] = False
if workflow_exists and not checks["ci_workflow"]["pass"]:
    checks["ci_workflow"]["evidence"] = "requires an exact-HEAD successful main-branch run, verified GitHub attestations, and out-of-band GANESHA_GITHUB_REPOSITORY"

current_dist = ROOT / "dist" / run_git("rev-parse", "--short", "HEAD")
sbom_candidates = [current_dist / "sbom.cdx.json"] if (current_dist / "sbom.cdx.json").is_file() else []
manifest_candidates = [current_dist / "RELEASE_MANIFEST.json"] if (current_dist / "RELEASE_MANIFEST.json").is_file() else []
signature_candidates = [current_dist / "RELEASE_MANIFEST.sig"] if (current_dist / "RELEASE_MANIFEST.sig").is_file() else []
public_key_candidates = [current_dist / "release-signing-public.pem"] if (current_dist / "release-signing-public.pem").is_file() else []
fingerprint = os.environ.get("RELEASE_TRUSTED_KEY_SHA256", "")
if (len(sbom_candidates) == len(manifest_candidates) == len(signature_candidates) == len(public_key_candidates) == 1
        and re.fullmatch(r"[0-9a-f]{64}", fingerprint)):
    try:
        verified = subprocess.run([
            sys.executable, str(ROOT / "tools/verify_release_manifest.py"),
            "--manifest", str(manifest_candidates[0]), "--signature", str(signature_candidates[0]),
            "--public-key", str(public_key_candidates[0]), "--trusted-key-sha256", fingerprint,
        ], cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        checks["signed_release_manifest_and_sbom"]["pass"] = verified.returncode == 0
    except Exception:
        checks["signed_release_manifest_and_sbom"]["pass"] = False
elif not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
    checks["signed_release_manifest_and_sbom"]["evidence"] = "an independently approved RELEASE_TRUSTED_KEY_SHA256 environment trust anchor and a unique signed release bundle are required"
tracks = {
    "public_source_repository": ["source_complete_and_tracked", "source_path_classification_integrity", "project_license", "asset_redistribution_rights", "license_and_asset_inventory_integrity", "sbom_completeness", "security_dependency_scan", "local_worktree_reproducibility", "build_reproducibility", "signed_release_manifest_and_sbom", "ci_workflow_definition", "ci_workflow", "security_contact_and_public_terms"],
    "hosted_non_wagering_preview": ["source_complete_and_tracked", "source_path_classification_integrity", "project_license", "asset_redistribution_rights", "license_and_asset_inventory_integrity", "sbom_completeness", "security_dependency_scan", "r9_frontend_candidate_integrity", "offline_frontend_preview_integrity", "local_accessibility_reflow", "local_worktree_reproducibility", "generated_frontend_snapshot_integrity", "hosted_privacy_and_operations", "accessibility_and_physical_devices", "security_contact_and_public_terms"],
    "stake_engine_real_money_release": ["canonical_math_and_provider_approval", "production_rgs_wallet_contract", "stake_studio_approval_and_activation", "real_money_legal_and_rg_controls", "accessibility_and_physical_devices", "local_accessibility_reflow", "r9_frontend_candidate_integrity", "project_license", "asset_redistribution_rights", "sbom_completeness", "security_dependency_scan", "signed_release_manifest_and_sbom", "ci_workflow"],
}
result = {
    "schema": "ganesha-publication-gate.v1",
    "project": "Ganesha and The Magic — Full Scratch V1",
    "status": "BLOCKED",
    "git_head": run_git("rev-parse", "HEAD"),
    "tracks": {},
    "checks": checks,
    "scope_note": "The static non-wagering preview is an internal engineering artifact. No public distribution, hosting, Stake submission or real-money use is authorized by this gate report.",
}
for track, keys in tracks.items():
    blockers = [key for key in keys if not checks[key]["pass"]]
    result["tracks"][track] = {"status": "PASS" if not blockers else "BLOCKED", "blockers": blockers}
print(json.dumps(result, indent=2))
if any(item["status"] != "PASS" for item in result["tracks"].values()):
    sys.exit(2)
