from enum import Enum


class IssueStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
