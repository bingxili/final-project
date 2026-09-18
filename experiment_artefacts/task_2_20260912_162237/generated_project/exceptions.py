from typing import Optional, List


class DependencyCycleError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class BlockedCompletionError(Exception):
    def __init__(self, message: str, blocking_dependencies: Optional[list[str]] = None) -> None:
        super().__init__(message)
        self.blocking_dependencies = list(blocking_dependencies) if blocking_dependencies else []


class DeletionBlockedError(Exception):
    def __init__(self, message: str, dependents: Optional[list[str]] = None) -> None:
        super().__init__(message)
        self.dependents = list(dependents) if dependents else []
