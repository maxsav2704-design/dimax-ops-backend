from enum import Enum


class IssueStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class IssuePriority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class IssueWorkflowState(str, Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
