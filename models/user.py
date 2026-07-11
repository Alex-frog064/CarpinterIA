from enum import Enum


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    CUSTOMER = "CUSTOMER"


class ActivityAction(str, Enum):
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    SEND_MESSAGE = "SEND_MESSAGE"
    CREATE_ORDER = "CREATE_ORDER"
    CONFIRM_ORDER = "CONFIRM_ORDER"
    CANCEL_ORDER = "CANCEL_ORDER"
