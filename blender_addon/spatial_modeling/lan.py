"""The LAN port (8767) for both roles: the session token and TLS that uses it as a pre-shared key.

Client-role add-ons join the host over the LAN. By default the connection is
TLS keyed by the session token (TLS-PSK), so there are no certificates: only a
peer that knows the token completes the handshake, in either direction, and the
traffic is encrypted. If TLS-PSK fails somewhere, the host can run the port
without TLS on an isolated network route; then the client puts the token in its
`hello` (contracts/README.md, "Connecting").

Standard library only and no bpy: the Client role (remote_client/), the tests
and tests/backend/ping_client.py use it as well as the host.

    sock = lan.connect(address, token)              # TLS-PSK; raises lan.HandshakeError
    sock = lan.connect(address, token, tls=False)   # fallback; send hello with "token" first

Never log or display the token anywhere except the host's add-on preferences.
"""

import functools
import hashlib
import hmac
import secrets
import socket
import ssl

PORT = 8767
ALL_INTERFACES = "0.0.0.0"
HANDSHAKE_TIMEOUT = 10.0  # s the host waits for the TLS handshake, or for hello without TLS

TOKEN_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"  # no 0/o or 1/i/l, so it reads aloud well
TOKEN_LENGTH = 24  # 24 of 31 symbols: about 119 bits
MIN_TOKEN_LENGTH = 16  # for a token the user types in

PSK_IDENTITY = "spatial_modeling/1"
# Our two ends negotiate TLS 1.3, where any OpenSSL PSK handshake uses ECDHE and an
# AEAD cipher. TLS 1.2 is accepted with the one OpenSSL PSK suite that does both. Never
# set_ciphers("PSK") as in Python's docs: that list includes PSK-NULL-* (no encryption).
TLS12_CIPHERS = "ECDHE-PSK-CHACHA20-POLY1305"
_KDF_SALT = b"spatial_modeling LAN PSK v1"
_KDF_ROUNDS = 200_000  # about 60 ms, once per token


class TokenError(ValueError):
    """The session token is missing or too short. The message never contains the token."""


class HandshakeError(ConnectionError):
    """The TLS handshake failed: a wrong token, a host without TLS, or not our host."""


def new_token():
    """A random session token like "k7qm-3xfa-9pdz-w2hn-r8ce-tb5u"."""
    chars = "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH))
    return "-".join(chars[i : i + 4] for i in range(0, TOKEN_LENGTH, 4))


def normalize_token(token):
    """The token without case, spaces or dashes, so a token read aloud still matches."""
    text = "".join(ch for ch in (token or "").lower() if not ch.isspace() and ch != "-")
    if len(text) < MIN_TOKEN_LENGTH:
        raise TokenError(f"The session token needs at least {MIN_TOKEN_LENGTH} characters")
    return text


def tokens_match(expected, given):
    """Compare a token received in `hello` with ours, in constant time."""
    if not isinstance(given, str):
        return False
    try:
        given = normalize_token(given)
    except TokenError:
        return False
    return hmac.compare_digest(normalize_token(expected).encode(), given.encode())


def psk(token):
    """The 32-byte pre-shared key for a token (PBKDF2, so guessing a typed-in token is slow)."""
    return _derive(normalize_token(token))


@functools.lru_cache(maxsize=4)
def _derive(normalized):
    return hashlib.pbkdf2_hmac("sha256", normalized.encode(), _KDF_SALT, _KDF_ROUNDS)


def _context(purpose):
    if not ssl.HAS_PSK:
        raise NotImplementedError(
            "This Python has no TLS-PSK support (ssl.HAS_PSK is False). "
            "Run the LAN port without TLS, on an isolated network only."
        )
    ctx = ssl.SSLContext(purpose)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    ctx.set_ciphers(TLS12_CIPHERS)
    return ctx


def server_tls_context(token):
    """The host's context for the LAN port. Raises TokenError or NotImplementedError."""
    key = psk(token)
    ctx = _context(ssl.PROTOCOL_TLS_SERVER)
    ctx.num_tickets = 0  # no session resumption: every connection proves the token again
    # No certificate is loaded, so a handshake without our PSK has nothing to fall back on.
    ctx.set_psk_server_callback(lambda identity: key if identity == PSK_IDENTITY else b"")
    return ctx


def client_tls_context(token):
    """A client's context for the host's LAN port. Raises TokenError or NotImplementedError.

    Use it with ssl wrap_socket or asyncio.open_connection(ssl=...); server_hostname is
    not needed. It accepts only a host that proves it has the same token.
    """
    key = psk(token)
    ctx = _context(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False  # there is no certificate to carry a host name
    # Keep CERT_REQUIRED with an empty trust store (never load CA certificates): a PSK
    # handshake has no certificate to check, but any host that skips the PSK and
    # presents a certificate instead is refused. CERT_NONE would let an impostor in.
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.cert_store_stats()["x509"] == 0
    ctx.set_psk_client_callback(lambda hint: (PSK_IDENTITY, key))
    return ctx


def local_address():
    """This PC's IPv4 address on the network with the default route, or None. Sends nothing."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1; connecting a UDP socket sends no packet
            return s.getsockname()[0]
        except OSError:
            return None


def connect(address, token, port=PORT, tls=True, timeout=5.0):
    """Open a blocking connection to a host's LAN port. Returns the socket.

    With tls=False (the host's fallback mode) nothing is checked here: the first
    message must be `hello` with "token", or the host closes the connection.
    Raises TokenError, OSError, or HandshakeError (a ConnectionError).
    """
    context = client_tls_context(token) if tls else None
    sock = socket.create_connection((address, port), timeout=timeout)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # TLS 1.3 waits 40 ms without
    if context is None:
        return sock
    try:
        tls_sock = context.wrap_socket(sock)
    except (ssl.SSLError, ConnectionError, TimeoutError) as e:
        sock.close()
        raise HandshakeError(
            f"The TLS handshake with {address}:{port} failed ({e}). "
            "Check the session token, and that the host's LAN port uses TLS."
        ) from e
    if tls_sock.getpeercert(binary_form=True) is not None:  # the context already refuses this
        tls_sock.close()
        raise HandshakeError(f"{address}:{port} sent a certificate instead of using the token")
    return tls_sock
