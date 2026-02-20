from __future__ import annotations

from abc import ABC, abstractmethod


class AbstractUnitOfWork(ABC):
    # репозитории будут назначаться в реализации
    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc:
            self.rollback()
        else:
            self.commit()
