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
import os
import hashlib
from pathlib import Path
from typing import Optional
from loguru import logger


class StoragePath:
    """
    Storage path utility, used for backend public key file path management
    and permission configuration.
    """

    BASE_DIR = os.path.join(Path(__file__).parent.parent.parent, "etc", "sign_verify", "jwks")

    @staticmethod
    def get_storage_path(organization: Optional[str], agent_name: str, provider_url: Optional[str] = None) -> str:
        """
        Build storage path.

        Args:
            organization: Organization name (optional).
            agent_name: Agent name.
            provider_url: Provider URL (optional, used when organization is None).

        Returns:
            str: Storage file path.
        """
        if organization:
            org_dir = os.path.join(StoragePath.BASE_DIR, organization)
            full_path = os.path.join(org_dir, f"{agent_name}.json")
            resolved = os.path.realpath(full_path)
            if not resolved.startswith(os.path.realpath(StoragePath.BASE_DIR)):
                raise ValueError(f"Path traversal detected: {full_path}")
            return resolved
        else:
            # Without organization: etc/sign_verify/jwks/{hash of name + url}.json
            if not provider_url:
                raise ValueError("provider_url is required when organization is None")

            hash_key = f"{agent_name}{provider_url}"
            hash_value = hashlib.sha256(hash_key.encode('utf-8')).hexdigest()
            full_path = os.path.join(StoragePath.BASE_DIR, f"{hash_value}.json")
            resolved = os.path.realpath(full_path)
            if not resolved.startswith(os.path.realpath(StoragePath.BASE_DIR)):
                raise ValueError(f"Path traversal detected: {full_path}")
            return resolved

    @staticmethod
    def get_organization_dir(organization: str) -> str:
        """
        Get organization directory path.

        Args:
            organization: Organization name.

        Returns:
            str: Organization directory path.
        """
        full_path = os.path.join(StoragePath.BASE_DIR, organization)
        resolved = os.path.realpath(full_path)
        if not resolved.startswith(os.path.realpath(StoragePath.BASE_DIR)):
            raise ValueError(f"Path traversal detected: {full_path}")
        return resolved

    @staticmethod
    def ensure_directory_exists(file_path: str) -> None:
        """
        Ensure the directory exists; create it if it doesn't.

        Args:
            file_path: File path.
        """
        file_path_obj = Path(file_path)
        file_path_obj.parent.mkdir(parents=True, exist_ok=True)

        # Set directory permissions to 700
        os.chmod(file_path_obj.parent, 0o700)

    @staticmethod
    def set_file_permissions(file_path: str) -> None:
        """
        Set file permissions to 600.

        Args:
            file_path: File path.
        """
        if os.path.exists(file_path):
            os.chmod(file_path, 0o600)

    @staticmethod
    def is_valid_path(file_path: str) -> bool:
        """
        Validate whether the path is valid.

        Args:
            file_path: File path.

        Returns:
            bool: Whether the path is valid.
        """
        try:
            path_obj = Path(file_path)
            return path_obj.exists() and path_obj.is_file()
        except Exception:
            return False
