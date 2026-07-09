#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: install-cli-wrapper.sh --hermes-bin PATH --link PATH [--link PATH ...] [options]

Install a PATH-visible Hermes launcher that execs an explicit venv binary.

Options:
  --hermes-bin PATH              Hermes console-script binary to execute.
  --link PATH                    Launcher path to write. May be repeated.
  --force                        Replace an existing non-managed launcher.
  --slack-doppler-env-file PATH  Optional env file to source for `hermes send --to slack...`.
  --doppler-bin PATH             Doppler binary for the optional Slack route.
  --slack-doppler-project NAME   Doppler project for the optional Slack route.
  --slack-doppler-config NAME    Doppler config for the optional Slack route.
  -h, --help                     Show this help.
USAGE
}

die() {
  echo "install-cli-wrapper: $*" >&2
  exit 1
}

hermes_bin=""
force=false
links=()
slack_doppler_env_file=""
doppler_bin="/usr/bin/doppler"
slack_doppler_project=""
slack_doppler_config=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --hermes-bin)
      [ "$#" -ge 2 ] || die "--hermes-bin requires a value"
      hermes_bin="$2"
      shift 2
      ;;
    --link)
      [ "$#" -ge 2 ] || die "--link requires a value"
      links+=("$2")
      shift 2
      ;;
    --force)
      force=true
      shift
      ;;
    --slack-doppler-env-file)
      [ "$#" -ge 2 ] || die "--slack-doppler-env-file requires a value"
      slack_doppler_env_file="$2"
      shift 2
      ;;
    --doppler-bin)
      [ "$#" -ge 2 ] || die "--doppler-bin requires a value"
      doppler_bin="$2"
      shift 2
      ;;
    --slack-doppler-project)
      [ "$#" -ge 2 ] || die "--slack-doppler-project requires a value"
      slack_doppler_project="$2"
      shift 2
      ;;
    --slack-doppler-config)
      [ "$#" -ge 2 ] || die "--slack-doppler-config requires a value"
      slack_doppler_config="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[ -n "$hermes_bin" ] || die "--hermes-bin is required"
[ "${#links[@]}" -gt 0 ] || die "at least one --link is required"
[ -x "$hermes_bin" ] || die "Hermes binary is not executable: $hermes_bin"

if [ -n "$slack_doppler_env_file" ]; then
  [ -n "$slack_doppler_project" ] || die "--slack-doppler-project is required with --slack-doppler-env-file"
  [ -n "$slack_doppler_config" ] || die "--slack-doppler-config is required with --slack-doppler-env-file"
fi

is_managed_link() {
  local path="$1"
  [ -f "$path" ] || return 1
  grep -q "Managed by Hermes install-cli-wrapper.sh" "$path"
}

write_wrapper() {
  local link_path="$1"
  local link_dir
  local tmp
  link_dir="$(dirname "$link_path")"
  mkdir -p "$link_dir"

  if [ -e "$link_path" ] || [ -L "$link_path" ]; then
    if [ "$force" != true ] && ! is_managed_link "$link_path"; then
      echo "install-cli-wrapper: refusing to overwrite non-managed launcher: $link_path" >&2
      echo "install-cli-wrapper: rerun with --force after verifying the target belongs to Hermes" >&2
      return 2
    fi
  fi

  tmp="$(mktemp "${link_dir}/.hermes-wrapper.XXXXXX")"
  chmod 0755 "$tmp"
  {
    printf '%s\n' '#!/usr/bin/env bash'
    printf '%s\n' '# Managed by Hermes install-cli-wrapper.sh'
    printf '%s\n' 'set -euo pipefail'
    printf 'REAL_HERMES=%q\n' "$hermes_bin"
    printf 'SLACK_DOPPLER_ENV_FILE=%q\n' "$slack_doppler_env_file"
    printf 'DOPPLER_BIN=%q\n' "$doppler_bin"
    printf 'SLACK_DOPPLER_PROJECT=%q\n' "$slack_doppler_project"
    printf 'SLACK_DOPPLER_CONFIG=%q\n' "$slack_doppler_config"
    cat <<'WRAPPER'

unset PYTHONPATH
unset PYTHONHOME

if [[ ! -x "${REAL_HERMES}" ]]; then
  echo "hermes wrapper: real Hermes binary not executable: ${REAL_HERMES}" >&2
  exit 127
fi

target=""
if [[ "${1:-}" == "send" ]]; then
  args=("$@")
  for i in "${!args[@]}"; do
    case "${args[$i]}" in
      --to=*) target="${args[$i]#--to=}" ;;
      -t=*) target="${args[$i]#-t=}" ;;
      --to|-t)
        next=$((i + 1))
        if (( next < ${#args[@]} )); then
          target="${args[$next]}"
        fi
        ;;
    esac
  done
fi

if [[ -n "${SLACK_DOPPLER_ENV_FILE}" && ( "${target}" == "slack" || "${target}" == slack:* ) ]]; then
  if [[ ! -r "${SLACK_DOPPLER_ENV_FILE}" ]]; then
    echo "hermes wrapper: Doppler env file not readable: ${SLACK_DOPPLER_ENV_FILE}" >&2
    exit 1
  fi
  if [[ ! -x "${DOPPLER_BIN}" ]]; then
    echo "hermes wrapper: doppler binary not executable: ${DOPPLER_BIN}" >&2
    exit 1
  fi
  set -a
  # shellcheck source=/dev/null
  . "${SLACK_DOPPLER_ENV_FILE}"
  set +a
  exec "${DOPPLER_BIN}" run --project "${SLACK_DOPPLER_PROJECT}" --config "${SLACK_DOPPLER_CONFIG}" -- "${REAL_HERMES}" "$@"
fi

exec "${REAL_HERMES}" "$@"
WRAPPER
  } > "$tmp"
  mv -f "$tmp" "$link_path"
  chmod 0755 "$link_path"
  echo "installed $link_path -> $hermes_bin"
}

for link in "${links[@]}"; do
  write_wrapper "$link"
done
