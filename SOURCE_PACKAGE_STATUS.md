# Public Source Package Status

## Included

- FactoryFly Sentinel v7.3.13 Streamlit application
- Active baseline, localization, pair-refinement, AMD-analysis, and
  reinspection source scripts
- v7.3.9b automatic-only AMD selection fix
- v7.3.12 change-tolerant reacquisition implementation
- v7.3.13 final-report reinspection metrics
- Portable project-root handling
- Sanitized Radeon Cloud and COLMAP examples
- Local and Radeon setup scripts
- Reproducibility README
- Technical report and final HTML example

## Deliberately excluded

- Virtual environments
- Backups and historical patch installers
- Private endpoints and SSH data
- Raw and derived inspection data
- DINOv2 checkpoint
- Generated COLMAP databases, sparse models, caches, logs, and archives
- Obsolete one-off registration scripts

## Still required before the final GitHub pull request

1. Add reduced public sample videos or verified external download links.
2. Add the final demo-video URL.
3. Choose a project-code licence if public reuse is intended.
4. Perform the clean Windows and Radeon Cloud smoke tests documented in README.

## v2 clean-validation corrections

- Treats an already-correct COLMAP default path as a successful configuration.
- Uses a literal MatchEvaluator when replacing the PowerShell `$ColmapBat` assignment.
- Propagates COLMAP-configuration and Python-syntax failures from `setup_local.ps1`.

## v3 packaging correction

- The ZIP top-level folder now matches the package name.
- No application logic changed from the validated v2 source.
