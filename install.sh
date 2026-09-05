#!/usr/bin/env bash
# ==============================================================================
# FoldGPT: Native ChatGPT Desktop on Samsung Galaxy Z Fold
# 1-Click Automated Installer (Zero Root, 100% Official Unmodified OpenAI Binary)
# ==============================================================================
set -euo pipefail

echo "============================================================"
echo "           FoldGPT: Native ChatGPT on Galaxy Z Fold         "
echo "============================================================"
echo "[*] Verifying architecture..."
ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ]; then
    echo "[-] Error: FoldGPT requires an ARM64 (aarch64) device. Detected: $ARCH"
    exit 1
fi
echo "[+] ARM64 architecture confirmed."

echo "[*] Updating Termux packages and installing dependencies..."
pkg update -y
pkg install -y proot-distro x11-repo pulseaudio xdotool clang make git

echo "[*] Ensuring Termux:X11 package is installed..."
pkg install -y termux-x11-nightly || true

DISTRO_NAME="fold-debian"
echo "[*] Setting up Debian environment ($DISTRO_NAME)..."
if ! proot-distro list | grep -q "$DISTRO_NAME.*installed"; then
    proot-distro install debian --override-alias "$DISTRO_NAME"
fi

echo "[*] Installing dependencies inside Debian..."
proot-distro login "$DISTRO_NAME" -- bash -c "
    apt-get update && apt-get install -y build-essential curl libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libgtk-3-0 libasound2 libxss1 xdg-utils xdotool libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libcairo2
"

echo "[*] Compiling user-space sandbox compatibility shim (fake_userns.so)..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$PREFIX/var/lib/proot-distro/installed-rootfs/$DISTRO_NAME/usr/local/src"
cp "$SCRIPT_DIR/fake_userns.c" "$PREFIX/var/lib/proot-distro/installed-rootfs/$DISTRO_NAME/usr/local/src/fake_userns.c"

proot-distro login "$DISTRO_NAME" -- bash -c "
    gcc -O3 -shared -fPIC /usr/local/src/fake_userns.c -o /usr/local/lib/libfake_userns.so -ldl
    echo '/usr/local/lib/libfake_userns.so' > /etc/ld.so.preload
"

echo "[*] Downloading official OpenAI ChatGPT desktop Linux ARM64 package..."
OPENAI_DEB_URL="https://persistent.oaistatic.com/sidecar-packages/chatgpt-26.901.41600_arm64.deb"
proot-distro login "$DISTRO_NAME" -- bash -c "
    mkdir -p /tmp/chatgpt-install
    cd /tmp/chatgpt-install
    if [ ! -f chatgpt.deb ]; then
        echo '[*] Fetching official .deb from OpenAI...'
        curl -fSL -o chatgpt.deb '$OPENAI_DEB_URL' || true
    fi
    if [ -f chatgpt.deb ]; then
        dpkg -i chatgpt.deb || apt-get install -f -y
        echo '[+] Official ChatGPT desktop installed successfully.'
    else
        echo '[!] Please place the official OpenAI chatgpt.deb into /tmp/chatgpt-install/chatgpt.deb and run: dpkg -i /tmp/chatgpt-install/chatgpt.deb'
    fi
"

echo "[*] Setting up desktop user and directories..."
proot-distro login "$DISTRO_NAME" -- bash -c "
    if ! id -u julien >/dev/null 2>&1; then
        useradd -m -s /bin/bash julien
        usermod -aG sudo,audio,video julien
    fi
    mkdir -p /home/julien/Projects
    chown -R julien:julien /home/julien
"

echo "[*] Installing start script to ~/start_chatgpt.sh..."
cp "$SCRIPT_DIR/start_chatgpt.sh" "$HOME/start_chatgpt.sh"
chmod +x "$HOME/start_chatgpt.sh"

echo "============================================================"
echo "[✓] FOLDGPT INSTALLATION COMPLETE!"
echo ""
echo "Quick Start:"
echo "  ~/start_chatgpt.sh"
echo "============================================================"
