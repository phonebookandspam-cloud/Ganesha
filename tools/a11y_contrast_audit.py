#!/usr/bin/env python3
"""Small explicit WCAG 2.x contrast-pair check; not a complete WCAG audit."""
PAIRS = (
    ("body text", "#f2e9d4", "#071c20"),
    ("muted text", "#8ba5a0", "#071c20"),
    ("mint focus", "#69c7ae", "#071c20"),
    ("gold accent", "#d7bb78", "#071c20"),
    ("symbol label", "#9fb4a9", "#102d32"),
    ("fine print", "#a0b5ae", "#0c292d"),
    ("disabled spin label", "#d9d0b7", "#314443"),
    ("buy label", "#c8b47e", "#12383a"),
)


def _luminance(color):
    values = [int(color[index:index + 2], 16) / 255.0 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in values]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground, background):
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def audit():
    return [{"name": name, "foreground": foreground, "background": background,
             "ratio": round(contrast_ratio(foreground, background), 2),
             "pass_aa_normal_text": contrast_ratio(foreground, background) >= 4.5}
            for name, foreground, background in PAIRS]


if __name__ == "__main__":
    results = audit()
    for result in results:
        print("{name}: {ratio}:1 {status}".format(status="PASS" if result["pass_aa_normal_text"] else "FAIL", **result))
    raise SystemExit(0 if all(item["pass_aa_normal_text"] for item in results) else 1)
