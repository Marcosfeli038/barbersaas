from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Agendamento, Barbearia, Profissional, Servico

User = get_user_model()


class CadastroForm(UserCreationForm):
    """Cadastro do dono: cria usuário + barbearia (14 dias de teste)."""

    nome_barbearia = forms.CharField(label="Nome da barbearia", max_length=120)
    telefone_whatsapp = forms.CharField(
        label="WhatsApp da barbearia (com DDD)", max_length=20, required=False
    )

    class Meta:
        model = User
        fields = ("username", "email")


class ServicoForm(forms.ModelForm):
    class Meta:
        model = Servico
        fields = ("nome", "duracao_minutos", "preco")


class ProfissionalForm(forms.ModelForm):
    class Meta:
        model = Profissional
        fields = ("nome",)


class ConfigBarbeariaForm(forms.ModelForm):
    class Meta:
        model = Barbearia
        fields = ("nome", "telefone_whatsapp", "abre_as", "fecha_as", "intervalo_minutos")
        widgets = {
            "abre_as": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "fecha_as": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }


class ReservaForm(forms.Form):
    """Formulário público de reserva (passo final)."""

    cliente_nome = forms.CharField(label="Seu nome", max_length=100)
    cliente_telefone = forms.CharField(label="WhatsApp (com DDD)", max_length=20)
