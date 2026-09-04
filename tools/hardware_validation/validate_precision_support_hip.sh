#!/usr/bin/env bash
# Compiles and runs validate_precision_support_hip.cpp against the local
# GPU. Requires hipcc (a ROCm/HIP install) and a real AMD GPU -- neither
# is a dependency of this project's own uv-managed environment.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

binary="$(mktemp)"
trap 'rm -f "$binary"' EXIT

hipcc --offload-arch=native -O2 -o "$binary" validate_precision_support_hip.cpp
"$binary" "$@"
