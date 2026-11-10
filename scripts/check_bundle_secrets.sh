#!/usr/bin/env bash
# Intent Gateway — Frontend Secrets Leak Scanner
# Ensures no sensitive administrative, agent, or third-party secret keys
# are bundled into the production frontend build.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DIST_DIR="${ROOT_DIR}/frontend/dist"
SRC_DIR="${ROOT_DIR}/frontend/src"

echo "=== Intent AI Gateway — Frontend Bundle Secrets Audit ==="

if [ ! -d "${DIST_DIR}" ]; then
  echo "ERROR: ${DIST_DIR} does not exist. Please run 'npm run build' inside frontend/ first."
  exit 1
fi

FORBIDDEN_PATTERNS=(
  "admin_super_secret_test_key"
  "demo_agent_secret_test_key"
  "bob_different_agent_key"
  "ADMIN_API_KEY"
  "DEMO_AGENT_KEY"
  "PAYPAL_CLIENT_SECRET"
  "CHANNEL3_API_KEY"
  "intent_admin_key"
)

FOUND_LEAKS=0

echo "Scanning built bundle in ${DIST_DIR}..."

for pattern in "${FORBIDDEN_PATTERNS[@]}"; do
  # Grep recursively in dist/ ignoring binary false positives where appropriate
  MATCHES=$(grep -rn "${pattern}" "${DIST_DIR}" 2>/dev/null || true)
  if [ -n "${MATCHES}" ]; then
    echo "❌ SECURITY LEAK DETECTED: Forbidden secret pattern '${pattern}' found in bundle:"
    echo "${MATCHES}"
    FOUND_LEAKS=$((FOUND_LEAKS + 1))
  fi
done

echo "Scanning source files in ${SRC_DIR} for hardcoded secrets and localStorage key storage..."

# Ensure localStorage is never used to store admin keys
LOCALSTORAGE_LEAKS=$(grep -rn "intent_admin_key" "${SRC_DIR}" 2>/dev/null || true)
if [ -n "${LOCALSTORAGE_LEAKS}" ]; then
  echo "❌ SECURITY LEAK: localStorage access for admin key found in frontend source:"
  echo "${LOCALSTORAGE_LEAKS}"
  FOUND_LEAKS=$((FOUND_LEAKS + 1))
fi

for pattern in "admin_super_secret_test_key" "demo_agent_secret_test_key" "bob_different_agent_key"; do
  SRC_MATCHES=$(grep -rn "${pattern}" "${SRC_DIR}" 2>/dev/null || true)
  if [ -n "${SRC_MATCHES}" ]; then
    echo "❌ SECURITY LEAK DETECTED: Hardcoded test key '${pattern}' found in frontend/src/:"
    echo "${SRC_MATCHES}"
    FOUND_LEAKS=$((FOUND_LEAKS + 1))
  fi
done

if [ "${FOUND_LEAKS}" -gt 0 ]; then
  echo ""
  echo "❌ BUILD FAILED: ${FOUND_LEAKS} secret leak(s) detected. Public frontend bundle must be secret-free."
  exit 1
else
  echo "✅ PASSED: Zero secret keys, localStorage admin keys, or credentials found in built bundle and source."
  exit 0
fi

