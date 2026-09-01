from sqlalchemy import ColumnElement, and_, false, or_, true

from app.models import CostLineItem, Recommendation
from app.schemas import CurrentUser, ScopeOut


def _tag_match(column, scope: ScopeOut) -> ColumnElement[bool]:
    clause = column[scope.tag_key].astext == scope.tag_value
    extras = []
    if scope.provider:
        extras.append(
            (CostLineItem.provider == scope.provider)
            if column is CostLineItem.tags
            else (Recommendation.provider == scope.provider)
        )
    if scope.connection_id:
        extras.append(
            (CostLineItem.connection_id == scope.connection_id)
            if column is CostLineItem.tags
            else (Recommendation.connection_id == scope.connection_id)
        )
    return and_(clause, *extras) if extras else clause


def cost_acl(user: CurrentUser) -> ColumnElement[bool]:
    if user.is_admin:
        return true()
    if not user.scopes:
        return false()
    return or_(*[_tag_match(CostLineItem.tags, s) for s in user.scopes])


def recommendation_acl(user: CurrentUser) -> ColumnElement[bool]:
    if user.is_admin:
        return true()
    if not user.scopes:
        return false()
    return or_(*[_tag_match(Recommendation.tags, s) for s in user.scopes])


def dashboard_visible(user: CurrentUser, owner_id, visibility: str, shared_group_id) -> bool:
    if user.is_admin or owner_id == user.id or visibility == "org":
        return True
    if visibility == "group" and shared_group_id:
        return shared_group_id in user.group_ids
    return False
