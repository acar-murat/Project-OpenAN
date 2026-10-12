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

import json
import socket
import threading

from loguru import logger
from pydantic import ValidationError

from agent_registry.internal.protocols.request import InternalRequest
from agent_registry.internal.registry_center_internal_service import RequestDispatcher
from agent_registry.registry_instance import get_registry
from common.util.app_config import get_conf


DEFAULT_TCP_PORT = 1108
DEFAULT_TCP_HOST = "127.0.0.1"


class TCPInternalService:
    """TCP-based internal service for Windows (replaces UDS which is not supported on Windows)."""

    def __init__(self, registry=None, config=None, host: str = DEFAULT_TCP_HOST, port: int = DEFAULT_TCP_PORT):
        self.host = host
        self.port = port
        self.registry = registry or get_registry()
        self.config = config or get_conf()
        self.dispatcher = RequestDispatcher()
        self._running = False
        self._server_socket = None

    def start(self):
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self._server_socket.bind((self.host, self.port))
            self._server_socket.listen(5)
            self._running = True
            logger.info(f"TCP internal service started on {self.host}:{self.port}")

            while self._running:
                try:
                    self._server_socket.settimeout(1.0)
                    conn, _ = self._server_socket.accept()
                    thread = threading.Thread(target=self._handle_request, args=(conn,), daemon=True)
                    thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self._running:
                        logger.error(f"Error accepting connection: {e}")
        except Exception as e:
            logger.error(f"Failed to start TCP service: {e}")
        finally:
            if self._server_socket:
                self._server_socket.close()

    def stop(self):
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
        logger.info("TCP internal service stopped")

    def _handle_request(self, conn):
        try:
            data = conn.recv(4096)
            if not data:
                return

            raw_request = json.loads(data.decode('utf-8'))

            try:
                request = InternalRequest(**raw_request)
            except ValidationError as e:
                response = {"success": False, "error": "Invalid request format", "message": str(e)}
                conn.send(json.dumps(response).encode('utf-8'))
                return

            handler = self.dispatcher.get_handler(request.action)
            if not handler:
                response = {"success": False, "error": f"Unknown action: {request.action}"}
            else:
                response = handler.handle(request.params, self.registry, self.config)

            conn.send(json.dumps(response).encode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON request: {e}")
            response = {"success": False, "error": "Invalid JSON format"}
            conn.send(json.dumps(response).encode('utf-8'))
        except Exception as e:
            logger.error(f"Error handling request: {e}")
            response = {"success": False, "error": str(e)}
            conn.send(json.dumps(response).encode('utf-8'))
        finally:
            conn.close()
