from __future__ import annotations

import csv
import json
import math
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_manual_frames(value: str) -> set[int]:
    frames: set[int] = set()

    for token in value.replace(
        ";",
        ",",
    ).split(","):
        token = token.strip()

        if not token:
            continue

        frames.add(
            int(token)
        )

    return frames


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(
        encoding="utf-8-sig",
        newline="",
    ) as file:
        return list(
            csv.DictReader(file)
        )


def numeric(
    row: dict[str, str],
    key: str,
    default: float = 0.0,
) -> float:
    try:
        return float(
            row.get(
                key,
                default,
            )
            or default
        )
    except (TypeError, ValueError):
        return default


def full_resolution_homography(
    row: dict[str, str],
) -> np.ndarray | None:
    values: list[list[float]] = []

    for matrix_row in range(3):
        current: list[float] = []

        for matrix_column in range(3):
            value = row.get(
                f"h{matrix_row}{matrix_column}",
                "",
            )

            if value == "":
                return None

            current.append(
                float(value)
            )

        values.append(
            current
        )

    feature_h = np.array(
        values,
        dtype=np.float64,
    )
    baseline_scale = numeric(
        row,
        "baseline_scale",
        1.0,
    )
    inspection_scale = numeric(
        row,
        "inspection_scale",
        1.0,
    )

    if (
        baseline_scale <= 0
        or inspection_scale <= 0
    ):
        return None

    baseline_scale_matrix = np.array(
        [
            [
                baseline_scale,
                0.0,
                0.0,
            ],
            [
                0.0,
                baseline_scale,
                0.0,
            ],
            [
                0.0,
                0.0,
                1.0,
            ],
        ],
        dtype=np.float64,
    )
    inspection_inverse_scale = np.array(
        [
            [
                1.0
                / inspection_scale,
                0.0,
                0.0,
            ],
            [
                0.0,
                1.0
                / inspection_scale,
                0.0,
            ],
            [
                0.0,
                0.0,
                1.0,
            ],
        ],
        dtype=np.float64,
    )

    return (
        inspection_inverse_scale
        @ feature_h
        @ baseline_scale_matrix
    )


def resolve_source(
    row: dict[str, str],
    explicit_key: str,
    root: Path,
    name_key: str,
) -> Path:
    explicit = Path(
        row.get(
            explicit_key,
            "",
        )
    )

    if explicit.is_file():
        return explicit.resolve()

    name = row.get(
        name_key,
        "",
    ).replace(
        "\\",
        "/",
    )
    candidates = [
        root / name,
        root / Path(
            name
        ).name,
    ]

    if name.startswith(
        "inspection/"
    ):
        candidates.append(
            root
            / name.split(
                "/",
                1,
            )[1]
        )

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise FileNotFoundError(
        f"Image not found for {name_key}: {name}"
    )


def main() -> None:
    if len(sys.argv) != 10:
        raise RuntimeError(
            "Usage: prepare_amd_package.py "
            "<refined_pairs.csv> <baseline_frames> <inspection_frames> "
            "<package_dir> <package_zip> <manual_frames> "
            "<remote_script> <inspection_id> <baseline_id>"
        )

    refined_pairs_path = Path(
        sys.argv[1]
    ).resolve()
    baseline_root = Path(
        sys.argv[2]
    ).resolve()
    inspection_root = Path(
        sys.argv[3]
    ).resolve()
    package_dir = Path(
        sys.argv[4]
    ).resolve()
    package_zip = Path(
        sys.argv[5]
    ).resolve()
    manual_frames = parse_manual_frames(
        sys.argv[6]
    )
    remote_script = Path(
        sys.argv[7]
    ).resolve()
    inspection_id = sys.argv[8]
    baseline_id = sys.argv[9]

    rows = read_rows(
        refined_pairs_path
    )

    if package_dir.exists():
        shutil.rmtree(
            package_dir
        )

    if package_zip.exists():
        package_zip.unlink()

    pair_root = package_dir / "pairs"
    pair_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    selected: list[
        tuple[
            dict[str, str],
            str,
        ]
    ] = []

    for row in rows:
        frame_number = int(
            numeric(
                row,
                "inspection_frame_number",
                -1,
            )
        )
        quality = row.get(
            "quality",
            "poor",
        )

        if quality in {
            "excellent",
            "good",
            "usable",
        }:
            selected.append(
                (
                    row,
                    "automatic_geometry_ready",
                )
            )
        elif frame_number in manual_frames:
            selected.append(
                (
                    row,
                    "manual_borderline_review",
                )
            )

    manifest_rows: list[
        dict[str, Any]
    ] = []
    automatic_count = 0
    manual_count = 0
    skipped_manual: list[int] = []

    for row, selection_reason in selected:
        frame_number = int(
            numeric(
                row,
                "inspection_frame_number",
                -1,
            )
        )
        homography = full_resolution_homography(
            row
        )

        if homography is None:
            if selection_reason == "manual_borderline_review":
                skipped_manual.append(
                    frame_number
                )
            continue

        baseline_source = resolve_source(
            row,
            "baseline_path",
            baseline_root,
            "baseline_name",
        )
        inspection_source = resolve_source(
            row,
            "inspection_path",
            inspection_root,
            "inspection_name",
        )
        pair_id = (
            f"frame_{frame_number:06d}"
        )
        pair_dir = pair_root / pair_id
        pair_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        baseline_target = (
            pair_dir
            / "baseline.jpg"
        )
        inspection_target = (
            pair_dir
            / "inspection.jpg"
        )
        shutil.copy2(
            baseline_source,
            baseline_target,
        )
        shutil.copy2(
            inspection_source,
            inspection_target,
        )

        output_row: dict[str, Any] = {
            "pair_id": pair_id,
            "inspection_frame_number": frame_number,
            "selection_reason": selection_reason,
            "quality": row.get(
                "quality"
            ),
            "baseline_name": row.get(
                "baseline_name"
            ),
            "inspection_name": row.get(
                "inspection_name"
            ),
            "baseline_file": (
                baseline_target
                .relative_to(
                    package_dir
                )
                .as_posix()
            ),
            "inspection_file": (
                inspection_target
                .relative_to(
                    package_dir
                )
                .as_posix()
            ),
            "mutual_matches": row.get(
                "mutual_matches"
            ),
            "fundamental_inlier_ratio": row.get(
                "fundamental_inlier_ratio"
            ),
            "homography_inlier_ratio": row.get(
                "homography_inlier_ratio"
            ),
            "overlap_ratio": row.get(
                "overlap_ratio"
            ),
            "median_reprojection_error": row.get(
                "median_reprojection_error"
            ),
            "refinement_score": row.get(
                "refinement_score"
            ),
        }

        for matrix_row in range(3):
            for matrix_column in range(3):
                output_row[
                    f"h{matrix_row}{matrix_column}"
                ] = float(
                    homography[
                        matrix_row,
                        matrix_column,
                    ]
                )

        manifest_rows.append(
            output_row
        )

        if selection_reason == "automatic_geometry_ready":
            automatic_count += 1
        else:
            manual_count += 1

    if not manifest_rows:
        raise RuntimeError(
            "No valid pairs were selected for AMD analysis."
        )

    manifest_path = package_dir / "manifest.csv"
    fieldnames = list(
        manifest_rows[0].keys()
    )

    with manifest_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as manifest_file:
        writer = csv.DictWriter(
            manifest_file,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(
            manifest_rows
        )

    shutil.copy2(
        remote_script,
        package_dir
        / "run_amd_dino_analysis.py",
    )

    package_summary = {
        "status": "ready",
        "completed_at": now_iso(),
        "inspection_id": inspection_id,
        "baseline_id": baseline_id,
        "selected_pairs": len(
            manifest_rows
        ),
        "automatic_pairs": automatic_count,
        "manual_pairs": manual_count,
        "requested_manual_frames": sorted(
            manual_frames
        ),
        "skipped_manual_frames": sorted(
            skipped_manual
        ),
        "manifest": str(
            manifest_path
        ),
        "package_zip": str(
            package_zip
        ),
        "privacy_note": (
            "The package contains only selected RGB image pairs, "
            "homographies, and geometric metrics. It excludes telemetry, "
            "GPS, home location, device serial numbers, and private keys."
        ),
    }
    summary_path = (
        package_dir
        / "package_summary.json"
    )
    summary_path.write_text(
        json.dumps(
            package_summary,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    package_zip.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with zipfile.ZipFile(
        package_zip,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for source in sorted(
            package_dir.rglob(
                "*"
            )
        ):
            if source.is_file():
                archive.write(
                    source,
                    source.relative_to(
                        package_dir
                    ).as_posix(),
                )

    print(
        "[PASS] AMD PACKAGE PREPARED"
    )
    print(
        f"Selected pairs      : {len(manifest_rows)}"
    )
    print(
        f"Automatic pairs     : {automatic_count}"
    )
    print(
        f"Manual pairs        : {manual_count}"
    )
    print(
        f"Skipped manual      : {sorted(skipped_manual)}"
    )
    print(
        f"Archive             : {package_zip}"
    )


if __name__ == "__main__":
    main()
