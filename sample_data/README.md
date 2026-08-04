# Sample Data

Full reproduction requires the following files:

```text
sample_data/raw/
├─ baseline.mp4
├─ inspection.mp4
├─ inspection_telemetry.txt
└─ reinspection.mp4
```

## Data definitions

- `baseline.mp4`: reference flight before the demonstrated scene changes
- `inspection.mp4`: repeated inspection containing the visible changes
- `inspection_telemetry.txt`: DJI flight-record telemetry corresponding to the inspection
- `reinspection.mp4`: targeted follow-up recording for the uncertain evidence mission

## Privacy

The original demonstration was recorded in a private indoor environment by the participant.

Before public submission:

- remove unrelated private footage
- remove visible personal documents or identifiers
- preserve enough visual context for COLMAP and target reacquisition
- retain the original frame order and video metadata where practical
- provide SHA256 hashes for the released clips

## Packaging options

Use one of the following:

1. Commit reduced clips directly if repository limits permit.
2. Store clips in a release asset or file host and add verified download links here.
3. Provide extracted frame sets plus the exact commands used to generate them.

The final submission must not leave this data location ambiguous, because full raw-input reproduction depends on it.
