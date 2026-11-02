#!/usr/bin/env bash
set -euo pipefail

REPO_RAW="${TRAE_SWITCH_RAW:-https://raw.githubusercontent.com/dubiao/trae-switch/main}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
TARGET="$BIN_DIR/trae-switch"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "提示：本工具只支持 macOS 上的 Trae CN。"
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "错误：需要 Python 3。" >&2
    exit 1
fi

SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

TMP=""
cleanup() {
    if [ -n "$TMP" ] && [ -f "$TMP" ]; then
        rm -f "$TMP"
    fi
}
trap cleanup EXIT

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/src/trae_switch.py" ]; then
    SRC="$SCRIPT_DIR/src/trae_switch.py"
else
    TMP="$(mktemp)"
    echo "正在下载源码..."
    curl -fsSL "$REPO_RAW/src/trae_switch.py" -o "$TMP"
    SRC="$TMP"
fi

mkdir -p "$BIN_DIR"
install -m 755 "$SRC" "$TARGET"

echo "已安装：$TARGET"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "提示：$BIN_DIR 不在 PATH 中，请把它加入 shell 配置。" ;;
esac
echo "运行 'trae-switch current' 查看当前账号。"
