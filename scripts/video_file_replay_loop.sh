#!/bin/bash

set -euo pipefail
set -x

required_env() {
    if [[ -z "${!1:-}" ]]; then
        echo "Environment variable ${1} not set"
        exit 1
    fi
}

required_env SOURCE_ID
required_env LOCATION
required_env ZMQ_ENDPOINT
required_env DOWNLOAD_PATH

SYNC_OUTPUT="${SYNC_OUTPUT:-false}"
FPS_OUTPUT="${FPS_OUTPUT:-stdout}"
FPS_PERIOD_FRAMES="${FPS_PERIOD_FRAMES:-1000}"
READ_METADATA="${READ_METADATA:-false}"

handler() {
    if [[ -n "${child_pid:-}" ]]; then
        kill -s SIGINT "${child_pid}" 2>/dev/null || true
        wait "${child_pid}" 2>/dev/null || true
    fi
    exit 0
}
trap handler SIGINT SIGTERM

gst-launch-1.0 --eos-on-shutdown \
    media_files_src_bin location="${LOCATION}" file-type=video loop-file=true download-path="${DOWNLOAD_PATH}" ! \
    fps_meter period-frames="${FPS_PERIOD_FRAMES}" output="${FPS_OUTPUT}" measure-per-loop=false ! \
    adjust_timestamps ! \
    set_dts ! \
    zeromq_sink \
        source-id="${SOURCE_ID}" \
        eos-on-file-end=false \
        eos-on-loop-end=false \
        read-metadata="${READ_METADATA}" \
        socket="${ZMQ_ENDPOINT}" \
        sync="${SYNC_OUTPUT}" &

child_pid="$!"
wait "${child_pid}"