from __future__ import annotations

"""Managed SSH credentials for Arii.

Passwords are accepted only as function arguments during onboarding.  The
generated Ed25519 private key is encrypted; its random passphrase is stored in
the operating-system credential store through ``keyring``.
"""

from dataclasses import dataclass
import base64
import hashlib
import os
from pathlib import Path
import secrets
import shlex
from typing import Callable

from arii.execution import ClusterProfile


KEYRING_SERVICE = "Arii managed SSH keys"


@dataclass(frozen=True)
class UnknownHostKey(Exception):
    lookup_name: str
    algorithm: str
    fingerprint: str
    key_base64: str

    def __str__(self) -> str:
        return f"Servidor SSH desconocido: {self.lookup_name} ({self.fingerprint})"


def _imports():
    try:
        import keyring
        import paramiko
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as exc:
        raise RuntimeError(
            "El acceso SSH administrado requiere paramiko, cryptography y keyring. "
            "Reinstale las dependencias de Arii."
        ) from exc
    return keyring, paramiko, serialization, Ed25519PrivateKey


def _data_directory() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"])
    else:
        root = Path.home() / ".local" / "share"
    destination = root / "Arii" / "ssh"
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def _credential_id(profile: ClusterProfile) -> str:
    identity = f"{profile.profile_id}|{profile.username}|{profile.host}|{profile.port}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def managed_key_path(profile: ClusterProfile) -> Path:
    return _data_directory() / f"id_ed25519_{_credential_id(profile)}"


def known_hosts_path() -> Path:
    return _data_directory() / "known_hosts"


def _fingerprint(key) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def _keyring_account(profile: ClusterProfile) -> str:
    return _credential_id(profile)


class _CaptureMissingHostKey:
    def missing_host_key(self, client, hostname, key) -> None:
        raise UnknownHostKey(
            lookup_name=hostname,
            algorithm=key.get_name(),
            fingerprint=_fingerprint(key),
            key_base64=key.get_base64(),
        )


def _new_client(profile: ClusterProfile, *, capture_unknown: bool):
    _, paramiko, _, _ = _imports()
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    hosts = known_hosts_path()
    if hosts.is_file():
        client.load_host_keys(str(hosts))
    client.set_missing_host_key_policy(
        _CaptureMissingHostKey() if capture_unknown else paramiko.RejectPolicy()
    )
    return client


def _connect_password(profile: ClusterProfile, password: str, *, capture_unknown: bool):
    client = _new_client(profile, capture_unknown=capture_unknown)
    client.connect(
        hostname=profile.host,
        port=profile.port,
        username=profile.username,
        password=password,
        look_for_keys=False,
        allow_agent=False,
        timeout=15,
        banner_timeout=15,
        auth_timeout=20,
    )
    return client


def _trust_host_key(unknown: UnknownHostKey) -> None:
    _, paramiko, _, _ = _imports()
    hosts_path = known_hosts_path()
    hosts = paramiko.HostKeys()
    if hosts_path.is_file():
        hosts.load(str(hosts_path))
    key = paramiko.PKey.from_type_string(
        unknown.algorithm, base64.b64decode(unknown.key_base64)
    )
    hosts.add(unknown.lookup_name, unknown.algorithm, key)
    hosts.save(str(hosts_path))


def _write_managed_key(profile: ClusterProfile) -> tuple[Path, str]:
    keyring, _, serialization, Ed25519PrivateKey = _imports()
    destination = managed_key_path(profile)
    account = _keyring_account(profile)
    passphrase = keyring.get_password(KEYRING_SERVICE, account)
    if destination.is_file() and passphrase:
        private = serialization.load_ssh_private_key(
            destination.read_bytes(), password=passphrase.encode("utf-8")
        )
    else:
        private = Ed25519PrivateKey.generate()
        passphrase = secrets.token_urlsafe(36)
        keyring.set_password(KEYRING_SERVICE, account, passphrase)
        encoded = private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.BestAvailableEncryption(
                passphrase.encode("utf-8")
            ),
        )
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(encoded)
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(destination)
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode("ascii")
    return destination, f"{public} arii-{profile.profile_id}"


def connect_managed(profile: ClusterProfile):
    keyring, paramiko, _, _ = _imports()
    passphrase = keyring.get_password(KEYRING_SERVICE, _keyring_account(profile))
    key_path = managed_key_path(profile)
    if not key_path.is_file() or not passphrase:
        raise RuntimeError(
            "El perfil no tiene una clave Arii utilizable. Configure el acceso "
            "automático nuevamente."
        )
    private_key = paramiko.Ed25519Key.from_private_key_file(
        str(key_path), password=passphrase
    )
    client = _new_client(profile, capture_unknown=False)
    client.connect(
        hostname=profile.host,
        port=profile.port,
        username=profile.username,
        pkey=private_key,
        look_for_keys=False,
        allow_agent=False,
        timeout=15,
        banner_timeout=15,
        auth_timeout=20,
    )
    return client


def provision_managed_key(
    profile: ClusterProfile,
    password: str,
    confirm_host_key: Callable[[str, str, str], bool],
) -> Path:
    """Authenticate once with a password and install an Arii Ed25519 key."""

    try:
        client = _connect_password(profile, password, capture_unknown=True)
    except UnknownHostKey as unknown:
        if not confirm_host_key(
            unknown.lookup_name, unknown.algorithm, unknown.fingerprint
        ):
            raise RuntimeError("La huella del servidor no fue aceptada")
        _trust_host_key(unknown)
        client = _connect_password(profile, password, capture_unknown=False)

    key_path, public_key = _write_managed_key(profile)
    quoted_key = shlex.quote(public_key)
    command = (
        "umask 077; mkdir -p \"$HOME/.ssh\"; "
        "touch \"$HOME/.ssh/authorized_keys\"; "
        f"grep -qxF -- {quoted_key} \"$HOME/.ssh/authorized_keys\" || "
        f"printf '%s\\n' {quoted_key} >> \"$HOME/.ssh/authorized_keys\"; "
        "chmod 700 \"$HOME/.ssh\"; chmod 600 \"$HOME/.ssh/authorized_keys\""
    )
    try:
        _, stdout, stderr = client.exec_command(command, timeout=30)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code:
            detail = stderr.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(detail or "No se pudo instalar la clave pública")
    finally:
        client.close()

    verification = connect_managed(profile)
    verification.close()
    return key_path
