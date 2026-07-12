#!/bin/bash -p
case "$-" in
  *p*) ;;
  *) echo "release smoke requires /bin/bash -p" >&2; exit 1 ;;
esac
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
case "$SCRIPT_PATH" in
  /*) ;;
  *) SCRIPT_PATH="$PWD/$SCRIPT_PATH" ;;
esac
if [[ -L "$SCRIPT_PATH" ]]; then
  echo "release smoke must not be invoked through a symlink" >&2
  exit 1
fi
SCRIPT_DIR="${SCRIPT_PATH%/*}"
SCRIPT_DIR="$(cd -P -- "$SCRIPT_DIR" && pwd)"
# shellcheck source=trusted_gate_helpers.sh
source "$SCRIPT_DIR/trusted_gate_helpers.sh"

ROOT="${1:-.}"
cd "$ROOT"

"$TRUSTED_PYTHON" -E -s -S scripts/validate_package.py --git-executable "$TRUSTED_GIT" .

TMP_ROOT="$("$TRUSTED_MKTEMP" -d "/tmp/agency-release-smoke.XXXXXX")"
cleanup_tmp_root() {
  "$TRUSTED_RM" -rf -- "$TMP_ROOT"
}
trap cleanup_tmp_root EXIT

"$TRUSTED_PYTHON" -E -s -S scripts/install_skill.py --target-root "$TMP_ROOT/skills" --json >"$TMP_ROOT/install.json"
"$TRUSTED_PYTHON" -E -s -S scripts/install_skill.py --target-root "$TMP_ROOT/skills" --dry-run --json >"$TMP_ROOT/dry-run.json"

"$TRUSTED_PYTHON" -E -s -S - "$TMP_ROOT/install.json" "$TMP_ROOT/dry-run.json" <<'PY'
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

install = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
dry_run = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if install["status"] != "installed":
    raise SystemExit(f"unexpected install status: {install['status']}")
if dry_run["status"] != "already-installed":
    raise SystemExit(f"unexpected dry-run status: {dry_run['status']}")
for label, receipt in (("install", install), ("dry-run", dry_run)):
    if receipt.get("cleanup_complete") is not True:
        raise SystemExit(f"{label} did not prove cleanup_complete=true")
    if receipt.get("residual_paths") != []:
        raise SystemExit(f"{label} reported installer transaction residuals")
    if receipt.get("cleanup_guidance") != []:
        raise SystemExit(f"{label} reported unresolved cleanup guidance")
    if receipt.get("cleanup_warnings") != []:
        raise SystemExit(f"{label} reported cleanup warnings")
    if receipt.get("tree_integrity_policy") != "sealed-tree-v1":
        raise SystemExit(f"{label} did not bind sealed-tree-v1")
    if receipt.get("tree_integrity_verified") is not True:
        raise SystemExit(f"{label} did not verify the sealed installed tree")
for key in ("agents_md_written", "agents_md_dependency", "agents_md_touched"):
    if install.get(key) is not False:
        raise SystemExit(f"installer did not prove {key}=false")
if set(install["targets"]) != {install["canonical_name"], install["legacy_name"]}:
    raise SystemExit("installer did not report the canonical and legacy pair")
if install["manifests"] != dry_run["manifests"]:
    raise SystemExit("runtime manifests drifted after install")
canonical_manifest_json = json.dumps(
    install["manifests"],
    ensure_ascii=True,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
expected_revision = hashlib.sha256(canonical_manifest_json).hexdigest()
for label, receipt in (("install", install), ("dry-run", dry_run)):
    if receipt.get("package_source_revision_sha256") != expected_revision:
        raise SystemExit(f"{label} package source revision does not bind both manifests")
def metadata_signature(metadata):
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def read_regular_hash(path, expected_metadata):
    flags = os.O_RDONLY | os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SystemExit("installed runtime node changed type while hashing")
        if metadata_signature(metadata) != metadata_signature(expected_metadata):
            raise SystemExit("installed runtime node rebound while hashing")
        hasher = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            hasher.update(chunk)
        if metadata_signature(os.fstat(descriptor)) != metadata_signature(metadata):
            raise SystemExit("installed runtime node changed while hashing")
        return hasher.hexdigest()
    finally:
        os.close(descriptor)


def sealed_scan(target, expected):
    expected_dirs = set()
    for relative_text in expected:
        for parent in Path(relative_text).parents:
            if parent == Path("."):
                break
            expected_dirs.add(parent.as_posix())
    records = {}

    def scan(directory, prefix):
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            relative = prefix / entry.name
            relative_text = relative.as_posix()
            metadata = entry.stat(follow_symlinks=False)
            records[relative_text] = metadata
            if stat.S_ISDIR(metadata.st_mode):
                scan(Path(entry.path), relative)

    root_metadata = os.lstat(target)
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise SystemExit("installed bundle root is not a real directory")
    if stat.S_IMODE(root_metadata.st_mode) != 0o700:
        raise SystemExit("installed bundle root mode drifted")
    if root_metadata.st_uid != os.geteuid():
        raise SystemExit("installed bundle root owner drifted")
    scan(target, Path())
    if set(records) != expected_dirs | set(expected):
        raise SystemExit("installed bundle path set is not sealed")
    actual = {}
    for relative_text, metadata in records.items():
        if metadata.st_uid != os.geteuid():
            raise SystemExit("installed bundle node owner drifted")
        if relative_text in expected_dirs:
            if not stat.S_ISDIR(metadata.st_mode):
                raise SystemExit("installed bundle directory changed type")
            if stat.S_IMODE(metadata.st_mode) != 0o755:
                raise SystemExit("installed bundle directory mode drifted")
            continue
        expected_mode = 0o755 if relative_text == "scripts/audit_historical_threads.py" else 0o644
        if not stat.S_ISREG(metadata.st_mode):
            raise SystemExit("installed runtime node is not a regular file")
        if stat.S_IMODE(metadata.st_mode) != expected_mode:
            raise SystemExit("installed runtime file mode drifted")
        if metadata.st_nlink != 1:
            raise SystemExit("installed runtime file is hard-linked")
        actual[relative_text] = read_regular_hash(
            target / relative_text, metadata
        )
    return actual


for name, target_text in install["targets"].items():
    target = Path(target_text)
    expected = install["manifests"][name]
    actual = sealed_scan(target, expected)
    if actual != expected:
        raise SystemExit(f"installed manifest mismatch for {name}")
    if any(path.name in {"AGENTS.md", "AGENTS.override.md"} for path in target.rglob("*")):
        raise SystemExit(f"unexpected AGENTS guidance in {name}")
PY

echo "Release smoke passed: two manifest-matched bundles installed without AGENTS guidance; model behavior not claimed."
