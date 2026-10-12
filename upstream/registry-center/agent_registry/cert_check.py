# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Client-certificate pre-check tool (task 6.1).

Operators run this before handing a client certificate to an integrating
third party (or before configuring one on the integration access port):

    python -m agent_registry.cert_check client.cer --ca trust.cer [--crl revocationlist.crl]

Checks: X.509 parse/v3 format, validity period, subject CN presence, key
algorithm and strength (RSA >= 3072 bits / EC >= 256 bits), trust chain
against the CA bundle, and CRL revocation status. Failures print a
structured report naming each failed check with remediation hints and exit
non-zero.
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec, rsa

_SEPARATOR = "=" * 78
_MIN_RSA_BITS = 3072
_MIN_EC_BITS = 256


def _load_certificate(path: str) -> x509.Certificate:
    data = Path(path).read_bytes()
    try:
        return x509.load_pem_x509_certificate(data)
    except ValueError:
        return x509.load_der_x509_certificate(data)


def check_certificate(cert_path: str, ca_path: str = None,
                      crl_path: str = None) -> tuple:
    """Run all checks. Returns (passed: bool, results: list[(check, ok, detail)])."""
    results = []

    def record(name: str, ok: bool, detail: str = ''):
        results.append((name, ok, detail))
        return ok

    # 1. Parse
    cert = None
    try:
        cert = _load_certificate(cert_path)
        record("certificate file parses", True)
    except Exception as e:
        record("certificate file parses", False,
               f"{cert_path}: {type(e).__name__}: {e} — verify the file is a "
               f"PEM or DER X.509 certificate")
        return False, results

    # 2. X.509 v3
    version = cert.version
    record("X.509 v3 format", version == x509.Version.v3,
           f"actual version: {version.name}" if version != x509.Version.v3 else "")

    # 3. Subject CN present
    cn = ''
    for attr in cert.subject:
        if attr.oid == x509.NameOID.COMMON_NAME:
            cn = attr.value
    record("subject CN present", bool(cn),
           "subject has no CommonName — integration identity is derived from CN"
           if not cn else f"CN={cn}")

    # 4. Validity period
    now = datetime.now(timezone.utc)
    not_before = cert.not_valid_before_utc
    not_after = cert.not_valid_after_utc
    if now < not_before:
        record("validity period", False,
               f"certificate is not yet valid (notBefore={not_before.isoformat()})")
    elif now > not_after:
        record("validity period", False,
               f"certificate EXPIRED at {not_after.isoformat()} — renew the certificate")
    else:
        record("validity period", True,
               f"valid until {not_after.isoformat()}")

    # 5. Key algorithm and strength
    key = cert.public_key()
    if isinstance(key, rsa.RSAPublicKey):
        ok = key.key_size >= _MIN_RSA_BITS
        record("key strength (RSA)", ok,
               f"RSA {key.key_size} bits < required {_MIN_RSA_BITS}" if not ok
               else f"RSA {key.key_size} bits")
    elif isinstance(key, ec.EllipticCurvePublicKey):
        ok = key.curve.key_size >= _MIN_EC_BITS
        record("key strength (EC)", ok,
               f"{key.curve.name} {key.curve.key_size} bits < required {_MIN_EC_BITS}"
               if not ok else f"{key.curve.name} {key.curve.key_size} bits")
    else:
        record("key strength (RSA)", False,
               f"unsupported key type {type(key).__name__} — use RSA or EC")

    # 6. Trust chain
    if ca_path:
        chain_ok = False
        detail = ''
        try:
            ca_data = Path(ca_path).read_bytes()
            ca_certs = x509.load_pem_x509_certificates(ca_data)
        except Exception as e:
            ca_certs = []
            detail = f"CA bundle unreadable: {type(e).__name__}: {e}"
        for ca in ca_certs:
            try:
                cert.verify_directly_issued_by(ca)
                chain_ok = True
                detail = f"issued by CA CN={ca.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value}"
                break
            except Exception as e:
                detail = f"{type(e).__name__}: {e}"
        record("trust chain", chain_ok,
               detail if not chain_ok else detail)
    else:
        record("trust chain", False, "CA bundle is required (--ca)")

    # 7. CRL revocation
    if crl_path:
        revoked = False
        crl_ok = True
        detail = ''
        try:
            crl = x509.load_pem_x509_crl(Path(crl_path).read_bytes())
            entry = crl.get_revoked_certificate_by_serial_number(cert.serial_number)
            revoked = entry is not None
            detail = (f"serial {hex(cert.serial_number)} is REVOKED "
                      f"(reason: {entry.extensions})" if revoked
                      else f"serial {hex(cert.serial_number)} not listed")
        except Exception as e:
            crl_ok = False
            detail = f"CRL unreadable: {type(e).__name__}: {e}"
        record("CRL revocation status", crl_ok and not revoked, detail)
    else:
        record("CRL revocation status", True, "skipped: no CRL provided (--crl)")

    passed = all(ok for _, ok, _ in results)
    return passed, results


def print_report(cert_path: str, results: tuple, ca_path: str = None, crl_path: str = None) -> None:
    passed, checks = results
    lines = [
        "=" * 78,
        "[certificate pre-check] " + ("PASSED" if passed else "FAILED"),
        f"  certificate : {cert_path}",
        f"  ca bundle   : {ca_path or '(not provided)'}",
        f"  crl         : {crl_path or '(not provided)'}",
        "  checks:",
    ]
    for name, ok, detail in checks:
        marker = "[ OK ]" if ok else "[FAIL]"
        suffix = f" — {detail}" if detail else ""
        lines.append(f"    {marker} {name}{suffix}")
    if not passed:
        lines.append("  Remediate the [FAIL] items above and re-run before integration.")
    lines.append("=" * 78)
    print("\n".join(lines))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agent_registry.cert_check",
        description="Pre-check a integration client certificate before integration")
    parser.add_argument("certificate", help="client certificate file (PEM/DER)")
    parser.add_argument("--ca", default=None,
                        help="trusted CA bundle (PEM), e.g. etc/ssl/trust.cer")
    parser.add_argument("--crl", default=None, help="CRL file (PEM), optional")
    args = parser.parse_args(argv)

    try:
        results = check_certificate(args.certificate, ca_path=args.ca, crl_path=args.crl)
    except FileNotFoundError as e:
        print(f"[certificate pre-check] FAILED: file not found: {e.filename}")
        return 1
    print_report(args.certificate, results, ca_path=args.ca, crl_path=args.crl)
    return 0 if results[0] else 1


if __name__ == "__main__":
    sys.exit(main())
