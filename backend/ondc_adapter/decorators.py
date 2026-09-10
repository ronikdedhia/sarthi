"""Reusable inbound-signature verification for any Beckn/ONDC-shaped endpoint --
mock_bpp's simulated seller views use this today; a real on_search/on_select/on_init/
on_confirm callback view (once ONDC registry access exists, see FEASIBILITY_RESEARCH.md
#2) would use the exact same decorator."""
import functools
import json

from django.http import JsonResponse

from .signing import SignatureVerificationError, verify_authorization_header


def require_valid_signature(get_public_key):
    """get_public_key: a zero-arg callable returning the base64 public key to verify
    against (a callable, not a plain value, so it can read django.conf.settings lazily --
    settings aren't necessarily configured yet at import/decoration time)."""

    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapped(request, *args, **kwargs):
            auth_header = request.headers.get("Authorization", "")
            try:
                verify_authorization_header(request.body, auth_header, get_public_key())
            except SignatureVerificationError as e:
                return JsonResponse({"error": f"invalid signature: {e}"}, status=401)
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


def parse_json_body(request):
    return json.loads(request.body.decode() or "{}")
