from __future__ import annotations

import csv
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def quaternion_to_rotation(
    qw: float,
    qx: float,
    qy: float,
    qz: float,
) -> list[list[float]]:
    return [
        [
            1 - 2 * (qy * qy + qz * qz),
            2 * (qx * qy - qz * qw),
            2 * (qx * qz + qy * qw),
        ],
        [
            2 * (qx * qy + qz * qw),
            1 - 2 * (qx * qx + qz * qz),
            2 * (qy * qz - qx * qw),
        ],
        [
            2 * (qx * qz - qy * qw),
            2 * (qy * qz + qx * qw),
            1 - 2 * (qx * qx + qy * qy),
        ],
    ]


def transpose(
    matrix: list[list[float]],
) -> list[list[float]]:
    return [
        [matrix[row][column] for row in range(3)]
        for column in range(3)
    ]


def mat_vec(
    matrix: list[list[float]],
    vector: list[float],
) -> list[float]:
    return [
        sum(
            matrix[row][column] * vector[column]
            for column in range(3)
        )
        for row in range(3)
    ]


def parse_frame_number(name: str) -> int | None:
    match = re.search(
        r"frame_(\d+)",
        name,
        flags=re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


def looks_like_image_name(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return Path(normalized).suffix.lower() in IMAGE_EXTENSIONS


def parse_colmap_images(
    images_txt: Path,
) -> list[dict[str, Any]]:
    poses: list[dict[str, Any]] = []

    for raw_line in images_txt.read_text(
        encoding="utf-8-sig",
        errors="replace",
    ).splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        tokens = line.split()
        if len(tokens) < 10:
            continue

        name = " ".join(tokens[9:])
        if not looks_like_image_name(name):
            continue

        try:
            image_id = int(tokens[0])
            qw, qx, qy, qz = map(
                float,
                tokens[1:5],
            )
            tx, ty, tz = map(
                float,
                tokens[5:8],
            )
            camera_id = int(tokens[8])
        except (TypeError, ValueError):
            continue

        rotation = quaternion_to_rotation(
            qw,
            qx,
            qy,
            qz,
        )
        rotation_transpose = transpose(
            rotation
        )
        camera_center = [
            -value
            for value in mat_vec(
                rotation_transpose,
                [tx, ty, tz],
            )
        ]

        # COLMAP camera looks along +Z in camera coordinates.
        forward = mat_vec(
            rotation_transpose,
            [0.0, 0.0, 1.0],
        )
        norm = math.sqrt(
            sum(value * value for value in forward)
        )
        if norm > 0:
            forward = [
                value / norm
                for value in forward
            ]

        poses.append(
            {
                "image_id": image_id,
                "camera_id": camera_id,
                "name": name.replace("\\", "/"),
                "frame_number": parse_frame_number(
                    name
                ),
                "qw": qw,
                "qx": qx,
                "qy": qy,
                "qz": qz,
                "tx": tx,
                "ty": ty,
                "tz": tz,
                "camera_x": camera_center[0],
                "camera_y": camera_center[1],
                "camera_z": camera_center[2],
                "forward_x": forward[0],
                "forward_y": forward[1],
                "forward_z": forward[2],
            }
        )

    return poses


def continuous_runs(
    frame_numbers: list[int],
) -> list[dict[str, int]]:
    if not frame_numbers:
        return []

    numbers = sorted(
        set(frame_numbers)
    )
    runs: list[dict[str, int]] = []
    start = numbers[0]
    previous = numbers[0]

    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue

        runs.append(
            {
                "start": start,
                "end": previous,
                "length": previous - start + 1,
            }
        )
        start = number
        previous = number

    runs.append(
        {
            "start": start,
            "end": previous,
            "length": previous - start + 1,
        }
    )
    return runs


def write_pose_csv(
    path: Path,
    poses: list[dict[str, Any]],
) -> None:
    fields = [
        "image_id",
        "camera_id",
        "name",
        "frame_number",
        "qw",
        "qx",
        "qy",
        "qz",
        "tx",
        "ty",
        "tz",
        "camera_x",
        "camera_y",
        "camera_z",
        "forward_x",
        "forward_y",
        "forward_z",
    ]

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=fields,
        )
        writer.writeheader()
        writer.writerows(poses)


def main() -> None:
    if len(sys.argv) != 9:
        raise RuntimeError(
            "Usage: analyze_colmap_registration.py "
            "<images.txt> <frames_dir> <output_dir> "
            "<inspection_id> <baseline_id> <database_path> "
            "<registered_model_path> <duration_seconds>"
        )

    images_txt = Path(sys.argv[1]).resolve()
    frames_dir = Path(sys.argv[2]).resolve()
    output_dir = Path(sys.argv[3]).resolve()
    inspection_id = sys.argv[4]
    baseline_id = sys.argv[5]
    database_path = Path(sys.argv[6]).resolve()
    registered_model_path = Path(
        sys.argv[7]
    ).resolve()
    duration_seconds = float(sys.argv[8])

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    all_poses = parse_colmap_images(
        images_txt
    )
    inspection_poses = sorted(
        [
            pose
            for pose in all_poses
            if pose["name"].startswith(
                "inspection/"
            )
        ],
        key=lambda pose: (
            pose["frame_number"]
            if pose["frame_number"] is not None
            else 10**9
        ),
    )
    baseline_poses = [
        pose
        for pose in all_poses
        if not pose["name"].startswith(
            "inspection/"
        )
    ]

    input_frames = sorted(
        [
            path
            for path in frames_dir.iterdir()
            if path.is_file()
            and path.suffix.lower()
            in IMAGE_EXTENSIONS
        ],
        key=lambda path: path.name,
    )

    expected_names = [
        f"inspection/{path.name}"
        for path in input_frames
    ]
    registered_names = {
        pose["name"]
        for pose in inspection_poses
    }

    registered_frames = [
        name
        for name in expected_names
        if name in registered_names
    ]
    failed_frames = [
        name
        for name in expected_names
        if name not in registered_names
    ]
    registered_numbers = [
        number
        for name in registered_frames
        if (
            number := parse_frame_number(
                name
            )
        )
        is not None
    ]
    runs = continuous_runs(
        registered_numbers
    )
    longest_run = (
        max(
            runs,
            key=lambda item: item["length"],
        )
        if runs
        else {}
    )

    pose_csv = output_dir / "inspection_poses.csv"
    baseline_pose_csv = output_dir / "baseline_poses.csv"
    timeline_csv = output_dir / "registration_timeline.csv"
    registered_txt = output_dir / "registered_frames.txt"
    failed_txt = output_dir / "failed_frames.txt"

    write_pose_csv(
        pose_csv,
        inspection_poses,
    )
    write_pose_csv(
        baseline_pose_csv,
        baseline_poses,
    )

    with timeline_csv.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as timeline_file:
        writer = csv.DictWriter(
            timeline_file,
            fieldnames=[
                "frame_number",
                "filename",
                "registered",
            ],
        )
        writer.writeheader()

        for frame in input_frames:
            relative_name = (
                f"inspection/{frame.name}"
            )
            writer.writerow(
                {
                    "frame_number": (
                        parse_frame_number(
                            frame.name
                        )
                    ),
                    "filename": frame.name,
                    "registered": int(
                        relative_name
                        in registered_names
                    ),
                }
            )

    registered_txt.write_text(
        "\n".join(
            registered_frames
        )
        + (
            "\n"
            if registered_frames
            else ""
        ),
        encoding="utf-8",
    )
    failed_txt.write_text(
        "\n".join(
            failed_frames
        )
        + (
            "\n"
            if failed_frames
            else ""
        ),
        encoding="utf-8",
    )

    registration_rate = (
        round(
            100.0
            * len(registered_frames)
            / len(input_frames),
            2,
        )
        if input_frames
        else 0.0
    )

    summary = {
        "inspection_id": inspection_id,
        "baseline_id": baseline_id,
        "status": (
            "ready"
            if registered_frames
            else "failed"
        ),
        "completed_at": now_iso(),
        "duration_seconds": round(
            duration_seconds,
            2,
        ),
        "input_frames": len(
            input_frames
        ),
        "registered_frames": len(
            registered_frames
        ),
        "failed_frames": len(
            failed_frames
        ),
        "registration_rate_percent": (
            registration_rate
        ),
        "baseline_registered_images": len(
            baseline_poses
        ),
        "total_registered_images": len(
            all_poses
        ),
        "continuous_runs": runs,
        "longest_continuous_run": longest_run,
        "first_registered_frame": (
            registered_frames[0]
            if registered_frames
            else None
        ),
        "last_registered_frame": (
            registered_frames[-1]
            if registered_frames
            else None
        ),
        "frame_path": str(
            frames_dir
        ),
        "database_path": str(
            database_path
        ),
        "registered_model_path": str(
            registered_model_path
        ),
        "model_txt_path": str(
            images_txt.parent
        ),
        "images_txt": str(
            images_txt
        ),
        "inspection_pose_csv": str(
            pose_csv
        ),
        "baseline_pose_csv": str(
            baseline_pose_csv
        ),
        "registration_timeline_csv": str(
            timeline_csv
        ),
        "registered_frames_txt": str(
            registered_txt
        ),
        "failed_frames_txt": str(
            failed_txt
        ),
        "note": (
            "Camera poses were added with COLMAP image_registrator. "
            "No bundle adjustment or triangulation was applied, so the "
            "active baseline coordinate system remains the reference."
        ),
    }

    summary_path = (
        output_dir
        / "localization_summary.json"
    )
    summary_path.write_text(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        "[PASS] REGISTRATION ANALYSIS COMPLETED"
    )
    print(
        f"Input frames       : {len(input_frames)}"
    )
    print(
        f"Registered frames  : {len(registered_frames)}"
    )
    print(
        f"Failed frames      : {len(failed_frames)}"
    )
    print(
        f"Registration rate  : {registration_rate}%"
    )
    print(
        f"Longest run        : {longest_run}"
    )
    print(
        f"Summary            : {summary_path}"
    )


if __name__ == "__main__":
    main()
