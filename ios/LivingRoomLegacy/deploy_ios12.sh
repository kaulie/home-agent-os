#!/usr/bin/env bash
# Deploy LivingRoomLegacy to iOS 12.x device (Xcode 26 lacks native 12.x support).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJ="$ROOT/LivingRoomLegacy.xcodeproj"
SCHEME="LivingRoomLegacy"
SUPPORT_SRC="$ROOT/.device-support"
XCODE_SUPPORT="/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/DeviceSupport"

echo "== 1/4 DeviceSupport (iOS 12.4 → 12.5.8 alias) =="
if [[ ! -d "$SUPPORT_SRC/12.4 (16G73)" ]]; then
  mkdir -p "$SUPPORT_SRC"
  curl -fsSL -o "$SUPPORT_SRC/12.4.zip" \
    "https://github.com/isatria/Xcode-iOS-DeviceSupport/raw/master/src/12.4%20(16G73).zip"
  unzip -qo "$SUPPORT_SRC/12.4.zip" -d "$SUPPORT_SRC"
  cp -R "$SUPPORT_SRC/12.4 (16G73)" "$SUPPORT_SRC/12.5.8 (16H41)"
fi

if [[ ! -d "$XCODE_SUPPORT/12.5.8 (16H41)" ]]; then
  echo "需要把 DeviceSupport 拷进 Xcode（只需做一次，会要管理员密码）："
  echo "  sudo cp -R \"$SUPPORT_SRC/12.4 (16G73)\" \"$XCODE_SUPPORT/\""
  echo "  sudo cp -R \"$SUPPORT_SRC/12.5.8 (16H41)\" \"$XCODE_SUPPORT/\""
  read -r -p "现在执行上述 sudo 拷贝？[y/N] " ans
  if [[ "${ans:-}" =~ ^[Yy]$ ]]; then
    sudo cp -R "$SUPPORT_SRC/12.4 (16G73)" "$XCODE_SUPPORT/"
    sudo cp -R "$SUPPORT_SRC/12.5.8 (16H41)" "$XCODE_SUPPORT/"
  else
    echo "跳过。若 ios-deploy / Xcode 仍报 disk image，请先完成拷贝。"
  fi
fi

echo ""
echo "== 2/4 检查老 iPhone 连接 =="
if ! command -v ios-deploy >/dev/null 2>&1; then
  echo "安装 ios-deploy: brew install ios-deploy"
  exit 1
fi
ios-deploy --detect || true
echo ""
echo "若看不到设备：USB 连接 → 解锁 → 信任此电脑 → 关闭 Xcode 后重试"

echo ""
echo "== 3/4 编译 (iphoneos) =="
python3 "$ROOT/generate_xcodeproj.py" >/dev/null
xcodebuild \
  -project "$PROJ" \
  -scheme "$SCHEME" \
  -configuration Debug \
  -destination 'generic/platform=iOS' \
  -allowProvisioningUpdates \
  build

APP="$(find ~/Library/Developer/Xcode/DerivedData/LivingRoomLegacy-*/Build/Products/Debug-iphoneos -name 'LivingRoomLegacy.app' -maxdepth 1 2>/dev/null | head -1)"
if [[ -z "$APP" || ! -d "$APP" ]]; then
  echo "找不到 LivingRoomLegacy.app，请检查 xcodebuild 输出"
  exit 1
fi
echo "Built: $APP"

echo ""
echo "== 4/4 安装到老 iPhone =="
ios-deploy --bundle "$APP" --justlaunch
echo "完成。"
