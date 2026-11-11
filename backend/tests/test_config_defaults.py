"""I default di Settings devono valere per chiunque cloni il repo: gli indirizzi di una installazione stanno in .env."""
import ipaddress
import re
from urllib.parse import urlparse

from app.core.config import Settings

LOCAL_SUFFIXES = (".local", ".lan", ".internal", ".home.arpa")


def _site_specific(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host.endswith(LOCAL_SUFFIXES)
    return ip.is_private and not ip.is_loopback


def test_defaults_do_not_point_at_a_private_network():
    offenders = {}
    for name, field in Settings.model_fields.items():
        if not isinstance(field.default, str):
            continue
        hosts = [urlparse(url).hostname or "" for url in re.findall(r"https?://[^\s,]+", field.default)]
        if any(_site_specific(h) for h in hosts):
            offenders[name] = field.default
    assert not offenders, f"default legati a una installazione, da spostare in .env: {offenders}"


def test_optional_services_are_off_by_default():
    for name in ("watchdog_url", "searxng_url", "firecracker_api_url", "firecracker_log_url"):
        assert Settings.model_fields[name].default == "", name
