"""Phone mode tests: certificates, tokens, LAN IP detection. No real network."""
import ipaddress
import os
import stat
from pathlib import Path
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest
from cryptography import x509
from cryptography.x509.oid import ExtensionOID, NameOID

import app.phone as phone


def _cert_ips(cert_path: Path) -> List[str]:
    cert: Any = x509.load_pem_x509_certificate(cert_path.read_bytes())
    ext: Any = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    return [str(value) for value in ext.get_values_for_type(x509.IPAddress)]


def test_certificate_has_ip_in_san_and_parses(tmp_path: Path) -> None:
    cert_path, key_path = phone.ensure_certificate("192.168.1.23", tmp_path)
    assert cert_path.is_file() and key_path.is_file()
    cert: Any = x509.load_pem_x509_certificate(cert_path.read_bytes())
    assert cert.subject.rfc4514_string()
    assert _cert_ips(cert_path) == ["192.168.1.23"]
    assert ipaddress.ip_address("192.168.1.23") in [
        ipaddress.ip_address(value) for value in _cert_ips(cert_path)
    ]
    assert phone.certificate_matches_ip(cert_path, "192.168.1.23") is True
    assert phone.certificate_matches_ip(cert_path, "192.168.1.24") is False


def test_existing_valid_certificate_is_reused(tmp_path: Path) -> None:
    cert_path, key_path = phone.ensure_certificate("10.0.0.5", tmp_path)
    cert_bytes: bytes = cert_path.read_bytes()
    key_bytes: bytes = key_path.read_bytes()
    again_cert, again_key = phone.ensure_certificate("10.0.0.5", tmp_path)
    assert again_cert == cert_path and again_key == key_path
    assert again_cert.read_bytes() == cert_bytes
    assert again_key.read_bytes() == key_bytes


def test_regenerated_certificate_replaces_mismatched_one(tmp_path: Path) -> None:
    cert_path, _key_path = phone.ensure_certificate("192.168.1.10", tmp_path)
    old_bytes: bytes = cert_path.read_bytes()
    assert _cert_ips(cert_path) == ["192.168.1.10"]
    new_cert, _new_key = phone.ensure_certificate("192.168.1.11", tmp_path)
    assert new_cert == cert_path
    assert new_cert.read_bytes() != old_bytes
    assert _cert_ips(new_cert) == ["192.168.1.11"]
    assert phone.certificate_matches_ip(new_cert, "192.168.1.10") is False
    assert phone.certificate_matches_ip(new_cert, "192.168.1.11") is True


def test_garbage_certificate_is_regenerated(tmp_path: Path) -> None:
    cert_path, key_path = phone.ensure_certificate("172.16.0.9", tmp_path)
    cert_path.write_bytes(b"not a certificate")
    fixed_cert, _fixed_key = phone.ensure_certificate("172.16.0.9", tmp_path)
    assert _cert_ips(fixed_cert) == ["172.16.0.9"]
    assert key_path.is_file()


def test_private_key_has_restrictive_permissions(tmp_path: Path) -> None:
    _cert_path, key_path = phone.ensure_certificate("192.168.1.30", tmp_path)
    if os.name == "nt":
        pytest.skip("POSIX permission bits are not applicable on Windows")
    mode: int = stat.S_IMODE(key_path.stat().st_mode)
    assert mode & 0o077 == 0


def test_token_has_sufficient_length_and_is_random() -> None:
    token: str = phone.generate_token()
    assert len(token) >= 20
    assert phone.generate_token() != token
    url: str = phone.build_url("192.168.1.2", token)
    assert url == f"https://192.168.1.2:8443/?token={token}"


class _FakeSocket:
    """UDP socket stand-in: records calls, sends nothing."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.connected: Any = None
        self.sent: List[Any] = []

    def connect(self, address: Any) -> None:
        self.connected = address

    def getsockname(self) -> Any:
        return ("192.168.1.77", 54321)

    def send(self, data: Any) -> None:  # pragma: no cover - must never run
        self.sent.append(data)
        raise AssertionError("get_lan_ip must not send packets")

    def sendto(self, data: Any, address: Any) -> None:  # pragma: no cover
        self.sent.append((data, address))
        raise AssertionError("get_lan_ip must not send packets")

    def close(self) -> None:
        return None


def test_get_lan_ip_uses_mocked_socket_without_sending() -> None:
    fake: _FakeSocket = _FakeSocket()
    with patch.object(phone.socket, "socket", return_value=fake) as factory:
        ip: str = phone.get_lan_ip()
    assert factory.called
    assert ip == "192.168.1.77"
    assert fake.connected == ("8.8.8.8", 80)
    assert fake.sent == []


def test_get_lan_ip_clear_error_without_network() -> None:
    broken: MagicMock = MagicMock()
    broken.connect.side_effect = OSError("network unreachable")
    with patch.object(phone.socket, "socket", return_value=broken):
        with pytest.raises(RuntimeError) as excinfo:
            phone.get_lan_ip()
    assert "局域网" in str(excinfo.value)


def test_print_qr_without_segno_prints_nothing_and_returns_false() -> None:
    import builtins

    real_import: Any = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "segno":
            raise ImportError("no segno")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", side_effect=fake_import):
        assert phone.print_qr("https://192.168.1.2:8443/?token=x") is False


def test_tls_dir_uses_store_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import store as store_mod

    monkeypatch.delenv("BLACKOUT_TLS_DIR", raising=False)
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path / "data"))
    assert phone.tls_dir() == store_mod.data_dir() / "tls"
    assert phone.tls_dir().parent == store_mod.data_dir()
    monkeypatch.setenv("BLACKOUT_TLS_DIR", str(tmp_path / "custom-tls"))
    assert phone.tls_dir() == Path(str(tmp_path / "custom-tls"))


def test_main_never_logs_the_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BLACKOUT_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("BLACKOUT_ALLOWED_HOSTS", raising=False)
    served: dict = {}

    def fake_run(target: Any, **kwargs: Any) -> None:
        served["target"] = target
        served.update(kwargs)

    fake_uvicorn: MagicMock = MagicMock()
    fake_uvicorn.run.side_effect = fake_run
    with patch.dict(os.environ):
        with patch.object(phone, "get_lan_ip", return_value="192.168.1.40"):
            with patch.dict("sys.modules", {"uvicorn": fake_uvicorn}):
                with patch.object(phone, "uvicorn", fake_uvicorn):
                    phone.main([])
        out: str = capsys.readouterr().out
        token: str = os.environ.get("BLACKOUT_ACCESS_TOKEN", "")
        assert len(token) >= 20
        assert token in out
        assert f"https://192.168.1.40:8443/?token={token}" in out
        assert "8443" in out
        assert token not in caplog.text
        assert served["host"] == "0.0.0.0" and served["port"] == 8443
        assert served["ssl_certfile"] and served["ssl_keyfile"]
        assert served["access_log"] is False
        assert "192.168.1.40" in os.environ.get("BLACKOUT_ALLOWED_HOSTS", "")


# --- Server invocation, certificate shape, token hygiene ------------------

def test_uvicorn_run_uses_access_log_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path / "data"))
    served: dict = {}
    fake_uvicorn: MagicMock = MagicMock()
    fake_uvicorn.run.side_effect = lambda target, **kwargs: served.update({"target": target, **kwargs})
    saved: dict = {name: os.environ.get(name) for name in ("BLACKOUT_ACCESS_TOKEN", "BLACKOUT_ALLOWED_HOSTS")}
    try:
        with patch.object(phone, "get_lan_ip", return_value="192.168.1.50"):
            with patch.object(phone, "uvicorn", fake_uvicorn):
                phone.main([])
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    assert served["target"] == "app.main:app"
    assert served["host"] == "0.0.0.0"
    assert served["port"] == 8443
    assert served["access_log"] is False
    assert served["ssl_certfile"]
    assert served["ssl_keyfile"]


def test_certificate_is_not_a_ca(tmp_path: Path) -> None:
    cert_path, _key_path = phone.ensure_certificate("192.168.1.60", tmp_path)
    cert: Any = x509.load_pem_x509_certificate(cert_path.read_bytes())
    ext: Any = cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value
    assert ext.ca is False
    assert ext.path_length is None
    # It is a leaf host certificate, self-issued for the LAN address.
    assert cert.issuer == cert.subject
    names: List[str] = [str(value) for value in cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value.get_values_for_type(x509.DNSName)]
    assert "localhost" in names
    assert cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)


def test_main_prints_token_only_inside_start_url_and_env_restored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path / "data"))
    fake_uvicorn: MagicMock = MagicMock()
    fake_uvicorn.run.side_effect = lambda target, **kwargs: None
    watched: tuple = ("BLACKOUT_ACCESS_TOKEN", "BLACKOUT_ALLOWED_HOSTS")
    saved: dict = {name: os.environ.get(name) for name in watched}
    try:
        with patch.object(phone, "get_lan_ip", return_value="192.168.1.70"):
            with patch.object(phone, "uvicorn", fake_uvicorn):
                phone.main([])
        out: str = capsys.readouterr().out
        token: str = str(os.environ.get("BLACKOUT_ACCESS_TOKEN", ""))
        assert len(token) >= 20
        token_lines: List[str] = [line for line in out.splitlines() if token in line]
        # The one place the token may appear in printed output is the
        # single start-up URL the user is meant to open on the phone.
        assert token_lines == [f"https://192.168.1.70:8443/?token={token}"]
        assert token not in caplog.text
    finally:
        # `main` sets process-wide variables for the server it launches;
        # the test restores the previous environment afterwards so no
        # token leaks into other tests.
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    for name, value in saved.items():
        assert os.environ.get(name) == value
