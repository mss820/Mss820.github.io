#!/usr/bin/env python3
"""
Encrypt a static HTML file into a self-contained, password-gated page.

The output is plain HTML/JS: it prompts for a password in the browser,
derives an AES-256 key from it with PBKDF2, and decrypts the original
page client-side with the Web Crypto API. Nobody can view the real
content (source, images, etc.) without the correct password -- but note
this is client-side protection: someone who saves the locked HTML file
could attempt an offline brute-force of the password, so use a real
passphrase, not a short PIN.

Usage:
    python3 tools/lock.py <source.html> <output.html>

You'll be prompted for the password interactively (hidden input, never
written to disk or shell history). Local <img>/<a> references to
.jpg/.jpeg/.png/.gif/.svg/.webp/.pdf files are automatically inlined as
base64 data URIs before encryption, so the output file has zero
external dependencies that could leak content.
"""
import sys
import re
import base64
import hashlib
import getpass
import secrets
import mimetypes
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITERATIONS = 300_000
TEMPLATE_PATH = Path(__file__).parent / "gate_template.html"
ASSET_RE = re.compile(
    r'(src|href)="((?!https?://|data:|mailto:|#)[^"]+\.(?:jpe?g|png|gif|svg|webp|pdf))"',
    re.IGNORECASE,
)


def inline_local_assets(html: str, base_dir: Path) -> str:
    def repl(m: re.Match) -> str:
        attr, rel_path = m.group(1), m.group(2)
        fp = (base_dir / rel_path).resolve()
        if not fp.is_file():
            print(f"  warning: referenced asset not found, leaving as-is: {rel_path}")
            return m.group(0)
        mime = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
        data = base64.b64encode(fp.read_bytes()).decode("ascii")
        print(f"  inlined {rel_path} ({fp.stat().st_size // 1024} KB, {mime})")
        return f'{attr}="data:{mime};base64,{data}"'

    return ASSET_RE.sub(repl, html)


def main() -> None:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <source.html> <output.html>")
        sys.exit(1)

    src_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    html = src_path.read_text(encoding="utf-8")
    print(f"Inlining local assets referenced by {src_path.name}...")
    html = inline_local_assets(html, src_path.parent)

    password = getpass.getpass("Password for this page: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match. Aborting.")
        sys.exit(1)
    if len(password) < 10:
        print(
            "Warning: that's a short password. Since this is a client-side gate, "
            "the strength of the password is what stands between the ciphertext "
            "and the content -- a longer passphrase is meaningfully safer."
        )

    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS, dklen=32)
    ciphertext = AESGCM(key).encrypt(iv, html.encode("utf-8"), None)

    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else "Protected Page"

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    out_html = (
        template.replace("{{TITLE}}", title)
        .replace("{{SALT_B64}}", base64.b64encode(salt).decode("ascii"))
        .replace("{{IV_B64}}", base64.b64encode(iv).decode("ascii"))
        .replace("{{ITERATIONS}}", str(ITERATIONS))
        .replace("{{CIPHERTEXT_B64}}", base64.b64encode(ciphertext).decode("ascii"))
    )

    out_path.write_text(out_html, encoding="utf-8")
    print(f"Wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
