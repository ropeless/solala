import threading

import httpx
from httpx import URL
# noinspection PyProtectedMember
from httpx._client import UseClientDefault, USE_CLIENT_DEFAULT
# noinspection PyProtectedMember
from httpx._types import QueryParamTypes, HeaderTypes, CookieTypes, AuthTypes, TimeoutTypes, RequestExtensions


class AsyncClients:
    """
    Manage reusable HTTPX asynchronous clients keyed by thread identity.

    Each thread gets its own client, created on first access. This relies on
    the application using at most one asyncio event loop per thread. Clients
    remain cached until `close()` is called.
    """

    def __init__(self) -> None:
        self._clients: dict[int, httpx.AsyncClient] = {}
        self._lock = threading.Lock()

    def get(self) -> httpx.AsyncClient:
        """
        Get or create the asynchronous HTTP client for the current thread.

        Returns:
            The cached client associated with the current thread.
        """
        with self._lock:
            thread_id = threading.get_ident()
            client = self._clients.get(thread_id)
            if client is None:
                self._clients[thread_id] = client = httpx.AsyncClient()
            return client

    async def close(self) -> None:
        """
        Close all cached clients and clear the client cache.

        Call this during shutdown when no requests are in progress. The caller
        is responsible for ensuring clients are closed in a suitable event-loop
        context.
        """
        with self._lock:
            for client in self._clients.values():
                await client.aclose()
            self._clients.clear()


ASYNC_CLIENTS = AsyncClients()


async def async_get(
        url: URL | str,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
) -> httpx.Response:
    """
    Send an asynchronous GET request using the current thread's shared client.

    Request options are passed through to `httpx.AsyncClient.get()`.

    Args:
        url: URL to request.
        params: Optional query parameters.
        headers: Optional request headers.
        cookies: Optional request cookies.
        auth: Authentication configuration or the client default.
        follow_redirects: Whether to follow redirects or use the client default.
        timeout: Request timeout configuration or the client default.
        extensions: Optional HTTPX request extensions.

    Returns:
        The HTTP response.

    Raises:
        httpx.HTTPError: If HTTPX encounters a request or transport error.
    """
    return await ASYNC_CLIENTS.get().get(
        url,
        params=params,
        headers=headers,
        cookies=cookies,
        auth=auth,
        follow_redirects=follow_redirects,
        timeout=timeout,
        extensions=extensions,
    )
