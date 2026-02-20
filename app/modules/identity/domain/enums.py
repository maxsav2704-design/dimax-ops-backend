from enum import Enum


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    INSTALLER = "INSTALLER"
