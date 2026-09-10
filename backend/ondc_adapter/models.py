import uuid

from django.db import models


class CallbackRecord(models.Model):
    """Correlates an outbound Beckn request with its later async on_* callback.

    The real ONDC/Beckn protocol is asynchronous: a BAP POSTs `search` (etc.) to the
    gateway/BPP and gets back a bare ACK/NACK immediately; the real result arrives later
    as a SEPARATE POST (`on_search`, etc.) to the BAP's own registered callback URL. This
    table is what lets ondc_adapter.client's synchronous-looking search()/select()/init()/
    confirm()/get_status() functions work against that reality: the on_* view
    (ondc_adapter/views.py) writes the callback payload here as soon as it arrives; the
    client function that sent the original request polls this table for it (see
    client._await_callback).

    Correlated by (transaction_id, action, message_id) -- NOT just (transaction_id,
    action). Confirmed live 2026-09-10: a transaction_id is reused across REPEATED calls
    of the same action (get_status polled more than once against the same booking, exactly
    what live tracking does), so (transaction_id, action) alone can match a STALE record
    from an earlier call before the new callback for THIS call has even arrived -- a real
    race, not hypothetical. `message_id` is a fresh UUID generated per outbound call (see
    client._build_context) and Beckn's own convention that a callback carries the same
    context (message_id included) as the request it answers -- mock_bpp's callback
    payloads already spread `{**context, "action": "on_x"}`, so this "just works" once the
    client passes its own freshly generated message_id through to what it polls for.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction_id = models.CharField(max_length=64, db_index=True)
    action = models.CharField(max_length=32)  # "on_search", "on_select", "on_init", "on_confirm", "on_status"
    message_id = models.CharField(max_length=64)
    payload = models.JSONField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("transaction_id", "action", "message_id")]

    def __str__(self):
        return f"{self.transaction_id}/{self.action}/{self.message_id}"
