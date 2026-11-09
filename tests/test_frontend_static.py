import hashlib
import json
import unittest
from html.parser import HTMLParser
from pathlib import Path
from tools.a11y_contrast_audit import audit

ROOT = Path(__file__).resolve().parents[1]


class FrontendParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.buttons = []
        self.local_refs = []
        self.ids = set()
        self.elements = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
            self.elements[attrs["id"]] = attrs
        if tag == "button":
            self.buttons.append(attrs)
        ref = attrs.get("src") if tag in ("img", "script") else attrs.get("href") if tag == "link" else None
        if ref and ref.startswith("./"):
            self.local_refs.append(ref[2:])


class FrontendStaticTests(unittest.TestCase):
    def test_preview_is_non_wagering_and_all_controls_fail_closed(self):
        html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        parser = FrontendParser()
        parser.feed(html)
        self.assertEqual(len(parser.buttons), 11)
        self.assertTrue(all("disabled" in button for button in parser.buttons if button.get("id") != "sound-toggle"))
        sound_button = next(button for button in parser.buttons if button.get("id") == "sound-toggle")
        self.assertNotIn("disabled", sound_button)
        self.assertIn("message", parser.ids)
        self.assertIn("connection-label", parser.ids)
        self.assertIn("engine-fixture-button", parser.ids)
        self.assertIn("fixture-readback", parser.ids)
        self.assertIn("runtime-button", parser.ids)
        self.assertIn("runtime-readback", parser.ids)
        self.assertIn("stake-reconnect-button", parser.ids)
        self.assertIn("sound-toggle", parser.ids)
        self.assertIn("PLAY ENGINE FIXTURE", html)
        self.assertIn("RUN INDEPENDENT RUNTIME", html)
        self.assertIn('aria-label="Run fixed non-financial demo spin"', html)
        self.assertIn("FIXED BOARD · NO WAGER", html)
        self.assertIn("3 Scatter awards 10 Free Spins", html)
        self.assertIn("4 Scatter awards 12 Free Spins", html)
        self.assertIn("Provider-authoritative payload and BASE payout-unit conversion are unavailable", html)
        self.assertIn("6+ Scatter and retriggers", html)
        self.assertIn("not a playable wagering product", html)
        app_script = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
        presentation_contract = (ROOT / "frontend/presentation-contract.js").read_text(encoding="utf-8")
        self.assertIn("WILD_GANESHA:", app_script)
        self.assertIn("deriveExpandedWildDisplayBoard", app_script)
        self.assertIn("WILD_GANESHA", presentation_contract)
        self.assertIn("MAGIC BUY", html)
        self.assertIn("EPIC BUY", html)
        self.assertIn("×100 · LOCKED", html)
        self.assertIn("×500 · LOCKED", html)
        self.assertIn("Both purchases remain disabled pending canonical Math and Provider approval", html)

    def test_accessibility_basics_are_present(self):
        html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        css = (ROOT / "frontend/style.css").read_text(encoding="utf-8")
        parser = FrontendParser()
        parser.feed(html)
        self.assertIn('<html lang="en">', html)
        self.assertIn('name="viewport"', html)
        self.assertIn('class="skip-link"', html)
        self.assertIn('id="game-preview" aria-label="Non-wagering game art preview" tabindex="-1"', html)
        self.assertIn(':focus-visible', css)
        self.assertIn('prefers-reduced-motion:reduce', css)
        self.assertIn('aria-live="polite"', html)
        self.assertEqual(parser.elements["connection-label"].get("role"), "status")
        self.assertEqual(parser.elements["connection-label"].get("aria-live"), "polite")
        self.assertEqual(parser.elements["round-status"].get("role"), "status")
        self.assertEqual(parser.elements["round-status"].get("aria-live"), "polite")
        self.assertEqual(parser.elements["round-status"].get("aria-atomic"), "true")
        self.assertNotIn("aria-live", parser.elements["stake-session-panel"])
        self.assertEqual(parser.elements["stake-session-status"].get("role"), "status")
        self.assertEqual(parser.elements["stake-session-status"].get("aria-live"), "polite")
        self.assertEqual(parser.elements["stake-session-status"].get("aria-atomic"), "true")
        self.assertIn('env(safe-area-inset-top)', css)

    def test_offline_vite_build_aliases_config_module_and_verifier_rejects_dev_endpoint(self):
        vite = (ROOT / "vite.config.js").read_text(encoding="utf-8")
        verifier = (ROOT / "tools/verify_frontend_build.mjs").read_text(encoding="utf-8")
        self.assertIn("find: './config.js'", vite)
        self.assertIn("path.resolve(workspaceRoot, configPath)", vite)
        self.assertIn("offline config was not resolved into the JavaScript module graph", verifier)
        self.assertIn("127.0.0.1:8795", verifier)

    def test_structural_stage_and_bet_console_hierarchy_is_fail_closed(self):
        html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        layout = (ROOT / "frontend/layout-v2.css").read_text(encoding="utf-8")
        script = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
        self.assertIn('href="./layout-v2.css"', html)
        for marker in (
            'id="stage-title"', 'id="control-title"', 'class="symbol-legend"',
            'class="account-readout"', 'class="readout-cell"', 'class="control-lock"',
            'tier-wild', 'tier-scatter', 'tier-high', 'tier-low',
        ):
            self.assertIn(marker, html)
        self.assertIn('WALLET BALANCE', html)
        self.assertIn('NOT CONNECTED', html)
        self.assertIn('Bet configuration disabled', html)
        self.assertIn('Both purchases remain disabled pending canonical Math and Provider approval', html)
        self.assertIn("definition[3]", script)
        self.assertIn("definition[4]", script)
        self.assertIn("appendSymbolArtwork(cell, definition, symbols[row])", script)
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr))", layout)
        self.assertIn("@media (max-width: 560px)", layout)
        self.assertIn("@media (orientation: landscape) and (max-height: 560px)", layout)
        self.assertIn("@media (prefers-reduced-motion: reduce)", layout)
        self.assertIn("button:disabled", layout)

    def test_feature_animation_cues_are_bound_to_verified_events_and_respect_reduced_motion(self):
        script = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
        css = (ROOT / "frontend/style.css").read_text(encoding="utf-8")
        self.assertIn("animateExpandedReels(event.payload.reels)", script)
        self.assertIn("replayCue(runtimeStatus, 'feature-start-reveal')", script)
        self.assertIn("replayCue(runtimeStatus, 'multiplier-reveal')", script)
        self.assertIn("replayCue(runtimePayout, 'payout-reveal')", script)
        self.assertIn("replayCue(fixturePayout, 'payout-reveal')", script)
        for cue in ("wild-expansion-reveal", "feature-start-reveal", "event-pulse", "multiplier-reveal", "payout-reveal"):
            self.assertIn(cue, css)
        self.assertIn("@media(prefers-reduced-motion:reduce){.symbol.wild-expansion-reveal", css)

    def test_selected_frontend_text_contrast_pairs_meet_wcag_aa_threshold(self):
        css = (ROOT / "frontend/style.css").read_text(encoding="utf-8")
        results = audit()
        self.assertEqual(len(results), 8)
        self.assertTrue(all(item["pass_aa_normal_text"] for item in results), results)
        for item in results:
            self.assertIn(item["foreground"], css)
            self.assertIn(item["background"], css)

    def test_read_only_round_renderer_requires_host_proxy_and_never_accepts_browser_credentials(self):
        script = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
        self.assertIn("window.GaneshaRoundState = Object.freeze({ connect })", script)
        self.assertIn("contract !== 'ganesha.game.events'", script)
        self.assertIn("typeof readbackProvider !== 'function'", script)
        self.assertIn("await readbackProvider({ roundId })", script)
        self.assertNotIn("Authorization:", script)
        self.assertNotIn("sessionToken", script)
        self.assertIn("HMAC secret must remain server-side", script)
        self.assertNotRegex(script, r"\b(?:window\.)?localStorage\s*\.")
        self.assertIn("ganesha.runtime.pending.v1:", script)
        self.assertIn("window.sessionStorage.setItem(runtimePendingStorageKey", script)
        self.assertIn("window.sessionStorage.getItem(runtimePendingStorageKey", script)
        self.assertNotRegex(script, r"sessionStorage\.(?:getItem|setItem)\(['\"](?:token|secret|auth|sessionToken)")
        self.assertIn("disableAllWagerControls()", script)
        self.assertNotIn("button.disabled = false", script)
        self.assertIn("event.round_id !== roundId", script)
        self.assertIn("event.schema_version !== 1", script)
        self.assertIn("renderRoundReadback(snapshot, roundId)", script)
        self.assertIn("authenticated-server-event-empty", script)
        self.assertIn("committed, not settled", script)
        self.assertIn('id="round-readback"', (ROOT / "frontend/index.html").read_text(encoding="utf-8"))

    def test_financial_round_restore_requires_host_bridge_and_verifies_redacted_hash_projection(self):
        script = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
        html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        self.assertIn("window.GaneshaRoundRecovery = Object.freeze({ restore: restoreExistingRound })", script)
        self.assertIn("window.GaneshaHost", script)
        self.assertIn("host.readRound({ roundId: id })", script)
        self.assertIn("host.recoverRound({ roundId })", script)
        self.assertIn("persisted round event hash verification failed", script)
        self.assertIn("round state head hash does not match", script)
        self.assertIn("a valid existing round ID is required before host recovery is requested", script)
        self.assertIn("!['BET_RESERVED', 'OUTCOME_COMMITTED', 'SETTLED', 'REFUNDED'].includes(snapshot.status)", script)
        self.assertIn("inFlightRoundReads", script)
        self.assertIn('id="restore-round-button"', html)
        self.assertIn('id="recover-round-button"', html)
        self.assertIn("No browser secret is accepted", html)
        self.assertNotRegex(script, r"\b(?:window\.)?localStorage\s*\.")
        restore_section = script.split("const restoreExistingRound", 1)[1].split("window.GaneshaRoundState", 1)[0]
        self.assertNotRegex(restore_section, r"\b(?:window\.)?sessionStorage\s*\.")

    def test_engine_fixture_frontend_verifies_hash_chain_and_never_uses_financial_api(self):
        script = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
        html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        fixture = (ROOT / "src/ganesha/demo/game_fixture.py").read_text(encoding="utf-8")
        self.assertIn("verifyPresentationEvents", script)
        self.assertIn("crypto.subtle.digest('SHA-256'", script)
        self.assertIn("event.previous_hash !== previousHash", script)
        self.assertIn("event.event_hash !== eventHash", script)
        self.assertIn("sourceLabel + ' for round '", script)
        self.assertIn("financial_effects !== false", script)
        self.assertIn("deriveExpandedWildDisplayBoard(rawBoard, wildReels)", script)
        self.assertIn("engineFixtureButton.disabled = true", script)
        self.assertIn("demoButton.disabled = true", script)
        self.assertIn("TEST_FIXTURE_ONLY", script)
        self.assertIn("/api/demo/game-sessions/", script)
        self.assertNotIn("/api/v1/rounds", script)
        self.assertNotIn("WalletLedger", fixture)
        self.assertNotIn("RoundService", fixture)
        self.assertIn("RNG, canonical Math, Wallet, debit, credit", fixture)
        self.assertIn('id="fixture-readback"', html)

    def test_independent_runtime_frontend_verifies_committed_projection_and_is_nonfinancial(self):
        script = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
        html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
        self.assertIn("verifyRuntimeResponse", script)
        self.assertIn("runtime lifecycle Event Contract is missing or incomplete", script)
        self.assertIn("SIMULATION_OUTCOME_COMMITTED", script)
        self.assertIn("NON_FINANCIAL_SIMULATION", script)
        self.assertIn("/api/runtime/sessions", script)
        self.assertIn("runtime replay projection differs from the committed engine outcome", script)
        self.assertIn("runtimeApiAvailable", script)
        self.assertIn('id="runtime-readback"', html)
        self.assertIn("deterministic development-only MathPort", html)

    def test_all_local_frontend_assets_exist_and_match_manifest(self):
        parser = FrontendParser()
        parser.feed((ROOT / "frontend/index.html").read_text(encoding="utf-8"))
        for relative in parser.local_refs:
            if relative == "config.js":  # generated at runtime by the local dev server
                continue
            self.assertTrue((ROOT / "frontend" / relative).is_file(), relative)
        manifest = json.loads((ROOT / "frontend/assets/ASSET_PROVENANCE.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "INTERNAL_PREVIEW_ONLY_RIGHTS_UNVERIFIED")
        for item in manifest["assets"]:
            data = (ROOT / "frontend/assets" / item["file"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"], item["file"])
            if item["file"].startswith("sfx/"):
                self.assertIn("Original project-generated audio", item["redistribution_rights"])
                self.assertIn("Project authorship", item["rights_holder"])
                self.assertIn("Project license not yet selected", item["license"])
                self.assertIn("reproducible", item["modification_permission"])
                self.assertIn("Pending project-level license", item["redistribution_permission"])
                self.assertIn("tools/generate_sfx.py", item["rights_evidence_ref"])
            elif item["file"].endswith("_v15.svg"):
                self.assertIn("Original vector artwork authored directly", item["creator"])
                self.assertIn("public redistribution remains blocked", item["redistribution_rights"])
                self.assertIn("Project license not yet selected", item["license"])
                self.assertIn("Pending project-level license", item["redistribution_permission"])
            else:
                self.assertEqual(item["redistribution_rights"], "not established; public redistribution blocked pending rights confirmation")
                self.assertEqual(item["rights_holder"], "not established in current evidence")
                self.assertEqual(item["license"], "not established in current evidence")
                self.assertEqual(item["modification_permission"], "not established")
                self.assertEqual(item["redistribution_permission"], "not established")
                self.assertEqual(item["rights_evidence_ref"], "not established in current evidence")


if __name__ == "__main__":
    unittest.main()
