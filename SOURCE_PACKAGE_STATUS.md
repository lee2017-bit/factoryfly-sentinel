# Public Source Package Status

## Included

- FactoryFly Sentinel v7.3.13 Streamlit application
- Baseline, localization, pair-refinement, AMD-analysis, triage, reinspection, and report source scripts
- Automatic-only AMD selection support
- `WorkspaceName` current/preview hotfix validated in the clean run
- Change-tolerant target reacquisition
- Reinspection geometry and initial/reinspection p95 cards in the final report
- Portable local project/COLMAP path configuration
- Clean Radeon setup that installs/starts SSH and handles the Radeon CA-chain issue
- English and Korean reproducibility READMEs
- Clean reproduction validation record
- Technical report and actual clean-run HTML report

## Clean validation completed

The full 13-stage path was executed with new local run IDs and a new Radeon Cloud instance. Required cloud markers were `ROCM_OK`, `GPU_OK`, and `DINOV2_OK`. The final report recorded 13 analyzed pairs, 7 stable clears, 4 confirmed findings, 1 reinspection, and 0 unresolved findings.

## Deliberately excluded

- Virtual environments
- Backups and historical patch installers
- Real cloud endpoints and SSH data
- Raw/private inspection footage and raw DJI telemetry
- DINOv2 checkpoint
- Generated COLMAP databases, sparse models, caches, logs, and archives

## External submission items still supplied separately

1. Public/reduced sample clips or verified download links and hashes, if full raw-input reproduction is claimed.
2. Final public demo-video URL in `submission/demo_video_link.md`.
3. A project-code license if public reuse beyond hackathon evaluation is intended.

## v4 final corrections

- Added the validated `WorkspaceName` parameter to `run_amd_analysis.ps1`.
- Added secure-first DINOv2 setup with Radeon mirror and command-scoped fallback.
- Documented Notebook-first SSH bootstrap on a new Radeon instance.
- Corrected Baseline FPS to 4 and Inspection FPS to 1.
- Documented 12 automatic pairs plus at least one reviewer-selected poor-geometry pair.
- Removed hardcoded frame, cluster, mission, template, host, and port identifiers from reproduction instructions.
- Corrected telemetry description: binary-capable file, metadata/hash only, not used for localization.
- Updated final validation metrics to 13/7/4/1/0/0 and reinspection p95 0.865/0.859.
