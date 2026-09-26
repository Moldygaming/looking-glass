"""Microsoft 365 SKU part numbers shown with a product name in the directory."""

from __future__ import annotations

FRIENDLY: dict[str, str] = {
    "SPE_E3": "Microsoft 365 E3",
    "SPE_E5": "Microsoft 365 E5",
    "SPE_F1": "Microsoft 365 F3",
    "SPB": "Microsoft 365 Business Premium",
    "O365_BUSINESS_ESSENTIALS": "Microsoft 365 Business Basic",
    "O365_BUSINESS_PREMIUM": "Microsoft 365 Business Standard",
    "SMB_BUSINESS": "Microsoft 365 Apps for business",
    "SMB_BUSINESS_ESSENTIALS": "Microsoft 365 Business Basic",
    "SMB_BUSINESS_PREMIUM": "Microsoft 365 Business Standard",
    "ENTERPRISEPACK": "Office 365 E3",
    "ENTERPRISEPREMIUM": "Office 365 E5",
    "DESKLESSPACK": "Office 365 F3",
    "EXCHANGESTANDARD": "Exchange Online (Plan 1)",
    "EXCHANGEENTERPRISE": "Exchange Online (Plan 2)",
    "ATP_ENTERPRISE": "Microsoft Defender for Office 365 (Plan 1)",
    "EMSPREMIUM": "Enterprise Mobility + Security E5",
    "EMS": "Enterprise Mobility + Security E3",
    "AAD_PREMIUM": "Microsoft Entra ID P1",
    "AAD_PREMIUM_P2": "Microsoft Entra ID P2",
    "RIGHTSMANAGEMENT": "Azure Information Protection Plan 1",
    "POWER_BI_STANDARD": "Power BI Free",
    "POWER_BI_PRO": "Power BI Pro",
    "FLOW_FREE": "Power Automate Free",
    "TEAMS_EXPLORATORY": "Microsoft Teams Exploratory",
    "VISIOCLIENT": "Visio Plan 2",
    "PROJECTPROFESSIONAL": "Project Plan 3",
    "WIN_DEF_ATP": "Microsoft Defender for Endpoint P1",
    "IDENTITY_THREAT_PROTECTION": "Microsoft 365 E5 Security",
    "M365_F1": "Microsoft 365 F1",
    "DEVELOPERPACK": "Office 365 E3 Developer",
}


def friendly_sku_name(part: str) -> str:
    if not part:
        return ""
    return FRIENDLY.get(part) or part.replace("_", " ")


def assigned_from_graph(raw, sku_parts: dict[str, str] | None = None) -> list[dict]:
    """Normalise Graph or stored license rows to sku_id / sku_part_number / disabled_plans."""
    sku_parts = sku_parts or {}
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        sku_id = str(item.get("skuId") or item.get("sku_id") or "")
        if not sku_id:
            continue
        if "disabledPlans" in item:
            disabled = item.get("disabledPlans") or []
        else:
            disabled = item.get("disabled_plans") or []
        out.append(
            {
                "sku_id": sku_id,
                "sku_part_number": str(
                    item.get("skuPartNumber") or item.get("sku_part_number") or sku_parts.get(sku_id) or ""
                ),
                "disabled_plans": [str(plan) for plan in disabled],
            }
        )
    return out
