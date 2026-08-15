from enum import Enum


class ProjectStatus(str, Enum):
    OK = "OK"
    PROBLEM = "PROBLEM"


class ProjectLifecycleStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProjectHealthStatus(str, Enum):
    NORMAL = "NORMAL"
    AT_RISK = "AT_RISK"
    BLOCKED = "BLOCKED"
