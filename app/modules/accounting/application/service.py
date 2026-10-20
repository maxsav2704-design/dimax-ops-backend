import hashlib
import json
import os
from uuid import UUID, uuid4

from app.modules.accounting.application.dto import (
    CommercialLine, CommercialPriceDetail, CommercialPricePage, CommercialPriceSummary,
    ContractDraft, ContractPage, CreateCommercialPriceDraft, CreateContractDraft,
)
from app.modules.accounting.infrastructure.models import (
    CommercialContractORM, CommercialPriceItemORM, CommercialPriceVersionORM,
)
from app.modules.accounting.infrastructure.repositories import CommercialDraftRepository
from app.modules.audit.application.service import AuditService
from app.shared.domain.errors import Conflict, ForbiddenScope, NotFound, ValidationError


def _fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class CommercialDraftService:
    @staticmethod
    def _repo(uow, user) -> CommercialDraftRepository:
        repo = CommercialDraftRepository(uow.session)
        if not repo.owner_is_active(user.company_id, user.id):
            raise ForbiddenScope("Only an active OWNER may access commercial drafts")
        return repo

    @staticmethod
    def _contract(repo, user, contract_id):
        row = repo.contract(user.company_id, contract_id)
        if row is None:
            raise NotFound("Commercial contract not found")
        return row

    @staticmethod
    def _summary(row, contract):
        return CommercialPriceSummary(**{
            key: getattr(row, key) for key in (
                "id", "contract_id", "version", "status", "proposed_from",
                "reason", "agreement_reference", "created_by", "created_at",
            )
        }, is_demo=contract.is_demo)

    @classmethod
    def _detail(cls, repo, row, contract):
        return CommercialPriceDetail(
            **cls._summary(row, contract).model_dump(),
            items=[CommercialLine(
                kind=item.kind, target_id=item.door_type_id or item.addon_type_id,
                stage_code=item.stage_code, name=item.name, unit=item.unit,
                unit_price_ex_vat=item.unit_price_ex_vat,
            ) for item in repo.items(row.company_id, row.id)],
        )

    @classmethod
    def contracts(cls, uow, user, *, limit: int, offset: int) -> ContractPage:
        rows, total = cls._repo(uow, user).contracts(user.company_id, limit, offset)
        return ContractPage(items=[ContractDraft.model_validate(row) for row in rows], total=total)

    @classmethod
    def create_contract(cls, uow, user, body: CreateContractDraft) -> ContractDraft:
        repo = cls._repo(uow, user)
        if not repo.lock_company(user.company_id):
            raise ForbiddenScope("Company is inactive")
        fingerprint = _fingerprint(body.model_dump(mode="json", exclude={"request_id"}))
        existing = repo.contract_request(user.company_id, body.request_id)
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise Conflict("Request ID already belongs to different contract terms")
            return ContractDraft.model_validate(existing)
        if repo.contract_reference_exists(user.company_id, body.reference):
            raise Conflict("Contract reference already exists")
        row = CommercialContractORM(
            id=uuid4(), company_id=user.company_id, factory_name=body.factory_name,
            reference=body.reference, reason=body.reason, status="DRAFT", currency="ILS",
            # Test fixtures never become real commercial evidence.
            is_demo=os.environ.get("APP_ENV", "").lower() == "test", request_id=body.request_id,
            request_fingerprint=fingerprint, created_by=user.id,
        )
        repo.add(row)
        AuditService.add(uow, company_id=user.company_id, actor_user_id=user.id,
                         entity_type="COMMERCIAL_CONTRACT", entity_id=row.id, action="CREATE",
                         after={"status": "DRAFT", "is_demo": row.is_demo})
        return ContractDraft.model_validate(row)

    @classmethod
    def prices(cls, uow, user, contract_id: UUID, *, limit: int, offset: int):
        repo = cls._repo(uow, user)
        contract = cls._contract(repo, user, contract_id)
        rows, total, latest = repo.prices(user.company_id, contract_id, limit, offset)
        return CommercialPricePage(items=[cls._summary(row, contract) for row in rows],
                                   total=total, latest_version=latest)

    @classmethod
    def get_price(cls, uow, user, contract_id: UUID, price_id: UUID):
        repo = cls._repo(uow, user)
        contract = cls._contract(repo, user, contract_id)
        row = repo.price(user.company_id, contract_id, price_id)
        if row is None:
            raise NotFound("Commercial price version not found")
        return cls._detail(repo, row, contract)

    @classmethod
    def create_price(cls, uow, user, contract_id: UUID, body: CreateCommercialPriceDraft):
        repo = cls._repo(uow, user)
        if not repo.lock_company(user.company_id):
            raise ForbiddenScope("Company is inactive")
        contract = cls._contract(repo, user, contract_id)
        payload = body.model_dump(mode="json", exclude={"request_id", "items"})
        payload["contract_id"] = str(contract_id)
        payload["items"] = sorted([{
            "kind": line.kind, "target_id": str(line.target_id), "stage_code": line.stage_code,
            "unit_price_ex_vat": format(line.unit_price_ex_vat, ".2f"),
        } for line in body.items], key=lambda line: (line["kind"], line["target_id"], line["stage_code"]))
        fingerprint = _fingerprint(payload)
        existing = repo.price_request(user.company_id, body.request_id)
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise Conflict("Request ID already belongs to different commercial terms")
            return cls._detail(repo, existing, contract)
        _, _, latest = repo.prices(user.company_id, contract_id, 1, 0)
        if latest != body.expected_latest_version:
            raise Conflict("Commercial draft changed; reload before creating a new version",
                           meta={"latest_version": latest})
        catalogs = {
            kind: repo.catalog(user.company_id, kind, {
                line.target_id for line in body.items if line.kind == kind
            }) for kind in ("INSTALLATION", "STAGE", "ADDON")
        }
        row = CommercialPriceVersionORM(
            id=uuid4(), company_id=user.company_id, contract_id=contract_id,
            version=latest + 1, status="DRAFT", proposed_from=body.proposed_from,
            reason=body.reason, agreement_reference=body.agreement_reference,
            request_id=body.request_id, request_fingerprint=fingerprint, created_by=user.id,
        )
        repo.add(row)
        for line in body.items:
            target = catalogs[line.kind].get(line.target_id)
            if target is None:
                raise ValidationError("Work type is unavailable in this company", field="items")
            name = target.name.strip()
            unit = target.unit.strip() if line.kind == "ADDON" else "pcs"
            if not name or not unit:
                raise ValidationError("Catalog name and unit are required", field="items")
            repo.add(CommercialPriceItemORM(
                company_id=user.company_id, price_version_id=row.id, kind=line.kind,
                door_type_id=line.target_id if line.kind != "ADDON" else None,
                addon_type_id=line.target_id if line.kind == "ADDON" else None,
                stage_code=line.stage_code, name=name, unit=unit,
                unit_price_ex_vat=line.unit_price_ex_vat,
            ))
        AuditService.add(uow, company_id=user.company_id, actor_user_id=user.id,
                         entity_type="COMMERCIAL_PRICE", entity_id=row.id, action="CREATE",
                         after={"contract_id": str(contract_id), "version": row.version,
                                "status": "DRAFT", "is_demo": contract.is_demo, "items": len(body.items)})
        return cls._detail(repo, row, contract)
