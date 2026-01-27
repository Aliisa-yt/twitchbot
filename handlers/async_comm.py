"""Asynchronous communication utilities for HTTP and socket operations.

This module provides classes for making asynchronous HTTP requests and socket communication.
It includes error handling for common issues such as timeouts, connection errors, and invalid content types.
The `AsyncHttp` class handles HTTP requests with customizable content type handlers,
while the `AsyncSocket` class manages socket connections for sending and receiving data.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, Final, Literal, Self

import aiohttp
from aiohttp.client import ClientSession
from aiohttp.web_exceptions import HTTPError

from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

    from aiohttp.client import ClientResponse


__all__: list[str] = ["AsyncCommError", "AsyncCommTimeoutError", "AsyncHttp", "AsyncSocket"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

HTTPMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

CONNECT_TIMEOUT: Final[float] = 1.0


class AsyncHttp:
    """Asynchronous HTTP client for making requests and handling responses.

    This class provides methods for performing GET and POST requests, handling different content types,
    and managing an aiohttp session.
    It supports custom content type handlers, allowing the client to process responses based on their content type.
    """

    def __init__(self) -> None:
        """Initialize the AsyncHttp client.

        This method sets up the aiohttp session and registers default content type handlers.
        It also logs the initialization of the client.

        The default handlers include:
            - "text/plain": Decodes bytes to a UTF-8 string.
            - "text/html": Decodes bytes to a UTF-8 string.
            - "application/json": Parses bytes as JSON.
        """
        logger.info("%s initializing", self.__class__.__name__)
        self.__session: ClientSession | None = None
        self.content_handlers: dict[str, Callable[[bytes], Any]] = {}

        self.add_handler("text/plain", lambda x: x.decode("utf-8"))
        self.add_handler("text/html", lambda x: x.decode("utf-8"))
        self.add_handler("application/json", lambda x: json.loads(x.decode("utf-8")))
        self.list_handlers()
        self.initialize_session()

    async def __aenter__(self) -> Self:
        logger.debug("%s entering context", self.__class__.__name__)
        # Suppress "session already initialized" log when entering the context if session
        # was already created during __init__ or a previous context.
        self.initialize_session(suppress_already_log=True)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        _ = exc_type, exc_val, exc_tb
        logger.debug("%s exiting context", self.__class__.__name__)
        await self.close()

    def initialize_session(self, *, suppress_already_log: bool = False) -> None:
        """Initialize the aiohttp session.

        Args:
            suppress_already_log (bool): If True, do not log when the session is already initialized.
        """
        if self.__session is None or self.__session.closed:
            self.__session = ClientSession(raise_for_status=True)
            logger.debug("%s session initialized", self.__class__.__name__)
        elif not suppress_already_log:
            logger.debug("%s session already initialized", self.__class__.__name__)

    @property
    def session(self) -> ClientSession:
        """Get or create the current aiohttp session."""
        if self.__session is None or self.__session.closed:
            msg = "Session is not initialized or has been closed"
            raise RuntimeError(msg)
        return self.__session

    async def close(self) -> None:
        """Close the aiohttp session if it is open."""
        if self.__session and not self.__session.closed:
            await self.__session.close()
        logger.info("%s session closed", self.__class__.__name__)

    async def get(self, *, url: str, total_timeout: float = 10.0, proxies: dict[str, str] | None = None) -> Any:
        """Perform an asynchronous HTTP GET request.

        Args:
            url (str): The URL to send the GET request to.
            total_timeout (float): Total timeout for the request in seconds.
            proxies (dict[str, str] | None): Optional proxies to use for the request.
        Returns:
            Any: The response data, parsed as JSON if applicable.
        """
        logger.debug("'url': '%s', 'timeout': '%s'", url, total_timeout)
        proxies = proxies if isinstance(proxies, dict) else {}

        return await self._request(
            "GET",
            url=url,
            total_timeout=total_timeout,
            proxies=proxies,
        )

    async def post(
        self,
        *,
        url: str,
        params: dict[str, str] | None = None,
        data: Any | None = None,
        total_timeout: float = 10.0,
        proxies: dict[str, str] | None = None,
    ) -> Any:
        """Perform an asynchronous HTTP POST request.

        Args:
            url (str): The URL to send the POST request to.
            params (dict[str, str] | None): Optional query parameters for the request.
            data (Any | None): The data to send in the POST request body.
            total_timeout (float): Total timeout for the request in seconds.
            proxies (dict[str, str] | None): Optional proxies to use for the request.
        Returns:
            Any: The response data, parsed as JSON if applicable.
        """
        logger.debug("'url': '%s', 'params': '%s', 'data': '%s', 'timeout': '%s'", url, params, data, total_timeout)
        proxies = proxies if isinstance(proxies, dict) else {}

        return await self._request(
            "POST",
            url=url,
            params=params,
            json=data,
            total_timeout=total_timeout,
            proxies=proxies,
        )

    async def decode_response(self, resp: ClientResponse) -> Any:
        """Parse the response from an HTTP request.

        This method checks the 'Content-Type' header of the response and uses the appropriate handler
        to parse the response data. If no handler is found for the content type, it raises an error.

        Args:
            resp (ClientResponse): The response object from the aiohttp request.
        Returns:
            Any: The parsed response data, which can be a string, JSON object,
                or other types depending on the content type.
        Raises:
            AsyncCommInvalidContentTypeError: If the content type of the response is not recognized
                or no handler is registered for it.
        """
        content_type: str = resp.headers.get("Content-Type", "").split(";")[0].strip()
        logger.debug("'Content-Type': '%s'", content_type)

        raw: bytes = await resp.read()
        if not raw:
            logger.debug("Received empty response")
            return None

        handler: Callable[[bytes], Any] | None = self.content_handlers.get(content_type)
        if handler:
            return handler(raw)

        msg: str = f"Unknown Content-Type '{content_type}'"
        raise AsyncCommInvalidContentTypeError(msg)

    def add_handler(self, content_type: str, handler: Callable[[bytes], Any]) -> None:
        """Add a custom handler for a specific content type.

        This allows the client to handle different content types with custom parsing logic.

        Args:
            content_type (str): The content type to handle (e.g., "text/plain", "application/json").
            handler (Callable[[bytes], Any]): A function that takes bytes and returns the parsed data.
        """
        if self.content_handlers.get(content_type):
            logger.warning("Handler for content type '%s' already exists, replacing it", content_type)
        self.content_handlers[content_type] = handler
        logger.debug("Added handler for content type '%s'", content_type)

    def list_handlers(self) -> None:
        """List all registered content type handlers.

        This method logs the content types for which handlers have been registered.
        It is useful for debugging and ensuring that the client has the necessary handlers for expected content types.
        """
        if not self.content_handlers:
            logger.info("No content type handlers registered")
            return
        logger.info("Handlers registered for content types '%s'", list(self.content_handlers.keys()))

    async def _request(
        self,
        method: HTTPMethod,
        *,
        url: str,
        total_timeout: float,
        proxies: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Perform an asynchronous HTTP request.

        Args:
            method (HTTPMethod): The HTTP method to use (GET, POST, etc.).
            url (str): The URL to send the request to.
            total_timeout (float): Total timeout for the request in seconds.
            proxies (dict[str, str] | None): Optional proxies to use for the request.
            **kwargs: Additional keyword arguments to pass to the aiohttp request.
        Returns:
            Any: The response data, parsed as JSON if applicable.
        """
        logger.debug("[%s] url=%s timeout=%s kwargs=%s", method, url, total_timeout, kwargs)
        proxy: str | None = (proxies or {}).get("https") or (proxies or {}).get("http")
        # Set a timeout for the request
        if total_timeout <= 0:
            # If total_timeout is 0 or negative, set no timeout
            _timeout = aiohttp.ClientTimeout(total=None)
        elif total_timeout < CONNECT_TIMEOUT:
            # If total_timeout is less than CONNECT_TIMEOUT, set a total timeout only
            # This prevents the connection timeout from being too short
            _timeout = aiohttp.ClientTimeout(total=total_timeout)
        else:
            # Set a connect timeout of 'CONNECT_TIMEOUT' and a total timeout as specified
            # This allows for quick connection attempts while still respecting the total timeout
            _timeout = aiohttp.ClientTimeout(connect=CONNECT_TIMEOUT, total=total_timeout)

        try:
            async with self.session.request(
                method=method,
                url=url,
                timeout=_timeout,
                proxy=proxy,
                **kwargs,
            ) as resp:
                resp.raise_for_status()
                return await self.decode_response(resp)

        except TimeoutError as err:
            logger.debug(err)
            msg = "Timeout due to a lack of response from the server."
            raise AsyncCommTimeoutError(msg) from err
        except ConnectionResetError as err:
            logger.debug(err)
            msg = "The connection to the server has been disconnected."
            raise AsyncCommError(msg) from err
        except aiohttp.ClientConnectorError as err:
            logger.debug(err)
            msg = "The server is not running, or the port is closed."
            raise AsyncCommError(msg) from err
        except (HTTPError, aiohttp.ClientResponseError) as err:
            logger.debug(err)
            msg = "Error response from the server."
            raise AsyncCommError(msg, response=err) from err


class AsyncSocket:
    """Asynchronous socket communication class for sending and receiving data.

    This class provides methods to connect to a server, send data, receive data, and close the connection.
    It uses asyncio for non-blocking I/O operations and handles various exceptions that may occur during communication.

    Note:
        - The context manager (``async with AsyncSocket() as s``) does not automatically perform
          a network connection. Call ``await s.connect(address)`` after entering the context to connect.
        - ``close()`` will close the connection and reset internal readers/writers so the instance can be reused.
    """

    def __init__(self, *, timeout: float = 10.0, buffer: int = 4096) -> None:
        logger.info("%s initializing", self.__class__.__name__)
        logger.debug("'timeout': '%s'", timeout)
        logger.debug("'buffer': '%s'", buffer)
        self._timeout: float = timeout
        self._buffer: int = buffer
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def __aenter__(self) -> Self:
        logger.debug("%s entering context", self.__class__.__name__)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        _ = exc_type, exc_val, exc_tb
        logger.debug("%s exiting context", self.__class__.__name__)
        await self.close()

    async def connect(self, address: tuple[str, int]) -> None:
        """Connect to a server using the provided address.

        This method attempts to establish a connection to the server at the specified address.

        Args:
            address (tuple[str, int]): A tuple containing the server address (IP or hostname) and port.
        Raises:
            AsyncCommError: If the server address is incorrectly specified or if the connection fails.
            AsyncCommTimeoutError: If the connection times out due to a lack of response from the server.
            ConnectionRefusedError: If the server is not running or the port is closed.
            BlockingIOError: If the timeout is too short for the connection attempt.
            OSError: If there is an OS error during the connection attempt.
        """
        try:
            logger.debug("Connecting to server at '%s:%s'", address[0], address[1])
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(address[0], address[1]), timeout=self._timeout
            )
        except IndexError as err:
            msg = "Server address is incorrectly specified."
            raise AsyncCommError(msg) from err
        except TimeoutError as err:
            msg = "Timeout due to a lack of response from the server."
            raise AsyncCommTimeoutError(msg) from err
        except ConnectionRefusedError as err:
            msg = "The server is not running, or the port is closed."
            raise AsyncCommError(msg) from err
        except BlockingIOError as err:
            msg = "Timeout too short."
            raise AsyncCommError(msg) from err
        except OSError as err:
            msg = "OS error during connection"
            raise AsyncCommError(msg) from err

    async def send(self, message_data: bytes) -> None:
        """Send data to the socket.

        This method writes the provided message data to the socket writer and ensures that the data is flushed.
        """
        logger.debug("Sending data with buffer size %s and timeout %s", self._buffer, self._timeout)
        logger.debug("'message': '%s'", message_data)
        if self._writer is None:
            msg = "Socket is not connected"
            raise AsyncCommError(msg)
        self._writer.write(message_data)
        await self._writer.drain()

    async def received(self) -> bytes:
        """Receive data from the socket.

        This method reads data from the socket using the configured buffer size and timeout.
        """
        logger.debug("Receiving data with buffer size %s and timeout %s", self._buffer, self._timeout)
        if self._reader is None:
            msg = "Socket is not connected"
            raise AsyncCommError(msg)
        try:
            data: bytes = await asyncio.wait_for(self._reader.read(self._buffer), timeout=self._timeout)
            if data == b"":
                msg = "Connection closed by remote host"
                raise AsyncCommError(msg)
        except TimeoutError as err:
            msg = "Timed out while waiting for data"
            raise AsyncCommTimeoutError(msg) from err
        except (ConnectionResetError, BrokenPipeError) as err:
            msg = "Connection reset during receive"
            raise AsyncCommError(msg) from err
        except OSError as err:
            msg = "OS error during receive"
            raise AsyncCommError(msg) from err
        else:
            return data

    async def close(self) -> None:
        """Close the socket connection.

        After closing, internal ``_reader`` and ``_writer`` attributes are reset to ``None``
        so the instance can be safely reused.
        """
        if self._writer is None:
            logger.warning("Socket writer is already closed or not initialized")
        else:
            logger.debug("Closing socket writer")
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as err:  # noqa: BLE001
                logger.debug("Error while closing writer: %s", err)

        self._reader = None
        self._writer = None
        logger.info("%s process termination", self.__class__.__name__)


class AsyncCommError(Exception):
    """Base class for asynchronous communication errors.

    This class is used to handle errors that occur during asynchronous communication,
    such as HTTP request failures, timeouts, or connection issues.
    It provides a standardized way to raise and catch these errors with additional context.
    """

    def __init__(self, msg: str | BaseException, **kwargs: Any) -> None:
        self.msg: str = str(msg)

        rsp: HTTPError | aiohttp.ClientResponseError | None = kwargs.pop("response", None)
        if isinstance(rsp, (HTTPError, aiohttp.ClientResponseError)):
            self.msg = f"{self.msg}: status='{rsp.status}'"

        super().__init__(self.msg)


class AsyncCommTimeoutError(AsyncCommError):
    """Error raised when an asynchronous communication operation times out.

    This error is used to indicate that a request or operation did not complete within the specified timeout period.
    It can be raised during HTTP requests, socket communication, or other asynchronous operations.
    """


class AsyncCommInvalidContentTypeError(AsyncCommError):
    """Error raised when the content type of a response is not recognized or no handler is registered for it.

    This error is used to indicate that the client received a response with an unexpected or unsupported content type,
    and there is no appropriate handler to process it.
    """
