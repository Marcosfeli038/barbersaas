# BarberAgenda — SaaS de agendamento para barbearias

MVP multiempresa em Django. Cada barbearia tem conta própria, painel e um link público de agendamento (`/b/<slug>/`). O lembrete por WhatsApp usa link `wa.me` (grátis, o dono envia com um clique).

## Rodar localmente

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser   # acesso ao /admin/ (você, dono do SaaS)
python manage.py runserver
```

Sem variáveis de ambiente, usa SQLite. Para PostgreSQL:

```bash
export DB_NAME=barberagenda DB_USER=postgres DB_PASSWORD=senha DB_HOST=localhost DB_PORT=5432
python manage.py migrate
```

## Fluxo

1. Dono cria conta em `/cadastro/` (14 dias de teste) e recebe a barbearia pronta.
2. Em **Configurações** cadastra serviços, profissionais e horário de funcionamento.
3. Compartilha o link `/b/<slug>/` com os clientes.
4. Clientes escolhem serviço, profissional e horário livre; conflitos são bloqueados.
5. No **Painel**, o dono vê a agenda do dia, conclui/cancela e clica em *Lembrar no WhatsApp*.

## Cobrança (próximos passos)

O modelo `Barbearia` já tem `plano` e `assinatura_ativa_ate`. Quando o período vence, a página pública pausa. Falta ligar um gateway (Mercado Pago, Stripe ou Asaas) com webhook que atualize `assinatura_ativa_ate`. Você também pode estender a assinatura manualmente pelo `/admin/`.

## Antes de ir para produção

- Defina `SECRET_KEY` por variável de ambiente, `DEBUG=False` e `ALLOWED_HOSTS` no `config/settings.py`.
- Use PostgreSQL, HTTPS e um servidor WSGI (gunicorn) com arquivos estáticos via WhiteNoise ou nginx.
- Peça aos clientes consentimento para receber mensagens e trate telefones conforme a LGPD.

## Testes

```bash
python manage.py test
```

## Mercado Pago (cobrança)

1. Crie uma conta em mercadopago.com.br e, em *Seu negócio > Configurações > Credenciais*, pegue o **Access Token** (use o de TESTE primeiro).
2. Defina as variáveis de ambiente (PowerShell):
   ```powershell
   $env:MERCADOPAGO_ACCESS_TOKEN="TEST-xxxxxxxx"
   $env:SITE_URL="https://seu-dominio-ou-ngrok"
   ```
3. O Mercado Pago precisa alcançar `SITE_URL/webhooks/mercadopago/`. Em `localhost` ele NÃO consegue; use [ngrok](https://ngrok.com) (`ngrok http 8000`) e coloque a URL https dele em `SITE_URL` (e em `ALLOWED_HOSTS`).
4. No painel do Mercado Pago, em *Webhooks/Notificações*, ative o evento **Pagamentos** (a URL também é enviada em cada cobrança).
5. Preços em `PLANOS_PRECOS` no `config/settings.py`; cada pagamento aprovado renova `DIAS_POR_PAGAMENTO` (30) dias.

O sistema nunca confia no que chega no webhook: ele consulta o pagamento na API do Mercado Pago, confere o valor e só então renova (de forma idempotente).
