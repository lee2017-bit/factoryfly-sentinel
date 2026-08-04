from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def read_poses(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    with path.open(
        encoding="utf-8-sig",
        newline="",
    ) as file:
        for row in csv.DictReader(file):
            try:
                rows.append(
                    {
                        "image_id": int(row["image_id"]),
                        "camera_id": int(row["camera_id"]),
                        "name": row["name"].replace("\\", "/"),
                        "frame_number": (
                            int(row["frame_number"])
                            if row.get("frame_number")
                            not in {
                                None,
                                "",
                            }
                            else None
                        ),
                        "camera_x": float(row["camera_x"]),
                        "camera_y": float(row["camera_y"]),
                        "camera_z": float(row["camera_z"]),
                        "forward_x": float(row["forward_x"]),
                        "forward_y": float(row["forward_y"]),
                        "forward_z": float(row["forward_z"]),
                    }
                )
            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

    return rows


def distance(
    left: dict[str, Any],
    right: dict[str, Any],
) -> float:
    return math.sqrt(
        (
            left["camera_x"]
            - right["camera_x"]
        )
        ** 2
        + (
            left["camera_y"]
            - right["camera_y"]
        )
        ** 2
        + (
            left["camera_z"]
            - right["camera_z"]
        )
        ** 2
    )


def viewing_angle(
    left: dict[str, Any],
    right: dict[str, Any],
) -> float:
    dot = (
        left["forward_x"]
        * right["forward_x"]
        + left["forward_y"]
        * right["forward_y"]
        + left["forward_z"]
        * right["forward_z"]
    )
    dot = max(
        -1.0,
        min(
            1.0,
            dot,
        ),
    )
    return math.degrees(
        math.acos(dot)
    )


def median_baseline_step(
    baseline_poses: list[dict[str, Any]],
) -> float:
    nearest_distances: list[float] = []

    for index, pose in enumerate(
        baseline_poses
    ):
        nearest = min(
            (
                distance(
                    pose,
                    other,
                )
                for other_index, other in enumerate(
                    baseline_poses
                )
                if other_index != index
            ),
            default=0.0,
        )

        if nearest > 0:
            nearest_distances.append(
                nearest
            )

    if not nearest_distances:
        return 1.0

    value = statistics.median(
        nearest_distances
    )
    return max(
        float(value),
        1e-9,
    )


def main() -> None:
    if len(sys.argv) != 6:
        raise RuntimeError(
            "Usage: generate_pose_candidates.py "
            "<baseline_poses.csv> <inspection_poses.csv> "
            "<output.csv> <top_k> <summary.json>"
        )

    baseline_pose_path = Path(
        sys.argv[1]
    ).resolve()
    inspection_pose_path = Path(
        sys.argv[2]
    ).resolve()
    output_path = Path(
        sys.argv[3]
    ).resolve()
    top_k = int(
        sys.argv[4]
    )
    summary_path = Path(
        sys.argv[5]
    ).resolve()

    if top_k < 1:
        raise RuntimeError(
            "top_k must be at least 1"
        )

    baseline_poses = read_poses(
        baseline_pose_path
    )
    inspection_poses = read_poses(
        inspection_pose_path
    )

    if not baseline_poses:
        raise RuntimeError(
            "No baseline poses were read."
        )

    if not inspection_poses:
        raise RuntimeError(
            "No inspection poses were read."
        )

    step = median_baseline_step(
        baseline_poses
    )
    rows: list[dict[str, Any]] = []

    for inspection_pose in inspection_poses:
        candidates: list[dict[str, Any]] = []

        for baseline_pose in baseline_poses:
            pose_distance = distance(
                inspection_pose,
                baseline_pose,
            )
            angle = viewing_angle(
                inspection_pose,
                baseline_pose,
            )
            distance_steps = (
                pose_distance
                / step
            )

            # Pose retrieval is only a candidate generator.
            # Geometric refinement performs the final selection.
            pose_score = (
                distance_steps
                + angle / 30.0
            )

            candidates.append(
                {
                    "inspection_image_id": inspection_pose[
                        "image_id"
                    ],
                    "inspection_name": inspection_pose[
                        "name"
                    ],
                    "inspection_frame_number": inspection_pose[
                        "frame_number"
                    ],
                    "baseline_image_id": baseline_pose[
                        "image_id"
                    ],
                    "baseline_name": baseline_pose[
                        "name"
                    ],
                    "pose_distance": pose_distance,
                    "pose_distance_steps": distance_steps,
                    "view_angle_degrees": angle,
                    "pose_score": pose_score,
                }
            )

        candidates.sort(
            key=lambda row: (
                row["pose_score"],
                row["pose_distance"],
                row["view_angle_degrees"],
            )
        )

        selected = candidates[
            : min(
                top_k,
                len(candidates),
            )
        ]

        for rank, row in enumerate(
            selected,
            start=1,
        ):
            output_row = dict(row)
            output_row["candidate_rank"] = rank
            rows.append(
                output_row
            )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    summary_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fieldnames = [
        "inspection_image_id",
        "inspection_name",
        "inspection_frame_number",
        "baseline_image_id",
        "baseline_name",
        "candidate_rank",
        "pose_distance",
        "pose_distance_steps",
        "view_angle_degrees",
        "pose_score",
    ]

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "status": "ready",
        "completed_at": now_iso(),
        "baseline_pose_count": len(
            baseline_poses
        ),
        "inspection_pose_count": len(
            inspection_poses
        ),
        "top_k": top_k,
        "candidate_count": len(rows),
        "median_baseline_step": step,
        "output_csv": str(
            output_path
        ),
    }
    summary_path.write_text(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        "[PASS] POSE CANDIDATE GENERATION COMPLETED"
    )
    print(
        f"Baseline poses      : {len(baseline_poses)}"
    )
    print(
        f"Inspection poses    : {len(inspection_poses)}"
    )
    print(
        f"Top K               : {top_k}"
    )
    print(
        f"Candidate pairs     : {len(rows)}"
    )
    print(
        f"Median baseline step: {step:.6f}"
    )
    print(
        f"Output              : {output_path}"
    )


if __name__ == "__main__":
    main()
