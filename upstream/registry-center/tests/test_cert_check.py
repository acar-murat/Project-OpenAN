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
Certificate pre-check CLI tests (task 6.1). Reuses the generated PKI from
the certificate authentication integration tests.
"""

import pytest

from agent_registry.cert_check import check_certificate, main
from tests.test_integration_cert_auth import pki  # noqa: F401


class TestCheckCertificate:
    def test_valid_cert_passes_all_checks(self, pki):
        passed, results = check_certificate(str(pki["valid"][0]), ca_path=str(pki["ca"]),
                                            crl_path=str(pki["root"] / "revocationlist.crl"))
        assert passed is True
        assert all(ok for _, ok, _ in results)
        # 7 checks ran: parse, v3, CN, validity, key strength, chain, CRL
        assert len(results) == 7

    def test_expired_cert_fails_with_hint(self, pki):
        passed, results = check_certificate(str(pki["expired"][0]), ca_path=str(pki["ca"]))
        assert passed is False
        validity = [detail for name, ok, detail in results
                    if name == "validity period" and not ok][0]
        assert "EXPIRED" in validity

    def test_revoked_cert_fails(self, pki):
        passed, results = check_certificate(str(pki["revoked"][0]),
                                            ca_path=str(pki["ca"]),
                                            crl_path=str(pki["root"] / "revocationlist.crl"))
        assert passed is False
        crl = [detail for name, ok, detail in results
               if name == "CRL revocation status"][0]
        assert "REVOKED" in crl

    def test_untrusted_chain_fails(self, pki, tmp_path):
        """A cert issued by a DIFFERENT CA fails the trust-chain check."""
        from tests.test_integration_cert_auth import _gen_key, _make_cert, _write_cert
        import datetime
        rogue_ca_key = _gen_key()
        rogue_ca = _make_cert("Rogue CA", rogue_ca_key, None, None,
                              datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30),
                              is_ca=True)
        rogue_cert_path = tmp_path / "rogue.cer"
        _write_cert(rogue_cert_path, pki["valid"][0] and _make_cert(
            "partner_valid_cn", _gen_key(), rogue_ca, rogue_ca_key,
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)))
        passed, results = check_certificate(str(rogue_cert_path), ca_path=str(pki["ca"]))
        assert passed is False
        chain = [detail for name, ok, detail in results if name == "trust chain"][0]
        assert "issued by CA" not in chain or "Rogue" not in chain

    def test_garbage_file_fails_gracefully(self, tmp_path):
        bad = tmp_path / "bad.cer"
        bad.write_text("this is not a certificate", encoding="utf-8")
        passed, results = check_certificate(str(bad))
        assert passed is False
        assert "parses" in results[0][0]

    def test_missing_ca_is_not_reported_as_success(self, pki):
        passed, results = check_certificate(str(pki["valid"][0]))
        assert passed is False
        assert any(name == "trust chain" and not ok for name, ok, _ in results)

    def test_unreadable_crl_is_not_reported_as_success(self, pki, tmp_path):
        bad_crl = tmp_path / "bad.crl"
        bad_crl.write_text("not a CRL", encoding="utf-8")
        passed, results = check_certificate(
            str(pki["valid"][0]), ca_path=str(pki["ca"]), crl_path=str(bad_crl))
        assert passed is False
        assert any(name == "CRL revocation status" and not ok for name, ok, _ in results)


class TestCliExitCodes:
    def test_valid_cert_exits_zero(self, pki, capsys):
        code = main([str(pki["valid"][0]), "--ca", str(pki["ca"])])
        assert code == 0
        assert "PASSED" in capsys.readouterr().out

    def test_expired_cert_exits_nonzero(self, pki, capsys):
        code = main([str(pki["expired"][0]), "--ca", str(pki["ca"])])
        assert code == 1
        assert "FAILED" in capsys.readouterr().out

    def test_missing_file_exits_nonzero(self, capsys):
        code = main(["Z:/nonexistent/client.cer"])
        assert code == 1
