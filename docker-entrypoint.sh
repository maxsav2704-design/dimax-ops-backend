#!/bin/sh
set -eu

if [ "${APP_ENV:-development}" = "production" ]; then
    python /app/scripts/validate_production_env.py --runtime
fi

exec "$@"
