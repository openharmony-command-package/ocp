#!/system/bin/sh
set -eu

ocp_runtime=$(dirname "$(readlink -f "$0")")
ocp_state=${OCP_STATE_DIR:-${TMPDIR:-/data/storage/el2/base/cache}/ocp}
ocp_maker="$ocp_runtime/ocp-maker"
ocp_bm="$ocp_runtime/ocp-bm"
ocp_tab=$(printf '\t')
export OCP_CA_BUNDLE="$ocp_runtime/cacert.pem"
mkdir -p "$ocp_state/cache" "$ocp_state/installed" "$ocp_state/taps" "$ocp_state/catalogs/generations"

ocp_fail() { echo "ocp: $*" >&2; exit 1; }
ocp_name() { case "$1" in ''|.|..|*[!a-zA-Z0-9_.-]*) ocp_fail 'Invalid name or version' ;; esac; }
ocp_tap_name() { case "$1" in ''|*[!a-z0-9_]*|[0-9_]*) ocp_fail 'Tap names use lowercase letters, digits and underscores, starting with a letter' ;; esac; }
ocp_url() {
  case "$1" in *[![:graph:]]*) ocp_fail 'URL contains whitespace or control characters' ;; esac
  case "$1" in https://?*|http://?*) ;; *) ocp_fail 'Use an HTTP or HTTPS catalog URL' ;; esac
}
ocp_identity() {
  case "$1" in */*) ocp_source=${1%%/*}; ocp_tool=${1#*/} ;; *) ocp_fail 'Use TAP/TOOL' ;; esac
  ocp_tap_name "$ocp_source"; ocp_name "$ocp_tool"
  ocp_key="${ocp_source}@${ocp_tool}"
}
ocp_fetch() {
  ocp_hash=$("$ocp_maker" fetch --zig-lib="$ocp_runtime" --zig="$ocp_maker" \
    --global-cache="$ocp_state/cache" --seed=0 --pkg-dir "$ocp_state/cache/p" "$1")
  ocp_name "$ocp_hash"
  printf '%s\n' "$ocp_state/cache/p/$ocp_hash"
}
ocp_index_path() {
  if [ -f "$ocp_state/catalogs/current" ]; then
    ocp_generation=$(cat "$ocp_state/catalogs/current"); ocp_name "$ocp_generation"
    ocp_index="$ocp_state/catalogs/generations/$ocp_generation/index.tsv"
  else ocp_index="$ocp_state/index.tsv"; fi
}
ocp_register() {
  ocp_tap_name "$1"; ocp_url "$2"
  if [ -f "$ocp_state/taps/$1" ] && [ "$(cat "$ocp_state/taps/$1")" != "$2" ]; then
    ocp_fail 'Tap already has a different URL; remove it before changing its origin'
  fi
  printf '%s\n' "$2" > "$ocp_state/taps/$1.new"
  mv "$ocp_state/taps/$1.new" "$ocp_state/taps/$1"
}
ocp_update() {
  if [ -n "${OCP_REPOSITORY:-}" ]; then ocp_register core "$OCP_REPOSITORY"; fi
  ocp_generation="$(date +%s)-$$"
  ocp_pending="$ocp_state/catalogs/generations/$ocp_generation"
  mkdir -p "$ocp_pending"
  : > "$ocp_pending/index.tsv"; : > "$ocp_pending/sources.tsv"
  ocp_count=0
  for ocp_registration in "$ocp_state"/taps/*; do
    [ -f "$ocp_registration" ] || continue
    ocp_source=$(basename "$ocp_registration"); ocp_tap_name "$ocp_source"
    ocp_origin=$(cat "$ocp_registration"); ocp_url "$ocp_origin"
    ocp_catalog=$(ocp_fetch "$ocp_origin")
    [ -f "$ocp_catalog/index.tsv" ] || ocp_fail 'Catalog has no index.tsv'
    if [ -f "$ocp_catalog/registry.tsv" ]; then
      IFS="$ocp_tab" read -r ocp_protocol ocp_declared < "$ocp_catalog/registry.tsv"
      [ "$ocp_protocol" = 2 ] && [ "$ocp_declared" = "$ocp_source" ] || ocp_fail 'Registry protocol or namespace mismatch'
    elif [ "$ocp_source" != core ]; then ocp_fail 'Third-party taps require registry protocol 2'; fi
    while IFS="$ocp_tab" read -r ocp_tool ocp_ver ocp_abi ocp_bundle ocp_sha ocp_url_value ocp_latest ocp_commands; do
      [ -n "$ocp_tool" ] || continue
      ocp_name "$ocp_tool"; ocp_name "$ocp_ver"
      case "$ocp_abi" in arm64-v8a|x86_64|armeabi-v7a) ;; *) ocp_fail 'Unknown catalog ABI' ;; esac
      if [ "$ocp_source" = core ]; then ocp_expected="com.richerfu.ocp.pkg.$ocp_tool"
      else ocp_expected="com.richerfu.ocp.pkg.$ocp_source.$ocp_tool"; fi
      [ "$ocp_bundle" = "$ocp_expected" ] || ocp_fail 'Catalog bundle does not match its namespace'
      case "$ocp_sha" in *[!0-9a-f]*|'') ocp_fail 'Invalid checksum' ;; esac
      [ ${#ocp_sha} -eq 64 ] || ocp_fail 'Invalid checksum length'
      case "$ocp_latest" in 0|1) ;; *) ocp_fail 'Invalid latest marker' ;; esac
      ocp_url "$ocp_url_value"
      ocp_commands=${ocp_commands:-$ocp_tool}
      case "$ocp_commands" in *[!a-zA-Z0-9_.+,-]*) ocp_fail 'Invalid exported commands' ;; esac
      case ",$ocp_commands," in *",ocp,"*|*",ocp-maker,"*|*",ocp-bm,"*) ocp_fail 'Catalog exports a reserved OCP command' ;; esac
      printf '%s/%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$ocp_source" "$ocp_tool" "$ocp_ver" "$ocp_abi" "$ocp_bundle" "$ocp_sha" "$ocp_url_value" "$ocp_latest" "$ocp_commands" >> "$ocp_pending/index.tsv"
    done < "$ocp_catalog/index.tsv"
    printf '%s\t%s\t%s\n' "$ocp_source" "$ocp_origin" "$(basename "$ocp_catalog")" >> "$ocp_pending/sources.tsv"
    ocp_count=$((ocp_count + 1))
  done
  [ "$ocp_count" -gt 0 ] || ocp_fail 'No taps registered; use ocp tap add NAME URL'
  ocp_duplicates=$(cut -f 1-3 "$ocp_pending/index.tsv" | sort | uniq -d)
  [ -z "$ocp_duplicates" ] || ocp_fail 'Catalog contains duplicate package versions'
  printf '%s\n' "$ocp_generation" > "$ocp_state/catalogs/current.new"
  mv "$ocp_state/catalogs/current.new" "$ocp_state/catalogs/current"
  echo "Catalog updated ($ocp_count taps)"
}
ocp_resolve() {
  case "$ocp_package" in */*) ocp_identity "$ocp_package"; return ;; esac
  ocp_name "$ocp_package"
  ocp_match=
  while IFS="$ocp_tab" read -r ocp_candidate ocp_rest; do
    case "$ocp_candidate" in */"$ocp_package") ;; *) continue ;; esac
    [ -f "$ocp_state/taps/${ocp_candidate%%/*}" ] || continue
    if [ -n "$ocp_match" ] && [ "$ocp_match" != "$ocp_candidate" ]; then ocp_fail 'Ambiguous tool name; use TAP/TOOL'; fi
    ocp_match=$ocp_candidate
  done < "$ocp_index"
  [ -n "$ocp_match" ] || ocp_fail "Tool unavailable: $ocp_package"
  ocp_package=$ocp_match; ocp_identity "$ocp_package"
}
ocp_lookup() {
  ocp_index_path
  [ -f "$ocp_index" ] || ocp_update >&2
  ocp_index_path; ocp_resolve
  [ -f "$ocp_state/taps/$ocp_source" ] || ocp_fail 'Register the tool source before installing or upgrading'
  case "$(uname -m)" in aarch64) ocp_machine=arm64-v8a ;; x86_64) ocp_machine=x86_64 ;; arm*) ocp_machine=armeabi-v7a ;; *) ocp_fail 'Unsupported architecture' ;; esac
  ocp_found=0
  while IFS="$ocp_tab" read -r ocp_pkg ocp_ver ocp_abi ocp_bundle ocp_sha ocp_url_value ocp_latest ocp_commands; do
    [ "$ocp_pkg" = "$ocp_package" ] && [ "$ocp_abi" = "$ocp_machine" ] || continue
    if [ -n "$ocp_requested" ]; then [ "$ocp_ver" = "$ocp_requested" ] || continue
    else [ "$ocp_latest" = 1 ] || continue; fi
    ocp_found=1; break
  done < "$ocp_index"
  [ "$ocp_found" = 1 ] || ocp_fail "Package/version unavailable: $ocp_package"
}
ocp_apply() {
  [ -x "$ocp_bm" ] || ocp_fail 'Device BMS adapter is missing; reinstall the OCP bootstrap'
  if [ "$1" = uninstall ]; then "$ocp_bm" uninstall "$ocp_bundle"
  else
    if [ "$ocp_source" = core ]; then ocp_hnp="ocp_$ocp_tool"
    else ocp_hnp="ocp_${ocp_source}_$ocp_tool"; fi
    "$ocp_bm" install "$ocp_payload/$ocp_tool.hap" "$ocp_bundle" "$ocp_ver" "$ocp_machine" "$ocp_hnp" "$ocp_commands"
  fi
}
ocp_conflicts() {
  for ocp_receipt in "$ocp_state"/installed/*; do
    [ -f "$ocp_receipt" ] || continue
    IFS="$ocp_tab" read -r ocp_oldver ocp_oldbundle ocp_oldsha ocp_oldcommands ocp_oldpackage < "$ocp_receipt"
    [ "$ocp_oldpackage" != "$ocp_package" ] || continue
    ocp_oldifs=$IFS; IFS=,
    for ocp_command in $ocp_commands; do
      case ",$ocp_oldcommands," in *",$ocp_command,"*) ocp_fail "Command $ocp_command is owned by $ocp_oldpackage" ;; esac
    done
    IFS=$ocp_oldifs
  done
}
ocp_sync() {
  ocp_index_path; [ -f "$ocp_index" ] || ocp_fail 'Update registered catalogs before synchronizing'
  case "$(uname -m)" in aarch64) ocp_local_abi=arm64-v8a ;; x86_64) ocp_local_abi=x86_64 ;; arm*) ocp_local_abi=armeabi-v7a ;; *) ocp_fail 'Unsupported architecture' ;; esac
  ocp_snapshot_file="$ocp_state/cache/native-installed.$$.tsv"; : > "$ocp_snapshot_file"
  while IFS="$ocp_tab" read -r ocp_package ocp_ver ocp_abi ocp_bundle ocp_sha ocp_url_value ocp_latest ocp_commands; do
    [ "$ocp_abi" = "$ocp_local_abi" ] || continue
    ocp_identity "$ocp_package"
    if [ "$ocp_source" = core ]; then ocp_hnp="ocp_$ocp_tool"; else ocp_hnp="ocp_${ocp_source}_$ocp_tool"; fi
    if "$ocp_bm" status "$ocp_hnp" "$ocp_ver" "$ocp_commands"; then
      printf '%s\t%s\t%s\t%s\t%s\n' "$ocp_package" "$ocp_ver" "$ocp_bundle" "$ocp_sha" "$ocp_commands" >> "$ocp_snapshot_file"
    else
      ocp_status=$?; [ "$ocp_status" = 3 ] || ocp_fail 'Cannot read installed HNP command state'
    fi
  done < "$ocp_index"
  ocp_pending="$ocp_state/installed.pending"; rm -rf "$ocp_pending"; mkdir -p "$ocp_pending"
  while IFS="$ocp_tab" read -r ocp_package ocp_ver ocp_bundle ocp_sha ocp_commands; do
    [ -n "$ocp_package" ] || continue
    ocp_identity "$ocp_package"; ocp_name "$ocp_ver"
    case "$ocp_sha" in *[!0-9a-f]*|'') ocp_fail 'Invalid checksum' ;; esac
    [ ${#ocp_sha} -eq 64 ] || ocp_fail 'Invalid checksum length'
    printf '%s\t%s\t%s\t%s\t%s\n' "$ocp_ver" "$ocp_bundle" "$ocp_sha" "$ocp_commands" "$ocp_package" > "$ocp_pending/$ocp_key"
  done < "$ocp_snapshot_file"
  rm -rf "$ocp_state/installed.previous"; mv "$ocp_state/installed" "$ocp_state/installed.previous"
  mv "$ocp_pending" "$ocp_state/installed"; rm -rf "$ocp_state/installed.previous"
  rm -f "$ocp_snapshot_file"
  echo 'Installed packages synchronized'
}

case "${1:-help}" in
  tap)
    case "${2:-list}" in
      add) [ $# -eq 4 ] || ocp_fail 'Usage: ocp tap add NAME URL'; ocp_register "$3" "$4"; echo "Tap $3 registered; run ocp update" ;;
      remove)
        [ $# -eq 3 ] || ocp_fail 'Usage: ocp tap remove NAME'; ocp_tap_name "$3"
        for ocp_receipt in "$ocp_state"/installed/"$3"@*; do [ ! -f "$ocp_receipt" ] || ocp_fail 'Uninstall this tap’s managed tools before removing it'; done
        rm -f "$ocp_state/taps/$3"; echo "Tap $3 removed" ;;
      list) for ocp_registration in "$ocp_state"/taps/*; do [ -f "$ocp_registration" ] || continue; printf '%s\t%s\n' "$(basename "$ocp_registration")" "$(cat "$ocp_registration")"; done ;;
      *) ocp_fail 'Usage: ocp tap add NAME URL | tap remove NAME | tap list' ;;
    esac ;;
  update) ocp_update ;;
  doctor) "$ocp_bm" doctor ;;
  sync) ocp_sync ;;
  install|upgrade)
    [ $# -ge 2 ] || ocp_fail 'Usage: ocp install TAP/TOOL [--version VERSION]'
    ocp_package=$2; ocp_requested=
    if [ $# -gt 2 ]; then [ $# -eq 4 ] && [ "$3" = --version ] || ocp_fail 'Invalid version option'; ocp_requested=$4; ocp_name "$ocp_requested"; fi
    ocp_lookup
    ocp_sync
    # Sync uses shared shell variables; restore the selected catalog entry.
    ocp_package=$2; ocp_lookup; ocp_conflicts
    ocp_cached_payload="$ocp_state/cache/bottles/$ocp_sha"
    if [ -f "$ocp_cached_payload/$ocp_tool.hap" ]; then ocp_payload=$ocp_cached_payload
    else
      [ "${OCP_OFFLINE:-0}" != 1 ] || ocp_fail 'Bottle is not available in the verified local cache'
      ocp_payload=$(ocp_fetch "$ocp_url_value")
    fi
    [ -f "$ocp_payload/$ocp_tool.hap" ] || ocp_fail 'Bottle has no HAP'
    ocp_actual=$(sha256sum "$ocp_payload/$ocp_tool.hap"); ocp_actual=${ocp_actual%% *}
    [ "$ocp_actual" = "$ocp_sha" ] || ocp_fail 'HAP checksum mismatch'
    if [ "$ocp_payload" != "$ocp_cached_payload" ]; then
      mkdir -p "$ocp_cached_payload"
      cp "$ocp_payload/$ocp_tool.hap" "$ocp_cached_payload/$ocp_tool.hap.new"
      mv "$ocp_cached_payload/$ocp_tool.hap.new" "$ocp_cached_payload/$ocp_tool.hap"
      ocp_payload=$ocp_cached_payload
    fi
    ocp_apply install
    printf '%s\t%s\t%s\t%s\t%s\n' "$ocp_ver" "$ocp_bundle" "$ocp_sha" "$ocp_commands" "$ocp_package" > "$ocp_state/installed/$ocp_key.new"
    mv "$ocp_state/installed/$ocp_key.new" "$ocp_state/installed/$ocp_key"
    echo "$ocp_package $ocp_ver installed" ;;
  uninstall)
    [ $# -eq 2 ] || ocp_fail 'Usage: ocp uninstall TAP/TOOL'
    ocp_package=$2
    case "$ocp_package" in */*) ocp_identity "$ocp_package" ;; *)
      ocp_name "$ocp_package"; ocp_match=
      for ocp_receipt in "$ocp_state"/installed/*@"$ocp_package"; do
        [ -f "$ocp_receipt" ] || continue
        [ -z "$ocp_match" ] || ocp_fail 'Ambiguous tool name; use TAP/TOOL'
        ocp_match=$(basename "$ocp_receipt")
      done
      [ -n "$ocp_match" ] || ocp_fail 'Package has no installation receipt'
      ocp_package="${ocp_match%%@*}/${ocp_match#*@}"; ocp_identity "$ocp_package" ;;
    esac
    [ -f "$ocp_state/installed/$ocp_key" ] || ocp_fail 'Package has no installation receipt; run ocp sync'
    IFS="$ocp_tab" read -r ocp_ver ocp_bundle ocp_sha ocp_commands ocp_package < "$ocp_state/installed/$ocp_key"
    ocp_apply uninstall; rm "$ocp_state/installed/$ocp_key"; echo "$ocp_package uninstalled" ;;
  list)
    for ocp_receipt in "$ocp_state"/installed/*; do
      [ -f "$ocp_receipt" ] || continue
      IFS="$ocp_tab" read -r ocp_ver ocp_bundle ocp_sha ocp_commands ocp_package < "$ocp_receipt"
      printf '%s\t%s\n' "$ocp_package" "$ocp_ver"
    done ;;
  help|--help|-h) echo 'Usage: ocp tap add NAME URL | tap remove NAME | tap list | update | sync | doctor | install TAP/TOOL [--version VERSION] | upgrade TAP/TOOL | uninstall TAP/TOOL | list' ;;
  *) ocp_fail "Unknown command: $1" ;;
esac
