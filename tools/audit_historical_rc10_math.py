#!/usr/bin/env python3
"""Read-only semantic audit of the preserved RC10 Exact3 R8 Math ZIP."""
from __future__ import annotations
import argparse, collections, csv, hashlib, io, json, math, zipfile
from pathlib import Path, PurePosixPath
import zstandard

EXPECTED_ARCHIVE_SHA256 = "5a7aaa4c51955efedb60c70d92704861f4439c591c084c65b13c9b65ac43e94c"
EXPECTED_ENTRIES = {
    "library/publish_files/books_BASE.jsonl.zst",
    "library/publish_files/books_MAGICBUY_V36.jsonl.zst",
    "library/publish_files/books_EPICBUY_V37.jsonl.zst",
    "library/publish_files/index.json",
    "library/publish_files/lookUpTable_BASE_0.csv",
    "library/publish_files/lookUpTable_MAGICBUY_V36_0.csv",
    "library/publish_files/lookUpTable_EPICBUY_V37_0.csv",
}
EXPECTED_MODES = ("BASE", "MAGICBUY_V36", "EPICBUY_V37")


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def audit_archive(path):
    path = Path(path).resolve()
    report = {"schema": "ganesha-rc10-r8-historical-math-audit.v1", "status": "BLOCKED",
              "archive": {"path": str(path), "size_bytes": path.stat().st_size,
                          "owner_note": "Read-only historical reference; no archive entry is modified."},
              "entries": [], "index": {}, "modes": {}, "issues": [],
              "authority": {"canonical_source": False, "provider_approved": False,
                            "disposition": "HISTORICAL_VALIDATION_FIXTURE_ONLY_NOT_CANONICAL_MATH"}}
    actual_archive_hash = sha256_file(path)
    report["archive"]["sha256"] = actual_archive_hash
    if actual_archive_hash != EXPECTED_ARCHIVE_SHA256:
        report["issues"].append({"code": "ARCHIVE_SHA256_MISMATCH", "expected": EXPECTED_ARCHIVE_SHA256,
                                 "actual": actual_archive_hash})
        return report
    with zipfile.ZipFile(path) as archive:
        names = [item.filename for item in archive.infolist()]
        if len(names) != len(set(names)):
            report["issues"].append({"code": "DUPLICATE_ZIP_ENTRIES"})
        if set(names) != EXPECTED_ENTRIES:
            report["issues"].append({"code": "ARCHIVE_ENTRY_SET_MISMATCH",
                                     "missing": sorted(EXPECTED_ENTRIES - set(names)),
                                     "unexpected": sorted(set(names) - EXPECTED_ENTRIES)})
        bad_entry = archive.testzip()
        if bad_entry:
            report["issues"].append({"code": "ZIP_CRC_FAILURE", "entry": bad_entry})
        for info in archive.infolist():
            blob = archive.read(info.filename)
            report["entries"].append({"path": info.filename, "size_bytes": info.file_size,
                                      "compressed_size_bytes": info.compress_size,
                                      "sha256": hashlib.sha256(blob).hexdigest(), "crc": "PASS"})
        index_path = "library/publish_files/index.json"
        try:
            index = json.loads(archive.read(index_path).decode("utf-8"), object_pairs_hook=_unique_pairs)
        except Exception as exc:
            report["issues"].append({"code": "INDEX_INVALID", "detail": str(exc)})
            return report
        if not isinstance(index, dict) or set(index) != {"modes"} or not isinstance(index.get("modes"), list):
            report["issues"].append({"code": "INDEX_SCHEMA_INVALID"})
            return report
        names_in_index = [m.get("name") for m in index["modes"] if isinstance(m, dict)]
        report["index"] = {"path": index_path, "size_bytes": len(archive.read(index_path)),
                            "sha256": hashlib.sha256(archive.read(index_path)).hexdigest(),
                            "mode_names": names_in_index, "modes": index["modes"]}
        if tuple(names_in_index) != EXPECTED_MODES:
            report["issues"].append({"code": "INDEX_MODE_SET_OR_ORDER_UNEXPECTED",
                                     "expected": list(EXPECTED_MODES), "actual": names_in_index})
        for mode in index["modes"]:
            if not isinstance(mode, dict) or set(mode) != {"name", "cost", "events", "weights"}:
                report["issues"].append({"code": "INDEX_MODE_SCHEMA_INVALID", "mode": mode})
                continue
            name, cost, events_ref, weights_ref = mode["name"], mode["cost"], mode["events"], mode["weights"]
            if name not in EXPECTED_MODES:
                report["issues"].append({"code": "UNEXPECTED_MODE", "mode": name})
                continue
            for ref in (events_ref, weights_ref):
                rel = PurePosixPath(ref) if isinstance(ref, str) else None
                if rel is None or rel.is_absolute() or len(rel.parts) != 1 or ("library/publish_files/" + ref) not in names:
                    report["issues"].append({"code": "INDEX_REFERENCE_INVALID", "mode": name, "reference": ref})
            if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost <= 0:
                report["issues"].append({"code": "MODE_COST_INVALID", "mode": name, "cost": cost})
                continue
            mode_report = {"index_cost_multiplier_observed_not_approved": cost,
                           "books_path": "library/publish_files/" + events_ref,
                           "lut_path": "library/publish_files/" + weights_ref,
                           "book_records": 0, "lut_rows": 0, "event_count": 0,
                           "event_types": {}, "symbol_value_types": {}, "symbol_values": {},
                           "free_spin_start_spins": {}, "free_spin_trigger_scatter_counts": {},
                           "retrigger_event_count": 0, "event_index_errors": 0,
                           "board_shape_errors": 0, "books_lut_id_mismatch_count": 0,
                           "books_lut_payout_mismatch_count": 0, "invalid_lut_payout_increment_count": 0,
                           "final_win_unit_match": {"amount_equals_payoutMultiplier": 0,
                                                     "amount_times_100_equals_payoutMultiplier": 0,
                                                     "amount_other_or_missing": 0},
                           "base_plus_free_win_unit_mismatch_count": 0,
                           "weighted_total": 0, "weighted_payout_sum": 0}
            event_types = collections.Counter(); symbol_types = collections.Counter(); symbols = collections.Counter()
            fs_starts = collections.Counter(); trigger_scatters = collections.Counter()
            id_mismatch = payout_mismatch = increment_violations = event_index_errors = board_errors = 0
            final_units = collections.Counter(); aggregate_mismatch = 0; weighted_total = weighted_payout = 0
            book_ids_seen = set(); lut_ids_seen = set()
            with archive.open("library/publish_files/" + weights_ref) as csv_raw, archive.open("library/publish_files/" + events_ref) as books_raw:
                rows = csv.reader(io.TextIOWrapper(csv_raw, encoding="utf-8", newline=""))
                books = io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(books_raw), encoding="utf-8")
                sentinel = object()
                import itertools
                for row, line in itertools.zip_longest(rows, books, fillvalue=sentinel):
                    if row is sentinel or line is sentinel:
                        id_mismatch += 1
                        break
                    if len(row) != 3 or any(not cell.isdigit() for cell in row):
                        report["issues"].append({"code": "LUT_ROW_INVALID", "mode": name,
                                                 "row": mode_report["lut_rows"] + 1})
                        break
                    sid, weight, payout = map(int, row)
                    lut_ids_seen.add(sid)
                    mode_report["lut_rows"] += 1
                    weighted_total += weight
                    weighted_payout += weight * payout
                    if payout and payout % 10:
                        increment_violations += 1
                    try:
                        item = json.loads(line, object_pairs_hook=_unique_pairs)
                    except Exception:
                        report["issues"].append({"code": "BOOK_JSON_INVALID", "mode": name,
                                                 "line": mode_report["book_records"] + 1})
                        break
                    if not isinstance(item, dict) or not {"id", "events", "payoutMultiplier"}.issubset(item):
                        report["issues"].append({"code": "BOOK_SCHEMA_INVALID", "mode": name,
                                                 "line": mode_report["book_records"] + 1})
                        break
                    book_id = item["id"]; book_ids_seen.add(book_id)
                    mode_report["book_records"] += 1
                    if type(book_id) is not int or book_id != sid:
                        id_mismatch += 1
                    payout_multiplier = item["payoutMultiplier"]
                    if type(payout_multiplier) is not int or payout_multiplier != payout:
                        payout_mismatch += 1
                    ev = item["events"]
                    if not isinstance(ev, list) or not all(isinstance(e, dict) for e in ev):
                        report["issues"].append({"code": "BOOK_EVENTS_INVALID", "mode": name,
                                                 "id": book_id})
                        continue
                    mode_report["event_count"] += len(ev)
                    for event_index, event in enumerate(ev):
                        typ = event.get("type", "<missing>"); event_types[typ] += 1
                        if "index" in event and event["index"] != event_index:
                            event_index_errors += 1
                        if "board" in event:
                            board = event["board"]
                            if not (isinstance(board, list) and len(board) == 3 and
                                    all(isinstance(reel, list) and len(reel) == 5 for reel in board)):
                                board_errors += 1
                            elif typ == "reveal":
                                for reel in board:
                                    for symbol in reel:
                                        symbol_types[type(symbol).__name__] += 1
                                        symbols[str(symbol)] += 1
                        if typ == "freeSpinStart":
                            fs_starts[str(event.get("spins"))] += 1
                            trigger_scatters[str(event.get("triggerScatters"))] += 1
                        if typ == "retrigger":
                            mode_report["retrigger_event_count"] += 1
                    final_events = [e for e in ev if e.get("type") == "finalWin"]
                    if len(final_events) != 1 or not isinstance(final_events[0].get("amount"), (int, float)):
                        final_units["amount_other_or_missing"] += 1
                    else:
                        amount = final_events[0]["amount"]
                        if amount == payout_multiplier:
                            final_units["amount_equals_payoutMultiplier"] += 1
                        elif amount * 100 == payout_multiplier:
                            final_units["amount_times_100_equals_payoutMultiplier"] += 1
                        else:
                            final_units["amount_other_or_missing"] += 1
                    aggregate = item.get("baseGameWins", 0) + item.get("freeGameWins", 0)
                    if not isinstance(aggregate, (int, float)) or aggregate * 100 != payout_multiplier:
                        aggregate_mismatch += 1
            mode_report.update({"event_types": dict(event_types), "symbol_value_types": dict(symbol_types),
                                "symbol_values": dict(symbols), "free_spin_start_spins": dict(fs_starts),
                                "free_spin_trigger_scatter_counts": dict(trigger_scatters),
                                "event_index_errors": event_index_errors, "board_shape_errors": board_errors,
                                "books_lut_id_mismatch_count": id_mismatch,
                                "books_lut_payout_mismatch_count": payout_mismatch,
                                "invalid_lut_payout_increment_count": increment_violations,
                                "final_win_unit_match": dict(final_units),
                                "base_plus_free_win_unit_mismatch_count": aggregate_mismatch,
                                "weighted_total": weighted_total, "weighted_payout_sum": weighted_payout,
                                "weighted_mean_payout_multiplier_raw": weighted_payout / weighted_total if weighted_total else None,
                                "weighted_rtp_percent_under_index_cost_and_hundredths_unit_assumption":
                                    (weighted_payout / weighted_total) / float(cost) if weighted_total else None})
            if len(book_ids_seen) != mode_report["book_records"] or len(lut_ids_seen) != mode_report["lut_rows"]:
                report["issues"].append({"code": "DUPLICATE_BOOK_OR_LUT_ID", "mode": name})
            if mode_report["books_lut_id_mismatch_count"] or mode_report["books_lut_payout_mismatch_count"]:
                report["issues"].append({"code": "BOOKS_LUT_PARITY_FAILURE", "mode": name})
            if mode_report["event_index_errors"] or mode_report["board_shape_errors"]:
                report["issues"].append({"code": "EVENT_STRUCTURE_FAILURE", "mode": name})
            if increment_violations:
                report["issues"].append({"code": "SDK_PAYOUT_INCREMENT_RULE_VIOLATIONS", "mode": name,
                                         "count": increment_violations})
            report["modes"][name] = mode_report
    report["semantic_findings"] = [
        "Books/LUT ordered IDs and payoutMultiplier values are compared for every record; this proves package-internal parity only.",
        "The R8 BASE Books contain numeric symbol IDs while MAGICBUY/EPICBUY Books use string symbol names; the symbol-ID mapping is absent from this archive.",
        "The R8 BASE Books contain retrigger events although the current user-authority record leaves retrigger behavior unspecified.",
        "BASE finalWin amount uses mixed observed units within the same mode; Buy-mode finalWin amount uses raw payoutMultiplier units while baseGameWins/freeGameWins remain on a different scale.",
        "Historical index Buy costs and weighted means are observations, not approved purchase prices, canonical probabilities, or RTP certification.",
        "The archive does not contain the generator, complete input manifest, reel strips, probability models, paytable, paylines, RNG derivation, or Golden Vectors."
    ]
    parity_failures = any(item.get("code") in {"BOOKS_LUT_PARITY_FAILURE", "EVENT_STRUCTURE_FAILURE", "DUPLICATE_BOOK_OR_LUT_ID", "BOOK_JSON_INVALID", "BOOK_SCHEMA_INVALID", "BOOK_EVENTS_INVALID", "LUT_ROW_INVALID"} for item in report["issues"])
    report["status"] = "HISTORICAL_PARITY_PASS_BUT_SDK_CONTRACT_FAIL" if not parity_failures and report["issues"] else ("HISTORICAL_PARITY_PASS_WITH_SEMANTIC_BLOCKERS" if not report["issues"] else "HISTORICAL_PACKAGE_AUDIT_BLOCKED")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = audit_archive(args.archive)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        target = Path(args.output)
        if target.exists():
            raise SystemExit("refusing to overwrite existing audit output: " + str(target))
        target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    raise SystemExit(0 if result["status"] in {"HISTORICAL_PARITY_PASS_WITH_SEMANTIC_BLOCKERS", "HISTORICAL_PARITY_PASS_BUT_SDK_CONTRACT_FAIL"} else 2)


if __name__ == "__main__":
    main()
