from enum import Enum


class DoorStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    INSTALLED = "INSTALLED"
    ISSUE_OPEN = "ISSUE_OPEN"
    LOCKED = "LOCKED"
    NOT_INSTALLED = "NOT_INSTALLED"
    CANCELLED = "CANCELLED"
