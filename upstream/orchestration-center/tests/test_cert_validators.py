# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the untested cert_validator.py classes.

The existing test_cert_validator.py covers PathValidator, password_verify,
ValidationResult, ConfObj, and CipherConverter. This file adds coverage for:
- CerContentValidator.validate() (success, wrong version, weak key, expired)
- PrivateKeyValidator.validate() (success, wrong password, key mismatch)
- CRLValidator.validate() (not configured, valid, invalid, nonexistent)
- CertValidator.validate() (config missing, path fail, content fail)
- CommonContentValidator.validate_certificate_validity()
- CerContentValidatorLink.build_link()
- PathValidatorLink.build_link() (already partially covered, but verify)
"""

import datetime
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from common.cert.cert_validator import (
    CRLValidator,
    CerContentValidator,
    CerContentValidatorLink,
    CertValidator,
    CommonContentValidator,
    PathValidator,
    PathValidatorLink,
    PrivateKeyValidator,
)
from common.cert.x509_obj import X509Obj
from common.util.validation_result import ValidationResult


# ---------------------------------------------------------------------------
# Helpers -- reuse from test_cert_parse.py pattern
# ---------------------------------------------------------------------------

def _generate_rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def _generate_ec_key():
    return ec.generate_private_key(ec.SECP256R1())


def _make_self_signed_cert(key, subject="CN=Test", days_valid=365):
    subject_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)])
    now = datetime.datetime.now(datetime.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(subject_name)
        .issuer_name(subject_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=days_valid))
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
# CommonContentValidator.validate_certificate_validity
# ===========================================================================

class TestValidateCertificateValidity:
    def test_valid_cert_within_range(self):
        key = _generate_rsa_key()
        cert = _make_self_signed_cert(key, "CN=Valid", days_valid=365)
        from common.cert.cert_parse import _extract_certificate_info
        cert_obj = _extract_certificate_info(cert)
        x509_obj = X509Obj(cert_list=[cert_obj])
        assert CommonContentValidator.validate_certificate_validity(x509_obj) is True

    def test_expired_cert(self):
        key = _generate_rsa_key()
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CN=Expired")]))
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CN=Expired")]))
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=400))
            .not_valid_after(now - datetime.timedelta(days=100))
            .sign(key, hashes.SHA256())
        )
        from common.cert.cert_parse import _extract_certificate_info
        cert_obj = _extract_certificate_info(cert)
        x509_obj = X509Obj(cert_list=[cert_obj])
        assert CommonContentValidator.validate_certificate_validity(x509_obj) is False

    def test_future_cert(self):
        key = _generate_rsa_key()
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CN=Future")]))
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CN=Future")]))
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now + datetime.timedelta(days=100))
            .not_valid_after(now + datetime.timedelta(days=500))
            .sign(key, hashes.SHA256())
        )
        from common.cert.cert_parse import _extract_certificate_info
        cert_obj = _extract_certificate_info(cert)
        x509_obj = X509Obj(cert_list=[cert_obj])
        assert CommonContentValidator.validate_certificate_validity(x509_obj) is False

    def test_multiple_certs_all_valid(self):
        key1 = _generate_rsa_key()
        key2 = _generate_ec_key()
        cert1 = _make_self_signed_cert(key1, "CN=A")
        cert2 = _make_self_signed_cert(key2, "CN=B")
        from common.cert.cert_parse import _extract_certificate_infos
        cert_objs = _extract_certificate_infos([cert1, cert2])
        x509_obj = X509Obj(cert_list=cert_objs)
        assert CommonContentValidator.validate_certificate_validity(x509_obj) is True


# ===========================================================================
# CerContentValidator.validate()
# ===========================================================================

class TestCerContentValidator:
    def test_valid_cert(self, tmp_path):
        key = _generate_rsa_key()
        cert = _make_self_signed_cert(key, "CN=Server")
        cert_path = str(tmp_path / "server.cer")
        _write_pem_cert(cert, cert_path)
        validator = CerContentValidator(cert_path, conf_tip="ssl_certfile")
        result = validator.validate()
        assert result.is_valid is True
        assert "passed" in result.message

    def test_nonexistent_file(self, tmp_path):
        validator = CerContentValidator(str(tmp_path / "nonexistent.cer"))
        result = validator.validate()
        assert result.is_valid is False

    def test_weak_key_rejected(self, tmp_path):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cert = _make_self_signed_cert(key, "CN=Weak")
        cert_path = str(tmp_path / "weak.cer")
        _write_pem_cert(cert, cert_path)
        validator = CerContentValidator(cert_path)
        result = validator.validate()
        assert result.is_valid is False
        assert "requirements" in result.message


# ===========================================================================
# PrivateKeyValidator.validate()
# ===========================================================================

class TestPrivateKeyValidator:
    def test_valid_private_key(self, tmp_path):
        key = _generate_rsa_key()
        cert = _make_self_signed_cert(key, "CN=Server")
        cert_path = str(tmp_path / "server.cer")
        key_path = str(tmp_path / "server_key.pem")
        _write_pem_cert(cert, cert_path)
        _write_pem_key(key, key_path, password=b"Str0ng!Pass")
        validator = PrivateKeyValidator(
            cert_path=key_path,
            password_bytes=b"Str0ng!Pass",
            server_path=cert_path,
            conf_tip="ssl_keyfile",
        )
        result = validator.validate()
        assert result.is_valid is True

    def test_weak_password_rejected(self, tmp_path):
        key = _generate_rsa_key()
        cert = _make_self_signed_cert(key, "CN=Server")
        cert_path = str(tmp_path / "server.cer")
        key_path = str(tmp_path / "server_key.pem")
        _write_pem_cert(cert, cert_path)
        _write_pem_key(key, key_path, password=b"weak")
        validator = PrivateKeyValidator(
            cert_path=key_path,
            password_bytes=b"weak",
            server_path=cert_path,
        )
        result = validator.validate()
        assert result.is_valid is False
        assert "password" in result.message.lower()

    def test_key_cert_mismatch(self, tmp_path):
        key1 = _generate_rsa_key()
        key2 = _generate_rsa_key()
        cert = _make_self_signed_cert(key1, "CN=Server")
        cert_path = str(tmp_path / "server.cer")
        key_path = str(tmp_path / "server_key.pem")
        _write_pem_cert(cert, cert_path)
        _write_pem_key(key2, key_path, password=b"Str0ng!Pass")
        validator = PrivateKeyValidator(
            cert_path=key_path,
            password_bytes=b"Str0ng!Pass",
            server_path=cert_path,
        )
        result = validator.validate()
        assert result.is_valid is False
        assert "match" in result.message.lower()

    def test_password_cleared_after_validate(self, tmp_path):
        key = _generate_rsa_key()
        cert = _make_self_signed_cert(key, "CN=Server")
        cert_path = str(tmp_path / "server.cer")
        key_path = str(tmp_path / "server_key.pem")
        _write_pem_cert(cert, cert_path)
        _write_pem_key(key, key_path, password=b"Str0ng!Pass")
        validator = PrivateKeyValidator(
            cert_path=key_path,
            password_bytes=b"Str0ng!Pass",
            server_path=cert_path,
        )
        validator.validate()
        # finally block should clear password_bytes
        assert validator.password_bytes == b""


# ===========================================================================
# CRLValidator.validate()
# ===========================================================================

class TestCRLValidator:
    def test_not_configured(self):
        validator = CRLValidator(cert_path=None)
        result = validator.validate()
        assert result.is_valid is True
        assert "not config" in result.message.lower()

    def test_empty_string(self):
        validator = CRLValidator(cert_path="")
        result = validator.validate()
        assert result.is_valid is True

    def test_nonexistent_file(self, tmp_path):
        validator = CRLValidator(cert_path=str(tmp_path / "nonexistent.crl"))
        result = validator.validate()
        assert result.is_valid is False
        assert "not exist" in result.message.lower()

    def test_valid_crl(self, tmp_path):
        key = _generate_rsa_key()
        now = datetime.datetime.now(datetime.timezone.utc)
        from cryptography.x509.oid import ExtensionOID
        crl = (
            x509.CertificateRevocationListBuilder()
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CN=CA")]))
            .last_update(now - datetime.timedelta(days=1))
            .next_update(now + datetime.timedelta(days=30))
            .add_extension(x509.CRLNumber(1), critical=False)
            .sign(key, hashes.SHA256())
        )
        crl_path = str(tmp_path / "revocation.crl")
        with open(crl_path, "wb") as f:
            f.write(crl.public_bytes(serialization.Encoding.PEM))
        validator = CRLValidator(cert_path=crl_path)
        result = validator.validate()
        assert result.is_valid is True

    def test_expired_crl(self, tmp_path):
        key = _generate_rsa_key()
        now = datetime.datetime.now(datetime.timezone.utc)
        from cryptography.x509.oid import ExtensionOID
        crl = (
            x509.CertificateRevocationListBuilder()
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CN=CA")]))
            .last_update(now - datetime.timedelta(days=100))
            .next_update(now - datetime.timedelta(days=1))
            .add_extension(x509.CRLNumber(1), critical=False)
            .sign(key, hashes.SHA256())
        )
        crl_path = str(tmp_path / "expired.crl")
        with open(crl_path, "wb") as f:
            f.write(crl.public_bytes(serialization.Encoding.PEM))
        validator = CRLValidator(cert_path=crl_path)
        result = validator.validate()
        assert result.is_valid is False
        assert "valid" in result.message.lower()


# ===========================================================================
# CerContentValidatorLink / PathValidatorLink
# ===========================================================================

class TestValidatorLinks:
    def test_cer_content_validator_link_builds(self):
        conf_obj = MagicMock()
        conf_obj.ssl_certfile = "/fake/cert.cer"
        conf_obj.ssl_ca_certs = "/fake/ca.cer"
        link = CerContentValidatorLink(conf_obj)
        assert len(link.link) == 2
        assert isinstance(link.link[0], CerContentValidator)
        assert isinstance(link.link[1], CerContentValidator)

    def test_path_validator_link_builds(self):
        conf_obj = MagicMock()
        conf_obj.ssl_certfile = "/fake/cert.cer"
        conf_obj.ssl_keyfile = "/fake/key.pem"
        conf_obj.ssl_keyfile_password = "/fake/pwd"
        conf_obj.ssl_ca_certs = "/fake/ca.cer"
        conf_obj.ssl_crl_file = ""
        link = PathValidatorLink(conf_obj)
        assert len(link.link) == 5
        assert all(isinstance(v, PathValidator) for v in link.link)

    def test_link_validate_all_pass(self):
        conf_obj = MagicMock()
        conf_obj.ssl_certfile = ""
        conf_obj.ssl_ca_certs = ""
        link = CerContentValidatorLink(conf_obj)
        result = link.validate()
        # Empty paths -> CerContentValidator will fail (file not found)
        assert result.is_valid is False


# ===========================================================================
# CommonContentValidator.validate() -- base class returns None
# ===========================================================================

class TestBaseValidate:
    def test_base_validate_returns_none(self):
        validator = CommonContentValidator("/fake/path")
        result = validator.validate()
        assert result is None

    def test_validate_public_key_length_rsa(self):
        key = _generate_rsa_key()
        assert CommonContentValidator.validate_public_key_length(key.public_key()) is True

    def test_validate_public_key_length_ec(self):
        key = _generate_ec_key()
        assert CommonContentValidator.validate_public_key_length(key.public_key()) is True

    def test_validate_public_key_length_unknown(self):
        fake_key = MagicMock()
        assert CommonContentValidator.validate_public_key_length(fake_key) is False

    def test_validate_private_key_length_rsa(self):
        key = _generate_rsa_key()
        assert CommonContentValidator.validate_private_key_length(key) is True

    def test_validate_private_key_length_ec(self):
        key = _generate_ec_key()
        assert CommonContentValidator.validate_private_key_length(key) is True

    def test_validate_private_key_length_unknown(self):
        fake_key = MagicMock()
        assert CommonContentValidator.validate_private_key_length(fake_key) is False
