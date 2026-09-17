#!/usr/bin/env bash
set -euo pipefail

packages=(
  build-essential git git-lfs curl ca-certificates
  cmake ninja-build pkg-config clang lld llvm
  gdb lldb python3 python3-venv python3-pip
  sqlite3 libsqlite3-dev ffmpeg jq ripgrep fd-find
  qemu-system-x86 ovmf mtools dosfstools openssl libssl-dev
)

echo "CASULO WSL CORE INSTALLER"
printf '  %s\n' "${packages[@]}"

if [[ "${1:-}" != "--apply" ]]; then
  echo
  echo "DRY RUN: no packages were installed."
  echo "Run: bash scripts/03-install-wsl-core.sh --apply"
  exit 0
fi

if ! grep -qiE 'ubuntu|debian' /etc/os-release; then
  echo "Unsupported distribution for this script. Review commands manually." >&2
  exit 2
fi

sudo apt-get update
sudo apt-get install -y --no-install-recommends "${packages[@]}"
git lfs install

echo
echo "WSL core packages installed."
echo "Install Rust with the official rustup procedure, then pin the toolchain in the repository."
echo "Install Node according to the repository lock/version file; avoid unneeded global packages."
