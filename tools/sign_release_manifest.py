#!/usr/bin/env python3
"""Ed25519 detached signing wrapper; private keys must be supplied out of band."""
import argparse
import hashlib
import subprocess
from pathlib import Path


def public_key_fingerprint(public_key):
    der = subprocess.check_output(["openssl", "pkey", "-pubin", "-in", str(public_key), "-outform", "DER"])
    return hashlib.sha256(der).hexdigest()


def require_openssl3():
    version = subprocess.check_output(["openssl", "version"], text=True).strip()
    if not version.startswith("OpenSSL 3."):
        raise SystemExit("OpenSSL 3.x is required for Ed25519 signing; detected: %s" % version)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--public-key", required=True)
    parser.add_argument("--signature", required=True)
    args = parser.parse_args()
    require_openssl3()
    manifest, private_key, public_key, signature = map(Path, (args.manifest, args.private_key, args.public_key, args.signature))
    if not all(path.is_file() for path in (manifest, private_key, public_key)):
        raise SystemExit("Manifest and externally managed Ed25519 key files must exist")
    subprocess.check_call(["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(private_key),
                           "-in", str(manifest), "-out", str(signature)])
    print("SIGNATURE=%s" % signature)
    print("PUBLIC_KEY_SHA256=%s" % public_key_fingerprint(public_key))
    print("NOTE=Fingerprint must be independently approved and pinned as a release trust anchor")


if __name__ == "__main__":
    main()
