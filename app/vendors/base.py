from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ParsedConfig:
    vendor: str
    objects: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class BaseVendorParser(ABC):
    """
    All vendor parsers must implement this interface.

    The core application only depends on BaseVendorParser and the parser factory.
    """

    vendor_name: str = ""
    supported_types: tuple = ()

    @abstractmethod
    def parse_config(
        self,
        raw_data: str,
        selected_types: Optional[List[str]] = None,
    ) -> ParsedConfig:
        """
        Parse raw vendor configuration into normalized Swiss Knife objects.
        """
        raise NotImplementedError

    @abstractmethod
    def generate_config(
        self,
        objects: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
        format: Optional[str] = None,
    ) -> str:
        """
        Generate vendor-specific configuration text from normalized Swiss Knife objects.

        ``format`` is an optional output flavor (e.g. ``xml`` or ``set`` for
        Palo Alto); vendors without alternative flavors ignore it.
        """
        raise NotImplementedError

    def fetch_config(self, firewall) -> str:
        """
        Optional method for pulling configuration directly from a live firewall.
        """
        raise NotImplementedError
