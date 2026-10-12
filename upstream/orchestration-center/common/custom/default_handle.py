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

"""Pluggable-handler mechanism: BaseHandler contract and the HandlerRegistry.

This module holds the *mechanism* only. Business implementations live outside
``common/``: the file-mode defaults and the database-backed handlers are
registered by ``orchestrate/handlers/__init__.py``; third parties can register
additional overrides the same way (:meth:`HandlerRegistry.register`).
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional, Type

from loguru import logger

from common.custom.interface_type import InterfaceType
from common.util.persistence_mode import is_db_mode, persistence_mode


class BaseHandler(ABC):
    """Abstract base class requiring subclasses to implement the handle method."""

    @abstractmethod
    def handle(self, *args, **kwargs):
        """Concrete business logic is implemented by subclasses."""
        pass


class HandlerRegistry:
    """Dispatch table from an :class:`InterfaceType` to a handler class.

    Two slots exist per interface type:

    - *defaults* (file mode): the JSON-storage implementations, registered
      with :meth:`register_default`;
    - *overrides* (database mode): implementations registered with
      :meth:`register`, which replace the defaults whenever
      ``persistence_mode`` selects a database-backed mode.

    Dispatch intentionally fails loudly in database mode when no override is
    registered: silently falling back to file storage would scatter workflow
    data across two backends.
    """

    _defaults: Dict[str, Type[BaseHandler]] = {}
    _overrides: Dict[str, Type[BaseHandler]] = {}
    _bundled_overrides: Dict[str, Type[BaseHandler]] = {}

    @classmethod
    def register_default(cls, interface_type: InterfaceType, handler_class: Type[BaseHandler]) -> None:
        """Register the file-mode implementation for an interface type."""
        cls._register_into(cls._defaults, interface_type, handler_class, slot="default", bundled=True)

    @classmethod
    def register(cls, interface_type: InterfaceType, handler_class: Type[BaseHandler],
                 bundled: bool = False) -> None:
        """
        Register a database-mode (or third-party) implementation class.

        :param interface_type: Interface type identifier, e.g. ``SAVE_PSOP``
        :param handler_class: Custom class inheriting from BaseHandler
        :param bundled: True for this repository's own handler (a built-in, not
            an extension). Built-ins are marked so that
            :meth:`get_extension_override` can tell them apart from a handler a
            third party registered in their place.
        """
        cls._register_into(cls._overrides, interface_type, handler_class, slot="override", bundled=bundled)

    @classmethod
    def get_extension_override(cls, interface_type: InterfaceType) -> Optional[Type[BaseHandler]]:
        """The class an extension registered *in place of* the bundled handler.

        Returns ``None`` when the slot still holds the bundled implementation or
        is empty. A storage port calls this before using its own implementation:
        an extension that replaced a query handler wins, and the bundled handler
        is deliberately not returned, because invoking it would dispatch back
        into the port that is asking (circular delegation).
        """
        key = interface_type.value
        candidate = cls._overrides.get(key)
        if candidate is None or candidate is cls._bundled_overrides.get(key):
            return None
        return candidate

    @classmethod
    def _register_into(cls, slot_map: Dict[str, Type[BaseHandler]], interface_type: InterfaceType,
                       handler_class: Type[BaseHandler], slot: str, bundled: bool = False) -> None:
        if not issubclass(handler_class, BaseHandler):
            raise TypeError("handler_class must be a subclass of BaseHandler")
        slot_map[interface_type.value] = handler_class
        if slot == "override":
            # Identity belongs to this registration, never to an inheritable
            # class attribute. Re-registering even the same class is an extension.
            if bundled:
                cls._bundled_overrides[interface_type.value] = handler_class
            else:
                cls._bundled_overrides.pop(interface_type.value, None)

    @classmethod
    def get_handler(cls, interface_type: InterfaceType, mode: Optional[str] = None) -> BaseHandler:
        """Instantiate the handler matching the configured persistence mode."""
        db_mode = is_db_mode() if mode is None else mode != "file"
        resolved_mode = persistence_mode() if mode is None else mode
        if db_mode:
            handler_class = cls._overrides.get(interface_type.value)
            if handler_class is None:
                raise ValueError(
                    f"No custom handler registered for '{interface_type.value}' "
                    f"but persistence_mode={resolved_mode}. "
                    "Register a handler via HandlerRegistry.register() first."
                )
            logger.debug(f"[Registry] Dispatching '{interface_type.value}' → DB handler (mode={resolved_mode})")
            return handler_class()
        handler_class = cls._defaults.get(interface_type.value)
        if handler_class is None:
            raise ValueError(f"Unknown interface type: {interface_type}")
        logger.debug(f"[Registry] Dispatching '{interface_type.value}' → file handler (mode={resolved_mode})")
        return handler_class()
