# Sample Data

A full FactoryFly run expects these paths:

```text
sample_data/raw/
├─ baseline.mp4
├─ inspection.mp4
├─ inspection_telemetry.txt
└─ reinspection.mp4
```

## File roles

- `baseline.mp4`: reference flight before the demonstrated scene changes
- `inspection.mp4`: repeated inspection containing visible changes
- `reinspection.mp4`: targeted follow-up recording for the uncertain evidence mission
- `inspection_telemetry.txt`: file registered with the inspection manifest

## Telemetry limitation in v7.3.13

The DJI flight-record file can have a `.txt` extension while containing binary data. FactoryFly v7.3.13 does not parse this file and does not use telemetry for localization. `register_inspection_inputs.ps1` records only:

- filename
- full path
- file size
- modification time
- SHA256 hash

COLMAP visual registration performs localization. No DJI API key is required.

Because raw DJI flight records may contain GPS, device, or personal identifiers, do not commit the original file without a privacy review. A privacy-safe placeholder file can exercise the current registration path, but it does not reproduce telemetry because the current pipeline does not consume telemetry content.

## Privacy

The original demonstration was recorded by the participant in a private indoor environment. Before public release:

- remove unrelated private footage
- remove visible documents or personal identifiers
- preserve enough visual context for COLMAP and target reacquisition
- retain frame order and timing where practical
- provide SHA256 hashes for released clips

## Packaging options

1. Commit reduced clips directly if repository limits permit.
2. Publish clips as a release asset and provide verified links and hashes.
3. Provide extracted frame sets plus exact extraction commands.

Do not leave the released input location ambiguous if full reproduction is claimed.
