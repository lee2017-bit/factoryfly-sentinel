from __future__ import annotations

import base64
import csv
import html
import io
import json
import math
import mimetypes
import re
import zipfile
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image


# ---------------------------------------------------------------------
# Project configuration
# ---------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
BASELINE_PARENT = PROJECT_ROOT / "baseline"
INSPECTION_PARENT = PROJECT_ROOT
CONFIG_ROOT = PROJECT_ROOT / "shared" / "config"
ACTIVE_BASELINE_PATH = CONFIG_ROOT / "active_baseline.json"

BASELINE_SCRIPT = (
    PROJECT_ROOT
    / "shared"
    / "scripts"
    / "run_baseline_pipeline.ps1"
)
INSPECTION_REGISTRATION_SCRIPT = (
    PROJECT_ROOT
    / "shared"
    / "scripts"
    / "register_inspection_inputs.ps1"
)
LOCALIZATION_SCRIPT = (
    PROJECT_ROOT
    / "shared"
    / "scripts"
    / "run_inspection_localization.ps1"
)
LOCALIZATION_ANALYZER_SCRIPT = (
    PROJECT_ROOT
    / "shared"
    / "scripts"
    / "analyze_colmap_registration.py"
)
PAIR_REFINEMENT_SCRIPT = (
    PROJECT_ROOT
    / "shared"
    / "scripts"
    / "run_pair_refinement.ps1"
)
POSE_CANDIDATE_SCRIPT = (
    PROJECT_ROOT
    / "shared"
    / "scripts"
    / "generate_pose_candidates.py"
)
GEOMETRIC_REFINEMENT_SCRIPT = (
    PROJECT_ROOT
    / "shared"
    / "scripts"
    / "refine_pose_pairs.py"
)
AMD_ANALYSIS_SCRIPT = (
    PROJECT_ROOT
    / "shared"
    / "scripts"
    / "run_amd_analysis.ps1"
)
AMD_PACKAGE_SCRIPT = (
    PROJECT_ROOT
    / "shared"
    / "scripts"
    / "prepare_amd_package.py"
)
AMD_REMOTE_SCRIPT = (
    PROJECT_ROOT
    / "shared"
    / "scripts"
    / "run_amd_dino_analysis.py"
)
REINSPECTION_PACKAGE_SCRIPT = (
    PROJECT_ROOT
    / "shared"
    / "scripts"
    / "prepare_reinspection_package.py"
)
REINSPECTION_ANALYSIS_SCRIPT = (
    PROJECT_ROOT
    / "shared"
    / "scripts"
    / "run_reinspection_analysis.ps1"
)
AMD_CONFIG_PATH = (
    PROJECT_ROOT
    / "shared"
    / "config"
    / "amd_cloud.json"
)
CURRENT_DEMO_RUN_PATH = (
    PROJECT_ROOT
    / "shared"
    / "config"
    / "current_demo_run.json"
)
DEMO_ARCHIVE_ROOT = (
    PROJECT_ROOT
    / "_archive"
    / "demo_runs"
)
APP_VERSION = "7.3.13"

DEFAULT_BASELINE_ID = "baseline_demo_001"
DEFAULT_BASELINE_VIDEO = str(
    PROJECT_ROOT / "sample_data" / "raw" / "baseline.mp4"
)
DEFAULT_INSPECTION_ID = "inspection_001"
DEFAULT_INSPECTION_VIDEO = str(
    PROJECT_ROOT / "sample_data" / "raw" / "inspection.mp4"
)
DEFAULT_INSPECTION_TELEMETRY = str(
    PROJECT_ROOT / "sample_data" / "raw" / "inspection_telemetry.txt"
)


STATE_SCHEMA_VERSION = 17
CONTEXT_VERSION = 4

STEP_NAMES = {
    1: "Baseline",
    2: "Spatial Memory",
    3: "Inspection",
    4: "Localization",
    5: "Localization Result",
    6: "Pair Refinement",
    7: "Pair Result",
    8: "AMD Analysis",
    9: "AMD Result",
    10: "Change Triage",
    11: "Reinspection Mission",
    12: "Reinspection Analysis",
    13: "Final Report",
}

STEP_TITLES = {
    1: "Baseline Registration",
    2: "Baseline Spatial Memory",
    3: "Inspection Registration",
    4: "Spatial Localization",
    5: "Localization Result",
    6: "Comparable View Refinement",
    7: "Refined Pair Result",
    8: "AMD Semantic Change Analysis",
    9: "AMD Analysis Result",
    10: "Automatic Change Triage",
    11: "Evidence-Directed Reinspection Missions",
    12: "Targeted Reinspection Analysis",
    13: "Evidence-Linked Change Report",
}

INVALID_WINDOWS_NAME = re.compile(r'[\\/:*?"<>|]')


# ---------------------------------------------------------------------
# File and process helpers
# ---------------------------------------------------------------------
def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}

    try:
        return json.loads(
            path.read_text(
                encoding="utf-8-sig"
            )
        )
    except (OSError, json.JSONDecodeError):
        return {}


def baseline_root_for(
    baseline_id: str,
) -> Path:
    return BASELINE_PARENT / baseline_id


def summary_path_for(
    baseline_id: str,
) -> Path:
    return (
        baseline_root_for(baseline_id)
        / "reports"
        / "baseline_summary.json"
    )


def load_baseline_summary(
    baseline_id: str,
) -> dict[str, Any]:
    return read_json(
        summary_path_for(baseline_id)
    )


def baseline_is_ready(
    summary: dict[str, Any],
) -> bool:
    try:
        registered_frames = int(
            summary.get(
                "registered_frames",
                0,
            )
            or 0
        )
    except (TypeError, ValueError):
        registered_frames = 0

    return (
        summary.get("status") == "ready"
        and registered_frames > 0
    )


def run_process(
    command: list[str],
    working_directory: Path,
) -> int:
    output_area = st.empty()
    output_lines: list[str] = []

    process = subprocess.Popen(
        command,
        cwd=str(working_directory),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    if process.stdout is None:
        raise RuntimeError(
            "Process output could not be opened."
        )

    for line in process.stdout:
        output_lines.append(
            line.rstrip()
        )

        output_area.code(
            "\n".join(
                output_lines[-80:]
            ),
            language="text",
        )

    return_code = process.wait()

    output_area.code(
        "\n".join(
            output_lines[-150:]
        ),
        language="text",
    )

    return return_code


def save_uploaded_file(
    uploaded_file: Any,
    output_directory: Path,
) -> Path:
    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    filename = Path(
        uploaded_file.name
    ).name
    output_path = output_directory / filename

    with output_path.open("wb") as output_file:
        shutil.copyfileobj(
            uploaded_file,
            output_file,
        )

    return output_path


def save_uploaded_video(
    uploaded_file: Any,
    baseline_root: Path,
) -> Path:
    return save_uploaded_file(
        uploaded_file,
        baseline_root / "video",
    )


def inspection_root_for(
    inspection_id: str,
) -> Path:
    return INSPECTION_PARENT / inspection_id


def inspection_manifest_path_for(
    inspection_id: str,
) -> Path:
    return (
        inspection_root_for(inspection_id)
        / "input_manifest.json"
    )


def load_inspection_manifest(
    inspection_id: str,
) -> dict[str, Any]:
    return read_json(
        inspection_manifest_path_for(inspection_id)
    )


def inspection_is_ready(
    manifest: dict[str, Any],
    baseline_id: str,
) -> bool:
    if not manifest:
        return False

    if manifest.get("status") != "ready_for_processing":
        return False

    if str(manifest.get("baseline_id", "")) != baseline_id:
        return False

    video = manifest.get("video") or {}
    telemetry = manifest.get("telemetry") or {}

    return (
        bool(video.get("full_path"))
        and bool(telemetry.get("full_path"))
    )


def localization_root_for(
    inspection_id: str,
    baseline_id: str,
) -> Path:
    return (
        inspection_root_for(inspection_id)
        / "localization"
        / baseline_id
    )


def localization_summary_path_for(
    inspection_id: str,
    baseline_id: str,
) -> Path:
    return (
        localization_root_for(
            inspection_id,
            baseline_id,
        )
        / "reports"
        / "localization_summary.json"
    )


def load_localization_summary(
    inspection_id: str,
    baseline_id: str,
) -> dict[str, Any]:
    return read_json(
        localization_summary_path_for(
            inspection_id,
            baseline_id,
        )
    )


def localization_is_ready(
    summary: dict[str, Any],
    inspection_id: str,
    baseline_id: str,
) -> bool:
    if not summary:
        return False

    try:
        registered_frames = int(
            summary.get(
                "registered_frames",
                0,
            )
            or 0
        )
    except (TypeError, ValueError):
        registered_frames = 0

    return (
        summary.get("status") == "ready"
        and summary.get("inspection_id") == inspection_id
        and summary.get("baseline_id") == baseline_id
        and registered_frames > 0
    )


def pair_refinement_root_for(
    inspection_id: str,
    baseline_id: str,
) -> Path:
    return (
        inspection_root_for(inspection_id)
        / "change_detection"
        / baseline_id
        / "pair_refinement"
    )


def pair_refinement_summary_path_for(
    inspection_id: str,
    baseline_id: str,
) -> Path:
    return (
        pair_refinement_root_for(
            inspection_id,
            baseline_id,
        )
        / "refinement_summary.json"
    )


def load_pair_refinement_summary(
    inspection_id: str,
    baseline_id: str,
) -> dict[str, Any]:
    return read_json(
        pair_refinement_summary_path_for(
            inspection_id,
            baseline_id,
        )
    )


def pair_refinement_is_ready(
    summary: dict[str, Any],
    inspection_id: str,
    baseline_id: str,
) -> bool:
    if not summary:
        return False

    try:
        inspection_frames = int(
            summary.get(
                "inspection_frames",
                0,
            )
            or 0
        )
        evaluated_candidates = int(
            summary.get(
                "evaluated_candidates",
                0,
            )
            or 0
        )
    except (TypeError, ValueError):
        return False

    return (
        summary.get("status") == "ready"
        and summary.get("inspection_id") == inspection_id
        and summary.get("baseline_id") == baseline_id
        and inspection_frames > 0
        and evaluated_candidates > 0
    )


def amd_analysis_root_for(
    inspection_id: str,
    baseline_id: str,
) -> Path:
    return (
        inspection_root_for(inspection_id)
        / "change_detection"
        / baseline_id
        / "amd_analysis"
        / "current"
    )


def amd_preview_root_for(
    inspection_id: str,
    baseline_id: str,
) -> Path:
    return (
        inspection_root_for(inspection_id)
        / "change_detection"
        / baseline_id
        / "amd_analysis"
        / "preview"
    )


def amd_run_summary_path_for(
    inspection_id: str,
    baseline_id: str,
) -> Path:
    return (
        amd_analysis_root_for(
            inspection_id,
            baseline_id,
        )
        / "amd_run_summary.json"
    )


def load_amd_run_summary(
    inspection_id: str,
    baseline_id: str,
) -> dict[str, Any]:
    return read_json(
        amd_run_summary_path_for(
            inspection_id,
            baseline_id,
        )
    )


def amd_analysis_is_ready(
    summary: dict[str, Any],
    inspection_id: str,
    baseline_id: str,
) -> bool:
    if not summary:
        return False

    try:
        analyzed_pairs = int(
            summary.get(
                "analyzed_pairs",
                0,
            )
            or 0
        )
    except (TypeError, ValueError):
        analyzed_pairs = 0

    result_summary = Path(
        summary.get(
            "result_summary_path",
            "",
        )
    )

    return (
        summary.get("status") == "ready"
        and summary.get("inspection_id") == inspection_id
        and summary.get("baseline_id") == baseline_id
        and analyzed_pairs > 0
        and result_summary.is_file()
    )


def default_amd_config() -> dict[str, Any]:
    return {
        "execution_mode": "Run on Radeon Cloud via SSH",
        "manual_frames": "",
        "batch_pairs": 2,
        "host": "",
        "port": 22,
        "user": "root",
        "key_path": (
            str(
                Path.home()
                / ".ssh"
                / "factoryfly_amd"
            )
        ),
        "remote_root": (
            "/workspace/factoryfly-radeon"
        ),
        "remote_python": (
            "/workspace/factoryfly-radeon/"
            ".venv-rocm/bin/python"
        ),
        "dinov2_repo": (
            "/workspace/factoryfly-radeon/vendor/dinov2"
        ),
        "checkpoint": (
            "/workspace/factoryfly-radeon/vendor/checkpoints/"
            "dinov2_vits14_pretrain.pth"
        ),
    }


def load_amd_config() -> dict[str, Any]:
    config = default_amd_config()
    stored = read_json(
        AMD_CONFIG_PATH
    )

    if isinstance(
        stored,
        dict,
    ):
        config.update(
            {
                key: value
                for key, value in stored.items()
                if key in config
            }
        )

    return config


def save_amd_config(
    config: dict[str, Any],
) -> None:
    AMD_CONFIG_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    AMD_CONFIG_PATH.write_text(
        json.dumps(
            config,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def load_amd_config_into_session() -> None:
    """Reload the saved AMD Cloud settings into Streamlit widget state."""
    config = load_amd_config()
    config_state_map = {
        "execution_mode": "amd_execution_mode",
        "manual_frames": "amd_manual_frames",
        "batch_pairs": "amd_batch_pairs",
        "host": "amd_host",
        "port": "amd_port",
        "user": "amd_user",
        "key_path": "amd_key_path",
        "remote_root": "amd_remote_root",
        "remote_python": "amd_remote_python",
        "dinov2_repo": "amd_dinov2_repo",
        "checkpoint": "amd_checkpoint",
    }

    defaults = default_amd_config()
    for config_key, state_key in config_state_map.items():
        value = config.get(config_key, defaults[config_key])
        if value in {None, ""}:
            value = defaults[config_key]
        if config_key in {"port", "batch_pairs"}:
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = int(defaults[config_key])
        st.session_state[state_key] = value

    st.session_state["_amd_config_loaded_v13"] = True
    st.session_state["_flash"] = (
        "success",
        f"Reloaded Radeon Cloud settings from {AMD_CONFIG_PATH}",
    )


def workflow_root_for(
    inspection_id: str,
    baseline_id: str,
) -> Path:
    return (
        inspection_root_for(inspection_id)
        / "change_detection"
        / baseline_id
        / "decision_workflow"
    )


def triage_path_for(
    inspection_id: str,
    baseline_id: str,
) -> Path:
    return workflow_root_for(
        inspection_id,
        baseline_id,
    ) / "change_triage.json"


def missions_path_for(
    inspection_id: str,
    baseline_id: str,
) -> Path:
    return workflow_root_for(
        inspection_id,
        baseline_id,
    ) / "reinspection_missions.json"


def final_report_json_path_for(
    inspection_id: str,
    baseline_id: str,
) -> Path:
    return workflow_root_for(
        inspection_id,
        baseline_id,
    ) / "final_change_report.json"


def final_report_md_path_for(
    inspection_id: str,
    baseline_id: str,
) -> Path:
    return workflow_root_for(
        inspection_id,
        baseline_id,
    ) / "final_change_report.md"


def final_report_html_path_for(
    inspection_id: str,
    baseline_id: str,
) -> Path:
    return workflow_root_for(
        inspection_id,
        baseline_id,
    ) / "final_change_report.html"


def reinspection_root_for(
    inspection_id: str,
    baseline_id: str,
) -> Path:
    return (
        inspection_root_for(inspection_id)
        / "reinspection"
        / baseline_id
    )


def mission_root_for(
    inspection_id: str,
    baseline_id: str,
    mission_id: str,
) -> Path:
    return (
        reinspection_root_for(
            inspection_id,
            baseline_id,
        )
        / mission_id
    )


def reinspection_run_summary_path_for(
    inspection_id: str,
    baseline_id: str,
    mission_id: str,
) -> Path:
    return (
        mission_root_for(
            inspection_id,
            baseline_id,
            mission_id,
        )
        / "analysis"
        / "current"
        / "reinspection_run_summary.json"
    )


def write_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def load_score_rows(
    inspection_id: str,
    baseline_id: str,
) -> list[dict[str, str]]:
    amd_summary = load_amd_run_summary(
        inspection_id,
        baseline_id,
    )
    scores_path = Path(
        amd_summary.get(
            "scores_csv_path",
            "",
        )
    )
    if not scores_path.is_file():
        return []
    with scores_path.open(
        encoding="utf-8-sig",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def safe_int(
    value: Any,
    default: int = 0,
) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default



def parse_frame_number_list(
    value: Any,
) -> set[int]:
    """Parse a comma/semicolon/space separated frame-number list."""
    frames: set[int] = set()

    for token in re.split(
        r"[,;\s]+",
        str(value or "").strip(),
    ):
        if not token:
            continue
        try:
            frame_number = int(token)
        except (TypeError, ValueError):
            continue
        if frame_number >= 0:
            frames.add(frame_number)

    return frames


def format_frame_number_list(
    frames: set[int] | list[int] | tuple[int, ...],
) -> str:
    return ", ".join(
        str(frame_number)
        for frame_number in sorted(
            {
                int(frame_number)
                for frame_number in frames
                if int(frame_number) >= 0
            }
        )
    )


def load_refined_pair_rows(
    inspection_id: str,
    baseline_id: str,
) -> tuple[list[dict[str, str]], Path]:
    summary = load_pair_refinement_summary(
        inspection_id,
        baseline_id,
    )
    output_root = pair_refinement_root_for(
        inspection_id,
        baseline_id,
    )
    outputs = summary.get("outputs") or {}
    refined_pairs_path = Path(
        outputs.get(
            "refined_pairs",
            output_root / "refined_pairs.csv",
        )
    )

    if not refined_pairs_path.is_file():
        return [], refined_pairs_path

    try:
        with refined_pairs_path.open(
            encoding="utf-8-sig",
            newline="",
        ) as file:
            return list(csv.DictReader(file)), refined_pairs_path
    except OSError:
        return [], refined_pairs_path


def row_has_homography(
    row: dict[str, Any],
) -> bool:
    return all(
        str(
            row.get(
                f"h{matrix_row}{matrix_column}",
                "",
            )
        ).strip()
        for matrix_row in range(3)
        for matrix_column in range(3)
    )


def resolve_pair_image_path(
    row: dict[str, Any],
    explicit_key: str,
    name_key: str,
    search_roots: list[Path],
) -> Path | None:
    explicit_value = str(
        row.get(
            explicit_key,
            "",
        )
        or ""
    ).strip()
    if explicit_value:
        explicit_path = Path(explicit_value)
        if explicit_path.is_file():
            return explicit_path

    image_name = str(
        row.get(
            name_key,
            "",
        )
        or ""
    ).replace("\\", "/").strip()
    if not image_name:
        return None

    relative = Path(image_name)
    candidates: list[Path] = []
    for root in search_roots:
        candidates.extend(
            [
                root / relative,
                root / relative.name,
            ]
        )
        if image_name.startswith("inspection/"):
            candidates.append(
                root
                / image_name.split(
                    "/",
                    1,
                )[1]
            )

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


def render_borderline_pair_selector(
    inspection_id: str,
    baseline_id: str,
) -> set[int]:
    """Render visual cards for reviewer-selected poor-geometry pairs.

    The returned frames remain reviewer overrides. They are not promoted to
    geometry-ready status, and prepare_amd_package.py still requires a valid
    homography before including them in the AMD package.
    """
    rows, refined_pairs_path = load_refined_pair_rows(
        inspection_id,
        baseline_id,
    )
    selected_frames = parse_frame_number_list(
        st.session_state.get(
            "amd_manual_frames",
            "",
        )
    )

    if not rows:
        st.warning(
            "Refined-pair rows are unavailable. Use the advanced frame-number "
            f"fallback if needed. Expected: {refined_pairs_path}"
        )
        return selected_frames

    candidates = [
        row
        for row in rows
        if str(
            row.get(
                "quality",
                "poor",
            )
        ).strip().lower()
        == "poor"
        and row_has_homography(row)
    ]
    candidates.sort(
        key=lambda row: safe_float(
            row.get(
                "refinement_score"
            ),
            0.0,
        ),
        reverse=True,
    )

    if not candidates:
        st.success(
            "No poor-geometry pair with a valid homography is available for "
            "manual review. Geometry-ready pairs will be included automatically."
        )
        st.session_state.amd_manual_frames = ""
        return set()

    selector_context = (
        f"{inspection_id}::{baseline_id}"
    )
    canonical_text = format_frame_number_list(
        selected_frames
    )
    previous_context = st.session_state.get(
        "_amd_borderline_selector_context"
    )
    previous_seed = st.session_state.get(
        "_amd_borderline_selector_seed",
        "",
    )

    if (
        previous_context != selector_context
        or previous_seed != canonical_text
    ):
        for row in candidates:
            frame_number = safe_int(
                row.get(
                    "inspection_frame_number"
                ),
                -1,
            )
            if frame_number < 0:
                continue
            widget_key = (
                "amd_borderline_select_"
                f"{inspection_id}_{baseline_id}_{frame_number}"
            )
            st.session_state[widget_key] = (
                frame_number in selected_frames
            )
        st.session_state[
            "_amd_borderline_selector_context"
        ] = selector_context
        st.session_state[
            "_amd_borderline_selector_seed"
        ] = canonical_text

    st.markdown(
        "#### Visual Borderline Evidence Review"
    )
    st.caption(
        "Geometry-ready pairs are already automatic. The cards below are "
        "poor-geometry candidates that still contain a computed homography. "
        "Select one only when a reviewer intentionally wants additional "
        "evidence analyzed; selection does not make the pair geometrically reliable."
    )

    default_limit = min(
        12,
        len(candidates),
    )

    max_limit = min(
        30,
        len(candidates),
    )
    if max_limit <= 6:
        candidate_limit = max_limit
    else:
        candidate_limit = st.slider(
            "Candidates shown",
            min_value=6,
            max_value=max_limit,
            value=min(
                int(
                    st.session_state.get(
                        "amd_borderline_candidate_limit",
                        default_limit,
                    )
                ),
                max_limit,
            ),
            step=1,
            key="amd_borderline_candidate_limit",
            help=(
                "Candidates are ranked by refinement score. Previously selected "
                "frames remain visible even when outside this limit."
            ),
        )

    selected_candidate_rows = [
        row
        for row in candidates
        if safe_int(
            row.get(
                "inspection_frame_number"
            ),
            -1,
        )
        in selected_frames
    ]
    visible_by_frame: dict[int, dict[str, str]] = {}
    for row in candidates[:candidate_limit]:
        frame_number = safe_int(
            row.get(
                "inspection_frame_number"
            ),
            -1,
        )
        if frame_number >= 0:
            visible_by_frame[frame_number] = row
    for row in selected_candidate_rows:
        frame_number = safe_int(
            row.get(
                "inspection_frame_number"
            ),
            -1,
        )
        if frame_number >= 0:
            visible_by_frame[frame_number] = row

    visible_rows = sorted(
        visible_by_frame.values(),
        key=lambda row: safe_float(
            row.get(
                "refinement_score"
            ),
            0.0,
        ),
        reverse=True,
    )

    baseline_summary = load_baseline_summary(
        baseline_id
    )
    localization_summary = load_localization_summary(
        inspection_id,
        baseline_id,
    )
    baseline_roots = [
        Path(
            str(
                baseline_summary.get(
                    "frame_path",
                    "",
                )
            )
        ),
        baseline_root_for(
            baseline_id
        )
        / "frames"
        / "raw",
    ]
    inspection_roots = [
        Path(
            str(
                localization_summary.get(
                    "frame_path",
                    "",
                )
            )
        ),
        inspection_root_for(
            inspection_id
        )
        / "frames"
        / "raw",
    ]
    baseline_roots = [
        root
        for root in baseline_roots
        if str(root).strip() not in {"", "."}
    ]
    inspection_roots = [
        root
        for root in inspection_roots
        if str(root).strip() not in {"", "."}
    ]

    card_columns = st.columns(2)
    current_selected: set[int] = set()

    for index, row in enumerate(visible_rows):
        frame_number = safe_int(
            row.get(
                "inspection_frame_number"
            ),
            -1,
        )
        if frame_number < 0:
            continue
        widget_key = (
            "amd_borderline_select_"
            f"{inspection_id}_{baseline_id}_{frame_number}"
        )
        baseline_image = resolve_pair_image_path(
            row,
            "baseline_path",
            "baseline_name",
            baseline_roots,
        )
        inspection_image = resolve_pair_image_path(
            row,
            "inspection_path",
            "inspection_name",
            inspection_roots,
        )

        with card_columns[index % 2]:
            with st.container(border=True):
                is_selected = st.checkbox(
                    f"Include inspection frame {frame_number}",
                    key=widget_key,
                    help=(
                        "Adds this reviewer-selected frame to the AMD package only "
                        "when prepare_amd_package.py confirms that its homography is valid."
                    ),
                )
                if is_selected:
                    current_selected.add(frame_number)

                st.caption(
                    " · ".join(
                        [
                            f"Baseline {Path(str(row.get('baseline_name', ''))).name or 'unknown'}",
                            f"score {safe_float(row.get('refinement_score'), 0.0):.3f}",
                            f"matches {safe_int(row.get('mutual_matches'), 0)}",
                            f"overlap {safe_float(row.get('overlap_ratio'), 0.0):.3f}",
                            (
                                "reprojection "
                                f"{safe_float(row.get('median_reprojection_error'), 0.0):.2f}px"
                            ),
                        ]
                    )
                )

                image_left, image_right = st.columns(2)
                with image_left:
                    st.markdown("**Baseline**")
                    if baseline_image is not None:
                        st.image(
                            str(baseline_image),
                            use_container_width=True,
                        )
                    else:
                        st.info("Baseline preview unavailable")
                with image_right:
                    st.markdown("**Inspection**")
                    if inspection_image is not None:
                        st.image(
                            str(inspection_image),
                            use_container_width=True,
                        )
                    else:
                        st.info("Inspection preview unavailable")

    # Preserve manually entered frames that are not represented by a valid
    # visual candidate. prepare_amd_package.py will still reject frames without
    # a usable homography and report them as skipped_manual_frames.
    visual_candidate_frames = {
        safe_int(
            row.get(
                "inspection_frame_number"
            ),
            -1,
        )
        for row in candidates
    }
    fallback_only_frames = {
        frame_number
        for frame_number in selected_frames
        if frame_number not in visual_candidate_frames
    }
    current_selected.update(
        fallback_only_frames
    )

    canonical_text = format_frame_number_list(
        current_selected
    )
    st.session_state.amd_manual_frames = canonical_text
    st.session_state[
        "_amd_borderline_selector_seed"
    ] = canonical_text

    selected_label = (
        canonical_text
        if canonical_text
        else "None"
    )
    st.info(
        f"Reviewer-selected borderline frames: {selected_label}"
    )

    with st.expander(
        "Advanced: frame-number fallback",
        expanded=False,
    ):
        st.caption(
            "Use this only when an expected image card is unavailable. Invalid "
            "or homography-free frames are safely skipped by the package builder."
        )
        with st.form(
            key=(
                "amd_manual_frames_form_"
                f"{inspection_id}_{baseline_id}"
            )
        ):
            advanced_value = st.text_input(
                "Inspection frame numbers",
                value=canonical_text,
                placeholder="101, 124, 203",
            )
            apply_fallback = st.form_submit_button(
                "Apply frame-number fallback",
                use_container_width=True,
            )
        if apply_fallback:
            applied_frames = parse_frame_number_list(
                advanced_value
            )
            applied_text = format_frame_number_list(
                applied_frames
            )
            st.session_state.amd_manual_frames = applied_text
            st.session_state[
                "_amd_borderline_selector_seed"
            ] = "__force_resync__"
            st.rerun()

    return current_selected


def frame_context(
    frame_number: int,
    score_row: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Build a data-derived, non-semantic mission reference.

    DINOv2 provides change evidence, not an object class or room/zone name.
    The mission therefore points to the localized inspection frame and its
    matched baseline image without inventing a physical object label.
    """
    row = score_row or {}
    baseline_name = Path(str(row.get("baseline_name", ""))).name
    inspection_name = Path(str(row.get("inspection_name", ""))).name

    target_parts = [f"Localized inspection frame {frame_number}"]
    if baseline_name:
        target_parts.append(f"matched to baseline {baseline_name}")

    evidence_parts = [
        "Unresolved visual-change region highlighted by DINOv2"
    ]
    if inspection_name:
        evidence_parts.append(f"inspection image {inspection_name}")

    return {
        "target_area": " — ".join(target_parts),
        "suspected_object": "; ".join(evidence_parts),
        "context_source": "localization_and_change_evidence",
        "object_classification": "not_inferred",
    }


def _frame_index_from_name(value: Any) -> int | None:
    name = Path(str(value or "")).name
    match = re.search(r"(\d+)(?=\.[^.]+$)", name)
    return int(match.group(1)) if match else None


def _cluster_high_change_rows(
    rows: list[dict[str, Any]],
    uncertain_threshold: float,
    frame_gap: int = 4,
    baseline_gap: int = 4,
) -> list[list[dict[str, Any]]]:
    high_rows = [
        row for row in rows
        if safe_float(row.get("score_p95")) >= uncertain_threshold
    ]
    high_rows.sort(key=lambda row: safe_int(row.get("inspection_frame_number"), -1))
    if not high_rows:
        return []

    clusters: list[list[dict[str, Any]]] = []
    for row in high_rows:
        frame = safe_int(row.get("inspection_frame_number"), -1)
        baseline_frame = _frame_index_from_name(row.get("baseline_name"))
        placed = False
        for cluster in reversed(clusters):
            last = cluster[-1]
            last_frame = safe_int(last.get("inspection_frame_number"), -1)
            last_baseline = _frame_index_from_name(last.get("baseline_name"))
            close_in_time = abs(frame - last_frame) <= frame_gap
            close_in_space = (
                baseline_frame is not None
                and last_baseline is not None
                and abs(baseline_frame - last_baseline) <= baseline_gap
            )
            if close_in_time and (close_in_space or baseline_frame is None or last_baseline is None):
                cluster.append(row)
                placed = True
                break
        if not placed:
            clusters.append([row])
    return clusters


def _cluster_target_area(cluster: list[dict[str, Any]]) -> str:
    frames = sorted(safe_int(row.get("inspection_frame_number"), -1) for row in cluster)
    baseline_frames = sorted({
        value
        for value in (_frame_index_from_name(row.get("baseline_name")) for row in cluster)
        if value is not None
    })
    frame_text = str(frames[0]) if len(frames) == 1 else f"{frames[0]}–{frames[-1]}"
    target = f"Localized inspection evidence cluster {frame_text}"
    if baseline_frames:
        baseline_text = (
            str(baseline_frames[0])
            if len(baseline_frames) == 1
            else f"{baseline_frames[0]}–{baseline_frames[-1]}"
        )
        target += f" — matched near baseline frames {baseline_text}"
    return target


def build_change_triage(
    inspection_id: str,
    baseline_id: str,
    confirmed_threshold: float = 0.62,
    uncertain_threshold: float = 0.60,
) -> dict[str, Any]:
    rows = load_score_rows(inspection_id, baseline_id)
    if not rows:
        raise RuntimeError("AMD scores.csv was not found. Complete Step 8 first.")

    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append({
            **row,
            "frame_number": safe_int(row.get("inspection_frame_number"), -1),
            "score_p95_value": safe_float(row.get("score_p95")),
            "score_p99_value": safe_float(row.get("score_p99")),
            "quality_value": str(row.get("quality", "poor")).lower(),
        })

    clusters = _cluster_high_change_rows(normalized, uncertain_threshold)
    clustered_frames = {
        safe_int(row.get("inspection_frame_number"), -1)
        for cluster in clusters
        for row in cluster
    }

    confirmed: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []
    for cluster in clusters:
        geometry_supported = [
            row for row in cluster
            if str(row.get("quality", "poor")).lower() in {"excellent", "good", "usable"}
            and safe_float(row.get("score_p95")) >= confirmed_threshold
        ]
        representative = max(
            geometry_supported or cluster,
            key=lambda row: safe_float(row.get("score_p95")),
        )
        source_frames = sorted(safe_int(row.get("inspection_frame_number"), -1) for row in cluster)
        evidence_frames = [
            {
                "frame_number": safe_int(row.get("inspection_frame_number"), -1),
                "quality": str(row.get("quality", "poor")).lower(),
                "score_p95": safe_float(row.get("score_p95")),
                "score_p99": safe_float(row.get("score_p99")),
                "baseline_name": row.get("baseline_name"),
                "inspection_name": row.get("inspection_name"),
                "montage_file": row.get("montage_file"),
                "overlay_file": row.get("overlay_file"),
            }
            for row in sorted(cluster, key=lambda item: safe_int(item.get("inspection_frame_number"), -1))
        ]
        item = {
            "frame_number": safe_int(representative.get("inspection_frame_number"), -1),
            "representative_frame": safe_int(representative.get("inspection_frame_number"), -1),
            "source_frames": source_frames,
            "status": "confirmed_change" if geometry_supported else "uncertain_change",
            "reason": (
                "At least one nearby view provides high semantic-change evidence with usable geometry; "
                "poor-geometry views in the same localized cluster are supporting evidence and do not create a separate mission."
                if geometry_supported
                else "High semantic-change evidence remains unsupported by usable geometry across this localized cluster."
            ),
            "quality": str(representative.get("quality", "poor")).lower(),
            "score_p95": safe_float(representative.get("score_p95")),
            "score_p99": safe_float(representative.get("score_p99")),
            "selection_reason": representative.get("selection_reason"),
            "montage_file": representative.get("montage_file"),
            "overlay_file": representative.get("overlay_file"),
            "target_area": _cluster_target_area(cluster),
            "suspected_object": "Localized visual-change region highlighted by DINOv2; object class not inferred",
            "context_source": "localized_multi_view_change_evidence",
            "object_classification": "not_inferred",
            "baseline_name": representative.get("baseline_name"),
            "inspection_name": representative.get("inspection_name"),
            "evidence_frames": evidence_frames,
        }
        (confirmed if geometry_supported else uncertain).append(item)

    stable = []
    for row in normalized:
        frame = safe_int(row.get("inspection_frame_number"), -1)
        if frame in clustered_frames:
            continue
        stable.append({
            "frame_number": frame,
            "status": "no_material_change",
            "reason": "No sufficiently supported persistent change signal",
            "quality": str(row.get("quality", "poor")).lower(),
            "score_p95": safe_float(row.get("score_p95")),
            "score_p99": safe_float(row.get("score_p99")),
            "baseline_name": row.get("baseline_name"),
            "inspection_name": row.get("inspection_name"),
        })

    confirmed.sort(key=lambda item: item["score_p95"], reverse=True)
    uncertain.sort(key=lambda item: item["score_p95"], reverse=True)
    stable.sort(key=lambda item: item["score_p95"], reverse=True)

    payload = {
        "status": "ready",
        "context_version": CONTEXT_VERSION,
        "created_at": now_iso(),
        "inspection_id": inspection_id,
        "baseline_id": baseline_id,
        "method": (
            "Spatial-temporal evidence clustering followed by uncertainty routing. "
            "Nearby high-change frames are treated as one finding. If any view in the cluster "
            "has usable geometry, the cluster is recorded as confirmed visual change; only clusters "
            "without usable geometry are sent to targeted reinspection."
        ),
        "thresholds": {
            "confirmed_p95": confirmed_threshold,
            "uncertain_p95": uncertain_threshold,
            "inspection_frame_gap": 4,
            "baseline_frame_gap": 4,
        },
        "counts": {
            "analyzed": len(normalized),
            "confirmed_change": len(confirmed),
            "uncertain_change": len(uncertain),
            "no_material_change": len(stable),
            "high_change_pairs_grouped": len(clustered_frames),
        },
        "confirmed_changes": confirmed,
        "uncertain_changes": uncertain,
        "no_material_changes": stable,
    }
    write_json(triage_path_for(inspection_id, baseline_id), payload)
    return payload


def triage_is_ready(
    inspection_id: str,
    baseline_id: str,
) -> bool:
    payload = read_json(
        triage_path_for(
            inspection_id,
            baseline_id,
        )
    )
    return (
        payload.get("status") == "ready"
        and payload.get("inspection_id") == inspection_id
        and payload.get("baseline_id") == baseline_id
    )



def _pose_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []

    rows: list[dict[str, Any]] = []
    try:
        with path.open(
            encoding="utf-8-sig",
            newline="",
        ) as pose_file:
            for raw in csv.DictReader(pose_file):
                rows.append(
                    {
                        **raw,
                        "frame_number": safe_int(
                            raw.get("frame_number"),
                            -1,
                        ),
                        "camera_x": safe_float(raw.get("camera_x")),
                        "camera_y": safe_float(raw.get("camera_y")),
                        "camera_z": safe_float(raw.get("camera_z")),
                    }
                )
    except (OSError, csv.Error):
        return []

    return sorted(
        rows,
        key=lambda item: (
            safe_int(item.get("frame_number"), -1),
            str(item.get("name", "")),
        ),
    )


def _point_cloud_rows(
    baseline_id: str,
    max_points: int = 2400,
) -> list[list[float]]:
    points_path = (
        baseline_root_for(baseline_id)
        / "poses"
        / "points3D.txt"
    )
    if not points_path.is_file():
        return []

    points: list[list[float]] = []
    try:
        for raw_line in points_path.read_text(
            encoding="utf-8-sig",
            errors="ignore",
        ).splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            tokens = line.split()
            if len(tokens) < 4:
                continue
            try:
                points.append(
                    [
                        float(tokens[1]),
                        float(tokens[2]),
                        float(tokens[3]),
                    ]
                )
            except ValueError:
                continue
    except OSError:
        return []

    if len(points) <= max_points:
        return points

    step = max(1, math.ceil(len(points) / max_points))
    return points[::step][:max_points]


def _vector_norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def _unit_vector(
    vector: list[float],
    fallback: list[float],
) -> list[float]:
    length = _vector_norm(vector)
    if length <= 1e-9:
        return list(fallback)
    return [value / length for value in vector]


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _cross(left: list[float], right: list[float]) -> list[float]:
    return [
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    ]


def _pose_position(pose: dict[str, Any]) -> list[float]:
    return [
        safe_float(pose.get("camera_x")),
        safe_float(pose.get("camera_y")),
        safe_float(pose.get("camera_z")),
    ]


def _pose_basename(value: Any) -> str:
    normalized = str(value or "").replace("\\", "/")
    return normalized.rsplit("/", 1)[-1].lower()


def _frame_number_from_name(value: Any) -> int:
    match = re.search(
        r"(?:frame[_-]?)?(\d+)",
        _pose_basename(value),
        flags=re.IGNORECASE,
    )
    return safe_int(match.group(1), -1) if match else -1


def _find_target_pose(
    baseline_poses: list[dict[str, Any]],
    mission: dict[str, Any],
) -> dict[str, Any] | None:
    requested_name = _pose_basename(mission.get("baseline_name"))
    requested_frame = _frame_number_from_name(requested_name)

    if not requested_name:
        for evidence in mission.get("evidence_frames") or []:
            requested_name = _pose_basename(evidence.get("baseline_name"))
            requested_frame = _frame_number_from_name(requested_name)
            if requested_name:
                break

    for pose in baseline_poses:
        if requested_name and _pose_basename(pose.get("name")) == requested_name:
            return pose

    if requested_frame >= 0:
        for pose in baseline_poses:
            if safe_int(pose.get("frame_number"), -1) == requested_frame:
                return pose

    return None


def _median_value(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _camera_up_from_pose(
    pose: dict[str, Any],
) -> list[float] | None:
    quaternion = [
        safe_float(pose.get("qw")),
        safe_float(pose.get("qx")),
        safe_float(pose.get("qy")),
        safe_float(pose.get("qz")),
    ]
    quaternion_norm = _vector_norm(quaternion)
    if quaternion_norm <= 1e-9:
        return None

    qw, qx, qy, qz = [
        value / quaternion_norm
        for value in quaternion
    ]

    # COLMAP stores a world-to-camera rotation. Camera coordinates use
    # +Y downward, so world-space camera up is R^T * [0, -1, 0], which
    # is the negative second row of R.
    camera_up = [
        -2.0 * (qx * qy + qz * qw),
        -(1.0 - 2.0 * (qx * qx + qz * qz)),
        -2.0 * (qy * qz - qx * qw),
    ]
    return _unit_vector(camera_up, [0.0, 0.0, 1.0])


def _orientation_up_axis(
    baseline_poses: list[dict[str, Any]],
) -> tuple[list[float], str, float]:
    camera_up_vectors = [
        camera_up
        for pose in baseline_poses
        if (camera_up := _camera_up_from_pose(pose)) is not None
    ]
    if not camera_up_vectors:
        spans: list[float] = []
        for axis in range(3):
            values = [_pose_position(pose)[axis] for pose in baseline_poses]
            spans.append(max(values) - min(values) if values else 0.0)
        vertical_axis = min(range(3), key=lambda axis: spans[axis])
        fallback = [0.0, 0.0, 0.0]
        fallback[vertical_axis] = 1.0
        return fallback, "trajectory-span fallback", 0.0

    median_up = _unit_vector(
        [
            _median_value([vector[axis] for vector in camera_up_vectors])
            for axis in range(3)
        ],
        [0.0, 0.0, 1.0],
    )
    dominant_axis = max(
        range(3),
        key=lambda axis: abs(median_up[axis]),
    )
    confidence = abs(median_up[dominant_axis])

    # DJI/gimbal footage can contain a small camera pitch. When the camera-up
    # estimate is strongly aligned with one COLMAP source axis, snap to that
    # axis so the reconstructed floor is not tilted by the gimbal angle.
    if confidence >= 0.80:
        up = [0.0, 0.0, 0.0]
        up[dominant_axis] = 1.0 if median_up[dominant_axis] >= 0 else -1.0
        axis_name = ("X", "Y", "Z")[dominant_axis]
        sign = "+" if up[dominant_axis] > 0 else "-"
        return up, f"COLMAP camera orientation ({sign}{axis_name})", confidence

    return median_up, "COLMAP camera orientation (free axis)", confidence


def _pose_forward_vector(
    pose: dict[str, Any],
) -> list[float]:
    return [
        safe_float(pose.get("forward_x")),
        safe_float(pose.get("forward_y")),
        safe_float(pose.get("forward_z")),
    ]


def _project_onto_horizontal(
    vector: list[float],
    up: list[float],
) -> list[float]:
    vertical_component = _dot(vector, up)
    return [
        value - vertical_component * up_value
        for value, up_value in zip(vector, up)
    ]


def _spatial_basis(
    baseline_poses: list[dict[str, Any]],
    target_pose: dict[str, Any],
) -> dict[str, Any]:
    start_pose = baseline_poses[0]
    start = _pose_position(start_pose)
    target = _pose_position(target_pose)

    up, up_method, up_confidence = _orientation_up_axis(baseline_poses)

    horizontal_positions = [
        _project_onto_horizontal(
            [
                current - origin
                for current, origin in zip(_pose_position(pose), start)
            ],
            up,
        )
        for pose in baseline_poses
    ]
    horizontal_extent = max(
        [_vector_norm(position) for position in horizontal_positions]
        or [0.0]
    )
    movement_threshold = max(horizontal_extent * 0.03, 1e-3)

    forward_candidate: list[float] | None = None
    forward_reference = "first significant baseline displacement"
    for horizontal_delta in horizontal_positions[1:]:
        if _vector_norm(horizontal_delta) >= movement_threshold:
            forward_candidate = horizontal_delta
            break

    if forward_candidate is None:
        camera_forward = _project_onto_horizontal(
            _pose_forward_vector(start_pose),
            up,
        )
        if _vector_norm(camera_forward) > 1e-6:
            forward_candidate = camera_forward
            forward_reference = "baseline start camera direction"

    if forward_candidate is None:
        forward_candidate = _project_onto_horizontal(
            [
                current - origin
                for current, origin in zip(target, start)
            ],
            up,
        )
        forward_reference = "target displacement fallback"

    fallback_forward = [1.0, 0.0, 0.0]
    if abs(_dot(fallback_forward, up)) > 0.90:
        fallback_forward = [0.0, 0.0, 1.0]
    fallback_forward = _unit_vector(
        _project_onto_horizontal(fallback_forward, up),
        [0.0, 1.0, 0.0],
    )

    forward = _unit_vector(forward_candidate, fallback_forward)

    # Output coordinates are right-handed: X=Right, Y=Straight, Z=Up.
    # Therefore Right x Straight = Up and Right = Straight x Up.
    right = _unit_vector(
        _cross(forward, up),
        fallback_forward,
    )
    forward = _unit_vector(
        _cross(up, right),
        forward,
    )

    return {
        "start_pose": start_pose,
        "start": start,
        "target": target,
        "right": right,
        "forward": forward,
        "up": up,
        "up_method": up_method,
        "up_confidence": up_confidence,
        "forward_reference": forward_reference,
    }

def _to_start_relative(
    point: list[float],
    basis: dict[str, Any],
) -> list[float]:
    delta = [
        value - origin
        for value, origin in zip(point, basis["start"])
    ]
    return [
        _dot(delta, basis["right"]),
        _dot(delta, basis["forward"]),
        _dot(delta, basis["up"]),
    ]


def _relative_direction_label(
    right_value: float,
    forward_value: float,
    vertical_value: float,
) -> str:
    horizontal = math.hypot(right_value, forward_value)
    if horizontal <= 1e-6:
        horizontal_label = "Near the baseline start"
    else:
        angle = math.degrees(
            math.atan2(right_value, forward_value)
        )
        directions = [
            "Straight",
            "Straight-right",
            "Right",
            "Back-right",
            "Back",
            "Back-left",
            "Left",
            "Straight-left",
        ]
        index = int((angle + 22.5) // 45.0) % 8
        horizontal_label = directions[index]

    vertical_note = ""
    if abs(vertical_value) > max(horizontal * 0.25, 1e-6):
        vertical_note = " / Up" if vertical_value > 0 else " / Down"
    return horizontal_label + vertical_note


def build_spatial_mission_model(
    inspection_id: str,
    baseline_id: str,
    mission: dict[str, Any],
) -> dict[str, Any]:
    reports_root = (
        localization_root_for(inspection_id, baseline_id)
        / "reports"
    )
    baseline_path = reports_root / "baseline_poses.csv"
    inspection_path = reports_root / "inspection_poses.csv"
    baseline_poses = _pose_csv_rows(baseline_path)
    inspection_poses = _pose_csv_rows(inspection_path)

    if not baseline_poses:
        return {
            "status": "unavailable",
            "reason": f"Baseline pose file not found or empty: {baseline_path}",
        }

    target_pose = _find_target_pose(baseline_poses, mission)
    if target_pose is None:
        return {
            "status": "unavailable",
            "reason": (
                "The mission baseline reference could not be matched to "
                "baseline_poses.csv."
            ),
        }

    basis = _spatial_basis(baseline_poses, target_pose)
    baseline_trajectory = [
        _to_start_relative(_pose_position(pose), basis)
        for pose in baseline_poses
    ]
    inspection_trajectory = [
        _to_start_relative(_pose_position(pose), basis)
        for pose in inspection_poses
    ]
    structure_points = [
        _to_start_relative(point, basis)
        for point in _point_cloud_rows(baseline_id)
    ]
    target_relative = _to_start_relative(basis["target"], basis)

    return {
        "status": "ready",
        "coordinate_system": (
            "Right-handed baseline-start-relative coordinates: "
            "X=Right/Left, Y=Straight/Back, Z=Up/Down"
        ),
        "metric_scale_calibrated": False,
        "axis_estimation": {
            "up_method": basis.get("up_method"),
            "up_confidence": safe_float(basis.get("up_confidence")),
            "forward_reference": basis.get("forward_reference"),
            "source_up_vector": basis.get("up"),
        },
        "start_frame": safe_int(
            basis["start_pose"].get("frame_number"),
            -1,
        ),
        "start_name": str(basis["start_pose"].get("name", "")),
        "target_frame": safe_int(target_pose.get("frame_number"), -1),
        "target_name": str(target_pose.get("name", "")),
        "target_relative": {
            "right": target_relative[0],
            "forward": target_relative[1],
            "vertical": target_relative[2],
        },
        "direction_label": _relative_direction_label(*target_relative),
        "baseline_trajectory": baseline_trajectory,
        "inspection_trajectory": inspection_trajectory,
        "structure_points": structure_points,
    }


def spatial_mission_summary(model: dict[str, Any]) -> dict[str, Any]:
    if model.get("status") != "ready":
        return {
            "status": "unavailable",
            "reason": model.get("reason", "Spatial mission data unavailable."),
        }
    return {
        key: value
        for key, value in model.items()
        if key not in {
            "baseline_trajectory",
            "inspection_trajectory",
            "structure_points",
        }
    }


def _mission_map_svg(
    model: dict[str, Any],
    width: int = 760,
    height: int = 560,
) -> str:
    point_cloud = model.get("structure_points") or []
    baseline_path = model.get("baseline_trajectory") or []
    inspection_path = model.get("inspection_trajectory") or []
    target = model.get("target_relative") or {}
    target_xy = [
        safe_float(target.get("right")),
        safe_float(target.get("forward")),
    ]

    route_xy = [[0.0, 0.0], target_xy]
    route_x = [row[0] for row in route_xy]
    route_y = [row[1] for row in route_xy]
    route_min_x, route_max_x = min(route_x), max(route_x)
    route_min_y, route_max_y = min(route_y), max(route_y)
    route_span = max(route_max_x - route_min_x, route_max_y - route_min_y, 1.0)
    focus_margin = max(route_span * 0.9, 2.0)

    def in_focus(row: list[float], extra: float = 0.0) -> bool:
        if len(row) < 2:
            return False
        return (
            route_min_x - focus_margin - extra <= row[0] <= route_max_x + focus_margin + extra
            and route_min_y - focus_margin - extra <= row[1] <= route_max_y + focus_margin + extra
        )

    focused_points = [row for row in point_cloud if in_focus(row)]
    if not focused_points:
        focused_points = [row for row in point_cloud if len(row) >= 2][:2000]

    focus_xy = [[0.0, 0.0], target_xy]
    focus_xy.extend([[row[0], row[1]] for row in focused_points if len(row) >= 2])
    focus_xy.extend([[row[0], row[1]] for row in baseline_path if in_focus(row, route_span * 0.35)])
    focus_xy.extend([[row[0], row[1]] for row in inspection_path if in_focus(row, route_span * 0.35)])

    x_values = [row[0] for row in focus_xy]
    y_values = [row[1] for row in focus_xy]
    min_x, max_x = min(x_values), max(x_values)
    min_y, max_y = min(y_values), max(y_values)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    padding = 28.0
    scale = min(
        (width - 2 * padding) / span_x,
        (height - 2 * padding) / span_y,
    )
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0

    def project(row: list[float]) -> tuple[float, float]:
        return (
            width / 2.0 + (row[0] - center_x) * scale,
            height / 2.0 - (row[1] - center_y) * scale,
        )

    point_nodes = []
    for row in focused_points:
        if len(row) < 2:
            continue
        x, y = project(row)
        point_nodes.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1.55" '
            'fill="#72848d" fill-opacity="0.30" />'
        )

    def polyline(rows: list[list[float]], color: str, opacity: float) -> str:
        coordinates = [project(row) for row in rows if len(row) >= 2]
        if len(coordinates) < 2:
            return ""
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in coordinates)
        return (
            f'<polyline points="{points}" fill="none" stroke="{color}" '
            f'stroke-width="3.25" stroke-opacity="{opacity}" '
            'stroke-linecap="round" stroke-linejoin="round" />'
        )

    start_x, start_y = project([0.0, 0.0])
    target_x, target_y = project(target_xy)
    return f'''<svg viewBox="0 0 {width} {height}" role="img" aria-label="Top-down spatial reinspection mission map">
<defs>
  <marker id="mission-arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
    <path d="M0,0 L0,6 L9,3 z" fill="#d1495b" />
  </marker>
</defs>
<rect x="0" y="0" width="{width}" height="{height}" rx="18" fill="#f7fafb" />
<g>{''.join(point_nodes)}</g>
{polyline(baseline_path, '#087f8c', 0.95)}
{polyline(inspection_path, '#d07a1c', 0.82)}
<line x1="{start_x:.2f}" y1="{start_y:.2f}" x2="{target_x:.2f}" y2="{target_y:.2f}" stroke="#d1495b" stroke-width="4" stroke-dasharray="9 7" marker-end="url(#mission-arrow)" />
<circle cx="{start_x:.2f}" cy="{start_y:.2f}" r="9.5" fill="#2e9d67" stroke="white" stroke-width="3" />
<circle cx="{target_x:.2f}" cy="{target_y:.2f}" r="12.5" fill="#d1495b" fill-opacity="0.22" stroke="#d1495b" stroke-width="3" />
<circle cx="{target_x:.2f}" cy="{target_y:.2f}" r="4.8" fill="#d1495b" />
<text x="{start_x + 12:.2f}" y="{start_y - 10:.2f}" font-family="Segoe UI,Arial" font-size="14" font-weight="700" fill="#216646">START</text>
<text x="{target_x + 15:.2f}" y="{target_y - 12:.2f}" font-family="Segoe UI,Arial" font-size="14" font-weight="700" fill="#a4293b">TARGET</text>
<g transform="translate(22,{height - 35})" font-family="Segoe UI,Arial" font-size="12" fill="#43545d">
  <line x1="0" y1="0" x2="54" y2="0" stroke="#40535d" stroke-width="2" marker-end="url(#mission-arrow)" />
  <text x="62" y="4">RIGHT</text>
  <line x1="0" y1="0" x2="0" y2="-50" stroke="#40535d" stroke-width="2" marker-end="url(#mission-arrow)" />
  <text x="8" y="-38">STRAIGHT</text>
  <text x="0" y="24" fill="#6a7a81">STRAIGHT follows baseline start travel | RIGHT follows baseline start-right</text>
</g>
</svg>'''


def spatial_mission_map_html(
    model: dict[str, Any],
    mission_id: str,
) -> str:
    target = model.get("target_relative") or {}
    target_right = safe_float(target.get("right"))
    target_forward = safe_float(target.get("forward"))
    target_vertical = safe_float(target.get("vertical"))
    client_data = json.dumps(
        {
            "points": model.get("structure_points") or [],
            "baseline": model.get("baseline_trajectory") or [],
            "inspection": model.get("inspection_trajectory") or [],
            "target": [
                target_right,
                target_forward,
                target_vertical,
            ],
        },
        separators=(",", ":"),
    )
    safe_mission = html.escape(str(mission_id))
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:Segoe UI,Arial,sans-serif;color:#17252d;background:transparent}}
.viewer{{background:white;border:1px solid #d7e1e5;border-radius:16px;padding:14px;box-shadow:0 2px 9px rgba(20,55,65,.05)}}
.header{{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap;margin-bottom:10px}}
h3{{margin:0 0 4px;font-size:17px}}
p{{margin:0;color:#60717a;font-size:12px}}
.coords{{display:flex;gap:8px;flex-wrap:wrap}}
.coord{{background:#eef5f6;border-radius:10px;padding:7px 10px;font-size:12px;color:#40545d}}
.coord b{{color:#17252d}}
.controls{{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 10px}}
button{{border:1px solid #cbd8dd;background:white;color:#29424d;border-radius:9px;padding:7px 11px;font:600 12px Segoe UI,Arial;cursor:pointer}}
button:hover{{background:#f2f7f8}}
canvas{{display:block;width:100%;height:720px;background:#f7fafb;border-radius:13px;cursor:grab}}
canvas:active{{cursor:grabbing}}
.legend{{display:flex;flex-wrap:wrap;gap:14px;margin-top:10px;font-size:12px;color:#50616a}}
.key{{display:inline-flex;align-items:center;gap:5px}}
.dot{{width:10px;height:10px;border-radius:50%}}
.axis-key{{display:inline-flex;align-items:center;gap:5px;font-weight:600}}
.note{{margin-top:10px;background:#eef5f6;border-radius:12px;padding:10px 12px;color:#4b5d65;font-size:12px}}
@media(max-width:900px){{canvas{{height:560px}}}}
</style></head><body>
<div class="viewer">
  <div class="header">
    <div>
      <h3>{safe_mission} | Interactive 3D mission view</h3>
      <p>Drag to rotate, use the mouse wheel to zoom, and use the buttons to restore a useful view.</p>
    </div>
    <div class="coords">
      <span class="coord"><b>X</b> {target_right:+.2f} rel. (Right / Left)</span>
      <span class="coord"><b>Y</b> {target_forward:+.2f} rel. (Straight / Back)</span>
      <span class="coord"><b>Z</b> {target_vertical:+.2f} rel. (Up / Down)</span>
    </div>
  </div>
  <div class="controls">
    <button id="reset" type="button">Reset view</button>
    <button id="top" type="button">Top view</button>
    <button id="side" type="button">Side view</button>
    <button id="front" type="button">Front view</button>
    <button id="target" type="button">Focus target</button>
  </div>
  <canvas id="view"></canvas>
  <div class="legend">
    <span class="key"><i class="dot" style="background:#087f8c"></i>Baseline path</span>
    <span class="key"><i class="dot" style="background:#d07a1c"></i>Inspection path</span>
    <span class="key"><i class="dot" style="background:#72848d"></i>Approximate reconstructed structure</span>
    <span class="axis-key" style="color:#cc4b4b">X: Right (+) / Left (-)</span>
    <span class="axis-key" style="color:#287d55">Y: Straight (+) / Back (-)</span>
    <span class="axis-key" style="color:#356ac3">Z: Up (+) / Down (-)</span>
  </div>
  <div class="note">The origin is the first registered baseline camera position. The XY grid is the START-height reference plane, not the physical floor. Coordinates are reconstructed relative units, not calibrated metres. The target is the mission's baseline reference camera position. The sparse reconstruction is approximate spatial context, not a certified obstacle map or collision-free route.</div>
</div>
<script>
const data={client_data};
const canvas=document.getElementById('view');
const ctx=canvas.getContext('2d');
let yaw=-0.62,pitch=0.50,zoom=1.0,drag=false,lastX=0,lastY=0;
let focus=[0,0,0];

function sceneBounds(){{
  const all=[...data.points,...data.baseline,...data.inspection,[0,0,0],data.target];
  let max=1;
  for(const p of all){{
    max=Math.max(max,Math.abs(p[0]-focus[0]),Math.abs(p[1]-focus[1]),Math.abs(p[2]-focus[2]));
  }}
  return max;
}}
function rotate(p){{
  const px=p[0]-focus[0],py=p[1]-focus[1],pz=p[2]-focus[2];
  const cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);
  const x=px*cy-py*sy;
  const y=px*sy+py*cy;
  return [x,y*cp-pz*sp,y*sp+pz*cp];
}}
function project(p,w,h,s){{
  const q=rotate(p);
  return [w/2+q[0]*s,h/2-q[2]*s,q[1]];
}}
function resize(){{
  const dpr=window.devicePixelRatio||1;
  const r=canvas.getBoundingClientRect();
  canvas.width=Math.max(1,Math.floor(r.width*dpr));
  canvas.height=Math.max(1,Math.floor(r.height*dpr));
  ctx.setTransform(dpr,0,0,dpr,0,0);
  draw();
}}
function path(rows,color,width,w,h,s,dashed=false){{
  if(rows.length<2)return;
  ctx.beginPath();
  rows.forEach((p,i)=>{{
    const q=project(p,w,h,s);
    if(i===0)ctx.moveTo(q[0],q[1]);else ctx.lineTo(q[0],q[1]);
  }});
  ctx.setLineDash(dashed?[8,6]:[]);
  ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();ctx.setLineDash([]);
}}
function marker(p,color,label,w,h,s,r){{
  const q=project(p,w,h,s);
  ctx.beginPath();ctx.arc(q[0],q[1],r,0,Math.PI*2);
  ctx.fillStyle=color;ctx.fill();ctx.strokeStyle='white';ctx.lineWidth=2;ctx.stroke();
  ctx.fillStyle=color;ctx.font='700 13px Segoe UI';ctx.fillText(label,q[0]+11,q[1]-10);
}}
function line3d(a,b,color,width,w,h,s,dashed=false){{path([a,b],color,width,w,h,s,dashed);}}
function endpoint(p,color,label,w,h,s,align=1){{
  const q=project(p,w,h,s);
  ctx.beginPath();ctx.arc(q[0],q[1],3.5,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();
  ctx.fillStyle=color;ctx.font='700 12px Segoe UI';ctx.textAlign=align>0?'left':'right';
  ctx.fillText(label,q[0]+(align>0?7:-7),q[1]-6);ctx.textAlign='left';
}}
function drawGrid(w,h,s,axisLength){{
  const steps=5,extent=axisLength*1.4;
  ctx.save();ctx.globalAlpha=.18;
  for(let i=-steps;i<=steps;i++){{
    const v=extent*i/steps;
    line3d([-extent,v,0],[extent,v,0],'#71848c',1,w,h,s);
    line3d([v,-extent,0],[v,extent,0],'#71848c',1,w,h,s);
  }}
  ctx.restore();
}}
function drawAxes(w,h,s,axisLength){{
  line3d([-axisLength,0,0],[axisLength,0,0],'#cc4b4b',2.4,w,h,s);
  line3d([0,-axisLength,0],[0,axisLength,0],'#287d55',2.4,w,h,s);
  line3d([0,0,-axisLength],[0,0,axisLength],'#356ac3',2.4,w,h,s);
  endpoint([axisLength,0,0],'#cc4b4b','RIGHT +X',w,h,s,1);
  endpoint([-axisLength,0,0],'#cc4b4b','LEFT -X',w,h,s,-1);
  endpoint([0,axisLength,0],'#287d55','STRAIGHT +Y',w,h,s,1);
  endpoint([0,-axisLength,0],'#287d55','BACK -Y',w,h,s,-1);
  endpoint([0,0,axisLength],'#356ac3','UP +Z',w,h,s,1);
  endpoint([0,0,-axisLength],'#356ac3','DOWN -Z',w,h,s,-1);
  marker([0,0,0],'#253b45','ORIGIN',w,h,s,5);
}}
function draw(){{
  const r=canvas.getBoundingClientRect(),w=r.width,h=r.height;
  ctx.clearRect(0,0,w,h);ctx.fillStyle='#f7fafb';ctx.fillRect(0,0,w,h);
  const max=sceneBounds();const s=Math.min(w,h)*0.44/max*zoom;
  const axisLength=Math.max(1,max*0.32);
  drawGrid(w,h,s,axisLength);
  const pts=data.points.map(p=>[p,project(p,w,h,s)]).sort((a,b)=>a[1][2]-b[1][2]);
  for(const item of pts){{
    ctx.beginPath();ctx.arc(item[1][0],item[1][1],1.25,0,Math.PI*2);
    ctx.fillStyle='rgba(91,111,121,.30)';ctx.fill();
  }}
  path(data.baseline,'#087f8c',3.0,w,h,s);
  path(data.inspection,'#d07a1c',2.7,w,h,s);
  line3d([0,0,0],data.target,'#d1495b',3,w,h,s,true);
  drawAxes(w,h,s,axisLength);
  marker([0,0,0],'#2e9d67','START',w,h,s,7);
  marker(data.target,'#d1495b','TARGET',w,h,s,8);
}}
function setView(nextYaw,nextPitch,nextZoom=1.0,nextFocus=[0,0,0]){{
  yaw=nextYaw;pitch=nextPitch;zoom=nextZoom;focus=[...nextFocus];draw();
}}
canvas.addEventListener('mousedown',e=>{{drag=true;lastX=e.clientX;lastY=e.clientY;}});
window.addEventListener('mouseup',()=>drag=false);
window.addEventListener('mousemove',e=>{{
  if(!drag)return;
  yaw+=(e.clientX-lastX)*0.008;
  pitch=Math.max(-1.5,Math.min(1.5,pitch+(e.clientY-lastY)*0.008));
  lastX=e.clientX;lastY=e.clientY;draw();
}});
canvas.addEventListener('wheel',e=>{{
  e.preventDefault();zoom=Math.max(.25,Math.min(7,zoom*(e.deltaY>0?.9:1.1)));draw();
}},{{passive:false}});
document.getElementById('reset').addEventListener('click',()=>setView(-0.62,0.50,1.0,[0,0,0]));
document.getElementById('top').addEventListener('click',()=>setView(0,1.52,1.0,[0,0,0]));
document.getElementById('side').addEventListener('click',()=>setView(1.57,0,1.0,[0,0,0]));
document.getElementById('front').addEventListener('click',()=>setView(0,0,1.0,[0,0,0]));
document.getElementById('target').addEventListener('click',()=>setView(-0.62,0.50,2.0,data.target));
window.addEventListener('resize',resize);resize();
</script></body></html>'''

def render_spatial_mission_map(
    inspection_id: str,
    baseline_id: str,
    mission: dict[str, Any],
) -> None:
    model = build_spatial_mission_model(
        inspection_id,
        baseline_id,
        mission,
    )
    if model.get("status") != "ready":
        st.warning(
            "Interactive 3D mission view unavailable: "
            + str(model.get("reason", "unknown reason"))
        )
        return

    relative = model.get("target_relative") or {}
    metrics = st.columns(4)
    metrics[0].metric(
        "Direction from Start",
        model.get("direction_label", "N/A"),
    )
    metrics[1].metric(
        "X — Right / Left",
        f"{safe_float(relative.get('right')):+.2f} rel.",
    )
    metrics[2].metric(
        "Y — Straight / Back",
        f"{safe_float(relative.get('forward')):+.2f} rel.",
    )
    metrics[3].metric(
        "Z — Up / Down",
        f"{safe_float(relative.get('vertical')):+.2f} rel.",
    )
    st.caption(
        "The 3D coordinate system is anchored at the baseline start: "
        "+X Right, -X Left, +Y Straight, -Y Back, +Z Up, and -Z Down. "
        "The XY grid is a START-height reference plane, not the physical floor."
    )
    components.html(
        spatial_mission_map_html(
            model,
            str(mission.get("mission_id", "Mission")),
        ),
        height=920,
        scrolling=False,
    )
    with st.expander(
        "Spatial mission metadata",
        expanded=False,
    ):
        st.json(spatial_mission_summary(model))

def build_reinspection_missions(
    inspection_id: str,
    baseline_id: str,
) -> dict[str, Any]:
    triage = read_json(triage_path_for(inspection_id, baseline_id))
    if triage.get("status") != "ready":
        raise RuntimeError("Change triage is not ready.")

    missions: list[dict[str, Any]] = []
    for finding in triage.get("uncertain_changes") or []:
        frame_number = safe_int(finding.get("representative_frame", finding.get("frame_number")), -1)
        mission_id = f"R-F{frame_number:06d}"
        mission = {
            "mission_id": mission_id,
            "status": "ready_for_flight",
            "source_frames": finding.get("source_frames") or [frame_number],
            "representative_frame": frame_number,
            "initial_score_p95": safe_float(finding.get("score_p95")),
            "initial_geometry": finding.get("quality"),
            "target_area": finding.get("target_area"),
            "suspected_object": finding.get("suspected_object"),
            "context_source": finding.get("context_source"),
            "object_classification": finding.get("object_classification"),
            "baseline_name": finding.get("baseline_name"),
            "inspection_name": finding.get("inspection_name"),
            "evidence_frames": finding.get("evidence_frames") or [],
            "reason": (
                "This localized evidence cluster has a strong semantic-change signal, "
                "but none of its views has usable geometry for a reliable persistent-change decision."
            ),
            "flight_instructions": [
                "Navigate from the baseline start point to the target area shown on the spatial mission map.",
                "Use the reconstructed structure and trajectories as approximate guidance and visually avoid obstacles.",
                "Capture a slow multi-angle sweep around the target area rather than reproducing one exact viewpoint.",
                "Include at least one stable view where surrounding fixed structures overlap the baseline reference for geometry validation.",
                "Keep recording for at least 3 seconds after the target area is stable and clearly visible.",
                "Avoid temporary people, moving objects, and close foreground occlusion.",
            ],
            "verification_goal": (
                "Reacquire the same spatial target area with at least one geometrically comparable view, then determine whether the visual change persists."
            ),
        }
        mission["spatial_target"] = spatial_mission_summary(
            build_spatial_mission_model(
                inspection_id,
                baseline_id,
                mission,
            )
        )
        mission_root = mission_root_for(inspection_id, baseline_id, mission_id)
        write_json(mission_root / "mission.json", mission)
        missions.append(mission)

    payload = {
        "status": "ready",
        "context_version": CONTEXT_VERSION,
        "created_at": now_iso(),
        "inspection_id": inspection_id,
        "baseline_id": baseline_id,
        "mission_count": len(missions),
        "missions": missions,
    }
    write_json(missions_path_for(inspection_id, baseline_id), payload)
    return payload


def missions_are_ready(
    inspection_id: str,
    baseline_id: str,
) -> bool:
    payload = read_json(
        missions_path_for(
            inspection_id,
            baseline_id,
        )
    )
    return (
        payload.get("status") == "ready"
        and payload.get("inspection_id") == inspection_id
        and payload.get("baseline_id") == baseline_id
    )


def load_reinspection_result(
    inspection_id: str,
    baseline_id: str,
    mission_id: str,
) -> dict[str, Any]:
    return read_json(
        reinspection_run_summary_path_for(
            inspection_id,
            baseline_id,
            mission_id,
        )
    )


def classify_reinspection_result(
    result: dict[str, Any],
    confirmed_threshold: float = 0.62,
    cleared_threshold: float = 0.50,
) -> str:
    quality = str(
        result.get("geometry_quality", "poor")
    ).lower()
    p95 = safe_float(result.get("score_p95"))
    if quality not in {"excellent", "good", "usable"}:
        return "still_unresolved"
    if p95 >= confirmed_threshold:
        return "persistent_change_confirmed"
    if p95 < cleared_threshold:
        return "no_persistent_change"
    return "still_unresolved"


def all_reinspection_missions_resolved(
    inspection_id: str,
    baseline_id: str,
) -> bool:
    payload = read_json(
        missions_path_for(
            inspection_id,
            baseline_id,
        )
    )
    if payload.get("status") != "ready":
        return False
    missions = payload.get("missions") or []
    if not missions:
        return True
    return all(
        load_reinspection_result(
            inspection_id,
            baseline_id,
            str(mission.get("mission_id")),
        ).get("status") == "ready"
        for mission in missions
    )


def _existing_path(value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_file() else None


def _amd_results_root(inspection_id: str, baseline_id: str) -> Path | None:
    summary = load_amd_run_summary(inspection_id, baseline_id)
    root = Path(str(summary.get("result_root", "")))
    return root if root.is_dir() else None


def _resolve_result_asset(root: Path | None, relative: Any) -> Path | None:
    if root is None:
        return None
    text = str(relative or "").strip()
    if not text:
        return None
    path = root / text
    return path if path.is_file() else None


def _initial_evidence_images(
    inspection_id: str,
    baseline_id: str,
    item: dict[str, Any],
    maximum: int = 1,
) -> list[dict[str, str]]:
    root = _amd_results_root(inspection_id, baseline_id)
    evidence_rows = item.get("evidence_frames") or [item]
    evidence: list[dict[str, str]] = []
    for row in sorted(
        evidence_rows,
        key=lambda value: safe_float(value.get("score_p95")),
        reverse=True,
    )[:maximum]:
        montage = _resolve_result_asset(root, row.get("montage_file"))
        overlay = _resolve_result_asset(root, row.get("overlay_file"))
        frame = safe_int(row.get("frame_number"), safe_int(item.get("frame_number"), -1))
        if montage:
            evidence.append({
                "label": f"Initial evidence — representative frame {frame}",
                "path": str(montage),
                "kind": "initial_montage",
            })
        elif overlay:
            evidence.append({
                "label": f"Initial overlay — representative frame {frame}",
                "path": str(overlay),
                "kind": "initial_overlay",
            })
    return evidence

def _reinspection_evidence_images(result: dict[str, Any]) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    montage = _existing_path(result.get("montage_path"))
    overlay = _existing_path(result.get("overlay_path"))
    candidate_review = _existing_path(result.get("candidate_review_path"))
    if montage:
        evidence.append({
            "label": "Targeted reinspection comparison",
            "path": str(montage),
            "kind": "reinspection_montage",
        })
    elif overlay:
        evidence.append({
            "label": "Targeted reinspection overlay",
            "path": str(overlay),
            "kind": "reinspection_overlay",
        })
    if candidate_review:
        evidence.append({
            "label": "Reinspection candidate validation",
            "path": str(candidate_review),
            "kind": "candidate_review",
        })
    return evidence

def build_final_report_payload(
    inspection_id: str,
    baseline_id: str,
    human_decisions: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    human_decisions = human_decisions or {}
    triage = read_json(triage_path_for(inspection_id, baseline_id))
    missions_payload = read_json(missions_path_for(inspection_id, baseline_id))

    confirmed_findings: list[dict[str, Any]] = []
    for index, item in enumerate(triage.get("confirmed_changes") or [], start=1):
        finding_id = f"F-I-{index:03d}"
        spatial_model = build_spatial_mission_model(inspection_id, baseline_id, item)
        confirmed_findings.append({
            "finding_id": finding_id,
            "source": "initial_inspection",
            "frames": item.get("source_frames") or [item.get("frame_number")],
            "representative_frame": item.get("representative_frame", item.get("frame_number")),
            "target_area": item.get("target_area"),
            "observed_change": item.get("suspected_object"),
            "ai_evidence_conclusion": (
                "Persistent visual change is supported by high semantic-change evidence and at least one usable geometrically aligned view in this localized cluster."
            ),
            "score_p95": item.get("score_p95"),
            "evidence_images": _initial_evidence_images(inspection_id, baseline_id, item),
            "spatial_mission": spatial_model,
            "human_disposition": human_decisions.get(finding_id, {}),
        })

    resolved_without_change: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for index, mission in enumerate(missions_payload.get("missions") or [], start=1):
        mission_id = str(mission.get("mission_id"))
        result = load_reinspection_result(inspection_id, baseline_id, mission_id)
        outcome = classify_reinspection_result(result)
        combined_evidence = _initial_evidence_images(inspection_id, baseline_id, mission)
        combined_evidence.extend(_reinspection_evidence_images(result))
        spatial_model = build_spatial_mission_model(inspection_id, baseline_id, mission)

        if outcome == "persistent_change_confirmed":
            finding_id = f"F-R-{index:03d}"
            confirmed_findings.append({
                "finding_id": finding_id,
                "source": "targeted_reinspection",
                "mission_id": mission_id,
                "frames": mission.get("source_frames") or [],
                "representative_frame": mission.get("representative_frame"),
                "target_area": mission.get("target_area"),
                "observed_change": mission.get("suspected_object"),
                "ai_evidence_conclusion": (
                    "The same localized target was reacquired with usable geometry and the visual-change signal remained after targeted reinspection."
                ),
                "geometry_quality": result.get("geometry_quality"),
                "initial_score_p95": mission.get("initial_score_p95"),
                "reinspection_score_p95": result.get("score_p95"),
                "evidence_images": combined_evidence,
                "spatial_mission": spatial_model,
                "human_disposition": human_decisions.get(finding_id, {}),
            })
        elif outcome == "no_persistent_change":
            resolved_without_change.append({
                "mission_id": mission_id,
                "target_area": mission.get("target_area"),
                "resolution": (
                    "The same target was reacquired with usable geometry and no persistent visual-change signal remained."
                ),
                "geometry_quality": result.get("geometry_quality"),
                "initial_score_p95": mission.get("initial_score_p95"),
                "reinspection_score_p95": result.get("score_p95"),
                "evidence_images": combined_evidence,
                "spatial_mission": spatial_model,
            })
        else:
            unresolved.append({
                "mission_id": mission_id,
                "target_area": mission.get("target_area"),
                "reason": (
                    "The target was not reacquired with usable geometry, or the semantic evidence remained inconclusive. Another targeted observation or direct inspection is required."
                ),
                "geometry_quality": result.get("geometry_quality"),
                "initial_score_p95": mission.get("initial_score_p95"),
                "reinspection_score_p95": result.get("score_p95"),
                "evidence_images": combined_evidence,
                "spatial_mission": spatial_model,
            })

    return {
        "status": "ready",
        "created_at": now_iso(),
        "inspection_id": inspection_id,
        "baseline_id": baseline_id,
        "report_type": "change_evidence_report",
        "scope_note": (
            "FactoryFly reports observed visual changes and evidence quality. It does not determine whether a change is a defect, safety issue, or acceptable operation; that operational disposition is assigned by a human reviewer."
        ),
        "summary": {
            "analyzed_pairs": triage.get("counts", {}).get("analyzed", 0),
            "stable_areas_cleared": triage.get("counts", {}).get("no_material_change", 0),
            "confirmed_changes": len(confirmed_findings),
            "reinspection_missions": len(missions_payload.get("missions") or []),
            "resolved_as_temporary_or_viewpoint": len(resolved_without_change),
            "unresolved_findings": len(unresolved),
        },
        "confirmed_changes": confirmed_findings,
        "resolved_without_persistent_change": resolved_without_change,
        "unresolved_findings": unresolved,
    }

def final_report_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# FactoryFly Change Evidence Report",
        "",
        f"- Inspection: {payload.get('inspection_id')}",
        f"- Baseline: {payload.get('baseline_id')}",
        f"- Generated: {payload.get('created_at')}",
        "",
        "## Scope",
        "",
        str(payload.get("scope_note", "")),
        "",
        "## Summary",
        "",
        f"- Analyzed pairs: {summary.get('analyzed_pairs', 0)}",
        f"- Stable areas automatically cleared: {summary.get('stable_areas_cleared', 0)}",
        f"- Confirmed visual-change findings: {summary.get('confirmed_changes', 0)}",
        f"- Targeted reinspection missions: {summary.get('reinspection_missions', 0)}",
        f"- Cleared after reinspection: {summary.get('resolved_as_temporary_or_viewpoint', 0)}",
        f"- Unresolved findings: {summary.get('unresolved_findings', 0)}",
        "",
        "## Confirmed Visual Changes",
        "",
    ]
    for finding in payload.get("confirmed_changes") or []:
        decision = finding.get("human_disposition") or {}
        lines.extend([
            f"### {finding.get('finding_id')} — {finding.get('target_area')}",
            "",
            f"- Source frames: {', '.join(str(v) for v in finding.get('frames') or [])}",
            f"- Observed change: {finding.get('observed_change')}",
            f"- AI evidence conclusion: {finding.get('ai_evidence_conclusion')}",
        ])
        if finding.get("source") == "targeted_reinspection":
            lines.extend([
                f"- Geometry: {finding.get('geometry_quality', 'N/A')}",
                f"- Initial p95: {_format_optional_score(finding.get('initial_score_p95'))}",
                f"- Reinspection p95: {_format_optional_score(finding.get('reinspection_score_p95'))}",
            ])
        else:
            lines.append(
                f"- Initial p95: {_format_optional_score(finding.get('score_p95'))}"
            )
        lines.extend([
            f"- Human disposition: {decision.get('category', 'Pending human judgment')}",
            f"- Human notes: {decision.get('notes', '')}",
            "",
        ])
    if payload.get("resolved_without_persistent_change"):
        lines.extend(["## Cleared by Reinspection", ""])
        for item in payload["resolved_without_persistent_change"]:
            lines.extend([f"- {item.get('mission_id')} / {item.get('target_area')}: {item.get('resolution')}", ""])
    if payload.get("unresolved_findings"):
        lines.extend(["## Unresolved Evidence", ""])
        for item in payload["unresolved_findings"]:
            lines.extend([f"- {item.get('mission_id')} / {item.get('target_area')}: {item.get('reason')}", ""])
    return "\n".join(lines).strip() + "\n"


def _image_data_uri(path_value: Any) -> str | None:
    path = _existing_path(path_value)
    if path is None:
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _pil_image_data_uri(image: Image.Image, quality: int = 92) -> str:
    output = io.BytesIO()
    converted = image.convert("RGB")
    converted.save(output, format="JPEG", quality=quality, optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _format_optional_score(value: Any) -> str:
    return "N/A" if value in {None, ""} else f"{safe_float(value):.3f}"


def _html_initial_montage(image: dict[str, str]) -> str | None:
    path = _existing_path(image.get("path"))
    if path is None:
        return None
    try:
        with Image.open(path) as source:
            source = source.convert("RGB")
            width, height = source.size
            if width < 800 or height < 500:
                return None
            cell_width = width // 2
            cell_height = height // 2
            label_strip = min(48, max(0, int(cell_height * 0.14)))
            panels = [
                ("Baseline reference", (0, label_strip, cell_width, cell_height)),
                ("Initial inspection", (cell_width, label_strip, width, cell_height)),
                ("Warped baseline", (0, cell_height + label_strip, cell_width, height)),
                ("DINOv2 change overlay", (cell_width, cell_height + label_strip, width, height)),
            ]
            cards = []
            for label_text, box in panels:
                crop = source.crop(box)
                cards.append(
                    '<div class="evidence-panel">'
                    f'<div class="panel-label">{html.escape(label_text)}</div>'
                    f'<img src="{_pil_image_data_uri(crop)}" alt="{html.escape(label_text)}">'
                    '</div>'
                )
    except (OSError, ValueError):
        return None

    caption = html.escape(str(image.get("label", "Initial evidence")))
    return (
        '<figure class="evidence evidence-wide">'
        '<div class="evidence-montage">' + ''.join(cards) + '</div>'
        '<p class="evidence-explainer"><strong>How to read this:</strong> '
        'Black regions in the warped baseline are outside the valid geometric overlap, not detected changes. '
        'In the DINOv2 overlay, warmer colors indicate greater relative semantic difference within the valid overlap. '
        'The colors are not defect probabilities or severity scores.</p>'
        f'<figcaption>{caption}</figcaption></figure>'
    )


def _html_candidate_review(image: dict[str, str], maximum_candidates: int = 2) -> str | None:
    path = _existing_path(image.get("path"))
    if path is None:
        return None
    try:
        with Image.open(path) as source:
            source = source.convert("RGB")
            width, height = source.size
            row_height = 240 if height >= 480 and height % 240 == 0 else 0
            if width < 700 or row_height == 0:
                return None
            label_strip = 38
            half = width // 2
            reference_cards = []
            for label_text, box in [
                ("Baseline reference", (0, label_strip, half, row_height)),
                ("Initial inspection reference", (half, label_strip, width, row_height)),
            ]:
                crop = source.crop(box)
                reference_cards.append(
                    '<div class="evidence-panel">'
                    f'<div class="panel-label">{html.escape(label_text)}</div>'
                    f'<img src="{_pil_image_data_uri(crop)}" alt="{html.escape(label_text)}">'
                    '</div>'
                )
            candidate_cards = []
            available = max(0, height // row_height - 1)
            for index in range(min(maximum_candidates, available)):
                top = row_height * (index + 1)
                crop = source.crop((0, top, width, min(top + row_height, height)))
                candidate_cards.append(
                    '<div class="candidate-panel">'
                    f'<div class="panel-label">Top reacquisition candidate {index + 1}</div>'
                    f'<img src="{_pil_image_data_uri(crop)}" alt="Top reacquisition candidate {index + 1}">'
                    '</div>'
                )
    except (OSError, ValueError):
        return None

    return (
        '<figure class="evidence evidence-wide">'
        '<div class="candidate-reference-grid">' + ''.join(reference_cards) + '</div>'
        '<div class="candidate-list">' + ''.join(candidate_cards) + '</div>'
        '<p class="evidence-explainer"><strong>Candidate validation only:</strong> '
        'These frames show why the target was or was not geometrically reacquired. '
        'They are not additional change findings.</p>'
        '<figcaption>Reinspection candidate validation — top candidates only</figcaption></figure>'
    )


def _html_evidence_gallery(images: list[dict[str, str]]) -> str:
    cards: list[str] = []
    for image in images:
        kind = str(image.get("kind", ""))
        if kind in {"initial_montage", "reinspection_montage"}:
            specialized = _html_initial_montage(image)
            if specialized:
                cards.append(specialized)
                continue
        if kind == "candidate_review":
            specialized = _html_candidate_review(image)
            if specialized:
                cards.append(specialized)
                continue
        uri = _image_data_uri(image.get("path"))
        if not uri:
            continue
        cards.append(
            '<figure class="evidence"><div class="panel-label">Evidence image</div>'
            '<img src="' + uri + '" alt="Evidence image">'
            '<figcaption>' + html.escape(str(image.get("label", "Evidence"))) + '</figcaption></figure>'
        )
    return '<div class="gallery">' + ''.join(cards) + '</div>' if cards else '<p class="muted">No image asset was available for this finding.</p>'


def _partition_evidence(images: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    initial_kinds = {"initial_montage", "initial_overlay"}
    initial = [image for image in images if str(image.get("kind", "")) in initial_kinds]
    followup = [image for image in images if str(image.get("kind", "")) not in initial_kinds]
    return initial, followup


def _frame_cluster_label(frames: list[Any], representative: Any) -> str:
    numbers = sorted({safe_int(value, -1) for value in frames if safe_int(value, -1) >= 0})
    rep = safe_int(representative, -1)
    if not numbers:
        return f"Representative frame: {rep}" if rep >= 0 else "Frame information unavailable"
    if len(numbers) == 1:
        return f"Representative frame: {rep if rep >= 0 else numbers[0]}"
    return (
        f"Cluster frames: {numbers[0]}–{numbers[-1]} ({len(numbers)} sampled)"
        + (f" · Representative: {rep}" if rep >= 0 else "")
    )


def _html_spatial_mission_view(model: dict[str, Any], identifier: str) -> str:
    if model.get("status") != "ready":
        return '<p class="muted">3D spatial mission information was unavailable for this finding.</p>'
    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", identifier).strip("-") or "mission"
    target = model.get("target_relative") or {}
    x = safe_float(target.get("right"))
    y = safe_float(target.get("forward"))
    z = safe_float(target.get("vertical"))
    data = json.dumps({
        "points": model.get("structure_points") or [],
        "baseline": model.get("baseline_trajectory") or [],
        "inspection": model.get("inspection_trajectory") or [],
        "target": [x, y, z],
    }, separators=(",", ":"))
    return f'''<section class="spatial-report" id="spatial-{safe_id}">
<h3>3D location from baseline start</h3>
<div class="spatial-coordinates"><span><b>X</b> {x:+.2f} rel. — Right / Left</span><span><b>Y</b> {y:+.2f} rel. — Straight / Back</span><span><b>Z</b> {z:+.2f} rel. — Up / Down</span></div>
<div class="spatial-controls"><button type="button" data-view="reset">Reset</button><button type="button" data-view="top">Top</button><button type="button" data-view="side">Side</button><button type="button" data-view="front">Front</button><button type="button" data-view="target">Focus target</button></div>
<canvas aria-label="Interactive 3D mission location"></canvas>
<div class="spatial-legend"><span>Baseline path</span><span>Inspection path</span><span>Reconstructed structure</span></div>
<p class="spatial-note">The origin is the first registered baseline camera position. The XY grid is the START-height reference plane, not the physical floor. Coordinates are reconstructed relative units, not calibrated metres.</p>
<script>(function(){{
const root=document.getElementById('spatial-{safe_id}');if(!root)return;const data={data};const canvas=root.querySelector('canvas');const ctx=canvas.getContext('2d');let yaw=-0.62,pitch=0.50,zoom=1,drag=false,lastX=0,lastY=0,focus=[0,0,0];
function bounds(){{const all=[...data.points,...data.baseline,...data.inspection,[0,0,0],data.target];let m=1;for(const p of all)m=Math.max(m,Math.abs(p[0]-focus[0]),Math.abs(p[1]-focus[1]),Math.abs(p[2]-focus[2]));return m;}}
function rotate(p){{const px=p[0]-focus[0],py=p[1]-focus[1],pz=p[2]-focus[2],cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch),rx=px*cy-py*sy,ry=px*sy+py*cy;return[rx,ry*cp-pz*sp,ry*sp+pz*cp];}}
function project(p,w,h,s){{const q=rotate(p);return[w/2+q[0]*s,h/2-q[2]*s,q[1]];}}
function line(a,b,color,width,w,h,s,dash=false){{const p=project(a,w,h,s),q=project(b,w,h,s);ctx.beginPath();ctx.setLineDash(dash?[7,6]:[]);ctx.moveTo(p[0],p[1]);ctx.lineTo(q[0],q[1]);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();ctx.setLineDash([]);}}
function path(rows,color,width,w,h,s){{if(rows.length<2)return;ctx.beginPath();rows.forEach((p,i)=>{{const q=project(p,w,h,s);if(i===0)ctx.moveTo(q[0],q[1]);else ctx.lineTo(q[0],q[1]);}});ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();}}
function marker(p,color,label,w,h,s,r){{const q=project(p,w,h,s);ctx.beginPath();ctx.arc(q[0],q[1],r,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();ctx.strokeStyle='white';ctx.lineWidth=2;ctx.stroke();ctx.fillStyle=color;ctx.font='700 12px Segoe UI';ctx.fillText(label,q[0]+9,q[1]-8);}}
function draw(){{const r=canvas.getBoundingClientRect(),w=r.width,h=r.height;ctx.clearRect(0,0,w,h);ctx.fillStyle='#f7fafb';ctx.fillRect(0,0,w,h);const max=bounds(),s=Math.min(w,h)*0.43/max*zoom,axis=Math.max(1,max*.30);ctx.save();ctx.globalAlpha=.16;for(let i=-5;i<=5;i++){{const v=axis*1.4*i/5;line([-axis*1.4,v,0],[axis*1.4,v,0],'#71848c',1,w,h,s);line([v,-axis*1.4,0],[v,axis*1.4,0],'#71848c',1,w,h,s);}}ctx.restore();const pts=data.points.map(p=>[p,project(p,w,h,s)]).sort((a,b)=>a[1][2]-b[1][2]);for(const item of pts){{ctx.beginPath();ctx.arc(item[1][0],item[1][1],1.15,0,Math.PI*2);ctx.fillStyle='rgba(91,111,121,.28)';ctx.fill();}}path(data.baseline,'#087f8c',2.7,w,h,s);path(data.inspection,'#d07a1c',2.4,w,h,s);line([0,0,0],data.target,'#d1495b',2.6,w,h,s,true);line([-axis,0,0],[axis,0,0],'#cc4b4b',2,w,h,s);line([0,-axis,0],[0,axis,0],'#287d55',2,w,h,s);line([0,0,-axis],[0,0,axis],'#356ac3',2,w,h,s);marker([0,0,0],'#2e9d67','START',w,h,s,6);marker(data.target,'#d1495b','TARGET',w,h,s,7);}}
function resize(){{const dpr=window.devicePixelRatio||1,r=canvas.getBoundingClientRect();canvas.width=Math.max(1,Math.floor(r.width*dpr));canvas.height=Math.max(1,Math.floor(r.height*dpr));ctx.setTransform(dpr,0,0,dpr,0,0);draw();}}
function setView(a,b,c=1,d=[0,0,0]){{yaw=a;pitch=b;zoom=c;focus=[...d];draw();}}
canvas.addEventListener('mousedown',e=>{{drag=true;lastX=e.clientX;lastY=e.clientY;}});window.addEventListener('mouseup',()=>drag=false);window.addEventListener('mousemove',e=>{{if(!drag)return;yaw+=(e.clientX-lastX)*.008;pitch=Math.max(-1.5,Math.min(1.5,pitch+(e.clientY-lastY)*.008));lastX=e.clientX;lastY=e.clientY;draw();}});canvas.addEventListener('wheel',e=>{{e.preventDefault();zoom=Math.max(.25,Math.min(7,zoom*(e.deltaY>0?.9:1.1)));draw();}},{{passive:false}});root.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{{const v=button.dataset.view;if(v==='top')setView(0,1.52);else if(v==='side')setView(1.57,0);else if(v==='front')setView(0,0);else if(v==='target')setView(-.62,.50,2,data.target);else setView(-.62,.50);}}));window.addEventListener('resize',resize);resize();
}})();</script></section>'''

def final_report_html(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    finding_sections: list[str] = []
    for finding in payload.get("confirmed_changes") or []:
        decision = finding.get("human_disposition") or {}
        initial_evidence, followup_evidence = _partition_evidence(finding.get("evidence_images") or [])
        frame_label = _frame_cluster_label(
            finding.get("frames") or [],
            finding.get("representative_frame"),
        )
        if finding.get("source") == "targeted_reinspection":
            evidence_metrics = (
                '<div class="finding-metrics">'
                '<div class="finding-metric"><span>Geometry</span><b>'
                + html.escape(str(finding.get("geometry_quality", "N/A")))
                + '</b></div>'
                '<div class="finding-metric"><span>Initial p95</span><b>'
                + _format_optional_score(finding.get("initial_score_p95"))
                + '</b></div>'
                '<div class="finding-metric"><span>Reinspection p95</span><b>'
                + _format_optional_score(finding.get("reinspection_score_p95"))
                + '</b></div>'
                '</div>'
            )
        else:
            evidence_metrics = (
                '<div class="finding-metrics finding-metrics-single">'
                '<div class="finding-metric"><span>Initial p95</span><b>'
                + _format_optional_score(finding.get("score_p95"))
                + '</b></div>'
                '</div>'
            )
        finding_sections.append(f'''<section class="finding confirmed">
<h2>{html.escape(str(finding.get("finding_id")))} — {html.escape(str(finding.get("target_area")))}</h2>
<div class="tags"><span>{html.escape(frame_label)}</span><span>Source: {html.escape(str(finding.get('source')))}</span></div>
<p><strong>Observed visual change:</strong> {html.escape(str(finding.get("observed_change")))}</p>
<p class="ai"><strong>AI evidence conclusion:</strong> {html.escape(str(finding.get("ai_evidence_conclusion")))}</p>
{evidence_metrics}
{_html_evidence_gallery(initial_evidence)}
{_html_spatial_mission_view(finding.get("spatial_mission") or {{}}, str(finding.get("finding_id")))}
{_html_evidence_gallery(followup_evidence) if followup_evidence else ''}
<div class="decision"><strong>Human disposition:</strong> {html.escape(str(decision.get("category", "Pending human judgment")))}<br><strong>Reviewer notes:</strong> {html.escape(str(decision.get("notes", "")))}</div>
</section>''')

    cleared_sections = ''.join(
        f'''<section class="finding cleared"><h2>{html.escape(str(item.get("mission_id")))} — Cleared by reinspection</h2><p>{html.escape(str(item.get("resolution")))}</p>{_html_evidence_gallery(_partition_evidence(item.get("evidence_images") or [])[0])}{_html_spatial_mission_view(item.get("spatial_mission") or {{}}, str(item.get("mission_id")))}{_html_evidence_gallery(_partition_evidence(item.get("evidence_images") or [])[1])}</section>'''
        for item in payload.get("resolved_without_persistent_change") or []
    )
    unresolved_sections = ''.join(
        f'''<section class="finding unresolved"><h2>{html.escape(str(item.get("mission_id")))} — Unresolved evidence</h2><p>{html.escape(str(item.get("reason")))}</p><p><strong>Geometry:</strong> {html.escape(str(item.get("geometry_quality")))} &nbsp; <strong>Reinspection p95:</strong> {_format_optional_score(item.get("reinspection_score_p95"))}</p>{_html_evidence_gallery(_partition_evidence(item.get("evidence_images") or [])[0])}{_html_spatial_mission_view(item.get("spatial_mission") or {{}}, str(item.get("mission_id")))}{_html_evidence_gallery(_partition_evidence(item.get("evidence_images") or [])[1])}</section>'''
        for item in payload.get("unresolved_findings") or []
    )

    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FactoryFly Change Evidence Report</title>
<style>
*{{box-sizing:border-box}}body{{font-family:Inter,Segoe UI,Arial,sans-serif;margin:0;background:#f4f7f9;color:#16202a;line-height:1.5}}main{{max-width:1240px;margin:auto;padding:36px}}header{{background:#0c3440;color:white;padding:30px;border-radius:18px}}header h1{{margin:0 0 8px}}.scope{{background:#e8f4f5;border-left:5px solid #0b8f94;padding:16px;margin:22px 0}}.metrics{{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));gap:12px;margin:20px 0}}.metric{{background:white;border:1px solid #d9e2e7;border-radius:12px;padding:14px}}.metric b{{display:block;font-size:26px}}.finding{{background:white;border:1px solid #d9e2e7;border-radius:16px;padding:20px;margin:18px 0;box-shadow:0 3px 12px rgba(10,40,50,.05)}}.confirmed{{border-left:7px solid #0b8f94}}.cleared{{border-left:7px solid #3f8f58}}.unresolved{{border-left:7px solid #d79a1f}}.tags span{{display:inline-block;background:#eef3f5;border-radius:999px;padding:5px 10px;margin:0 6px 8px 0;font-size:13px}}.ai{{background:#eef7ff;padding:12px;border-radius:10px}}.finding-metrics{{display:grid;grid-template-columns:repeat(3,minmax(150px,1fr));gap:12px;margin:14px 0 18px}}.finding-metrics-single{{grid-template-columns:minmax(180px,320px)}}.finding-metric{{background:#f8fbfc;border:1px solid #bfd0d7;border-radius:11px;padding:12px 14px}}.finding-metric span{{display:block;color:#52636d;font-size:13px;margin-bottom:3px}}.finding-metric b{{display:block;font-size:22px;color:#173946}}.decision{{background:#f7f7f7;padding:14px;border-radius:10px;margin-top:18px}}.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:18px;margin-top:18px}}figure{{margin:0}}.evidence{{background:#f8fafb;border:2px solid #c6d3d9;border-radius:14px;padding:12px;overflow:hidden}}.evidence-wide{{grid-column:1/-1}}.evidence img{{display:block;width:100%;height:auto;border:1px solid #8fa3ad}}.panel-label{{background:#173946;color:white;font-size:16px;font-weight:700;padding:10px 12px;border-radius:8px 8px 0 0;letter-spacing:.01em}}.evidence-montage{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.evidence-panel{{border:2px solid #8299a4;border-radius:10px;overflow:hidden;background:white}}.candidate-reference-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.candidate-list{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:14px}}.candidate-panel{{border:2px solid #8299a4;border-radius:10px;overflow:hidden;background:white}}.evidence-explainer{{background:#eef4f6;border-left:4px solid #708892;padding:12px 14px;margin:14px 0 4px;font-size:14px}}figcaption{{font-size:14px;color:#52636d;margin-top:8px;font-weight:600}}.spatial-report{{margin:20px 0;background:#f8fafb;border:2px solid #c6d3d9;border-radius:14px;padding:14px}}.spatial-report h3{{margin:0 0 10px}}.spatial-coordinates{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}}.spatial-coordinates span{{background:#e8f2f4;border-radius:9px;padding:7px 10px;font-size:13px}}.spatial-controls{{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:10px}}.spatial-controls button{{border:1px solid #b9c9d0;background:white;border-radius:8px;padding:7px 11px;cursor:pointer}}.spatial-report canvas{{display:block;width:100%;height:520px;background:#f7fafb;border:1px solid #c6d3d9;border-radius:10px;cursor:grab}}.spatial-legend{{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;font-size:13px;color:#52636d}}.spatial-note{{background:#eef4f6;padding:10px 12px;border-radius:9px;font-size:13px;color:#52636d}}.muted{{color:#657680}}footer{{color:#657680;margin-top:30px;font-size:13px}}@media(max-width:900px){{.metrics{{grid-template-columns:repeat(2,1fr)}}.finding-metrics{{grid-template-columns:1fr}}main{{padding:16px}}.evidence-montage,.candidate-reference-grid,.candidate-list{{grid-template-columns:1fr}}.spatial-report canvas{{height:400px}}}}
</style></head><body><main>
<header><h1>FactoryFly Change Evidence Report</h1><div>Inspection: {html.escape(str(payload.get('inspection_id')))} &nbsp; | &nbsp; Baseline: {html.escape(str(payload.get('baseline_id')))}<br>Generated: {html.escape(str(payload.get('created_at')))}</div></header>
<div class="scope"><strong>Scope:</strong> {html.escape(str(payload.get('scope_note')))}</div>
<div class="metrics">
<div class="metric"><span>Analyzed pairs</span><b>{summary.get('analyzed_pairs',0)}</b></div>
<div class="metric"><span>Stable cleared</span><b>{summary.get('stable_areas_cleared',0)}</b></div>
<div class="metric"><span>Confirmed findings</span><b>{summary.get('confirmed_changes',0)}</b></div>
<div class="metric"><span>Reinspections</span><b>{summary.get('reinspection_missions',0)}</b></div>
<div class="metric"><span>Cleared after reinspection</span><b>{summary.get('resolved_as_temporary_or_viewpoint',0)}</b></div>
<div class="metric"><span>Unresolved</span><b>{summary.get('unresolved_findings',0)}</b></div>
</div>
<h1>Confirmed Visual Changes</h1>{''.join(finding_sections) or '<p>No persistent visual change was confirmed.</p>'}
{('<h1>Cleared by Reinspection</h1>'+cleared_sections) if cleared_sections else ''}
{('<h1>Unresolved Evidence</h1>'+unresolved_sections) if unresolved_sections else ''}
<footer>Evidence heatmaps are visualization aids. DINOv2 scores rank semantic visual difference and are not calibrated defect probabilities or severity scores.</footer>
</main></body></html>'''

def now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).astimezone().isoformat()


def active_baseline_record() -> dict[str, Any]:
    return read_json(
        ACTIVE_BASELINE_PATH
    )


def activate_baseline(
    baseline_id: str,
    summary: dict[str, Any],
) -> None:
    CONFIG_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "baseline_id": baseline_id,
        "status": "active",
        "activated_at": now_iso(),
        "summary_path": str(
            summary_path_for(baseline_id)
        ),
        "best_model_path": summary.get(
            "best_model_path"
        ),
        "frame_path": summary.get(
            "frame_path"
        ),
    }

    ACTIVE_BASELINE_PATH.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def current_demo_run_record() -> dict[str, Any]:
    return read_json(CURRENT_DEMO_RUN_PATH)


def default_demo_run_ids() -> tuple[str, str]:
    timestamp = datetime.now().astimezone().strftime(
        "%Y%m%d_%H%M"
    )
    return (
        f"baseline_demo_{timestamp}",
        f"inspection_demo_{timestamp}",
    )


def validate_demo_run_id(
    value: str,
    label: str,
) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{label} is required.")
    if normalized in {".", ".."}:
        raise ValueError(f"{label} is invalid.")
    if INVALID_WINDOWS_NAME.search(normalized):
        raise ValueError(
            f"{label} contains an invalid Windows filename character."
        )
    if normalized.endswith((" ", ".")):
        raise ValueError(
            f"{label} cannot end with a space or period."
        )
    return normalized


def archive_path_for_demo_run(
    source_path: Path,
    archive_root: Path,
    category: str,
) -> Path:
    category_root = archive_root / category
    category_root.mkdir(parents=True, exist_ok=True)
    candidate = category_root / source_path.name
    suffix = 1
    while candidate.exists():
        candidate = category_root / (
            f"{source_path.name}_{suffix:02d}"
        )
        suffix += 1
    return candidate


def archive_existing_demo_path(
    source_path: Path,
    archive_root: Path,
    category: str,
) -> Path | None:
    if not source_path.exists():
        return None

    destination = archive_path_for_demo_run(
        source_path,
        archive_root,
        category,
    )
    shutil.move(
        str(source_path),
        str(destination),
    )
    return destination


def reset_session_for_new_demo_run(
    baseline_id: str,
    inspection_id: str,
) -> None:
    # Clear all video-derived widget and workflow state. Persisted AMD SSH
    # settings are intentionally reloaded from amd_cloud.json on rerun.
    for key in list(st.session_state.keys()):
        del st.session_state[key]

    st.session_state.current_step = 1
    st.session_state.completed_steps = []
    st.session_state.max_unlocked_step = 1
    st.session_state.baseline_id = baseline_id
    st.session_state.baseline_source_mode = (
        "Register local MP4 path"
    )
    st.session_state.baseline_local_video = ""
    st.session_state.baseline_fps = 4.0
    st.session_state.baseline_force_rebuild = False
    st.session_state.inspection_id = inspection_id
    st.session_state.inspection_source_mode = (
        "Register local file paths"
    )
    st.session_state.inspection_local_video = ""
    st.session_state.inspection_local_telemetry = ""
    st.session_state.inspection_force_register = False
    st.session_state.localization_fps = 4.0
    st.session_state.localization_force = False
    st.session_state.pair_top_k = 5
    st.session_state.pair_force = False
    st.session_state.amd_manual_frames = ""
    st.session_state.amd_force = False
    st.session_state.state_schema_version = STATE_SCHEMA_VERSION


def start_new_demo_run(
    baseline_id: str,
    inspection_id: str,
    archive_existing: bool,
) -> dict[str, Any]:
    baseline_id = validate_demo_run_id(
        baseline_id,
        "Baseline ID",
    )
    inspection_id = validate_demo_run_id(
        inspection_id,
        "Inspection ID",
    )

    reserved_inspection_ids = {
        "baseline",
        "shared",
        "backups",
        "_archive",
    }
    if inspection_id.lower() in reserved_inspection_ids:
        raise ValueError(
            "Inspection ID conflicts with a reserved project folder."
        )

    baseline_root = baseline_root_for(baseline_id)
    inspection_root = inspection_root_for(inspection_id)
    existing_targets = [
        path
        for path in (baseline_root, inspection_root)
        if path.exists()
    ]

    if existing_targets and not archive_existing:
        existing_text = "\n".join(
            str(path)
            for path in existing_targets
        )
        raise FileExistsError(
            "The selected Demo Run IDs already contain data. "
            "Enable archive mode or choose new IDs:\n"
            f"{existing_text}"
        )

    timestamp = datetime.now().astimezone().strftime(
        "%Y%m%d_%H%M%S"
    )
    archive_root = DEMO_ARCHIVE_ROOT / timestamp
    archived_items: list[dict[str, str]] = []

    if existing_targets:
        archive_root.mkdir(parents=True, exist_ok=True)
        baseline_archive = archive_existing_demo_path(
            baseline_root,
            archive_root,
            "baseline",
        )
        inspection_archive = archive_existing_demo_path(
            inspection_root,
            archive_root,
            "inspection",
        )
        for source, destination in (
            (baseline_root, baseline_archive),
            (inspection_root, inspection_archive),
        ):
            if destination is not None:
                archived_items.append({
                    "source": str(source),
                    "destination": str(destination),
                })

    CONFIG_ROOT.mkdir(parents=True, exist_ok=True)

    # Active baseline selection is video-derived state. Preserve a copy,
    # then clear it so the new baseline must be built and activated.
    if ACTIVE_BASELINE_PATH.is_file():
        archive_root.mkdir(parents=True, exist_ok=True)
        config_archive = archive_root / "config"
        config_archive.mkdir(parents=True, exist_ok=True)
        active_destination = (
            config_archive
            / ACTIVE_BASELINE_PATH.name
        )
        shutil.copy2(
            ACTIVE_BASELINE_PATH,
            active_destination,
        )
        ACTIVE_BASELINE_PATH.unlink()
        archived_items.append({
            "source": str(ACTIVE_BASELINE_PATH),
            "destination": str(active_destination),
        })

    amd_config = load_amd_config()
    amd_config["manual_frames"] = ""
    save_amd_config(amd_config)

    previous_run = current_demo_run_record()
    if previous_run:
        archive_root.mkdir(parents=True, exist_ok=True)
        config_archive = archive_root / "config"
        config_archive.mkdir(parents=True, exist_ok=True)
        previous_run_path = (
            config_archive
            / "previous_current_demo_run.json"
        )
        previous_run_path.write_text(
            json.dumps(
                previous_run,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    payload = {
        "status": "initialized",
        "app_version": APP_VERSION,
        "created_at": now_iso(),
        "baseline_id": baseline_id,
        "inspection_id": inspection_id,
        "baseline_video_path": "",
        "inspection_video_path": "",
        "inspection_telemetry_path": "",
        "archive_root": (
            str(archive_root)
            if archive_root.exists()
            else None
        ),
        "archived_items": archived_items,
        "preserved_configuration": [
            str(AMD_CONFIG_PATH),
            "Local Python environments",
            "FactoryFly source code",
        ],
    }
    CURRENT_DEMO_RUN_PATH.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    reset_session_for_new_demo_run(
        baseline_id,
        inspection_id,
    )
    return payload


# ---------------------------------------------------------------------
# Wizard state
# ---------------------------------------------------------------------
def initialize_state() -> None:
    configured_demo_run = current_demo_run_record()
    configured_baseline_id = str(
        configured_demo_run.get(
            "baseline_id",
            DEFAULT_BASELINE_ID,
        )
    ).strip() or DEFAULT_BASELINE_ID
    configured_inspection_id = str(
        configured_demo_run.get(
            "inspection_id",
            DEFAULT_INSPECTION_ID,
        )
    ).strip() or DEFAULT_INSPECTION_ID
    configured_baseline_video = str(
        configured_demo_run.get(
            "baseline_video_path",
            (
                ""
                if configured_demo_run
                else DEFAULT_BASELINE_VIDEO
            ),
        )
    )
    configured_inspection_video = str(
        configured_demo_run.get(
            "inspection_video_path",
            (
                ""
                if configured_demo_run
                else DEFAULT_INSPECTION_VIDEO
            ),
        )
    )
    configured_inspection_telemetry = str(
        configured_demo_run.get(
            "inspection_telemetry_path",
            (
                ""
                if configured_demo_run
                else DEFAULT_INSPECTION_TELEMETRY
            ),
        )
    )
    suggested_baseline_id, suggested_inspection_id = (
        default_demo_run_ids()
    )

    defaults = {
        "current_step": 1,
        "completed_steps": [],
        "baseline_id": configured_baseline_id,
        "baseline_source_mode": (
            "Register local MP4 path"
        ),
        "baseline_local_video": (
            configured_baseline_video
        ),
        "baseline_fps": 4.0,
        "baseline_force_rebuild": False,
        "inspection_id": configured_inspection_id,
        "inspection_source_mode": (
            "Register local file paths"
        ),
        "inspection_local_video": (
            configured_inspection_video
        ),
        "inspection_local_telemetry": (
            configured_inspection_telemetry
        ),
        "inspection_force_register": False,
        "localization_fps": 4.0,
        "localization_force": False,
        "pair_top_k": 5,
        "pair_force": False,
        "amd_execution_mode": "Run on Radeon Cloud via SSH",
        "amd_manual_frames": "",
        "amd_batch_pairs": 2,
        "amd_force": False,
        "amd_host": "",
        "amd_port": 22,
        "amd_user": "root",
        "amd_key_path": str(
            Path.home()
            / ".ssh"
            / "factoryfly_amd"
        ),
        "amd_remote_root": (
            "/workspace/factoryfly-radeon"
        ),
        "amd_remote_python": (
            "/workspace/factoryfly-radeon/"
            ".venv-rocm/bin/python"
        ),
        "amd_dinov2_repo": (
            "/workspace/factoryfly-radeon/vendor/dinov2"
        ),
        "amd_checkpoint": (
            "/workspace/factoryfly-radeon/vendor/checkpoints/"
            "dinov2_vits14_pretrain.pth"
        ),
        "new_demo_baseline_id": suggested_baseline_id,
        "new_demo_inspection_id": suggested_inspection_id,
        "new_demo_archive_existing": True,
        "new_demo_confirm": False,
        "state_schema_version": STATE_SCHEMA_VERSION,
    }

    previous_schema_version = st.session_state.get(
        "state_schema_version"
    )

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    # Always recover persisted AMD settings when the app schema changes or
    # when this browser session has not loaded v13 settings yet. Older widget
    # state can otherwise survive a Streamlit hot reload and override both
    # code defaults and the JSON configuration file.
    stored_amd_config = load_amd_config()
    config_state_map = {
        "execution_mode": "amd_execution_mode",
        "manual_frames": "amd_manual_frames",
        "batch_pairs": "amd_batch_pairs",
        "host": "amd_host",
        "port": "amd_port",
        "user": "amd_user",
        "key_path": "amd_key_path",
        "remote_root": "amd_remote_root",
        "remote_python": "amd_remote_python",
        "dinov2_repo": "amd_dinov2_repo",
        "checkpoint": "amd_checkpoint",
    }

    invalid_persisted_widget_state = (
        not str(st.session_state.get("amd_host", "")).strip()
        or int(st.session_state.get("amd_port", 1) or 1) <= 1
        or not str(st.session_state.get("amd_user", "")).strip()
        or not str(st.session_state.get("amd_key_path", "")).strip()
        or not str(st.session_state.get("amd_remote_root", "")).strip()
        or not str(st.session_state.get("amd_remote_python", "")).strip()
        or not str(st.session_state.get("amd_dinov2_repo", "")).strip()
        or not str(st.session_state.get("amd_checkpoint", "")).strip()
    )

    reload_amd_config = (
        previous_schema_version != STATE_SCHEMA_VERSION
        or not st.session_state.get(
            "_amd_config_loaded_v13",
            False,
        )
        or invalid_persisted_widget_state
    )

    if reload_amd_config:
        for config_key, state_key in config_state_map.items():
            stored_value = stored_amd_config.get(
                config_key,
                defaults[state_key],
            )

            if stored_value in {None, ""}:
                stored_value = defaults[state_key]

            if config_key in {"port", "batch_pairs"}:
                try:
                    stored_value = int(stored_value)
                except (TypeError, ValueError):
                    stored_value = defaults[state_key]

            st.session_state[state_key] = stored_value

        st.session_state["_amd_config_loaded_v13"] = True

    # Repair stale blank values left by older app versions.
    if previous_schema_version != STATE_SCHEMA_VERSION:
        migration_defaults = {
            "inspection_id": DEFAULT_INSPECTION_ID,
            "inspection_local_video": DEFAULT_INSPECTION_VIDEO,
            "inspection_local_telemetry": DEFAULT_INSPECTION_TELEMETRY,
        }

        for key, value in migration_defaults.items():
            current_value = str(
                st.session_state.get(key, "")
            ).strip()

            if not current_value:
                st.session_state[key] = value

        st.session_state.state_schema_version = (
            STATE_SCHEMA_VERSION
        )


def active_baseline_id() -> str:
    return str(
        st.session_state.get(
            "baseline_id",
            DEFAULT_BASELINE_ID,
        )
    ).strip()


def active_inspection_id() -> str:
    return str(
        st.session_state.get(
            "inspection_id",
            DEFAULT_INSPECTION_ID,
        )
    ).strip()


def synchronize_wizard_state() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    baseline_id = active_baseline_id()
    summary = (
        load_baseline_summary(baseline_id)
        if baseline_id
        else {}
    )

    completed: list[int] = []
    max_unlocked = 1

    if baseline_is_ready(summary):
        completed.append(1)
        max_unlocked = 2

        active_record = active_baseline_record()
        if (
            active_record.get("status") == "active"
            and active_record.get("baseline_id") == baseline_id
        ):
            completed.append(2)
            max_unlocked = 3

    inspection_id = active_inspection_id()
    manifest = (
        load_inspection_manifest(inspection_id)
        if inspection_id
        else {}
    )

    if (
        max_unlocked >= 3
        and inspection_is_ready(
            manifest,
            baseline_id,
        )
    ):
        completed.append(3)
        max_unlocked = 4

    localization_summary = (
        load_localization_summary(
            inspection_id,
            baseline_id,
        )
        if inspection_id and baseline_id
        else {}
    )

    if (
        max_unlocked >= 4
        and localization_is_ready(
            localization_summary,
            inspection_id,
            baseline_id,
        )
    ):
        completed.extend([4, 5])
        max_unlocked = 6

    pair_summary = (
        load_pair_refinement_summary(
            inspection_id,
            baseline_id,
        )
        if inspection_id and baseline_id
        else {}
    )

    if (
        max_unlocked >= 6
        and pair_refinement_is_ready(
            pair_summary,
            inspection_id,
            baseline_id,
        )
    ):
        completed.extend([6, 7])
        max_unlocked = 8

    amd_summary = (
        load_amd_run_summary(
            inspection_id,
            baseline_id,
        )
        if inspection_id and baseline_id
        else {}
    )

    if (
        max_unlocked >= 8
        and amd_analysis_is_ready(
            amd_summary,
            inspection_id,
            baseline_id,
        )
    ):
        completed.extend([8, 9])
        max_unlocked = 10

    if (
        max_unlocked >= 10
        and triage_is_ready(
            inspection_id,
            baseline_id,
        )
    ):
        completed.append(10)
        max_unlocked = 11

    if (
        max_unlocked >= 11
        and missions_are_ready(
            inspection_id,
            baseline_id,
        )
    ):
        completed.append(11)
        max_unlocked = 12

    if (
        max_unlocked >= 12
        and all_reinspection_missions_resolved(
            inspection_id,
            baseline_id,
        )
    ):
        completed.append(12)
        max_unlocked = 13

    report_payload = read_json(
        final_report_json_path_for(
            inspection_id,
            baseline_id,
        )
    )
    if (
        max_unlocked >= 13
        and report_payload.get("status") == "ready"
    ):
        completed.append(13)

    st.session_state.completed_steps = sorted(
        set(completed)
    )
    st.session_state.max_unlocked_step = max_unlocked

    current = int(
        st.session_state.get(
            "current_step",
            1,
        )
    )
    st.session_state.current_step = max(
        1,
        min(
            current,
            max_unlocked,
            len(STEP_NAMES),
        ),
    )

    return (
        summary,
        manifest,
        localization_summary,
        pair_summary,
        amd_summary,
    )

def complete_baseline_step(
    message: str,
) -> None:
    st.session_state.completed_steps = [1]
    st.session_state.max_unlocked_step = 2
    st.session_state.current_step = 2
    st.session_state["_flash"] = (
        "success",
        message,
    )
    st.rerun()


def complete_spatial_memory_step(
    baseline_id: str,
    summary: dict[str, Any],
) -> None:
    activate_baseline(
        baseline_id,
        summary,
    )
    st.session_state.completed_steps = [1, 2]
    st.session_state.max_unlocked_step = 3
    st.session_state.current_step = 3
    st.session_state["_flash"] = (
        "success",
        "Baseline activated. Inspection registration is now available.",
    )
    st.rerun()


def complete_localization_step(
    inspection_id: str,
    baseline_id: str,
) -> None:
    st.session_state.completed_steps = [
        1,
        2,
        3,
        4,
    ]
    st.session_state.max_unlocked_step = 5
    st.session_state.current_step = 5
    st.session_state["_flash"] = (
        "success",
        (
            "Inspection localized inside "
            f"{baseline_id}. Review the registration result."
        ),
    )
    st.rerun()


def complete_pair_refinement_step(
    inspection_id: str,
    baseline_id: str,
) -> None:
    st.session_state.completed_steps = [
        1,
        2,
        3,
        4,
        5,
        6,
    ]
    st.session_state.max_unlocked_step = 7
    st.session_state.current_step = 7
    st.session_state["_flash"] = (
        "success",
        (
            "Comparable baseline views were geometrically refined. "
            "Review the AMD-ready pairs."
        ),
    )
    st.rerun()


def complete_amd_analysis_step(
    inspection_id: str,
    baseline_id: str,
) -> None:
    st.session_state.completed_steps = list(
        range(
            1,
            9,
        )
    )
    st.session_state.max_unlocked_step = 9
    st.session_state.current_step = 9
    st.session_state["_flash"] = (
        "success",
        (
            "AMD Radeon analysis completed. "
            "Review semantic-change heatmaps and benchmarks."
        ),
    )
    st.rerun()


def navigate_to_step(
    step: int,
) -> None:
    if step <= int(
        st.session_state.max_unlocked_step
    ):
        st.session_state.current_step = step
        st.rerun()


def show_flash_message() -> None:
    flash = st.session_state.pop(
        "_flash",
        None,
    )

    if not flash:
        return

    level, message = flash
    getattr(
        st,
        level,
        st.info,
    )(message)


# ---------------------------------------------------------------------
# Styling and shell
# ---------------------------------------------------------------------
def apply_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --navy-950: #071624;
            --navy-900: #0b2134;
            --navy-800: #12344d;
            --teal-500: #00a6a6;
            --teal-600: #008f91;
            --slate-700: #334155;
            --slate-500: #64748b;
            --slate-300: #cbd5e1;
            --slate-200: #e2e8f0;
            --slate-100: #f1f5f9;
            --surface: #ffffff;
            --success: #16825d;
            --warning: #a25d00;
        }

        html, body, [class*="css"] {
            font-family:
                Inter, ui-sans-serif, -apple-system,
                BlinkMacSystemFont, "Segoe UI", sans-serif;
        }

        .stApp {
            background:
                radial-gradient(
                    circle at top right,
                    #e7f5f5 0,
                    transparent 30rem
                ),
                #f3f6f8;
        }

        header[data-testid="stHeader"],
        footer,
        #MainMenu {
            visibility: hidden;
        }

        .block-container {
            max-width: 1040px;
            padding: 1rem 1.2rem 2rem;
        }

        .app-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            background:
                linear-gradient(
                    135deg,
                    var(--navy-950),
                    var(--navy-800)
                );
            color: white;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px;
            padding: 1rem 1.15rem;
            margin-bottom: 0.8rem;
            box-shadow:
                0 8px 24px rgba(7, 22, 36, 0.14);
        }

        .app-header__eyebrow {
            color: #8be2df;
            font-size: 0.7rem;
            font-weight: 750;
            letter-spacing: 0.13em;
            text-transform: uppercase;
            margin-bottom: 0.14rem;
        }

        .app-header__title {
            font-size: 1.35rem;
            font-weight: 760;
            line-height: 1.2;
        }

        .app-header__subtitle {
            color: #c9d7e3;
            font-size: 0.8rem;
            margin-top: 0.25rem;
        }

        .status-pill {
            flex: 0 0 auto;
            display: inline-flex;
            align-items: center;
            gap: 0.42rem;
            padding: 0.36rem 0.62rem;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 680;
            border: 1px solid rgba(255,255,255,0.18);
            background: rgba(255,255,255,0.07);
        }

        .status-dot {
            width: 0.5rem;
            height: 0.5rem;
            border-radius: 50%;
            background: #95a4b0;
        }

        .status-dot.ready {
            background: #3ddc97;
            box-shadow:
                0 0 0 3px rgba(61,220,151,0.15);
        }

        .step-kicker {
            color: var(--teal-600);
            font-size: 0.73rem;
            font-weight: 780;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            margin-bottom: 0.12rem;
        }

        .step-title {
            color: var(--navy-900);
            font-size: 1.35rem;
            font-weight: 760;
            line-height: 1.25;
            margin-bottom: 0.18rem;
        }

        .step-description {
            color: var(--slate-500);
            font-size: 0.86rem;
            line-height: 1.48;
            margin-bottom: 0.8rem;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-color: #d8e1e8 !important;
            border-radius: 10px !important;
            background: rgba(255,255,255,0.94);
            box-shadow:
                0 4px 18px rgba(15,40,60,0.045);
        }

        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid var(--slate-200);
            border-radius: 9px;
            padding: 0.65rem 0.72rem;
            min-height: 5.2rem;
        }

        div[data-testid="stMetricLabel"] p {
            color: var(--slate-500);
            font-size: 0.74rem;
            line-height: 1.2;
        }

        div[data-testid="stMetricValue"] {
            color: var(--navy-900);
            font-size: 1.15rem;
        }

        .stButton > button,
        .stDownloadButton > button {
            border-radius: 7px;
            min-height: 2.45rem;
            font-weight: 680;
            border: 1px solid #b9c7d2;
        }

        .stButton > button[kind="primary"] {
            background: var(--teal-600);
            border-color: var(--teal-600);
            color: white;
        }

        .stButton > button[kind="primary"]:hover {
            background: #007b7d;
            border-color: #007b7d;
        }

        .stButton > button:disabled {
            opacity: 0.48;
        }

        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input {
            border-radius: 6px;
        }

        div[data-testid="stDataFrame"] {
            border: 1px solid var(--slate-200);
            border-radius: 8px;
            overflow: hidden;
        }

        .path-note {
            color: var(--slate-500);
            font-size: 0.76rem;
            line-height: 1.42;
            overflow-wrap: anywhere;
        }

        @media (max-width: 760px) {
            .block-container {
                max-width: 100%;
                padding-left: 0.7rem;
                padding-right: 0.7rem;
            }

            .app-header__subtitle {
                display: none;
            }

            .app-header__title {
                font-size: 1.05rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_new_demo_run_panel() -> None:
    current_run = current_demo_run_record()

    with st.expander(
        "Start New Demo Run",
        expanded=False,
    ):
        st.markdown(
            "Create a clean video-processing context without deleting "
            "previous runs or changing Radeon Cloud SSH settings."
        )

        current_left, current_right = st.columns(2)
        current_left.caption(
            "Current Baseline ID: "
            f"`{active_baseline_id() or 'Not selected'}`"
        )
        current_right.caption(
            "Current Inspection ID: "
            f"`{active_inspection_id() or 'Not selected'}`"
        )

        if current_run:
            st.caption(
                "Persisted Demo Run: "
                f"`{current_run.get('baseline_id', '')}` / "
                f"`{current_run.get('inspection_id', '')}`"
            )

        id_left, id_right = st.columns(2)
        with id_left:
            new_baseline_id = st.text_input(
                "New Baseline ID",
                key="new_demo_baseline_id",
                help=(
                    "A clean baseline folder will be used under "
                    "factoryfly-sentinel\\baseline."
                ),
            ).strip()
        with id_right:
            new_inspection_id = st.text_input(
                "New Inspection ID",
                key="new_demo_inspection_id",
                help=(
                    "A clean inspection folder will be used directly "
                    "under factoryfly-sentinel."
                ),
            ).strip()

        archive_existing = st.checkbox(
            "Archive folders when either selected ID already exists",
            key="new_demo_archive_existing",
            help=(
                "Existing folders with the same IDs are moved to "
                "_archive\\demo_runs instead of being deleted."
            ),
        )

        reset_columns = st.columns(2)
        with reset_columns[0]:
            st.markdown(
                "**Reset for the new videos**\n"
                "- Active baseline selection\n"
                "- Baseline and inspection input fields\n"
                "- Localization, pair, AMD, triage, mission, "
                "reinspection, and report workflow state\n"
                "- Uploaded-file and manual-pair widget state"
            )
        with reset_columns[1]:
            st.markdown(
                "**Preserved**\n"
                "- `shared/config/amd_cloud.json`\n"
                "- SSH host, port, user, key path, and remote paths\n"
                "- FactoryFly code and Python environments\n"
                "- Previous runs with different IDs"
            )

        confirmed = st.checkbox(
            "I understand that the workflow will return to Step 1.",
            key="new_demo_confirm",
        )

        validation_message = ""
        try:
            validate_demo_run_id(
                new_baseline_id,
                "Baseline ID",
            )
            validate_demo_run_id(
                new_inspection_id,
                "Inspection ID",
            )
        except ValueError as exception:
            validation_message = str(exception)

        if validation_message:
            st.warning(validation_message)

        start_clicked = st.button(
            "Start New Demo Run",
            type="primary",
            use_container_width=True,
            disabled=(
                not confirmed
                or bool(validation_message)
            ),
            key="start_new_demo_run",
        )

        if not start_clicked:
            return

        try:
            payload = start_new_demo_run(
                new_baseline_id,
                new_inspection_id,
                archive_existing,
            )
            st.session_state["_flash"] = (
                "success",
                "New Demo Run initialized. Add the new baseline "
                "video in Step 1.",
            )
            st.rerun()
        except Exception as exception:
            st.exception(exception)


def render_header(
    summary: dict[str, Any],
    inspection_manifest: dict[str, Any],
    localization_summary: dict[str, Any],
    pair_summary: dict[str, Any],
    amd_summary: dict[str, Any],
) -> None:
    baseline_ready = baseline_is_ready(
        summary
    )
    inspection_id = active_inspection_id()
    baseline_id = active_baseline_id()
    inspection_ready = inspection_is_ready(
        inspection_manifest,
        baseline_id,
    )
    localization_ready = localization_is_ready(
        localization_summary,
        inspection_id,
        baseline_id,
    )
    pair_ready = pair_refinement_is_ready(
        pair_summary,
        inspection_id,
        baseline_id,
    )
    amd_ready = amd_analysis_is_ready(
        amd_summary,
        inspection_id,
        baseline_id,
    )

    if amd_ready:
        dot_class = "ready"
        status_text = "AMD Results Ready"
    elif pair_ready:
        dot_class = "ready"
        status_text = "Pairs Ready"
    elif localization_ready:
        dot_class = "ready"
        status_text = "Localization Ready"
    elif inspection_ready:
        dot_class = "ready"
        status_text = "Inspection Ready"
    elif baseline_ready:
        dot_class = "ready"
        status_text = "Baseline Ready"
    else:
        dot_class = ""
        status_text = "Setup Required"

    st.markdown(
        f"""
        <div class="app-header">
            <div>
                <div class="app-header__eyebrow">
                    AMD-Accelerated Physical AI
                </div>
                <div class="app-header__title">
                    🛰️ FactoryFly Sentinel
                </div>
                <div class="app-header__subtitle">
                    Human-Guided Physical AI for Active Factory Inspection · v{APP_VERSION}
                </div>
            </div>
            <div class="status-pill">
                <span class="status-dot {dot_class}"></span>
                {status_text}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_step_navigation() -> None:
    current_step = int(
        st.session_state.current_step
    )
    max_unlocked = int(
        st.session_state.max_unlocked_step
    )
    completed = {
        int(item)
        for item in st.session_state.get(
            "completed_steps",
            [],
        )
    }

    step_numbers = list(
        STEP_NAMES
    )
    navigation_rows = [
        step_numbers[:5],
        step_numbers[5:],
    ]

    for row_steps in navigation_rows:
        if not row_steps:
            continue

        columns = st.columns(
            len(row_steps),
            gap="small",
        )

        for step, column in zip(
            row_steps,
            columns,
        ):
            is_locked = step > max_unlocked
            is_current = step == current_step
            is_complete = step in completed

            if is_complete:
                status_prefix = "✓"
            elif is_locked:
                status_prefix = "🔒"
            else:
                status_prefix = ""

            label = " ".join(
                item
                for item in (
                    status_prefix,
                    str(step),
                    STEP_NAMES[step],
                )
                if item
            )

            with column:
                if st.button(
                    label,
                    key=f"wizard_nav_{step}",
                    disabled=is_locked,
                    type=(
                        "primary"
                        if is_current
                        else "secondary"
                    ),
                    use_container_width=True,
                ):
                    navigate_to_step(step)

    progress_value = (
        (current_step - 1)
        / (len(STEP_NAMES) - 1)
        if len(STEP_NAMES) > 1
        else 1.0
    )

    st.progress(
        progress_value
    )

def render_step_intro(
    step: int,
    description: str,
) -> None:
    st.markdown(
        f"""
        <div class="step-kicker">
            Step {step} of {len(STEP_NAMES)}
        </div>
        <div class="step-title">
            {STEP_TITLES[step]}
        </div>
        <div class="step-description">
            {description}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------
# Step 1: Baseline registration
# ---------------------------------------------------------------------
def render_step_1() -> None:
    render_step_intro(
        1,
        (
            "Register a human-operated RGB flight and build "
            "a persistent COLMAP-based 3D baseline."
        ),
    )

    if not BASELINE_SCRIPT.is_file():
        st.error(
            "Baseline pipeline script was not found:\n"
            f"{BASELINE_SCRIPT}"
        )
        return

    with st.container(
        border=True
    ):
        baseline_id = st.text_input(
            "Baseline ID",
            key="baseline_id",
            help=(
                "A separate folder is created under "
                "factoryfly-sentinel\\baseline."
            ),
        ).strip()

        validation_error = ""

        if not baseline_id:
            validation_error = (
                "Baseline ID is required."
            )
        elif INVALID_WINDOWS_NAME.search(
            baseline_id
        ):
            validation_error = (
                "Baseline ID contains an invalid "
                "Windows filename character."
            )

        if validation_error:
            st.error(
                validation_error
            )

        baseline_root = (
            baseline_root_for(baseline_id)
            if baseline_id
            else BASELINE_PARENT
        )

        source_mode = st.radio(
            "Baseline video source",
            [
                "Register local MP4 path",
                "Upload MP4 in browser",
            ],
            horizontal=True,
            key="baseline_source_mode",
        )

        selected_video_path: Path | None = None
        uploaded_video = None

        if (
            source_mode
            == "Register local MP4 path"
        ):
            local_video_text = st.text_input(
                "Baseline MP4 path",
                key="baseline_local_video",
            )

            if local_video_text.strip():
                selected_video_path = Path(
                    local_video_text.strip()
                )

                if selected_video_path.is_file():
                    st.success(
                        "Video found: "
                        f"{selected_video_path.name}"
                    )
                else:
                    st.warning(
                        "The selected video path "
                        "does not exist."
                    )
        else:
            uploaded_video = st.file_uploader(
                "Upload Baseline MP4",
                type=[
                    "mp4",
                    "mov",
                    "mkv",
                    "avi",
                ],
                key="baseline_uploaded_video",
            )

            if uploaded_video is not None:
                st.info(
                    "Selected: "
                    f"{uploaded_video.name}"
                )

        control_left, control_right = (
            st.columns(2)
        )

        with control_left:
            fps = st.number_input(
                "Frame sampling FPS",
                min_value=1.0,
                max_value=10.0,
                step=1.0,
                key="baseline_fps",
            )

        with control_right:
            force_rebuild = st.checkbox(
                (
                    "Overwrite existing derived "
                    "baseline results"
                ),
                key="baseline_force_rebuild",
                help=(
                    "This removes frames, reconstruction, "
                    "poses, reports, and logs under the "
                    "selected Baseline ID."
                ),
            )

        st.markdown(
            '<div class="path-note">'
            f'Output folder: <code>{baseline_root}</code>'
            "</div>",
            unsafe_allow_html=True,
        )

        existing_summary = (
            load_baseline_summary(
                baseline_id
            )
            if baseline_id
            else {}
        )
        existing_ready = baseline_is_ready(
            existing_summary
        )

        if existing_ready:
            st.info(
                "A completed baseline already exists "
                "for this Baseline ID."
            )

            if st.button(
                "Open Existing Baseline Result",
                use_container_width=True,
                key="open_existing_result",
            ):
                st.session_state.current_step = 2
                st.session_state.max_unlocked_step = 2
                st.session_state.completed_steps = [1]
                st.rerun()

        can_build = (
            not validation_error
            and BASELINE_SCRIPT.is_file()
            and (
                (
                    selected_video_path is not None
                    and selected_video_path.is_file()
                )
                if (
                    source_mode
                    == "Register local MP4 path"
                )
                else uploaded_video is not None
            )
            and (
                not existing_ready
                or force_rebuild
            )
        )

        build_clicked = st.button(
            (
                "Rebuild 3D Baseline"
                if existing_ready
                else "Build 3D Baseline"
            ),
            type="primary",
            use_container_width=True,
            disabled=not can_build,
        )

    if not build_clicked:
        return

    try:
        if (
            source_mode
            == "Register local MP4 path"
        ):
            if (
                selected_video_path is None
                or not selected_video_path.is_file()
            ):
                raise FileNotFoundError(
                    "Select a valid Baseline MP4 path."
                )

            video_path = selected_video_path
        else:
            if uploaded_video is None:
                raise FileNotFoundError(
                    "Upload a Baseline MP4."
                )

            with st.status(
                "Saving uploaded Baseline MP4",
                expanded=True,
            ) as upload_status:
                video_path = save_uploaded_video(
                    uploaded_video,
                    baseline_root,
                )

                upload_status.update(
                    label="Baseline MP4 saved",
                    state="complete",
                )

        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(BASELINE_SCRIPT),
            "-BaselineRoot",
            str(baseline_root),
            "-VideoPath",
            str(video_path),
            "-Fps",
            str(fps),
        ]

        if force_rebuild:
            command.append(
                "-Force"
            )

        with st.expander(
            "Execution Command",
            expanded=False,
        ):
            st.code(
                subprocess.list2cmdline(
                    command
                ),
                language="powershell",
            )

        with st.status(
            "Building baseline spatial memory",
            expanded=True,
        ) as processing_status:
            return_code = run_process(
                command,
                PROJECT_ROOT,
            )

            if return_code != 0:
                processing_status.update(
                    label=(
                        "Baseline pipeline failed "
                        f"(exit code {return_code})"
                    ),
                    state="error",
                )

                st.error(
                    "Open the baseline logs to inspect "
                    "the failed stage."
                )
                return

            summary = load_baseline_summary(
                baseline_id
            )

            if not baseline_is_ready(
                summary
            ):
                processing_status.update(
                    label=(
                        "Pipeline completed, but the "
                        "baseline summary is not ready"
                    ),
                    state="error",
                )

                st.error(
                    "baseline_summary.json was not found "
                    "or does not contain a ready result."
                )
                return

            processing_status.update(
                label=(
                    "Baseline spatial memory completed"
                ),
                state="complete",
            )

        complete_baseline_step(
            "Baseline registration completed. "
            "The spatial-memory result is now available."
        )

    except Exception as exception:
        st.exception(
            exception
        )


# ---------------------------------------------------------------------
# Step 2: Baseline result
# ---------------------------------------------------------------------
def render_step_2() -> None:
    render_step_intro(
        2,
        (
            "Review registration coverage, sparse-map quality, "
            "generated assets, and reproducibility metadata. "
            "Activate this baseline before registering an inspection."
        ),
    )

    baseline_id = active_baseline_id()
    summary_path = summary_path_for(
        baseline_id
    )
    summary = read_json(
        summary_path
    )

    if not baseline_is_ready(
        summary
    ):
        st.warning(
            "The selected baseline is not ready. Complete Step 1 first."
        )

        if st.button(
            "Return to Baseline Registration",
            use_container_width=True,
        ):
            navigate_to_step(1)

        return

    st.success(
        "Baseline spatial memory is ready."
    )

    metric_columns = st.columns(4)
    metric_columns[0].metric(
        "Extracted Frames",
        summary.get("extracted_frames", "N/A"),
    )
    metric_columns[1].metric(
        "Registered Frames",
        summary.get("registered_frames", "N/A"),
    )
    metric_columns[2].metric(
        "Registration Rate",
        (
            f"{summary.get('registration_rate_percent')}%"
            if summary.get("registration_rate_percent") is not None
            else "N/A"
        ),
    )
    metric_columns[3].metric(
        "Sparse Points",
        summary.get("sparse_points", "N/A"),
    )

    with st.container(border=True):
        st.subheader("Baseline Assets")

        result_rows = {
            "Baseline ID": summary.get("baseline_id"),
            "Source Video": summary.get("source_video"),
            "Sampling FPS": summary.get("fps"),
            "Camera Model": summary.get("camera_model"),
            "Matching Method": summary.get("matching_method"),
            "Sparse Model Count": summary.get("sparse_model_count"),
            "Best Model": summary.get("best_model_path"),
            "Pose Export": summary.get("pose_export_path"),
            "Frame Directory": summary.get("frame_path"),
            "Completed At": summary.get("completed_at"),
        }

        with st.expander(
            "Baseline Metadata",
            expanded=False,
        ):
            st.json(result_rows)

        best_model_path = Path(
            summary.get("best_model_path", "")
        )

        if best_model_path.is_dir():
            model_files = [
                {
                    "file": path.name,
                    "size_bytes": path.stat().st_size,
                }
                for path in sorted(best_model_path.iterdir())
                if path.is_file()
            ]
            st.dataframe(
                model_files,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.warning(
                "The best-model directory recorded in the summary was not found."
            )

        action_left, action_right = st.columns(2)
        with action_left:
            st.download_button(
                label="Download baseline_summary.json",
                data=summary_path.read_bytes(),
                file_name=summary_path.name,
                mime="application/json",
                use_container_width=True,
            )
        with action_right:
            if st.button(
                "Back to Baseline Registration",
                use_container_width=True,
            ):
                navigate_to_step(1)

        active_record = active_baseline_record()
        already_active = (
            active_record.get("status") == "active"
            and active_record.get("baseline_id") == baseline_id
        )

        if already_active:
            st.success(
                f"Active baseline: {baseline_id}"
            )
            if st.button(
                "Continue to Inspection Registration",
                type="primary",
                use_container_width=True,
            ):
                st.session_state.current_step = 3
                st.rerun()
        else:
            if st.button(
                "Use This Baseline & Continue",
                type="primary",
                use_container_width=True,
            ):
                complete_spatial_memory_step(
                    baseline_id,
                    summary,
                )


# ---------------------------------------------------------------------
# Step 3: Inspection registration
# ---------------------------------------------------------------------
def render_step_3() -> None:
    render_step_intro(
        3,
        (
            "Register a free-route inspection flight and its matching "
            "telemetry against the active 3D baseline. This step creates "
            "a reproducible input manifest without rerunning localization yet."
        ),
    )

    baseline_id = active_baseline_id()
    active_record = active_baseline_record()

    if (
        active_record.get("status") != "active"
        or active_record.get("baseline_id") != baseline_id
    ):
        st.warning(
            "Activate the selected baseline in Step 2 before registering an inspection."
        )
        if st.button(
            "Return to Spatial Memory",
            use_container_width=True,
        ):
            navigate_to_step(2)
        return

    if not INSPECTION_REGISTRATION_SCRIPT.is_file():
        st.error(
            "Inspection registration script was not found:\n"
            f"{INSPECTION_REGISTRATION_SCRIPT}"
        )
        return

    with st.container(border=True):
        st.markdown(
            f"**Active baseline:** `{baseline_id}`"
        )

        if st.button(
            "Load Existing inspection_001 Inputs",
            key="restore_default_inspection_inputs",
            help=(
                "Restores the existing inspection ID, MP4 path, "
                "and DJI telemetry path used in this PoC."
            ),
        ):
            st.session_state.inspection_id = (
                DEFAULT_INSPECTION_ID
            )
            st.session_state.inspection_source_mode = (
                "Register local file paths"
            )
            st.session_state.inspection_local_video = (
                DEFAULT_INSPECTION_VIDEO
            )
            st.session_state.inspection_local_telemetry = (
                DEFAULT_INSPECTION_TELEMETRY
            )
            st.session_state.inspection_force_register = (
                True
            )
            st.rerun()

        inspection_id = st.text_input(
            "Inspection ID",
            key="inspection_id",
            help=(
                "A folder is created directly under "
                "factoryfly-sentinel, for example inspection_001."
            ),
        ).strip()

        validation_error = ""
        if not inspection_id:
            validation_error = "Inspection ID is required."
        elif INVALID_WINDOWS_NAME.search(inspection_id):
            validation_error = (
                "Inspection ID contains an invalid Windows filename character."
            )

        if validation_error:
            st.error(validation_error)

        inspection_root = (
            inspection_root_for(inspection_id)
            if inspection_id
            else PROJECT_ROOT
        )

        source_mode = st.radio(
            "Inspection input source",
            [
                "Register local file paths",
                "Upload files in browser",
            ],
            horizontal=True,
            key="inspection_source_mode",
        )

        selected_video_path: Path | None = None
        selected_telemetry_path: Path | None = None
        uploaded_video = None
        uploaded_telemetry = None

        if source_mode == "Register local file paths":
            local_video_text = st.text_input(
                "Inspection MP4 path",
                key="inspection_local_video",
            )
            local_telemetry_text = st.text_input(
                "Inspection telemetry path",
                key="inspection_local_telemetry",
            )

            if local_video_text.strip():
                selected_video_path = Path(local_video_text.strip())
                if selected_video_path.is_file():
                    st.success(
                        f"Video found: {selected_video_path.name}"
                    )
                else:
                    st.warning(
                        "The selected inspection video path does not exist."
                    )

            if local_telemetry_text.strip():
                selected_telemetry_path = Path(
                    local_telemetry_text.strip()
                )
                if selected_telemetry_path.is_file():
                    st.success(
                        f"Telemetry found: {selected_telemetry_path.name}"
                    )
                else:
                    st.warning(
                        "The selected telemetry path does not exist."
                    )
        else:
            upload_left, upload_right = st.columns(2)
            with upload_left:
                uploaded_video = st.file_uploader(
                    "Upload Inspection MP4",
                    type=["mp4", "mov", "mkv", "avi"],
                    key="inspection_uploaded_video",
                )
            with upload_right:
                uploaded_telemetry = st.file_uploader(
                    "Upload Inspection Telemetry",
                    type=["txt", "csv", "json", "srt"],
                    key="inspection_uploaded_telemetry",
                )

        force_register = st.checkbox(
            "Overwrite existing inspection manifest",
            key="inspection_force_register",
            help=(
                "This replaces input_manifest.json and inspection_config.json. "
                "Existing frames, localization, and analysis outputs are not deleted."
            ),
        )

        st.markdown(
            '<div class="path-note">'
            f'Output folder: <code>{inspection_root}</code>'
            "</div>",
            unsafe_allow_html=True,
        )

        existing_manifest = (
            load_inspection_manifest(inspection_id)
            if inspection_id
            else {}
        )
        existing_ready = inspection_is_ready(
            existing_manifest,
            baseline_id,
        )

        if existing_manifest and not existing_ready:
            old_baseline = existing_manifest.get(
                "baseline_id",
                "unknown",
            )
            st.warning(
                "An inspection manifest exists, but it is not valid for "
                f"the active baseline. Recorded baseline: {old_baseline}."
            )
        elif existing_ready:
            st.info(
                "This inspection is already registered against the active baseline."
            )

        can_register = (
            not validation_error
            and INSPECTION_REGISTRATION_SCRIPT.is_file()
            and (
                (
                    selected_video_path is not None
                    and selected_video_path.is_file()
                    and selected_telemetry_path is not None
                    and selected_telemetry_path.is_file()
                )
                if source_mode == "Register local file paths"
                else (
                    uploaded_video is not None
                    and uploaded_telemetry is not None
                )
            )
            and (
                not existing_manifest
                or force_register
            )
        )

        register_clicked = st.button(
            (
                "Re-register Inspection Inputs"
                if existing_manifest
                else "Register Inspection Inputs"
            ),
            type="primary",
            use_container_width=True,
            disabled=not can_register,
        )

        if existing_ready:
            manifest_path = inspection_manifest_path_for(
                inspection_id
            )
            st.success(
                "Inspection inputs are ready for spatial localization."
            )
            metric_left, metric_right = st.columns(2)
            video_info = existing_manifest.get("video") or {}
            telemetry_info = existing_manifest.get("telemetry") or {}
            metric_left.metric(
                "Video Size",
                f"{video_info.get('size_mb', 'N/A')} MB",
            )
            metric_right.metric(
                "Telemetry Size",
                f"{telemetry_info.get('size_mb', 'N/A')} MB",
            )
            with st.expander("Inspection Manifest"):
                st.json(existing_manifest)
            st.download_button(
                "Download input_manifest.json",
                data=manifest_path.read_bytes(),
                file_name=manifest_path.name,
                mime="application/json",
                use_container_width=True,
            )

            if st.button(
                "Continue to Spatial Localization",
                type="primary",
                use_container_width=True,
                key="continue_to_localization",
            ):
                navigate_to_step(4)

    if not register_clicked:
        st.caption(
            "Next implementation stage: localize the registered inspection "
            "inside the active baseline coordinate system."
        )
        return

    try:
        if source_mode == "Register local file paths":
            if (
                selected_video_path is None
                or selected_telemetry_path is None
            ):
                raise FileNotFoundError(
                    "Select valid inspection video and telemetry paths."
                )
            video_path = selected_video_path
            telemetry_path = selected_telemetry_path
        else:
            if uploaded_video is None or uploaded_telemetry is None:
                raise FileNotFoundError(
                    "Upload both the inspection MP4 and telemetry file."
                )
            with st.status(
                "Saving uploaded inspection files",
                expanded=True,
            ) as upload_status:
                video_path = save_uploaded_file(
                    uploaded_video,
                    inspection_root / "video",
                )
                telemetry_path = save_uploaded_file(
                    uploaded_telemetry,
                    inspection_root / "telemetry",
                )
                upload_status.update(
                    label="Inspection files saved",
                    state="complete",
                )

        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(INSPECTION_REGISTRATION_SCRIPT),
            "-ProjectRoot",
            str(PROJECT_ROOT),
            "-InspectionId",
            inspection_id,
            "-BaselineId",
            baseline_id,
            "-VideoPath",
            str(video_path),
            "-TelemetryPath",
            str(telemetry_path),
        ]

        if force_register:
            command.append("-Force")

        with st.expander("Execution Command", expanded=False):
            st.code(
                subprocess.list2cmdline(command),
                language="powershell",
            )

        with st.status(
            "Registering inspection inputs",
            expanded=True,
        ) as registration_status:
            return_code = run_process(
                command,
                PROJECT_ROOT,
            )

            if return_code != 0:
                registration_status.update(
                    label=(
                        "Inspection registration failed "
                        f"(exit code {return_code})"
                    ),
                    state="error",
                )
                return

            manifest = load_inspection_manifest(
                inspection_id
            )
            if not inspection_is_ready(
                manifest,
                baseline_id,
            ):
                registration_status.update(
                    label="Manifest was created but is not ready",
                    state="error",
                )
                st.error(
                    "input_manifest.json does not match the active baseline."
                )
                return

            registration_status.update(
                label="Inspection inputs registered",
                state="complete",
            )

        st.session_state["_flash"] = (
            "success",
            "Inspection registered against the active baseline. "
            "It is ready for spatial localization.",
        )
        st.rerun()

    except Exception as exception:
        st.exception(exception)



# ---------------------------------------------------------------------
# Step 4: Spatial localization
# ---------------------------------------------------------------------
def render_step_4() -> None:
    render_step_intro(
        4,
        (
            "Extract inspection frames, add them to a copy of the active "
            "baseline COLMAP database, match them against the baseline, "
            "and estimate their camera poses without moving the baseline "
            "coordinate system."
        ),
    )

    baseline_id = active_baseline_id()
    inspection_id = active_inspection_id()
    baseline_summary = load_baseline_summary(
        baseline_id
    )
    inspection_manifest = load_inspection_manifest(
        inspection_id
    )

    if not baseline_is_ready(
        baseline_summary
    ):
        st.error(
            "The active baseline is not ready."
        )
        return

    if not inspection_is_ready(
        inspection_manifest,
        baseline_id,
    ):
        st.error(
            "Register inspection inputs against the active baseline first."
        )
        return

    missing_scripts = [
        path
        for path in (
            LOCALIZATION_SCRIPT,
            LOCALIZATION_ANALYZER_SCRIPT,
        )
        if not path.is_file()
    ]
    if missing_scripts:
        st.error(
            "Localization backend file not found:\n"
            + "\n".join(
                str(path)
                for path in missing_scripts
            )
        )
        return

    localization_root = localization_root_for(
        inspection_id,
        baseline_id,
    )
    existing_summary = load_localization_summary(
        inspection_id,
        baseline_id,
    )
    existing_ready = localization_is_ready(
        existing_summary,
        inspection_id,
        baseline_id,
    )

    with st.container(
        border=True
    ):
        context_left, context_right = st.columns(2)
        context_left.markdown(
            f"**Active baseline:** `{baseline_id}`"
        )
        context_right.markdown(
            f"**Inspection:** `{inspection_id}`"
        )

        metric_left, metric_right = st.columns(2)
        with metric_left:
            fps = st.number_input(
                "Inspection frame sampling FPS",
                min_value=1.0,
                max_value=10.0,
                step=1.0,
                key="localization_fps",
                help=(
                    "The current PoC used 4 FPS. Existing frames are "
                    "re-extracted automatically when the source video or "
                    "sampling rate changes."
                ),
            )
        with metric_right:
            force_localization = st.checkbox(
                "Overwrite localization for this baseline",
                key="localization_force",
                help=(
                    "Deletes only localization outputs under this baseline. "
                    "The MP4, telemetry, and input manifest are preserved."
                ),
            )

        st.markdown(
            '<div class="path-note">'
            f'Output folder: <code>{localization_root}</code>'
            "</div>",
            unsafe_allow_html=True,
        )

        st.info(
            "The baseline database and sparse model are copied into an "
            "isolated work folder. The active baseline itself is not modified."
        )

        if existing_ready:
            st.success(
                "A completed localization result already exists for this "
                "inspection and baseline."
            )
            if st.button(
                "Open Existing Localization Result",
                use_container_width=True,
                key="open_localization_result",
            ):
                navigate_to_step(5)

        can_run = (
            not existing_ready
            or force_localization
        )

        run_clicked = st.button(
            (
                "Re-run Spatial Localization"
                if existing_ready
                else "Run Spatial Localization"
            ),
            type="primary",
            use_container_width=True,
            disabled=not can_run,
        )

    if not run_clicked:
        return

    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(LOCALIZATION_SCRIPT),
        "-ProjectRoot",
        str(PROJECT_ROOT),
        "-InspectionId",
        inspection_id,
        "-BaselineId",
        baseline_id,
        "-Fps",
        str(fps),
        "-PythonExe",
        sys.executable,
    ]

    if force_localization:
        command.append("-Force")

    with st.expander(
        "Execution Command",
        expanded=False,
    ):
        st.code(
            subprocess.list2cmdline(
                command
            ),
            language="powershell",
        )

    with st.status(
        "Localizing inspection frames",
        expanded=True,
    ) as localization_status:
        return_code = run_process(
            command,
            PROJECT_ROOT,
        )

        if return_code != 0:
            localization_status.update(
                label=(
                    "Spatial localization failed "
                    f"(exit code {return_code})"
                ),
                state="error",
            )
            st.error(
                "Review the localization logs shown above. "
                "The active baseline was not modified."
            )
            return

        result = load_localization_summary(
            inspection_id,
            baseline_id,
        )
        if not localization_is_ready(
            result,
            inspection_id,
            baseline_id,
        ):
            localization_status.update(
                label=(
                    "COLMAP completed, but no ready "
                    "localization summary was produced"
                ),
                state="error",
            )
            st.error(
                "localization_summary.json is missing or contains "
                "zero registered inspection frames."
            )
            return

        localization_status.update(
            label="Spatial localization completed",
            state="complete",
        )

    complete_localization_step(
        inspection_id,
        baseline_id,
    )


# ---------------------------------------------------------------------
# Step 5: Localization result
# ---------------------------------------------------------------------
def render_step_5() -> None:
    render_step_intro(
        5,
        (
            "Review how much of the free-route inspection was registered "
            "inside the persistent baseline coordinate system."
        ),
    )

    baseline_id = active_baseline_id()
    inspection_id = active_inspection_id()
    summary_path = localization_summary_path_for(
        inspection_id,
        baseline_id,
    )
    summary = load_localization_summary(
        inspection_id,
        baseline_id,
    )

    if not localization_is_ready(
        summary,
        inspection_id,
        baseline_id,
    ):
        st.warning(
            "No completed localization result was found."
        )
        if st.button(
            "Back to Spatial Localization",
            use_container_width=True,
        ):
            navigate_to_step(4)
        return

    st.success(
        "Inspection camera poses are registered in the active baseline "
        "coordinate system."
    )

    longest_run = (
        summary.get("longest_continuous_run")
        or {}
    )
    metric_columns = st.columns(5)
    metric_columns[0].metric(
        "Input Frames",
        summary.get(
            "input_frames",
            "N/A",
        ),
    )
    metric_columns[1].metric(
        "Registered",
        summary.get(
            "registered_frames",
            "N/A",
        ),
    )
    metric_columns[2].metric(
        "Registration Rate",
        (
            f"{summary.get('registration_rate_percent')}%"
            if summary.get(
                "registration_rate_percent"
            ) is not None
            else "N/A"
        ),
    )
    metric_columns[3].metric(
        "Failed",
        summary.get(
            "failed_frames",
            "N/A",
        ),
    )
    metric_columns[4].metric(
        "Longest Run",
        longest_run.get(
            "length",
            "N/A",
        ),
    )

    with st.container(
        border=True
    ):
        st.subheader(
            "Localization Assets"
        )

        details = {
            "Inspection ID": inspection_id,
            "Baseline ID": baseline_id,
            "Frames": summary.get(
                "frame_path"
            ),
            "Work Database": summary.get(
                "database_path"
            ),
            "Registered Model": summary.get(
                "registered_model_path"
            ),
            "Model TXT": summary.get(
                "model_txt_path"
            ),
            "Pose CSV": summary.get(
                "inspection_pose_csv"
            ),
            "Timeline CSV": summary.get(
                "registration_timeline_csv"
            ),
            "Completed At": summary.get(
                "completed_at"
            ),
            "Duration Seconds": summary.get(
                "duration_seconds"
            ),
        }

        with st.expander(
            "Localization Metadata",
            expanded=False,
        ):
            st.json(
                details
            )

        timeline_path = Path(
            summary.get(
                "registration_timeline_csv",
                "",
            )
        )

        if timeline_path.is_file():
            timeline_rows: list[dict[str, Any]] = []
            with timeline_path.open(
                encoding="utf-8-sig",
                newline="",
            ) as timeline_file:
                reader = csv.DictReader(
                    timeline_file
                )
                for row in reader:
                    timeline_rows.append(
                        {
                            "frame": row.get(
                                "frame_number"
                            ),
                            "filename": row.get(
                                "filename"
                            ),
                            "registered": (
                                "Yes"
                                if str(
                                    row.get(
                                        "registered",
                                        "0",
                                    )
                                )
                                == "1"
                                else "No"
                            ),
                        }
                    )

            if timeline_rows:
                st.caption(
                    "Registration timeline preview"
                )
                st.dataframe(
                    timeline_rows[:80],
                    use_container_width=True,
                    hide_index=True,
                )

        download_left, download_right = st.columns(2)
        with download_left:
            st.download_button(
                "Download localization_summary.json",
                data=summary_path.read_bytes(),
                file_name=summary_path.name,
                mime="application/json",
                use_container_width=True,
            )
        with download_right:
            if timeline_path.is_file():
                st.download_button(
                    "Download registration_timeline.csv",
                    data=timeline_path.read_bytes(),
                    file_name=timeline_path.name,
                    mime="text/csv",
                    use_container_width=True,
                )

        action_left, action_right = st.columns(2)

        with action_left:
            if st.button(
                "Back to Spatial Localization",
                use_container_width=True,
            ):
                navigate_to_step(4)

        with action_right:
            if st.button(
                "Continue to Pair Refinement",
                type="primary",
                use_container_width=True,
            ):
                navigate_to_step(6)

    st.caption(
        "Next implementation stage: retrieve comparable baseline views, "
        "perform geometric refinement, and prepare AMD DINOv2 inputs."
    )



# ---------------------------------------------------------------------
# Step 6: Pair refinement
# ---------------------------------------------------------------------
def render_step_6() -> None:
    render_step_intro(
        6,
        (
            "Retrieve the five nearest baseline views for every localized "
            "inspection frame, then re-rank them with SIFT, fundamental "
            "matrix RANSAC, homography RANSAC, overlap, and reprojection "
            "quality."
        ),
    )

    baseline_id = active_baseline_id()
    inspection_id = active_inspection_id()
    localization_summary = load_localization_summary(
        inspection_id,
        baseline_id,
    )

    if not localization_is_ready(
        localization_summary,
        inspection_id,
        baseline_id,
    ):
        st.error(
            "Complete spatial localization first."
        )
        return

    missing_scripts = [
        path
        for path in (
            PAIR_REFINEMENT_SCRIPT,
            POSE_CANDIDATE_SCRIPT,
            GEOMETRIC_REFINEMENT_SCRIPT,
        )
        if not path.is_file()
    ]
    if missing_scripts:
        st.error(
            "Pair-refinement backend file not found:\n"
            + "\n".join(
                str(path)
                for path in missing_scripts
            )
        )
        return

    output_root = pair_refinement_root_for(
        inspection_id,
        baseline_id,
    )
    existing_summary = load_pair_refinement_summary(
        inspection_id,
        baseline_id,
    )
    existing_ready = pair_refinement_is_ready(
        existing_summary,
        inspection_id,
        baseline_id,
    )

    with st.container(
        border=True
    ):
        context_left, context_right = st.columns(2)
        context_left.markdown(
            f"**Active baseline:** `{baseline_id}`"
        )
        context_right.markdown(
            f"**Localized inspection:** `{inspection_id}`"
        )

        option_left, option_right = st.columns(2)
        with option_left:
            top_k = st.number_input(
                "Pose candidates per inspection frame",
                min_value=3,
                max_value=10,
                step=1,
                key="pair_top_k",
                help=(
                    "Top-5 is the validated PoC setting. More candidates "
                    "increase runtime and may rescue difficult viewpoints."
                ),
            )
        with option_right:
            force_refinement = st.checkbox(
                "Overwrite pair refinement for this baseline",
                key="pair_force",
                help=(
                    "Deletes only this baseline's pair-refinement outputs. "
                    "Localization, source videos, and the active baseline "
                    "are preserved."
                ),
            )

        st.markdown(
            '<div class="path-note">'
            f'Output folder: <code>{output_root}</code>'
            "</div>",
            unsafe_allow_html=True,
        )

        localized_frames = int(
            localization_summary.get(
                "registered_frames",
                0,
            )
            or 0
        )
        st.info(
            f"{localized_frames} localized inspection frames × "
            f"Top-{int(top_k)} candidates = up to "
            f"{localized_frames * int(top_k):,} geometric evaluations."
        )

        if existing_ready:
            st.success(
                "A completed refined-pair result already exists for this "
                "inspection and baseline."
            )
            if st.button(
                "Open Existing Pair Result",
                use_container_width=True,
                key="open_pair_result",
            ):
                navigate_to_step(7)

        can_run = (
            not existing_ready
            or force_refinement
        )

        run_clicked = st.button(
            (
                "Re-run Pair Refinement"
                if existing_ready
                else "Run Pair Refinement"
            ),
            type="primary",
            use_container_width=True,
            disabled=not can_run,
        )

    if not run_clicked:
        return

    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(PAIR_REFINEMENT_SCRIPT),
        "-ProjectRoot",
        str(PROJECT_ROOT),
        "-InspectionId",
        inspection_id,
        "-BaselineId",
        baseline_id,
        "-TopK",
        str(int(top_k)),
        "-PythonExe",
        sys.executable,
    ]

    if force_refinement:
        command.append("-Force")

    with st.expander(
        "Execution Command",
        expanded=False,
    ):
        st.code(
            subprocess.list2cmdline(
                command
            ),
            language="powershell",
        )

    with st.status(
        "Retrieving and refining comparable baseline views",
        expanded=True,
    ) as refinement_status:
        return_code = run_process(
            command,
            PROJECT_ROOT,
        )

        if return_code != 0:
            refinement_status.update(
                label=(
                    "Pair refinement failed "
                    f"(exit code {return_code})"
                ),
                state="error",
            )
            st.error(
                "Review the logs shown above. Localization and the active "
                "baseline were not modified."
            )
            return

        result = load_pair_refinement_summary(
            inspection_id,
            baseline_id,
        )
        if not pair_refinement_is_ready(
            result,
            inspection_id,
            baseline_id,
        ):
            refinement_status.update(
                label=(
                    "Pair refinement completed, but no ready summary "
                    "was produced"
                ),
                state="error",
            )
            st.error(
                "refinement_summary.json is missing or contains no "
                "evaluated candidates."
            )
            return

        refinement_status.update(
            label="Pair refinement completed",
            state="complete",
        )

    complete_pair_refinement_step(
        inspection_id,
        baseline_id,
    )


# ---------------------------------------------------------------------
# Step 7: Pair-refinement result
# ---------------------------------------------------------------------
def render_step_7() -> None:
    render_step_intro(
        7,
        (
            "Review the best historical view selected for each localized "
            "inspection frame and identify the pairs that are ready for "
            "AMD-accelerated semantic change analysis."
        ),
    )

    baseline_id = active_baseline_id()
    inspection_id = active_inspection_id()
    summary_path = pair_refinement_summary_path_for(
        inspection_id,
        baseline_id,
    )
    summary = load_pair_refinement_summary(
        inspection_id,
        baseline_id,
    )

    if not pair_refinement_is_ready(
        summary,
        inspection_id,
        baseline_id,
    ):
        st.warning(
            "No completed pair-refinement result was found."
        )
        if st.button(
            "Back to Pair Refinement",
            use_container_width=True,
        ):
            navigate_to_step(6)
        return

    st.success(
        "Comparable baseline views were selected and geometrically "
        "validated."
    )

    quality_counts = (
        summary.get("quality_counts")
        or {}
    )
    metrics = st.columns(6)
    metrics[0].metric(
        "Inspection Frames",
        summary.get(
            "inspection_frames",
            "N/A",
        ),
    )
    metrics[1].metric(
        "Candidates",
        summary.get(
            "evaluated_candidates",
            "N/A",
        ),
    )
    metrics[2].metric(
        "Excellent",
        quality_counts.get(
            "excellent",
            0,
        ),
    )
    metrics[3].metric(
        "Good",
        quality_counts.get(
            "good",
            0,
        ),
    )
    metrics[4].metric(
        "Usable",
        quality_counts.get(
            "usable",
            0,
        ),
    )
    metrics[5].metric(
        "AMD-ready",
        summary.get(
            "amd_ready_pairs",
            summary.get(
                "non_poor_pairs",
                0,
            ),
        ),
    )

    output_root = pair_refinement_root_for(
        inspection_id,
        baseline_id,
    )
    outputs = (
        summary.get("outputs")
        or {}
    )
    refined_pairs_path = Path(
        outputs.get(
            "refined_pairs",
            output_root / "refined_pairs.csv",
        )
    )
    all_scores_path = Path(
        outputs.get(
            "all_candidate_scores",
            output_root
            / "all_candidate_refinement_scores.csv",
        )
    )
    amd_ready_path = Path(
        outputs.get(
            "amd_ready_pairs",
            output_root / "amd_ready_pairs.csv",
        )
    )
    candidate_path = Path(
        outputs.get(
            "pose_candidates",
            output_root / "pose_candidates_topk.csv",
        )
    )
    preview_root = Path(
        outputs.get(
            "preview_directory",
            output_root / "previews",
        )
    )

    rows: list[dict[str, str]] = []
    if refined_pairs_path.is_file():
        with refined_pairs_path.open(
            encoding="utf-8-sig",
            newline="",
        ) as pairs_file:
            rows = list(
                csv.DictReader(
                    pairs_file
                )
            )

    def row_number(
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

    quality_rank = {
        "excellent": 3,
        "good": 2,
        "usable": 1,
        "poor": 0,
    }
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            -quality_rank.get(
                row.get(
                    "quality",
                    "poor",
                ),
                0,
            ),
            -row_number(
                row,
                "refinement_score",
            ),
        ),
    )

    with st.container(
        border=True
    ):
        st.subheader(
            "Demo Target Coverage"
        )

        target_frames = {
            101,
            122,
            195,
            196,
            204,
        }
        target_rows = [
            {
                "frame": row.get(
                    "inspection_frame_number"
                ),
                "quality": row.get(
                    "quality"
                ),
                "baseline": row.get(
                    "baseline_name"
                ),
                "selected_rank": row.get(
                    "candidate_rank"
                ),
                "mutual_matches": row.get(
                    "mutual_matches"
                ),
                "F_ratio": row.get(
                    "fundamental_inlier_ratio"
                ),
                "H_ratio": row.get(
                    "homography_inlier_ratio"
                ),
                "overlap": row.get(
                    "overlap_ratio"
                ),
                "reprojection_px": row.get(
                    "median_reprojection_error"
                ),
            }
            for row in rows
            if int(
                row_number(
                    row,
                    "inspection_frame_number",
                    -1,
                )
            )
            in target_frames
        ]

        if target_rows:
            st.dataframe(
                sorted(
                    target_rows,
                    key=lambda item: int(
                        item["frame"]
                    ),
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info(
                "The five tracked demo frames are not present in the "
                "refined-pair CSV."
            )

    preview_rows = [
        row
        for row in sorted_rows
        if row.get(
            "quality"
        )
        in {
            "excellent",
            "good",
            "usable",
        }
    ][:12]

    if preview_rows:
        st.subheader(
            "Top Alignment Previews"
        )
        preview_columns = st.columns(2)

        for index, row in enumerate(
            preview_rows
        ):
            frame_number = int(
                row_number(
                    row,
                    "inspection_frame_number",
                )
            )
            quality = row.get(
                "quality",
                "unknown",
            )
            preview_path = (
                preview_root
                / (
                    f"frame_{frame_number:06d}"
                    f"_{quality}.jpg"
                )
            )

            with preview_columns[
                index % 2
            ]:
                with st.container(
                    border=True
                ):
                    st.markdown(
                        f"**Frame {frame_number} · "
                        f"{quality.upper()}**"
                    )
                    st.caption(
                        (
                            f"Baseline {row.get('baseline_name')} · "
                            f"rank {row.get('candidate_rank')} · "
                            f"matches {row.get('mutual_matches')} · "
                            f"overlap {row.get('overlap_ratio')}"
                        )
                    )
                    if preview_path.is_file():
                        st.image(
                            str(preview_path),
                            use_container_width=True,
                        )
                    else:
                        st.warning(
                            f"Preview not found: {preview_path.name}"
                        )

    with st.container(
        border=True
    ):
        st.subheader(
            "Pair-Refinement Assets"
        )

        metadata = {
            "Inspection ID": inspection_id,
            "Baseline ID": baseline_id,
            "Top K": summary.get(
                "top_k"
            ),
            "Median Baseline Step": summary.get(
                "median_baseline_step"
            ),
            "Non-poor Pairs": summary.get(
                "non_poor_pairs"
            ),
            "High-confidence Pairs": summary.get(
                "high_confidence_pairs"
            ),
            "Median Refinement Score": summary.get(
                "median_refinement_score"
            ),
            "Median Reprojection Error": summary.get(
                "median_reprojection_error"
            ),
            "Duration Seconds": summary.get(
                "duration_seconds"
            ),
            "Completed At": summary.get(
                "completed_at"
            ),
        }

        with st.expander(
            "Pair Metadata",
            expanded=False,
        ):
            st.json(
                metadata
            )

        download_columns = st.columns(3)

        with download_columns[0]:
            st.download_button(
                "Download refinement_summary.json",
                data=summary_path.read_bytes(),
                file_name=summary_path.name,
                mime="application/json",
                use_container_width=True,
            )

        with download_columns[1]:
            if refined_pairs_path.is_file():
                st.download_button(
                    "Download refined_pairs.csv",
                    data=refined_pairs_path.read_bytes(),
                    file_name=refined_pairs_path.name,
                    mime="text/csv",
                    use_container_width=True,
                )

        with download_columns[2]:
            if amd_ready_path.is_file():
                st.download_button(
                    "Download AMD-ready pairs",
                    data=amd_ready_path.read_bytes(),
                    file_name=amd_ready_path.name,
                    mime="text/csv",
                    use_container_width=True,
                )

        with st.expander(
            "All output paths",
            expanded=False,
        ):
            st.json(
                {
                    "Pose candidates": str(
                        candidate_path
                    ),
                    "Refined pairs": str(
                        refined_pairs_path
                    ),
                    "All candidate scores": str(
                        all_scores_path
                    ),
                    "AMD-ready pairs": str(
                        amd_ready_path
                    ),
                    "Preview directory": str(
                        preview_root
                    ),
                }
            )

        action_left, action_right = st.columns(2)

        with action_left:
            if st.button(
                "Back to Pair Refinement",
                use_container_width=True,
            ):
                navigate_to_step(6)

        with action_right:
            if st.button(
                "Continue to AMD Analysis",
                type="primary",
                use_container_width=True,
            ):
                navigate_to_step(8)

    st.caption(
        "Next stage: package geometry-ready pairs, transfer them through "
        "SSH to Radeon Cloud, run DINOv2, and retrieve heatmaps and "
        "benchmarks."
    )



# ---------------------------------------------------------------------
# Step 8: AMD semantic analysis
# ---------------------------------------------------------------------
def render_step_8() -> None:
    render_step_intro(
        8,
        (
            "Package geometrically usable pairs, optionally include "
            "reviewed borderline frames, transfer the package through "
            "SSH, run DINOv2 on AMD Radeon with ROCm, and retrieve "
            "semantic-change heatmaps and inference benchmarks."
        ),
    )

    baseline_id = active_baseline_id()
    inspection_id = active_inspection_id()
    pair_summary = load_pair_refinement_summary(
        inspection_id,
        baseline_id,
    )

    if not pair_refinement_is_ready(
        pair_summary,
        inspection_id,
        baseline_id,
    ):
        st.error(
            "Complete pair refinement first."
        )
        return

    missing_scripts = [
        path
        for path in (
            AMD_ANALYSIS_SCRIPT,
            AMD_PACKAGE_SCRIPT,
            AMD_REMOTE_SCRIPT,
        )
        if not path.is_file()
    ]
    if missing_scripts:
        st.error(
            "AMD backend file not found:\n"
            + "\n".join(
                str(path)
                for path in missing_scripts
            )
        )
        return

    analysis_root = amd_analysis_root_for(
        inspection_id,
        baseline_id,
    )
    current_summary = load_amd_run_summary(
        inspection_id,
        baseline_id,
    )
    current_ready = amd_analysis_is_ready(
        current_summary,
        inspection_id,
        baseline_id,
    )

    with st.container(
        border=True
    ):
        context_left, context_right = st.columns(2)
        context_left.markdown(
            f"**Inspection:** `{inspection_id}`"
        )
        context_right.markdown(
            f"**Baseline:** `{baseline_id}`"
        )

        st.radio(
            "Execution mode",
            [
                "Run on Radeon Cloud via SSH",
                "Prepare package only",
            ],
            horizontal=True,
            key="amd_execution_mode",
        )

        selected_borderline_frames = render_borderline_pair_selector(
            inspection_id,
            baseline_id,
        )

        st.number_input(
            "Inference batch size in pairs",
            min_value=1,
            max_value=8,
            step=1,
            key="amd_batch_pairs",
            help=(
                "Each pair contains two images. Batch size 2 matches "
                "the validated Radeon Cloud smoke test."
            ),
        )

        st.info(
            (
                f"{pair_summary.get('amd_ready_pairs', 0)} geometry-ready "
                "pairs are included automatically. "
                f"{len(selected_borderline_frames)} reviewer-selected borderline "
                "frame(s) will be requested; the package builder includes them "
                "only when a valid homography exists."
            )
        )

        with st.expander(
            "Radeon Cloud SSH Settings",
            expanded=(
                st.session_state.amd_execution_mode
                == "Run on Radeon Cloud via SSH"
            ),
        ):
            st.caption(
                f"Saved configuration: `{AMD_CONFIG_PATH}`"
            )
            st.button(
                "Reload saved SSH settings",
                key="reload_amd_ssh_settings",
                on_click=load_amd_config_into_session,
                use_container_width=True,
            )

            ssh_left, ssh_middle, ssh_right = st.columns(
                [2, 1, 1]
            )
            with ssh_left:
                st.text_input(
                    "SSH host or alias",
                    key="amd_host",
                    placeholder=(
                        "Enter the external SSH host shown by "
                        "Radeon Cloud"
                    ),
                )
            with ssh_middle:
                st.number_input(
                    "SSH port",
                    min_value=1,
                    max_value=65535,
                    step=1,
                    key="amd_port",
                )
            with ssh_right:
                st.text_input(
                    "SSH user",
                    key="amd_user",
                )

            st.text_input(
                "Private key path",
                key="amd_key_path",
                help=(
                    "The key file remains on this computer. "
                    "Its contents are never stored in the project."
                ),
            )
            st.text_input(
                "Remote project root",
                key="amd_remote_root",
            )
            st.text_input(
                "Remote ROCm Python",
                key="amd_remote_python",
            )
            st.text_input(
                "Remote DINOv2 repository",
                key="amd_dinov2_repo",
            )
            st.text_input(
                "Remote DINOv2 checkpoint",
                key="amd_checkpoint",
            )

            if st.button(
                "Save SSH Settings",
                use_container_width=True,
            ):
                host_value = str(
                    st.session_state.amd_host
                ).strip()
                user_value = str(
                    st.session_state.amd_user
                ).strip()

                if not host_value:
                    st.error(
                        "SSH host is blank. Settings were not overwritten."
                    )
                elif not user_value:
                    st.error(
                        "SSH user is blank. Settings were not overwritten."
                    )
                else:
                    save_amd_config(
                        {
                            "execution_mode": str(
                                st.session_state.amd_execution_mode
                            ),
                            "manual_frames": str(
                                st.session_state.amd_manual_frames
                            ).strip(),
                            "batch_pairs": int(
                                st.session_state.amd_batch_pairs
                            ),
                            "host": host_value,
                            "port": int(
                                st.session_state.amd_port
                            ),
                            "user": user_value,
                            "key_path": str(
                                st.session_state.amd_key_path
                            ).strip(),
                            "remote_root": str(
                                st.session_state.amd_remote_root
                            ).strip(),
                            "remote_python": str(
                                st.session_state.amd_remote_python
                            ).strip(),
                            "dinov2_repo": str(
                                st.session_state.amd_dinov2_repo
                            ).strip(),
                            "checkpoint": str(
                                st.session_state.amd_checkpoint
                            ).strip(),
                        }
                    )
                    st.success(
                        "SSH settings saved. Only the private-key path is stored; key contents are never copied."
                    )

        cloud_mode = (
            st.session_state.amd_execution_mode
            == "Run on Radeon Cloud via SSH"
        )
        output_root = (
            analysis_root
            if cloud_mode
            else amd_preview_root_for(
                inspection_id,
                baseline_id,
            )
        )

        if cloud_mode:
            st.checkbox(
                "Overwrite the current AMD package and result",
                key="amd_force",
                help=(
                    "Deletes only the current AMD analysis workspace. "
                    "Baseline, inspection, localization, and pair refinement "
                    "remain unchanged."
                ),
            )
        else:
            st.info(
                "Package preview is isolated from the completed AMD result. "
                "Preparing it replaces only amd_analysis\\preview; "
                "amd_analysis\\current remains unchanged."
            )

        st.markdown(
            '<div class="path-note">'
            f'Output folder: <code>{output_root}</code>'
            "</div>",
            unsafe_allow_html=True,
        )

        if current_ready:
            st.success(
                "A completed AMD result already exists and will be preserved "
                "unless cloud mode is explicitly overwritten."
            )
            if st.button(
                "Open Existing AMD Result",
                use_container_width=True,
                key="open_existing_amd_result",
            ):
                navigate_to_step(9)

        host_missing = (
            cloud_mode
            and not str(
                st.session_state.amd_host
            ).strip()
        )
        key_missing = (
            cloud_mode
            and not Path(
                str(
                    st.session_state.amd_key_path
                )
            ).expanduser().is_file()
        )

        if host_missing:
            st.warning(
                "Enter the external SSH host or SSH-config alias shown "
                "for the active Radeon Cloud instance."
            )

        if key_missing:
            st.warning(
                "The configured private key file was not found locally."
            )

        can_run = True
        if cloud_mode:
            can_run = (
                (not current_ready or st.session_state.amd_force)
                and not host_missing
                and not key_missing
            )

        run_clicked = st.button(
            (
                "Run AMD Analysis"
                if cloud_mode
                else "Prepare Preview Package"
            ),
            type="primary",
            use_container_width=True,
            disabled=not can_run,
        )

    package_display_root = (
        analysis_root
        if cloud_mode
        else amd_preview_root_for(
            inspection_id,
            baseline_id,
        )
    )
    package_summary_path = (
        package_display_root
        / "package"
        / "package_summary.json"
    )
    package_zip_path = (
        package_display_root
        / "factoryfly_amd_package.zip"
    )

    if package_summary_path.is_file():
        package_summary = read_json(
            package_summary_path
        )

        with st.container(
            border=True
        ):
            st.subheader(
                "Prepared Package"
            )
            package_metrics = st.columns(4)
            package_metrics[0].metric(
                "Selected Pairs",
                package_summary.get(
                    "selected_pairs",
                    "N/A",
                ),
            )
            package_metrics[1].metric(
                "Automatic",
                package_summary.get(
                    "automatic_pairs",
                    "N/A",
                ),
            )
            package_metrics[2].metric(
                "Manual Borderline",
                package_summary.get(
                    "manual_pairs",
                    "N/A",
                ),
            )
            package_metrics[3].metric(
                "Archive Size",
                (
                    f"{package_zip_path.stat().st_size / 1024 / 1024:.1f} MB"
                    if package_zip_path.is_file()
                    else "N/A"
                ),
            )

            if package_zip_path.is_file():
                st.download_button(
                    "Download AMD Input Package",
                    data=package_zip_path.read_bytes(),
                    file_name=package_zip_path.name,
                    mime="application/zip",
                    use_container_width=True,
                )

    if not run_clicked:
        return

    # Persist the current values automatically before every run so the user
    # does not need to press Save SSH Settings separately.
    if cloud_mode:
        save_amd_config(
            {
                "execution_mode": str(
                    st.session_state.amd_execution_mode
                ),
                "manual_frames": str(
                    st.session_state.amd_manual_frames
                ).strip(),
                "batch_pairs": int(
                    st.session_state.amd_batch_pairs
                ),
                "host": str(
                    st.session_state.amd_host
                ).strip(),
                "port": int(
                    st.session_state.amd_port
                ),
                "user": str(
                    st.session_state.amd_user
                ).strip(),
                "key_path": str(
                    st.session_state.amd_key_path
                ).strip(),
                "remote_root": str(
                    st.session_state.amd_remote_root
                ).strip(),
                "remote_python": str(
                    st.session_state.amd_remote_python
                ).strip(),
                "dinov2_repo": str(
                    st.session_state.amd_dinov2_repo
                ).strip(),
                "checkpoint": str(
                    st.session_state.amd_checkpoint
                ).strip(),
            }
        )

    mode_value = (
        "cloud"
        if cloud_mode
        else "package"
    )
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(AMD_ANALYSIS_SCRIPT),
        "-ProjectRoot",
        str(PROJECT_ROOT),
        "-InspectionId",
        inspection_id,
        "-BaselineId",
        baseline_id,
        "-Mode",
        mode_value,
        "-WorkspaceName",
        (
            "current"
            if cloud_mode
            else "preview"
        ),
        "-ManualFrames",
        format_frame_number_list(selected_borderline_frames),
        "-BatchPairs",
        str(
            int(
                st.session_state.amd_batch_pairs
            )
        ),
        "-PythonExe",
        sys.executable,
        "-HostName",
        str(
            st.session_state.amd_host
        ).strip(),
        "-Port",
        str(
            int(
                st.session_state.amd_port
            )
        ),
        "-UserName",
        str(
            st.session_state.amd_user
        ).strip(),
        "-KeyPath",
        str(
            st.session_state.amd_key_path
        ).strip(),
        "-RemoteRoot",
        str(
            st.session_state.amd_remote_root
        ).strip(),
        "-RemotePython",
        str(
            st.session_state.amd_remote_python
        ).strip(),
        "-DinoRepo",
        str(
            st.session_state.amd_dinov2_repo
        ).strip(),
        "-Checkpoint",
        str(
            st.session_state.amd_checkpoint
        ).strip(),
    ]

    if cloud_mode and st.session_state.amd_force:
        command.append(
            "-Force"
        )

    with st.expander(
        "Execution Command",
        expanded=False,
    ):
        redacted_command = list(
            command
        )
        st.code(
            subprocess.list2cmdline(
                redacted_command
            ),
            language="powershell",
        )

    status_label = (
        "Running AMD Radeon analysis through SSH"
        if cloud_mode
        else "Preparing AMD analysis package"
    )

    with st.status(
        status_label,
        expanded=True,
    ) as amd_status:
        return_code = run_process(
            command,
            PROJECT_ROOT,
        )

        if return_code != 0:
            amd_status.update(
                label=(
                    "AMD workflow failed "
                    f"(exit code {return_code})"
                ),
                state="error",
            )
            st.error(
                "The local source data and previous pipeline stages "
                "were not modified."
            )
            return

        result = load_amd_run_summary(
            inspection_id,
            baseline_id,
        )

        if cloud_mode:
            if not amd_analysis_is_ready(
                result,
                inspection_id,
                baseline_id,
            ):
                amd_status.update(
                    label=(
                        "Cloud execution finished, but no ready AMD "
                        "result was produced"
                    ),
                    state="error",
                )
                st.error(
                    "Check the SSH, ROCm Python, DINOv2 repository, "
                    "checkpoint, and remote logs."
                )
                return

            amd_status.update(
                label="AMD Radeon analysis completed",
                state="complete",
            )
        else:
            amd_status.update(
                label="AMD input package prepared",
                state="complete",
            )
            st.success(
                "The preview package is ready. The completed AMD result "
                "in amd_analysis\\current was not changed."
            )
            st.rerun()

    complete_amd_analysis_step(
        inspection_id,
        baseline_id,
    )


# ---------------------------------------------------------------------
# Step 9: AMD result
# ---------------------------------------------------------------------
def render_step_9() -> None:
    render_step_intro(
        9,
        (
            "Review AMD Radeon DINOv2 semantic-change scores, heatmaps, "
            "inference latency, throughput, and GPU-memory measurements. "
            "Scores rank visual change; they are not calibrated defect "
            "probabilities."
        ),
    )

    baseline_id = active_baseline_id()
    inspection_id = active_inspection_id()
    amd_summary_path = amd_run_summary_path_for(
        inspection_id,
        baseline_id,
    )
    amd_summary = load_amd_run_summary(
        inspection_id,
        baseline_id,
    )

    if not amd_analysis_is_ready(
        amd_summary,
        inspection_id,
        baseline_id,
    ):
        st.warning(
            "No completed AMD result was found."
        )
        if st.button(
            "Back to AMD Analysis",
            use_container_width=True,
        ):
            navigate_to_step(8)
        return

    result_root = Path(
        amd_summary[
            "result_root"
        ]
    )
    result_summary_path = Path(
        amd_summary[
            "result_summary_path"
        ]
    )
    benchmark_path = Path(
        amd_summary[
            "benchmark_path"
        ]
    )
    scores_path = Path(
        amd_summary[
            "scores_csv_path"
        ]
    )

    result_summary = read_json(
        result_summary_path
    )
    benchmark = read_json(
        benchmark_path
    )

    st.success(
        "AMD Radeon semantic-change analysis completed and the results "
        "were retrieved locally."
    )

    metric_columns = st.columns(6)
    metric_columns[0].metric(
        "Analyzed Pairs",
        amd_summary.get(
            "analyzed_pairs",
            "N/A",
        ),
    )
    metric_columns[1].metric(
        "Mean ms / Pair",
        (
            f"{benchmark.get('mean_ms_per_pair', 0):.2f}"
            if benchmark.get(
                "mean_ms_per_pair"
            )
            is not None
            else "N/A"
        ),
    )
    metric_columns[2].metric(
        "Pairs / Second",
        (
            f"{benchmark.get('pairs_per_second', 0):.2f}"
            if benchmark.get(
                "pairs_per_second"
            )
            is not None
            else "N/A"
        ),
    )
    metric_columns[3].metric(
        "Peak GPU Memory",
        (
            f"{benchmark.get('peak_gpu_memory_mb', 0):.1f} MB"
            if benchmark.get(
                "peak_gpu_memory_mb"
            )
            is not None
            else "N/A"
        ),
    )
    metric_columns[4].metric(
        "GPU",
        benchmark.get(
            "device_name",
            "N/A",
        ),
    )
    metric_columns[5].metric(
        "Batch Pairs",
        benchmark.get(
            "batch_pairs",
            "N/A",
        ),
    )

    score_rows: list[dict[str, str]] = []
    if scores_path.is_file():
        with scores_path.open(
            encoding="utf-8-sig",
            newline="",
        ) as scores_file:
            score_rows = list(
                csv.DictReader(
                    scores_file
                )
            )

    def score_number(
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

    ranked_rows = sorted(
        score_rows,
        key=lambda row: score_number(
            row,
            "score_p95",
        ),
        reverse=True,
    )

    if ranked_rows:
        st.subheader(
            "Semantic Change Ranking"
        )
        table_rows = [
            {
                "rank": index,
                "frame": row.get(
                    "inspection_frame_number"
                ),
                "selection": row.get(
                    "selection_reason"
                ),
                "geometry": row.get(
                    "quality"
                ),
                "p95": round(
                    score_number(
                        row,
                        "score_p95",
                    ),
                    4,
                ),
                "p99": round(
                    score_number(
                        row,
                        "score_p99",
                    ),
                    4,
                ),
                "mean": round(
                    score_number(
                        row,
                        "score_mean",
                    ),
                    4,
                ),
                "valid_patches": row.get(
                    "valid_patch_count"
                ),
            }
            for index, row in enumerate(
                ranked_rows,
                start=1,
            )
        ]
        st.dataframe(
            table_rows,
            use_container_width=True,
            hide_index=True,
        )

        st.caption(
            "Higher scores indicate larger DINOv2 patch-feature change "
            "within the valid geometric overlap. They do not directly "
            "represent defect severity or probability."
        )

    target_frames = {
        101,
        122,
        195,
        196,
        204,
    }
    target_rows = [
        row
        for row in ranked_rows
        if int(
            score_number(
                row,
                "inspection_frame_number",
                -1,
            )
        )
        in target_frames
    ]

    if target_rows:
        st.subheader(
            "Demo Target Results"
        )
        st.dataframe(
            [
                {
                    "frame": row.get(
                        "inspection_frame_number"
                    ),
                    "selection": row.get(
                        "selection_reason"
                    ),
                    "geometry": row.get(
                        "quality"
                    ),
                    "p95": round(
                        score_number(
                            row,
                            "score_p95",
                        ),
                        4,
                    ),
                    "p99": round(
                        score_number(
                            row,
                            "score_p99",
                        ),
                        4,
                    ),
                }
                for row in sorted(
                    target_rows,
                    key=lambda item: int(
                        score_number(
                            item,
                            "inspection_frame_number",
                        )
                    ),
                )
            ],
            use_container_width=True,
            hide_index=True,
        )

    montage_root = result_root / "montages"
    montage_rows = ranked_rows[:12]

    if montage_rows:
        st.subheader(
            "Top Semantic Change Evidence"
        )
        image_columns = st.columns(2)

        for index, row in enumerate(
            montage_rows
        ):
            montage_name = row.get(
                "montage_file",
                "",
            )
            montage_path = (
                result_root
                / montage_name
            )

            if not montage_path.is_file():
                montage_path = (
                    montage_root
                    / Path(
                        montage_name
                    ).name
                )

            frame_number = int(
                score_number(
                    row,
                    "inspection_frame_number",
                )
            )

            with image_columns[
                index % 2
            ]:
                with st.container(
                    border=True
                ):
                    st.markdown(
                        f"**Frame {frame_number} · "
                        f"p95 {score_number(row, 'score_p95'):.3f}**"
                    )
                    st.caption(
                        (
                            f"{row.get('selection_reason')} · "
                            f"geometry {row.get('quality')} · "
                            f"p99 {score_number(row, 'score_p99'):.3f}"
                        )
                    )
                    if montage_path.is_file():
                        st.image(
                            str(
                                montage_path
                            ),
                            use_container_width=True,
                        )
                    else:
                        st.warning(
                            f"Montage not found: {montage_path.name}"
                        )

    with st.container(
        border=True
    ):
        st.subheader(
            "AMD Analysis Assets"
        )

        with st.expander(
            "Run Metadata",
            expanded=False,
        ):
            st.json(
                {
                    "Inspection ID": inspection_id,
                    "Baseline ID": baseline_id,
                    "Completed At": amd_summary.get(
                        "completed_at"
                    ),
                    "Remote Run Directory": amd_summary.get(
                        "remote_run_directory"
                    ),
                    "Result Root": str(
                        result_root
                    ),
                    "Model": result_summary.get(
                        "model"
                    ),
                    "Method": result_summary.get(
                        "method"
                    ),
                    "Score Note": result_summary.get(
                        "score_note"
                    ),
                }
            )

        downloads = st.columns(3)
        with downloads[0]:
            st.download_button(
                "Download run_summary.json",
                data=result_summary_path.read_bytes(),
                file_name=result_summary_path.name,
                mime="application/json",
                use_container_width=True,
            )
        with downloads[1]:
            st.download_button(
                "Download amd_benchmark.json",
                data=benchmark_path.read_bytes(),
                file_name=benchmark_path.name,
                mime="application/json",
                use_container_width=True,
            )
        with downloads[2]:
            st.download_button(
                "Download scores.csv",
                data=scores_path.read_bytes(),
                file_name=scores_path.name,
                mime="text/csv",
                use_container_width=True,
            )

        if st.button(
            "Back to AMD Analysis",
            use_container_width=True,
        ):
            navigate_to_step(8)

    st.caption(
        "Next stage: automatically clear stable areas, record well-supported "
        "visual changes, and send only uncertain evidence to targeted reinspection."
    )

    if st.button(
        "Continue to Change Triage",
        type="primary",
        use_container_width=True,
    ):
        st.session_state.current_step = 10
        st.session_state.max_unlocked_step = max(
            int(st.session_state.max_unlocked_step),
            10,
        )
        st.rerun()


# ---------------------------------------------------------------------
# Step 10: Change triage
# ---------------------------------------------------------------------
def render_step_10() -> None:
    render_step_intro(
        10,
        (
            "Automatically clear areas without supported change, record visual "
            "changes that have both strong semantic evidence and usable geometry, "
            "and route only high-scoring but geometrically uncertain evidence to "
            "targeted reinspection."
        ),
    )

    inspection_id = active_inspection_id()
    baseline_id = active_baseline_id()
    path = triage_path_for(inspection_id, baseline_id)
    triage = read_json(path)
    if (
        triage.get("status") == "ready"
        and triage.get("context_version") != CONTEXT_VERSION
    ):
        stored_thresholds = triage.get("thresholds") or {}
        triage = build_change_triage(
            inspection_id,
            baseline_id,
            safe_float(stored_thresholds.get("confirmed_p95"), 0.62),
            safe_float(stored_thresholds.get("uncertain_p95"), 0.60),
        )

    with st.container(border=True):
        st.subheader("Triage Policy")
        threshold_columns = st.columns(2)
        confirmed_threshold = threshold_columns[0].number_input(
            "Confirmed-change p95 threshold",
            min_value=0.0,
            max_value=1.0,
            value=float(
                triage.get("thresholds", {}).get("confirmed_p95", 0.62)
            ),
            step=0.01,
            key="triage_confirmed_threshold",
        )
        uncertain_threshold = threshold_columns[1].number_input(
            "Uncertain-change p95 threshold",
            min_value=0.0,
            max_value=1.0,
            value=float(
                triage.get("thresholds", {}).get("uncertain_p95", 0.60)
            ),
            step=0.01,
            key="triage_uncertain_threshold",
        )
        st.caption(
            "These are demo evidence-routing thresholds, not calibrated defect "
            "probabilities. Operational abnormality is not decided here."
        )

        generate_label = (
            "Regenerate Change Triage"
            if triage.get("status") == "ready"
            else "Generate Change Triage"
        )
        if st.button(
            generate_label,
            type="primary",
            use_container_width=True,
        ):
            try:
                triage = build_change_triage(
                    inspection_id,
                    baseline_id,
                    float(confirmed_threshold),
                    float(uncertain_threshold),
                )
            except Exception as error:
                st.error(str(error))
                return
            st.success("Change triage generated from the AMD evidence.")
            st.rerun()

    if triage.get("status") != "ready":
        st.info("Generate the triage to continue.")
        return

    counts = triage.get("counts") or {}
    metrics = st.columns(4)
    metrics[0].metric("Analyzed", counts.get("analyzed", 0))
    metrics[1].metric("Confirmed Change", counts.get("confirmed_change", 0))
    metrics[2].metric("Needs Reinspection", counts.get("uncertain_change", 0))
    metrics[3].metric("Automatically Cleared", counts.get("no_material_change", 0))

    confirmed = triage.get("confirmed_changes") or []
    uncertain = triage.get("uncertain_changes") or []

    st.subheader("Confirmed Visual Changes")
    if confirmed:
        st.dataframe(
            [
                {
                    "frame": item.get("frame_number"),
                    "area": item.get("target_area"),
                    "change evidence": item.get("suspected_object"),
                    "geometry": item.get("quality"),
                    "p95": round(safe_float(item.get("score_p95")), 4),
                    "next action": "Add to final report",
                }
                for item in confirmed
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No well-supported visual change met the current policy.")

    st.subheader("Uncertain Evidence — Reinspection Only")
    if uncertain:
        st.dataframe(
            [
                {
                    "frame": item.get("frame_number"),
                    "area": item.get("target_area"),
                    "unresolved change region": item.get("suspected_object"),
                    "geometry": item.get("quality"),
                    "p95": round(safe_float(item.get("score_p95")), 4),
                    "why uncertain": item.get("reason"),
                }
                for item in uncertain
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("No ambiguous high-change evidence requires reinspection.")

    with st.expander("Automatically cleared evidence", expanded=False):
        st.dataframe(
            [
                {
                    "frame": item.get("frame_number"),
                    "geometry": item.get("quality"),
                    "p95": round(safe_float(item.get("score_p95")), 4),
                    "status": "No supported material change",
                }
                for item in triage.get("no_material_changes") or []
            ],
            use_container_width=True,
            hide_index=True,
        )

    actions = st.columns(2)
    with actions[0]:
        st.download_button(
            "Download change_triage.json",
            data=path.read_bytes(),
            file_name=path.name,
            mime="application/json",
            use_container_width=True,
        )
    with actions[1]:
        if st.button(
            "Generate Reinspection Missions",
            type="primary",
            use_container_width=True,
        ):
            build_reinspection_missions(inspection_id, baseline_id)
            st.session_state.current_step = 11
            st.session_state.max_unlocked_step = max(
                int(st.session_state.max_unlocked_step),
                11,
            )
            st.rerun()


# ---------------------------------------------------------------------
# Step 11: Reinspection missions
# ---------------------------------------------------------------------
def render_step_11() -> None:
    render_step_intro(
        11,
        (
            "Create a physical reinspection task only for evidence that remains ambiguous. "
            "Each mission maps the baseline start position, reconstructed room context, "
            "camera trajectories, and the baseline-reference target position so an operator "
            "can identify where to go. DINOv2 does not infer an object class or facility-zone name."
        ),
    )

    inspection_id = active_inspection_id()
    baseline_id = active_baseline_id()
    missions_path = missions_path_for(inspection_id, baseline_id)
    payload = read_json(missions_path)
    if payload.get("context_version") != CONTEXT_VERSION:
        triage = read_json(triage_path_for(inspection_id, baseline_id))
        if triage.get("context_version") != CONTEXT_VERSION:
            build_change_triage(inspection_id, baseline_id)
        payload = build_reinspection_missions(inspection_id, baseline_id)
    if payload.get("status") != "ready":
        try:
            payload = build_reinspection_missions(inspection_id, baseline_id)
        except Exception as error:
            st.error(str(error))
            return

    missions = payload.get("missions") or []
    if not missions:
        st.success(
            "No ambiguous evidence remains. No targeted reinspection flight is required."
        )
        if st.button(
            "Continue to Final Report",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.current_step = 13
            st.session_state.max_unlocked_step = 13
            st.rerun()
        return

    st.metric("Targeted Missions", len(missions))
    for mission in missions:
        mission_id = str(mission.get("mission_id"))
        frame_number = safe_int(mission.get("representative_frame"), -1)
        with st.container(border=True):
            st.markdown(
                f"### {mission_id} — {mission.get('target_area')}"
            )
            columns = st.columns(3)
            columns[0].metric("Source Frame", frame_number)
            columns[1].metric(
                "Initial p95",
                f"{safe_float(mission.get('initial_score_p95')):.3f}",
            )
            columns[2].metric(
                "Initial Geometry",
                mission.get("initial_geometry", "N/A"),
            )
            st.markdown(f"**Suspected change:** {mission.get('suspected_object')}")
            st.info(str(mission.get("reason")))

            amd_summary = load_amd_run_summary(inspection_id, baseline_id)
            result_root = Path(amd_summary.get("result_root", ""))
            montage = result_root / "montages" / f"frame_{frame_number:06d}_montage.jpg"
            if montage.is_file():
                st.markdown("#### Reinspection target evidence")
                montage_html = _html_initial_montage({
                    "label": f"Initial evidence — representative frame {frame_number}",
                    "path": str(montage),
                    "kind": "initial_montage",
                })
                if montage_html:
                    components.html(
                        '<style>body{font-family:Segoe UI,Arial;margin:0}.evidence{background:#f8fafb;border:2px solid #c6d3d9;border-radius:14px;padding:12px}.evidence-montage{display:grid;grid-template-columns:1fr 1fr;gap:12px}.evidence-panel{border:2px solid #8299a4;border-radius:10px;overflow:hidden}.panel-label{background:#173946;color:white;font-size:16px;font-weight:700;padding:9px 11px}.evidence-panel img{display:block;width:100%}.evidence-explainer{background:#eef4f6;border-left:4px solid #708892;padding:10px 12px;font-size:13px}.evidence figcaption{font-size:13px;color:#52636d;margin-top:7px}@media(max-width:700px){.evidence-montage{grid-template-columns:1fr}}</style>' + montage_html,
                        height=820,
                        scrolling=False,
                    )
                else:
                    st.image(str(montage), use_container_width=True)

            st.markdown("#### Interactive 3D Mission View")
            render_spatial_mission_map(
                inspection_id,
                baseline_id,
                mission,
            )
            st.markdown("**Reinspection instruction**")
            for index, instruction in enumerate(
                mission.get("flight_instructions") or [],
                start=1,
            ):
                st.markdown(f"{index}. {instruction}")
            st.markdown(
                f"**Verification goal:** {mission.get('verification_goal')}"
            )

    st.download_button(
        "Download reinspection_missions.json",
        data=missions_path.read_bytes(),
        file_name=missions_path.name,
        mime="application/json",
        use_container_width=True,
    )

    if st.button(
        "Continue to Reinspection Analysis",
        type="primary",
        use_container_width=True,
    ):
        st.session_state.current_step = 12
        st.session_state.max_unlocked_step = max(
            int(st.session_state.max_unlocked_step),
            12,
        )
        st.rerun()

# ---------------------------------------------------------------------
# Step 12: Reinspection analysis
# ---------------------------------------------------------------------
def render_step_12() -> None:
    render_step_intro(
        12,
        (
            "Register the targeted follow-up image or video for each mission. "
            "FactoryFly selects the best geometrically comparable view, runs the "
            "same AMD Radeon DINOv2 analysis, and decides whether the visual change "
            "persisted, disappeared, or remains unresolved."
        ),
    )

    inspection_id = active_inspection_id()
    baseline_id = active_baseline_id()
    payload = read_json(missions_path_for(inspection_id, baseline_id))
    missions = payload.get("missions") or []

    if not missions:
        st.success("No reinspection was required.")
        if st.button(
            "Continue to Final Report",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.current_step = 13
            st.session_state.max_unlocked_step = 13
            st.rerun()
        return

    config = load_amd_config()
    completed_count = 0

    def normalized_source(value: Any) -> str:
        return (
            str(value or "")
            .strip()
            .strip('"')
            .strip("'")
            .replace("/", "\\")
            .rstrip("\\")
            .casefold()
        )

    def result_is_stale(
        result_payload: dict[str, Any],
        source_path: Path | None,
        overwrite_requested: bool,
    ) -> tuple[bool, str]:
        if result_payload.get("status") != "ready":
            return False, ""
        if overwrite_requested:
            return True, "Overwrite is selected."
        if source_path is None or not source_path.is_file():
            return False, ""

        result_source = normalized_source(result_payload.get("source_path"))
        current_source = normalized_source(source_path)
        if result_source and current_source and result_source != current_source:
            return True, "The selected source path differs from the completed result."

        completed_at = str(result_payload.get("completed_at", "")).strip()
        if completed_at:
            try:
                completed = datetime.fromisoformat(completed_at)
                if completed.tzinfo is None:
                    completed = completed.replace(tzinfo=timezone.utc)
                completed_timestamp = completed.timestamp()
                source_timestamp = source_path.stat().st_mtime
                if source_timestamp > completed_timestamp + 1.0:
                    return True, "The source file was modified after the completed result."
            except (OSError, ValueError, OverflowError):
                pass

        return False, ""

    for mission in missions:
        mission_id = str(mission.get("mission_id"))
        result_path = reinspection_run_summary_path_for(
            inspection_id,
            baseline_id,
            mission_id,
        )
        result = read_json(result_path)

        source_key = f"reinspection_source_{mission_id}"
        force_key = f"reinspection_force_{mission_id}"
        preview_key = f"reinspection_preview_{mission_id}"
        reset_controls_key = f"reinspection_reset_controls_{mission_id}"

        # Widget-backed session-state values may only be changed before the
        # corresponding widgets are instantiated. A successful analysis sets
        # this non-widget flag, and the next rerun clears the controls here.
        if st.session_state.pop(reset_controls_key, False):
            st.session_state[force_key] = False
            st.session_state[preview_key] = False

        default_source_path = str(
            PROJECT_ROOT.parent
            / "reinspection"
            / f"{mission_id}.mp4"
        )
        if not str(st.session_state.get(source_key, "")).strip():
            st.session_state[source_key] = default_source_path

        with st.container(border=True):
            st.markdown(
                f"### {mission_id} — {mission.get('target_area')}"
            )
            st.caption(
                f"Suspected change: {mission.get('suspected_object')}"
            )

            st.text_input(
                "Targeted reinspection image or video path",
                key=source_key,
                help=(
                    "This is an actual local path value, not placeholder text. "
                    "The default is C:\\Projects\\factoryfly-data\\reinspection\\"
                    f"{mission_id}.mp4. The same flight video may be entered for "
                    "multiple missions when it revisits every target."
                ),
            )

            visible_source = (
                str(st.session_state.get(source_key, ""))
                .strip()
                .strip('"')
                .strip("'")
            )
            visible_source_path = Path(visible_source) if visible_source else None
            source_size_mb = None
            if visible_source_path and visible_source_path.is_file():
                source_size_mb = visible_source_path.stat().st_size / 1024 / 1024
                st.success(
                    f"Local evidence found: {visible_source_path} "
                    f"({source_size_mb:.1f} MB)"
                )
                if source_size_mb > 250:
                    st.caption(
                        "Large source video detected. Analysis can take longer, "
                        "but the UI will not load the video bytes."
                    )
            else:
                st.warning(
                    "Local evidence is not found at the current path. "
                    "Paste a valid file path or place the file at the displayed default."
                )

            st.checkbox(
                "Overwrite this mission analysis",
                key=force_key,
                help=(
                    "Select this after replacing the reinspection file or when you "
                    "need to rerun the same mission. The previous result is preserved "
                    "until the new run completes successfully."
                ),
            )

            overwrite_requested = bool(
                st.session_state.get(force_key, False)
            )
            stale_result, stale_reason = result_is_stale(
                result,
                visible_source_path,
                overwrite_requested,
            )

            if result.get("status") == "ready" and stale_result:
                st.info(
                    "A previous result exists, but it is now marked as stale and "
                    "will not count as completed. "
                    f"{stale_reason} Run the analysis below to replace it."
                )

            run_label = (
                f"Re-run AMD Reinspection Analysis — {mission_id}"
                if result.get("status") == "ready"
                else f"Run AMD Reinspection Analysis — {mission_id}"
            )
            if st.button(
                run_label,
                type="primary",
                use_container_width=True,
                key=f"run_reinspection_{mission_id}",
            ):
                source_path = (
                    str(st.session_state.get(source_key, ""))
                    .strip()
                    .strip('"')
                    .strip("'")
                )
                if not source_path or not Path(source_path).is_file():
                    st.error("Enter an existing local image or video path.")
                    continue

                command = [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(REINSPECTION_ANALYSIS_SCRIPT),
                    "-ProjectRoot",
                    str(PROJECT_ROOT),
                    "-InspectionId",
                    inspection_id,
                    "-BaselineId",
                    baseline_id,
                    "-MissionId",
                    mission_id,
                    "-SourcePath",
                    source_path,
                    "-BatchPairs",
                    "1",
                    "-PythonExe",
                    sys.executable,
                    "-HostName",
                    str(config.get("host", "")),
                    "-Port",
                    str(int(config.get("port", 22))),
                    "-UserName",
                    str(config.get("user", "root")),
                    "-KeyPath",
                    str(config.get("key_path", "")),
                    "-RemoteRoot",
                    str(config.get("remote_root", "")),
                    "-RemotePython",
                    str(config.get("remote_python", "")),
                    "-DinoRepo",
                    str(config.get("dinov2_repo", "")),
                    "-Checkpoint",
                    str(config.get("checkpoint", "")),
                ]
                if overwrite_requested:
                    command.append("-Force")

                with st.status(
                    f"Running targeted reinspection analysis for {mission_id}",
                    expanded=True,
                ) as status:
                    return_code = run_process(command, PROJECT_ROOT)
                    if return_code != 0:
                        status.update(
                            label="Reinspection analysis failed",
                            state="error",
                        )
                        st.error(
                            "Review the geometric-match log, SSH endpoint, and AMD environment."
                        )
                        continue
                    status.update(
                        label="Reinspection analysis completed",
                        state="complete",
                    )

                st.session_state[reset_controls_key] = True
                st.rerun()

            if result.get("status") == "ready" and not stale_result:
                completed_count += 1
                outcome = classify_reinspection_result(result)
                target_not_reacquired = (
                    result.get("outcome") == "target_not_reacquired"
                )
                labels = {
                    "persistent_change_confirmed": "Persistent visual change confirmed",
                    "no_persistent_change": "No persistent change after reinspection",
                    "still_unresolved": "Still unresolved — another observation is required",
                }

                st.markdown("#### Current completed result")
                if target_not_reacquired:
                    st.warning(
                        "Target not reacquired with usable geometry. DINOv2 comparison was skipped; "
                        "the displayed candidate review is not change evidence."
                    )
                elif outcome == "persistent_change_confirmed":
                    st.success(labels[outcome])
                elif outcome == "no_persistent_change":
                    st.info(labels[outcome])
                else:
                    st.warning(labels[outcome])

                metrics = st.columns(4)
                metrics[0].metric(
                    "Geometry",
                    result.get("geometry_quality", "N/A"),
                )
                metrics[1].metric(
                    "Initial p95",
                    f"{safe_float(mission.get('initial_score_p95')):.3f}",
                )
                reinspection_score = result.get("score_p95")
                metrics[2].metric(
                    "Reinspection p95",
                    (
                        "N/A"
                        if reinspection_score in {None, ""}
                        else f"{safe_float(reinspection_score):.3f}"
                    ),
                )
                metrics[3].metric(
                    "Selected Evidence",
                    result.get("source_candidate", "N/A"),
                )

                show_preview = st.checkbox(
                    "Load result images",
                    key=preview_key,
                    help=(
                        "Result images are loaded only on demand to keep the "
                        "Streamlit page responsive."
                    ),
                )

                if show_preview:
                    montage = Path(str(result.get("montage_path", "")))
                    candidate_review = Path(
                        str(result.get("candidate_review_path", ""))
                    )
                    if montage.is_file():
                        montage_html = _html_initial_montage({
                            "label": "Targeted reinspection comparison",
                            "path": str(montage),
                            "kind": "reinspection_montage",
                        })
                        if montage_html:
                            components.html(
                                '<style>body{font-family:Segoe UI,Arial;margin:0}'
                                '.evidence{background:#f8fafb;border:2px solid #c6d3d9;'
                                'border-radius:14px;padding:12px}.evidence-montage{display:grid;'
                                'grid-template-columns:1fr 1fr;gap:12px}.evidence-panel{'
                                'border:2px solid #8299a4;border-radius:10px;overflow:hidden}'
                                '.panel-label{background:#173946;color:white;font-size:16px;'
                                'font-weight:700;padding:9px 11px}.evidence-panel img{display:block;'
                                'width:100%}.evidence-explainer{background:#eef4f6;'
                                'border-left:4px solid #708892;padding:10px 12px;font-size:13px}'
                                '.evidence figcaption{font-size:13px;color:#52636d;margin-top:7px}'
                                '</style>' + montage_html,
                                height=820,
                                scrolling=False,
                            )
                        else:
                            st.image(
                                str(montage),
                                use_container_width=True,
                            )
                    elif candidate_review.is_file():
                        candidate_html = _html_candidate_review({
                            "label": "Reinspection candidate validation",
                            "path": str(candidate_review),
                            "kind": "candidate_review",
                        })
                        if candidate_html:
                            components.html(
                                '<style>body{font-family:Segoe UI,Arial;margin:0}'
                                '.evidence{background:#f8fafb;border:2px solid #c6d3d9;'
                                'border-radius:14px;padding:12px}.candidate-reference-grid,'
                                '.candidate-list{display:grid;grid-template-columns:1fr 1fr;'
                                'gap:12px}.candidate-list{margin-top:12px}.evidence-panel,'
                                '.candidate-panel{border:2px solid #8299a4;border-radius:10px;'
                                'overflow:hidden}.panel-label{background:#173946;color:white;'
                                'font-size:16px;font-weight:700;padding:9px 11px}.evidence-panel img,'
                                '.candidate-panel img{display:block;width:100%}.evidence-explainer{'
                                'background:#fff7df;border-left:4px solid #d79a1f;padding:10px 12px;'
                                'font-size:13px}.evidence figcaption{font-size:13px;color:#52636d;'
                                'margin-top:7px}@media(max-width:700px){.candidate-reference-grid,'
                                '.candidate-list{grid-template-columns:1fr}}</style>' + candidate_html,
                                height=760,
                                scrolling=False,
                            )
                        else:
                            st.image(
                                str(candidate_review),
                                caption=(
                                    "Candidate validation review — target was not "
                                    "geometrically reacquired"
                                ),
                                use_container_width=True,
                            )

                with st.expander(
                    "Reinspection run metadata",
                    expanded=False,
                ):
                    st.json(result)

    st.progress(completed_count / max(len(missions), 1))
    st.caption(
        f"Completed targeted analyses: {completed_count} / {len(missions)}"
    )
    if completed_count == len(missions):
        if st.button(
            "Continue to Final Change Report",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.current_step = 13
            st.session_state.max_unlocked_step = 13
            st.rerun()
    else:
        st.info(
            "Complete every uncertain mission before generating the consolidated report."
        )


# ---------------------------------------------------------------------
# Step 13: Final report
# ---------------------------------------------------------------------
def render_step_13() -> None:
    render_step_intro(
        13,
        (
            "Combine the initial inspection and targeted reinspection into a "
            "single evidence report. FactoryFly states what visually changed; "
            "a human reviewer decides whether each change is expected, abnormal, "
            "or requires operational action."
        ),
    )

    inspection_id = active_inspection_id()
    baseline_id = active_baseline_id()
    if not all_reinspection_missions_resolved(inspection_id, baseline_id):
        st.warning(
            "At least one targeted reinspection mission is still missing a completed analysis."
        )
        if st.button("Back to Reinspection Analysis", use_container_width=True):
            navigate_to_step(12)
        return

    preliminary = build_final_report_payload(inspection_id, baseline_id)
    confirmed = preliminary.get("confirmed_changes") or []
    existing = read_json(final_report_json_path_for(inspection_id, baseline_id))
    existing_decisions = {
        str(item.get("finding_id")): item.get("human_disposition") or {}
        for item in existing.get("confirmed_changes") or []
    }

    st.subheader("AI-Confirmed Visual Changes")
    if not confirmed:
        st.success("No persistent visual change was confirmed.")

    human_decisions: dict[str, dict[str, str]] = {}
    categories = [
        "Pending human judgment",
        "Expected operational change",
        "No action required",
        "Housekeeping issue",
        "Maintenance concern",
        "Safety concern",
        "Other abnormal condition",
    ]

    for finding in confirmed:
        finding_id = str(finding.get("finding_id"))
        prior = existing_decisions.get(finding_id, {})
        with st.container(border=True):
            st.markdown(
                f"### {finding_id} — {finding.get('target_area')}"
            )
            st.markdown(
                f"**Observed visual change:** {finding.get('observed_change')}"
            )
            st.info(str(finding.get("ai_evidence_conclusion")))
            if finding.get("source") == "targeted_reinspection":
                metrics = st.columns(3)
                metrics[0].metric(
                    "Geometry",
                    str(finding.get("geometry_quality", "N/A")),
                )
                metrics[1].metric(
                    "Initial p95",
                    f"{safe_float(finding.get('initial_score_p95')):.3f}",
                )
                metrics[2].metric(
                    "Reinspection p95",
                    f"{safe_float(finding.get('reinspection_score_p95')):.3f}",
                )
            else:
                st.metric(
                    "Initial p95",
                    f"{safe_float(finding.get('score_p95')):.3f}",
                )

            evidence_images = finding.get("evidence_images") or []
            if evidence_images:
                st.markdown("**Visual evidence**")
                for evidence in evidence_images:
                    evidence_path = Path(str(evidence.get("path", "")))
                    if evidence_path.is_file():
                        st.image(
                            str(evidence_path),
                            caption=str(evidence.get("label", "Evidence")),
                            use_container_width=True,
                        )

            default_category = str(
                prior.get("category", "Pending human judgment")
            )
            if default_category not in categories:
                default_category = categories[0]
            category = st.selectbox(
                "Human operational disposition",
                categories,
                index=categories.index(default_category),
                key=f"human_category_{finding_id}",
            )
            notes = st.text_area(
                "Reviewer notes",
                value=str(prior.get("notes", "")),
                key=f"human_notes_{finding_id}",
            )
            human_decisions[finding_id] = {
                "category": category,
                "notes": notes.strip(),
            }

    report = build_final_report_payload(
        inspection_id,
        baseline_id,
        human_decisions,
    )

    summary = report.get("summary") or {}
    metrics = st.columns(5)
    metrics[0].metric("Analyzed", summary.get("analyzed_pairs", 0))
    metrics[1].metric("Stable Cleared", summary.get("stable_areas_cleared", 0))
    metrics[2].metric("Confirmed Changes", summary.get("confirmed_changes", 0))
    metrics[3].metric("Reinspections", summary.get("reinspection_missions", 0))
    metrics[4].metric("Unresolved", summary.get("unresolved_findings", 0))

    if report.get("resolved_without_persistent_change"):
        with st.expander("Cleared after targeted reinspection", expanded=True):
            st.dataframe(
                report["resolved_without_persistent_change"],
                use_container_width=True,
                hide_index=True,
            )
    if report.get("unresolved_findings"):
        st.warning(
            "Some findings remain unresolved and require another observation or direct inspection."
        )
        st.dataframe(
            report["unresolved_findings"],
            use_container_width=True,
            hide_index=True,
        )

    if st.button(
        "Save Final Change Report",
        type="primary",
        use_container_width=True,
    ):
        json_path = final_report_json_path_for(inspection_id, baseline_id)
        md_path = final_report_md_path_for(inspection_id, baseline_id)
        html_path = final_report_html_path_for(inspection_id, baseline_id)
        write_json(json_path, report)
        md_path.write_text(
            final_report_markdown(report),
            encoding="utf-8",
        )
        html_path.write_text(
            final_report_html(report),
            encoding="utf-8",
        )
        st.success("Final JSON, Markdown, and self-contained HTML evidence reports were saved.")
        st.rerun()

    json_path = final_report_json_path_for(inspection_id, baseline_id)
    md_path = final_report_md_path_for(inspection_id, baseline_id)
    html_path = final_report_html_path_for(inspection_id, baseline_id)
    downloads = st.columns(3)
    if json_path.is_file():
        downloads[0].download_button(
            "Download final_change_report.json",
            data=json_path.read_bytes(),
            file_name=json_path.name,
            mime="application/json",
            use_container_width=True,
        )
    if md_path.is_file():
        downloads[1].download_button(
            "Download final_change_report.md",
            data=md_path.read_bytes(),
            file_name=md_path.name,
            mime="text/markdown",
            use_container_width=True,
        )
    if html_path.is_file():
        downloads[2].download_button(
            "Download visual HTML report",
            data=html_path.read_bytes(),
            file_name=html_path.name,
            mime="text/html",
            use_container_width=True,
        )


# ---------------------------------------------------------------------
# App entry point
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="FactoryFly Sentinel",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

initialize_state()
apply_styles()
(
    active_summary,
    active_inspection_manifest,
    active_localization_summary,
    active_pair_summary,
    active_amd_summary,
) = synchronize_wizard_state()

render_header(
    active_summary,
    active_inspection_manifest,
    active_localization_summary,
    active_pair_summary,
    active_amd_summary,
)
render_new_demo_run_panel()
render_step_navigation()
show_flash_message()

current_step = int(
    st.session_state.current_step
)

if current_step == 1:
    render_step_1()
elif current_step == 2:
    render_step_2()
elif current_step == 3:
    render_step_3()
elif current_step == 4:
    render_step_4()
elif current_step == 5:
    render_step_5()
elif current_step == 6:
    render_step_6()
elif current_step == 7:
    render_step_7()
elif current_step == 8:
    render_step_8()
elif current_step == 9:
    render_step_9()
elif current_step == 10:
    render_step_10()
elif current_step == 11:
    render_step_11()
elif current_step == 12:
    render_step_12()
else:
    render_step_13()
