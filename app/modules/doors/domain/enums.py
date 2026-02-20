from enum import Enum


class DoorStatus(str, Enum):
    INSTALLED = "INSTALLED"
    NOT_INSTALLED = "NOT_INSTALLED"
