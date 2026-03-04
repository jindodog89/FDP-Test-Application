from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any, Callable


class TestStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"
    ERROR = "error"


@dataclass
class TestResult:
    status: TestStatus
    message: str
    details: Any = None


class BaseTest(ABC):
    test_id: str = ""
    name: str = ""
    description: str = ""
    category: str = "General"
    tags: list = field(default_factory=list)

    @abstractmethod
    def run(self, driver, log: Callable[[str], None]) -> TestResult:
        """Execute the test. Call log() to emit real-time messages."""
        pass

    def to_dict(self) -> dict:
        return {
            "id": self.test_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
        }

    @classmethod
    def meta(cls) -> dict:
        return {
            "id": cls.test_id,
            "name": cls.name,
            "description": cls.description,
            "category": cls.category,
            "tags": cls.tags,
        }