#!/bin/sh
set -eu
python3 - "$OCP_ROOT" "$OCP_ABI" <<'PY'
import sys, subprocess
from pathlib import Path
root=Path(sys.argv[1]); abi=sys.argv[2]
sys.path.insert(0,str(root/'scripts'))
from ocp import sdk_path
sdk=sdk_path()/"native"
target={"arm64-v8a":"aarch64-linux-ohos","x86_64":"x86_64-linux-ohos","armeabi-v7a":"arm-linux-ohos"}[abi]
source=root/'build/example-tap/hello'/abi
source.mkdir(parents=True,exist_ok=True)
subprocess.run([sdk/'llvm/bin/clang',f'--target={target}',f'--sysroot={sdk / "sysroot"}',
               root/'example/tap/installer/hello/hello.c','-O2','-o',source/'ocp-hello'],check=True)
PY
python3 "$OCP_ROOT/scripts/ocp.py" component --config "$OCP_COMPONENT_CONFIG" --abi "$OCP_ABI" --stage "$OCP_STAGE" --metadata-dir "$OCP_METADATA_DIR"
