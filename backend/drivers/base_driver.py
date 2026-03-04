from abc import ABC, abstractmethod

class BaseNVMeDriver(ABC):
    """Abstract interface for NVMe backends (nvme-cli, SPDK, etc.)"""

    def __init__(self, device: str):
        self.device = device

    @abstractmethod
    def run_command(self, args: list) -> dict:
        """Run a driver-specific command. Returns {'stdout': ..., 'stderr': ..., 'returncode': ...}"""
        pass

    @abstractmethod
    def get_fdp_status(self) -> dict:
        pass

    @abstractmethod
    def get_fdp_configs(self) -> dict:
        pass

    @abstractmethod
    def get_fdp_placement_ids(self, namespace: int = 1) -> dict:
        pass

    @abstractmethod
    def get_reclaim_unit_handle_status(self, namespace: int = 1) -> dict:
        pass

    @abstractmethod
    def get_fdp_events(self, namespace: int = 1) -> dict:
        pass

    @property
    @abstractmethod
    def driver_name(self) -> str:
        pass