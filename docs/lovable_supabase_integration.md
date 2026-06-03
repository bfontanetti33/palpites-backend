# Integração Supabase × Lovable — Palpites da IA

## 1. Conectar Supabase ao projeto Lovable

1. Acesse **palpitesdaia.lovable.app** → editor do Lovable
2. Clique em **Settings** (ícone de engrenagem)
3. Vá em **Integrations → Supabase**
4. Clique **Connect Supabase**
5. Cole os valores:
   - **Project URL**: `https://jwzvuixvuptazfyasmlm.supabase.co`
   - **Anon Key**: a chave do `.env.example` (SUPABASE_KEY)
6. Clique **Save** — o Lovable injeta automaticamente o cliente Supabase

---

## 2. Ativar autenticação (login/cadastro por e-mail)

No Lovable, o Supabase Auth já vem pré-configurado após a conexão.

### Criar tela de login
```typescript
import { supabase } from "@/integrations/supabase/client";

// Cadastro
const { error } = await supabase.auth.signUp({
  email: "usuario@email.com",
  password: "senha123",
});

// Login
const { data, error } = await supabase.auth.signInWithPassword({
  email: "usuario@email.com",
  password: "senha123",
});

// Logout
await supabase.auth.signOut();

// Sessão atual
const { data: { session } } = await supabase.auth.getSession();
```

### Criar usuário na tabela `users` após cadastro
No Supabase Dashboard → **Database → Functions**, crie um trigger:
```sql
-- Função que cria registro em users quando alguém se cadastra no Auth
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger AS $$
BEGIN
  INSERT INTO public.users (id, email)
  VALUES (NEW.id, NEW.email)
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger no auth.users
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
```

---

## 3. Proteger rotas premium no frontend

### Hook para verificar acesso
```typescript
// hooks/usePremiumAccess.ts
import { useEffect, useState } from "react";
import { supabase } from "@/integrations/supabase/client";

export function usePremiumAccess() {
  const [loading, setLoading] = useState(true);
  const [temAcesso, setTemAcesso] = useState(false);
  const [usuario, setUsuario] = useState(null);

  useEffect(() => {
    async function verificar() {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) { setLoading(false); return; }

      const { data } = await supabase
        .from("users")
        .select("is_premium, premium_until, avulso_credits")
        .eq("id", session.user.id)
        .single();

      const premiumAtivo = data?.is_premium &&
        (!data.premium_until || new Date(data.premium_until) > new Date());
      const temCredito = (data?.avulso_credits ?? 0) > 0;

      setUsuario(session.user);
      setTemAcesso(premiumAtivo || temCredito);
      setLoading(false);
    }
    verificar();
  }, []);

  return { loading, temAcesso, usuario };
}
```

### Proteger componente de recomendação
```typescript
// components/RecomendacaoIA.tsx
import { usePremiumAccess } from "@/hooks/usePremiumAccess";
import { useNavigate } from "react-router-dom";

export function RecomendacaoIA({ slug }: { slug: string }) {
  const { loading, temAcesso, usuario } = usePremiumAccess();
  const navigate = useNavigate();

  if (loading) return <Spinner />;

  if (!usuario) {
    return <BotaoLogin onClick={() => navigate("/login")} />;
  }

  if (!temAcesso) {
    return <BotaoPlanos onClick={() => navigate("/planos")} />;
  }

  return <ConteudoPremium slug={slug} />;
}
```

---

## 4. Passar JWT token do Supabase para o backend

```typescript
// utils/api.ts
import { supabase } from "@/integrations/supabase/client";

const API_BASE = "https://palpites-backend-production.up.railway.app";

export async function buscarRecomendacao(slug: string) {
  const { data: { session } } = await supabase.auth.getSession();

  const res = await fetch(`${API_BASE}/api/v1/copa/jogos/${slug}/recomendacao`, {
    headers: {
      "Authorization": `Bearer ${session?.access_token}`,
      "Content-Type": "application/json",
    },
  });

  if (res.status === 403) throw new Error("Sem acesso premium");
  if (!res.ok) throw new Error("Erro na API");
  return res.json();
}

export async function buscarPartida(slug: string) {
  // Endpoint público — sem token
  const res = await fetch(`${API_BASE}/api/v1/copa/jogos/${slug}`);
  return res.json();
}
```

---

## 5. Fluxo completo de compra

```
Usuário acessa /planos
    ↓
Clica "Assinar Premium" ou "Comprar Análise Avulsa"
    ↓
Frontend cria preferência no Mercado Pago via backend
(ou redireciona para link MP com external_reference="email|plano")
    ↓
Usuário paga no Mercado Pago
    ↓
MP envia webhook para:
  POST /api/v1/webhooks/mercadopago
    ↓
Backend verifica pagamento + atualiza Supabase:
  - Plano mensal → users.is_premium=true, premium_until=hoje+30d
  - Avulso      → users.avulso_credits += 1
    ↓
Backend envia notificação Telegram: "💰 Nova conversão!"
    ↓
Usuário faz login/refresh → frontend lê is_premium=true → acesso liberado
```

### external_reference no Mercado Pago
Configure o `external_reference` no formato `"email|plano"`:
- Plano mensal: `"user@email.com|mensal"`
- Análise avulsa: `"user@email.com|avulso"`

O webhook do backend usa esse campo para identificar o usuário e o plano.

---

## Row Level Security (RLS) no Supabase

Ative RLS para proteger a tabela `users`:

```sql
-- Habilita RLS
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- Usuário só lê os próprios dados
CREATE POLICY "users_select_own" ON users
  FOR SELECT USING (auth.uid() = id);

-- Usuário só atualiza os próprios dados
CREATE POLICY "users_update_own" ON users
  FOR UPDATE USING (auth.uid() = id);

-- Apenas service_role pode inserir (via backend/trigger)
CREATE POLICY "users_insert_service" ON users
  FOR INSERT WITH CHECK (false); -- bloqueado para anon/authenticated

-- RLS na usage_log
ALTER TABLE usage_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "usage_log_select_own" ON usage_log
  FOR SELECT USING (auth.uid() = user_id);
```
