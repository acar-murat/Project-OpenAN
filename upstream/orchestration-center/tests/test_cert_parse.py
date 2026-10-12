# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for cert_parse.py -- X.509 certificate and CRL parsing functions.

Covers:
- parse_cer_certificate: valid PEM, missing BEGIN, file not found, SM2 rejection
- parse_pem_files: valid PEM, wrong password, file not found
- parse_crl_list: valid CRL, missing BEGIN, no CRL found
- _extract_certificate_info: normal extraction
- _extract_certificate_infos: list processing
"""

import datetime
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from common.cert.cert_parse import (
    SM2_SIGN,
    _extract_certificate_info,
    _extract_certificate_infos,
    parse_cer_certificate,
    parse_crl_list,
    parse_pem_files,
)
from common.cert.cert_exception import CertParseException
from common.cert.x509_obj import CertObj, X509Obj


# ---------------------------------------------------------------------------
# Helpers -- generate real certs in temp files
# ---------------------------------------------------------------------------

def _generate_rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def _generate_ec_key():
    return ec.generate_private_key(ec.SECP256R1())


def _make_self_signed_cert(key, subject="CN=Test"):
    subject_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)])
    now = datetime.datetime.now(datetime.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(subject_name)
        .issuer_name(subject_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )


def _write_pem_cert(cert, path):
    with open(path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def _write_pem_key(key, path, password=None):
    enc = (
        serialization.BestAvailableEncryption(password)
        if password
        else serialization.NoEncryption()
    )
    with open(path, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=enc,
        ))


# ===========================================================================
# parse_cer_certificate
# ===========================================================================

class TestParseCerCertificate:
    def test_parse_valid_cert(self, tmp_path):
        key = _generate_rsa_key()
        cert = _make_self_signed_cert(key, "CN=TestCert")
        cert_path = str(tmp_path / "server.cer")
        _write_pem_cert(cert, cert_path)

        result = parse_cer_certificate(cert_path)
        assert isinstance(result, X509Obj)
        assert len(result.cert_list) == 1
        assert "TestCert" in result.cert_list[0].subject

    def test_parse_missing_begin_line(self, tmp_path):
        cert_path = str(tmp_path / "bad.cer")
        with open(cert_path, "wb") as f:
            f.write(b"\x30\x82\x01\x00")  # DER bytes, no PEM
        with pytest.raises(CertParseException, match="BEGIN"):
            parse_cer_certificate(cert_path)

    def test_parse_nonexistent_file(self):
        with pytest.raises(Exception):
            parse_cer_certificate("/nonexistent/path/cert.cer")

    def test_parse_empty_pem_file(self, tmp_path):
        cert_path = str(tmp_path / "empty.cer")
        with open(cert_path, "wb") as f:
            f.write(b"-----BEGIN CERTIFICATE-----\n-----END CERTIFICATE-----\n")
        with pytest.raises(CertParseException):
            parse_cer_certificate(cert_path)

    def test_parse_multiple_certs(self, tmp_path):
        key1 = _generate_rsa_key()
        key2 = _generate_ec_key()
        cert1 = _make_self_signed_cert(key1, "CN=Cert1")
        cert2 = _make_self_signed_cert(key2, "CN=Cert2")
        cert_path = str(tmp_path / "chain.cer")
        with open(cert_path, "wb") as f:
            f.write(cert1.public_bytes(serialization.Encoding.PEM))
            f.write(cert2.public_bytes(serialization.Encoding.PEM))
        result = parse_cer_certificate(cert_path)
        assert len(result.cert_list) == 2
        assert "Cert1" in result.cert_list[0].subject
        assert "Cert2" in result.cert_list[1].subject


# ===========================================================================
# parse_pem_files
# ===========================================================================

class TestParsePemFiles:
    def test_parse_valid_key_no_password(self, tmp_path):
        key = _generate_rsa_key()
        key_path = str(tmp_path / "server_key.pem")
        _write_pem_key(key, key_path)
        result = parse_pem_files(key_path)
        assert result is not None
        assert isinstance(result, rsa.RSAPrivateKey)

    def test_parse_valid_key_with_password(self, tmp_path):
        key = _generate_rsa_key()
        key_path = str(tmp_path / "encrypted_key.pem")
        _write_pem_key(key, key_path, password=b"Str0ng!Pass")
        result = parse_pem_files(key_path, password=b"Str0ng!Pass")
        assert result is not None

    def test_parse_wrong_password(self, tmp_path):
        key = _generate_rsa_key()
        key_path = str(tmp_path / "encrypted_key.pem")
        _write_pem_key(key, key_path, password=b"CorrectPass1!")
        with pytest.raises(CertParseException):
            parse_pem_files(key_path, password=b"WrongPassword1!")

    def test_parse_nonexistent_file(self):
        with pytest.raises(CertParseException):
            parse_pem_files("/nonexistent/key.pem")


# ===========================================================================
# parse_crl_list
# ===========================================================================

class TestParseCrlList:
    def test_parse_valid_crl(self, tmp_path):
        key = _generate_rsa_key()
        cert = _make_self_signed_cert(key, "CN=CA")
        now = datetime.datetime.now(datetime.timezone.utc)
        crl = (
            x509.CertificateRevocationListBuilder()
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CN=CA")]))
            .last_update(now - datetime.timedelta(days=1))
            .next_update(now + datetime.timedelta(days=30))
            .sign(key, hashes.SHA256())
        )
        crl_path = str(tmp_path / "revocation.crl")
        with open(crl_path, "wb") as f:
            f.write(crl.public_bytes(serialization.Encoding.PEM))
        result = parse_crl_list(crl_path)
        assert result is not None
        assert result.issuer == cert.issuer

    def test_parse_missing_begin_line(self, tmp_path):
        crl_path = str(tmp_path / "bad.crl")
        with open(crl_path, "wb") as f:
            f.write(b"\x30\x82\x01\x00")
        with pytest.raises(CertParseException, match="BEGIN"):
            parse_crl_list(crl_path)

    def test_parse_nonexistent_file(self):
        with pytest.raises(CertParseException):
            parse_crl_list("/nonexistent/revocation.crl")


# ===========================================================================
# _extract_certificate_info / _extract_certificate_infos
# ===========================================================================

class TestExtractCertInfo:
    def test_extract_single_cert(self):
        key = _generate_rsa_key()
        cert = _make_self_signed_cert(key, "CN=Extract")
        result = _extract_certificate_info(cert)
        assert isinstance(result, CertObj)
        assert "Extract" in result.subject
        assert result.version == x509.Version.v3
        assert result.public_key is not None
        assert result.org_cert is not None

    def test_extract_multiple_certs(self):
        key1 = _generate_rsa_key()
        key2 = _generate_ec_key()
        cert1 = _make_self_signed_cert(key1, "CN=A")
        cert2 = _make_self_signed_cert(key2, "CN=B")
        results = _extract_certificate_infos([cert1, cert2])
        assert len(results) == 2
        assert "A" in results[0].subject
        assert "B" in results[1].subject

    def test_extract_empty_list(self):
        results = _extract_certificate_infos([])
        assert results == []


# ===========================================================================
# SM2 rejection
# ===========================================================================

class TestSM2Rejection:
    def test_sm2_sign_constant(self):
        assert SM2_SIGN == "1.2.156.10197.1.501"

    def test_extract_cert_info_rejects_sm2(self):
        """If a cert's signature_algorithm_oid matches SM2_SIGN, a
        CertParseException should be raised."""
        mock_cert = MagicMock()
        mock_oid = MagicMock()
        mock_oid.dotted_string = SM2_SIGN
        mock_cert.signature_algorithm_oid = mock_oid
        with pytest.raises(CertParseException, match="sm3"):
            _extract_certificate_info(mock_cert)
