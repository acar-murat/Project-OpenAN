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

"""Generate a static Bearer token digest without writing the token to disk."""

import argparse
import getpass
import os
import sys

from agent_registry.integration.authn import token_fingerprint


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate a static Bearer token HMAC digest")
    parser.add_argument('--key-env', default='INTEGRATION_TOKEN_HMAC_KEY',
                        help='environment variable containing the HMAC key')
    args = parser.parse_args(argv)
    key = os.environ.get(args.key_env, '')
    if not key:
        print(f"Missing HMAC key environment variable: {args.key_env}", file=sys.stderr)
        return 1
    token = getpass.getpass('Bearer token: ')
    if not token:
        print("Token must not be empty", file=sys.stderr)
        return 1
    print(token_fingerprint(token, key))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
