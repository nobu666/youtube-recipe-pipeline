import socket
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from url_guard import UnsafeURLError, assert_safe_url, safe_head


def _gai(ip):
    """Mocked return value for socket.getaddrinfo (family, type, proto, canon, (ip, port))"""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 0))]


@pytest.mark.parametrize("url", [
    "ftp://example.com/x",
    "file:///etc/passwd",
    "gopher://example.com/",
    "javascript:alert(1)",
    "http://",        # no host
    "https://",
])
def test_scheme_or_host_blocked(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata
    "http://127.0.0.1/",
    "http://10.0.0.1/",
    "http://172.16.0.1/",
    "http://192.168.1.1/",
    "http://[::1]/",
    "http://0.0.0.0/",
])
def test_literal_internal_ip_blocked(url):
    # For a literal IP, getaddrinfo returns that same IP as-is, so no mock is needed
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


@pytest.mark.parametrize("url", [
    "http://0177.0.0.1/",   # octal -> 127.0.0.1
    "http://0x7f.0.0.1/",   # hex -> 127.0.0.1
    "http://2130706433/",   # decimal -> 127.0.0.1
])
def test_numeric_ipv4_parser_differential_blocked(url):
    # Block a numeric IP notation that exploits the getaddrinfo/inet_aton interpretation gap
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


def test_public_host_allowed():
    with patch("url_guard.socket.getaddrinfo", return_value=_gai("93.184.216.34")):
        scheme, host, ips = assert_safe_url("https://example.com/page")
    assert scheme == "https"
    assert host == "example.com"
    assert ips == ["93.184.216.34"]


@pytest.mark.parametrize("ip", ["::1", "fe80::1", "::", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254"])
def test_getaddrinfo_resolved_ipv6_internal_blocked(ip):
    # Block when the host resolves to an internal-facing IPv6 (including IPv4-mapped)
    with patch("url_guard.socket.getaddrinfo", return_value=_gai(ip)):
        with pytest.raises(UnsafeURLError):
            assert_safe_url("http://evil.example.test/")


def test_hostname_resolving_to_private_blocked():
    # Block even a domain that looks public if it resolves to an internal IP (defends against DNS setup tricks)
    with patch("url_guard.socket.getaddrinfo", return_value=_gai("10.1.2.3")):
        with pytest.raises(UnsafeURLError):
            assert_safe_url("http://internal.example.test/")


def test_unresolvable_host_blocked():
    with patch("url_guard.socket.getaddrinfo", side_effect=socket.gaierror("nope")):
        with pytest.raises(UnsafeURLError):
            assert_safe_url("http://no-such-host.invalid/")


class _Resp:
    def __init__(self, status, location=None, url=None):
        self.status_code = status
        self.headers = {"Location": location} if location else {}
        self.url = url


def _host_aware_gai(host, *a, **k):
    # An internal-IP host returns that IP; everything else returns a public IP
    internal = {"169.254.169.254"}
    return _gai(host if host in internal else "93.184.216.34")


def test_safe_head_blocks_redirect_to_internal():
    # A public URL redirects via 302 to 169.254.169.254 -> blocked by per-hop validation
    with patch("url_guard.socket.getaddrinfo", side_effect=_host_aware_gai), \
         patch("requests.head", return_value=_Resp(302, location="http://169.254.169.254/")):
        with pytest.raises(UnsafeURLError):
            safe_head("https://start.example/")


def test_safe_head_follows_public_redirect():
    seq = [
        _Resp(302, location="/article"),  # a relative Location
        _Resp(200, url="https://start.example/article"),
    ]
    with patch("url_guard.socket.getaddrinfo", return_value=_gai("93.184.216.34")), \
         patch("requests.head", side_effect=seq):
        resp = safe_head("https://start.example/")
    assert resp.status_code == 200
    assert resp.url == "https://start.example/article"


def test_safe_head_redirect_loop_aborts():
    # A 302 loop back to the same URL is cut off by max_redirects
    with patch("url_guard.socket.getaddrinfo", return_value=_gai("93.184.216.34")), \
         patch("requests.head", return_value=_Resp(302, location="https://loop.example/")):
        with pytest.raises(UnsafeURLError):
            safe_head("https://loop.example/")
