from django.contrib import admin

from .models import Agendamento, Barbearia, Pagamento, Profissional, Servico


@admin.register(Barbearia)
class BarbeariaAdmin(admin.ModelAdmin):
    list_display = ("nome", "slug", "plano", "assinatura_ativa_ate", "criado_em")
    list_filter = ("plano",)
    search_fields = ("nome", "slug")


@admin.register(Servico)
class ServicoAdmin(admin.ModelAdmin):
    list_display = ("nome", "barbearia", "duracao_minutos", "preco", "ativo")


@admin.register(Profissional)
class ProfissionalAdmin(admin.ModelAdmin):
    list_display = ("nome", "barbearia", "ativo")


@admin.register(Agendamento)
class AgendamentoAdmin(admin.ModelAdmin):
    list_display = ("cliente_nome", "barbearia", "profissional", "servico", "inicio", "status")
    list_filter = ("status", "barbearia")
    date_hierarchy = "inicio"


@admin.register(Pagamento)
class PagamentoAdmin(admin.ModelAdmin):
    list_display = ("barbearia", "plano", "valor", "status", "mp_payment_id", "criado_em")
    list_filter = ("status", "plano")
