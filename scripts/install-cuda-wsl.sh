#!/usr/bin/env bash
# WSL2 에 llama.cpp 를 CUDA 로 빌드하는 데 필요한 것만 설치합니다: nvcc, CUDA runtime, cuBLAS (약 1GB).
# GPU 드라이버는 설치하지 않습니다. WSL 은 Windows 의 NVIDIA 드라이버를 그대로 쓰고, Ubuntu 의
# nvidia-cuda-toolkit 패키지는 리눅스용 드라이버 라이브러리(libnvidia-compute)를 같이 깔아 충돌합니다.
#
#   sudo bash scripts/install-cuda-wsl.sh [드라이버가 지원하는 최대 CUDA 버전, 예: 13.1]
#
# 버전을 주면 그보다 높지 않은 nvcc 를 고릅니다 (Windows 의 nvidia-smi 맨 위 "CUDA Version").
set -euo pipefail

MAX="${1:-}"
REPO=https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64
APT=(-o Acquire::Max-FutureTime=86400)
export DEBIAN_FRONTEND=noninteractive

if ! dpkg -s cuda-keyring >/dev/null 2>&1; then
    tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/cuda-keyring.deb" "$REPO/cuda-keyring_1.1-1_all.deb"
    dpkg -i "$tmp/cuda-keyring.deb"
    rm -rf "$tmp"
fi
apt-get "${APT[@]}" -q update

# 최소 버전: 최근 Ubuntu 의 gcc(14, 15)는 CUDA 12 의 nvcc 가 지원하지 않고, glibc 2.42+ (Ubuntu 26.04 는 2.43)의
# math.h 는 CUDA 13.1 이하 헤더와 rsqrt 선언이 충돌해 아무것도 컴파일되지 않습니다 (13.2, 13.3 은 확인)
glibc=$(ldd --version | head -1 | grep -oE '[0-9]+\.[0-9]+$')
MIN=13.0
if [ "$(printf '%s\n%s\n' "$glibc" 2.42 | sort -V | head -1)" = "2.42" ]; then MIN=13.2; fi
le() { [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -1)" = "$1" ]; }

best=""
for v in $(apt-cache search --names-only '^cuda-nvcc-1[3-9]-[0-9]*$' | cut -d' ' -f1 | sed 's/^cuda-nvcc-//' | sort -V); do
    dotted="${v/-/.}"
    if le "$MIN" "$dotted" && { [ -z "$MAX" ] || le "$dotted" "$MAX"; }; then best="$v"; fi
done
if [ -z "$best" ]; then
    echo "이 Ubuntu(glibc $glibc)에는 CUDA $MIN 이상이 필요한데, Windows 의 NVIDIA 드라이버는 CUDA ${MAX:-?} 까지만 지원합니다." >&2
    echo "Windows 에서 NVIDIA 드라이버를 최신으로 업데이트한 뒤 다시 실행하세요 (PowerShell 의 nvidia-smi 맨 위 'CUDA Version' 이 $MIN 이상)." >&2
    exit 1
fi

apt-get "${APT[@]}" -q -y install --no-install-recommends \
    "cuda-nvcc-$best" "cuda-cudart-dev-$best" "libcublas-dev-$best" "cuda-cccl-$best" "cuda-driver-dev-$best"
ln -sfn "/usr/local/cuda-${best/-/.}" /usr/local/cuda
echo "CUDA ${best/-/.} 설치: /usr/local/cuda/bin/nvcc"
