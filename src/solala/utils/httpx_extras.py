import threading

import httpx
from httpx import URL
# noinspection PyProtectedMember
from httpx._client import UseClientDefault, USE_CLIENT_DEFAULT
# noinspection PyProtectedMember
from httpx._types import QueryParamTypes, HeaderTypes, CookieTypes, AuthTypes, TimeoutTypes, RequestExtensions


class AsyncClients:
    """
    Note, we assume maximum one asyncio event loop per thread.
    """

    def __init__(self) -> None:
        self._clients: dict[int, httpx.AsyncClient] = {}
        self._lock = threading.Lock()

    def get(self) -> httpx.AsyncClient:
        with self._lock:
            thread_id = threading.get_ident()
            client = self._clients.get(thread_id)
            if client is None:
                self._clients[thread_id] = client = httpx.AsyncClient()
            return client

    async def close(self) -> None:
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
