#!/system/bin/sh
set -eu
. ./native.env
unset OCP_REPOSITORY
export OCP_STATE_DIR="$PWD/native-state"
rm -rf "$OCP_STATE_DIR"
test -t 0
echo OCP_NATIVE_LIFECYCLE_BEGIN
ocp doctor
ocp tap add core "$OCP_NATIVE_CATALOG"
ocp update
ocp sync
if [ -f "$OCP_STATE_DIR/installed/core@zig" ]; then ocp uninstall core/zig; fi
ocp install core/zig --version 0.16.0
test "$(zig version)" = 0.16.0
echo OCP_NATIVE_INSTALL_016_OK
ocp upgrade core/zig
test "$(zig version)" = 0.17.0
echo OCP_NATIVE_UPGRADE_017_OK
ocp uninstall core/zig
if command -v zig; then exit 1; fi
echo OCP_NATIVE_UNINSTALL_OK
OCP_OFFLINE=1 ocp install core/zig
test "$(zig version)" = 0.17.0
echo OCP_NATIVE_CACHED_REINSTALL_OK
# A second PTY state directory can discover the same installed HNP links.
OCP_STATE_DIR="$PWD/second-state" ocp tap add core "$OCP_NATIVE_CATALOG"
OCP_STATE_DIR="$PWD/second-state" ocp update
OCP_STATE_DIR="$PWD/second-state" ocp sync
test "$(cut -f1 "$PWD/second-state/installed/core@zig")" = 0.17.0
echo OCP_NATIVE_CROSS_HOST_SYNC_OK
ocp tap add community "$OCP_NATIVE_COMMUNITY"
ocp update
ocp sync
if [ -f "$OCP_STATE_DIR/installed/community@hello" ]; then ocp uninstall community/hello; fi
ocp install community/hello
test "$(ocp-hello --version)" = OCP_TAP_HELLO_OK
echo OCP_NATIVE_THIRD_PARTY_OK
ocp uninstall community/hello
before=$(cat "$OCP_STATE_DIR/catalogs/current")
ocp tap add wrong_namespace "$OCP_NATIVE_CATALOG"
if ocp update; then exit 1; fi
test "$(cat "$OCP_STATE_DIR/catalogs/current")" = "$before"
ocp tap remove wrong_namespace
echo OCP_NATIVE_INDEX_TRANSACTION_OK
if ocp-bm uninstall com.richerfu.ocp; then exit 1; fi
echo OCP_NATIVE_NAMESPACE_GUARD_OK
echo OCP_NATIVE_LIFECYCLE_OK
