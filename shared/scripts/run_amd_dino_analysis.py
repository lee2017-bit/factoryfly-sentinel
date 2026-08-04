from __future__ import annotations

import argparse
import csv
import json
import math
import os
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch


IMAGE_SIZE = 224
PATCH_GRID = 16
IMAGENET_MEAN = np.array(
    [
        0.485,
        0.456,
        0.406,
    ],
    dtype=np.float32,
)
IMAGENET_STD = np.array(
    [
        0.229,
        0.224,
        0.225,
    ],
    dtype=np.float32,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--package-dir",
        required=True,
    )
    parser.add_argument(
        "--output-dir",
        required=True,
    )
    parser.add_argument(
        "--result-zip",
        required=True,
    )
    parser.add_argument(
        "--dinov2-repo",
        required=True,
    )
    parser.add_argument(
        "--checkpoint",
        required=True,
    )
    parser.add_argument(
        "--batch-pairs",
        type=int,
        default=2,
    )
    return parser.parse_args()


def read_manifest(
    path: Path,
) -> list[dict[str, str]]:
    with path.open(
        encoding="utf-8-sig",
        newline="",
    ) as file:
        return list(
            csv.DictReader(
                file
            )
        )


def matrix_from_row(
    row: dict[str, str],
) -> np.ndarray:
    return np.array(
        [
            [
                float(
                    row[
                        f"h{matrix_row}{matrix_column}"
                    ]
                )
                for matrix_column in range(3)
            ]
            for matrix_row in range(3)
        ],
        dtype=np.float64,
    )


def load_checkpoint_state(
    checkpoint_path: Path,
) -> dict[str, torch.Tensor]:
    checkpoint = torch.load(
        checkpoint_path,
        map_location="cpu",
        weights_only=False,
    )

    candidates: list[Any] = [
        checkpoint
    ]

    if isinstance(
        checkpoint,
        dict,
    ):
        for key in (
            "teacher",
            "model",
            "state_dict",
            "student",
        ):
            if key in checkpoint:
                candidates.append(
                    checkpoint[key]
                )

    state: dict[str, Any] | None = None

    for candidate in candidates:
        if (
            isinstance(
                candidate,
                dict,
            )
            and candidate
            and all(
                isinstance(
                    key,
                    str,
                )
                for key in candidate
            )
        ):
            tensor_count = sum(
                isinstance(
                    value,
                    torch.Tensor,
                )
                for value in candidate.values()
            )

            if tensor_count > 10:
                state = candidate
                break

    if state is None:
        raise RuntimeError(
            "No tensor state dictionary was found in the checkpoint."
        )

    prefixes = (
        "module.",
        "teacher.",
        "student.",
        "backbone.",
    )
    cleaned: dict[
        str,
        torch.Tensor,
    ] = {}

    for key, value in state.items():
        if not isinstance(
            value,
            torch.Tensor,
        ):
            continue

        cleaned_key = key
        changed = True

        while changed:
            changed = False

            for prefix in prefixes:
                if cleaned_key.startswith(
                    prefix
                ):
                    cleaned_key = cleaned_key[
                        len(prefix):
                    ]
                    changed = True

        cleaned[
            cleaned_key
        ] = value

    return cleaned


def load_model(
    repo: Path,
    checkpoint: Path,
    device: torch.device,
) -> torch.nn.Module:
    started = time.perf_counter()
    model = torch.hub.load(
        str(
            repo
        ),
        "dinov2_vits14",
        source="local",
        pretrained=False,
    )
    state = load_checkpoint_state(
        checkpoint
    )
    incompatibility = model.load_state_dict(
        state,
        strict=False,
    )

    total_model_keys = len(
        model.state_dict()
    )
    missing_ratio = (
        len(
            incompatibility.missing_keys
        )
        / max(
            total_model_keys,
            1,
        )
    )

    if missing_ratio > 0.15:
        raise RuntimeError(
            "Checkpoint did not match DINOv2 ViT-S/14. "
            f"Missing key ratio: {missing_ratio:.2%}"
        )

    model.eval()
    model.to(
        device
    )
    model.half()

    return model, (
        time.perf_counter()
        - started
    )


def read_pair(
    package_dir: Path,
    row: dict[str, str],
) -> dict[str, Any]:
    baseline_path = (
        package_dir
        / row["baseline_file"]
    )
    inspection_path = (
        package_dir
        / row["inspection_file"]
    )
    baseline = cv2.imread(
        str(
            baseline_path
        ),
        cv2.IMREAD_COLOR,
    )
    inspection = cv2.imread(
        str(
            inspection_path
        ),
        cv2.IMREAD_COLOR,
    )

    if (
        baseline is None
        or inspection is None
    ):
        raise RuntimeError(
            f"Could not read pair {row['pair_id']}"
        )

    homography = matrix_from_row(
        row
    )
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

    # Remove unstable warp boundaries before semantic scoring.
    kernel_size = max(
        5,
        int(
            round(
                min(
                    inspection_height,
                    inspection_width,
                )
                * 0.012
            )
        ),
    )
    if kernel_size % 2 == 0:
        kernel_size += 1
    kernel = np.ones(
        (
            kernel_size,
            kernel_size,
        ),
        dtype=np.uint8,
    )
    eroded_mask = cv2.erode(
        overlap_mask,
        kernel,
        iterations=1,
    )

    return {
        "row": row,
        "baseline": baseline,
        "inspection": inspection,
        "warped": warped,
        "mask": eroded_mask,
    }


def to_tensor(
    image: np.ndarray,
) -> torch.Tensor:
    rgb = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2RGB,
    )
    resized = cv2.resize(
        rgb,
        (
            IMAGE_SIZE,
            IMAGE_SIZE,
        ),
        interpolation=cv2.INTER_AREA,
    ).astype(
        np.float32
    ) / 255.0
    normalized = (
        resized
        - IMAGENET_MEAN
    ) / IMAGENET_STD
    tensor = torch.from_numpy(
        normalized.transpose(
            2,
            0,
            1,
        )
    )
    return tensor


def extract_patch_tokens(
    model: torch.nn.Module,
    batch: torch.Tensor,
) -> torch.Tensor:
    features = model.forward_features(
        batch
    )

    if isinstance(
        features,
        dict,
    ):
        for key in (
            "x_norm_patchtokens",
            "x_prenorm",
            "x_patchtokens",
        ):
            if key in features:
                tokens = features[
                    key
                ]
                break
        else:
            raise RuntimeError(
                "DINOv2 patch tokens were not found."
            )
    else:
        tokens = features

    if tokens.ndim != 3:
        raise RuntimeError(
            f"Unexpected token shape: {tuple(tokens.shape)}"
        )

    if tokens.shape[1] == (
        PATCH_GRID
        * PATCH_GRID
        + 1
    ):
        tokens = tokens[
            :,
            1:,
            :
        ]

    if tokens.shape[1] != (
        PATCH_GRID
        * PATCH_GRID
    ):
        raise RuntimeError(
            f"Expected 256 patch tokens, got {tokens.shape[1]}"
        )

    return torch.nn.functional.normalize(
        tokens.float(),
        dim=-1,
    )


def valid_patch_mask(
    mask: np.ndarray,
) -> np.ndarray:
    resized = cv2.resize(
        mask,
        (
            PATCH_GRID,
            PATCH_GRID,
        ),
        interpolation=cv2.INTER_AREA,
    )
    return resized > 180


def percentile(
    values: np.ndarray,
    value: float,
) -> float:
    return float(
        np.percentile(
            values,
            value,
        )
    )


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


def label(
    image: np.ndarray,
    text: str,
) -> np.ndarray:
    output = image.copy()
    cv2.rectangle(
        output,
        (
            0,
            0,
        ),
        (
            output.shape[1],
            48,
        ),
        (
            0,
            0,
            0,
        ),
        -1,
    )
    cv2.putText(
        output,
        text,
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


def save_visuals(
    pair: dict[str, Any],
    score_grid: np.ndarray,
    output_dir: Path,
) -> tuple[str, str, str]:
    row = pair["row"]
    frame_number = int(
        row[
            "inspection_frame_number"
        ]
    )
    inspection = pair[
        "inspection"
    ]
    warped = pair[
        "warped"
    ]
    mask = pair[
        "mask"
    ]
    inspection_height, inspection_width = (
        inspection.shape[:2]
    )
    score_resized = cv2.resize(
        score_grid.astype(
            np.float32
        ),
        (
            inspection_width,
            inspection_height,
        ),
        interpolation=cv2.INTER_CUBIC,
    )
    valid = mask > 0
    valid_scores = score_resized[
        valid
    ]

    if valid_scores.size:
        low = float(
            np.percentile(
                valid_scores,
                5,
            )
        )
        high = float(
            np.percentile(
                valid_scores,
                99,
            )
        )
    else:
        low = 0.0
        high = 1.0

    normalized = np.zeros_like(
        score_resized,
        dtype=np.uint8,
    )

    if high > low:
        scaled = (
            (
                score_resized
                - low
            )
            / (
                high
                - low
            )
        )
        normalized = np.clip(
            scaled
            * 255.0,
            0,
            255,
        ).astype(
            np.uint8
        )

    normalized[
        ~valid
    ] = 0
    heatmap = cv2.applyColorMap(
        normalized,
        cv2.COLORMAP_TURBO,
    )
    heatmap[
        ~valid
    ] = 0
    overlay = inspection.copy()
    overlay[
        valid
    ] = cv2.addWeighted(
        inspection,
        0.62,
        heatmap,
        0.38,
        0.0,
    )[
        valid
    ]

    heatmap_dir = (
        output_dir
        / "heatmaps"
    )
    overlay_dir = (
        output_dir
        / "overlays"
    )
    montage_dir = (
        output_dir
        / "montages"
    )

    for directory in (
        heatmap_dir,
        overlay_dir,
        montage_dir,
    ):
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    heatmap_path = (
        heatmap_dir
        / f"frame_{frame_number:06d}_heatmap.jpg"
    )
    overlay_path = (
        overlay_dir
        / f"frame_{frame_number:06d}_overlay.jpg"
    )
    montage_path = (
        montage_dir
        / f"frame_{frame_number:06d}_montage.jpg"
    )
    cv2.imwrite(
        str(
            heatmap_path
        ),
        heatmap,
    )
    cv2.imwrite(
        str(
            overlay_path
        ),
        overlay,
    )
    montage = np.vstack(
        [
            np.hstack(
                [
                    fit_to_cell(
                        label(
                            pair[
                                "baseline"
                            ],
                            "Baseline",
                        )
                    ),
                    fit_to_cell(
                        label(
                            inspection,
                            "Inspection",
                        )
                    ),
                ]
            ),
            np.hstack(
                [
                    fit_to_cell(
                        label(
                            warped,
                            "Warped baseline",
                        )
                    ),
                    fit_to_cell(
                        label(
                            overlay,
                            "DINOv2 semantic change",
                        )
                    ),
                ]
            ),
        ]
    )
    cv2.imwrite(
        str(
            montage_path
        ),
        montage,
        [
            int(
                cv2.IMWRITE_JPEG_QUALITY
            ),
            92,
        ],
    )

    return (
        heatmap_path
        .relative_to(
            output_dir
        )
        .as_posix(),
        overlay_path
        .relative_to(
            output_dir
        )
        .as_posix(),
        montage_path
        .relative_to(
            output_dir
        )
        .as_posix(),
    )


def main() -> None:
    args = parse_args()
    package_dir = Path(
        args.package_dir
    ).resolve()
    output_dir = Path(
        args.output_dir
    ).resolve()
    result_zip = Path(
        args.result_zip
    ).resolve()
    repo = Path(
        args.dinov2_repo
    ).resolve()
    checkpoint = Path(
        args.checkpoint
    ).resolve()
    batch_pairs = max(
        1,
        int(
            args.batch_pairs
        ),
    )

    manifest_path = (
        package_dir
        / "manifest.csv"
    )

    for required in (
        manifest_path,
        repo,
        checkpoint,
    ):
        if not required.exists():
            raise RuntimeError(
                f"Required path not found: {required}"
            )

    if not torch.cuda.is_available():
        raise RuntimeError(
            "ROCm GPU is not available through torch.cuda."
        )

    device = torch.device(
        "cuda"
    )
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    rows = read_manifest(
        manifest_path
    )
    pairs = [
        read_pair(
            package_dir,
            row,
        )
        for row in rows
    ]

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    model, model_load_seconds = load_model(
        repo,
        checkpoint,
        device,
    )

    # Warmup with the first pair.
    warmup_images = torch.stack(
        [
            to_tensor(
                pairs[0][
                    "warped"
                ]
            ),
            to_tensor(
                pairs[0][
                    "inspection"
                ]
            ),
        ]
    ).to(
        device=device,
        dtype=torch.float16,
    )

    with torch.inference_mode():
        for _ in range(2):
            _ = extract_patch_tokens(
                model,
                warmup_images,
            )

    torch.cuda.synchronize()
    inference_seconds = 0.0
    results: list[
        dict[str, Any]
    ] = []

    for batch_start in range(
        0,
        len(pairs),
        batch_pairs,
    ):
        batch_items = pairs[
            batch_start:
            batch_start
            + batch_pairs
        ]
        tensors: list[
            torch.Tensor
        ] = []

        for pair in batch_items:
            tensors.extend(
                [
                    to_tensor(
                        pair[
                            "warped"
                        ]
                    ),
                    to_tensor(
                        pair[
                            "inspection"
                        ]
                    ),
                ]
            )

        batch = torch.stack(
            tensors
        ).to(
            device=device,
            dtype=torch.float16,
        )
        torch.cuda.synchronize()
        started = time.perf_counter()

        with torch.inference_mode():
            tokens = extract_patch_tokens(
                model,
                batch,
            )

        torch.cuda.synchronize()
        inference_seconds += (
            time.perf_counter()
            - started
        )

        for pair_index, pair in enumerate(
            batch_items
        ):
            baseline_tokens = tokens[
                pair_index
                * 2
            ]
            inspection_tokens = tokens[
                pair_index
                * 2
                + 1
            ]
            distances = (
                1.0
                - (
                    baseline_tokens
                    * inspection_tokens
                ).sum(
                    dim=-1
                )
            ).detach().cpu().numpy()
            score_grid = distances.reshape(
                PATCH_GRID,
                PATCH_GRID,
            )
            patch_mask = valid_patch_mask(
                pair[
                    "mask"
                ]
            )
            valid_scores = score_grid[
                patch_mask
            ]

            if valid_scores.size < 8:
                valid_scores = score_grid.reshape(
                    -1
                )

            heatmap_file, overlay_file, montage_file = (
                save_visuals(
                    pair,
                    score_grid,
                    output_dir,
                )
            )
            source_row = pair[
                "row"
            ]
            results.append(
                {
                    "pair_id": source_row[
                        "pair_id"
                    ],
                    "inspection_frame_number": int(
                        source_row[
                            "inspection_frame_number"
                        ]
                    ),
                    "selection_reason": source_row[
                        "selection_reason"
                    ],
                    "quality": source_row[
                        "quality"
                    ],
                    "baseline_name": source_row[
                        "baseline_name"
                    ],
                    "inspection_name": source_row[
                        "inspection_name"
                    ],
                    "score_mean": float(
                        np.mean(
                            valid_scores
                        )
                    ),
                    "score_p50": percentile(
                        valid_scores,
                        50,
                    ),
                    "score_p95": percentile(
                        valid_scores,
                        95,
                    ),
                    "score_p99": percentile(
                        valid_scores,
                        99,
                    ),
                    "score_max": float(
                        np.max(
                            valid_scores
                        )
                    ),
                    "valid_patch_count": int(
                        valid_scores.size
                    ),
                    "heatmap_file": heatmap_file,
                    "overlay_file": overlay_file,
                    "montage_file": montage_file,
                }
            )

        print(
            f"[{min(batch_start + batch_pairs, len(pairs)):02d}/"
            f"{len(pairs):02d}] inference complete",
            flush=True,
        )

    results.sort(
        key=lambda row: row[
            "score_p95"
        ],
        reverse=True,
    )
    scores_path = (
        output_dir
        / "scores.csv"
    )

    with scores_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as scores_file:
        writer = csv.DictWriter(
            scores_file,
            fieldnames=list(
                results[0].keys()
            ),
        )
        writer.writeheader()
        writer.writerows(
            results
        )

    peak_memory_mb = (
        torch.cuda.max_memory_allocated()
        / 1024
        / 1024
    )
    mean_ms_per_pair = (
        inference_seconds
        * 1000.0
        / len(
            results
        )
    )
    pairs_per_second = (
        len(
            results
        )
        / inference_seconds
        if inference_seconds > 0
        else 0.0
    )
    device_name = (
        torch.cuda.get_device_name(
            0
        )
    )
    benchmark = {
        "completed_at": now_iso(),
        "device_name": device_name,
        "torch_version": torch.__version__,
        "hip_version": getattr(
            torch.version,
            "hip",
            None,
        ),
        "batch_pairs": batch_pairs,
        "analyzed_pairs": len(
            results
        ),
        "model_load_seconds": round(
            model_load_seconds,
            4,
        ),
        "total_inference_seconds": round(
            inference_seconds,
            6,
        ),
        "mean_ms_per_pair": round(
            mean_ms_per_pair,
            3,
        ),
        "pairs_per_second": round(
            pairs_per_second,
            3,
        ),
        "peak_gpu_memory_mb": round(
            peak_memory_mb,
            2,
        ),
        "scope_note": (
            "Inference timing covers DINOv2 forward passes and GPU "
            "synchronization. It excludes image decoding, homography "
            "warping, visualization, SSH transfer, and model loading."
        ),
    }
    benchmark_path = (
        output_dir
        / "amd_benchmark.json"
    )
    benchmark_path.write_text(
        json.dumps(
            benchmark,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    run_summary = {
        "status": "completed",
        "completed_at": now_iso(),
        "model": "DINOv2 ViT-S/14",
        "method": (
            "Patch-token cosine distance after full-resolution "
            "homography warping and overlap-boundary erosion."
        ),
        "score_note": (
            "Heatmaps are normalized per pair for visualization. "
            "Raw scores rank semantic visual change and are not "
            "calibrated anomaly or defect probabilities."
        ),
        "analyzed_pairs": len(
            results
        ),
        "ranking": [
            {
                "inspection_frame_number": row[
                    "inspection_frame_number"
                ],
                "selection_reason": row[
                    "selection_reason"
                ],
                "quality": row[
                    "quality"
                ],
                "score_p95": row[
                    "score_p95"
                ],
                "score_p99": row[
                    "score_p99"
                ],
                "montage_file": row[
                    "montage_file"
                ],
            }
            for row in results
        ],
        "outputs": {
            "scores_csv": "scores.csv",
            "benchmark_json": "amd_benchmark.json",
            "montages": "montages",
            "heatmaps": "heatmaps",
            "overlays": "overlays",
        },
    }
    run_summary_path = (
        output_dir
        / "run_summary.json"
    )
    run_summary_path.write_text(
        json.dumps(
            run_summary,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    if result_zip.exists():
        result_zip.unlink()

    result_zip.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with zipfile.ZipFile(
        result_zip,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for source in sorted(
            output_dir.rglob(
                "*"
            )
        ):
            if source.is_file():
                archive.write(
                    source,
                    source.relative_to(
                        output_dir
                    ).as_posix(),
                )

    print(
        "[PASS] AMD DINOv2 ANALYSIS COMPLETED"
    )
    print(
        f"Device             : {device_name}"
    )
    print(
        f"Pairs              : {len(results)}"
    )
    print(
        f"Mean ms / pair     : {mean_ms_per_pair:.3f}"
    )
    print(
        f"Pairs / second     : {pairs_per_second:.3f}"
    )
    print(
        f"Peak GPU memory MB : {peak_memory_mb:.2f}"
    )
    print(
        f"Result archive     : {result_zip}"
    )


if __name__ == "__main__":
    main()
