# FactoryFly Sentinel

**Human-Guided Physical AI for Active Factory Inspection**

FactoryFly Sentinel converts repeated human-operated drone inspections into localized visual-change evidence, routes uncertain observations to targeted reinspection, and produces a self-contained report for human review.

This repository accompanies the **AMD AI DevMaster Hackathon 2026 — Track 3** submission.

> **Scope:** FactoryFly reports observed visual changes and evidence quality. It does not decide whether a change is a defect, safety issue, or acceptable operation. A human reviewer assigns the operational disposition.

---

## 1. Reproducibility Overview

FactoryFly uses a hybrid execution model:

- **Windows workstation**
  - Streamlit UI
  - Video frame extraction
  - COLMAP baseline reconstruction
  - Inspection localization
  - SIFT/RANSAC/homography pair refinement
  - Triage, reinspection mission generation, and reporting

- **AMD Radeon Cloud**
  - PyTorch with ROCm
  - DINOv2 ViT-S/14 inference
  - Relative semantic-change heatmaps and p95 score generation

The complete workflow contains 13 stages:

1. Baseline Registration
2. Baseline Spatial Memory
3. Inspection Registration
4. Spatial Localization
5. Localization Result
6. Pair Refinement
7. Pair Result
8. AMD Analysis
9. AMD Result
10. Change Triage
11. Reinspection Mission
12. Reinspection Analysis
13. Final Report

Two verification paths are provided:

### Path A — Full reproduction

Run the complete workflow from the baseline, inspection, telemetry, and reinspection source files.

### Path B — Result inspection

Launch the UI and open the included self-contained sample report under `expected_results/`. This verifies the submitted evidence format without rerunning COLMAP or Radeon Cloud inference.

Path B is supplementary. Path A is the full reproduction procedure.

---

## 2. Repository Layout

```text
factoryfly-sentinel/
├─ app.py
├─ start_factoryfly.bat
├─ stop_factoryfly.bat
├─ requirements-local.txt
├─ requirements-rocm.txt
├─ README.md
├─ config/
│  ├─ amd_cloud.example.json
│  └─ colmap.example.json
├─ scripts/
│  ├─ configure_local_paths.ps1
│  ├─ setup_local.ps1
│  ├─ setup_radeon_cloud.sh
│  └─ verify_radeon_cloud.sh
├─ shared/
│  ├─ config/
│  └─ scripts/
├─ baseline/
├─ sample_data/
│  └─ README.md
├─ expected_results/
│  └─ final_change_report.html
└─ docs/
   ├─ FactoryFly_Sentinel_Technical_Report.pdf
   └─ figures/
```

Derived data such as extracted frames, COLMAP databases, sparse models, AMD packages, logs, and reports are generated under the selected Baseline ID and Inspection ID.

---

## 3. Tested Configuration

### 3.1 Local workstation

- Windows 10 or Windows 11
- Windows PowerShell 5.1 or later
- Python 3.12 or later
- Streamlit 1.44 or later, below 2.0
- OpenCV 4.10 or later
- NumPy 1.26 or later
- FFmpeg available on `PATH`
- OpenSSH client with `ssh` and `scp`
- COLMAP 4.1.1
- Tested COLMAP launcher path: `C:\Tools\COLMAP\COLMAP.bat`

The captured prototype run used a Windows workstation. A local CUDA GPU is not required for DINOv2 because the semantic inference stage runs on Radeon Cloud. COLMAP performance depends on the local installation and hardware.

### 3.2 AMD Radeon Cloud

- AMD Radeon Cloud instance
- Linux environment with ROCm 7.2.1
- Python 3.12
- PyTorch 2.9.1 with ROCm 7.2.1
- TorchVision 0.24.0 with ROCm 7.2.1
- TorchAudio 2.9.0 with ROCm 7.2.1
- Triton 3.5.1 with ROCm 7.2.1
- NumPy 1.26.4
- OpenCV Headless 4.10.0.84
- Open-source DINOv2 repository
- `dinov2_vits14_pretrain.pth` checkpoint

The actual Radeon GPU model is detected and printed by `scripts/verify_radeon_cloud.sh`.

---

## 4. Required Input Data

Full reproduction requires four source files:

```text
sample_data/raw/
├─ baseline.mp4
├─ inspection.mp4
├─ inspection_telemetry.txt
└─ reinspection.mp4
```

The demonstration data were captured by the participant in a private indoor environment.

- `baseline.mp4`: reference scene before the demonstrated changes
- `inspection.mp4`: repeated inspection containing visible changes
- `inspection_telemetry.txt`: matching DJI flight-record telemetry
- `reinspection.mp4`: targeted follow-up view of the uncertain evidence location

See `sample_data/README.md` for packaging and privacy guidance.

---

## 5. Local Installation

Open **Windows PowerShell**.

### 5.1 Clone or extract the repository

```powershell
git clone <YOUR_FACTORYFLY_REPOSITORY_URL>
cd factoryfly-sentinel
```

A ZIP extraction is also valid.

### 5.2 Install COLMAP

Install COLMAP and confirm that the launcher exists.

Tested path:

```text
C:\Tools\COLMAP\COLMAP.bat
```

Verify:

```powershell
& "C:\Tools\COLMAP\COLMAP.bat" -h
```

### 5.3 Install FFmpeg and OpenSSH

Verify:

```powershell
ffmpeg -version
ssh -V
scp
```

On Windows 10/11, OpenSSH Client can be enabled from **Optional Features**.

### 5.4 Run the local setup script

From the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\setup_local.ps1" `
  -ProjectRoot "$PWD" `
  -ColmapBat "C:\Tools\COLMAP\COLMAP.bat"
```

This script:

- creates `.venv-vision`
- installs `requirements-local.txt`
- validates FFmpeg, COLMAP, SSH, and SCP
- validates the portable repository root used by `app.py`
- updates the default COLMAP path in the two pipeline scripts

### 5.5 Manual installation alternative

```powershell
py -3.12 -m venv .venv-vision

.\.venv-vision\Scripts\python.exe `
  -m pip install --upgrade pip

.\.venv-vision\Scripts\python.exe `
  -m pip install -r requirements-local.txt

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\configure_colmap.ps1" `
  -ProjectRoot "$PWD" `
  -ColmapBat "C:\Tools\COLMAP\COLMAP.bat"
```

---

## 6. AMD Radeon Cloud Setup

### 6.1 Prepare an SSH key on Windows

```powershell
ssh-keygen -t ed25519 `
  -f "$HOME\.ssh\factoryfly_amd" `
  -C "factoryfly-radeon-cloud"
```

Do not add the private key to Git.

Display the public key:

```powershell
Get-Content "$HOME\.ssh\factoryfly_amd.pub"
```

Add the public key to `/root/.ssh/authorized_keys` in the Radeon Cloud instance.

### 6.2 Upload and run the setup script

From Windows:

```powershell
scp -P <PORT> `
  -i "$HOME\.ssh\factoryfly_amd" `
  ".\scripts\setup_radeon_cloud.sh" `
  ".\scripts\verify_radeon_cloud.sh" `
  root@<HOST>:/workspace/
```

Run it:

```powershell
ssh -p <PORT> `
  -i "$HOME\.ssh\factoryfly_amd" `
  root@<HOST> `
  "bash /workspace/setup_radeon_cloud.sh"
```

The default remote paths created by the script are:

```text
Remote root:
  /workspace/factoryfly-radeon

ROCm Python:
  /workspace/factoryfly-radeon/.venv-rocm/bin/python

DINOv2 repository:
  /workspace/factoryfly-radeon/vendor/dinov2

DINOv2 checkpoint:
  /workspace/factoryfly-radeon/vendor/checkpoints/dinov2_vits14_pretrain.pth
```

### 6.3 Verify Radeon GPU access

```powershell
ssh -p <PORT> `
  -i "$HOME\.ssh\factoryfly_amd" `
  root@<HOST> `
  "bash /workspace/factoryfly-radeon/scripts/verify_radeon_cloud.sh"
```

Expected markers:

```text
ROCM_OK
GPU_OK
DINOV2_OK
```

The command also prints the detected GPU, PyTorch version, HIP version, Python version, and checkpoint path.

---

## 7. Configure Radeon Cloud in FactoryFly

Start FactoryFly first, then enter the following values in **Step 8 — AMD Analysis**.

```text
Execution mode:
  Run on Radeon Cloud via SSH

SSH host:
  <HOST DISPLAYED BY RADEON CLOUD>

SSH port:
  <PORT DISPLAYED BY RADEON CLOUD>

SSH user:
  root

Private key:
  C:\Users\<USER>\.ssh\factoryfly_amd

Remote project root:
  /workspace/factoryfly-radeon

Remote ROCm Python:
  /workspace/factoryfly-radeon/.venv-rocm/bin/python

DINOv2 repository:
  /workspace/factoryfly-radeon/vendor/dinov2

Checkpoint:
  /workspace/factoryfly-radeon/vendor/checkpoints/dinov2_vits14_pretrain.pth
```

Host and port may change when a cloud instance is recreated. Never commit the real endpoint or private-key path to the public repository.

---

## 8. Launch FactoryFly

From the repository root:

```powershell
.\.venv-vision\Scripts\python.exe `
  -m streamlit run .\app.py `
  --server.port 8501 `
  --server.headless true `
  --browser.gatherUsageStats false
```

Open:

```text
http://localhost:8501
```

The application header should show:

```text
FactoryFly Sentinel v7.3.13
```

A convenience launcher may also be used:

```powershell
.\start_factoryfly.bat
```

---

## 9. Full Reproduction Procedure

### 9.1 Start a clean run

Expand **Start New Demo Run**.

Recommended IDs:

```text
Baseline ID:
  baseline_reproduction_001

Inspection ID:
  inspection_reproduction_001
```

Confirm the reset and click **Start New Demo Run**.

This operation resets the selected run state while preserving saved Radeon Cloud connection settings and previous archived runs.

### Step 1 — Baseline Registration

1. Select **Register local MP4 path**.
2. Enter:

   ```text
   <REPOSITORY>\sample_data\raw\baseline.mp4
   ```

3. Set **Frame sampling FPS** to `4`.
4. Click **Build 3D Baseline**.

Expected outputs include:

```text
baseline/<BASELINE_ID>/
├─ frames/
├─ reconstruction/
├─ poses/
├─ reports/
└─ logs/
```

### Step 2 — Baseline Spatial Memory

Review:

- extracted frame count
- registered camera count
- registration rate
- sparse point count
- camera trajectory
- active-baseline metadata

Activate or continue with the completed baseline.

### Step 3 — Inspection Registration

Register:

```text
Inspection video:
  <REPOSITORY>\sample_data\raw\inspection.mp4

Inspection telemetry:
  <REPOSITORY>\sample_data\raw\inspection_telemetry.txt
```

Click **Register Inspection Inputs**.

The registration stage stores SHA256 hashes and input metadata. Source files are not overwritten.

### Step 4 — Spatial Localization

1. Set **Inspection frame sampling FPS** to `4`.
2. Click **Run Spatial Localization**.

The active baseline is copied to an isolated working directory before inspection images are registered. The baseline source model is not modified.

### Step 5 — Localization Result

Review:

- input and registered frame counts
- localization percentage
- longest continuous registered run
- failed frames
- baseline and inspection trajectories

### Step 6 — Pair Refinement

1. Set **Top-K baseline candidates per inspection frame** to `5`.
2. Click **Run Pair Refinement**.

The refinement stage evaluates candidate pairs with SIFT, Fundamental Matrix RANSAC, Homography RANSAC, overlap, and reprojection quality.

### Step 7 — Pair Result

Review:

- Excellent / Good / Usable / Poor quality counts
- AMD-ready pair count
- high-confidence count
- median reprojection error
- candidate and refined image comparisons

Only non-poor geometry is routed to AMD analysis.

### Step 8 — AMD Analysis

1. Select **Run on Radeon Cloud via SSH**.
2. Load or enter the Radeon Cloud settings from Section 7.
3. Leave **Manual frames** empty for the automatic-only reproduction.
4. Set **Batch pairs** to `2`.
5. Click **Run AMD Analysis**.

FactoryFly packages geometry-ready pairs, transfers them through SCP, executes DINOv2 with PyTorch + ROCm, and downloads the result archive.

### Step 9 — AMD Result

Review:

- baseline reference
- inspection view
- warped baseline
- DINOv2 relative-change overlay
- per-pair score statistics
- AMD runtime and benchmark metadata

Warm heatmap regions represent relative semantic difference inside the geometrically valid overlap. They are not calibrated defect probabilities.

### Step 10 — Change Triage

Set:

```text
Confirmed-change p95 threshold:
  0.62

Uncertain-change p95 threshold:
  0.70
```

Click **Generate Change Triage** or **Regenerate Change Triage**.

Expected routing for the submitted demonstration:

```text
Confirmed Change:
  3

Needs Reinspection:
  1

Automatically Cleared:
  10
```

These values are evidence-routing thresholds for the demonstration, not calibrated probabilities.

### Step 11 — Reinspection Mission

Review the generated mission:

```text
Mission:
  R-F000021

Inspection evidence cluster:
  frames 21-23

Matched baseline area:
  frames 81-82
```

Review the interactive spatial map and download `reinspection_missions.json` if required.

Click **Continue to Reinspection Analysis**.

### Step 12 — Reinspection Analysis

Enter:

```text
<REPOSITORY>\sample_data\raw\reinspection.mp4
```

Run the reinspection analysis for the generated mission.

Expected result:

```text
Geometry:
  good

Initial p95:
  0.866

Reinspection p95:
  0.860

Conclusion:
  Persistent visual change confirmed
```

The reinspection stage can use direct baseline-to-reinspection geometry or a change-tolerant inspection bridge when the physical appearance changed too much for a direct match.

### Step 13 — Final Report

Click **Save Final Change Report**.

FactoryFly generates:

```text
final_change_report.json
final_change_report.md
final_change_report.html
```

The HTML report is self-contained and can be opened without the Streamlit server.

Expected final summary:

```text
Analyzed pairs:
  18

Stable cleared:
  10

Confirmed findings:
  4

Reinspections:
  1

Cleared after reinspection:
  0

Unresolved:
  0
```

---

## 10. Expected Demonstration Metrics

The submitted run produced the following dataset-specific results.

### Baseline

| Metric | Result |
|---|---:|
| Sampled frames | 158 |
| Registered cameras | 91 |
| Registration rate | 57.59% |
| Sparse 3D points | 5,499 |

### Inspection localization

| Metric | Result |
|---|---:|
| Input frames | 47 |
| Registered frames | 18 |
| Registration rate | 38.3% |
| Longest continuous run | 16 frames |

### Pair refinement

| Metric | Result |
|---|---:|
| Candidate pairs evaluated | 90 |
| Excellent | 3 |
| Good | 5 |
| Usable | 4 |
| Poor | 6 |
| AMD-ready | 12 |
| High confidence | 8 |
| Median reprojection error | 0.962 px |

### Final evidence result

| Metric | Result |
|---|---:|
| Analyzed evidence entries | 18 |
| Stable cleared | 10 |
| Confirmed findings | 4 |
| Reinspections | 1 |
| Unresolved | 0 |

COLMAP output can vary slightly across versions and hardware. The important reproducibility conditions are:

- the baseline model is successfully constructed
- inspection frames are localized in the same coordinate system
- geometry-ready pairs are generated
- DINOv2 executes on AMD Radeon GPU through ROCm
- one uncertain target is routed to reinspection with the submitted thresholds
- the reinspection target is reacquired
- the final report is generated

---

## 11. Quick Result Inspection

Open:

```text
expected_results/final_change_report.html
```

Verify that it contains:

- `Reinspections: 1`
- `Unresolved: 0`
- `Source: targeted_reinspection`
- `Geometry: good`
- `Initial p95: 0.866`
- `Reinspection p95: 0.860`

This report contains embedded images and interactive 3D data.

---

## 12. Troubleshooting

### Streamlit is slow after a long session

```powershell
Get-NetTCPConnection `
  -LocalPort 8501 `
  -State Listen `
  -ErrorAction SilentlyContinue |
ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force
}

.\.venv-vision\Scripts\python.exe `
  -m streamlit cache clear
```

Restart the application.

### COLMAP cannot be found

Confirm:

```powershell
Test-Path "C:\Tools\COLMAP\COLMAP.bat"
```

Then rerun:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\configure_local_paths.ps1" `
  -ProjectRoot "$PWD" `
  -ColmapBat "C:\Tools\COLMAP\COLMAP.bat"
```

### FFmpeg cannot be found

```powershell
Get-Command ffmpeg
```

Add the FFmpeg `bin` directory to `PATH`, or provide the executable path when running the backend PowerShell script directly.

### SSH connection fails

Verify the current endpoint:

```powershell
Test-NetConnection <HOST> -Port <PORT>
```

Then:

```powershell
ssh -p <PORT> `
  -i "$HOME\.ssh\factoryfly_amd" `
  -o IdentitiesOnly=yes `
  root@<HOST> `
  "echo SSH_OK"
```

Cloud host and port can change after instance recreation.

### ROCm is not visible

On Radeon Cloud:

```bash
/workspace/factoryfly-radeon/.venv-rocm/bin/python - <<'PY'
import torch
print("torch:", torch.__version__)
print("HIP:", torch.version.hip)
print("available:", torch.cuda.is_available())
print("GPU:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A")
PY
```

### DINOv2 checkpoint is missing

Expected path:

```text
/workspace/factoryfly-radeon/vendor/checkpoints/dinov2_vits14_pretrain.pth
```

Rerun `setup_radeon_cloud.sh`.

### No reinspection mission is generated

Confirm that Step 10 uses:

```text
Confirmed threshold: 0.62
Uncertain threshold: 0.70
```

Then click **Regenerate Change Triage**.

### Reinspection geometry is poor

Use a follow-up video that:

- approaches the same target area
- includes wider context before the close view
- avoids fast rotation and heavy blur
- keeps the target visible for multiple frames

The submitted implementation also supports change-tolerant reacquisition through the initial inspection view.

---

## 13. Generated Artifacts

Typical output hierarchy:

```text
baseline/<BASELINE_ID>/
├─ frames/
├─ reconstruction/
├─ poses/
├─ reports/
└─ logs/

<INSPECTION_ID>/
├─ video/
├─ telemetry/
├─ localization/
├─ pair_refinement/
├─ amd_analysis/
├─ change_triage/
├─ reinspection/
└─ reports/
```

Important artifacts include:

- baseline summary JSON
- localization summary JSON
- pose candidates CSV
- refined pairs CSV
- refinement summary JSON
- AMD package and result ZIPs
- DINOv2 score CSV/JSON
- change-triage JSON
- reinspection mission JSON
- reinspection result JSON
- final JSON, Markdown, and HTML reports

---

## 14. Security and Privacy

Never commit:

```text
SSH private keys
Real Radeon Cloud host and port
Personal absolute paths
Cloud credentials or tokens
Private source videos without consent
Generated caches and virtual environments
Large checkpoints
```

Use the supplied example configuration files.

The demonstration contains no employer data, employer code, confidential factory data, or company-owned assets. The project data were captured in the participant's private indoor environment.

---

## 15. Known Limitations

- The COLMAP coordinate system uses relative scale, not calibrated metres.
- The spatial mission map is approximate and is not a collision-free navigation map.
- Homography is a planar approximation.
- Localization depends on texture, overlap, lighting, and motion blur.
- Triage thresholds are demonstration policies, not probabilities.
- The current dataset is a proof of concept, not a statistically calibrated industrial benchmark.
- The drone and reinspection flight remain human-guided.
- FactoryFly reports visual change; it does not infer defect class or safety severity.

---

## 16. Team

**Jaewon Lee — Solo Developer**

Contributions include problem definition, system architecture, private data collection, COLMAP integration, geometry refinement, AMD Radeon Cloud and ROCm integration, DINOv2 inference workflow, triage, targeted reinspection, Streamlit UI, reporting, testing, and documentation.

AI-assisted development tools were used under the participant's direction for code drafting, debugging support, and documentation. The participant performed the project-specific architecture decisions, data collection, integration, execution, verification, and final submission.

---

## 17. Additional Documentation

- Technical report: `docs/FactoryFly_Sentinel_Technical_Report.pdf`
- Sample final report: `expected_results/final_change_report.html`
- Sample-data instructions: `sample_data/README.md`
- Local dependencies: `requirements-local.txt`
- Radeon dependencies: `requirements-rocm.txt`
