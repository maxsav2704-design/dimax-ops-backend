from enum import Enum


class JournalStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"  # публичная ссылка включена
    ARCHIVED = "ARCHIVED"  # после подписи/закрытия


class JournalDeliveryStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
