"""
Authentication-related views.
"""
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import FormView


class SignupView(FormView):
    """Simple signup view using Django's built-in UserCreationForm."""

    template_name = 'registration/signup.html'
    form_class = UserCreationForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(self._safe_next_url() or '/')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['next'] = self._safe_next_url() or ''
        return context

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        return redirect(self._safe_next_url() or '/')

    def _safe_next_url(self):
        candidate = (
            self.request.POST.get('next')
            or self.request.GET.get('next')
            or ''
        )
        if candidate and url_has_allowed_host_and_scheme(
            url=candidate,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return candidate
        return ''
