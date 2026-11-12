from django.shortcuts import render

from .views import SemBarbearia


class SemBarbeariaMiddleware:
    """Mostra uma tela explicativa em vez de um 404 seco."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, SemBarbearia):
            return render(request, "agenda/sem_barbearia.html", status=200)
