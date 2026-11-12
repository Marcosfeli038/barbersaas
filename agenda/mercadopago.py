"""Integração mínima com o Mercado Pago (Checkout Pro), sem SDK.

Fluxo:
1. criar_preferencia(): cria o link de pagamento (Pix, cartão, boleto).
2. O cliente paga no site do Mercado Pago.
3. O Mercado Pago chama o nosso webhook; nós NÃO confiamos no corpo da
   notificação: consultamos o pagamento na API e só então liberamos.
"""
from datetime import timedelta
import os

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Pagamento

API = "https://api.mercadopago.com"
TIMEOUT = 15


class MercadoPagoErro(Exception):
    pass


def _headers():
    # Tenta pegar do settings ou usa a chave de produção fornecida diretamente se não configurada
    token = getattr(settings, "MERCADOPAGO_ACCESS_TOKEN", None) or os.getenv(
        "MERCADOPAGO_ACCESS_TOKEN", 
        "APP_USR-5655878146174616-111118-1ca86c3e226c250be19171173470d7b9-2235938738"
    )
    if not token:
        raise MercadoPagoErro("MERCADOPAGO_ACCESS_TOKEN não configurado.")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def criar_preferencia(pagamento):
    """Cria a preferência de pagamento e devolve a URL (init_point) para redirecionar."""
    base = settings.SITE_URL.rstrip("/")
    dados = {
        "items": [
            {
                "title": f"BarberAgenda - plano {pagamento.get_plano_display()} (1 mês)",
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": float(pagamento.valor),
            }
        ],
        "external_reference": str(pagamento.pk),
        "back_urls": {
            "success": f"{base}/painel/assinatura/retorno/",
            "pending": f"{base}/painel/assinatura/retorno/",
            "failure": f"{base}/painel/assinatura/retorno/",
        },
        "notification_url": f"{base}/webhooks/mercadopago/",
    }
    # auto_return só é aceito pelo MP com URLs https públicas
    if base.startswith("https://"):
        dados["auto_return"] = "approved"

    try:
        r = requests.post(
            f"{API}/checkout/preferences", json=dados, headers=_headers(), timeout=TIMEOUT
        )
        r.raise_for_status()
    except requests.RequestException as e:
        raise MercadoPagoErro(f"Falha ao criar pagamento: {e}") from e

    resp = r.json()
    pagamento.mp_preference_id = resp.get("id", "")
    pagamento.save(update_fields=["mp_preference_id"])
    return resp["init_point"]


def buscar_pagamento(payment_id):
    try:
        r = requests.get(
            f"{API}/v1/payments/{payment_id}", headers=_headers(), timeout=TIMEOUT
        )
        r.raise_for_status()
    except requests.RequestException as e:
        raise MercadoPagoErro(f"Falha ao consultar pagamento: {e}") from e
    return r.json()


def processar_pagamento(payment_id):
    """Consulta o pagamento no MP e, se aprovado, renova a assinatura (idempotente).

    Retorna o objeto Pagamento atualizado, ou None se não for nosso.
    """
    mp = buscar_pagamento(payment_id)
    ref = mp.get("external_reference")
    if not ref or not str(ref).isdigit():
        return None

    with transaction.atomic():
        try:
            pag = Pagamento.objects.select_for_update().select_related("barbearia").get(pk=int(ref))
        except Pagamento.DoesNotExist:
            return None

        status_mp = mp.get("status")
        if status_mp == "approved":
            if pag.status == Pagamento.Status.APROVADO:
                return pag  # já processado (webhook repetido)
            # confere o valor para evitar liberar plano com pagamento menor
            if float(mp.get("transaction_amount", 0)) + 0.001 < float(pag.valor):
                return pag
            pag.status = Pagamento.Status.APROVADO
            pag.mp_payment_id = str(mp["id"])
            pag.aprovado_em = timezone.now()
            pag.save()
            _renovar(pag)
        elif status_mp in ("rejected", "cancelled"):
            if pag.status == Pagamento.Status.PENDENTE:
                pag.status = Pagamento.Status.RECUSADO
                pag.save(update_fields=["status"])
        return pag


def _renovar(pag):
    b = pag.barbearia
    hoje = timezone.localdate()
    base = b.assinatura_ativa_ate if b.assinatura_ativa_ate and b.assinatura_ativa_ate > hoje else hoje
    b.assinatura_ativa_ate = base + timedelta(days=settings.DIAS_POR_PAGAMENTO)
    b.plano = pag.plano
    b.save(update_fields=["assinatura_ativa_ate", "plano"])