# FactoryFly Sentinel

**Human-Guided Physical AI for Active Factory Inspection**

FactoryFly Sentinel converts repeated human-operated drone inspections into localized visual-change evidence, routes uncertain observations to targeted reinspection, and produces a self-contained report for human review.

This repository accompanies the **AMD AI DevMaster Hackathon 2026 - Track 3** submission.

> **Scope:** FactoryFly reports observed visual changes and evidence quality. It does not decide whether a change is a defect, safety issue, or acceptable operation. A human reviewer assigns the operational disposition.

## 1. What this repository demonstrates

FactoryFly is a 13-stage, hybrid local/cloud workflow:

1. Build a COLMAP baseline from a human-guided reference flight.
2. Preserve sparse structure and camera poses as relative spatial memory.
3. Register a later inspection video.
4. Localize inspection frames inside the fixed baseline coordinate system.
5. Review localization coverage and trajectory continuity.
6. Retrieve nearby baseline cameras and refine image geometry.
7. Separate geometry-ready pairs from poor alignments.
8. Run DINOv2 semantic-change inference on an AMD Radeon GPU through ROCm.
9. Review heatmaps, scores, and runtime metadata.
10. Triage stable, confirmed, and geometrically uncertain evidence.
11. Generate a targeted reinspection mission.
12. Reacquire and analyze the uncertain target.
13. Generate a self-contained HTML evidence report.

The system is **human-guided**. It does not autonomously fly the drone or produce a certified collision-free route.

## 2. Execution architecture

### Windows workstation

- Streamlit UI
- FFmpeg frame extraction
- COLMAP sparse reconstruction and image registration
- SIFT, Fundamental Matrix RANSAC, Homography RANSAC, overlap, and reprojection checks
- Change triage
- Reinspection mission generation
- Final JSON, Markdown, and self-contained HTML reporting

### AMD Radeon Cloud

- Python 3.12
- PyTorch 2.9.1 with ROCm 7.2.1
- DINOv2 ViT-S/14 inference
- Relative semantic-change heatmaps and p95 scores
- GPU runtime and memory measurements

No local CUDA GPU is required for DINOv2 inference.

## 3. Repository layout

```text
factoryfly-sentinel/
├─ app.py
├─ README.md
├─ README_KO.md
├─ requirements-local.txt
├─ requirements-rocm.txt
├─ start_factoryfly.bat
├─ stop_factoryfly.bat
├─ config/
│  ├─ amd_cloud.example.json
│  └─ colmap.example.json
├─ scripts/
│  ├─ configure_colmap.ps1
│  ├─ create_factoryfly_shortcut.ps1
│  ├─ setup_local.ps1
│  ├─ setup_radeon_cloud.sh
│  └─ verify_radeon_cloud.sh
├─ shared/
│  ├─ config/
│  └─ scripts/
├─ sample_data/
│  ├─ README.md
│  └─ raw/
├─ expected_results/
│  └─ final_change_report.html
├─ docs/
│  ├─ FactoryFly_Sentinel_Technical_Report.pdf
│  ├─ FactoryFly_Sentinel_Technical_Report.md
│  └─ CLEAN_REPRODUCTION_VALIDATION.md
└─ submission/
   └─ demo_video_link.md
```

Derived frames, COLMAP databases, sparse models, AMD packages, logs, and reports are generated under the selected Baseline ID and Inspection ID. They are intentionally excluded from the public source package.

## 4. Validated environment

### Local workstation

- Windows 10/11
- Windows PowerShell 5.1 or later
- Python 3.12
- Streamlit 1.44 or later and below 2.0
- NumPy 1.26.x
- OpenCV 4.10.x
- FFmpeg on `PATH`
- OpenSSH client: `ssh` and `scp`
- COLMAP 4.1.1
- Tested COLMAP launcher: `C:\Tools\COLMAP\COLMAP.bat`

### Clean Radeon Cloud validation

The final clean run reported:

```text
ROCM_OK
GPU_OK
DINOV2_OK

Python : 3.12.3
PyTorch: 2.9.1+rocm7.2.1
HIP    : 7.2.53211
GPU    : AMD Radeon Graphics
VRAM   : 47.98 GiB
NumPy  : 1.26.4
OpenCV : 4.10.0
```

The displayed GPU name may be generic in the cloud container. `GPU_OK` and the ROCm/HIP values are the validation markers used by the project.

## 5. Required input data

The UI expects these paths for a full run:

```text
sample_data/raw/
├─ baseline.mp4
├─ inspection.mp4
├─ inspection_telemetry.txt
└─ reinspection.mp4
```

- `baseline.mp4`: reference flight before the demonstrated visual changes
- `inspection.mp4`: repeated inspection containing visible changes
- `reinspection.mp4`: targeted follow-up recording of an uncertain evidence location
- `inspection_telemetry.txt`: a file registered with the inspection input manifest

### Important telemetry limitation

The DJI flight-record file may use a `.txt` extension while containing binary data. In v7.3.13, FactoryFly **does not parse telemetry and does not use it for localization**. The registration stage only records the telemetry filename, size, modification time, and SHA256 hash. Visual localization is performed by COLMAP.

Therefore:

- No DJI API key is required.
- Do not assume the file is human-readable text.
- Do not publish a raw DJI flight record if it may contain GPS, device, or personal identifiers.
- A privacy-safe placeholder file is sufficient to exercise the current registration code, but it does not reproduce flight telemetry because telemetry is not consumed by the pipeline.

See `sample_data/README.md` for release and privacy guidance.

## 6. Quick result inspection

Open the included report:

```text
expected_results/final_change_report.html
```

The file is self-contained and includes embedded evidence images and interactive 3D mission context. The validated final summary is:

```text
Analyzed pairs             : 13
Stable cleared             : 7
Confirmed findings         : 4
Reinspections              : 1
Cleared after reinspection : 0
Unresolved                 : 0
```

The targeted follow-up result is:

```text
Geometry         : good
Initial p95      : 0.865
Reinspection p95 : 0.859
Conclusion       : Persistent visual change confirmed
```

These p95 values are relative semantic-change scores, not defect probabilities.

## 7. Local installation

Open Windows PowerShell from the repository root.

### 7.1 Install and verify prerequisites

```powershell
& "C:\Tools\COLMAP\COLMAP.bat" -h
ffmpeg -version
ssh -V
scp
```

### 7.2 Automated local setup

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\setup_local.ps1" `
  -ProjectRoot "$PWD" `
  -ColmapBat "C:\Tools\COLMAP\COLMAP.bat"
```

The script creates `.venv-vision`, installs local dependencies, checks required executables, and updates portable project/COLMAP paths.

### 7.3 Launch FactoryFly

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

A convenience launcher is also included:

```powershell
.\start_factoryfly.bat
```

## 8. Create a clean Radeon Cloud environment

The validated run used a **new Template and a new Instance**, not a previously configured workspace.

### 8.1 Suggested Template settings

```text
Title           : FactoryFly Sentinel
Category        : Computer Vision
Container image : AMD OneClick Base (ROCm 7.2.1 / Python 3.12)
GitHub Repo URL : https://github.com/lee2017-bit/factoryfly-sentinel
Branch          : main
Notebook Path   : blank
SSH Access      : enabled
Workspace       : Local SSD only
```

Host and external SSH port are assigned per instance and must never be committed.

### 8.2 Open Notebook Terminal first

After launching a new Instance, open its Notebook/Terminal once. Radeon Cloud Templates may place the repository under an instance-specific path such as `/workspace/template-repos/.../repo`.

Locate the checkout without hardcoding a template number:

```bash
REPO="$(find /workspace/template-repos \
  -type f \
  -path '*/repo/scripts/setup_radeon_cloud.sh' \
  -print -quit 2>/dev/null | sed 's#/scripts/setup_radeon_cloud.sh##')"

test -n "$REPO"
cd "$REPO"
pwd
ls app.py scripts/setup_radeon_cloud.sh scripts/verify_radeon_cloud.sh
```

If the Template did not check out the repository, clone it into `/workspace` and enter the repository root.

### 8.3 Install ROCm/DINOv2 and start SSH

From the repository root inside the Radeon Notebook Terminal:

```bash
bash scripts/setup_radeon_cloud.sh /workspace/factoryfly-radeon \
  2>&1 | tee /workspace/factoryfly_setup.log
```

The setup script:

- installs/starts `openssh-server`
- creates `/workspace/factoryfly-radeon/.venv-rocm`
- installs validated ROCm wheels
- obtains the DINOv2 source and ViT-S/14 checkpoint
- works around the Radeon image's known public-GitHub CA-chain issue with a secure-first, mirror-second, command-scoped fallback
- copies the verification script into the remote project root

The script does **not** disable TLS verification globally.

Expected final message:

```text
[PASS] Radeon Cloud environment installed
```

### 8.4 Verify Radeon access

```bash
bash /workspace/factoryfly-radeon/scripts/verify_radeon_cloud.sh \
  /workspace/factoryfly-radeon \
  2>&1 | tee /workspace/factoryfly_verify.log
```

Required markers:

```text
ROCM_OK
GPU_OK
DINOV2_OK
```

### 8.5 Verify external SSH from Windows

```powershell
Test-NetConnection <HOST> -Port <PORT>
```

Expected:

```text
TcpTestSucceeded : True
```

Then connect using the private key that remains on the Windows machine:

```powershell
ssh `
  -i "$HOME\.ssh\factoryfly_amd" `
  -p <PORT> `
  -o IdentitiesOnly=yes `
  root@<HOST>
```

Only the **public key** belongs in Radeon Cloud. Never upload or paste the private key.

## 9. Configure Step 8 - AMD Analysis

Use the current endpoint shown by the active Radeon Cloud instance:

```text
Execution mode:
  Run on Radeon Cloud via SSH

SSH host:
  <CURRENT HOST>

SSH port:
  <CURRENT PORT>

SSH user:
  root

Private key:
  C:\Users\<USER>\.ssh\factoryfly_amd

Remote project root:
  /workspace/factoryfly-radeon

Remote ROCm Python:
  /workspace/factoryfly-radeon/.venv-rocm/bin/python

Remote DINOv2 repository:
  /workspace/factoryfly-radeon/vendor/dinov2

Remote checkpoint:
  /workspace/factoryfly-radeon/vendor/checkpoints/dinov2_vits14_pretrain.pth
```

Click **Save SSH Settings** before running inference. The saved configuration stores the local key path, not the private-key contents.

## 10. Full reproduction procedure

Use new IDs for a clean run, for example:

```text
Baseline ID   : baseline_reproduction_001
Inspection ID : inspection_reproduction_001
```

### Step 1 - Baseline Registration

- Select the local `baseline.mp4`.
- Set **Frame sampling FPS** to `4`.
- Click **Build 3D Baseline**.

Validated sample result:

```text
Sampled frames     : 158
Registered cameras : 91
Registration rate  : 57.59%
Sparse 3D points   : 5,438
```

COLMAP sparse-point count can vary slightly across versions and hardware.

### Step 2 - Baseline Spatial Memory

Review the sparse model, camera trajectory, registration statistics, and active-baseline metadata. Coordinates are reconstructed relative units, not calibrated metres.

### Step 3 - Inspection Registration

Register:

```text
Inspection video     : sample_data/raw/inspection.mp4
Inspection telemetry : sample_data/raw/inspection_telemetry.txt
```

This stage stores input metadata and SHA256 hashes. It does not parse telemetry or alter the source files.

### Step 4 - Spatial Localization

- Set **Inspection frame sampling FPS** to `1`.
- Click **Run Spatial Localization**.

Validated result:

```text
Input frames             : 47
Registered frames        : 18
Registration rate        : 38.3%
Failed frames            : 29
Longest continuous run   : 16
```

The baseline source model remains fixed; inspection poses are registered into an isolated working copy.

### Step 5 - Localization Result

Review the baseline/inspection trajectories, failed-frame list, registration timeline, and spatial coverage.

### Step 6 - Pair Refinement

- Set **Top-K baseline candidates per inspection frame** to `5`.
- Run pair refinement with overwrite enabled when repeating the stage.

Validated result:

| Metric | Result |
|---|---:|
| Candidate pairs | 90 |
| Excellent | 3 |
| Good | 5 |
| Usable | 4 |
| Poor | 6 |
| AMD-ready | 12 |
| High confidence | 8 |
| Median reprojection error | 0.962 px |

### Step 7 - Pair Result

Review geometry classes and candidate comparisons. Non-poor pairs are routed automatically to AMD analysis. Poor pairs are not treated as confirmed evidence without a reviewer decision.

### Step 8 - AMD Analysis

Use:

```text
Automatic geometry-ready pairs : all 12 available
Reviewer-selected pairs        : at least one high-change, poor-geometry pair
Visual Borderline Review       : select the poor-geometry pair manually
Batch pairs                    : 2
```

The reviewer-selected pair is necessary to validate the targeted-reinspection branch. Do **not** hardcode a frame number in general reproduction instructions; frame identifiers are dataset/run dependent.

FactoryFly v7.3.13 final source accepts both `current` and `preview` AMD workspaces. This includes the validated `WorkspaceName` PowerShell parameter fix.

Click **Run AMD Analysis**. Expected stages:

```text
1 / 4 - Prepare privacy-filtered AMD package
2 / 4 - Create Radeon Cloud run directory
3 / 4 - Upload and execute AMD DINOv2 analysis
Run ROCm DINOv2 on Radeon Cloud
4 / 4 - Download AMD results
```

Validated Radeon result:

```text
Analyzed pairs  : 13
Automatic pairs : 12
Reviewer pairs  : 1
Batch pairs     : 2
Mean ms/pair    : 4.75
Pairs/second    : 210.46
Peak GPU memory : 133.7 MB
```

`xFormers is not available` is a non-fatal optimization warning in this environment.

### Step 9 - AMD Result

Review the baseline, inspection, warped baseline, DINOv2 overlay, p95/p99/mean scores, valid-patch counts, and benchmark JSON.

Warm colors indicate greater relative semantic difference inside valid overlap. They are not calibrated defect probabilities or severity scores.

### Step 10 - Change Triage

Set:

```text
Confirmed-change p95 threshold : 0.62
Uncertain-change p95 threshold : 0.70
```

Validated initial routing:

```text
Confirmed change clusters : 3
Needs reinspection        : 1
Automatically cleared     : 7
```

The 13 analyzed image pairs are consolidated into localized evidence clusters. Therefore the triage route counts do not have to sum to the raw pair count.

### Step 11 - Reinspection Mission

Generate the mission and review:

- the target baseline reference camera position
- the baseline and inspection trajectories
- approximate sparse spatial structure
- relative Right/Left, Straight/Back, and Up/Down directions

Mission IDs, frame numbers, and evidence-cluster numbers are generated from the current run. They must not be hardcoded in the README.

### Step 12 - Reinspection Analysis

Select `sample_data/raw/reinspection.mp4` and run the generated mission.

Validated result:

```text
Geometry         : good
Initial p95      : 0.865
Reinspection p95 : 0.859
Conclusion       : Persistent visual change confirmed
```

Reacquisition may use either direct baseline-to-reinspection geometry or a change-tolerant bridge through the initial inspection view.

### Step 13 - Final Report

Generate the consolidated report. FactoryFly produces JSON, Markdown, and self-contained HTML outputs.

Validated final summary:

```text
Analyzed pairs             : 13
Stable cleared             : 7
Confirmed findings         : 4
Reinspections              : 1
Cleared after reinspection : 0
Unresolved                 : 0
```

The four confirmed findings consist of three initial confirmed evidence clusters plus one persistent change confirmed after targeted reinspection.

## 11. Reproducibility acceptance criteria

The run is considered successful when:

- the baseline sparse model is constructed
- inspection frames are localized in the same coordinate system
- pair refinement produces geometry-ready comparisons
- `ROCM_OK`, `GPU_OK`, and `DINOV2_OK` are reported on a new Radeon instance
- 12 automatic geometry-ready pairs and at least one reviewer-selected poor-geometry pair are analyzed
- one geometrically uncertain high-change target is routed to reinspection
- the target is reacquired with usable geometry
- the self-contained final report is generated

Minor variation in COLMAP point count, exact frame IDs, scores, and runtime is expected across hardware and software builds.

## 12. Troubleshooting

### External SSH port times out

If ping succeeds but `Test-NetConnection <HOST> -Port <PORT>` is false, open the Radeon Notebook Terminal and run the setup script. It installs and starts `sshd`.

Verify inside the instance:

```bash
pgrep -a sshd
ss -lntp | grep ':22'
```

### GitHub certificate verification fails in Radeon Cloud

The final setup script tries:

1. official GitHub with the system CA bundle
2. the Radeon Cloud Git mirror
3. a command-scoped insecure fallback only for the public DINOv2 source/checkpoint when enabled

It never writes a global `http.sslVerify=false` setting. To disable the fallback:

```bash
FACTORYFLY_ALLOW_INSECURE_TLS_FALLBACK=0 \
  bash scripts/setup_radeon_cloud.sh /workspace/factoryfly-radeon
```

### `WorkspaceName` is not recognized

Use the final source version of:

```text
shared/scripts/run_amd_analysis.ps1
```

It defines `WorkspaceName` with `current` and `preview` values. Earlier v3 packaging omitted this parameter.

### No reinspection mission is generated

A threshold change cannot create uncertain evidence when every analyzed pair has good/usable geometry. Return to Step 8 and reviewer-select at least one high-change pair whose geometry is classified as `poor`, then overwrite and rerun AMD analysis.

### `xFormers is not available`

This is a performance warning, not an inference failure. Confirm that all requested pairs completed and that the result archive was downloaded.

### COLMAP metrics differ slightly

Sparse reconstruction can vary with COLMAP version, CPU, threading, and numerical order. Use the acceptance criteria rather than requiring an identical sparse-point count.

## 13. Generated artifacts

Typical outputs include:

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
├─ change_detection/
│  └─ <BASELINE_ID>/
│     ├─ pair_refinement/
│     ├─ amd_analysis/
│     └─ change_triage/
├─ reinspection/
└─ reports/
```

Important artifacts include baseline/localization summaries, refined-pair CSV, AMD package/result archives, score CSV/JSON, reinspection mission/result JSON, and final JSON/Markdown/HTML reports.

## 14. Security and privacy

Never commit:

```text
SSH private keys
Real Radeon Cloud host or port
Cloud tokens or credentials
Personal absolute paths
Raw DJI flight records containing identifiers
Private source videos without consent
Virtual environments or caches
DINOv2 checkpoints
Generated COLMAP/AMD archives
```

The demonstration contains no employer data, employer code, confidential factory information, or company-owned assets. Source footage was captured by the participant in a private indoor environment.

## 15. Known limitations

- COLMAP scale is relative, not calibrated metric scale.
- The 3D mission map is approximate and not a collision-free navigation map.
- Homography is a planar approximation.
- Localization depends on texture, overlap, lighting, and motion blur.
- DINOv2 scores and triage thresholds are not probabilities.
- The current dataset is a proof of concept, not an industrial benchmark.
- Drone operation and reinspection remain human-guided.
- FactoryFly reports visual change; it does not infer defect class or safety severity.
- Telemetry is registered but not parsed or used for localization in v7.3.13.

## 16. Team

**Jaewon Lee - Solo Developer**

Contributions include problem definition, architecture, private data collection, COLMAP integration, geometry refinement, AMD Radeon Cloud/ROCm integration, DINOv2 inference, triage, targeted reinspection, Streamlit UI, reporting, testing, and documentation.

AI-assisted development tools were used under the participant's direction for drafting, debugging support, and documentation. The participant performed the project-specific design decisions, data collection, integration, execution, verification, and final submission.

## 17. Additional documentation

- Technical report: `docs/FactoryFly_Sentinel_Technical_Report.pdf`
- Clean validation record: `docs/CLEAN_REPRODUCTION_VALIDATION.md`
- Sample final report: `expected_results/final_change_report.html`
- Sample-data guidance: `sample_data/README.md`
- Local dependencies: `requirements-local.txt`
- Radeon dependencies: `requirements-rocm.txt`
