"""Compare stored Draft-005 outputs descriptively; never a release or tail-risk proof."""
import json
import math
from pathlib import Path
from ganesha.math.artifact_writers import write_crosscheck_report

exact = json.loads(Path('artifacts/math_audit_v1_draft_only.json').read_text())
mc = json.loads(Path('artifacts/monte_carlo_v1_draft_only.json').read_text())
probability_keys = {
    'BASE': exact['BASE']['50k_jackpot_probability'],
    'MAGIC_BUY': exact['MAGIC_BUY']['jackpot_probability_50k'],
    'EPIC_BUY': exact['EPIC_BUY']['jackpot_probability_50k'],
}
comparison = {
    'schema': 'ganesha-math-crosscheck.v1',
    'exact_config_version': exact['config_version'],
    'monte_carlo_seed': mc['seed'],
    'modes': {},
}
for mode in ('BASE', 'MAGIC_BUY', 'EPIC_BUY'):
    observed = mc['modes'][mode]
    p_jackpot = probability_keys[mode]
    rounds = observed['rounds']
    expected_jackpots = p_jackpot * rounds
    comparison['modes'][mode] = {
        'draft_exact_rtp_percent': exact[mode]['rtp_percent'],
        'draft_observed_rtp_percent': observed['observed_rtp_percent'],
        'descriptive_difference_percentage_points': observed['observed_rtp_percent'] - exact[mode]['rtp_percent'],
        'sample_sd_normal_interval_diagnostic_only_percent': observed['rtp_95pct_normal_ci_percent'],
        'interval_is_valid_for_rare_tail_certification': False,
        'divine_jackpot_probability_per_round_exact_under_draft': p_jackpot,
        'total_50000x_payout_probability': 'NOT_COMPUTED; accumulated-cap paths are not included in jackpot probability',
        'monte_carlo_rounds': rounds,
        'expected_divine_jackpot_observations': expected_jackpots,
        'probability_zero_divine_jackpots_poisson': math.exp(-expected_jackpots),
        'observed_divine_jackpot_count': observed['max_win_observed_count'],
        'empirical_upper_0_1pct_cvar_sample_only': observed['upper_0_1pct_cvar_x_of_purchase_cost'],
        'exact_standard_deviation_base_wager_x_under_draft': exact[mode].get('standard_deviation_base_wager_x'),
        'observed_sample_standard_deviation_base_wager_x': observed['standard_deviation_x_of_base_wager'],
    }
comparison['limitations'] = [
    'This is a comparison of two calculations that share evaluate_board(); it is not an independent evaluator.',
    'The stored Monte Carlo sample observed zero 50,000x jackpots; the expected jackpot counts are below one in each mode.',
    'Sample SD-based normal intervals and empirical CVaR do not capture an unobserved rare jackpot mass.',
    'The reported probability is the Divine Jackpot event only, not total probability of reaching the 50,000x round cap.',
    'All values are hypothetical Draft-005 research and conflict with user-authoritative Math rules; no public product claim is permitted.',
]
output_path = write_crosscheck_report(comparison)
print(json.dumps(json.loads(output_path.read_text(encoding='utf-8')), indent=2))
