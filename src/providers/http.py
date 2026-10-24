"""Small HTTP helper shared by the providers: timeouts, bounded retries,
status mapping, and removal of secrets from every error message."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

from .. import config
from ..utils import APIError, AuthenticationError, RateLimitError, get_logger

logger = get_logger()
RETRYABLE = {500, 502, 503, 504}


def scrub(text: Any) -> str:
    """Replace every configured secret in ``text`` with ``***``."""
    out = str(text)
    for secret in config.secret_values():
        out = out.replace(secret, "***")
    import re
    out = re.sub(r"((?:access_key|token|api_key)=)[^&\s'\")]+", r"\1***", out)
    # FlightAPI puts the key in the URL path: .../onewaytrip/<KEY>/LHR/...
    return re.sub(r"(flightapi\.io/[A-Za-z_]+/)[^/\s'\")?]+", r"\1***", out)


def get_json(url: str, params: Optional[Dict[str, Any]] = None,
             headers: Optional[Dict[str, str]] = None, timeout: Optional[int] = None,
             retries: Optional[int] = None, provider: str = "API",
             status_hints: Optional[Dict[int, str]] = None) -> Any:
    """GET ``url`` and return decoded JSON.

    Retries timeouts, connection errors and HTTP 5xx with exponential
    back-off. 401/403 -> AuthenticationError, 429 -> RateLimitError, other
    problems -> APIError. Secrets never appear in the raised message.
    """
    timeout = timeout or config.REQUEST_TIMEOUT
    retries = config.MAX_RETRIES if retries is None else retries
    last = ""
    for attempt in range(retries + 1):
        try:
            # short connect timeout: a dead network fails in seconds, a slow answer still gets the full read timeout
            resp = requests.get(url, params=params, headers=headers, timeout=(min(5, timeout), timeout))
        except requests.exceptions.Timeout:
            last = f"timed out after {timeout}s"
        except requests.exceptions.ConnectionError:
            last = "could not connect (check your internet connection)"
        except requests.exceptions.RequestException as exc:
            raise APIError(f"{provider} request failed: {scrub(exc)}")
        else:
            code = resp.status_code
            if code in RETRYABLE:
                last = f"server error HTTP {code}"
            elif code in (401, 403):
                raise AuthenticationError(
                    f"{provider} rejected the credentials (HTTP {code}). Check the key in Settings.")
            elif code == 429:
                raise RateLimitError(f"{provider} rate limit reached (HTTP 429). Try again later.")
            elif code >= 400:
                hint = (status_hints or {}).get(code)
                raise APIError(f"{provider} returned HTTP {code}." + (f" {hint}" if hint else ""))
            else:
                body = getattr(resp, "content", b"") or getattr(resp, "text", "")
                if not body:
                    raise APIError(f"{provider} returned an empty response.")
                try:
                    return resp.json()
                except ValueError:
                    raise APIError(f"{provider} returned a response that is not valid JSON.")
        if attempt < retries:
            logger.warning("%s transient problem (%s); retry %d/%d", provider, last, attempt + 1, retries)
            time.sleep(config.RETRY_BACKOFF_SECONDS * (2 ** attempt))
    raise APIError(f"{provider} request failed after {retries + 1} attempts: {last}.")
