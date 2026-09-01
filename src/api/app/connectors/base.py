from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID


@dataclass
class NormalizedCost:
    usage_date: date
    account_id: str
    account_name: str
    resource_id: str
    resource_name: str
    resource_type: str
    service: str
    category: str
    meter: str
    region: str
    resource_group: str = ""
    org_id: str = ""
    org_name: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    cost: float = 0
    amortized_cost: float = 0
    currency: str = "GBP"
    usage_quantity: float = 0
    usage_unit: str = ""


class Connector(ABC):
    provider: str

    @abstractmethod
    async def ingest(self, connection_id: UUID, config: dict[str, Any], secret: str | None) -> list[NormalizedCost]:
        """Pull cost rows for one connected cloud instance."""

    async def test(self, config: dict[str, Any], secret: str | None) -> str:
        """Validate credentials. Return a short success message or raise."""
        return "Configuration saved."
