#!/system/bin/sh
# Run from the terminal application's PTY. The destination must not exist.
set -u
if [ "$#" -ne 1 ] || [ -e "$1" ]; then
  printf 'Usage: sh zig_default_workflow.sh NEW_DIRECTORY\n' >&2
  exit 2
fi
export PATH=/data/service/hnp/bin:/data/app/bin:/system/bin
mkdir "$1" || exit 1
cd "$1" || exit 1
export ZIG_GLOBAL_CACHE_DIR="$PWD/.cache/zig"
log="$PWD/workflow.log"
exec 3>&1
: >"$log"
exec >>"$log" 2>&1
finish() {
  result=$?
  trap - EXIT
  cat "$log" >&3
  exit "$result"
}
trap finish EXIT
printf 'PTY: '
tty
printf 'Domain: '
cat /proc/self/attr/current
printf '\n'
grep -E '^(NoNewPrivs|Seccomp|Seccomp_filters):' /proc/self/status
printf 'Fresh global cache: %s\n' "$ZIG_GLOBAL_CACHE_DIR"
zig version || exit "$?"
zig init
result=$?
printf 'ZIG_INIT_EXIT=%s\n' "$result"
[ "$result" -eq 0 ] || exit "$result"
zig build test
result=$?
printf 'ZIG_TEST_EXIT=%s\n' "$result"
[ "$result" -eq 0 ] || exit "$result"
zig build run
result=$?
printf 'ZIG_RUN_EXIT=%s\n' "$result"
exit "$result"
