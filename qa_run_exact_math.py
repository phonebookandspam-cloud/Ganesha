import argparse
import json
from ganesha.math.round_ev import exact_full_mode_moments
from ganesha.math.artifact_writers import write_exact_report

parser = argparse.ArgumentParser(description="Fail-closed exact full-round Math audit; unresolved feature rules block metrics.")
parser.add_argument('--output', default='artifacts/math_audit_v1_draft_only.json')
args = parser.parse_args()
report = exact_full_mode_moments()
path = write_exact_report(report, args.output)
print(json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=2))
