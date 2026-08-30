"""Shared governance / compliance metadata.

Both modes - the MCP server (in its service contract) and the agent (in its
agent card) - carry the same set of labels, read from ``AIPOD_*`` environment
variables so one image is labelled differently per environment (dev vs.
regulated prod). The defaults describe this reference build: public demo data.
"""

from __future__ import annotations

import os
from typing import Any


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _csv(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def base() -> dict[str, Any]:
    """The environment-driven labels common to both modes."""

    return {
        "owner": _env("AIPOD_OWNER", "unassigned@example.com"),
        "domain": _env("AIPOD_DOMAIN", "reference/testing"),
        # PUBLIC | INTERNAL | CONFIDENTIAL | RESTRICTED - the highest class of
        # data this deployment is cleared to process.
        "dataClassification": _env("AIPOD_DATA_CLASSIFICATION", "PUBLIC"),
        "dataResidency": _env("AIPOD_DATA_RESIDENCY", "unspecified"),
        # e.g. "GDPR", "HIPAA", "SOC2", "EU-AI-Act:limited-risk"
        "regulatoryScope": _csv("AIPOD_REGULATORY_SCOPE", ""),
        "authenticationSchemes": _csv("AIPOD_AUTH_SCHEMES", "none"),
        "containsPII": _env("AIPOD_CONTAINS_PII", "false").lower() == "true",
        "auditLogging": _env("AIPOD_AUDIT_LOG", "stdout"),
        "dataRetention": _env("AIPOD_DATA_RETENTION", "none (stateless per request)"),
    }
