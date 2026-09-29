"""python -m client_sdk.keygen --directory runtime/my-client (never overwrites keys)."""
import argparse
import os
import subprocess
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        identity = subprocess.check_output(["whoami"], text=True).strip()
        subprocess.run(["icacls", str(directory), "/inheritance:r", "/grant:r", f"{identity}:(OI)(CI)F"], check=True, capture_output=True)
    else:
        directory.chmod(0o700)
    key = ec.generate_private_key(ec.SECP256R1())
    private, public = directory / "private.pem", directory / "public.pem"
    if private.exists() or public.exists():
        raise SystemExit("Key files already exist; choose a new directory for rotation")
    fd = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with public.open("xb") as stream:
        stream.write(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    print(f"Generated keys in {directory}. Register public.pem only; keep private.pem local.")


if __name__ == "__main__":
    main()
