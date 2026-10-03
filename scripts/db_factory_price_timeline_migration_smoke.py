"""Verify the price timeline only in the guarded disposable factory migration database."""
import os
from decimal import Decimal
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from scripts.db_factory_price_approval_migration_smoke import main as verify_approvals


def main():
    if os.getenv("DIMAX_PRICE_TIMELINE_MIGRATION") != "1":
        raise RuntimeError("Explicit factory timeline migration check required")
    # Includes the exact isolated host/name, empty-DB and explicit test-environment guards.
    verify_approvals()
    from app.modules.identity.infrastructure.models import AdminProfileORM
    from app.modules.rates.application.approval_dto import ConfirmApproval, IssueApproval
    from app.modules.rates.application.approval_service import FactoryPriceApprovalService
    from app.modules.rates.application.price_list_dto import CreatePriceList
    from app.modules.rates.application.price_lists_service import FactoryPriceListsService
    from app.modules.rates.application.timeline_dto import ActivatePriceVersion
    from app.modules.rates.application.timeline_service import FactoryPriceTimelineService
    from app.modules.rates.infrastructure.price_list_models import FactoryPriceListORM
    from app.modules.rates.infrastructure.models import InstallerRateORM
    from app.shared.infrastructure.db.base import Base, utcnow
    from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork

    engine = create_engine(os.environ["DATABASE_URL"])
    config = Config("alembic.ini")
    tables = [name for name in inspect(engine).get_table_names() if name != "alembic_version"]
    def snapshot(names):
        with engine.connect() as connection:
            return {name: connection.execute(text(
                f'SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), \'[]\'::jsonb) FROM "{name}" t'
            )).scalar_one() for name in names}
    before = snapshot(tables)
    command.upgrade(config, "0065_factory_price_timeline")
    assert snapshot(tables) == before
    def include_object(obj, name, type_, reflected, compare_to):
        if type_ == "table":
            return name in {"factory_price_activations", "factory_price_approvals"}
        return obj.table.name == "factory_price_activations" or (
            type_ == "unique_constraint" and name == "uq_factory_approvals_tenant_list_id")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM factory_price_activations")).scalar_one() == 0
        context = MigrationContext.configure(connection, opts={"include_object": include_object})
        assert compare_metadata(context, Base.metadata) == []
    command.downgrade(config, "0064_factory_price_approval")
    assert "factory_price_activations" not in inspect(engine).get_table_names()
    assert snapshot(tables) == before
    command.upgrade(config, "0065_factory_price_timeline")
    assert snapshot(tables) == before

    business_tables = [name for name in tables if not name.startswith("factory_price_")
                       and name not in {"audit_logs", "admin_profiles"}]
    business_before = snapshot(business_tables)
    with Session(engine) as session:
        draft = session.scalar(select(FactoryPriceListORM))
        rate = session.scalar(select(InstallerRateORM))
        company_id, actor, door_type_id = draft.company_id, draft.created_by, rate.door_type_id
        session.add(AdminProfileORM(company_id=company_id, user_id=actor, admin_scope="OWNER", can_view_rates=True))
        session.commit()
    with SqlAlchemyUnitOfWork() as uow:
        version = FactoryPriceListsService.create(uow, company_id=company_id, actor_user_id=actor,
            body=CreatePriceList(request_id=uuid4(), expected_latest_version=1, reason="QA factory offer",
                agreement_reference="QA agreement", items=[{"kind": "DOOR", "target_id": door_type_id,
                                                             "installer_price": Decimal("300")}]))
    with SqlAlchemyUnitOfWork() as uow:
        issued = FactoryPriceApprovalService.issue(uow, company_id=company_id, actor_user_id=actor,
            price_list_id=version.id, body=IssueApproval(factory_name="QA Factory", recipient_name="QA Recipient",
                                                        recipient_email="qa@example.com"))
    with SqlAlchemyUnitOfWork() as uow:
        token = issued.confirmation_url.split("#")[1]
        preview = FactoryPriceApprovalService.preview(uow, token=token)
        FactoryPriceApprovalService.confirm(uow, body=ConfirmApproval(token=token, expected_version=version.version,
            snapshot_hash=preview.snapshot_hash, signer_name="QA Recipient", accepted=True))
    with SqlAlchemyUnitOfWork() as uow:
        FactoryPriceTimelineService.activate(uow, company_id=company_id, actor_user_id=actor, price_list_id=version.id,
            body=ActivatePriceVersion(request_id=uuid4(), expected_active_price_list_id=None,
                                      reason="QA reviewed transition", reviewed_transition=True))
    with SqlAlchemyUnitOfWork() as uow:
        price = FactoryPriceTimelineService.quote(uow, company_id=company_id, kind="DOOR", target_id=door_type_id,
                                                  performed_at=utcnow())
        assert price.amount(Decimal("1")) == Decimal("300")
    assert snapshot(business_tables) == business_before
    all_tables = tables + ["factory_price_activations"]
    with_history = snapshot(all_tables)
    try:
        command.downgrade(config, "0064_factory_price_approval")
    except RuntimeError as error:
        assert "effective factory price history exists" in str(error)
    else:
        raise AssertionError("Downgrade discarded effective price history")
    assert snapshot(all_tables) == with_history
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0065_factory_price_timeline"
    engine.dispose()
    print("PASS: timeline upgrade, rollback, metadata, activation/quote, legacy business snapshots and history protection")


if __name__ == "__main__":
    main()
