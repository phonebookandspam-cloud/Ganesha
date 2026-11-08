SOURCE_DATE_EPOCH ?= $(shell git log -1 --format=%ct 2>/dev/null)
RELEASE_DIR ?= dist/$(shell git rev-parse --short HEAD 2>/dev/null)
PYTHON ?= python3

.PHONY: test serve package math-audit math-audit-draft source-completeness release-check sbom release-manifest sign-release-manifest verify-release-manifest

test:
	PYTHONPATH=src:$$PYTHONPATH $(PYTHON) -m unittest discover -s tests -v
	npm run test:frontend-rgs

# Fail closed: the current draft inputs are not canonical or approved.
math-audit:
	@echo "BLOCKED: canonical user Math source, approved probability inputs and Provider Golden Vectors are unavailable."
	@echo "Historical Draft-005 audit artifacts are superseded and must not be used for release claims."
	@exit 2

math-audit-draft:
	PYTHONPATH=src:$$PYTHONPATH $(PYTHON) qa_run_exact_math.py

# Required source inventory is checked in the clean CI checkout before packaging.
source-completeness:
	$(PYTHON) qa_source_completeness.py

package:
	test -n "$(SOURCE_DATE_EPOCH)" || (echo "SOURCE_DATE_EPOCH must be set or run from a Git checkout"; exit 2)
	mkdir -p "$(RELEASE_DIR)"
	SOURCE_DATE_EPOCH=$(SOURCE_DATE_EPOCH) $(PYTHON) -m build --outdir "$(RELEASE_DIR)"
	SOURCE_DATE_EPOCH=$(SOURCE_DATE_EPOCH) $(PYTHON) tools/normalize_sdist.py "$(RELEASE_DIR)"/*.tar.gz

sbom:
	mkdir -p "$(RELEASE_DIR)"
	$(PYTHON) tools/generate_sbom.py --output "$(RELEASE_DIR)/sbom.cdx.json"

release-manifest:
	$(PYTHON) tools/create_release_manifest.py --output "$(RELEASE_DIR)/RELEASE_MANIFEST.json" --artifact "$(RELEASE_DIR)/sbom.cdx.json" --artifact "$(RELEASE_DIR)"/*.whl --artifact "$(RELEASE_DIR)"/*.tar.gz

sign-release-manifest:
	test -n "$(RELEASE_SIGNING_PRIVATE_KEY)" || (echo "RELEASE_SIGNING_PRIVATE_KEY is required"; exit 2)
	test -n "$(RELEASE_SIGNING_PUBLIC_KEY)" || (echo "RELEASE_SIGNING_PUBLIC_KEY is required"; exit 2)
	$(PYTHON) tools/sign_release_manifest.py --manifest "$(RELEASE_DIR)/RELEASE_MANIFEST.json" --private-key "$(RELEASE_SIGNING_PRIVATE_KEY)" --public-key "$(RELEASE_SIGNING_PUBLIC_KEY)" --signature "$(RELEASE_DIR)/RELEASE_MANIFEST.sig"
	cp "$(RELEASE_SIGNING_PUBLIC_KEY)" "$(RELEASE_DIR)/release-signing-public.pem"

verify-release-manifest:
	test -n "$(RELEASE_TRUSTED_KEY_SHA256)" || (echo "RELEASE_TRUSTED_KEY_SHA256 trust anchor is required"; exit 2)
	$(PYTHON) tools/verify_release_manifest.py --manifest "$(RELEASE_DIR)/RELEASE_MANIFEST.json" --signature "$(RELEASE_DIR)/RELEASE_MANIFEST.sig" --public-key "$(RELEASE_DIR)/release-signing-public.pem" --trusted-key-sha256 "$(RELEASE_TRUSTED_KEY_SHA256)"

serve:
	PYTHONPATH=src:$$PYTHONPATH $(PYTHON) dev_server.py

release-check:
	$(PYTHON) qa_release_gate.py
