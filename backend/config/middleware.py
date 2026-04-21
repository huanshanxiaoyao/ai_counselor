"""
Auth-related middleware for AI Counselor.

Anonymous users are allowed everywhere by default: GuestSessionMiddleware ensures
every visitor has a stable, session-backed `guest_id` we can use as a temporary
identity. Views that genuinely need a real account should use Django's standard
`@login_required` decorator on a case-by-case basis.
"""
import uuid
from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import resolve_url
from urllib.parse import quote

from backend.roundtable.services.token_quota import ANON_USAGE_COOKIE_KEY

GUEST_SESSION_KEY = 'guest_id'


class GuestSessionMiddleware:
    """Give every visitor a stable `guest_id` stored in their Django session.

    Written to the session on first request (which also sets the `sessionid` cookie),
    so subsequent requests — HTTP and WebSocket alike — see the same id. Views and
    the WS consumer can read it via `request.session['guest_id']` / `scope['session']`.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        session = getattr(request, 'session', None)
        if session is not None and not session.get(GUEST_SESSION_KEY):
            session[GUEST_SESSION_KEY] = uuid.uuid4().hex
            session.modified = True
        anon_usage_id = request.COOKIES.get(ANON_USAGE_COOKIE_KEY)
        if not anon_usage_id:
            anon_usage_id = uuid.uuid4().hex
        request.anon_usage_id = anon_usage_id

        response = self.get_response(request)
        if not request.COOKIES.get(ANON_USAGE_COOKIE_KEY):
            response.set_cookie(
                ANON_USAGE_COOKIE_KEY,
                anon_usage_id,
                max_age=60 * 60 * 24 * 365,
                httponly=True,
                samesite='Lax',
            )
        return response


class LoginRequiredMiddleware:
    """Redirect any unauthenticated request to LOGIN_URL. NOT mounted globally by
    default — kept for environments that want to lock the whole site down via
    settings. For per-view enforcement, use `django.contrib.auth.decorators.login_required`.
    """

    EXEMPT_PATH_PREFIXES = (
        '/accounts/login/',
        '/accounts/logout/',
        '/accounts/password_reset/',
        '/accounts/password_change/',
        '/accounts/reset/',
    )

    def __init__(self, get_response):
        self.get_response = get_response
        static_url = getattr(settings, 'STATIC_URL', '/static/') or '/static/'
        self.static_prefix = static_url if static_url.startswith('/') else '/' + static_url

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            return self.get_response(request)

        path = request.path
        if path.startswith(self.static_prefix):
            return self.get_response(request)
        for prefix in self.EXEMPT_PATH_PREFIXES:
            if path.startswith(prefix):
                return self.get_response(request)

        accept = request.headers.get('Accept', '')
        wants_json = (
            '/api/' in path
            or accept.startswith('application/json')
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        )
        if wants_json:
            return JsonResponse(
                {'error': '未登录', 'login_url': resolve_url(settings.LOGIN_URL)},
                status=401,
            )

        login_url = resolve_url(settings.LOGIN_URL)
        return HttpResponseRedirect(f'{login_url}?next={quote(request.get_full_path())}')
