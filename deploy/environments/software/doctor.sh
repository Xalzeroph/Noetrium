#!/usr/bin/env bash
set -Eeuo pipefail
for command in gcc g++ make cmake ninja patch rsync; do
  command -v "$command" >/dev/null || { echo "software environment requires $command" >&2; exit 2; }
done
echo "software_toolchain=gcc,g++,make,cmake,ninja,patch,rsync"
