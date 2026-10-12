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

#!/usr/bin/env python3
"""Generate SHA-256 hash for access_password config.

Usage:
    python generate_access_password.py

Then copy the output hash to etc/conf/server.conf:
    access_password=<hash>
"""

import hashlib
import sys


def main():
    if len(sys.argv) > 1:
        print(f"Error: unexpected argument(s): {' '.join(sys.argv[1:])}")
        print("This tool only generates the access password hash interactively; it takes no arguments.")
        print("For TLS certificates use: python -m generate_selfsign_cert <cert_dir> serverAuth "
              "[--dns HOST] [--ip ADDRESS] [--plain-key]")
        sys.exit(1)
    print("Access Password Generator")
    print("=" * 40)
    password = input("Enter password: ").strip()
    if not password:
        print("Error: password cannot be empty")
        return
    hash_value = hashlib.sha256(password.encode()).hexdigest()
    print()
    print(f"SHA-256 hash: {hash_value}")
    print()
    print("Add this to etc/conf/server.conf:")
    print(f"  access_password={hash_value}")


if __name__ == "__main__":
    main()
