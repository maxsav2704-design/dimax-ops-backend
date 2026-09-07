from enum import Enum


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    INSTALLER = "INSTALLER"


class AdminScope(str, Enum):
    OWNER = "OWNER"
    OPERATIONS = "OPERATIONS"
    FINANCE = "FINANCE"
    VIEWER = "VIEWER"
