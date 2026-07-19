from __future__ import annotations

import logging

from rest_framework.renderers import JSONRenderer

from accounts.models import User
from learning_analytics.privacy import find_student_privacy_violations


logger = logging.getLogger(__name__)


class StudentPrivacyJSONRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None):
        context = renderer_context or {}
        request = context.get("request")
        response = context.get("response")
        user = getattr(request, "user", None)
        if (
            user
            and user.is_authenticated
            and user.role == User.Role.STUDENT
            and not user.is_superuser
        ):
            violations = find_student_privacy_violations(data)
            if violations:
                logger.error(
                    "Blocked student response containing hidden inference fields: %s",
                    ", ".join(violations[:20]),
                )
                data = {
                    "data": None,
                    "message": "响应包含受限分析信息，已被系统阻止。",
                    "errors": {"privacy": ["请联系学校管理员检查接口契约。"]},
                }
                if response is not None:
                    response.status_code = 500
                    response.data = data
        return super().render(data, accepted_media_type, context)
