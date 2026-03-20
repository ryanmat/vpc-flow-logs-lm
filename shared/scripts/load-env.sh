# Description: Loads environment variables from the project .env file.
# Description: Sources .env if it exists, otherwise prints a warning.

_LOAD_ENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_LOAD_ENV_ROOT="$(cd "$_LOAD_ENV_DIR/../.." && pwd)"

ENV_FILE="$_LOAD_ENV_ROOT/.env"

if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "[WARN] No .env file found at $ENV_FILE"
    echo "[WARN] Copy .env.example to .env and fill in your credentials."
fi
