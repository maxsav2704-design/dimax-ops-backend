from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectCreateBody(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    address: str = Field(min_length=2, max_length=400)
    developer_company: str | None = Field(default=None, max_length=200)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=40)
    contact_email: str | None = Field(default=None, max_length=255)


class ProjectUpdateBody(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=400)
    developer_company: str | None = Field(default=None, max_length=200)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=40)
    contact_email: str | None = Field(default=None, max_length=255)


class ProjectListItem(BaseModel):
    id: UUID
    name: str
    address: str
    status: str


class ProjectListResponse(BaseModel):
    items: list[ProjectListItem]


class ProjectCreateResponse(BaseModel):
    id: UUID


class DoorImportRow(BaseModel):
    door_type_id: UUID
    unit_label: str = Field(min_length=1, max_length=120)
    our_price: Decimal = Field(ge=0)
    order_number: str | None = Field(default=None, max_length=80)
    house_number: str | None = Field(default=None, max_length=40)
    floor_label: str | None = Field(default=None, max_length=40)
    apartment_number: str | None = Field(default=None, max_length=40)
    location_code: str | None = Field(default=None, max_length=80)
    door_marking: str | None = Field(default=None, max_length=120)


class ImportDoorsBody(BaseModel):
    rows: list[DoorImportRow] = Field(min_length=1, max_length=5000)


class ImportDoorsResponse(BaseModel):
    imported: int


class ImportDoorsFromFileBody(BaseModel):
    filename: str = Field(min_length=3, max_length=255)
    content_base64: str = Field(min_length=1)
    default_door_type_id: UUID | None = None
    default_our_price: Decimal = Field(default=Decimal("0"), ge=0)
    delimiter: str | None = Field(default=None, max_length=3)
    mapping_profile: str = Field(
        default="auto_v1",
        pattern=r"^(auto_v1|factory_he_v1|factory_ru_v1|generic_en_v1)$",
    )
    strict_required_fields: bool | None = None
    create_missing_door_types: bool = False
    analyze_only: bool = False


class ImportDoorsFromFileErrorDTO(BaseModel):
    row: int
    message: str


class ImportRequiredFieldDiagnosticsDTO(BaseModel):
    field_key: str
    display_name: str
    found: bool
    matched_columns: list[str] = Field(default_factory=list)


class ImportDataSummaryDTO(BaseModel):
    source_rows: int = 0
    prepared_rows: int = 0
    rows_with_errors: int = 0
    duplicate_rows_skipped: int = 0
    unique_order_numbers: int = 0
    unique_houses: int = 0
    unique_floors: int = 0
    unique_apartments: int = 0
    unique_locations: int = 0
    unique_markings: int = 0


class ImportPreviewGroupDTO(BaseModel):
    order_number: str | None = None
    house_number: str | None = None
    floor_label: str | None = None
    apartment_number: str | None = None
    door_marking: str | None = None
    door_count: int = 0
    location_codes: list[str] = Field(default_factory=list)


class ImportColumnsDiagnosticsDTO(BaseModel):
    required_fields: list[ImportRequiredFieldDiagnosticsDTO] = Field(default_factory=list)
    recognized_columns: list[str] = Field(default_factory=list)
    unmapped_columns: list[str] = Field(default_factory=list)
    mapping_profile: str | None = None
    strict_required_fields: bool | None = None
    missing_required_fields: list[str] = Field(default_factory=list)
    data_summary: ImportDataSummaryDTO | None = None
    preview_groups: list[ImportPreviewGroupDTO] = Field(default_factory=list)


class ImportDoorsFromFileResponse(BaseModel):
    parsed_rows: int
    prepared_rows: int
    imported: int
    skipped: int
    errors: list[ImportDoorsFromFileErrorDTO]
    diagnostics: ImportColumnsDiagnosticsDTO | None = None
    mode: str = "import"
    would_import: int = 0
    would_skip: int = 0
    idempotency_hit: bool = False


class ImportMappingProfileDTO(BaseModel):
    code: str
    name: str
    description: str
    preferred_delimiter: str | None = None


class ImportMappingProfilesResponse(BaseModel):
    default_code: str
    items: list[ImportMappingProfileDTO]


class ProjectImportRunItemDTO(BaseModel):
    id: UUID
    created_at: datetime
    mode: str
    status: str
    source_filename: str | None
    mapping_profile: str | None
    parsed_rows: int
    prepared_rows: int
    imported: int
    skipped: int
    errors_count: int
    idempotency_hit: bool
    retry_available: bool
    last_error: str | None = None


class ProjectImportRunsResponse(BaseModel):
    items: list[ProjectImportRunItemDTO]


class ProjectImportRunDetailsDTO(ProjectImportRunItemDTO):
    errors: list[ImportDoorsFromFileErrorDTO] = Field(default_factory=list)
    diagnostics: ImportColumnsDiagnosticsDTO | None = None
    would_import: int = 0
    would_skip: int = 0


class ProjectBulkImportReconcileBody(BaseModel):
    project_ids: list[UUID] = Field(min_length=1, max_length=100)
    only_failed_runs: bool = False


class ProjectLatestImportReviewItemDTO(BaseModel):
    project_id: UUID
    project_name: str
    source_run_id: UUID | None = None
    mode: str | None = None
    status: str
    source_filename: str | None = None
    mapping_profile: str | None = None
    parsed_rows: int = 0
    prepared_rows: int = 0
    imported: int = 0
    skipped: int = 0
    errors_count: int = 0
    last_error: str | None = None
    retry_available: bool = False


class ProjectLatestImportReviewResponse(BaseModel):
    items: list[ProjectLatestImportReviewItemDTO]
    total_projects: int
    reviewable_projects: int
    failed_or_partial_projects: int
    skipped_projects: int


class ProjectBulkImportReconcileItemDTO(BaseModel):
    project_id: UUID
    source_run_id: UUID | None = None
    status: str
    imported: int
    skipped: int
    errors_count: int
    last_error: str | None = None


class ProjectBulkImportReconcileResponse(BaseModel):
    items: list[ProjectBulkImportReconcileItemDTO]
    total_projects: int
    successful_projects: int
    failed_projects: int
    skipped_projects: int


class FailedImportRunQueueItemDTO(BaseModel):
    run_id: UUID
    project_id: UUID
    project_name: str
    created_at: datetime
    mode: str
    status: str
    source_filename: str | None
    mapping_profile: str | None
    parsed_rows: int
    prepared_rows: int
    imported: int
    skipped: int
    errors_count: int
    last_error: str | None = None
    retry_available: bool


class FailedImportRunsQueueResponse(BaseModel):
    items: list[FailedImportRunQueueItemDTO]
    total: int
    limit: int
    offset: int


class RetryFailedImportRunsBody(BaseModel):
    run_ids: list[UUID] = Field(min_length=1, max_length=100)


class RetryFailedImportRunItemDTO(BaseModel):
    run_id: UUID
    project_id: UUID | None = None
    status: str
    imported: int
    skipped: int
    errors_count: int
    last_error: str | None = None


class RetryFailedImportRunsResponse(BaseModel):
    items: list[RetryFailedImportRunItemDTO]
    total_runs: int
    successful_runs: int
    failed_runs: int
    skipped_runs: int


class AssignInstallerBody(BaseModel):
    installer_id: UUID


class DoorDTO(BaseModel):
    id: UUID
    unit_label: str
    door_type_id: UUID
    our_price: Decimal
    order_number: str | None
    house_number: str | None
    floor_label: str | None
    apartment_number: str | None
    location_code: str | None
    door_marking: str | None
    status: str
    installer_id: UUID | None
    reason_id: UUID | None
    comment: str | None
    is_locked: bool


class LayoutDoorDTO(BaseModel):
    id: UUID
    unit_label: str
    door_type_id: UUID
    order_number: str | None
    apartment_number: str | None
    location_code: str | None
    door_marking: str | None
    status: str
    installer_id: UUID | None


class ProjectDoorLayoutBucketDTO(BaseModel):
    order_number: str | None
    house_number: str | None
    floor_label: str | None
    location_code: str | None
    door_marking: str | None
    total: int
    status_breakdown: dict[str, int]
    doors: list[LayoutDoorDTO]


class ProjectDoorsLayoutResponse(BaseModel):
    project_id: UUID
    total_doors: int
    buckets: list[ProjectDoorLayoutBucketDTO]


class IssueDTO(BaseModel):
    id: UUID
    door_id: UUID
    status: str
    title: str | None
    details: str | None


class ProjectDetailsResponse(BaseModel):
    id: UUID
    name: str
    address: str
    status: str
    developer_company: str | None
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None
    doors: list[DoorDTO]
    issues_open: list[IssueDTO]


class OkResponse(BaseModel):
    ok: bool = True
