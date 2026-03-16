"""Philips Hue Bridge v2 API client for gradient lightstrip control."""

import asyncio
import hashlib
import ipaddress
import logging
import re
import ssl
from dataclasses import dataclass

import aiohttp

from .credentials import (
    compute_cert_fingerprint,
    load_cert_fingerprint,
    store_cert_fingerprint,
)

logger = logging.getLogger(__name__)

# Default timeout for API calls
_API_TIMEOUT = aiohttp.ClientTimeout(total=5, connect=3)
# Max response size (1 MB — bridge responses are small)
_MAX_RESPONSE_SIZE = 1024 * 1024
# Max allowed gradient zones
_MAX_ZONE_COUNT = 20
# Max light name length
_MAX_NAME_LENGTH = 64
# UUID-like pattern for light IDs
_LIGHT_ID_PATTERN = re.compile(r"^[a-f0-9\-]{1,64}$")


def validate_bridge_ip(ip: str) -> str:
    """Validate that a bridge IP is a private/local address.

    Raises ValueError if the IP is not private.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        raise ValueError(f"Invalid IP address: {ip}")

    if not (addr.is_private or addr.is_loopback or addr.is_link_local):
        raise ValueError(
            f"Bridge IP {ip} is not a private address. "
            "Hue Bridges should only be on your local network."
        )
    return ip


def _make_ssl_context() -> ssl.SSLContext:
    """Create an SSL context that accepts self-signed certs but captures them.

    The Hue Bridge uses a self-signed certificate, so we can't do standard
    CA verification. Instead we use trust-on-first-use (TOFU) — the cert
    fingerprint is stored on first connection and verified on subsequent ones.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def _get_bridge_cert_fingerprint(ip: str) -> str:
    """Connect to the bridge and return the SHA-256 fingerprint of its TLS cert."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, 443, ssl=ctx),
            timeout=5,
        )
        ssl_obj = writer.get_extra_info("ssl_object")
        cert_der = ssl_obj.getpeercert(binary_form=True)
        writer.close()
        await writer.wait_closed()
        if cert_der:
            return compute_cert_fingerprint(cert_der)
    except Exception as e:
        logger.warning("Could not get bridge certificate: %s", e)
    return ""


def _sanitize_name(name: str) -> str:
    """Sanitize a light name from bridge response."""
    if not isinstance(name, str):
        return "Unknown"
    # Truncate and strip control characters
    cleaned = "".join(c for c in name[:_MAX_NAME_LENGTH] if c.isprintable())
    return cleaned or "Unknown"


def _validate_light_id(light_id: str) -> bool:
    """Check that a light ID looks like a valid UUID."""
    return bool(isinstance(light_id, str) and _LIGHT_ID_PATTERN.match(light_id))


@dataclass
class GradientLight:
    id: str
    name: str
    zone_count: int


class HueBridgeClient:
    def __init__(self, ip: str, app_key: str = ""):
        if ip:
            validate_bridge_ip(ip)
        self.ip = ip
        self.app_key = app_key
        self._base_url = f"https://{ip}"
        self._session: aiohttp.ClientSession | None = None
        self._cert_verified = False

    async def _verify_cert_tofu(self):
        """Trust-on-first-use certificate pinning.

        On first connection to a bridge IP, stores the cert fingerprint.
        On subsequent connections, verifies it matches.
        """
        if self._cert_verified or not self.ip:
            return

        current_fp = await _get_bridge_cert_fingerprint(self.ip)
        if not current_fp:
            logger.warning("Could not obtain bridge certificate for pinning")
            return

        stored_fp = load_cert_fingerprint(self.ip)
        if not stored_fp:
            # First connection — trust and store
            store_cert_fingerprint(self.ip, current_fp)
            logger.info("Stored bridge certificate fingerprint (TOFU)")
        elif stored_fp != current_fp:
            raise RuntimeError(
                f"Bridge certificate has changed! Expected {stored_fp[:16]}..., "
                f"got {current_fp[:16]}.... This could indicate a MITM attack. "
                "If you replaced your bridge, delete the stored fingerprint and retry."
            )
        else:
            logger.debug("Bridge certificate fingerprint verified")

        self._cert_verified = True

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            await self._verify_cert_tofu()
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=_make_ssl_context()),
                headers={"hue-application-key": self.app_key},
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # --- Discovery ---

    @staticmethod
    async def discover_bridge() -> str | None:
        """Discover Hue Bridge IP via meethue.com cloud endpoint."""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    "https://discovery.meethue.com",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.content_length and resp.content_length > _MAX_RESPONSE_SIZE:
                        logger.warning("Discovery response too large")
                        return None
                    bridges = await resp.json(content_type=None)
                    if not isinstance(bridges, list) or not bridges:
                        return None
                    entry = bridges[0]
                    if not isinstance(entry, dict):
                        return None
                    ip = entry.get("internalipaddress", "")
                    if not isinstance(ip, str) or not ip:
                        return None
                    # Validate the discovered IP is private
                    ip = validate_bridge_ip(ip)
                    logger.info("Discovered bridge at %s", ip)
                    return ip
            except ValueError as e:
                logger.warning("Discovered bridge IP rejected: %s", e)
            except Exception as e:
                logger.warning("Bridge discovery failed: %s", e)
        return None

    # --- Authentication ---

    async def authenticate(self, app_name: str = "desktop-lights", device_name: str = "mac") -> str:
        """Pair with bridge. User must press link button first.

        Returns the app key (username) on success.
        Raises RuntimeError if link button not pressed.
        """
        await self._verify_cert_tofu()

        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=_make_ssl_context()),
        ) as session:
            payload = {"devicetype": f"{app_name}#{device_name}", "generateclientkey": True}
            async with session.post(
                f"{self._base_url}/api",
                json=payload,
                timeout=_API_TIMEOUT,
            ) as resp:
                if resp.content_length and resp.content_length > _MAX_RESPONSE_SIZE:
                    raise RuntimeError("Auth response too large")
                result = await resp.json(content_type=None)

            if isinstance(result, list):
                if not result:
                    raise RuntimeError("Empty response from bridge")
                result = result[0]

            if not isinstance(result, dict):
                raise RuntimeError("Unexpected response format")

            if "error" in result:
                error = result["error"]
                desc = "Authentication failed"
                if isinstance(error, dict):
                    desc = _sanitize_name(error.get("description", desc))
                raise RuntimeError(desc)

            success = result.get("success", {})
            if not isinstance(success, dict):
                raise RuntimeError("Unexpected success format")

            self.app_key = success.get("username", "")
            if not self.app_key:
                raise RuntimeError("No app key in response")

            # Close existing session so it picks up new app_key
            if self._session and not self._session.closed:
                await self._session.close()
                self._session = None

            logger.info("Authenticated with bridge successfully")
            return self.app_key

    # --- Light Discovery ---

    async def discover_gradient_lights(self) -> list[GradientLight]:
        """Find all gradient-capable lights on the bridge."""
        session = await self._get_session()
        async with session.get(
            f"{self._base_url}/clip/v2/resource/light",
            timeout=_API_TIMEOUT,
        ) as resp:
            if resp.content_length and resp.content_length > _MAX_RESPONSE_SIZE:
                logger.warning("Light discovery response too large")
                return []
            data = await resp.json(content_type=None)

        if not isinstance(data, dict):
            logger.warning("Unexpected light discovery response format")
            return []

        lights = []
        for item in data.get("data", []):
            if not isinstance(item, dict):
                continue
            gradient = item.get("gradient", {})
            if not isinstance(gradient, dict):
                continue
            zone_count = gradient.get("points_capable", 0)
            if not isinstance(zone_count, int) or zone_count <= 0:
                continue
            zone_count = min(zone_count, _MAX_ZONE_COUNT)

            light_id = item.get("id", "")
            if not _validate_light_id(light_id):
                logger.warning("Skipping light with invalid ID: %r", str(light_id)[:32])
                continue

            name = _sanitize_name(item.get("metadata", {}).get("name", "Unknown"))
            lights.append(GradientLight(id=light_id, name=name, zone_count=zone_count))
            logger.info("Found gradient light: %s (%d zones)", name, zone_count)

        return lights

    # --- Gradient Control ---

    async def set_gradient(
        self,
        light_id: str,
        colors: list[tuple[float, float]],
        brightness: float = 100.0,
    ):
        """Set gradient points on a light.

        Args:
            light_id: Hue light resource ID
            colors: List of (x, y) CIE chromaticity values
            brightness: 0-100 brightness percentage
        """
        gradient_points = [
            {"color": {"xy": {"x": round(x, 4), "y": round(y, 4)}}}
            for x, y in colors
        ]

        payload = {
            "gradient": {"points": gradient_points},
            "dimming": {"brightness": min(100, max(0, brightness))},
        }

        session = await self._get_session()
        try:
            async with session.put(
                f"{self._base_url}/clip/v2/resource/light/{light_id}",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=2),
            ) as resp:
                if resp.status != 200:
                    logger.warning("Gradient update failed (%d) for light %s", resp.status, light_id)
        except asyncio.TimeoutError:
            logger.warning("Gradient update timed out for %s", light_id)
        except Exception as e:
            logger.warning("Gradient update error for %s: %s", light_id, type(e).__name__)

    async def turn_on(self, light_id: str):
        """Turn on a light."""
        session = await self._get_session()
        await session.put(
            f"{self._base_url}/clip/v2/resource/light/{light_id}",
            json={"on": {"on": True}},
            timeout=_API_TIMEOUT,
        )

    async def turn_off(self, light_id: str):
        """Turn off a light."""
        session = await self._get_session()
        await session.put(
            f"{self._base_url}/clip/v2/resource/light/{light_id}",
            json={"on": {"on": False}},
            timeout=_API_TIMEOUT,
        )
