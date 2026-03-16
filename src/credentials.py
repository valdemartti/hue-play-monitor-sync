"""Secure credential storage using macOS Keychain via keyring."""

import hashlib
import logging

import keyring

logger = logging.getLogger(__name__)

SERVICE_NAME = "com.desktoplights.app"
_APP_KEY_ACCOUNT = "hue-bridge-app-key"
_CERT_FP_PREFIX = "hue-bridge-cert-"


def store_app_key(app_key: str):
    """Store the Hue Bridge app key in the macOS Keychain."""
    keyring.set_password(SERVICE_NAME, _APP_KEY_ACCOUNT, app_key)
    logger.info("App key stored in Keychain")


def load_app_key() -> str:
    """Load the Hue Bridge app key from the macOS Keychain."""
    value = keyring.get_password(SERVICE_NAME, _APP_KEY_ACCOUNT)
    return value or ""


def delete_app_key():
    """Remove the app key from the Keychain."""
    try:
        keyring.delete_password(SERVICE_NAME, _APP_KEY_ACCOUNT)
    except keyring.errors.PasswordDeleteError:
        pass


def store_cert_fingerprint(bridge_ip: str, fingerprint: str):
    """Store a bridge's TLS certificate fingerprint for TOFU pinning."""
    account = f"{_CERT_FP_PREFIX}{bridge_ip}"
    keyring.set_password(SERVICE_NAME, account, fingerprint)
    logger.info("Certificate fingerprint stored for %s", bridge_ip)


def load_cert_fingerprint(bridge_ip: str) -> str:
    """Load the stored certificate fingerprint for a bridge IP."""
    account = f"{_CERT_FP_PREFIX}{bridge_ip}"
    value = keyring.get_password(SERVICE_NAME, account)
    return value or ""


def compute_cert_fingerprint(cert_der: bytes) -> str:
    """Compute SHA-256 fingerprint of a DER-encoded certificate."""
    return hashlib.sha256(cert_der).hexdigest()
