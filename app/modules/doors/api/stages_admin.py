from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.v1.deps import CurrentUser, get_uow, require_admin
from app.modules.doors.api.stage_schemas import (
    AdminCompleteStage, ApplyDoorPlan, AssignStage, CreateStageDefinition, CreateStagePlan, DoorStagesDTO,
    StageCompletionResponse, StageDefinitionDTO, StagePlanDTO, StagePlanItemDTO, StagePlanPage, UpdateStageDefinition,
)
from app.modules.doors.application.stages_service import WorkStagesService
from app.shared.domain.errors import ForbiddenScope

router = APIRouter(prefix="/admin", tags=["Admin / Work stages"])


def require_stage_planner(response: Response, user: CurrentUser = Depends(require_admin)) -> CurrentUser:
    """Planning who installs what is an operations decision: OWNER or OPERATIONS, never FINANCE or VIEWER."""
    if user.admin_scope not in ("OWNER", "OPERATIONS"):
        raise ForbiddenScope("Work stage planning requires OWNER or OPERATIONS")
    response.headers["Cache-Control"] = "no-store"
    return user


def _plan_dto(uow, plan) -> StagePlanDTO:
    return StagePlanDTO(id=plan.id, door_type_id=plan.door_type_id, version=plan.version, reason=plan.reason,
                        created_by=plan.created_by, created_at=plan.created_at,
                        items=[StagePlanItemDTO(stage_code=i.stage_code, required=i.required, sequence=i.sequence)
                               for i in WorkStagesService.plan_items(uow.session, plan.id)])


@router.get("/work-stages", response_model=list[StageDefinitionDTO])
def list_stages(user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    with uow:
        return [StageDefinitionDTO.model_validate(row) for row in WorkStagesService.definitions(uow, user.company_id)]


@router.post("/work-stages", response_model=StageDefinitionDTO, status_code=201)
def create_stage(body: CreateStageDefinition, user: CurrentUser = Depends(require_stage_planner), uow=Depends(get_uow)):
    with uow:
        row = WorkStagesService.create_definition(uow, company_id=user.company_id, actor_user_id=user.id,
                                                  code=body.code, name=body.name, sort_order=body.sort_order)
        uow.commit()
        return StageDefinitionDTO.model_validate(row)


@router.patch("/work-stages/{code}", response_model=StageDefinitionDTO)
def update_stage(code: str, body: UpdateStageDefinition, user: CurrentUser = Depends(require_stage_planner), uow=Depends(get_uow)):
    with uow:
        row = WorkStagesService.update_definition(uow, company_id=user.company_id, actor_user_id=user.id, code=code.upper(),
                                                  name=body.name, sort_order=body.sort_order, is_active=body.is_active)
        uow.commit()
        return StageDefinitionDTO.model_validate(row)


@router.get("/door-types/{door_type_id}/stage-plans", response_model=StagePlanPage)
def list_plans(door_type_id: UUID, user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    with uow:
        rows, latest = WorkStagesService.plans(uow, user.company_id, door_type_id)
        return StagePlanPage(items=[_plan_dto(uow, row) for row in rows], latest_version=latest)


@router.post("/door-types/{door_type_id}/stage-plans", response_model=StagePlanDTO, status_code=201)
def create_plan(door_type_id: UUID, body: CreateStagePlan, user: CurrentUser = Depends(require_stage_planner), uow=Depends(get_uow)):
    with uow:
        items = [type("Item", (), {"stage_code": i.stage_code.upper(), "required": i.required})() for i in body.items]
        plan = WorkStagesService.create_plan(uow, company_id=user.company_id, actor_user_id=user.id, door_type_id=door_type_id,
                                             expected_latest_version=body.expected_latest_version, reason=body.reason, items=items)
        uow.commit()
        return _plan_dto(uow, plan)


@router.get("/doors/{door_id}/stages", response_model=DoorStagesDTO | None)
def door_stages(door_id: UUID, user: CurrentUser = Depends(require_admin), uow=Depends(get_uow)):
    with uow:
        WorkStagesService._require_enabled()
        view = WorkStagesService.door_stages(uow, company_id=user.company_id, door_id=door_id)
        return DoorStagesDTO(**view) if view else None


@router.post("/doors/{door_id}/work-plan", response_model=DoorStagesDTO)
def apply_plan(door_id: UUID, body: ApplyDoorPlan, user: CurrentUser = Depends(require_stage_planner), uow=Depends(get_uow)):
    with uow:
        WorkStagesService.apply_plan(uow, company_id=user.company_id, actor_user_id=user.id, door_id=door_id, plan_id=body.plan_id)
        uow.commit()
        return DoorStagesDTO(**WorkStagesService.door_stages(uow, company_id=user.company_id, door_id=door_id))


@router.post("/doors/{door_id}/stages/{stage_code}/assign", response_model=DoorStagesDTO)
def assign_stage(door_id: UUID, stage_code: str, body: AssignStage, user: CurrentUser = Depends(require_stage_planner), uow=Depends(get_uow)):
    with uow:
        WorkStagesService.assign_stage(uow, company_id=user.company_id, actor_user_id=user.id, door_id=door_id,
                                       stage_code=stage_code.upper(), installer_id=body.installer_id)
        uow.commit()
        return DoorStagesDTO(**WorkStagesService.door_stages(uow, company_id=user.company_id, door_id=door_id))


@router.post("/doors/{door_id}/stages/{stage_code}/complete", response_model=StageCompletionResponse)
def admin_complete_stage(door_id: UUID, stage_code: str, body: AdminCompleteStage,
                         user: CurrentUser = Depends(require_stage_planner), uow=Depends(get_uow)):
    """Office records a stage done by the assigned installer (e.g. reported by phone); the installer stays the executor."""
    with uow:
        result = WorkStagesService.complete_stage(uow, company_id=user.company_id, actor_user_id=user.id, installer_id=body.installer_id,
                                                  door_id=door_id, stage_code=stage_code.upper(), happened_at=body.happened_at,
                                                  source="ADMIN", request_id=body.request_id)
        uow.commit()
        return StageCompletionResponse(**result)
