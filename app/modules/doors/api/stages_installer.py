from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.acl import get_current_installer_id
from app.api.v1.deps import CurrentUser, get_uow, require_installer
from app.modules.doors.api.stage_schemas import CompleteStage, DoorStagesDTO, StageCompletionResponse
from app.modules.doors.application.stages_service import WorkStagesService

router = APIRouter(prefix="/installer/doors", tags=["Installer / Work stages"])


@router.get("/{door_id}/stages", response_model=DoorStagesDTO | None)
def my_door_stages(door_id: UUID, user: CurrentUser = Depends(require_installer),
                   installer_id: UUID = Depends(get_current_installer_id), uow=Depends(get_uow)):
    with uow:
        WorkStagesService._require_enabled()
        view = WorkStagesService.door_stages(uow, company_id=user.company_id, door_id=door_id, installer_id=installer_id)
        return DoorStagesDTO(**view) if view else None


@router.post("/{door_id}/stages/{stage_code}/complete", response_model=StageCompletionResponse)
def complete_my_stage(door_id: UUID, stage_code: str, body: CompleteStage | None = None,
                      user: CurrentUser = Depends(require_installer), installer_id: UUID = Depends(get_current_installer_id),
                      uow=Depends(get_uow)):
    body = body or CompleteStage()
    with uow:
        result = WorkStagesService.complete_stage(uow, company_id=user.company_id, actor_user_id=user.id, installer_id=installer_id,
                                                  door_id=door_id, stage_code=stage_code.upper(), happened_at=body.happened_at,
                                                  source="API", request_id=body.request_id)
        uow.commit()
        return StageCompletionResponse(**result)
