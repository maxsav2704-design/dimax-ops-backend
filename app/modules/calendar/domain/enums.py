from enum import Enum


class CalendarEventType(str, Enum):
    INSTALLATION = "installation"
    DELIVERY = "delivery"
    MEETING = "meeting"
    CONSULTATION = "consultation"
    INSPECTION = "inspection"
