"""Self-signed certificate for the family page.

Browsers show a one-time 'not private' warning (Advanced -> Proceed) because
no public authority vouches for a home LAN box — but traffic is encrypted and
Chrome's forced HTTPS upgrade stops breaking the links.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..credentials import SERVICE_ROOT


def lan_addresses() -> list[str]:
    import socket

    addrs = {"127.0.0.1"}
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True)
        addrs.update(a for a in out.stdout.split() if "." in a)
    except Exception:
        pass
    names = {"localhost", socket.gethostname()}
    return sorted(addrs), sorted(names)


def ensure_self_signed_cert() -> tuple[Path, Path]:
    """Create (once) and return (certfile, keyfile) with SANs for every LAN
    address so the same cert works via IP or hostname."""
    cert_dir = SERVICE_ROOT / "var" / "certs"
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert, key = cert_dir / "pantryos.crt", cert_dir / "pantryos.key"
    if cert.exists() and key.exists():
        return cert, key
    ips, names = lan_addresses()
    san = ",".join([*(f"IP:{i}" for i in ips), *(f"DNS:{n}" for n in names)])
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert),
            "-days", "3650", "-subj", "/CN=PantryOS",
            "-addext", f"subjectAltName={san}",
        ],
        check=True, capture_output=True,
    )
    key.chmod(0o600)
    return cert, key
