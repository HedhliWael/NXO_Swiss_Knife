from typing import Dict, Type

from .base import BaseVendorParser
from .fortinet import FortinetParser
from .paloalto import PaloAltoParser


_REGISTRY: Dict[str, Type[BaseVendorParser]] = {
    "fortinet": FortinetParser,
    "paloalto": PaloAltoParser,
}


def register_vendor(vendor_name: str, parser_class: Type[BaseVendorParser]):
    """
    Manual registration helper.

    For a larger plugin system, this can be replaced by entry points or automatic discovery.
    """
    _REGISTRY[vendor_name.lower()] = parser_class


def get_parser(vendor: str) -> BaseVendorParser:
    key = (vendor or "").strip().lower()

    parser_class = _REGISTRY.get(key)

    if parser_class is None:
        raise ValueError(f"No parser registered for vendor '{vendor}'.")

    return parser_class()


def registered_vendors():
    return sorted(_REGISTRY.keys())
