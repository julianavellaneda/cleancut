#!/usr/bin/env bash
# Runs once when the devcontainer is created. Installs from the same locks CI
# does, and gives a checkout with no .env one that runs without an API key.
set -euo pipefail

cd "$(dirname "$0")/.."

# Named volumes arrive owned by root; the container runs as vscode. ~/.cache
# itself too, not recursively: mounting the Hugging Face volume creates it as
# root, and pip then silently runs with its cache disabled.
sudo chown -R "$(id -u):$(id -g)" backend/.venv frontend/node_modules "$HOME/.cache/huggingface"
sudo chown "$(id -u):$(id -g)" "$HOME/.cache"

echo "=== Backend: the dev lock, hashes enforced ==="
# The dev lock rather than the runtime one, since this is where people run the
# tests; it includes every runtime dependency.
python3 -m venv backend/.venv
backend/.venv/bin/pip install -q --upgrade pip
(cd backend && .venv/bin/pip install -q --require-hashes -r requirements-dev.txt)

echo "=== Frontend: npm ci ==="
(cd frontend && npm ci)

# Only when there is no .env at all. An existing one - with a real key in it -
# is never touched.
if [ ! -f .env ]; then
    sed -e 's/^CLEANCUT_MODEL=$/CLEANCUT_MODEL=mock:demo/' \
        -e 's/^OPENAI_API_KEY=.*$/OPENAI_API_KEY=/' \
        .env.example > .env
    # If .env.example stops carrying a bare `CLEANCUT_MODEL=` line the
    # substitution above silently does nothing, and the app would boot into a
    # preflight failure for a key nobody was asked for. Say so here instead.
    if ! grep -q '^CLEANCUT_MODEL=mock:demo$' .env; then
        echo "ERROR: could not set CLEANCUT_MODEL=mock:demo in the new .env." >&2
        exit 1
    fi
    echo ""
    echo "Created .env with CLEANCUT_MODEL=mock:demo: suggestions are keyword"
    echo "matches labelled 'Mock:', not a model's analysis. Add a key and change"
    echo "CLEANCUT_MODEL in .env for the real thing."
fi

echo ""
echo "Ready. Start both servers with: make dev"
echo "The first job downloads the Whisper model (~1.5 GB) before it transcribes."
