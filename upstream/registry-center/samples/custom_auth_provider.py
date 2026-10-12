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

"""Example adapter for a private, non-standard authentication protocol.

This module is not imported by Registry Center.  A deployment that needs a
business-specific protocol can register equivalent implementations during its
own startup without teaching the core access plane about private headers.
"""

from agent_registry.integration.authn import (
    AuthenticationContext, AuthenticationProvider, Credential, CredentialExtractor,
    register_authentication_provider,
)
from common.util.authenticate_util import CallerRole, CallerType, Principal


class BusinessHeaderExtractor(CredentialExtractor):
    def extract(self, request):
        value = request.headers.get('X-Business-Credential', '').strip()
        return Credential(kind='business', value=value) if value else None


class BusinessAuthenticationProvider(AuthenticationProvider):
    provider_id = 'business_custom'
    credential_kind = 'business'

    async def authenticate(self, credential: Credential,
                           context: AuthenticationContext) -> Principal:
        # Delegate to the business IAM here.  Never log credential.value.
        verified_subject = await verify_with_business_iam(credential.value)
        return Principal(
            client_ip=context.client_ip,
            identity=verified_subject,
            subject=verified_subject,
            credential_id=f'business:{verified_subject}',
            caller_type=CallerType.INTEGRATION,
            role=CallerRole.PARTNER_SERVICE,
            auth_method=self.provider_id,
        )


async def verify_with_business_iam(value: str) -> str:
    raise NotImplementedError('replace with the deployment-specific verifier')


def register() -> None:
    """Call from deployment startup before the integration listener starts."""
    register_authentication_provider(BusinessAuthenticationProvider(), BusinessHeaderExtractor())
