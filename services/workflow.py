"""services/workflow.py - Nhật ký thao tác và kiểm tra dùng chung cho luồng nháp - gửi - duyệt."""
from __future__ import annotations

from models import WorkflowLog, db
from services.common import WorkflowError


def log_action(entity_type, entity_id, action, from_status, to_status, user, note=None):
    db.session.add(WorkflowLog(
        entity_type=entity_type, entity_id=entity_id, action=action,
        from_status=from_status, to_status=to_status, user_id=user.id if user else None, note=note,
    ))


def require_open_period(period):
    if period.status != "open":
        raise WorkflowError(f"{period.name} đã đóng, không thể thay đổi.")


def logs_for(entity_type, entity_id):
    return (WorkflowLog.query.filter_by(entity_type=entity_type, entity_id=entity_id)
            .order_by(WorkflowLog.created_at.desc(), WorkflowLog.id.desc()).all())
