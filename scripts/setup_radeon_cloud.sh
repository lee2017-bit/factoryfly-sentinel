#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${1:-/workspace/factoryfly-radeon}"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"
ALLOW_INSECURE_TLS_FALLBACK="${FACTORYFLY_ALLOW_INSECURE_TLS_FALLBACK:-1}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CA_BUNDLE="/etc/ssl/certs/ca-certificates.crt"

echo "FactoryFly Radeon Cloud setup"
echo "Root: $ROOT"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  openssh-server iproute2 \
  python3.12 python3.12-venv python3.12-dev \
  build-essential cmake ninja-build \
  git wget curl ca-certificates

update-ca-certificates || true

mkdir -p /run/sshd /root/.ssh
chmod 700 /root/.ssh
ssh-keygen -A
pgrep -x sshd >/dev/null || /usr/sbin/sshd

mkdir -p "$ROOT/vendor/checkpoints" "$ROOT/scripts"

clone_dinov2() {
  local target="$1"
  local official="https://github.com/facebookresearch/dinov2.git"
  local radeon_mirror="https://gh-test.anruicloud.com/facebookresearch/dinov2.git"

  rm -rf "$target"

  echo "Cloning DINOv2 from the official repository."
  if GIT_SSL_CAINFO="$CA_BUNDLE" git clone --depth 1 "$official" "$target"; then
    return 0
  fi

  echo "[WARN] Official GitHub TLS validation failed; trying the Radeon Cloud mirror."
  rm -rf "$target"
  if git clone --depth 1 "$radeon_mirror" "$target"; then
    return 0
  fi

  if [[ "$ALLOW_INSECURE_TLS_FALLBACK" == "1" ]]; then
    echo "[WARN] Both secure clone paths failed."
    echo "[WARN] Retrying only this public DINOv2 clone with TLS verification disabled."
    rm -rf "$target"
    GIT_SSL_NO_VERIFY=true git clone --depth 1 "$official" "$target"
    return 0
  fi

  echo "[ERROR] DINOv2 clone failed and insecure fallback is disabled." >&2
  echo "Set FACTORYFLY_ALLOW_INSECURE_TLS_FALLBACK=1 only if the Radeon image has a known CA-chain issue." >&2
  return 1
}

download_checkpoint() {
  local target="$1"
  local url="https://dl.fbaipublicfiles.com/dinov2/dinov2_vits14/dinov2_vits14_pretrain.pth"

  echo "Downloading the public DINOv2 ViT-S/14 checkpoint."
  if curl --fail --location --retry 5 --retry-delay 3 \
      --cacert "$CA_BUNDLE" -o "$target" "$url"; then
    return 0
  fi

  if [[ "$ALLOW_INSECURE_TLS_FALLBACK" == "1" ]]; then
    echo "[WARN] Checkpoint TLS validation failed."
    echo "[WARN] Retrying only this public checkpoint download with TLS verification disabled."
    curl --insecure --fail --location --retry 5 --retry-delay 3 \
      -o "$target" "$url"
    return 0
  fi

  echo "[ERROR] Checkpoint download failed and insecure fallback is disabled." >&2
  return 1
}

if [[ ! -d "$ROOT/vendor/dinov2/.git" ]]; then
  clone_dinov2 "$ROOT/vendor/dinov2"
fi

CHECKPOINT="$ROOT/vendor/checkpoints/dinov2_vits14_pretrain.pth"
if [[ ! -s "$CHECKPOINT" ]]; then
  rm -f "$CHECKPOINT"
  download_checkpoint "$CHECKPOINT"
fi

# Reject obvious HTML/error responses before the expensive Python setup.
CHECKPOINT_BYTES="$(stat -c%s "$CHECKPOINT")"
if [[ "$CHECKPOINT_BYTES" -lt 50000000 ]]; then
  echo "[ERROR] DINOv2 checkpoint is unexpectedly small: $CHECKPOINT_BYTES bytes" >&2
  exit 1
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

download_wheel() {
  local name="$1"
  local url="$2"

  if [[ ! -s "$WHEEL_ROOT/$name" ]]; then
    wget -c -O "$WHEEL_ROOT/$name" "$url"
  fi
}

torch_ready() {
  "$PY" - <<'PYTORCH' >/dev/null 2>&1
import torch
assert torch.version.hip
assert torch.cuda.is_available()
PYTORCH
}

if ! torch_ready; then
  download_wheel "$TORCH_WHEEL" \
    "https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/torch-2.9.1%2Brocm7.2.1.lw.gitff65f5bc-cp312-cp312-linux_x86_64.whl"
  download_wheel "$VISION_WHEEL" \
    "https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/torchvision-0.24.0%2Brocm7.2.1.gitb919bd0c-cp312-cp312-linux_x86_64.whl"
  download_wheel "$TRITON_WHEEL" \
    "https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/triton-3.5.1%2Brocm7.2.1.gita272dfa8-cp312-cp312-linux_x86_64.whl"
  download_wheel "$AUDIO_WHEEL" \
    "https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/torchaudio-2.9.0%2Brocm7.2.1.gite3c6ee2b-cp312-cp312-linux_x86_64.whl"

  "$PY" -m pip install \
    "$WHEEL_ROOT/$TORCH_WHEEL" \
    "$WHEEL_ROOT/$VISION_WHEEL" \
    "$WHEEL_ROOT/$TRITON_WHEEL" \
    "$WHEEL_ROOT/$AUDIO_WHEEL"
fi

"$PY" -m pip install --no-deps "opencv-python-headless==4.10.0.84"

cp "$SCRIPT_DIR/verify_radeon_cloud.sh" \
  "$ROOT/scripts/verify_radeon_cloud.sh"
chmod +x "$ROOT/scripts/verify_radeon_cloud.sh"

echo
echo "[PASS] Radeon Cloud environment installed"
echo "Python     : $PY"
echo "DINOv2     : $ROOT/vendor/dinov2"
echo "Checkpoint : $CHECKPOINT"
echo
echo "Run verification:"
echo "bash $ROOT/scripts/verify_radeon_cloud.sh $ROOT"
