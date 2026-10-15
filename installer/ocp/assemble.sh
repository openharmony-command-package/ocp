#!/usr/bin/env bash
set -euo pipefail
ocp_recipe_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$ocp_recipe_dir/prepare.py" --abi "$OCP_ABI"
python3 "$ocp_recipe_dir/prepare-native.py" --abi "$OCP_ABI"
python3 "$OCP_ROOT/scripts/ocp.py" component --config "$ocp_recipe_dir/component.json" \
  --abi "$OCP_ABI" --stage "$OCP_STAGE" --metadata-dir "$OCP_METADATA_DIR"
