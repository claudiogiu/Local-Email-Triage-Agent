from enum import Enum


class OperationStatus(str, Enum):
    """
    Enumeration defining the outcome of an evaluation or API operation.
    """

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
