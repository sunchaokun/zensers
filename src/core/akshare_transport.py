"""
Akshare Transport Patch
========================

Fixes requests proxy incompatibility with push2.eastmoney.com.

Root cause: requests library's HTTPS CONNECT proxy handling fails for
eastmoney push2 subdomains (returns ProxyError/RemoteDisconnected),
while httpx with the same proxy works fine (though occasionally flaky).

Solution: monkey-patch requests.Session.get to route push2.eastmoney.com
requests through httpx with retry when a proxy is configured.
"""

import logging
import os
import re
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_PATCHED = False
_PUSH2_PATTERN = re.compile(r"\.push2\.eastmoney\.com$")
_MAX_RETRIES = 3


def patch_akshare_requests(proxy_url: Optional[str] = None) -> bool:
    """
    Monkey-patch requests.Session.get to use httpx for push2.eastmoney.com.

    Call once at application startup, AFTER settings are loaded.

    Args:
        proxy_url: Proxy URL (e.g. 'http://127.0.0.1:7897').
                   If None, reads from settings.yaml or env vars.

    Returns:
        True if patch was applied successfully.
    """
    global _PATCHED
    if _PATCHED:
        return True

    if not proxy_url:
        proxy_url = _detect_proxy()
    if not proxy_url:
        logger.info("AkshareTransport: no proxy configured, patch not needed")
        return False

    try:
        import httpx
        import requests
    except ImportError:
        logger.warning("AkshareTransport: httpx not installed, cannot patch")
        return False

    _original_get = requests.Session.get

    class _PatchedSession(requests.Session):
        def get(self, url: str, **kwargs: Any) -> Any:
            parsed = urlparse(url)
            if _PUSH2_PATTERN.search(parsed.netloc):
                return self._get_via_httpx(url, proxy_url, **kwargs)
            return _original_get(self, url, **kwargs)

        @staticmethod
        def _get_via_httpx(url: str, proxy: str, **kwargs: Any) -> Any:
            parsed = urlparse(url)
            params = kwargs.get("params")
            timeout_val = kwargs.get("timeout", 15)
            timeout_val = timeout_val if isinstance(timeout_val, (int, float)) else 15

            last_err = None
            for attempt in range(_MAX_RETRIES):
                try:
                    with httpx.Client(
                        proxy=proxy,
                        verify=False,
                        timeout=timeout_val,
                        follow_redirects=True,
                    ) as client:
                        resp = client.get(url, params=params)
                        resp.raise_for_status()

                    fake_resp = requests.Response()
                    fake_resp.status_code = resp.status_code
                    fake_resp._content = resp.content
                    fake_resp.encoding = resp.encoding or "utf-8"
                    fake_resp.url = str(resp.url)
                    return fake_resp
                except Exception as e:
                    last_err = e
                    if attempt < _MAX_RETRIES - 1:
                        time.sleep(1.0 * (attempt + 1))

            logger.warning(f"AkshareTransport: httpx failed after {_MAX_RETRIES} retries for {parsed.netloc}: {last_err}")
            raise requests.ConnectionError(
                f"httpx failed for {parsed.netloc} after {_MAX_RETRIES} retries: {last_err}"
            )

    requests.Session = _PatchedSession
    _PATCHED = True
    logger.info(f"AkshareTransport: patched requests.Session for push2.eastmoney.com via httpx (proxy={proxy_url})")
    return True


def _detect_proxy() -> Optional[str]:
    for env_key in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        val = os.environ.get(env_key)
        if val:
            return val
    try:
        import yaml
        from pathlib import Path
        for candidate in (
            Path("config/settings.yaml"),
            Path(__file__).resolve().parent.parent.parent / "config" / "settings.yaml",
        ):
            if candidate.exists():
                with open(candidate, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                val = cfg.get("proxy", {}).get("url", "")
                if val:
                    return str(val)
                val = cfg.get("search", {}).get("proxy", "")
                if val:
                    return str(val)
    except Exception:
        pass

    try:
        from urllib.request import getproxies
        system_proxies = getproxies()
        for key in ("https", "http"):
            if key in system_proxies:
                return system_proxies[key]
    except Exception:
        pass

    return None
