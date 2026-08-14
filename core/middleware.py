import time
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse
from dashboard.models import SystemSetting

class DynamicSessionTimeoutMiddleware:
    """
    Controla o tempo limite de inatividade e validade de sessão dinamicamente.
    Se 'remember_me' não estiver marcado, desloga após o tempo de inatividade configurado (padrão 10 min).
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # Verifica se o usuário marcou "Lembrar-me / Manter conectado"
            remember_me = request.session.get('remember_me', False)
            
            if not remember_me:
                # Busca tempo limite de inatividade configurado no banco de dados (padrão: 10 minutos)
                try:
                    timeout_minutes = int(SystemSetting.get_value('session_timeout_minutes', 10))
                except (ValueError, TypeError):
                    timeout_minutes = 10
                
                timeout_seconds = max(1, timeout_minutes) * 60
                now = time.time()
                last_activity = request.session.get('last_activity')

                if last_activity:
                    elapsed = now - last_activity
                    if elapsed > timeout_seconds:
                        # Sessão expirou por inatividade
                        logout(request)
                        login_url = reverse('login')
                        return redirect(f"{login_url}?timeout=1")

                # Atualiza timestamp da última atividade
                request.session['last_activity'] = now

        response = self.get_response(request)
        return response
