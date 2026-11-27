import asyncio
from collections.abc import Callable
from datetime import timedelta
from time import monotonic
from typing import Literal

from solala.constants import Constants
from solala.delegates.power_consumer.consumer_status import ConsumerStatus
from solala.delegates.power_consumer.power_consumer import PowerConsumer
from solala.register_bank import RegisterBank
from solala.utils.json_extras import JSONDict


type ConsumerReadOperation = Literal['status', 'registers']
type ConsumerReadObserver = Callable[[PowerConsumerManager, ConsumerReadOperation, Exception | None], None]


class PowerConsumerManager:
    """
    Run one background worker for a power consumer's status and register discovery.

    The worker reads the delegate on demand. Requests for the same operation
    share a single queued or in-flight attempt.

    Call `try_get_status()` to read the latest available status and queue a
    refresh if due. The method returns immediately.

    Call `request_register_discovery()` to queue discovery and return
    immediately. Read `discovered_registers` on a later client refresh.
    A value of None means the active connection has yet to publish a bank.
    The published definitions are fixed for that connection. A new request
    can retry a failed discovery.

    The worker reports completed attempts for the active connection to the
    configured observer. Awaiting `close()` stops new requests and waits for
    the worker to finish any in-flight read and close the delegate.
    """

    def __init__(
            self,
            consumer: PowerConsumer,
            status_expiry_duration: timedelta = Constants.CONSUMER_STATUS_CACHE_TIME,
            *,
            on_read_complete: ConsumerReadObserver | None = None,
    ) -> None:
        """
        Start a worker for the consumer on the current event loop.

        Args:
            consumer: Delegate owned by this manager.
            status_expiry_duration: Time after a successful read before a
                client request can trigger the next refresh.
            on_read_complete: Output callback invoked by the worker after
                a status or discovery attempt completes. It receives this
                manager, the operation, and the exception or None on success.
                Pending, cancelled, and retired reads produce no callback.
        """
        self._consumer: PowerConsumer = consumer
        self._on_read_complete = on_read_complete
        self._registers: RegisterBank | None = None
        self._status: ConsumerStatus | None = None
        self._status_expiry_duration: float = status_expiry_duration.total_seconds()
        self._status_cache_expiry: float = float('-inf')  # monotonic timestamp

        # Each flag stays True while a request is queued or in flight, so clients
        # share an attempt. The worker clears it after success or failure.
        self._need_status = False
        self._need_registers = False

        self._closed = False
        self._wake = asyncio.Event()
        self._worker = asyncio.create_task(self._run())

    def get_connection_info(self) -> JSONDict:
        """
        Get the consumer connection information.
        """
        # no special treatment needed
        return self._consumer.get_connection_info()

    def request_register_discovery(self) -> None:
        """
        Queue discovery if the connection is active and its bank is still unknown.
        """
        if not self._closed and self._registers is None and not self._need_registers:
            self._need_registers = True
            self._wake.set()

    @property
    def discovered_registers(self) -> RegisterBank | None:
        """
        Return the published register definitions for the active connection.
        """
        return None if self._closed else self._registers

    def try_get_status(self) -> ConsumerStatus | None:
        """
        Return the latest status and request a refresh if due.

        Once the status expiry duration has elapsed, the next request queues
        a refresh and still returns the previous reading. Return None until
        the first successful read, after a failed read, or after closure.
        """
        if self._closed:
            return None
        if monotonic() >= self._status_cache_expiry and not self._need_status:
            self._need_status = True
            self._wake.set()
        return self._status

    def begin_close(self) -> None:
        """
        Stop accepting demand and wake the worker to finish closing.
        """
        self._closed = True
        self._wake.set()

    async def close(self) -> None:
        """
        Wait for the worker to close the delegate before propagating cancellation.
        """
        self.begin_close()
        cancelled = False
        # Let the worker finish closing even if the caller is cancelled.
        while not self._worker.done():
            try:
                await asyncio.shield(self._worker)
            except asyncio.CancelledError:
                cancelled = True
        await self._worker
        if cancelled:
            raise asyncio.CancelledError

    async def _run(self) -> None:
        try:
            while not self._closed:
                await self._wake.wait()
                self._wake.clear()
                if self._closed:
                    break

                # Keep the flags set during I/O so duplicate requests share the read.
                if self._need_status:
                    status_error: Exception | None = None
                    try:
                        self._got_status(await self._consumer.get_status())
                    except Exception as err:
                        self._status = None
                        status_error = err
                    finally:
                        self._need_status = False
                    self._notify_read_complete('status', status_error)

                if self._need_registers and not self._closed:
                    discovery_error: Exception | None = None
                    try:
                        self._registers = await self._consumer.get_registers()
                    except Exception as err:
                        self._registers = None
                        discovery_error = err
                    finally:
                        self._need_registers = False
                    self._notify_read_complete('registers', discovery_error)
        finally:
            await self._consumer.close()

    def _notify_read_complete(self, operation: ConsumerReadOperation, error: Exception | None) -> None:
        if not self._closed and self._on_read_complete is not None:
            self._on_read_complete(self, operation, error)

    def _got_status(self, status: ConsumerStatus) -> None:
        self._status = status
        # setting expiry must be set after setting status
        self._status_cache_expiry = monotonic() + self._status_expiry_duration
