#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

HOOKS_DIR="$(git rev-parse --git-common-dir)/hooks"
mkdir -p "$HOOKS_DIR"

cat > "$HOOKS_DIR/pre-commit" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "Running devbox run fmt:check..."
devbox run fmt:check
EOF

chmod +x "$HOOKS_DIR/pre-commit"
echo "Installed pre-commit hook at $HOOKS_DIR/pre-commit"
