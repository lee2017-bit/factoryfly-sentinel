# Clean Reproduction Validation

**Validation date:** 5 August 2026  
**FactoryFly version:** v7.3.13 final public-source package  
**Method:** New Windows run IDs + new Radeon Cloud Template + new Radeon Cloud Instance

## Cloud environment

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

## Baseline

| Metric | Result |
|---|---:|
| Sampled frames | 158 |
| Registered cameras | 91 |
| Registration rate | 57.59% |
| Sparse points | 5,438 |

## Inspection localization

| Metric | Result |
|---|---:|
| Input frames | 47 |
| Registered frames | 18 |
| Registration rate | 38.3% |
| Failed frames | 29 |
| Longest continuous run | 16 |

## Pair refinement

| Metric | Result |
|---|---:|
| Top-K | 5 |
| Candidate pairs | 90 |
| Excellent | 3 |
| Good | 5 |
| Usable | 4 |
| Poor | 6 |
| AMD-ready | 12 |
| High confidence | 8 |
| Median reprojection error | 0.962 px |

## AMD analysis

| Metric | Result |
|---|---:|
| Automatic geometry-ready pairs | 12 |
| Reviewer-selected poor-geometry pairs | 1 |
| Total analyzed pairs | 13 |
| Batch pairs | 2 |
| Mean latency | 4.75 ms/pair |
| Throughput | 210.46 pairs/s |
| Peak GPU memory | 133.7 MB |

## Triage and reinspection

```text
Confirmed change clusters : 3
Needs reinspection        : 1
Automatically cleared     : 7
```

Pair results are clustered into localized evidence entries before triage, so route counts are not expected to equal the raw pair count.

```text
Reinspection geometry : good
Initial p95           : 0.865
Reinspection p95      : 0.859
Result                : Persistent visual change confirmed
```

## Final report

```text
Analyzed pairs             : 13
Stable cleared             : 7
Confirmed findings         : 4
Reinspections              : 1
Cleared after reinspection : 0
Unresolved                 : 0
```

## Issues found and corrected during clean validation

1. `WorkspaceName` was passed by the Streamlit app but missing from `run_amd_analysis.ps1`.
2. The Radeon Cloud base image did not automatically start `sshd`.
3. The Radeon image had a public-GitHub certificate-chain issue during DINOv2 setup.
4. Automatic geometry-ready pairs alone did not exercise the reinspection branch; one high-change poor-geometry pair had to be reviewer-selected.
5. Earlier documentation incorrectly listed inspection sampling at 4 FPS and older 18-pair report metrics.

The final source and README incorporate these corrections without hardcoding instance endpoints, template IDs, frame IDs, or mission IDs.
