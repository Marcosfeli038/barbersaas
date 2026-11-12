from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("cadastro/", views.cadastro, name="cadastro"),
    path("entrar/", auth_views.LoginView.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    # painel do dono
    path("painel/", views.painel, name="painel"),
    path("painel/configuracoes/", views.configuracoes, name="configuracoes"),
    path("painel/agendamento/<int:pk>/<str:status>/", views.alterar_status, name="alterar_status"),
    path("painel/alternar/<str:tipo>/<int:pk>/", views.alternar_ativo, name="alternar_ativo"),
    # assinatura / Mercado Pago
    path("painel/assinatura/", views.assinatura, name="assinatura"),
    path("painel/assinatura/retorno/", views.assinatura_retorno, name="assinatura_retorno"),
    path("webhooks/mercadopago/", views.webhook_mercadopago, name="webhook_mercadopago"),
    # página pública de cada barbearia
    path("b/<slug:slug>/", views.reservar, name="reservar"),
    path("b/<slug:slug>/confirmar/", views.confirmar_reserva, name="confirmar_reserva"),
]
