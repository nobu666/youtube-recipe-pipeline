#!/usr/bin/env python3
"""Shared SSRF-defense guard.

Validates a URL before fetching it externally. Restricts the scheme to
http/https, resolves the hostname via DNS, and blocks any internal-facing
IP (private / loopback / link-local / reserved, etc). This blocks:

- Cloud metadata: http://169.254.169.254/ (link-local)
- localhost / 127.0.0.1 / ::1 (loopback)
- LAN: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 (private)
- Non-HTTP schemes such as file:// / ftp://

Note (residual risk): DNS rebinding — where the IP resolved at check time
differs from the IP used at connect time — isn't fully preventable by this
guard alone (resolve -> check -> each library re-resolves and connects).
The requests path mitigates this via safe_head(), which manually follows
redirects and re-validates each hop; trafilatura / playwright / markitdown's
internal redirects are only validated at the entry point.
"""

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    """Raised when a URL is rejected as SSRF-unsafe."""


def _ip_is_blocked(ip_str):
    ip = ipaddress.ip_address(ip_str)
    # For an IPv4-mapped IPv6 address (::ffff:a.b.c.d), judge by the inner IPv4.
    # On Python < 3.13, IPv6Address("::ffff:127.0.0.1").is_private incorrectly
    # returns False, so without this explicit unwrap an internal IP would slip through.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_safe_url(url):
    """Validate that url is safe to fetch externally. Raises UnsafeURLError if not.

    On success, returns (scheme, host, [resolved_ips]).
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"Disallowed scheme: {scheme or '(none)'} ({url})")

    host = parsed.hostname
    if not host:
        raise UnsafeURLError(f"No hostname: {url}")

    # libc(inet_aton)-based clients (Chromium / some HTTP libraries) may connect
    # using an octal/hex/decimal numeric IPv4 interpretation that differs from
    # getaddrinfo's. To close this parser-differential SSRF, if the host can be
    # parsed as a numeric IPv4 literal, also judge the block-list against that
    # interpretation's IP.
    try:
        aton_ip = socket.inet_ntoa(socket.inet_aton(host))
    except OSError:
        aton_ip = None
    if aton_ip and _ip_is_blocked(aton_ip):
        raise UnsafeURLError(f"Blocked access to an internal IP (numeric notation): {host} -> {aton_ip}")

    try:
        port = parsed.port
    except ValueError:
        raise UnsafeURLError(f"Invalid port: {url}")
    port = port or (443 if scheme == "https" else 80)

    # Resolve the hostname via DNS and check every resolved IP (guards against multiple A/AAAA records)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeURLError(f"Couldn't resolve the hostname: {host} ({e})")

    ips = sorted({info[4][0] for info in infos})
    for ip in ips:
        if _ip_is_blocked(ip):
            raise UnsafeURLError(f"Blocked access to an internal IP: {host} -> {ip}")
    return scheme, host, ips


def safe_head(url, *, max_redirects=5, timeout=10):
    """Equivalent to requests.head, but manually follows redirects and calls
    assert_safe_url at each hop.

    Returns the final requests.Response. Raises UnsafeURLError if an unsafe hop is reached.
    """
    import requests

    current = url
    for _ in range(max_redirects + 1):
        assert_safe_url(current)
        resp = requests.head(current, allow_redirects=False, timeout=timeout)
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location")
            if not loc:
                return resp
            current = urljoin(current, loc)
            continue
        return resp
    raise UnsafeURLError(f"Too many redirects: {url}")
