#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${1:-/workspace/factoryfly-radeon}"
PY="$ROOT/.venv-rocm/bin/python"
DINO="$ROOT/vendor/dinov2"
CHECKPOINT="$ROOT/vendor/checkpoints/dinov2_vits14_pretrain.pth"

[[ -x "$PY" ]] || { echo "ROCm Python missing: $PY"; exit 10; }
[[ -d "$DINO" ]] || { echo "DINOv2 source missing: $DINO"; exit 11; }
[[ -s "$CHECKPOINT" ]] || { echo "Checkpoint missing: $CHECKPOINT"; exit 12; }

"$PY" - <<PY
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

root = Path(r"$ROOT")
dino = root / "vendor" / "dinov2"
checkpoint = root / "vendor" / "checkpoints" / "dinov2_vits14_pretrain.pth"

assert torch.version.hip
assert torch.cuda.is_available()
assert dino.is_dir()
assert checkpoint.is_file() and checkpoint.stat().st_size > 0

sys.path.insert(0, str(dino))
import dinov2

a = torch.randn((512, 512), device="cuda", dtype=torch.float16)
b = torch.randn((512, 512), device="cuda", dtype=torch.float16)
c = a @ b
torch.cuda.synchronize()
assert torch.isfinite(c).all().item()

print("ROCM_OK")
print("GPU_OK")
print("DINOV2_OK")
print(json.dumps({
    "python": sys.version.split()[0],
    "torch": torch.__version__,
    "hip": torch.version.hip,
    "gpu": torch.cuda.get_device_name(0),
    "vram_gib": round(
        torch.cuda.get_device_properties(0).total_memory / 1024**3,
        2,
    ),
    "numpy": np.__version__,
    "opencv": cv2.__version__,
    "dinov2_repo": str(dino),
    "checkpoint": str(checkpoint),
}, indent=2))
PY
