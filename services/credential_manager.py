import base64
import json
import os
from getpass import getpass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


PROVIDER_KEYS = {
    "gemini":      ["GEMINI_API_KEY",      "AMADEUS_API_KEY", "AMADEUS_API_SECRET"],
    "anthropic":   ["ANTHROPIC_API_KEY",   "AMADEUS_API_KEY", "AMADEUS_API_SECRET"],
    "openrouter":  ["OPENROUTER_API_KEY",  "AMADEUS_API_KEY", "AMADEUS_API_SECRET"],
}


class CredentialManager:
    CONFIG_DIR = Path.home() / ".travel-agent"
    CREDS_FILE = CONFIG_DIR / "credentials.enc"
    SALT_FILE = CONFIG_DIR / ".salt"
    PBKDF2_ITERATIONS = 480_000

    def __init__(self, provider: str = "gemini"):
        self.CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._credentials: dict[str, str] = {}
        self._is_unlocked = False
        self.provider = provider

    @property
    def REQUIRED_KEYS(self) -> list[str]:
        return PROVIDER_KEYS.get(self.provider, PROVIDER_KEYS["gemini"])

    def _derive_key(self, password: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self.PBKDF2_ITERATIONS,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))

    def _get_or_create_salt(self) -> bytes:
        if self.SALT_FILE.exists():
            return self.SALT_FILE.read_bytes()
        salt = os.urandom(16)
        self.SALT_FILE.write_bytes(salt)
        self.SALT_FILE.chmod(0o600)
        return salt

    def is_configured(self) -> bool:
        return self.CREDS_FILE.exists() and self.CREDS_FILE.stat().st_size > 0

    def setup(self, master_password: str) -> None:
        """First-time setup: collect API keys interactively, encrypt, and persist."""
        creds: dict[str, str] = {}
        for key in self.REQUIRED_KEYS:
            value = getpass(f"  Enter {key}: ").strip()
            if not value:
                raise ValueError(f"{key} cannot be empty.")
            creds[key] = value

        salt = self._get_or_create_salt()
        fernet_key = self._derive_key(master_password, salt)
        f = Fernet(fernet_key)
        encrypted = f.encrypt(json.dumps(creds).encode("utf-8"))
        self.CREDS_FILE.write_bytes(encrypted)
        self.CREDS_FILE.chmod(0o600)
        self._credentials = creds
        self._is_unlocked = True

    def unlock(self, master_password: str) -> None:
        """Decrypt credential store into memory. Raises ValueError on wrong password."""
        if not self.is_configured():
            raise RuntimeError("Credentials not configured. Run first-time setup.")
        salt = self._get_or_create_salt()
        fernet_key = self._derive_key(master_password, salt)
        f = Fernet(fernet_key)
        try:
            decrypted = f.decrypt(self.CREDS_FILE.read_bytes())
        except InvalidToken:
            raise ValueError("Incorrect master password.")
        self._credentials = json.loads(decrypted.decode("utf-8"))
        self._is_unlocked = True

    def get_credential(self, name: str) -> str:
        if not self._is_unlocked:
            raise RuntimeError("Credential store is locked. Call unlock() first.")
        if name not in self._credentials:
            raise KeyError(f"Credential '{name}' not found.")
        return self._credentials[name]

    def set_credential(self, name: str, value: str, master_password: str) -> None:
        """Update a single credential and re-encrypt the store."""
        if not self._is_unlocked:
            raise RuntimeError("Credential store is locked. Call unlock() first.")
        self._credentials[name] = value
        salt = self._get_or_create_salt()
        fernet_key = self._derive_key(master_password, salt)
        f = Fernet(fernet_key)
        encrypted = f.encrypt(json.dumps(self._credentials).encode("utf-8"))
        self.CREDS_FILE.write_bytes(encrypted)
