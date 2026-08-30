#!/usr/bin/env bash
# Deploy LivingRoomPickup to iOS 12.x device.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJ="$ROOT/LivingRoomPickup.xcodeproj"
SCHEME="LivingRoomPickup"
DEVICE_ID="${PICKUP_DEVICE_ID:-f1b21669ee34f92cb8014c43d2b16fd84eaa88e9}"

echo "== 1/3 检查设备 =="
if ! command -v ios-deploy >/dev/null 2>&1; then
  echo "安装 ios-deploy: brew install ios-deploy"
  exit 1
fi
ios-deploy --detect || true

echo ""
echo "== 2/3 编译 (iphoneos) =="
python3 "$ROOT/generate_xcodeproj.py"
xcodebuild \
  -project "$PROJ" \
  -scheme "$SCHEME" \
  -configuration Debug \
  -destination 'generic/platform=iOS' \
  -allowProvisioningUpdates \
  build

APP="$(find ~/Library/Developer/Xcode/DerivedData/LivingRoomPickup-*/Build/Products/Debug-iphoneos -name 'LivingRoomPickup.app' -maxdepth 1 2>/dev/null | head -1)"
if [[ -z "$APP" || ! -d "$APP" ]]; then
  echo "找不到 LivingRoomPickup.app，请检查 xcodebuild 输出"
  exit 1
fi
echo "Built: $APP"
# Wake-ack CAF must ship or legacy hears nothing after「面条面条」.
if [[ ! -f "$APP/wake_ack_wozaine.caf" ]]; then
  echo "ERROR: wake_ack_wozaine.caf missing from app bundle (generate_xcodeproj Resources?)"
  exit 1
fi

echo ""
echo "== 3/3 安装到老 iPhone =="
ios-deploy --id "$DEVICE_ID" --bundle "$APP" --justlaunch
echo "完成。"
