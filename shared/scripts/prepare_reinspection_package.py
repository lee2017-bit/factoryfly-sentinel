from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np


PATCH_VERSION = "7.3.12"
GEOMETRY_READY = {"excellent", "good", "usable"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--initial-package-dir", required=True)
    parser.add_argument("--mission-json", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--package-dir", required=True)
    parser.add_argument("--package-zip", required=True)
    parser.add_argument("--remote-script", required=True)
    parser.add_argument("--max-video-candidates", type=int, default=48)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def numeric(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def source_frame_number(mission: dict[str, Any]) -> int:
    representative = mission.get("representative_frame")
    if representative not in {None, ""}:
        return int(representative)
    frames = mission.get("source_frames") or []
    if frames:
        return int(frames[0])
    return -1


def load_initial_pair(
    initial_package_dir: Path,
    mission: dict[str, Any],
) -> tuple[dict[str, str], Path, Path]:
    manifest_path = initial_package_dir / "manifest.csv"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Initial AMD manifest not found: {manifest_path}")

    target_frame = source_frame_number(mission)
    for row in read_csv(manifest_path):
        if int(numeric(row.get("inspection_frame_number"), -1)) != target_frame:
            continue
        baseline_path = initial_package_dir / row["baseline_file"]
        inspection_path = initial_package_dir / row["inspection_file"]
        if not baseline_path.is_file():
            raise FileNotFoundError(f"Baseline evidence not found: {baseline_path}")
        if not inspection_path.is_file():
            raise FileNotFoundError(f"Initial inspection evidence not found: {inspection_path}")
        return row, baseline_path, inspection_path

    raise RuntimeError(f"No initial AMD pair was found for source frame {target_frame}.")


def video_candidates(path: Path, maximum: int) -> list[tuple[str, np.ndarray]]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open reinspection video: {path}")

    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    if frame_count <= 0:
        frame_count = maximum

    sample_count = max(1, min(maximum, frame_count))
    indices = np.linspace(0, max(frame_count - 1, 0), sample_count, dtype=int)
    output: list[tuple[str, np.ndarray]] = []

    for index in sorted(set(int(value) for value in indices)):
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = capture.read()
        if not ok or frame is None:
            continue
        seconds = index / fps if fps > 0 else 0.0
        output.append((f"video_frame_{index:06d}_{seconds:.2f}s", frame))

    capture.release()
    if not output:
        raise RuntimeError("No frames could be decoded from the reinspection video.")
    return output


def image_candidates(path: Path) -> list[tuple[str, np.ndarray]]:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not read reinspection image: {path}")
    return [(path.stem, image)]


def candidate_images(path: Path, maximum: int) -> list[tuple[str, np.ndarray]]:
    image_suffixes = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    video_suffixes = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}
    suffix = path.suffix.lower()

    if suffix in image_suffixes:
        return image_candidates(path)
    if suffix in video_suffixes:
        return video_candidates(path, maximum)
    raise RuntimeError(
        "Reinspection source must be an image or video file. "
        f"Unsupported suffix: {suffix}"
    )


def resized_for_features(image: np.ndarray, max_side: int = 1280) -> tuple[np.ndarray, float]:
    height, width = image.shape[:2]
    scale = min(1.0, max_side / max(height, width))
    if scale >= 0.999:
        return image, 1.0
    resized = cv2.resize(
        image,
        (int(round(width * scale)), int(round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )
    return resized, scale


def detector_and_norm() -> tuple[Any, int]:
    if hasattr(cv2, "SIFT_create"):
        return cv2.SIFT_create(nfeatures=5000), cv2.NORM_L2
    return cv2.ORB_create(nfeatures=6000, fastThreshold=8), cv2.NORM_HAMMING


def polygon_area(points: np.ndarray) -> float:
    return abs(float(cv2.contourArea(points.astype(np.float32))))


def hull_coverage(points: np.ndarray, image_shape: tuple[int, int]) -> float:
    if points.shape[0] < 3:
        return 0.0
    hull = cv2.convexHull(points.astype(np.float32))
    return polygon_area(hull) / max(float(image_shape[0] * image_shape[1]), 1.0)


def overlap_ratio(
    reference_shape: tuple[int, int],
    candidate_shape: tuple[int, int],
    homography: np.ndarray,
) -> float:
    mask = np.full(reference_shape, 255, dtype=np.uint8)
    warped = cv2.warpPerspective(
        mask,
        homography,
        (candidate_shape[1], candidate_shape[0]),
        flags=cv2.INTER_NEAREST,
    )
    return float(np.count_nonzero(warped)) / float(warped.size)


def evaluate_alignment(reference: np.ndarray, candidate: np.ndarray) -> dict[str, Any] | None:
    reference_small, reference_scale = resized_for_features(reference)
    candidate_small, candidate_scale = resized_for_features(candidate)
    reference_gray = cv2.cvtColor(reference_small, cv2.COLOR_BGR2GRAY)
    candidate_gray = cv2.cvtColor(candidate_small, cv2.COLOR_BGR2GRAY)

    detector, norm = detector_and_norm()
    keypoints_a, descriptors_a = detector.detectAndCompute(reference_gray, None)
    keypoints_b, descriptors_b = detector.detectAndCompute(candidate_gray, None)

    if descriptors_a is None or descriptors_b is None:
        return None
    if len(keypoints_a) < 12 or len(keypoints_b) < 12:
        return None

    matcher = cv2.BFMatcher(norm)
    raw_ab = matcher.knnMatch(descriptors_a, descriptors_b, k=2)
    raw_ba = matcher.knnMatch(descriptors_b, descriptors_a, k=2)

    ratio_ab: dict[int, Any] = {}
    for pair in raw_ab:
        if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance:
            ratio_ab[pair[0].queryIdx] = pair[0]

    reverse_best: dict[int, int] = {}
    for pair in raw_ba:
        if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance:
            reverse_best[pair[0].queryIdx] = pair[0].trainIdx

    mutual_matches = [
        match
        for query_index, match in ratio_ab.items()
        if reverse_best.get(match.trainIdx) == query_index
    ]
    if len(mutual_matches) < 10:
        return None

    src = np.float32([keypoints_a[m.queryIdx].pt for m in mutual_matches]).reshape(-1, 1, 2)
    dst = np.float32([keypoints_b[m.trainIdx].pt for m in mutual_matches]).reshape(-1, 1, 2)
    h_small, inlier_mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if h_small is None or inlier_mask is None:
        return None

    inliers = inlier_mask.reshape(-1).astype(bool)
    inlier_count = int(np.count_nonzero(inliers))
    if inlier_count < 8:
        return None

    reference_to_small = np.array(
        [[reference_scale, 0.0, 0.0], [0.0, reference_scale, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    candidate_from_small = np.array(
        [[1.0 / candidate_scale, 0.0, 0.0], [0.0, 1.0 / candidate_scale, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    homography = candidate_from_small @ h_small @ reference_to_small
    if not np.isfinite(homography).all() or abs(float(homography[2, 2])) < 1e-12:
        return None
    homography = homography / homography[2, 2]

    src_inlier_small = src[inliers]
    dst_inlier_small = dst[inliers]
    projected = cv2.perspectiveTransform(src_inlier_small, h_small)
    forward_errors = np.linalg.norm(
        projected.reshape(-1, 2) - dst_inlier_small.reshape(-1, 2), axis=1
    )
    median_forward_full = (
        float(np.median(forward_errors)) / max(candidate_scale, 1e-9)
        if forward_errors.size
        else math.inf
    )

    try:
        inverse_h_small = np.linalg.inv(h_small)
        back_projected = cv2.perspectiveTransform(dst_inlier_small, inverse_h_small)
        backward_errors = np.linalg.norm(
            back_projected.reshape(-1, 2) - src_inlier_small.reshape(-1, 2), axis=1
        )
        median_backward_full = (
            float(np.median(backward_errors)) / max(reference_scale, 1e-9)
            if backward_errors.size
            else math.inf
        )
    except np.linalg.LinAlgError:
        return None

    symmetric_error = max(median_forward_full, median_backward_full)
    inlier_ratio = inlier_count / max(len(mutual_matches), 1)
    overlap = overlap_ratio(reference.shape[:2], candidate.shape[:2], homography)

    src_full = src_inlier_small.reshape(-1, 2) / max(reference_scale, 1e-9)
    dst_full = dst_inlier_small.reshape(-1, 2) / max(candidate_scale, 1e-9)
    reference_coverage = hull_coverage(src_full, reference.shape[:2])
    candidate_coverage = hull_coverage(dst_full, candidate.shape[:2])

    h_ref, w_ref = reference.shape[:2]
    corners = np.float32(
        [[[0.0, 0.0]], [[w_ref - 1.0, 0.0]], [[w_ref - 1.0, h_ref - 1.0]], [[0.0, h_ref - 1.0]]]
    )
    projected_corners = cv2.perspectiveTransform(corners, homography).reshape(-1, 2)
    projected_area_ratio = polygon_area(projected_corners) / max(
        float(candidate.shape[0] * candidate.shape[1]), 1.0
    )
    corners_finite = bool(np.isfinite(projected_corners).all())
    corners_convex = bool(cv2.isContourConvex(projected_corners.astype(np.float32)))
    max_extent = max(candidate.shape[:2]) * 8.0
    corners_bounded = bool(np.max(np.abs(projected_corners)) <= max_extent)
    plausible_homography = (
        corners_finite
        and corners_convex
        and corners_bounded
        and 0.05 <= projected_area_ratio <= 3.0
        and reference_coverage >= 0.02
        and candidate_coverage >= 0.02
        and symmetric_error <= 12.0
    )

    quality = "poor"
    if (
        plausible_homography
        and inlier_count >= 30
        and inlier_ratio >= 0.45
        and overlap >= 0.25
        and symmetric_error <= 5.0
        and reference_coverage >= 0.05
        and candidate_coverage >= 0.05
    ):
        quality = "good"
    elif (
        plausible_homography
        and inlier_count >= 16
        and inlier_ratio >= 0.35
        and overlap >= 0.15
        and symmetric_error <= 8.0
        and reference_coverage >= 0.03
        and candidate_coverage >= 0.03
    ):
        quality = "usable"

    score = (
        min(inlier_count / 60.0, 1.0) * 0.25
        + min(inlier_ratio / 0.7, 1.0) * 0.20
        + min(overlap / 0.65, 1.0) * 0.20
        + min(reference_coverage / 0.15, 1.0) * 0.12
        + min(candidate_coverage / 0.15, 1.0) * 0.12
        + max(0.0, 1.0 - symmetric_error / 12.0) * 0.11
    )

    return {
        "homography": homography,
        "quality": quality,
        "feature_matches": len(mutual_matches),
        "inlier_count": inlier_count,
        "inlier_ratio": inlier_ratio,
        "overlap_ratio": overlap,
        "median_reprojection_error": median_forward_full,
        "symmetric_reprojection_error": symmetric_error,
        "reference_coverage": reference_coverage,
        "candidate_coverage": candidate_coverage,
        "projected_area_ratio": projected_area_ratio,
        "plausible_homography": plausible_homography,
        "alignment_score": score,
    }


def quality_rank(value: str) -> int:
    return {"poor": 0, "usable": 1, "good": 2, "excellent": 3}.get(value, 0)


def manifest_homography(row: dict[str, str]) -> np.ndarray:
    matrix = np.array(
        [
            [numeric(row.get("h00")), numeric(row.get("h01")), numeric(row.get("h02"))],
            [numeric(row.get("h10")), numeric(row.get("h11")), numeric(row.get("h12"))],
            [numeric(row.get("h20")), numeric(row.get("h21")), numeric(row.get("h22"), 1.0)],
        ],
        dtype=np.float64,
    )
    if not np.isfinite(matrix).all() or abs(float(matrix[2, 2])) < 1e-12:
        raise RuntimeError("The initial baseline-to-inspection homography is invalid.")
    return matrix / matrix[2, 2]


def bridge_alignment(
    baseline_to_initial: np.ndarray,
    initial_alignment: dict[str, Any],
    baseline_shape: tuple[int, int],
    candidate_shape: tuple[int, int],
) -> dict[str, Any]:
    initial_to_candidate = np.asarray(
        initial_alignment["homography"],
        dtype=np.float64,
    )
    composed = initial_to_candidate @ baseline_to_initial
    if not np.isfinite(composed).all() or abs(float(composed[2, 2])) < 1e-12:
        raise RuntimeError("The composed baseline-to-reinspection homography is invalid.")
    composed = composed / composed[2, 2]

    result = dict(initial_alignment)
    result["homography"] = composed
    result["overlap_ratio"] = overlap_ratio(
        baseline_shape,
        candidate_shape,
        composed,
    )

    h_ref, w_ref = baseline_shape
    corners = np.float32(
        [[[0.0, 0.0]], [[w_ref - 1.0, 0.0]], [[w_ref - 1.0, h_ref - 1.0]], [[0.0, h_ref - 1.0]]]
    )
    projected = cv2.perspectiveTransform(corners, composed).reshape(-1, 2)
    result["projected_area_ratio"] = polygon_area(projected) / max(
        float(candidate_shape[0] * candidate_shape[1]),
        1.0,
    )
    result["reference_mode"] = "initial_inspection_bridge"
    return result


def crop_to_projected_reference(
    candidate: np.ndarray,
    homography: np.ndarray,
    reference_shape: tuple[int, int],
    margin_ratio: float = 0.12,
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    h_ref, w_ref = reference_shape
    corners = np.float32(
        [[[0.0, 0.0]], [[w_ref - 1.0, 0.0]], [[w_ref - 1.0, h_ref - 1.0]], [[0.0, h_ref - 1.0]]]
    )
    projected = cv2.perspectiveTransform(corners, homography).reshape(-1, 2)
    if not np.isfinite(projected).all():
        return candidate, homography, [0, 0, candidate.shape[1], candidate.shape[0]]

    x_min, y_min = np.min(projected, axis=0)
    x_max, y_max = np.max(projected, axis=0)
    width = max(float(x_max - x_min), 1.0)
    height = max(float(y_max - y_min), 1.0)
    margin_x = width * margin_ratio
    margin_y = height * margin_ratio

    x0 = max(0, int(math.floor(x_min - margin_x)))
    y0 = max(0, int(math.floor(y_min - margin_y)))
    x1 = min(candidate.shape[1], int(math.ceil(x_max + margin_x)))
    y1 = min(candidate.shape[0], int(math.ceil(y_max + margin_y)))

    # Keep the original frame if the projected area is implausibly small.
    if x1 - x0 < 96 or y1 - y0 < 96:
        return candidate, homography, [0, 0, candidate.shape[1], candidate.shape[0]]

    cropped = candidate[y0:y1, x0:x1].copy()
    crop_translation = np.array(
        [[1.0, 0.0, -float(x0)], [0.0, 1.0, -float(y0)], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    adjusted = crop_translation @ homography
    adjusted = adjusted / adjusted[2, 2]
    return cropped, adjusted, [x0, y0, x1, y1]


def thumbnail(image: np.ndarray, width: int = 420, height: int = 240) -> np.ndarray:
    canvas = np.full((height, width, 3), 245, dtype=np.uint8)
    scale = min(width / image.shape[1], height / image.shape[0])
    resized = cv2.resize(
        image,
        (max(1, int(image.shape[1] * scale)), max(1, int(image.shape[0] * scale))),
        interpolation=cv2.INTER_AREA,
    )
    y = (height - resized.shape[0]) // 2
    x = (width - resized.shape[1]) // 2
    canvas[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
    return canvas


def write_candidate_review(
    path: Path,
    baseline: np.ndarray,
    initial: np.ndarray,
    evaluated: list[dict[str, Any]],
) -> None:
    rows: list[np.ndarray] = []
    reference_row = np.hstack([thumbnail(baseline), thumbnail(initial)])
    cv2.putText(reference_row, "Baseline reference", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 2)
    cv2.putText(reference_row, "Initial inspection reference", (432, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 2)
    rows.append(reference_row)

    for item in evaluated[:6]:
        image = thumbnail(item["image"], width=840, height=240)
        baseline_result = item.get("baseline_alignment") or {}
        initial_result = item.get("initial_alignment") or {}
        text = (
            f"{item['name']} | baseline={baseline_result.get('quality', 'none')} "
            f"score={numeric(baseline_result.get('alignment_score')):.3f} | "
            f"initial={initial_result.get('quality', 'none')} "
            f"score={numeric(initial_result.get('alignment_score')):.3f}"
        )
        cv2.rectangle(image, (0, 0), (840, 38), (255, 255, 255), -1)
        cv2.putText(image, text[:115], (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.53, (0, 0, 0), 1, cv2.LINE_AA)
        rows.append(image)

    if rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), np.vstack(rows), [int(cv2.IMWRITE_JPEG_QUALITY), 92])


def main() -> None:
    args = parse_args()
    initial_package_dir = Path(args.initial_package_dir).resolve()
    mission_json = Path(args.mission_json).resolve()
    source = Path(args.source).resolve()
    package_dir = Path(args.package_dir).resolve()
    package_zip = Path(args.package_zip).resolve()
    remote_script = Path(args.remote_script).resolve()

    if not source.is_file():
        raise FileNotFoundError(f"Reinspection source not found: {source}")

    mission = json.loads(mission_json.read_text(encoding="utf-8-sig"))
    initial_row, baseline_source, initial_inspection_source = load_initial_pair(
        initial_package_dir, mission
    )
    baseline = cv2.imread(str(baseline_source), cv2.IMREAD_COLOR)
    initial_inspection = cv2.imread(str(initial_inspection_source), cv2.IMREAD_COLOR)
    if baseline is None:
        raise RuntimeError(f"Could not read baseline image: {baseline_source}")
    if initial_inspection is None:
        raise RuntimeError(f"Could not read initial inspection image: {initial_inspection_source}")

    if package_dir.exists():
        shutil.rmtree(package_dir)
    if package_zip.exists():
        package_zip.unlink()
    package_dir.mkdir(parents=True, exist_ok=True)

    baseline_to_initial = manifest_homography(initial_row)

    evaluated: list[dict[str, Any]] = []
    for name, image in candidate_images(source, args.max_video_candidates):
        baseline_alignment = evaluate_alignment(baseline, image)
        initial_alignment = evaluate_alignment(initial_inspection, image)

        baseline_quality = str(
            (baseline_alignment or {}).get("quality", "poor")
        )
        initial_quality = str(
            (initial_alignment or {}).get("quality", "poor")
        )
        baseline_ready = baseline_quality in GEOMETRY_READY
        initial_ready = initial_quality in GEOMETRY_READY

        reacquisition_alignment: dict[str, Any] | None = None
        reacquisition_reference = "none"
        if baseline_ready and baseline_alignment is not None:
            reacquisition_alignment = dict(baseline_alignment)
            reacquisition_alignment["reference_mode"] = "baseline_direct"
            reacquisition_reference = "baseline_direct"
        elif initial_ready and initial_alignment is not None:
            reacquisition_alignment = bridge_alignment(
                baseline_to_initial,
                initial_alignment,
                baseline.shape[:2],
                image.shape[:2],
            )
            reacquisition_reference = "initial_inspection_bridge"

        baseline_score = numeric((baseline_alignment or {}).get("alignment_score"))
        initial_score = numeric((initial_alignment or {}).get("alignment_score"))
        reacquisition_score = numeric(
            (reacquisition_alignment or {}).get("alignment_score")
        )
        evaluated.append(
            {
                "name": name,
                "image": image,
                "baseline_alignment": baseline_alignment,
                "initial_alignment": initial_alignment,
                "reacquisition_alignment": reacquisition_alignment,
                "reacquisition_reference": reacquisition_reference,
                "combined_score": (
                    0.70 * reacquisition_score
                    + 0.20 * initial_score
                    + 0.10 * baseline_score
                ),
            }
        )

    if not evaluated:
        raise RuntimeError("No frames could be evaluated from the reinspection source.")

    evaluated.sort(
        key=lambda item: (
            quality_rank(
                str(
                    (item.get("reacquisition_alignment") or {}).get(
                        "quality",
                        "poor",
                    )
                )
            ),
            quality_rank(
                str(
                    (item.get("initial_alignment") or {}).get(
                        "quality",
                        "poor",
                    )
                )
            ),
            item["combined_score"],
        ),
        reverse=True,
    )

    review_path = package_dir / "candidate_review.jpg"
    write_candidate_review(review_path, baseline, initial_inspection, evaluated)

    valid = [
        item
        for item in evaluated
        if str(
            (item.get("reacquisition_alignment") or {}).get(
                "quality",
                "poor",
            )
        )
        in GEOMETRY_READY
    ]

    validation = {
        "status": "ready" if valid else "target_not_reacquired",
        "completed_at": now_iso(),
        "mission_id": mission.get("mission_id"),
        "source": str(source),
        "candidate_count": len(evaluated),
        "valid_baseline_candidates": sum(
            1
            for item in evaluated
            if str((item.get("baseline_alignment") or {}).get("quality", "poor"))
            in GEOMETRY_READY
        ),
        "valid_reacquisition_candidates": len(valid),
        "candidate_review": str(review_path),
        "top_candidates": [
            {
                "name": item["name"],
                "baseline": {
                    key: value
                    for key, value in (item.get("baseline_alignment") or {}).items()
                    if key != "homography"
                },
                "initial": {
                    key: value
                    for key, value in (item.get("initial_alignment") or {}).items()
                    if key != "homography"
                },
                "reacquisition": {
                    key: value
                    for key, value in (
                        item.get("reacquisition_alignment") or {}
                    ).items()
                    if key != "homography"
                },
                "reacquisition_reference": item.get(
                    "reacquisition_reference",
                    "none",
                ),
                "combined_score": item["combined_score"],
            }
            for item in evaluated[:10]
        ],
    }
    (package_dir / "reinspection_validation.json").write_text(
        json.dumps(validation, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if not valid:
        best = evaluated[0]
        best_baseline = best.get("baseline_alignment") or {}
        summary = {
            "status": "target_not_reacquired",
            "analysis_required": False,
            "completed_at": now_iso(),
            "mission_id": mission.get("mission_id"),
            "source": str(source),
            "selected_candidate": best["name"],
            "candidate_count": len(evaluated),
            "valid_baseline_candidates": 0,
            "quality": str(best_baseline.get("quality", "poor")),
            "feature_matches": int(best_baseline.get("feature_matches", 0)),
            "inlier_count": int(best_baseline.get("inlier_count", 0)),
            "inlier_ratio": numeric(best_baseline.get("inlier_ratio")),
            "overlap_ratio": numeric(best_baseline.get("overlap_ratio")),
            "median_reprojection_error": (
                numeric(best_baseline.get("median_reprojection_error"))
                if best_baseline.get("median_reprojection_error") not in {None, ""}
                else None
            ),
            "alignment_score": numeric(best_baseline.get("alignment_score")),
            "candidate_review": str(review_path),
            "message": (
                "The target area was not reacquired with usable baseline geometry. "
                "No DINOv2 change score was produced because unrelated views must not be compared."
            ),
        }
        (package_dir / "package_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("[WARN] TARGET AREA NOT REACQUIRED")
        print(f"Best candidate      : {best['name']}")
        print(f"Baseline geometry   : {best_baseline.get('quality', 'none')}")
        print(f"Candidate review    : {review_path}")
        print("DINOv2 analysis     : skipped")
        return

    selected = valid[0]
    selected_name = selected["name"]
    selected_image = selected["image"]
    alignment = dict(selected["reacquisition_alignment"])
    initial_alignment = selected.get("initial_alignment") or {}
    reacquisition_reference = str(
        selected.get("reacquisition_reference", "baseline_direct")
    )

    selected_image, adjusted_homography, crop_box = crop_to_projected_reference(
        selected_image,
        np.asarray(alignment["homography"], dtype=np.float64),
        baseline.shape[:2],
    )
    alignment["homography"] = adjusted_homography
    alignment["overlap_ratio"] = overlap_ratio(
        baseline.shape[:2],
        selected_image.shape[:2],
        adjusted_homography,
    )

    pair_id = str(mission.get("mission_id", "reinspection_001"))
    pair_dir = package_dir / "pairs" / pair_id
    pair_dir.mkdir(parents=True, exist_ok=True)
    baseline_target = pair_dir / "baseline.jpg"
    initial_target = pair_dir / "initial_inspection.jpg"
    reinspection_target = pair_dir / "inspection.jpg"
    shutil.copy2(baseline_source, baseline_target)
    shutil.copy2(initial_inspection_source, initial_target)
    cv2.imwrite(str(reinspection_target), selected_image, [int(cv2.IMWRITE_JPEG_QUALITY), 94])

    manifest_row: dict[str, Any] = {
        "pair_id": pair_id,
        "inspection_frame_number": source_frame_number(mission),
        "selection_reason": (
            "targeted_reinspection_initial_bridge"
            if reacquisition_reference == "initial_inspection_bridge"
            else "targeted_reinspection_baseline_direct"
        ),
        "quality": alignment["quality"],
        "reacquisition_reference": reacquisition_reference,
        "source_crop_box": json.dumps(crop_box),
        "baseline_name": initial_row.get("baseline_name", baseline_source.name),
        "inspection_name": selected_name,
        "baseline_file": baseline_target.relative_to(package_dir).as_posix(),
        "inspection_file": reinspection_target.relative_to(package_dir).as_posix(),
        "mutual_matches": alignment["inlier_count"],
        "fundamental_inlier_ratio": alignment["inlier_ratio"],
        "homography_inlier_ratio": alignment["inlier_ratio"],
        "overlap_ratio": alignment["overlap_ratio"],
        "median_reprojection_error": alignment["median_reprojection_error"],
        "refinement_score": alignment["alignment_score"],
        "reference_coverage": alignment["reference_coverage"],
        "candidate_coverage": alignment["candidate_coverage"],
        "projected_area_ratio": alignment["projected_area_ratio"],
        "mission_id": pair_id,
        "initial_score_p95": mission.get("initial_score_p95"),
        "suspected_object": mission.get("suspected_object"),
        "target_area": mission.get("target_area"),
    }
    homography = alignment["homography"]
    for matrix_row in range(3):
        for matrix_column in range(3):
            manifest_row[f"h{matrix_row}{matrix_column}"] = float(homography[matrix_row, matrix_column])

    manifest_path = package_dir / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(manifest_row.keys()))
        writer.writeheader()
        writer.writerow(manifest_row)

    shutil.copy2(remote_script, package_dir / "run_amd_dino_analysis.py")
    shutil.copy2(mission_json, package_dir / "mission.json")

    summary = {
        "status": "ready",
        "analysis_required": True,
        "completed_at": now_iso(),
        "mission_id": pair_id,
        "source": str(source),
        "selected_candidate": selected_name,
        "candidate_count": len(evaluated),
        "valid_baseline_candidates": sum(
            1
            for item in evaluated
            if str((item.get("baseline_alignment") or {}).get("quality", "poor"))
            in GEOMETRY_READY
        ),
        "valid_reacquisition_candidates": len(valid),
        "quality": alignment["quality"],
        "reacquisition_reference": reacquisition_reference,
        "source_crop_box": crop_box,
        "feature_matches": alignment["feature_matches"],
        "inlier_count": alignment["inlier_count"],
        "inlier_ratio": alignment["inlier_ratio"],
        "overlap_ratio": alignment["overlap_ratio"],
        "median_reprojection_error": alignment["median_reprojection_error"],
        "symmetric_reprojection_error": alignment["symmetric_reprojection_error"],
        "reference_coverage": alignment["reference_coverage"],
        "candidate_coverage": alignment["candidate_coverage"],
        "projected_area_ratio": alignment["projected_area_ratio"],
        "alignment_score": alignment["alignment_score"],
        "initial_reference_quality": initial_alignment.get("quality", "none"),
        "initial_reference_score": numeric(initial_alignment.get("alignment_score")),
        "candidate_review": str(review_path),
        "package_zip": str(package_zip),
    }
    (package_dir / "package_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    package_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        package_zip,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(package_dir).as_posix())

    print("[PASS] REINSPECTION PACKAGE PREPARED")
    print(f"Mission                 : {pair_id}")
    print(f"Selected candidate      : {selected_name}")
    print(f"Reacquisition geometry  : {alignment['quality']}")
    print(f"Reference mode          : {reacquisition_reference}")
    print(f"Initial-reference match : {initial_alignment.get('quality', 'none')}")
    print(f"Automatic crop          : {crop_box}")
    print(f"Inliers                 : {alignment['inlier_count']}")
    print(f"Overlap ratio           : {alignment['overlap_ratio']:.3f}")
    print(f"Symmetric reproj px     : {alignment['symmetric_reprojection_error']:.3f}")
    print(f"Archive                 : {package_zip}")


if __name__ == "__main__":
    main()
