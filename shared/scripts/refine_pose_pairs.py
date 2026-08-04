from __future__ import annotations

import csv
import html
import json
import math
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np


MAX_FEATURE_DIMENSION = 1280
SIFT_FEATURES = 4500
RATIO_TEST = 0.78
MIN_MATCHES_FOR_F = 8
MIN_MATCHES_FOR_H = 6


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def numeric(
    value: Any,
    kind: type = float,
    default: Any = 0,
) -> Any:
    try:
        return kind(value)
    except (
        TypeError,
        ValueError,
    ):
        return default


def resolve_image(
    root: Path,
    name: str,
) -> Path:
    normalized = name.replace(
        "\\",
        "/",
    )
    relative = Path(normalized)

    candidates = [
        root / relative,
        root / relative.name,
    ]

    if normalized.startswith(
        "inspection/"
    ):
        candidates.append(
            root
            / normalized.split(
                "/",
                1,
            )[1]
        )

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise FileNotFoundError(
        f"Image not found: {name} under {root}"
    )


def read_candidates(
    path: Path,
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    with path.open(
        encoding="utf-8-sig",
        newline="",
    ) as file:
        for source in csv.DictReader(file):
            row = dict(source)
            row["inspection_image_id"] = numeric(
                row.get(
                    "inspection_image_id"
                ),
                int,
            )
            row["inspection_frame_number"] = numeric(
                row.get(
                    "inspection_frame_number"
                ),
                int,
            )
            row["baseline_image_id"] = numeric(
                row.get(
                    "baseline_image_id"
                ),
                int,
            )
            row["candidate_rank"] = numeric(
                row.get(
                    "candidate_rank"
                ),
                int,
            )
            row["pose_distance"] = numeric(
                row.get(
                    "pose_distance"
                )
            )
            row["pose_distance_steps"] = numeric(
                row.get(
                    "pose_distance_steps"
                )
            )
            row["view_angle_degrees"] = numeric(
                row.get(
                    "view_angle_degrees"
                )
            )
            row["pose_score"] = numeric(
                row.get(
                    "pose_score"
                )
            )

            groups.setdefault(
                row["inspection_name"],
                [],
            ).append(row)

    for candidates in groups.values():
        candidates.sort(
            key=lambda row: row[
                "candidate_rank"
            ]
        )

    return groups


class FeatureCache:
    def __init__(self) -> None:
        self._cache: dict[
            str,
            dict[str, Any],
        ] = {}
        self._sift = cv2.SIFT_create(
            nfeatures=SIFT_FEATURES
        )

    def get(
        self,
        path: Path,
    ) -> dict[str, Any]:
        key = str(
            path.resolve()
        )

        if key in self._cache:
            return self._cache[key]

        image = cv2.imread(
            key,
            cv2.IMREAD_COLOR,
        )

        if image is None:
            raise RuntimeError(
                f"OpenCV could not read: {path}"
            )

        height, width = image.shape[:2]
        scale = min(
            1.0,
            MAX_FEATURE_DIMENSION
            / max(
                width,
                height,
            ),
        )

        if scale < 1.0:
            feature_image = cv2.resize(
                image,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_AREA,
            )
        else:
            feature_image = image

        gray = cv2.cvtColor(
            feature_image,
            cv2.COLOR_BGR2GRAY,
        )
        gray = cv2.equalizeHist(
            gray
        )
        keypoints, descriptors = (
            self._sift.detectAndCompute(
                gray,
                None,
            )
        )

        if descriptors is None:
            descriptors = np.empty(
                (0, 128),
                dtype=np.float32,
            )

        result = {
            "path": str(path.resolve()),
            "image": image,
            "keypoints": keypoints,
            "descriptors": descriptors,
            "scale": scale,
            "feature_width": feature_image.shape[1],
            "feature_height": feature_image.shape[0],
        }
        self._cache[key] = result
        return result


def ratio_matches(
    query_descriptors: np.ndarray,
    train_descriptors: np.ndarray,
) -> list[cv2.DMatch]:
    if (
        len(query_descriptors) < 2
        or len(train_descriptors) < 2
    ):
        return []

    matcher = cv2.BFMatcher(
        cv2.NORM_L2,
        crossCheck=False,
    )
    knn = matcher.knnMatch(
        query_descriptors,
        train_descriptors,
        k=2,
    )

    accepted: list[cv2.DMatch] = []

    for pair in knn:
        if len(pair) < 2:
            continue

        first, second = pair

        if first.distance < (
            RATIO_TEST
            * second.distance
        ):
            accepted.append(
                first
            )

    return accepted


def mutual_ratio_matches(
    baseline_descriptors: np.ndarray,
    inspection_descriptors: np.ndarray,
) -> list[cv2.DMatch]:
    forward = ratio_matches(
        baseline_descriptors,
        inspection_descriptors,
    )
    reverse = ratio_matches(
        inspection_descriptors,
        baseline_descriptors,
    )

    reverse_map = {
        match.queryIdx: match.trainIdx
        for match in reverse
    }

    return [
        match
        for match in forward
        if reverse_map.get(
            match.trainIdx
        )
        == match.queryIdx
    ]


def compute_overlap_ratio(
    homography: np.ndarray,
    baseline_size: tuple[int, int],
    inspection_size: tuple[int, int],
) -> float:
    baseline_height, baseline_width = baseline_size
    inspection_height, inspection_width = inspection_size

    corners = np.float32(
        [
            [0, 0],
            [baseline_width - 1, 0],
            [
                baseline_width - 1,
                baseline_height - 1,
            ],
            [0, baseline_height - 1],
        ]
    ).reshape(
        -1,
        1,
        2,
    )

    try:
        transformed = cv2.perspectiveTransform(
            corners,
            homography,
        ).reshape(
            -1,
            2,
        )
    except cv2.error:
        return 0.0

    if not np.isfinite(
        transformed
    ).all():
        return 0.0

    image_polygon = np.float32(
        [
            [0, 0],
            [inspection_width - 1, 0],
            [
                inspection_width - 1,
                inspection_height - 1,
            ],
            [0, inspection_height - 1],
        ]
    )

    transformed = cv2.convexHull(
        transformed.astype(
            np.float32
        )
    ).reshape(
        -1,
        2,
    )

    if len(transformed) < 3:
        return 0.0

    try:
        intersection_area, _ = (
            cv2.intersectConvexConvex(
                transformed,
                image_polygon,
            )
        )
    except cv2.error:
        return 0.0

    image_area = float(
        inspection_width
        * inspection_height
    )

    if image_area <= 0:
        return 0.0

    return max(
        0.0,
        min(
            1.0,
            float(intersection_area)
            / image_area,
        ),
    )


def compute_reprojection_error(
    homography: np.ndarray,
    baseline_points: np.ndarray,
    inspection_points: np.ndarray,
    mask: np.ndarray,
) -> float | None:
    valid = mask.ravel().astype(
        bool
    )

    if not np.any(valid):
        return None

    source = baseline_points[
        valid
    ].reshape(
        -1,
        1,
        2,
    )
    target = inspection_points[
        valid
    ]

    try:
        projected = cv2.perspectiveTransform(
            source,
            homography,
        ).reshape(
            -1,
            2,
        )
    except cv2.error:
        return None

    errors = np.linalg.norm(
        projected - target,
        axis=1,
    )

    if not len(errors):
        return None

    return float(
        np.median(errors)
    )


def matrix_to_columns(
    prefix: str,
    matrix: np.ndarray | None,
) -> dict[str, Any]:
    columns: dict[str, Any] = {}

    for row in range(3):
        for column in range(3):
            columns[
                f"{prefix}{row}{column}"
            ] = (
                float(
                    matrix[row, column]
                )
                if matrix is not None
                else ""
            )

    return columns


def evaluate_candidate(
    candidate: dict[str, Any],
    baseline_path: Path,
    inspection_path: Path,
    cache: FeatureCache,
) -> dict[str, Any]:
    result = dict(
        candidate
    )
    result["baseline_path"] = str(
        baseline_path.resolve()
    )
    result["inspection_path"] = str(
        inspection_path.resolve()
    )
    result.update(
        {
            "mutual_matches": 0,
            "fundamental_inliers": 0,
            "fundamental_inlier_ratio": 0.0,
            "homography_inliers": 0,
            "homography_inlier_ratio": 0.0,
            "overlap_ratio": 0.0,
            "median_reprojection_error": "",
            "refinement_score": -1.0,
            "valid_geometry": 0,
            "baseline_scale": 1.0,
            "inspection_scale": 1.0,
        }
    )

    baseline = cache.get(
        baseline_path
    )
    inspection = cache.get(
        inspection_path
    )

    matches = mutual_ratio_matches(
        baseline["descriptors"],
        inspection["descriptors"],
    )
    result["mutual_matches"] = len(
        matches
    )

    if len(matches) < MIN_MATCHES_FOR_H:
        result.update(
            matrix_to_columns(
                "h",
                None,
            )
        )
        return result

    baseline_points = np.float32(
        [
            baseline["keypoints"][
                match.queryIdx
            ].pt
            for match in matches
        ]
    )
    inspection_points = np.float32(
        [
            inspection["keypoints"][
                match.trainIdx
            ].pt
            for match in matches
        ]
    )

    fundamental_inliers = 0
    fundamental_ratio = 0.0

    if len(matches) >= MIN_MATCHES_FOR_F:
        try:
            _, fundamental_mask = (
                cv2.findFundamentalMat(
                    baseline_points,
                    inspection_points,
                    cv2.FM_RANSAC,
                    1.75,
                    0.995,
                )
            )

            if fundamental_mask is not None:
                fundamental_inliers = int(
                    np.count_nonzero(
                        fundamental_mask
                    )
                )
                fundamental_ratio = (
                    fundamental_inliers
                    / max(
                        len(matches),
                        1,
                    )
                )
        except cv2.error:
            pass

    homography = None
    homography_mask = None

    try:
        homography, homography_mask = (
            cv2.findHomography(
                baseline_points,
                inspection_points,
                cv2.RANSAC,
                4.5,
                maxIters=5000,
                confidence=0.995,
            )
        )
    except cv2.error:
        pass

    homography_inliers = 0
    homography_ratio = 0.0
    overlap_ratio = 0.0
    reprojection_error = None

    if (
        homography is not None
        and homography_mask is not None
    ):
        homography_inliers = int(
            np.count_nonzero(
                homography_mask
            )
        )
        homography_ratio = (
            homography_inliers
            / max(
                len(matches),
                1,
            )
        )
        overlap_ratio = compute_overlap_ratio(
            homography,
            (
                baseline[
                    "feature_height"
                ],
                baseline[
                    "feature_width"
                ],
            ),
            (
                inspection[
                    "feature_height"
                ],
                inspection[
                    "feature_width"
                ],
            ),
        )
        reprojection_error = (
            compute_reprojection_error(
                homography,
                baseline_points,
                inspection_points,
                homography_mask,
            )
        )

    result[
        "fundamental_inliers"
    ] = fundamental_inliers
    result[
        "fundamental_inlier_ratio"
    ] = fundamental_ratio
    result[
        "homography_inliers"
    ] = homography_inliers
    result[
        "homography_inlier_ratio"
    ] = homography_ratio
    result[
        "overlap_ratio"
    ] = overlap_ratio
    result[
        "median_reprojection_error"
    ] = (
        reprojection_error
        if reprojection_error is not None
        else ""
    )

    support_score = min(
        fundamental_inliers
        / 100.0,
        1.0,
    )
    reprojection_score = (
        math.exp(
            -reprojection_error
            / 5.0
        )
        if reprojection_error is not None
        else 0.0
    )
    pose_penalty = min(
        candidate["pose_score"]
        / 10.0,
        1.0,
    )

    refinement_score = (
        0.32
        * fundamental_ratio
        + 0.18
        * homography_ratio
        + 0.20
        * support_score
        + 0.18
        * min(
            overlap_ratio,
            1.0,
        )
        + 0.12
        * reprojection_score
        - 0.08
        * pose_penalty
    )

    valid_geometry = int(
        fundamental_inliers >= 12
        and fundamental_ratio >= 0.20
        and homography_inliers >= 10
        and homography is not None
    )

    result[
        "refinement_score"
    ] = refinement_score
    result[
        "valid_geometry"
    ] = valid_geometry
    result[
        "baseline_scale"
    ] = baseline["scale"]
    result[
        "inspection_scale"
    ] = inspection["scale"]
    result.update(
        matrix_to_columns(
            "h",
            homography,
        )
    )

    return result


def classify_quality(
    row: dict[str, Any],
) -> str:
    matches = row[
        "mutual_matches"
    ]
    f_inliers = row[
        "fundamental_inliers"
    ]
    f_ratio = row[
        "fundamental_inlier_ratio"
    ]
    h_inliers = row[
        "homography_inliers"
    ]
    h_ratio = row[
        "homography_inlier_ratio"
    ]
    overlap = row[
        "overlap_ratio"
    ]

    reprojection = row[
        "median_reprojection_error"
    ]
    reprojection = (
        float(
            reprojection
        )
        if reprojection != ""
        else 999.0
    )

    if (
        matches >= 90
        and f_inliers >= 55
        and f_ratio >= 0.48
        and h_inliers >= 45
        and h_ratio >= 0.38
        and overlap >= 0.35
        and reprojection <= 4.5
    ):
        return "excellent"

    if (
        matches >= 55
        and f_inliers >= 32
        and f_ratio >= 0.36
        and h_inliers >= 25
        and h_ratio >= 0.28
        and overlap >= 0.25
        and reprojection <= 6.5
    ):
        return "good"

    if (
        matches >= 25
        and f_inliers >= 15
        and f_ratio >= 0.24
        and h_inliers >= 12
        and h_ratio >= 0.18
        and overlap >= 0.12
        and reprojection <= 10.0
    ):
        return "usable"

    return "poor"


def read_homography(
    row: dict[str, Any],
) -> np.ndarray | None:
    values: list[list[float]] = []

    for matrix_row in range(3):
        current: list[float] = []

        for matrix_column in range(3):
            value = row[
                f"h{matrix_row}{matrix_column}"
            ]

            if value == "":
                return None

            current.append(
                float(value)
            )

        values.append(
            current
        )

    return np.array(
        values,
        dtype=np.float64,
    )


def full_resolution_homography(
    row: dict[str, Any],
) -> np.ndarray | None:
    feature_homography = (
        read_homography(row)
    )

    if feature_homography is None:
        return None

    baseline_scale = float(
        row["baseline_scale"]
    )
    inspection_scale = float(
        row["inspection_scale"]
    )

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
        @ feature_homography
        @ baseline_scale_matrix
    )


def add_label(
    image: np.ndarray,
    label: str,
) -> np.ndarray:
    output = image.copy()
    cv2.rectangle(
        output,
        (0, 0),
        (
            output.shape[1],
            48,
        ),
        (
            0,
            0,
            0,
        ),
        thickness=-1,
    )
    cv2.putText(
        output,
        label,
        (
            14,
            32,
        ),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (
            255,
            255,
            255,
        ),
        2,
        cv2.LINE_AA,
    )
    return output


def fit_to_cell(
    image: np.ndarray,
    width: int = 640,
    height: int = 360,
) -> np.ndarray:
    canvas = np.zeros(
        (
            height,
            width,
            3,
        ),
        dtype=np.uint8,
    )
    scale = min(
        width
        / image.shape[1],
        height
        / image.shape[0],
    )
    resized = cv2.resize(
        image,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_AREA,
    )
    y = (
        height
        - resized.shape[0]
    ) // 2
    x = (
        width
        - resized.shape[1]
    ) // 2
    canvas[
        y : y
        + resized.shape[0],
        x : x
        + resized.shape[1],
    ] = resized
    return canvas


def create_preview(
    row: dict[str, Any],
    output_path: Path,
) -> bool:
    baseline = cv2.imread(
        row["baseline_path"],
        cv2.IMREAD_COLOR,
    )
    inspection = cv2.imread(
        row["inspection_path"],
        cv2.IMREAD_COLOR,
    )

    if (
        baseline is None
        or inspection is None
    ):
        return False

    homography = full_resolution_homography(
        row
    )

    if homography is None:
        return False

    inspection_height, inspection_width = (
        inspection.shape[:2]
    )
    warped = cv2.warpPerspective(
        baseline,
        homography,
        (
            inspection_width,
            inspection_height,
        ),
    )
    source_mask = np.full(
        baseline.shape[:2],
        255,
        dtype=np.uint8,
    )
    overlap_mask = cv2.warpPerspective(
        source_mask,
        homography,
        (
            inspection_width,
            inspection_height,
        ),
        flags=cv2.INTER_NEAREST,
    )
    valid = overlap_mask > 0
    overlay = inspection.copy()
    overlay[valid] = (
        0.5
        * warped[valid]
        + 0.5
        * inspection[valid]
    ).astype(
        np.uint8
    )

    warped_gray = cv2.cvtColor(
        warped,
        cv2.COLOR_BGR2GRAY,
    )
    inspection_gray = cv2.cvtColor(
        inspection,
        cv2.COLOR_BGR2GRAY,
    )
    warped_gray = cv2.equalizeHist(
        warped_gray
    )
    inspection_gray = cv2.equalizeHist(
        inspection_gray
    )
    difference = cv2.absdiff(
        warped_gray,
        inspection_gray,
    )
    difference[
        ~valid
    ] = 0
    difference = cv2.GaussianBlur(
        difference,
        (
            5,
            5,
        ),
        0,
    )
    heatmap = cv2.applyColorMap(
        difference,
        cv2.COLORMAP_TURBO,
    )
    heatmap[
        ~valid
    ] = 0

    baseline_cell = fit_to_cell(
        add_label(
            baseline,
            "Baseline",
        )
    )
    inspection_cell = fit_to_cell(
        add_label(
            inspection,
            "Inspection",
        )
    )
    warped_cell = fit_to_cell(
        add_label(
            warped,
            "Warped baseline",
        )
    )
    overlay_heat = cv2.addWeighted(
        overlay,
        0.65,
        heatmap,
        0.35,
        0.0,
    )
    overlay_cell = fit_to_cell(
        add_label(
            overlay_heat,
            "Alignment preview / raw difference",
        )
    )
    montage = np.vstack(
        [
            np.hstack(
                [
                    baseline_cell,
                    inspection_cell,
                ]
            ),
            np.hstack(
                [
                    warped_cell,
                    overlay_cell,
                ]
            ),
        ]
    )
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    return bool(
        cv2.imwrite(
            str(output_path),
            montage,
            [
                int(
                    cv2.IMWRITE_JPEG_QUALITY
                ),
                92,
            ],
        )
    )


def file_uri(
    path: Path,
) -> str:
    return path.resolve().as_uri()


def make_review_html(
    path: Path,
    review_rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    cards: list[str] = []

    for row in review_rows:
        preview_path = Path(
            row["preview_path"]
        )
        reprojection = float(
            row[
                "median_reprojection_error"
            ]
        )
        metric_text = (
            f"Frame {row['inspection_frame_number']} · "
            f"{row['quality']} · "
            f"selected original rank {row['candidate_rank']} · "
            f"mutual matches {row['mutual_matches']} · "
            f"F inliers {row['fundamental_inliers']} "
            f"({row['fundamental_inlier_ratio']:.2f}) · "
            f"H inliers {row['homography_inliers']} "
            f"({row['homography_inlier_ratio']:.2f}) · "
            f"overlap {row['overlap_ratio']:.2f} · "
            f"reprojection {reprojection:.2f}px"
        )
        cards.append(
            f"""
<section class="card">
  <h2>{html.escape(metric_text)}</h2>
  <p>
    Baseline: {html.escape(row["baseline_name"])}
    <br>
    Inspection: {html.escape(row["inspection_name"])}
  </p>
  <img src="{html.escape(file_uri(preview_path))}">
</section>
"""
        )

    quality_text = " · ".join(
        f"{name}: {count}"
        for name, count in summary[
            "quality_counts"
        ].items()
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FactoryFly Geometric Refinement Review</title>
<style>
body {{
    margin: 24px;
    background: #101010;
    color: #eeeeee;
    font-family: Arial, sans-serif;
}}
header {{
    position: sticky;
    top: 0;
    z-index: 5;
    padding: 14px 0;
    background: rgba(16, 16, 16, 0.97);
    border-bottom: 1px solid #555;
}}
h1 {{ margin: 0 0 8px 0; }}
.summary {{ color: #bbbbbb; }}
.card {{
    margin: 26px 0;
    padding: 18px;
    background: #1b1b1b;
    border: 1px solid #444;
    border-radius: 10px;
}}
.card h2 {{
    font-size: 16px;
    line-height: 1.45;
}}
.card p {{
    color: #bbbbbb;
    word-break: break-all;
}}
.card img {{
    display: block;
    width: 100%;
    height: auto;
    background: black;
}}
</style>
</head>
<body>
<header>
  <h1>FactoryFly Geometric Refinement</h1>
  <div class="summary">
    Inspection frames: {summary["inspection_frames"]} ·
    {html.escape(quality_text)}
  </div>
</header>
{''.join(cards)}
</body>
</html>
"""
    path.write_text(
        document,
        encoding="utf-8",
    )


def write_rows(
    path: Path,
    rows: list[dict[str, Any]],
) -> None:
    fields = sorted(
        {
            key
            for row in rows
            for key in row.keys()
        }
    )

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fields,
        )
        writer.writeheader()
        writer.writerows(
            rows
        )


def main() -> None:
    if len(sys.argv) != 8:
        raise RuntimeError(
            "Usage: refine_pose_pairs.py "
            "<candidate_csv> <baseline_root> <inspection_root> "
            "<output_root> <preview_root> <inspection_id> <baseline_id>"
        )

    started = time.perf_counter()
    candidate_csv = Path(
        sys.argv[1]
    ).resolve()
    baseline_root = Path(
        sys.argv[2]
    ).resolve()
    inspection_root = Path(
        sys.argv[3]
    ).resolve()
    output_root = Path(
        sys.argv[4]
    ).resolve()
    preview_root = Path(
        sys.argv[5]
    ).resolve()
    inspection_id = sys.argv[6]
    baseline_id = sys.argv[7]

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )
    preview_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        cv2.SIFT_create(
            nfeatures=10
        )
    except AttributeError as exc:
        raise RuntimeError(
            "OpenCV SIFT is unavailable. Install a current "
            "opencv-python or opencv-contrib-python build."
        ) from exc

    groups = read_candidates(
        candidate_csv
    )
    cache = FeatureCache()
    all_candidate_results: list[
        dict[str, Any]
    ] = []
    best_results: list[
        dict[str, Any]
    ] = []
    total_groups = len(
        groups
    )

    for group_index, (
        inspection_name,
        candidates,
    ) in enumerate(
        sorted(
            groups.items(),
            key=lambda item: item[1][0][
                "inspection_frame_number"
            ],
        ),
        start=1,
    ):
        inspection_path = resolve_image(
            inspection_root,
            inspection_name,
        )
        evaluated: list[
            dict[str, Any]
        ] = []

        for candidate in candidates:
            baseline_path = resolve_image(
                baseline_root,
                candidate[
                    "baseline_name"
                ],
            )
            result = evaluate_candidate(
                candidate,
                baseline_path,
                inspection_path,
                cache,
            )
            evaluated.append(
                result
            )
            all_candidate_results.append(
                result
            )

        evaluated.sort(
            key=lambda row: row[
                "refinement_score"
            ],
            reverse=True,
        )
        best = dict(
            evaluated[0]
        )
        best["quality"] = classify_quality(
            best
        )
        best["refinement_margin"] = (
            best["refinement_score"]
            - evaluated[1][
                "refinement_score"
            ]
            if len(evaluated) > 1
            else 0.0
        )
        best_results.append(
            best
        )

        if (
            group_index == 1
            or group_index % 10 == 0
            or group_index == total_groups
        ):
            print(
                f"[{group_index:03d}/{total_groups:03d}] "
                f"inspection frame "
                f"{best['inspection_frame_number']:03d} "
                f"-> rank {best['candidate_rank']} "
                f"{best['quality']} "
                f"score={best['refinement_score']:.3f}",
                flush=True,
            )

    best_results.sort(
        key=lambda row: row[
            "inspection_frame_number"
        ]
    )
    all_output = (
        output_root
        / "all_candidate_refinement_scores.csv"
    )
    best_output = (
        output_root
        / "refined_pairs.csv"
    )
    amd_ready_output = (
        output_root
        / "amd_ready_pairs.csv"
    )

    write_rows(
        all_output,
        all_candidate_results,
    )
    write_rows(
        best_output,
        best_results,
    )

    amd_ready_rows = [
        row
        for row in best_results
        if row["quality"]
        in {
            "excellent",
            "good",
            "usable",
        }
    ]
    write_rows(
        amd_ready_output,
        amd_ready_rows,
    )

    quality_counts = {
        "excellent": 0,
        "good": 0,
        "usable": 0,
        "poor": 0,
    }

    for row in best_results:
        quality_counts[
            row["quality"]
        ] += 1

    quality_rank = {
        "excellent": 3,
        "good": 2,
        "usable": 1,
        "poor": 0,
    }
    preview_candidates = [
        row
        for row in best_results
        if row["quality"] != "poor"
        and row[
            "median_reprojection_error"
        ]
        != ""
    ]
    preview_candidates.sort(
        key=lambda row: (
            -quality_rank[
                row["quality"]
            ],
            -row[
                "refinement_score"
            ],
        )
    )
    preview_candidates = (
        preview_candidates[:40]
    )
    review_rows: list[
        dict[str, Any]
    ] = []

    for row in preview_candidates:
        preview_name = (
            f"frame_"
            f"{row['inspection_frame_number']:06d}"
            f"_{row['quality']}.jpg"
        )
        preview_path = (
            preview_root
            / preview_name
        )

        if create_preview(
            row,
            preview_path,
        ):
            review_row = dict(
                row
            )
            review_row[
                "preview_path"
            ] = str(
                preview_path
            )
            review_rows.append(
                review_row
            )

    valid_scores = [
        float(
            row["refinement_score"]
        )
        for row in best_results
    ]
    valid_reprojection = [
        float(
            row[
                "median_reprojection_error"
            ]
        )
        for row in best_results
        if row[
            "median_reprojection_error"
        ]
        != ""
    ]

    pose_summary_path = (
        output_root
        / "pose_candidate_summary.json"
    )
    pose_summary = (
        json.loads(
            pose_summary_path.read_text(
                encoding="utf-8-sig"
            )
        )
        if pose_summary_path.is_file()
        else {}
    )

    summary = {
        "inspection_id": inspection_id,
        "baseline_id": baseline_id,
        "status": "ready",
        "completed_at": now_iso(),
        "duration_seconds": round(
            time.perf_counter()
            - started,
            2,
        ),
        "top_k": pose_summary.get(
            "top_k"
        ),
        "median_baseline_step": (
            pose_summary.get(
                "median_baseline_step"
            )
        ),
        "inspection_frames": len(
            best_results
        ),
        "evaluated_candidates": len(
            all_candidate_results
        ),
        "quality_counts": quality_counts,
        "non_poor_pairs": len(
            amd_ready_rows
        ),
        "amd_ready_pairs": len(
            amd_ready_rows
        ),
        "high_confidence_pairs": (
            quality_counts[
                "excellent"
            ]
            + quality_counts[
                "good"
            ]
        ),
        "median_refinement_score": (
            statistics.median(
                valid_scores
            )
            if valid_scores
            else None
        ),
        "median_reprojection_error": (
            statistics.median(
                valid_reprojection
            )
            if valid_reprojection
            else None
        ),
        "preview_count": len(
            review_rows
        ),
        "method": (
            "Top-K pose retrieval followed by mutual-ratio SIFT, "
            "Fundamental Matrix RANSAC, Homography RANSAC, overlap, "
            "and reprojection scoring."
        ),
        "limitations": (
            "Homography is a planar alignment approximation. "
            "Non-rigid objects, dynamic people, parallax, blur, and "
            "illumination changes can still produce poor or misleading pairs."
        ),
        "outputs": {
            "pose_candidates": str(
                candidate_csv
            ),
            "refined_pairs": str(
                best_output
            ),
            "all_candidate_scores": str(
                all_output
            ),
            "amd_ready_pairs": str(
                amd_ready_output
            ),
            "review_html": str(
                output_root
                / "refinement_review.html"
            ),
            "preview_directory": str(
                preview_root
            ),
        },
    }
    summary_path = (
        output_root
        / "refinement_summary.json"
    )
    summary_path.write_text(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    make_review_html(
        output_root
        / "refinement_review.html",
        review_rows,
        summary,
    )

    print("")
    print(
        "=" * 62
    )
    print(
        "[PASS] GEOMETRIC REFINEMENT COMPLETED"
    )
    print(
        "=" * 62
    )
    print(
        f"Inspection frames    : {len(best_results)}"
    )
    print(
        f"Candidates evaluated : {len(all_candidate_results)}"
    )
    print(
        "Refined pair quality:"
    )

    for name in (
        "excellent",
        "good",
        "usable",
        "poor",
    ):
        print(
            f"  {name:<9} : "
            f"{quality_counts[name]}"
        )

    print(
        f"AMD-ready pairs      : {len(amd_ready_rows)}"
    )
    print(
        f"Summary              : {summary_path}"
    )


if __name__ == "__main__":
    main()
