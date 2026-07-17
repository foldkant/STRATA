from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from courses.models import ClassroomSession

from .models import ClassroomChatConfig


@receiver(post_save, sender=ClassroomSession)
def close_chat_when_classroom_finishes(sender, instance: ClassroomSession, **kwargs) -> None:
    if instance.status != ClassroomSession.Status.FINISHED:
        return
    ClassroomChatConfig.objects.filter(session=instance).update(
        whole_class_enabled=False,
        teacher_private_enabled=False,
        group_chat_enabled=False,
    )
