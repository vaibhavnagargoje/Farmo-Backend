"""
Send a broadcast: a notification-list entry and a push for every recipient,
each in the recipient's preferred language (English when not translated).

There is no task queue on the server, so the admin panel starts the send in a
background thread. Status and counters are saved as it goes, so the panel
shows progress, and a broadcast can only be sent once.
"""

import logging
import threading
from collections import defaultdict

from django.db import connection, transaction
from django.utils import timezone

from notifications.models import DeviceToken, Notification
from notifications.utils import send_push_to_tokens
from users.models import User

from .models import Audience, Broadcast
from .services import normalize_lang, pick, texts

logger = logging.getLogger(__name__)


class BroadcastError(Exception):
    """The broadcast cannot be sent; the message is shown to the admin."""


def recipients(audience):
    """Active users a broadcast with this audience reaches."""
    users = User.objects.filter(is_active=True)
    if audience == Audience.FARMERS:
        users = users.filter(role=User.Role.CUSTOMER)
    elif audience == Audience.PROVIDERS:
        users = users.filter(role=User.Role.PARTNER)
    return users


def start(broadcast, *, background=True):
    """Mark a draft as sending and send it (in a background thread by default)."""
    with transaction.atomic():
        locked = Broadcast.objects.select_for_update().get(pk=broadcast.pk)
        if locked.status != Broadcast.Status.DRAFT:
            raise BroadcastError("This broadcast has already been sent.")
        locked.status = Broadcast.Status.SENDING
        locked.error = ''
        locked.save(update_fields=['status', 'error'])

    if background:
        threading.Thread(
            target=_send_in_thread, args=(locked.pk,), daemon=True, name=f'broadcast-{locked.pk}',
        ).start()
    else:
        send(locked)
    return locked


def _send_in_thread(pk):
    try:
        send(Broadcast.objects.get(pk=pk))
    finally:
        connection.close()  # The thread opened its own database connection.


def send(broadcast):
    title, message = texts(broadcast, 'title'), texts(broadcast, 'message')
    try:
        audience = recipients(broadcast.audience)
        rows = [
            Notification(
                user_id=user_id,
                title=pick(title, normalize_lang(language)),
                message=pick(message, normalize_lang(language)),
                notification_type=Notification.NotificationType.GENERAL,
            )
            for user_id, language in audience.values_list('id', 'preferred_language').iterator()
        ]
        Notification.objects.bulk_create(rows, batch_size=1000)
        broadcast.recipients = len(rows)
        broadcast.save(update_fields=['recipients'])

        tokens_by_lang = defaultdict(list)
        for token, language in DeviceToken.objects.filter(user__in=audience).values_list(
            'token', 'user__preferred_language',
        ):
            tokens_by_lang[normalize_lang(language)].append(token)

        data = {'type': 'broadcast', 'broadcast_id': broadcast.pk}
        for lang, tokens in tokens_by_lang.items():
            result = send_push_to_tokens(tokens, pick(title, lang), pick(message, lang), data)
            broadcast.push_success += result['success']
            broadcast.push_failure += result['failure']
            broadcast.save(update_fields=['push_success', 'push_failure'])

        broadcast.status = Broadcast.Status.SENT
        broadcast.sent_at = timezone.now()
        broadcast.save(update_fields=['status', 'sent_at'])
    except Exception as exc:
        logger.exception('Broadcast %s failed', broadcast.pk)
        broadcast.status = Broadcast.Status.FAILED
        broadcast.error = str(exc)[:2000]
        broadcast.save(update_fields=['status', 'error'])
