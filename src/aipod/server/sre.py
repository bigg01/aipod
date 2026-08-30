"""An IT-application / SRE toy estate for the ``*_service`` / ``*_incident`` tools.

A fixed service catalogue plus a small amount of **mutable** state (incidents you
open, deployments you roll back). Metrics and log lines are synthesised
deterministically from the service name, so the same query always returns the
same data without a real backend.

Every :class:`SREState` is independent - ``build_server()`` makes a fresh one, so
tools that mutate state do not leak between server instances or test runs.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["SEV1", "SEV2", "SEV3", "SEV4"]
IncidentStatus = Literal["open", "acknowledged", "mitigated", "resolved"]
DeployStatus = Literal["succeeded", "failed", "rolled_back", "in_progress"]
Health = Literal["healthy", "degraded", "down"]


class Service(BaseModel):
    """One application / service in the catalogue."""

    name: str
    tier: int = Field(description="1 = business critical, 3 = best effort", ge=1, le=3)
    team: str
    environments: list[str]
    depends_on: list[str] = Field(description="Other services this one calls")
    slo_availability: float = Field(description="Target availability %, e.g. 99.9")
    slo_latency_p99_ms: int = Field(description="Target 99th-percentile latency in ms")
    repo: str


class Metrics(BaseModel):
    requests_per_second: float
    error_rate_pct: float
    latency_p50_ms: int
    latency_p95_ms: int
    latency_p99_ms: int
    saturation_pct: float = Field(description="Busiest resource (CPU / pool) utilisation")


class HealthReport(BaseModel):
    service: str
    status: Health
    reasons: list[str]
    metrics: Metrics
    open_incident_ids: list[str]
    slo_availability: float
    slo_latency_p99_ms: int


class ErrorBudget(BaseModel):
    service: str
    window_days: int
    slo_availability: float
    budget_minutes: float = Field(description="Total downtime allowed in the window")
    consumed_minutes: float
    remaining_pct: float
    burn_rate: float = Field(description="Multiples of the sustainable rate; >1 is too fast")


class LogLine(BaseModel):
    timestamp: str
    level: str
    service: str
    message: str


class Incident(BaseModel):
    id: str
    service: str
    severity: Severity
    status: IncidentStatus
    summary: str
    opened_at: str
    updated_at: str
    notes: list[str] = []


class Deployment(BaseModel):
    id: str
    service: str
    version: str
    status: DeployStatus
    started_at: str
    can_rollback: bool


class RunbookEntry(BaseModel):
    symptom: str
    steps: list[str]


# --------------------------------------------------------------------------- #
# Static catalogue
# --------------------------------------------------------------------------- #

_SERVICES: list[Service] = [
    Service(
        name="checkout-api", tier=1, team="payments",
        environments=["prod", "staging"], depends_on=["payments-api", "inventory-worker", "auth-service"],
        slo_availability=99.95, slo_latency_p99_ms=400, repo="github.com/acme/checkout-api",
    ),
    Service(
        name="payments-api", tier=1, team="payments",
        environments=["prod", "staging"], depends_on=["auth-service"],
        slo_availability=99.99, slo_latency_p99_ms=300, repo="github.com/acme/payments-api",
    ),
    Service(
        name="web-frontend", tier=1, team="storefront",
        environments=["prod", "staging", "dev"], depends_on=["checkout-api", "auth-service"],
        slo_availability=99.9, slo_latency_p99_ms=800, repo="github.com/acme/web-frontend",
    ),
    Service(
        name="inventory-worker", tier=2, team="storefront",
        environments=["prod", "staging"], depends_on=["payments-api"],
        slo_availability=99.5, slo_latency_p99_ms=1500, repo="github.com/acme/inventory-worker",
    ),
    Service(
        name="auth-service", tier=1, team="platform",
        environments=["prod", "staging", "dev"], depends_on=[],
        slo_availability=99.99, slo_latency_p99_ms=150, repo="github.com/acme/auth-service",
    ),
    Service(
        name="notifications-worker", tier=3, team="platform",
        environments=["prod"], depends_on=["auth-service"],
        slo_availability=99.0, slo_latency_p99_ms=5000, repo="github.com/acme/notifications-worker",
    ),
]

SERVICES: dict[str, Service] = {s.name: s for s in _SERVICES}

# team -> on-call rotation (index 0 is "now")
_ONCALL: dict[str, list[str]] = {
    "payments": ["Priya Nair", "Marco Rossi", "Sam Okafor"],
    "storefront": ["Lena Weber", "Diego Alvarez"],
    "platform": ["Yuki Tanaka", "Fatima Zahra", "Tom Byrne"],
}

_RUNBOOKS: dict[str, list[RunbookEntry]] = {
    "checkout-api": [
        RunbookEntry(
            symptom="elevated 5xx",
            steps=[
                "Check payments-api health and error budget.",
                "Inspect the last deployment; roll back if it correlates.",
                "Scale the pod replicas to 2x if saturation > 80%.",
                "If payments-api is the cause, page the payments on-call.",
            ],
        ),
        RunbookEntry(
            symptom="latency spike",
            steps=[
                "Check downstream latency (payments-api, inventory-worker).",
                "Look for slow DB queries in the logs (message contains 'slow query').",
                "Enable the read-through cache flag if DB-bound.",
            ],
        ),
    ],
    "payments-api": [
        RunbookEntry(
            symptom="declined transactions",
            steps=[
                "Confirm the upstream processor status page.",
                "Check auth-service token error rate.",
                "Fail over to the secondary processor with the `processor=secondary` flag.",
            ],
        ),
    ],
    "auth-service": [
        RunbookEntry(
            symptom="token validation errors",
            steps=[
                "Check for a recent key-rotation event.",
                "Verify clock skew on the nodes (NTP).",
                "Restart pods one AZ at a time.",
            ],
        ),
    ],
}


def _seed(*parts: str) -> random.Random:
    digest = hashlib.sha256("::".join(parts).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def metrics_for(service: str, *, unhealthy: bool = False) -> Metrics:
    """Deterministic synthetic metrics for a service."""

    rng = _seed("metrics", service)
    svc = SERVICES[service]
    base_p50 = int(svc.slo_latency_p99_ms * rng.uniform(0.15, 0.30))
    p95 = int(base_p50 * rng.uniform(1.6, 2.2))
    p99 = int(p95 * rng.uniform(1.15, 1.40))
    err = round(rng.uniform(0.02, 0.4), 3)
    sat = round(rng.uniform(30, 70), 1)
    if unhealthy:
        p99 = int(svc.slo_latency_p99_ms * rng.uniform(1.3, 2.2))
        p95 = int(p99 * 0.8)
        err = round(rng.uniform(2.0, 8.0), 3)
        sat = round(rng.uniform(82, 97), 1)
    return Metrics(
        requests_per_second=round(rng.uniform(5, 900), 1),
        error_rate_pct=err,
        latency_p50_ms=base_p50,
        latency_p95_ms=p95,
        latency_p99_ms=p99,
        saturation_pct=sat,
    )


_LOG_TEMPLATES = [
    ("INFO", "handled {method} {path} -> {code} in {ms}ms"),
    ("INFO", "cache {hitmiss} for key user:{uid}"),
    ("WARN", "slow query ({ms}ms): SELECT * FROM orders WHERE user_id=${uid}"),
    ("WARN", "retry {n}/3 calling {dep}"),
    ("ERROR", "{dep} call failed: connection reset"),
    ("ERROR", "unhandled exception in worker: KeyError('order_id')"),
]


def logs_for(service: str, query: str, level: str | None, limit: int) -> list[LogLine]:
    rng = _seed("logs", service, query, level or "")
    svc = SERVICES[service]
    now = datetime.now(timezone.utc)
    out: list[LogLine] = []
    i = 0
    while len(out) < max(1, min(limit, 200)) and i < 2000:
        i += 1
        lvl, tmpl = rng.choice(_LOG_TEMPLATES)
        if level and lvl != level.upper():
            continue
        msg = tmpl.format(
            method=rng.choice(["GET", "POST", "PUT"]),
            path=rng.choice(["/v1/checkout", "/v1/pay", "/healthz", "/v1/items"]),
            code=rng.choice([200, 200, 200, 404, 500, 503]),
            ms=rng.randint(5, 2400),
            hitmiss=rng.choice(["hit", "miss"]),
            uid=rng.randint(1000, 9999),
            n=rng.randint(1, 3),
            dep=rng.choice(svc.depends_on or ["upstream"]),
        )
        if query and query.lower() not in msg.lower() and query.lower() not in lvl.lower():
            continue
        ts = (now - timedelta(seconds=rng.randint(0, 3600))).isoformat(timespec="seconds")
        out.append(LogLine(timestamp=ts, level=lvl, service=service, message=msg))
    out.sort(key=lambda line: line.timestamp)
    return out


def oncall_for(team_or_service: str) -> tuple[str, str]:
    """Return ``(team, person)`` for a team name or a service name."""

    key = team_or_service.strip().lower()
    if key in SERVICES:
        team = SERVICES[key].team
    elif key in _ONCALL:
        team = key
    else:
        raise ValueError(
            f"unknown team or service {team_or_service!r}; "
            f"teams: {', '.join(sorted(_ONCALL))}; services: {', '.join(sorted(SERVICES))}"
        )
    return team, _ONCALL[team][0]


def runbook_for(service: str, symptom: str | None = None) -> list[RunbookEntry]:
    if service not in SERVICES:
        raise ValueError(f"unknown service {service!r}")
    entries = _RUNBOOKS.get(service, [])
    if symptom:
        needle = symptom.lower()
        entries = [e for e in entries if needle in e.symptom.lower()] or entries
    return entries


class SREState:
    """Per-server mutable state: incidents and deployments."""

    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        self._incident_seq = 0
        self.incidents: dict[str, Incident] = {}
        self._add_incident(
            "payments-api", "SEV2", "Elevated decline rate on card payments",
            status="acknowledged", opened_delta=timedelta(minutes=38),
        )
        self._add_incident(
            "notifications-worker", "SEV4", "Backlog in the email queue",
            status="resolved", opened_delta=timedelta(hours=26),
        )
        self.deployments: dict[str, Deployment] = {}
        seeds = [
            ("checkout-api", "2024.11.3", "succeeded", timedelta(hours=5), True),
            ("checkout-api", "2024.11.2", "rolled_back", timedelta(days=1, hours=2), False),
            ("payments-api", "5.7.1", "succeeded", timedelta(hours=2), True),
            ("web-frontend", "app-8842", "in_progress", timedelta(minutes=6), True),
            ("auth-service", "1.19.0", "failed", timedelta(hours=9), False),
        ]
        for i, (svc, ver, status, delta, rb) in enumerate(seeds, start=1):
            dep_id = f"dep-{i:04d}"
            self.deployments[dep_id] = Deployment(
                id=dep_id, service=svc, version=ver, status=status,  # type: ignore[arg-type]
                started_at=(now - delta).isoformat(timespec="seconds"), can_rollback=rb,
            )

    # -- incidents ----------------------------------------------------------- #

    def _add_incident(
        self, service: str, severity: str, summary: str, *,
        status: str = "open", opened_delta: timedelta = timedelta(0),
    ) -> Incident:
        self._incident_seq += 1
        now = datetime.now(timezone.utc)
        opened = now - opened_delta
        inc = Incident(
            id=f"INC-{self._incident_seq:04d}",
            service=service, severity=severity, status=status,  # type: ignore[arg-type]
            summary=summary,
            opened_at=opened.isoformat(timespec="seconds"),
            updated_at=opened.isoformat(timespec="seconds"),
        )
        self.incidents[inc.id] = inc
        return inc

    def open_incident(self, service: str, severity: str, summary: str) -> Incident:
        if service not in SERVICES:
            raise ValueError(f"unknown service {service!r}")
        return self._add_incident(service, severity, summary)

    def update_incident(self, incident_id: str, status: str, note: str | None = None) -> Incident:
        inc = self.incidents.get(incident_id)
        if inc is None:
            raise ValueError(f"unknown incident {incident_id!r}")
        inc.status = status  # type: ignore[assignment]
        inc.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if note:
            inc.notes.append(note)
        return inc

    def list_incidents(
        self, status: str | None = None, severity: str | None = None, service: str | None = None
    ) -> list[Incident]:
        out = list(self.incidents.values())
        if status:
            out = [i for i in out if i.status == status]
        if severity:
            out = [i for i in out if i.severity == severity.upper()]
        if service:
            out = [i for i in out if i.service == service]
        return sorted(out, key=lambda i: i.opened_at, reverse=True)

    def open_incident_ids(self, service: str) -> list[str]:
        return [
            i.id for i in self.incidents.values()
            if i.service == service and i.status != "resolved"
        ]

    # -- deployments ------------------------------------------------------- #

    def list_deployments(
        self, service: str | None = None, status: str | None = None
    ) -> list[Deployment]:
        out = list(self.deployments.values())
        if service:
            out = [d for d in out if d.service == service]
        if status:
            out = [d for d in out if d.status == status]
        return sorted(out, key=lambda d: d.started_at, reverse=True)

    def rollback_deployment(self, deployment_id: str) -> Deployment:
        dep = self.deployments.get(deployment_id)
        if dep is None:
            raise ValueError(f"unknown deployment {deployment_id!r}")
        if not dep.can_rollback:
            raise ValueError(f"{deployment_id} cannot be rolled back (status={dep.status})")
        dep.status = "rolled_back"
        dep.can_rollback = False
        return dep

    # -- derived views --------------------------------------------------- #

    def health(self, service: str) -> HealthReport:
        if service not in SERVICES:
            raise ValueError(f"unknown service {service!r}")
        svc = SERVICES[service]
        open_ids = self.open_incident_ids(service)
        open_incs = [self.incidents[i] for i in open_ids]
        unhealthy = any(i.severity in ("SEV1", "SEV2") for i in open_incs)
        m = metrics_for(service, unhealthy=unhealthy)

        reasons: list[str] = []
        status: Health = "healthy"
        if any(i.severity == "SEV1" for i in open_incs):
            status = "down"
            reasons.append("open SEV1 incident")
        if m.error_rate_pct > (100 - svc.slo_availability) * 10:
            status = "down" if status == "down" else "degraded"
            reasons.append(f"error rate {m.error_rate_pct}% over budget")
        if m.latency_p99_ms > svc.slo_latency_p99_ms:
            status = "down" if status == "down" else "degraded"
            reasons.append(
                f"p99 {m.latency_p99_ms}ms over SLO {svc.slo_latency_p99_ms}ms"
            )
        if m.saturation_pct > 85:
            status = "down" if status == "down" else "degraded"
            reasons.append(f"saturation {m.saturation_pct}%")
        for inc in open_incs:
            if inc.severity in ("SEV2", "SEV3"):
                status = "down" if status == "down" else "degraded"
                reasons.append(f"open {inc.severity} incident {inc.id}")
        if not reasons:
            reasons.append("all signals within SLO")

        return HealthReport(
            service=service, status=status, reasons=reasons, metrics=m,
            open_incident_ids=open_ids,
            slo_availability=svc.slo_availability,
            slo_latency_p99_ms=svc.slo_latency_p99_ms,
        )

    def error_budget(self, service: str, window_days: int = 30) -> ErrorBudget:
        if service not in SERVICES:
            raise ValueError(f"unknown service {service!r}")
        svc = SERVICES[service]
        window_days = max(1, min(window_days, 90))
        budget_minutes = window_days * 24 * 60 * (1 - svc.slo_availability / 100)
        # Consume the budget in proportion to the current error rate.
        m = metrics_for(service, unhealthy=bool(self.open_incident_ids(service)))
        consumed = min(budget_minutes * (m.error_rate_pct / 1.0), budget_minutes * 3)
        remaining_pct = round(max(-200.0, (1 - consumed / budget_minutes) * 100), 1)
        burn_rate = round(consumed / budget_minutes, 2) if budget_minutes else 0.0
        return ErrorBudget(
            service=service, window_days=window_days,
            slo_availability=svc.slo_availability,
            budget_minutes=round(budget_minutes, 1),
            consumed_minutes=round(consumed, 1),
            remaining_pct=remaining_pct,
            burn_rate=burn_rate,
        )


# --------------------------------------------------------------------------- #
# Structured wrappers returned by the list tools
# --------------------------------------------------------------------------- #


class ServiceList(BaseModel):
    count: int
    services: list[Service]


class IncidentList(BaseModel):
    count: int
    incidents: list[Incident]


class DeploymentList(BaseModel):
    count: int
    deployments: list[Deployment]


class LogSearchResult(BaseModel):
    service: str
    query: str
    count: int
    lines: list[LogLine]


class OnCall(BaseModel):
    team: str
    engineer: str
    escalation: list[str] = Field(description="Who to page next, in order")


class Runbook(BaseModel):
    service: str
    entries: list[RunbookEntry]


def list_services(tier: int | None = None, environment: str | None = None) -> list[Service]:
    out = list(_SERVICES)
    if tier is not None:
        out = [s for s in out if s.tier == tier]
    if environment:
        out = [s for s in out if environment in s.environments]
    return out


def get_service(name: str) -> Service:
    try:
        return SERVICES[name.strip().lower()]
    except KeyError:
        raise ValueError(
            f"unknown service {name!r}; known: {', '.join(sorted(SERVICES))}"
        ) from None


def escalation_for(team: str) -> list[str]:
    return _ONCALL.get(team, [])[1:]
