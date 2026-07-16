#!/usr/bin/env bash
# Bootstrap wrapper for coursectl (macOS / Linux).
#
# Thin by design (course spec sections 5.4 and 12): its only job is to
# download the correct prebuilt coursectl binary from the latest GitHub
# Release, verify its checksum, and place it in ./bin/. All real course
# operations live in coursectl itself. Windows users: run
# scripts/bootstrap.ps1 instead; both wrappers behave identically.
set -euo pipefail

REPO="ai-eng-bootcamps/ai-native-sweng"
API="https://api.github.com/repos/${REPO}/releases/latest"
INSTALL_DIR="./bin"

fail() {
  echo "bootstrap: $*" >&2
  exit 1
}

command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v tar >/dev/null 2>&1 || fail "tar is required"

# Detect operating system.
case "$(uname -s)" in
  Darwin) os="darwin" ;;
  Linux)  os="linux" ;;
  *) fail "unsupported operating system '$(uname -s)'; on Windows run scripts/bootstrap.ps1" ;;
esac

# Detect architecture.
case "$(uname -m)" in
  x86_64|amd64)  arch="amd64" ;;
  arm64|aarch64) arch="arm64" ;;
  *) fail "unsupported architecture '$(uname -m)'" ;;
esac

echo "Looking up the latest coursectl release for ${os}/${arch}..."
release_json="$(curl -fsSL "$API")" \
  || fail "no release found at https://github.com/${REPO}/releases - coursectl has not been published yet"

# "|| true" keeps set -e/pipefail from killing the script on a non-matching
# grep, so the explicit [ -n ... ] checks below report the real problem.
tag="$(printf '%s' "$release_json" | grep -m1 '"tag_name"' | sed -E 's/.*"tag_name":[[:space:]]*"([^"]+)".*/\1/' || true)"
[ -n "$tag" ] || fail "could not read tag_name from the GitHub API response"
case "$tag" in
  coursectl/v*) ;;
  *) fail "latest release '${tag}' is not a coursectl release - coursectl has not been published yet" ;;
esac

version="${tag#coursectl/}"
archive="coursectl_${version}_${os}_${arch}.tar.gz"

# Take download URLs from the release's asset list to avoid encoding the
# slash in the tag name by hand.
asset_urls="$(printf '%s' "$release_json" | grep -oE '"browser_download_url":[[:space:]]*"[^"]+"' | grep -oE 'https://[^"]+' || true)"
archive_url="$(printf '%s\n' "$asset_urls" | grep "/${archive}\$" | head -n1 || true)"
sums_url="$(printf '%s\n' "$asset_urls" | grep "/SHA256SUMS\$" | head -n1 || true)"
[ -n "$archive_url" ] || fail "release ${tag} has no asset named ${archive}"
[ -n "$sums_url" ] || fail "release ${tag} has no SHA256SUMS asset"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "Downloading ${archive}..."
curl -fsSL -o "${tmp}/${archive}" "$archive_url" || fail "downloading ${archive} failed"
curl -fsSL -o "${tmp}/SHA256SUMS" "$sums_url" || fail "downloading SHA256SUMS failed"

echo "Verifying SHA256 checksum..."
expected="$(grep " ${archive}\$" "${tmp}/SHA256SUMS" | head -n1 | awk '{print $1}' || true)"
[ -n "$expected" ] || fail "${archive} is not listed in SHA256SUMS"
if command -v sha256sum >/dev/null 2>&1; then
  actual="$(sha256sum "${tmp}/${archive}" | awk '{print $1}')"
else
  actual="$(shasum -a 256 "${tmp}/${archive}" | awk '{print $1}')"
fi
[ "$actual" = "$expected" ] || fail "checksum mismatch for ${archive}: expected ${expected}, got ${actual}"

mkdir -p "$INSTALL_DIR"
tar -xzf "${tmp}/${archive}" -C "$INSTALL_DIR"
chmod +x "${INSTALL_DIR}/coursectl"

echo "coursectl ${version} installed to ${INSTALL_DIR}/coursectl"
echo ""
echo "Next steps:"
echo "  1. ${INSTALL_DIR}/coursectl setup"
echo "  2. ${INSTALL_DIR}/coursectl status"
echo "Optionally add ${INSTALL_DIR} to your PATH."
