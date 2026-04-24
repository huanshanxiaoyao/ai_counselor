import json
import logging

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views import View

from backend.roundtable.services.token_quota import (
    QuotaExceededError,
    ensure_within_quota_or_raise,
    get_quota_snapshot,
    subject_from_request,
)

from .services.crisis_service import build_sticky_crisis_result, detect_crisis_text
from .services.message_service import (
    append_crisis_response_pair,
    append_message_pair,
    is_crisis_mode,
    list_serialized_messages,
    serialize_message,
)
from .services.model_option_service import (
    get_default_selected_model,
    get_model_options,
    normalize_selected_model,
)
from .services.session_service import (
    MoodPalSession,
    activate_session,
    create_session,
    destroy_summary,
    end_session,
    get_persona_catalog,
    get_persona_config,
    get_session_or_404,
    save_summary,
    serialize_session,
)


logger = logging.getLogger(__name__)


def _json_body(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body)
    except json.JSONDecodeError:
        return {}


def _is_truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _quota_error_response(snapshot: dict, status: int = 402) -> JsonResponse:
    return JsonResponse(
        {
            'error': '已超过可用 token 配额，请联系管理员获取更多额度',
            'error_code': 'quota_exceeded',
            'quota': snapshot,
        },
        status=status,
        json_dumps_params={'ensure_ascii': False},
    )


def _log_quota_block(context: str, snapshot: dict, *, session_id: str = ''):
    logger.warning(
        'MoodPal quota blocked context=%s session=%s subject=%s used=%s limit=%s',
        context,
        session_id or '',
        snapshot.get('subject_key', ''),
        snapshot.get('used_tokens', 0),
        snapshot.get('quota_limit', 0),
    )


def _home_context(**kwargs):
    context = {
        'personas': get_persona_catalog(),
        'llm_options': get_model_options(),
        'default_selected_model': get_default_selected_model(),
        'selected_model_value': get_default_selected_model(),
    }
    context.update(kwargs)
    return context


class MoodPalHomeView(View):
    def get(self, request):
        return render(request, 'moodpal/index.html', _home_context())

    def post(self, request):
        persona_id = (request.POST.get('persona_id') or '').strip()
        selected_model = (request.POST.get('selected_model') or '').strip()
        privacy_acknowledged = _is_truthy(request.POST.get('privacy_acknowledged'))
        quota_subject = subject_from_request(request)
        try:
            ensure_within_quota_or_raise(quota_subject)
        except QuotaExceededError as exc:
            _log_quota_block('home_form_start', exc.snapshot)
            return render(
                request,
                'moodpal/index.html',
                _home_context(
                    form_error='已超过可用 token 配额，请点击顶部 Token 查看并联系管理员获取更多额度。',
                    quota=exc.snapshot,
                    selected_model_value=normalize_selected_model(selected_model),
                ),
                status=402,
            )
        try:
            session = create_session(
                request=request,
                persona_id=persona_id,
                selected_model=selected_model,
                privacy_acknowledged=privacy_acknowledged,
            )
        except ValueError as exc:
            if str(exc) == 'privacy_ack_required':
                return render(
                    request,
                    'moodpal/index.html',
                    _home_context(
                        form_error='请先确认隐私契约与边界说明，再开始新会话。',
                        selected_model_value=normalize_selected_model(selected_model),
                    ),
                    status=400,
                )
            return render(
                request,
                'moodpal/index.html',
                _home_context(
                    form_error='请选择一个有效角色后再开始会话。',
                    selected_model_value=normalize_selected_model(selected_model),
                ),
                status=400,
            )
        return redirect('moodpal:session', session_id=session.id)


class MoodPalSessionView(View):
    def get(self, request, session_id):
        session = get_session_or_404(request=request, session_id=session_id)
        if session.status in [MoodPalSession.Status.SUMMARY_PENDING, MoodPalSession.Status.CLOSED]:
            return redirect('moodpal:summary', session_id=session.id)
        session = activate_session(session)
        session_payload = serialize_session(session)
        return render(
            request,
            'moodpal/session.html',
            {
                'session': session,
                'persona': get_persona_config(session.persona_id),
                'session_json': json.dumps(session_payload, ensure_ascii=False),
                'messages': list_serialized_messages(session),
                'selected_model_label': session_payload['selected_model_label'],
            },
        )

    def post(self, request, session_id):
        session = get_session_or_404(request=request, session_id=session_id)
        action = (request.POST.get('action') or '').strip()
        if action == 'end':
            end_session(session, reason=MoodPalSession.CloseReason.USER_ENDED)
            return redirect('moodpal:summary', session_id=session.id)
        return JsonResponse({'error': 'unsupported_action'}, status=400)


class MoodPalSummaryView(View):
    def get(self, request, session_id):
        session = get_session_or_404(request=request, session_id=session_id)
        if session.status in [MoodPalSession.Status.STARTING, MoodPalSession.Status.ACTIVE]:
            return redirect('moodpal:session', session_id=session.id)
        return render(
            request,
            'moodpal/summary.html',
            {
                'session': session,
                'status_closed': MoodPalSession.Status.CLOSED,
                'status_summary_pending': MoodPalSession.Status.SUMMARY_PENDING,
                'summary_destroyed': MoodPalSession.SummaryAction.DESTROYED,
                'summary_saved': MoodPalSession.SummaryAction.SAVED,
                'summary_text': session.summary_final or session.summary_draft,
                'raw_message_count': session.messages.count(),
            },
        )

    def post(self, request, session_id):
        session = get_session_or_404(request=request, session_id=session_id)
        action = (request.POST.get('action') or '').strip()
        if action == 'save':
            try:
                save_summary(session, summary_text=request.POST.get('summary_text', ''))
            except ValueError:
                return redirect('moodpal:session', session_id=session.id)
        elif action == 'destroy':
            try:
                destroy_summary(session)
            except ValueError:
                return redirect('moodpal:session', session_id=session.id)
        return redirect('moodpal:summary', session_id=session.id)


class MoodPalSessionStartApiView(View):
    def post(self, request):
        data = _json_body(request)
        persona_id = (data.get('persona_id') or '').strip()
        selected_model = (data.get('selected_model') or '').strip()
        privacy_acknowledged = _is_truthy(data.get('privacy_acknowledged'))
        quota_subject = subject_from_request(request)
        try:
            ensure_within_quota_or_raise(quota_subject)
        except QuotaExceededError as exc:
            _log_quota_block('session_start_api', exc.snapshot)
            return _quota_error_response(exc.snapshot)
        try:
            session = create_session(
                request=request,
                persona_id=persona_id,
                selected_model=selected_model,
                privacy_acknowledged=privacy_acknowledged,
            )
        except ValueError as exc:
            error_code = str(exc)
            if error_code not in {'invalid_persona', 'privacy_ack_required'}:
                error_code = 'invalid_persona'
            return JsonResponse({'error': error_code}, status=400)
        return JsonResponse(
            {
                'session': serialize_session(session),
                'session_url': f'/moodpal/session/{session.id}/',
                'summary_url': f'/moodpal/session/{session.id}/summary/',
                'quota': get_quota_snapshot(quota_subject),
            },
            status=201,
        )


class MoodPalSessionDetailApiView(View):
    def get(self, request, session_id):
        session = get_session_or_404(request=request, session_id=session_id)
        if session.status == MoodPalSession.Status.STARTING:
            session = activate_session(session)
        messages = []
        if session.status in [MoodPalSession.Status.STARTING, MoodPalSession.Status.ACTIVE]:
            messages = list_serialized_messages(session)
        return JsonResponse({'session': serialize_session(session), 'messages': messages})


class MoodPalSessionMessageApiView(View):
    def post(self, request, session_id):
        session = get_session_or_404(request=request, session_id=session_id)
        if session.status in [MoodPalSession.Status.SUMMARY_PENDING, MoodPalSession.Status.CLOSED]:
            return JsonResponse(
                {
                    'error': 'session_unavailable',
                    'error_code': 'session_summary_pending',
                    'summary_url': f'/moodpal/session/{session.id}/summary/',
                    'session': serialize_session(session),
                },
                status=409,
            )
        data = _json_body(request)
        content = (data.get('content') or '').strip()
        if not content:
            return JsonResponse({'error': 'empty_message', 'session': serialize_session(session)}, status=400)

        quota_subject = subject_from_request(request)
        crisis_result = build_sticky_crisis_result() if is_crisis_mode(session) else detect_crisis_text(content)
        if crisis_result.triggered:
            try:
                session, user_message, assistant_message = append_crisis_response_pair(
                    session,
                    user_content=content,
                    crisis_result=crisis_result,
                )
            except ValueError as exc:
                return JsonResponse(
                    {
                        'error': str(exc),
                        'session': serialize_session(session),
                    },
                    status=409,
                )
            return JsonResponse(
                {
                    'session': serialize_session(session),
                    'messages': [
                        serialize_message(user_message),
                        serialize_message(assistant_message),
                    ],
                    'quota': get_quota_snapshot(quota_subject),
                    'safety_override': True,
                },
                status=201,
            )

        try:
            ensure_within_quota_or_raise(quota_subject)
        except QuotaExceededError as exc:
            _log_quota_block('session_message_api', exc.snapshot, session_id=str(session.id))
            return _quota_error_response(exc.snapshot)

        try:
            session, user_message, assistant_message = append_message_pair(
                session,
                user_content=content,
            )
        except ValueError as exc:
            error_code = str(exc)
            status_code = 400 if error_code == 'empty_message' else 409
            return JsonResponse(
                {
                    'error': error_code,
                    'session': serialize_session(session),
                },
                status=status_code,
            )
        return JsonResponse(
            {
                'session': serialize_session(session),
                'messages': [
                    serialize_message(user_message),
                    serialize_message(assistant_message),
                ],
                'quota': get_quota_snapshot(quota_subject),
            },
            status=201,
        )


class MoodPalSessionEndApiView(View):
    def post(self, request, session_id):
        session = get_session_or_404(request=request, session_id=session_id)
        session = end_session(session, reason=MoodPalSession.CloseReason.USER_ENDED)
        return JsonResponse(
            {
                'session': serialize_session(session),
                'summary_url': f'/moodpal/session/{session.id}/summary/',
            }
        )


class MoodPalSummarySaveApiView(View):
    def post(self, request, session_id):
        session = get_session_or_404(request=request, session_id=session_id)
        data = _json_body(request)
        try:
            session = save_summary(session, summary_text=data.get('summary_text', ''))
        except ValueError as exc:
            return JsonResponse({'error': str(exc)}, status=409)
        return JsonResponse({'session': serialize_session(session)})


class MoodPalSummaryDestroyApiView(View):
    def post(self, request, session_id):
        session = get_session_or_404(request=request, session_id=session_id)
        try:
            session = destroy_summary(session)
        except ValueError as exc:
            return JsonResponse({'error': str(exc)}, status=409)
        return JsonResponse({'session': serialize_session(session)})
