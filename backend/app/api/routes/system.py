"""Health, stato dei servizi e audit log."""
import asyncio
from typing import Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends

from app.api.deps import verify_api_key
from app.core import config
from app.security import audit_log

router = APIRouter(tags=["system"])


@router.get("/v1/health")
async def health():
    return {"status": "ok"}

@router.get("/v1/status", dependencies=[Depends(verify_api_key)])
async def status():
    """Health check aggregato dei servizi esterni (Fase 1.4). Mai bloccante."""
    import httpx

    from app.llm.providers import list_providers

    def _origin(url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    async def _ping(name: str, url: str, headers: dict = None):
        try:
            async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
                res = await client.get(url, headers=headers)
                return {"name": name, "url": url, "ok": res.status_code == 200, "status_code": res.status_code}
        except Exception as e:
            return {"name": name, "url": url, "ok": False, "error": str(e)[:120]}

    letta_headers = {"Authorization": f"Bearer {config.LETTA_API_KEY}"} if config.LETTA_API_KEY else {}
    results = await asyncio.gather(
        _ping("llamacpp", f"{config.LLAMA_CPP_URL.rstrip('/')}/models"),
        _ping("metamcp", _origin(config.METAMCP_URL)),
        _ping("letta", f"{config.LETTA_URL.rstrip('/')}/v1/agents/", headers=letta_headers),
        return_exceptions=True,
    )
    services = [r for r in results if isinstance(r, dict)]
    providers_status = list_providers()
    return {
        "status": "ok" if all(s["ok"] for s in services) else "degraded",
        "services": services,
        "providers": providers_status,
    }


@router.get("/v1/audit", dependencies=[Depends(verify_api_key)])
async def get_audit_log(limit: int = 100, thread_id: Optional[str] = None):
    """Restituisce le ultime voci dell'audit log dei tool call (Fase 0.4)."""
    limit = max(1, min(limit, 500))
    return {"entries": audit_log.get_recent(limit=limit, thread_id=thread_id)}
