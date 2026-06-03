# Mercado Pago — Setup de Pagamentos

## 1. Criar conta e habilitar recebimentos

1. Acesse **mercadopago.com.br** → Criar conta (ou use a conta existente)
2. Vá em **Sua conta → Conta Mercado Pago → Ativar para receber pagamentos**
3. Informe seus dados pessoais/CPF para verificação
4. Confirme o e-mail e número de telefone

---

## 2. Criar os produtos

### Plano Mensal — R$ 19,90
No painel MP → **Cobranças → Link de pagamento → Criar link**:
- Nome: `Palpites da IA — Premium Mensal`
- Preço: `R$ 19,90`
- Referência externa: `{email_do_comprador}|mensal` ← configurar via API
- Descrição: `Acesso ilimitado a recomendações de IA por 30 dias`

### Análise Avulsa — R$ 2,90
- Nome: `Palpites da IA — Análise Avulsa`
- Preço: `R$ 2,90`
- Referência externa: `{email_do_comprador}|avulso`
- Descrição: `1 análise detalhada com IA para o jogo escolhido`

> **Dica**: Para setar o `external_reference` dinamicamente (com o e-mail do usuário), use a API de Preferências do MP no backend, não o link estático.

---

## 3. Configurar o webhook

### No painel Mercado Pago:
1. Acesse **Seu negócio → Configurações → Webhooks**
2. Clique **+ Adicionar webhook**
3. Configure:
   - **URL**: `https://palpites-backend-production.up.railway.app/api/v1/webhooks/mercadopago`
   - **Eventos**: marque `Pagamentos`
   - **Versão**: v2
4. Clique **Salvar**
5. MP mostrará uma **Signature Secret** — copie para o Railway

### Testar o webhook:
No mesmo painel, clique **Simular evento** para enviar um pagamento de teste.

---

## 4. Variáveis para adicionar no Railway

No Railway → seu serviço → **Variables**:

```
MERCADOPAGO_ACCESS_TOKEN=APP_USR-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
MERCADOPAGO_WEBHOOK_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Como obter o ACCESS_TOKEN:
1. Painel MP → **Sua conta → Credenciais**
2. Em "Credenciais de produção" → copie o **Access Token**
3. (Para testes: use as "Credenciais de teste" — começam com `TEST-`)

### Como obter o WEBHOOK_SECRET:
- É gerado automaticamente quando você salva o webhook (passo 3)
- Aparece como "Chave secreta" na lista de webhooks

---

## 5. Testar em sandbox antes do go live

### Criar usuários de teste:
1. Painel MP → **Sua conta → Credenciais → Credenciais de teste**
2. Role até "Usuários de teste" → Criar 2 usuários:
   - Vendedor (sua conta teste)
   - Comprador (quem vai pagar)

### Processo de teste:
```bash
# 1. Use as credenciais de TESTE no Railway (TEST-xxx)

# 2. Gere uma preferência de pagamento via API:
curl -X POST https://api.mercadopago.com/checkout/preferences \
  -H "Authorization: Bearer TEST-seu-access-token" \
  -H "Content-Type: application/json" \
  -d '{
    "items": [{
      "title": "Premium Mensal",
      "quantity": 1,
      "unit_price": 19.90
    }],
    "external_reference": "teste@email.com|mensal",
    "back_urls": {
      "success": "https://palpitesdaia.lovable.app/sucesso",
      "failure": "https://palpitesdaia.lovable.app/falha"
    },
    "auto_return": "approved"
  }'

# 3. Abra o init_point retornado no browser
# 4. Use o cartão de teste: 5031 7557 3453 0604 / CVV: 123 / Venc: 11/25
# 5. Confirme que o webhook chegou no Railway (ver logs)
# 6. Confirme que o Supabase foi atualizado (is_premium=true)
```

### Cartões de teste (aprovação):
| Bandeira | Número | CVV | Vencimento |
|----------|--------|-----|------------|
| Mastercard | `5031 7557 3453 0604` | `123` | `11/25` |
| Visa | `4235 6477 2802 5682` | `123` | `11/25` |

### Cartão para reprovar:
| Tipo | Número |
|------|--------|
| Recusado | `4000 0000 0000 0002` |

---

## 6. Go live checklist

- [ ] Conta MP verificada com CPF/CNPJ
- [ ] Conta bancária vinculada para saques
- [ ] Credenciais de produção (não teste) no Railway
- [ ] Webhook apontando para URL de produção
- [ ] Teste real com R$ 0,01 feito e recebido
- [ ] Supabase atualizado corretamente após pagamento real
- [ ] Notificação Telegram chegando após conversão
