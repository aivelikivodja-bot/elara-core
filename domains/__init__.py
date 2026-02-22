# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)

"""Domain adapter registry."""

from domains.base import DomainAdapter

_ADAPTERS = {
    "medical": "domains.medical.MedicalAdapter",
    "industrial": "domains.industrial.IndustrialAdapter",
    "companion": "domains.companion.CompanionAdapter",
    "education": "domains.education.EducationAdapter",
    "finance": "domains.finance.FinanceAdapter",
    "defense": "domains.defense.DefenseAdapter",
    "agriculture": "domains.agriculture.AgricultureAdapter",
}

_cache = {}


def get_adapter(domain: str) -> DomainAdapter:
    """Get a domain adapter by name. Cached after first load."""
    if domain in _cache:
        return _cache[domain]

    if domain not in _ADAPTERS:
        raise ValueError(f"Unknown domain: {domain}. Available: {list(_ADAPTERS.keys())}")

    module_path, class_name = _ADAPTERS[domain].rsplit(".", 1)
    import importlib
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    instance = cls()
    _cache[domain] = instance
    return instance


def list_domains() -> list:
    """List all available domain names."""
    return list(_ADAPTERS.keys())
