#!/usr/bin/env bash
# Used when an outer isaac_gpu_lock.sh already holds the lock.
exec "$@"
