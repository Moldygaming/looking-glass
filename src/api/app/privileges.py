from dataclasses import dataclass


@dataclass(frozen=True)
class Privilege:
    key: str
    module: str
    name: str
    description: str


CATALOG: tuple[Privilege, ...] = (
    Privilege(
        "platform.admin",
        "Platform",
        "Platform administrator",
        "Full control. Bypasses privilege checks and data scopes.",
    ),
    Privilege(
        "admin.users.read",
        "Admin",
        "View users",
        "List users, their groups, and effective access.",
    ),
    Privilege(
        "admin.users.write",
        "Admin",
        "Manage users",
        "Create, disable, and edit users and their assigned roles.",
    ),
    Privilege(
        "admin.groups.read",
        "Admin",
        "View groups",
        "List groups, members, roles, and data scopes.",
    ),
    Privilege(
        "admin.groups.write",
        "Admin",
        "Manage groups",
        "Create and edit groups, membership, assigned roles, and data scopes.",
    ),
    Privilege(
        "admin.roles.read",
        "Admin",
        "View roles",
        "List roles and the permissions they grant.",
    ),
    Privilege(
        "admin.roles.write",
        "Admin",
        "Manage roles",
        "Create roles and choose their permissions.",
    ),
    Privilege(
        "connections.read",
        "Infrastructure",
        "View connections",
        "See cloud connectors and their status.",
    ),
    Privilege(
        "connections.write",
        "Infrastructure",
        "Manage connections",
        "Create, configure, test, and ingest cloud connectors.",
    ),
    Privilege(
        "finops.costs.read",
        "FinOps",
        "View costs",
        "Open cost explorer, overview, and cost line items within data scopes.",
    ),
    Privilege(
        "finops.recommendations.read",
        "FinOps",
        "View recommendations",
        "See savings recommendations within data scopes.",
    ),
    Privilege(
        "finops.recommendations.write",
        "FinOps",
        "Manage recommendations",
        "Accept or dismiss recommendations and refresh the job.",
    ),
    Privilege(
        "finops.dashboards.read",
        "FinOps",
        "View dashboards",
        "Open dashboards shared with the organisation or the user's groups.",
    ),
    Privilege(
        "finops.dashboards.write",
        "FinOps",
        "Manage dashboards",
        "Create and edit dashboards the user owns.",
    ),
)

BY_KEY = {item.key: item for item in CATALOG}
ALL_KEYS = frozenset(BY_KEY)
PLATFORM_ADMIN_KEY = "platform.admin"
PLATFORM_ADMIN_ROLE_NAME = "Platform administrator"

DEMO_COST_KEYS = (
    "finops.costs.read",
    "finops.recommendations.read",
    "finops.recommendations.write",
    "finops.dashboards.read",
    "finops.dashboards.write",
    "connections.read",
)


def catalog_payload() -> list[dict[str, str]]:
    return [
        {"key": item.key, "module": item.module, "name": item.name, "description": item.description}
        for item in CATALOG
    ]


def unknown_privileges(keys: list[str]) -> list[str]:
    return sorted({key for key in keys if key not in ALL_KEYS})
