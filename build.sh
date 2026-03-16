#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "=== Building Desktop Lights.app ==="

# Clean previous builds
rm -rf build dist

# Build the .app bundle
pyinstaller desktop_lights.spec

echo ""
echo "✓ Build complete: dist/Desktop Lights.app"
echo ""
echo "To install: drag 'dist/Desktop Lights.app' to /Applications"
echo "Note: On first launch, grant Screen Recording permission in"
echo "      System Settings > Privacy & Security > Screen Recording"
