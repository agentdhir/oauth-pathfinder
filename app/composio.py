"""Optional: ask Composio's toolkit API whether a Composio-managed OAuth app exists for this app.
Docs: https://next.docs.composio.dev/toolkits/managed-auth ("A toolkit that lists managed auth schemes in the
response has managed auth. An empty list means you need to supply your own credentials.")"""
import os, re
import httpx

CALLBACK_URL = "https://backend.composio.dev/api/v3/toolkits/auth/callback"


def _find_managed(obj):
    """The response schema isn't documented in detail; find any key mentioning managed auth schemes."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if "managed" in k.lower() and isinstance(v, list):
                return v
            found = _find_managed(v)
            if found is not None:
                return found
    return None


def managed_status(app_name: str) -> dict | None:
    key = os.getenv("COMPOSIO_API_KEY")
    if not key:
        return None
    for slug in dict.fromkeys([re.sub(r"[^a-z0-9]", "", app_name.lower()), re.sub(r"[^a-z0-9]+", "_", app_name.lower()).strip("_")]):
        try:
            r = httpx.get(f"https://backend.composio.dev/api/v3.1/toolkits/{slug}", headers={"x-api-key": key}, timeout=15)
        except Exception:
            return None
        if r.status_code == 200:
            schemes = _find_managed(r.json())
            return {"toolkit": slug, "managed": bool(schemes), "managed_schemes": schemes or [], "callback_url": CALLBACK_URL}
    return {"toolkit": None, "managed": False, "managed_schemes": [], "callback_url": CALLBACK_URL, "note": "No matching Composio toolkit found"}
