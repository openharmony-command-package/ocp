#!/usr/bin/env bash
set -euo pipefail

export OCP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export OCP_ABI=arm64-v8a
if [[ $# -gt 0 ]]; then
  [[ $# -eq 2 && "$1" == --abi ]] || { echo 'Usage: build-hnp.sh [--abi arm64-v8a|x86_64|armeabi-v7a]' >&2; exit 2; }
  OCP_ABI="$2"
fi

export OCP_STAGE="$(python3 "$OCP_ROOT/scripts/ocp.py" prepare --abi "$OCP_ABI")"
export OCP_METADATA_DIR="$(dirname "$OCP_STAGE")/components"

# Each component owns its assembly. Adding a directory requires no edit here.
ocp_count=0
for ocp_assembler in "$OCP_ROOT"/installer/*/assemble.sh; do
  [[ -f "$ocp_assembler" ]] || continue
  ocp_config="$(dirname "$ocp_assembler")/component.json"
  if [[ -f "$ocp_config" ]]; then
    ocp_bootstrap=$(python3 - "$ocp_config" <<'PY'
import json,sys
print('yes' if json.load(open(sys.argv[1])).get('bootstrap', True) else 'no')
PY
)
    [[ "$ocp_bootstrap" == yes ]] || continue
  fi
  "$ocp_assembler"
  ocp_count=$((ocp_count + 1))
done
[[ $ocp_count -gt 0 ]] || { echo 'No installer/*/assemble.sh found' >&2; exit 1; }
python3 "$OCP_ROOT/scripts/ocp.py" pack --abi "$OCP_ABI"
