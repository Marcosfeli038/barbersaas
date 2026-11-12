from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Agendamento, Barbearia, Profissional, Servico, horarios_livres

User = get_user_model()


def amanha_as(hora, minuto=0):
    dia = timezone.localdate() + timedelta(days=1)
    return timezone.make_aware(
        timezone.datetime(dia.year, dia.month, dia.day, hora, minuto)
    )


class BaseCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dono", password="senha12345")
        self.barbearia = Barbearia.objects.create(
            dono=self.user, nome="Barba Forte", slug="barba-forte",
            telefone_whatsapp="11999998888",
        )
        self.servico = Servico.objects.create(
            barbearia=self.barbearia, nome="Corte", duracao_minutos=30, preco=Decimal("40")
        )
        self.prof = Profissional.objects.create(barbearia=self.barbearia, nome="João")


class AgendamentoTests(BaseCase):
    def criar(self, inicio, **kw):
        return Agendamento.objects.create(
            barbearia=self.barbearia, profissional=self.prof, servico=self.servico,
            cliente_nome="Carlos", cliente_telefone="(11) 98888-7777", inicio=inicio, **kw,
        )

    def test_calcula_fim_pela_duracao(self):
        ag = self.criar(amanha_as(10))
        self.assertEqual(ag.fim - ag.inicio, timedelta(minutes=30))

    def test_conflito_de_horario_e_bloqueado(self):
        self.criar(amanha_as(10))
        with self.assertRaises(ValidationError):
            self.criar(amanha_as(10, 15))  # sobrepõe 10:00-10:30

    def test_horario_colado_nao_conflita(self):
        self.criar(amanha_as(10))
        self.criar(amanha_as(10, 30))  # começa quando o outro termina

    def test_cancelado_libera_horario(self):
        ag = self.criar(amanha_as(10))
        ag.status = Agendamento.Status.CANCELADO
        ag.save()
        self.criar(amanha_as(10))

    def test_horarios_livres_excluem_ocupados(self):
        self.criar(amanha_as(10))
        dia = timezone.localdate() + timedelta(days=1)
        livres = horarios_livres(self.barbearia, self.prof, self.servico, dia)
        horas = {timezone.localtime(h).strftime("%H:%M") for h in livres}
        self.assertNotIn("10:00", horas)
        self.assertIn("09:00", horas)
        self.assertIn("10:30", horas)
        self.assertNotIn("19:00", horas)  # barbearia fecha às 19:00

    def test_link_whatsapp(self):
        ag = self.criar(amanha_as(10))
        self.assertTrue(ag.link_whatsapp.startswith("https://wa.me/5511988887777?text="))
        self.assertIn("Barba%20Forte", ag.link_whatsapp)


class FluxoPublicoTests(BaseCase):
    def test_reserva_completa(self):
        inicio = amanha_as(14)
        r = self.client.post(
            reverse("confirmar_reserva", args=["barba-forte"]),
            {
                "servico": self.servico.pk, "profissional": self.prof.pk,
                "inicio": inicio.isoformat(),
                "cliente_nome": "Pedro", "cliente_telefone": "11977776666",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Agendamento.objects.count(), 1)

    def test_reserva_duplicada_e_recusada(self):
        dados = {
            "servico": self.servico.pk, "profissional": self.prof.pk,
            "inicio": amanha_as(14).isoformat(),
            "cliente_nome": "Pedro", "cliente_telefone": "11977776666",
        }
        url = reverse("confirmar_reserva", args=["barba-forte"])
        self.client.post(url, dados)
        r = self.client.post(url, dados)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Agendamento.objects.count(), 1)

    def test_assinatura_expirada_bloqueia_pagina_publica(self):
        self.barbearia.assinatura_ativa_ate = timezone.localdate() - timedelta(days=1)
        self.barbearia.save()
        r = self.client.get(reverse("reservar", args=["barba-forte"]))
        self.assertTemplateUsed(r, "agenda/indisponivel.html")

    def test_pagina_publica_lista_horarios(self):
        dia = (timezone.localdate() + timedelta(days=1)).isoformat()
        r = self.client.get(
            reverse("reservar", args=["barba-forte"]),
            {"servico": self.servico.pk, "profissional": self.prof.pk, "dia": dia},
        )
        self.assertContains(r, "09:00")


class PainelTests(BaseCase):
    def test_painel_exige_login(self):
        r = self.client.get(reverse("painel"))
        self.assertEqual(r.status_code, 302)

    def test_cadastro_cria_barbearia_com_teste(self):
        r = self.client.post(
            reverse("cadastro"),
            {
                "username": "novo", "email": "n@x.com",
                "password1": "Senha-forte-123", "password2": "Senha-forte-123",
                "nome_barbearia": "Corte & Cia", "telefone_whatsapp": "11911112222",
            },
        )
        self.assertRedirects(r, reverse("painel"))
        b = Barbearia.objects.get(slug="corte-cia")
        self.assertIsNotNone(b.assinatura_ativa_ate)

    def test_dono_nao_altera_agendamento_de_outra_barbearia(self):
        outro = User.objects.create_user("outro", password="senha12345")
        b2 = Barbearia.objects.create(dono=outro, nome="Outra", slug="outra")
        s2 = Servico.objects.create(barbearia=b2, nome="Corte", preco=30)
        p2 = Profissional.objects.create(barbearia=b2, nome="Zé")
        ag = Agendamento.objects.create(
            barbearia=b2, profissional=p2, servico=s2,
            cliente_nome="X", cliente_telefone="11900000000", inicio=amanha_as(11),
        )
        self.client.login(username="dono", password="senha12345")
        r = self.client.post(reverse("alterar_status", args=[ag.pk, "cancelado"]))
        self.assertEqual(r.status_code, 404)
        ag.refresh_from_db()
        self.assertEqual(ag.status, "marcado")

    def test_painel_mostra_agendamentos_do_dia(self):
        Agendamento.objects.create(
            barbearia=self.barbearia, profissional=self.prof, servico=self.servico,
            cliente_nome="Visível", cliente_telefone="11900000000",
            inicio=timezone.now() + timedelta(hours=1),
        )
        self.client.login(username="dono", password="senha12345")
        dia = timezone.localtime(timezone.now() + timedelta(hours=1)).date().isoformat()
        r = self.client.get(reverse("painel"), {"dia": dia})
        self.assertContains(r, "Visível")


# ------------------------------------------------------------ Mercado Pago
from unittest import mock

from django.test import override_settings

from .models import Pagamento


@override_settings(MERCADOPAGO_ACCESS_TOKEN="TEST-token", SITE_URL="https://exemplo.com")
class MercadoPagoTests(BaseCase):
    def _pagamento(self, valor="39.90", plano="basico"):
        return Pagamento.objects.create(barbearia=self.barbearia, plano=plano, valor=valor)

    def _mp_resposta(self, pag, status="approved", valor=39.90, pid=999):
        return {"id": pid, "status": status, "external_reference": str(pag.pk),
                "transaction_amount": valor}

    @mock.patch("agenda.mercadopago.requests.post")
    def test_assinar_redireciona_para_checkout(self, post):
        post.return_value.json.return_value = {"id": "pref1", "init_point": "https://mp.com/pagar"}
        post.return_value.raise_for_status.return_value = None
        self.client.login(username="dono", password="senha12345")
        r = self.client.post(reverse("assinatura"), {"plano": "basico"})
        self.assertRedirects(r, "https://mp.com/pagar", fetch_redirect_response=False)
        pag = Pagamento.objects.get()
        self.assertEqual(pag.mp_preference_id, "pref1")
        enviado = post.call_args.kwargs["json"]
        self.assertEqual(enviado["external_reference"], str(pag.pk))
        self.assertEqual(enviado["items"][0]["unit_price"], 39.90)

    def test_plano_invalido(self):
        self.client.login(username="dono", password="senha12345")
        self.client.post(reverse("assinatura"), {"plano": "gratis-pra-sempre"})
        self.assertEqual(Pagamento.objects.count(), 0)

    @mock.patch("agenda.mercadopago.requests.get")
    def test_webhook_aprovado_renova_assinatura(self, get):
        pag = self._pagamento()
        get.return_value.json.return_value = self._mp_resposta(pag)
        get.return_value.raise_for_status.return_value = None
        r = self.client.post(
            reverse("webhook_mercadopago"),
            data='{"type": "payment", "data": {"id": "999"}}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        pag.refresh_from_db()
        self.barbearia.refresh_from_db()
        self.assertEqual(pag.status, "aprovado")
        self.assertEqual(self.barbearia.plano, "basico")
        self.assertEqual(
            self.barbearia.assinatura_ativa_ate, timezone.localdate() + timedelta(days=30)
        )

    @mock.patch("agenda.mercadopago.requests.get")
    def test_webhook_repetido_nao_renova_duas_vezes(self, get):
        pag = self._pagamento()
        get.return_value.json.return_value = self._mp_resposta(pag)
        get.return_value.raise_for_status.return_value = None
        for _ in range(2):
            self.client.post(reverse("webhook_mercadopago") + "?type=payment&data.id=999")
        self.barbearia.refresh_from_db()
        self.assertEqual(
            self.barbearia.assinatura_ativa_ate, timezone.localdate() + timedelta(days=30)
        )

    @mock.patch("agenda.mercadopago.requests.get")
    def test_valor_menor_nao_libera(self, get):
        pag = self._pagamento(valor="79.90", plano="pro")
        get.return_value.json.return_value = self._mp_resposta(pag, valor=1.00)
        get.return_value.raise_for_status.return_value = None
        self.client.post(reverse("webhook_mercadopago") + "?type=payment&data.id=999")
        pag.refresh_from_db()
        self.assertEqual(pag.status, "pendente")

    @mock.patch("agenda.mercadopago.requests.get")
    def test_pagamento_recusado(self, get):
        pag = self._pagamento()
        get.return_value.json.return_value = self._mp_resposta(pag, status="rejected")
        get.return_value.raise_for_status.return_value = None
        self.client.post(reverse("webhook_mercadopago") + "?type=payment&data.id=999")
        pag.refresh_from_db()
        self.assertEqual(pag.status, "recusado")

    @mock.patch("agenda.mercadopago.requests.get")
    def test_renovacao_soma_a_partir_do_vencimento(self, get):
        self.barbearia.assinatura_ativa_ate = timezone.localdate() + timedelta(days=10)
        self.barbearia.save()
        pag = self._pagamento()
        get.return_value.json.return_value = self._mp_resposta(pag)
        get.return_value.raise_for_status.return_value = None
        self.client.post(reverse("webhook_mercadopago") + "?type=payment&data.id=999")
        self.barbearia.refresh_from_db()
        self.assertEqual(
            self.barbearia.assinatura_ativa_ate, timezone.localdate() + timedelta(days=40)
        )

    @mock.patch("agenda.mercadopago.requests.get")
    def test_retorno_de_outra_barbearia_e_ignorado(self, get):
        outro = User.objects.create_user("outro", password="senha12345")
        b2 = Barbearia.objects.create(dono=outro, nome="Outra", slug="outra")
        pag2 = Pagamento.objects.create(barbearia=b2, plano="basico", valor="39.90")
        get.return_value.json.return_value = self._mp_resposta(pag2)
        get.return_value.raise_for_status.return_value = None
        self.client.login(username="dono", password="senha12345")
        self.client.get(reverse("assinatura_retorno"), {"payment_id": "999"})
        self.barbearia.refresh_from_db()
        self.assertIsNone(self.barbearia.assinatura_ativa_ate)


class SemBarbeariaTests(TestCase):
    def test_superusuario_sem_barbearia_ve_tela_explicativa(self):
        User.objects.create_superuser("admin", password="senha12345")
        self.client.login(username="admin", password="senha12345")
        for nome in ("painel", "assinatura", "configuracoes"):
            r = self.client.get(reverse(nome))
            self.assertContains(r, "ainda não tem uma barbearia")
