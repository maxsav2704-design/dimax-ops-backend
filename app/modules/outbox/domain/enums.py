from enum import Enum


class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class OutboxChannel(str, Enum):
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
