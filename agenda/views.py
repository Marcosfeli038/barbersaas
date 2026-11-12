from datetime import date, datetime, timedelta

import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import (
    CadastroForm,
    ConfigBarbeariaForm,
    ProfissionalForm,
    ReservaForm,
    ServicoForm,
)
from . import mercadopago
from .models import (
    Agendamento,
    Barbearia,
    Pagamento,
    Plano,
    Profissional,
    Servico,
    horarios_livres,
)


# ---------------------------------------------------------------- público
def home(request):
    return render(request, "agenda/home.html")


def cadastro(request):
    form = CadastroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        nome = form.cleaned_data["nome_barbearia"]
        slug_base = slugify(nome) or user.username
        slug, n = slug_base, 2
        while Barbearia.objects.filter(slug=slug).exists():
            slug, n = f"{slug_base}-{n}", n + 1
        Barbearia.objects.create(
            dono=user,
            nome=nome,
            slug=slug,
            telefone_whatsapp=form.cleaned_data["telefone_whatsapp"],
            plano=Plano.GRATIS,
            assinatura_ativa_ate=timezone.localdate() + timedelta(days=14),
        )
        login(request, user)
        messages.success(request, "Conta criada! Você tem 14 dias de teste grátis.")
        return redirect("painel")
    return render(request, "registration/cadastro.html", {"form": form})


def _parse_dia(texto):
    try:
        dia = datetime.strptime(texto, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return timezone.localdate()
    return max(dia, timezone.localdate())


def reservar(request, slug):
    barbearia = get_object_or_404(Barbearia, slug=slug)
    if not barbearia.assinatura_valida:
        return render(request, "agenda/indisponivel.html", {"barbearia": barbearia})

    servicos = barbearia.servicos.filter(ativo=True)
    profissionais = barbearia.profissionais.filter(ativo=True)
    dia = _parse_dia(request.GET.get("dia"))
    servico = servicos.filter(pk=request.GET.get("servico") or 0).first()
    profissional = profissionais.filter(pk=request.GET.get("profissional") or 0).first()

    horarios = []
    if servico and profissional:
        horarios = horarios_livres(barbearia, profissional, servico, dia)

    ctx = {
        "barbearia": barbearia,
        "servicos": servicos,
        "profissionais": profissionais,
        "dia": dia,
        "servico": servico,
        "profissional": profissional,
        "horarios": horarios,
        "form": ReservaForm(),
    }
    return render(request, "agenda/reservar.html", ctx)


@require_POST
def confirmar_reserva(request, slug):
    barbearia = get_object_or_404(Barbearia, slug=slug)
    if not barbearia.assinatura_valida:
        return render(request, "agenda/indisponivel.html", {"barbearia": barbearia})

    servico = get_object_or_404(Servico, pk=request.POST.get("servico"), barbearia=barbearia, ativo=True)
    profissional = get_object_or_404(
        Profissional, pk=request.POST.get("profissional"), barbearia=barbearia, ativo=True
    )
    form = ReservaForm(request.POST)
    try:
        inicio = datetime.fromisoformat(request.POST.get("inicio", ""))
        if timezone.is_naive(inicio):
            inicio = timezone.make_aware(inicio)
    except ValueError:
        messages.error(request, "Horário inválido.")
        return redirect("reservar", slug=slug)

    if not form.is_valid():
        messages.error(request, "Preencha seu nome e WhatsApp.")
        return redirect("reservar", slug=slug)

    if inicio not in horarios_livres(barbearia, profissional, servico, timezone.localtime(inicio).date()):
        messages.error(request, "Esse horário acabou de ser ocupado. Escolha outro.")
        return redirect("reservar", slug=slug)

    try:
        ag = Agendamento.objects.create(
            barbearia=barbearia,
            profissional=profissional,
            servico=servico,
            inicio=inicio,
            cliente_nome=form.cleaned_data["cliente_nome"],
            cliente_telefone=form.cleaned_data["cliente_telefone"],
        )
    except ValidationError:
        messages.error(request, "Esse horário acabou de ser ocupado. Escolha outro.")
        return redirect("reservar", slug=slug)
    return render(request, "agenda/confirmado.html", {"barbearia": barbearia, "ag": ag})


# ---------------------------------------------------------------- painel
class SemBarbearia(Exception):
    """Usuário logado que não é dono de nenhuma barbearia (ex.: superusuário)."""


def _barbearia(request):
    try:
        return Barbearia.objects.get(dono=request.user)
    except Barbearia.DoesNotExist:
        raise SemBarbearia()


@login_required
def painel(request):
    barbearia = _barbearia(request)
    dia = _parse_dia(request.GET.get("dia")) if request.GET.get("dia") else timezone.localdate()
    ags = (
        barbearia.agendamentos.filter(inicio__date=dia)
        .exclude(status=Agendamento.Status.CANCELADO)
        .select_related("servico", "profissional")
    )
    faturamento = (
        ags.filter(status=Agendamento.Status.CONCLUIDO).aggregate(t=Sum("servico__preco"))["t"] or 0
    )
    ctx = {
        "barbearia": barbearia,
        "dia": dia,
        "dia_anterior": dia - timedelta(days=1),
        "dia_seguinte": dia + timedelta(days=1),
        "agendamentos": ags,
        "faturamento": faturamento,
        "link_publico": request.build_absolute_uri(f"/b/{barbearia.slug}/"),
    }
    return render(request, "agenda/painel.html", ctx)


@login_required
@require_POST
def alterar_status(request, pk, status):
    ag = get_object_or_404(Agendamento, pk=pk, barbearia=_barbearia(request))
    if status not in Agendamento.Status.values:
        messages.error(request, "Status inválido.")
    else:
        ag.status = status
        ag.save()
    return redirect("painel")


@login_required
def configuracoes(request):
    barbearia = _barbearia(request)
    config = ConfigBarbeariaForm(request.POST or None, instance=barbearia, prefix="cfg")
    servico_form = ServicoForm(prefix="srv")
    prof_form = ProfissionalForm(prefix="prof")

    if request.method == "POST":
        acao = request.POST.get("acao")
        if acao == "config" and config.is_valid():
            config.save()
            messages.success(request, "Configurações salvas.")
            return redirect("configuracoes")
        if acao == "servico":
            servico_form = ServicoForm(request.POST, prefix="srv")
            if servico_form.is_valid():
                s = servico_form.save(commit=False)
                s.barbearia = barbearia
                s.save()
                messages.success(request, "Serviço adicionado.")
                return redirect("configuracoes")
        if acao == "profissional":
            prof_form = ProfissionalForm(request.POST, prefix="prof")
            if prof_form.is_valid():
                p = prof_form.save(commit=False)
                p.barbearia = barbearia
                p.save()
                messages.success(request, "Profissional adicionado.")
                return redirect("configuracoes")

    return render(
        request,
        "agenda/configuracoes.html",
        {
            "barbearia": barbearia,
            "config": config,
            "servico_form": servico_form,
            "prof_form": prof_form,
            "servicos": barbearia.servicos.all(),
            "profissionais": barbearia.profissionais.all(),
        },
    )


@login_required
@require_POST
def alternar_ativo(request, tipo, pk):
    barbearia = _barbearia(request)
    modelo = {"servico": Servico, "profissional": Profissional}.get(tipo)
    if modelo is None:
        return redirect("configuracoes")
    obj = get_object_or_404(modelo, pk=pk, barbearia=barbearia)
    obj.ativo = not obj.ativo
    obj.save()
    return redirect("configuracoes")


# ---------------------------------------------------------------- assinatura (Mercado Pago)
@login_required
def assinatura(request):
    """Mostra os planos; no POST cria a cobrança e manda para o Mercado Pago."""
    barbearia = _barbearia(request)
    planos = settings.PLANOS_PRECOS

    if request.method == "POST":
        plano = request.POST.get("plano")
        if plano not in planos:
            messages.error(request, "Plano inválido.")
            return redirect("assinatura")
        pag = Pagamento.objects.create(
            barbearia=barbearia, plano=plano, valor=planos[plano]["preco"]
        )
        try:
            return redirect(mercadopago.criar_preferencia(pag))
        except mercadopago.MercadoPagoErro:
            pag.delete()
            messages.error(
                request, "Não foi possível iniciar o pagamento agora. Tente novamente em instantes."
            )
            return redirect("assinatura")

    return render(
        request,
        "agenda/assinatura.html",
        {
            "barbearia": barbearia,
            "planos": planos,
            "pagamentos": barbearia.pagamentos.all()[:10],
        },
    )


@login_required
def assinatura_retorno(request):
    """Para onde o cliente volta depois de pagar. Confirma na API (não confia na URL)."""
    barbearia = _barbearia(request)
    payment_id = request.GET.get("payment_id") or request.GET.get("collection_id")
    if payment_id and payment_id != "null":
        try:
            pag = mercadopago.processar_pagamento(payment_id)
            if pag and pag.barbearia_id != barbearia.pk:
                pag = None  # pagamento de outra barbearia: ignora
        except mercadopago.MercadoPagoErro:
            pag = None
        if pag and pag.status == Pagamento.Status.APROVADO:
            messages.success(request, "Pagamento confirmado! Sua assinatura foi renovada.")
        elif pag and pag.status == Pagamento.Status.RECUSADO:
            messages.error(request, "Pagamento não aprovado. Tente novamente.")
        else:
            messages.info(request, "Pagamento em análise. Assim que confirmar, a assinatura é liberada.")
    else:
        messages.info(request, "Pagamento em análise. Assim que confirmar, a assinatura é liberada.")
    return redirect("assinatura")


@csrf_exempt
def webhook_mercadopago(request):
    """Notificação do Mercado Pago. Sempre consulta o pagamento na API antes de liberar."""
    tipo = request.GET.get("type") or request.GET.get("topic")
    payment_id = request.GET.get("data.id") or request.GET.get("id")
    if request.body:
        try:
            corpo = json.loads(request.body)
            tipo = tipo or corpo.get("type") or corpo.get("topic")
            payment_id = payment_id or (corpo.get("data") or {}).get("id")
        except (ValueError, AttributeError):
            pass

    if tipo == "payment" and payment_id:
        try:
            mercadopago.processar_pagamento(payment_id)
        except mercadopago.MercadoPagoErro:
            return HttpResponse(status=500)  # o MP tenta de novo mais tarde
    return HttpResponse(status=200)
