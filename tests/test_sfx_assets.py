import hashlib
import importlib.util
import json
import wave
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('ganesha_sfx_generator', ROOT / 'tools/generate_sfx.py')
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


class SoundAssetTests(unittest.TestCase):
    def test_original_sfx_are_valid_reproducible_pcm_wav_files(self):
        provenance = json.loads((ROOT / 'frontend/assets/ASSET_PROVENANCE.json').read_text())
        records = {item['file']: item for item in provenance['assets']}
        for filename, spec in GENERATOR.SOUNDS.items():
            with self.subTest(filename=filename):
                path = ROOT / 'frontend/assets/sfx' / filename
                raw = path.read_bytes()
                self.assertEqual(raw[:4], b'RIFF')
                self.assertEqual(hashlib.sha256(raw).hexdigest(), records['sfx/' + filename]['sha256'])
                self.assertEqual(len(raw), records['sfx/' + filename]['bytes'])
                with wave.open(str(path), 'rb') as wav:
                    self.assertEqual(wav.getnchannels(), 1)
                    self.assertEqual(wav.getsampwidth(), 2)
                    self.assertEqual(wav.getframerate(), GENERATOR.RATE)
                    self.assertGreater(wav.getnframes(), 1000)
                    self.assertAlmostEqual(wav.getnframes() / wav.getframerate(), spec['duration'], places=3)
                    self.assertEqual(wav.readframes(wav.getnframes()), GENERATOR.synthesize(spec))

    def test_frontend_has_accessible_opt_in_sound_control_and_event_hooks(self):
        html = (ROOT / 'frontend/index.html').read_text()
        js = (ROOT / 'frontend/app.js').read_text()
        self.assertIn('id="sound-toggle"', html)
        self.assertIn('aria-pressed="false"', html)
        self.assertIn("soundEnabled = !soundEnabled", js)
        for name in ('reelStop', 'wildExpansion', 'freeSpins', 'win'):
            self.assertIn("playSfx('%s')" % name, js)

    def test_runtime_and_engine_fixture_bind_sound_to_the_matching_events(self):
        js = (ROOT / 'frontend/app.js').read_text()
        runtime = js.split('const renderRuntimeResult = async', 1)[1].split('const readRuntimeSnapshot =', 1)[0]
        fixture = js.split('const playEngineFixture = async', 1)[1].split('const readFixtureSnapshot =', 1)[0]
        for name, event in (
            ('reelStop', 'BASE_REEL_STOPPED'),
            ('freeSpins', 'FEATURE_STARTED'),
            ('wildExpansion', 'WILD_EXPANSION_APPLIED'),
            ('win', 'BASE_OUTCOME_REVEALED'),
        ):
            with self.subTest(handler='runtime', sound=name, event=event):
                branch = runtime.split("event.event_type === '%s'" % event, 1)[1].split('} else if', 1)[0]
                self.assertIn("playSfx('%s')" % name, branch)
            with self.subTest(handler='fixture', sound=name, event=event):
                branch = fixture.split("event.event_type === '%s'" % event, 1)[1].split('} else if', 1)[0]
                self.assertIn("playSfx('%s')" % name, branch)
        for handler_name, handler in (('runtime', runtime), ('fixture', fixture)):
            with self.subTest(handler=handler_name, sound='win', event='FEATURE_SPIN_RESOLVED'):
                branch = handler.split("event.event_type === 'FEATURE_SPIN_RESOLVED'", 1)[1].split('} else if', 1)[0]
                self.assertIn("if (event.payload.payout_awarded_milli > 0) playSfx('win')", branch)

    def test_each_sfx_event_uses_an_independent_player_without_aborting_previous_playback(self):
        js = (ROOT / 'frontend/app.js').read_text()
        play_sfx = js.split('const playSfx = (name) => {', 1)[1].split('\n  };', 1)[0]
        self.assertIn('const soundPlayers = new Set()', js)
        self.assertIn('const player = new Audio(soundSources[name])', play_sfx)
        self.assertIn('document.body.append(player)', play_sfx)
        self.assertIn("player.addEventListener('ended', release, { once: true })", play_sfx)
        self.assertNotIn('player.pause()', play_sfx)
        self.assertIn('for (const player of soundPlayers) {', js)
        self.assertIn('player.pause();', js)
        self.assertIn('soundPlayers.clear();', js)


if __name__ == '__main__':
    unittest.main()
