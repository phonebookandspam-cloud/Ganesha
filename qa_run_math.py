import argparse
import json
from ganesha.math.simulation import run_monte_carlo
from ganesha.math.artifact_writers import write_monte_carlo_report

parser = argparse.ArgumentParser(description="Fail-closed draft Math Monte Carlo audit; no unapproved mode assumptions are sampled.")
parser.add_argument('--output', default='artifacts/monte_carlo_v1_draft_only.json')
args = parser.parse_args()
report = run_monte_carlo()
path = write_monte_carlo_report(report, args.output)
print(json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=2))
