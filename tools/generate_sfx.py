"""Generate original deterministic Ganesha preview sound effects (no samples or third-party music)."""
import math
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RATE = 44100

SOUNDS = {
    "reel-stop.wav": {
        "duration": 0.16,
        "notes": [(0.0, 165.0, 0.15, 0.055), (0.0, 660.0, 0.07, 0.035)],
    },
    "wild-expansion.wav": {
        "duration": 0.78,
        "notes": [(0.00, 392.0, 0.12, 0.28), (0.12, 494.0, 0.12, 0.28),
                  (0.24, 587.0, 0.12, 0.28), (0.36, 784.0, 0.12, 0.32),
                  (0.48, 988.0, 0.10, 0.30)],
    },
    "free-spins.wav": {
        "duration": 0.92,
        "notes": [(0.00, 523.25, 0.10, 0.34), (0.13, 659.25, 0.10, 0.34),
                  (0.26, 783.99, 0.10, 0.38), (0.39, 1046.50, 0.10, 0.42),
                  (0.52, 1318.51, 0.08, 0.34)],
    },
    "win.wav": {
        "duration": 0.72,
        "notes": [(0.00, 659.25, 0.10, 0.30), (0.14, 783.99, 0.10, 0.32),
                  (0.28, 987.77, 0.10, 0.35), (0.42, 1318.51, 0.08, 0.28)],
    },
}


def synthesize(spec):
    count = round(spec["duration"] * RATE)
    samples = []
    for index in range(count):
        t = index / RATE
        value = 0.0
        for start, frequency, amplitude, decay in spec["notes"]:
            local = t - start
            if local < 0:
                continue
            attack = min(1.0, local / 0.006)
            envelope = attack * math.exp(-local / decay)
            fundamental = math.sin(2 * math.pi * frequency * local)
            overtone = 0.22 * math.sin(2 * math.pi * frequency * 2.01 * local)
            value += amplitude * envelope * (fundamental + overtone)
        samples.append(value)
    peak = max((abs(value) for value in samples), default=1.0) or 1.0
    scale = min(1.0, 0.82 / peak)
    pcm = bytearray()
    for value in samples:
        clipped = max(-1.0, min(1.0, value * scale))
        pcm.extend(struct.pack("<h", round(clipped * 32767)))
    return bytes(pcm)


def write_all():
    directory = ROOT / "frontend/assets/sfx"
    directory.mkdir(parents=True, exist_ok=True)
    for name, spec in SOUNDS.items():
        path = directory / name
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(RATE)
            wav.writeframes(synthesize(spec))
        print(path.relative_to(ROOT), path.stat().st_size)


if __name__ == "__main__":
    write_all()
