#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${1:-/workspace/factoryfly-radeon}"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"

echo "FactoryFly Radeon Cloud setup"
echo "Root: $ROOT"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  openssh-server iproute2 \
  python3.12 python3.12-venv python3.12-dev \
  build-essential cmake ninja-build \
  git wget curl ca-certificates

mkdir -p /run/sshd /root/.ssh
chmod 700 /root/.ssh
ssh-keygen -A
pgrep -x sshd >/dev/null || /usr/sbin/sshd

mkdir -p "$ROOT/vendor/checkpoints" "$ROOT/scripts"

if [[ ! -d "$ROOT/vendor/dinov2/.git" ]]; then
  rm -rf "$ROOT/vendor/dinov2"
  git clone --depth 1 https://github.com/facebookresearch/dinov2.git \
    "$ROOT/vendor/dinov2"
fi

CHECKPOINT="$ROOT/vendor/checkpoints/dinov2_vits14_pretrain.pth"
if [[ ! -s "$CHECKPOINT" ]]; then
  wget -c \
    -O "$CHECKPOINT" \
    https://dl.fbaipublicfiles.com/dinov2/dinov2_vits14/dinov2_vits14_pretrain.pth
fi

VENV="$ROOT/.venv-rocm"
PY="$VENV/bin/python"

if [[ ! -x "$PY" ]]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi

"$PY" -m pip install --upgrade pip setuptools wheel
"$PY" -m pip install "numpy==1.26.4"

WHEEL_ROOT="/workspace/rocm721-wheels"
mkdir -p "$WHEEL_ROOT"

TORCH_WHEEL="torch-2.9.1+rocm7.2.1.lw.gitff65f5bc-cp312-cp312-linux_x86_64.whl"
VISION_WHEEL="torchvision-0.24.0+rocm7.2.1.gitb919bd0c-cp312-cp312-linux_x86_64.whl"
TRITON_WHEEL="triton-3.5.1+rocm7.2.1.gita272dfa8-cp312-cp312-linux_x86_64.whl"
AUDIO_WHEEL="torchaudio-2.9.0+rocm7.2.1.gite3c6ee2b-cp312-cp312-linux_x86_64.whl"

download() {
  local name="$1"
  local url="$2"

  if [[ ! -s "$WHEEL_ROOT/$name" ]]; then
    wget -c -O "$WHEEL_ROOT/$name" "$url"
  fi
}

torch_ready() {
  "$PY" - <<'PY' >/dev/null 2>&1
import torch
assert torch.version.hip
assert torch.cuda.is_available()
PY
}

if ! torch_ready; then
  download "$TORCH_WHEEL" \
    "https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/torch-2.9.1%2Brocm7.2.1.lw.gitff65f5bc-cp312-cp312-linux_x86_64.whl"
  download "$VISION_WHEEL" \
    "https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/torchvision-0.24.0%2Brocm7.2.1.gitb919bd0c-cp312-cp312-linux_x86_64.whl"
  download "$TRITON_WHEEL" \
    "https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/triton-3.5.1%2Brocm7.2.1.gita272dfa8-cp312-cp312-linux_x86_64.whl"
  download "$AUDIO_WHEEL" \
    "https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/torchaudio-2.9.0%2Brocm7.2.1.gite3c6ee2b-cp312-cp312-linux_x86_64.whl"

  "$PY" -m pip install \
    "$WHEEL_ROOT/$TORCH_WHEEL" \
    "$WHEEL_ROOT/$VISION_WHEEL" \
    "$WHEEL_ROOT/$TRITON_WHEEL" \
    "$WHEEL_ROOT/$AUDIO_WHEEL"
fi

"$PY" -m pip install --no-deps "opencv-python-headless==4.10.0.84"

cp "$(dirname "$0")/verify_radeon_cloud.sh" \
  "$ROOT/scripts/verify_radeon_cloud.sh" 2>/dev/null || true
chmod +x "$ROOT/scripts/verify_radeon_cloud.sh" 2>/dev/null || true

echo
echo "[PASS] Radeon Cloud environment installed"
echo "Python     : $PY"
echo "DINOv2     : $ROOT/vendor/dinov2"
echo "Checkpoint : $CHECKPOINT"
echo
echo "Run verification:"
echo "bash $ROOT/scripts/verify_radeon_cloud.sh"
