"""LAN HTTPS launcher for phones: `python -m app.phone`.

Phones only allow the microphone over HTTPS, so this generates a
self-signed certificate (reused while its LAN IP still matches), creates
a random access token, and serves the app on 0.0.0.0:8443 with TLS.
The token is only ever shown in the one printed start-up URL and QR
code; it is never logged.
"""
import datetime
import ipaddress
import logging
import os
import secrets
import socket
import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtensionOID, NameOID

from app.store import data_dir as store_data_dir

logger: logging.Logger = logging.getLogger(__name__)
PORT: int = 8443
CERT_FILE_NAME: str = "cert.pem"
KEY_FILE_NAME: str = "key.pem"


def tls_dir() -> Path:
    """Certificate directory: under the shared data dir, outside the repo."""
    override: str = os.environ.get("BLACKOUT_TLS_DIR") or ""
    if override:
        return Path(override)
    return store_data_dir() / "tls"


def get_lan_ip() -> str:
    """Detect the LAN IP with a UDP socket trick that sends no packets.

    A UDP `connect` only records the peer address locally; nothing is
    transmitted. Raises RuntimeError with a clear message when there is
    no usable network.
    """
    sock: Any = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        address: Any = sock.getsockname()
        ip: str = str(address[0]) if address else ""
    except Exception as exc:
        raise RuntimeError("无法检测到局域网 IP：这台设备似乎没有可用的网络连接。请连上 Wi-Fi 或局域网后再试。") from exc
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
    if not ip or ip.startswith("127."):
        raise RuntimeError("无法检测到局域网 IP：这台设备似乎没有可用的网络连接。请连上 Wi-Fi 或局域网后再试。")
    return ip


def generate_token() -> str:
    """Random access token (128 bits of entropy, URL-safe)."""
    return secrets.token_urlsafe(16)


def build_url(ip: str, token: str) -> str:
    """The one start-up URL that is allowed to carry the token."""
    return f"https://{ip}:{PORT}/?token={token}"


def _load_certificate(cert_path: Path) -> Optional[Any]:
    try:
        return x509.load_pem_x509_certificate(cert_path.read_bytes())
    except Exception:
        return None


def _cert_ips(cert: Any) -> List[str]:
    try:
        ext: Any = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
        return [str(value) for value in ext.get_values_for_type(x509.IPAddress)]
    except Exception:
        return []


def certificate_matches_ip(cert_path: Path, ip: str) -> bool:
    """True when the certificate parses, is unexpired, and names `ip`."""
    if not cert_path.is_file():
        return False
    cert: Optional[Any] = _load_certificate(cert_path)
    if cert is None:
        return False
    try:
        now: datetime.datetime = datetime.datetime.now(datetime.timezone.utc)
        not_before: Any = getattr(cert, "not_valid_before_utc", None) or cert.not_valid_before.replace(tzinfo=datetime.timezone.utc)
        not_after: Any = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)
        if not (not_before <= now < not_after):
            return False
    except Exception:
        return False
    try:
        wanted: str = str(ipaddress.ip_address(ip))
    except ValueError:
        return False
    return wanted in _cert_ips(cert)


def _make_certificate(ip: str) -> Tuple[bytes, bytes]:
    """Return (certificate PEM, private key PEM) for `ip`."""
    address: Any = ipaddress.ip_address(ip)
    key: Any = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name: Any = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ip)])
    now: datetime.datetime = datetime.datetime.now(datetime.timezone.utc)
    cert: Any = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(address), x509.DNSName("localhost")]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_pem: bytes = cert.public_bytes(serialization.Encoding.PEM)
    key_pem: bytes = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    return cert_pem, key_pem


def _restrict_permissions(path: Path) -> None:
    """Best-effort 0600 on the private key, where the platform supports it."""
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def ensure_certificate(ip: str, directory: Optional[Path] = None) -> Tuple[Path, Path]:
    """Reuse a valid certificate for `ip`, otherwise regenerate it."""
    folder: Path = Path(directory) if directory is not None else tls_dir()
    folder.mkdir(parents=True, exist_ok=True)
    cert_path: Path = folder / CERT_FILE_NAME
    key_path: Path = folder / KEY_FILE_NAME
    if cert_path.is_file() and key_path.is_file() and certificate_matches_ip(cert_path, ip):
        _restrict_permissions(key_path)
        return cert_path, key_path
    cert_pem, key_pem = _make_certificate(ip)
    fd: int = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(key_pem)
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        raise
    _restrict_permissions(key_path)
    cert_path.write_bytes(cert_pem)
    return cert_path, key_path


def print_qr(url: str) -> bool:
    """Print a terminal QR code when segno is available; otherwise False."""
    try:
        import segno  # type: ignore[import-not-found]
    except Exception:
        return False
    try:
        qr: Any = segno.make(url)
        qr.terminal()
        return True
    except Exception:
        return False


def main(argv: Optional[List[str]] = None) -> None:
    """Detect the LAN IP, prepare TLS + token, print the URL, and serve."""
    logging.basicConfig(level=logging.INFO)
    try:
        ip: str = get_lan_ip()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    cert_path, key_path = ensure_certificate(ip)
    token: str = generate_token()
    os.environ["BLACKOUT_ACCESS_TOKEN"] = token
    allowed: str = os.environ.get("BLACKOUT_ALLOWED_HOSTS", "")
    hosts: List[str] = [item.strip() for item in allowed.replace(";", ",").split(",") if item.strip()]
    if ip not in hosts:
        hosts.append(ip)
    os.environ["BLACKOUT_ALLOWED_HOSTS"] = ",".join(hosts)
    url: str = build_url(ip, token)
    print("Blackout 手机模式已准备好。")
    print("请在手机浏览器打开下面这个地址（手机和电脑要连同一个 Wi-Fi）：")
    print(url)
    if not print_qr(url):
        print("（未安装 segno，无法打印二维码，请直接输入上面的地址。）")
    print("手机会提示这个证书不受信任，这是自签名证书的正常提示，确认继续一次即可，之后不会再问。")
    print("如果手机连不上，请检查电脑防火墙是否放行了 8443 端口。")
    print("按 Ctrl+C 停止。")
    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, ssl_certfile=str(cert_path), ssl_keyfile=str(key_path), access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
