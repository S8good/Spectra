#!/usr/bin/env python3
"""
Generate a Phase 1 schema-compliant demo database for the Database Explorer UI.

The dataset covers:
  * two example projects
  * a completed batch run with linked batch items and spectra
  * an in-progress batch run demonstrating partially collected wells
  * a standalone calibration experiment outside of batch capture

All spectra are written through DatabaseManager.save_spectrum so that the
structured tables (spectrum_sets / spectrum_data) remain in sync with the
legacy tables.
"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from nanosense.core.database_manager import DatabaseManager

WAVELENGTHS = [round(500.0 + i * 0.5, 2) for i in range(10)]


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def build_intensities(base: float, step: float = 0.02, count: int = 10) -> List[float]:
    return [round(base + step * i, 4) for i in range(count)]


def save_well_spectra(
    db: DatabaseManager,
    experiment_id: int,
    batch_item_id: int,
    base_time: datetime,
    spectra: Iterable[Tuple[str, float]],
    *,
    instrument_info: Dict[str, object],
    processing_info: Dict[str, object],
) -> int:
    capture_count = 0

    for offset, (label, baseline) in enumerate(spectra):
        timestamp = iso(base_time + timedelta(minutes=offset * 2))
        intensities = build_intensities(baseline)
        db.save_spectrum(
            experiment_id,
            label,
            timestamp,
            WAVELENGTHS,
            intensities,
            batch_run_item_id=batch_item_id,
            instrument_info=instrument_info,
            processing_info=processing_info,
        )
        if label.lower().startswith("signal"):
            capture_count += 1

    return capture_count


def seed_batch_run(
    db: DatabaseManager,
    project_id: int,
    name: str,
    operator: str,
    start_time: datetime,
    layout: Dict[str, Dict[str, object]],
    completed_wells: Iterable[str],
    review_wells: Iterable[str] = (),
) -> None:
    run_id = db.create_batch_run(
        project_id,
        name,
        layout_reference=json.dumps({"wells": sorted(layout.keys())}, ensure_ascii=False),
        operator=operator,
        notes=f"Demo batch run generated on {iso(datetime.now())}",
    )
    if not run_id:
        raise RuntimeError(f"Failed to create batch run '{name}'")

    item_map = db.create_batch_items(run_id, layout)

    instrument_defaults = {
        "device_serial": "INS-001",
        "integration_time_ms": 120.0,
        "averaging": 16,
        "temperature": 25.0,
        "config": {"source": "demo_generator"},
    }
    processing_defaults = {
        "name": "batch_acquisition",
        "version": "1.0",
        "parameters": {"source": "demo_generator", "points_per_well": 3},
    }

    review_targets = set(review_wells)

    for index, (well_id, metadata) in enumerate(layout.items(), start=1):
        item_id = item_map.get(well_id)
        if not item_id:
            continue

        experiment_time = start_time + timedelta(minutes=15 * index)
        exp_notes = f"Auto-generated batch experiment for {well_id}"
        config_snapshot = json.dumps(
            {"well": well_id, "layout_meta": metadata},
            ensure_ascii=False,
        )

        experiment_id = db.create_experiment(
            project_id,
            f"{name}::{well_id}",
            "Batch Measurement",
            iso(experiment_time),
            operator=operator,
            notes=exp_notes,
            config_snapshot=config_snapshot,
        )
        if not experiment_id:
            continue

        db.attach_experiment_to_batch_item(item_id, experiment_id)

        instrument_info = dict(instrument_defaults)
        instrument_info["integration_time_ms"] = 100.0 + index * 10.0

        processing_info = dict(processing_defaults)
        processing_info["parameters"] = dict(processing_defaults["parameters"])
        processing_info["parameters"]["well"] = well_id

        spectra_plan: List[Tuple[str, float]] = [
            ("Background", 0.15),
            ("Reference", 1.05),
            ("Signal_Point_1", 0.82),
        ]

        if well_id in completed_wells:
            spectra_plan.append(("Result_Point_1", 0.48))

        captures = save_well_spectra(
            db,
            experiment_id,
            item_id,
            experiment_time,
            spectra_plan,
            instrument_info=instrument_info,
            processing_info=processing_info,
        )

        status = "completed" if well_id in completed_wells else "in_progress"
        db.update_batch_item_progress(
            item_id,
            capture_count=captures,
            status=status,
        )
    final_status = "completed" if set(completed_wells) == set(layout.keys()) else "in_progress"
    db.update_batch_run(run_id, status=final_status)


def seed_calibration_experiment(db: DatabaseManager, project_id: int) -> None:
    exp_id = db.create_experiment(
        project_id,
        "Calibration Day 1",
        "Calibration",
        iso(datetime(2025, 9, 20, 8, 30)),
        operator="bob",
        notes="Standalone calibration run for demo data",
        config_snapshot=json.dumps({"mode": "calibration", "source": "demo_generator"}),
    )
    if not exp_id:
        return

    db.save_spectrum(
        exp_id,
        "Calibration_Spectrum",
        iso(datetime(2025, 9, 20, 8, 45)),
        WAVELENGTHS,
        build_intensities(0.65),
        instrument_info={
            "device_serial": "INS-002",
            "integration_time_ms": 90.0,
            "temperature": 24.5,
            "config": {"source": "demo_generator", "mode": "calibration"},
        },
        processing_info={
            "name": "calibration",
            "version": "1.2",
            "parameters": {"fit": "linear"},
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a demo SQLite database for the Database Explorer UI.",
    )
    parser.add_argument(
        "--output",
        default="data/demo_database.db",
        help="Path to the demo database file (default: data/demo_database.db).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing database file if present.",
    )
    args = parser.parse_args()

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        if not args.force:
            raise SystemExit(f"File already exists: {output_path}. Use --force to overwrite.")
        output_path.unlink()

    manager = DatabaseManager(str(output_path))
    try:
        screening_project = manager.find_or_create_project("Protein Screening", "Demo screening dataset")
        calibration_project = manager.find_or_create_project("Sensor Calibration", "Demo calibration dataset")

        if screening_project is None or calibration_project is None:
            raise RuntimeError("Failed to create demo projects.")

        seed_batch_run(
            manager,
            screening_project,
            name="Plate 0905",
            operator="alice",
            start_time=datetime(2025, 9, 5, 9, 0),
            layout={
                "A1": {"sample": "Analyte A1", "position": "A1"},
                "A2": {"sample": "Analyte A2", "position": "A2"},
                "B1": {"sample": "Control Blank", "position": "B1"},
            },
            completed_wells={"A1", "A2"},
            review_wells={"A2"},
        )

        seed_batch_run(
            manager,
            screening_project,
            name="Plate 0907",
            operator="alice",
            start_time=datetime(2025, 9, 7, 10, 30),
            layout={
                "A1": {"sample": "Analyte B1", "position": "A1"},
                "A2": {"sample": "Analyte B2", "position": "A2"},
            },
            completed_wells={"A1"},
            review_wells={"A2"},
        )

        seed_calibration_experiment(manager, calibration_project)

    finally:
        manager.close()

    print(f"Demo database generated at: {output_path}")


if __name__ == "__main__":
    main()
