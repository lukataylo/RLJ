#!/bin/zsh
# Double-clickable launcher: starts the PulseGo Driver Expo dev server with the
# QR code, from the correct project directory.
cd "/Users/lukadadiani/RLJ/mobile" || exit 1
echo "Starting Expo in: $(pwd)"
exec npx expo start
