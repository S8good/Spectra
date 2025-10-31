#!/usr/bin/env python3
"""
Utility script for importing spectra files into the nanosense database.

The script supports both single-spectrum files (two columns: wavelength, value)
and wide-format files containing multiple spectra columns. It creates (or
reuses) a project/experiment entry and writes the spectra using
DatabaseManager.save_spectrum so that the structured tables (spectrum_sets /
spectrum_data) stay in sync with the legacy tables.
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from nanosense.core.database_manager import DatabaseManager
from nanosense.utils.file_io import load_spectra_from_path, load_spectrum_from_path


DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".nanosense", "nanosense_data.db")


def _normalise_spec_label(label: str, fallback_prefix: str, index: int) -> str:
    """
    Convert an arbitrary column/file name into a safe spectrum label.
    """
    cleaned = "".join(ch if ch.isalnum() or ch in ("_", "-", ".") else "_" for ch in label.strip())
    cleaned = cleaned.strip("_")
    if not cleaned:
        cleaned = f"{fallback_prefix}_{index}"
    return cleaned


def _load_multi_column_file(path: str) -> List[Tuple[List[float], List[float], str]]:
    """
    Return a list of (wavelengths, intensities, label) tuples for a wide-format file.
    """
    spectra_entries = []
    spectra_list = load_spectra_from_path(path, mode="file")
    for idx, entry in enumerate(spectra_list, start=1):
        wavelengths = entry.get("x")
        intensities = entry.get("y")
        label = entry.get("name", f"Column_{idx}")
        if wavelengths is None or intensities is None:
            continue
        spectra_entries.append((list(map(float, wavelengths)), list(map(float, intensities)), label))
    return spectra_entries


def _load_single_file(path: str) -> Tuple[List[float], List[float]]:
    """
    Load a single-spectrum file (two columns).
    """
    x_data, y_data = load_spectrum_from_path(path)
    if x_data is None or y_data is None:
        return [], []
    return list(map(float, x_data)), list(map(float, y_data))


def import_file(
    db: DatabaseManager,
    source_path: str,
    project_name: str,
    experiment_name: str,
    experiment_type: str,
    operator: str,
    notes: str,
    timestamp: str,
    default_label: str,
    project_description: str = "",
    experiment_id: int = None,
    instrument_info: Optional[Dict[str, Any]] = None,
    processing_info: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Import the given file into the database. Returns the experiment_id used.
    """
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source path does not exist: {source_path}")

    project_id = db.find_or_create_project(project_name, project_description or "")
    if project_id is None:
        raise RuntimeError("Unable to create or locate the project entry.")

    exp_id = experiment_id
    if exp_id is None:
        exp_id = db.create_experiment(
            project_id,
            experiment_name,
            experiment_type,
            timestamp,
            operator=operator,
            notes=notes,
            config_snapshot=json.dumps({"source": os.path.abspath(source_path)}),
        )
        if exp_id is None:
            raise RuntimeError("Failed to create experiment entry.")

    # Determine whether the file contains multiple spectra
    entries: List[Tuple[List[float], List[float], str]] = []
    try:
        entries = _load_multi_column_file(source_path)
    except Exception:
        entries = []

    if not entries:
        wavelengths, intensities = _load_single_file(source_path)
        if not wavelengths or not intensities:
            raise RuntimeError("Could not parse spectra data from the provided file.")
        entries = [(wavelengths, intensities, default_label)]

    instrument_payload: Optional[Dict[str, Any]]
    if instrument_info:
        instrument_payload = {
            key: instrument_info.get(key)
            for key in ('device_serial', 'integration_time_ms', 'averaging', 'temperature')
            if instrument_info.get(key) is not None
        }
        extra_config = dict(instrument_info.get('config') or {})
        extra_config.setdefault('source', 'cli_import')
        extra_config.setdefault('source_file', os.path.abspath(source_path))
        if extra_config:
            instrument_payload['config'] = extra_config
        if not instrument_payload:
            instrument_payload = None
    else:
        instrument_payload = None

    base_processing = {
        'name': 'cli_import',
        'version': '1.0',
        'parameters': {}
    }
    if processing_info:
        if processing_info.get('name'):
            base_processing['name'] = processing_info['name']
        if processing_info.get('version'):
            base_processing['version'] = processing_info['version']
        if processing_info.get('parameters'):
            base_processing['parameters'].update(processing_info['parameters'])
    base_processing['parameters'].setdefault('source', 'cli_import')
    base_processing['parameters'].setdefault('source_file', os.path.abspath(source_path))
    base_processing['parameters']['spectra_count'] = len(entries)
    base_processing['parameters']['detected_labels'] = [raw_label for _, _, raw_label in entries]

    saved = 0
    for index, (wavelengths, intensities, raw_label) in enumerate(entries, start=1):
        label = _normalise_spec_label(raw_label, default_label, index)
        processing_payload = {
            'name': base_processing['name'],
            'version': base_processing['version'],
            'parameters': dict(base_processing['parameters']),
        }
        processing_payload['parameters']['spectrum_label'] = label
        result = db.save_spectrum(
            exp_id,
            label,
            timestamp,
            wavelengths,
            intensities,
            instrument_info=instrument_payload,
            processing_info=processing_payload,
        )
        if result:
            saved += 1

    if saved == 0:
        raise RuntimeError("No spectra were imported; see logs for details.")

    print(f"[import] Stored {saved} spectrum record(s) for experiment {exp_id}.")
    return exp_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import spectra data into the nanosense database (structured schema)."
    )
    parser.add_argument("source", help="Path to the spectra file to import (Excel/CSV/TXT).")
    parser.add_argument("--db", dest="db_path", default=DEFAULT_DB_PATH, help="Path to the SQLite database file.")
    parser.add_argument("--project", required=True, help="Target project name (will be created if missing).")
    parser.add_argument("--project-description", default="", help="Optional project description.")
    parser.add_argument("--experiment", required=True, help="Experiment name for the imported data.")
    parser.add_argument("--experiment-type", default="Imported", help="Experiment type label.")
    parser.add_argument("--operator", default="importer", help="Operator recorded for the experiment.")
    parser.add_argument("--notes", default="", help="Optional notes saved with the experiment.")
    parser.add_argument("--timestamp", default=None, help="Timestamp for the experiment (defaults to current time).")
    parser.add_argument(
        "--default-label",
        default="Result",
        help="Fallback spectrum label prefix when the data set does not expose column names.",
    )
    parser.add_argument(
        "--experiment-id",
        type=int,
        default=None,
        help="Existing experiment id to append data to (skips experiment creation).",
    )
    parser.add_argument("--device-serial", default=None, help="Instrument serial number to record in metadata.")
    parser.add_argument("--integration-time", type=float, default=None, help="Integration time in milliseconds.")
    parser.add_argument("--averaging", type=int, default=None, help="Number of scans averaged for the spectra.")
    parser.add_argument("--temperature", type=float, default=None, help="Instrument temperature in °C.")
    parser.add_argument(
        "--instrument-extra",
        default=None,
        help="JSON object with additional instrument configuration metadata.",
    )
    parser.add_argument("--processing-name", default=None, help="Processing snapshot name override.")
    parser.add_argument("--processing-version", default=None, help="Processing snapshot version override.")
    parser.add_argument(
        "--processing-params",
        default=None,
        help="JSON object containing processing parameters (e.g. smoothing, preprocessing).",
    )
    return parser


def main(argv: List[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    timestamp = args.timestamp or time.strftime("%Y-%m-%d %H:%M:%S")
    instrument_info: Optional[Dict[str, Any]] = {}
    if args.device_serial:
        instrument_info['device_serial'] = args.device_serial
    if args.integration_time is not None:
        instrument_info['integration_time_ms'] = float(args.integration_time)
    if args.averaging is not None:
        instrument_info['averaging'] = int(args.averaging)
    if args.temperature is not None:
        instrument_info['temperature'] = float(args.temperature)
    if args.instrument_extra:
        instrument_info['config'] = json.loads(args.instrument_extra)
    if not instrument_info:
        instrument_info = None

    processing_info: Optional[Dict[str, Any]] = {}
    if args.processing_name:
        processing_info['name'] = args.processing_name
    if args.processing_version:
        processing_info['version'] = args.processing_version
    if args.processing_params:
        processing_info['parameters'] = json.loads(args.processing_params)
    if not processing_info:
        processing_info = None

    db = DatabaseManager(args.db_path)
    try:
        import_file(
            db,
            args.source,
            args.project,
            args.experiment,
            args.experiment_type,
            args.operator,
            args.notes,
            timestamp,
            args.default_label,
            project_description=args.project_description,
            experiment_id=args.experiment_id,
            instrument_info=instrument_info,
            processing_info=processing_info,
        )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
