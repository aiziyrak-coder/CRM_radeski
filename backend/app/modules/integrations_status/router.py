from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.deps import SessionDep, client_ip, require_roles
from app.modules.audit import service as audit
from app.modules.integrations_status import service
from app.modules.users.models import Role, User

# under /system (not /integrations: that prefix belongs to the providers' webhooks)
router = APIRouter(prefix="/system/integrations", tags=["system"])
Admin = Annotated[User, Depends(require_roles(Role.ADMIN))]


@router.get("")
async def integrations(session: SessionDep, _: Admin) -> list[dict[str, Any]]:
    """TZ 3: the admin sees every integration, whether it works and what it still needs."""
    return await service.status(session)


@router.post("/{key}/test")
async def test_integration(
    key: str, request: Request, session: SessionDep, user: Admin
) -> dict[str, Any]:
    """A read-only check with the real provider (no messages, no AI spend)."""
    if key not in service.TESTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown_integration")
    result = await service.run_test(key)
    audit.record(
        session, "integration.test", user_id=user.id, entity="integration", entity_id=key,
        after={"ok": result["ok"], "error": result.get("error")}, ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return result
