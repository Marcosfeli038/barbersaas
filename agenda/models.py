from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class Plano(models.TextChoices):
    GRATIS = "gratis", "Grátis (teste)"
    BASICO = "basico", "Básico"
    PRO = "pro", "Pro"


class Barbearia(models.Model):
    """Cada barbearia é um cliente (tenant) do SaaS."""

    dono = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="barbearia"
    )
    nome = models.CharField(max_length=120)
    slug = models.SlugField(unique=True, help_text="Endereço público: /b/<slug>/")
    telefone_whatsapp = models.CharField(
        max_length=20, blank=True, help_text="Só números, com DDD. Ex: 11999998888"
    )
    abre_as = models.TimeField(default=time(9, 0))
    fecha_as = models.TimeField(default=time(19, 0))
    intervalo_minutos = models.PositiveIntegerField(
        default=30, help_text="Tamanho de cada horário na agenda"
    )
    plano = models.CharField(max_length=10, choices=Plano.choices, default=Plano.GRATIS)
    assinatura_ativa_ate = models.DateField(
        null=True, blank=True, help_text="Fim do período pago/teste"
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "barbearia"

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nome)
        super().save(*args, **kwargs)

    @property
    def assinatura_valida(self):
        if self.assinatura_ativa_ate is None:
            return True
        return self.assinatura_ativa_ate >= timezone.localdate()


class Servico(models.Model):
    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.CASCADE, related_name="servicos"
    )
    nome = models.CharField(max_length=80)
    duracao_minutos = models.PositiveIntegerField(default=30)
    preco = models.DecimalField(max_digits=8, decimal_places=2)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} ({self.duracao_minutos} min)"


class Profissional(models.Model):
    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.CASCADE, related_name="profissionais"
    )
    nome = models.CharField(max_length=80)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "profissionais"

    def __str__(self):
        return self.nome


class Agendamento(models.Model):
    class Status(models.TextChoices):
        MARCADO = "marcado", "Marcado"
        CONCLUIDO = "concluido", "Concluído"
        CANCELADO = "cancelado", "Cancelado"

    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.CASCADE, related_name="agendamentos"
    )
    profissional = models.ForeignKey(
        Profissional, on_delete=models.PROTECT, related_name="agendamentos"
    )
    servico = models.ForeignKey(
        Servico, on_delete=models.PROTECT, related_name="agendamentos"
    )
    cliente_nome = models.CharField(max_length=100)
    cliente_telefone = models.CharField(max_length=20, help_text="Com DDD")
    inicio = models.DateTimeField()
    fim = models.DateTimeField(editable=False)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.MARCADO
    )
    lembrete_enviado = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["inicio"]

    def __str__(self):
        return f"{self.cliente_nome} - {self.inicio:%d/%m %H:%M}"

    def clean(self):
        if not (self.servico_id and self.profissional_id and self.inicio):
            return
        self.fim = self.inicio + timedelta(minutes=self.servico.duracao_minutos)
        if self.status == self.Status.CANCELADO:
            return
        conflitos = Agendamento.objects.filter(
            profissional_id=self.profissional_id,
            inicio__lt=self.fim,
            fim__gt=self.inicio,
        ).exclude(status=self.Status.CANCELADO)
        if self.pk:
            conflitos = conflitos.exclude(pk=self.pk)
        if conflitos.exists():
            raise ValidationError("Este horário já está ocupado para o profissional.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    # ---- WhatsApp (começamos com link wa.me, sem API paga) ----
    @property
    def telefone_limpo(self):
        digitos = "".join(c for c in self.cliente_telefone if c.isdigit())
        if len(digitos) in (10, 11):  # sem DDI, assume Brasil
            digitos = "55" + digitos
        return digitos

    @property
    def mensagem_lembrete(self):
        inicio_local = timezone.localtime(self.inicio)
        return (
            f"Olá, {self.cliente_nome}! Lembrando do seu horário na "
            f"{self.barbearia.nome}: {self.servico.nome} com {self.profissional.nome}, "
            f"dia {inicio_local:%d/%m} às {inicio_local:%H:%M}. "
            "Se não puder comparecer, avise por aqui. Até lá!"
        )

    @property
    def link_whatsapp(self):
        from urllib.parse import quote

        return f"https://wa.me/{self.telefone_limpo}?text={quote(self.mensagem_lembrete)}"


def horarios_livres(barbearia, profissional, servico, dia):
    """Lista de datetimes disponíveis para um dia, respeitando conflitos e o horário atual."""
    tz = timezone.get_current_timezone()
    abre = timezone.make_aware(datetime.combine(dia, barbearia.abre_as), tz)
    fecha = timezone.make_aware(datetime.combine(dia, barbearia.fecha_as), tz)
    passo = timedelta(minutes=barbearia.intervalo_minutos)
    duracao = timedelta(minutes=servico.duracao_minutos)

    ocupados = list(
        Agendamento.objects.filter(
            profissional=profissional, inicio__lt=fecha, fim__gt=abre
        )
        .exclude(status=Agendamento.Status.CANCELADO)
        .values_list("inicio", "fim")
    )

    agora = timezone.now()
    livres = []
    atual = abre
    while atual + duracao <= fecha:
        fim_slot = atual + duracao
        if atual > agora and not any(i < fim_slot and f > atual for i, f in ocupados):
            livres.append(atual)
        atual += passo
    return livres


class Pagamento(models.Model):
    """Cobrança mensal feita pelo Mercado Pago (Checkout Pro)."""

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        APROVADO = "aprovado", "Aprovado"
        RECUSADO = "recusado", "Recusado"

    barbearia = models.ForeignKey(
        Barbearia, on_delete=models.CASCADE, related_name="pagamentos"
    )
    plano = models.CharField(max_length=10, choices=Plano.choices)
    valor = models.DecimalField(max_digits=8, decimal_places=2)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDENTE
    )
    mp_preference_id = models.CharField(max_length=80, blank=True)
    mp_payment_id = models.CharField(max_length=40, blank=True, null=True, unique=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    aprovado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.barbearia} - {self.plano} - {self.get_status_display()}"
