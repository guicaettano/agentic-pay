# Agente de Pagamentos (Agentic Payments)

Agente de IA que recebe um objetivo do tipo **"pague essa conta até X valor"**,
verifica saldo disponível, decide se pode executar sozinho ou precisa de
confirmação humana, e executa o pagamento (Stripe sandbox) dentro de um teto
pré-aprovado — com trilha de auditoria completa de cada decisão.

## O problema

Agentes de IA autônomos capazes de executar pagamentos são uma das fronteiras
mais quentes em fintech hoje (Stripe Agentic Commerce Protocol, Visa Trusted
Agent, Mastercard Agent Pay). O desafio não é fazer o agente "chamar uma API" —
é garantir que ele **nunca gaste além do combinado**, que **toda decisão seja
rastreável**, e que ele **não possa ser manipulado** por dados externos para
agir fora do escopo autorizado.

Este projeto implementa um agente mínimo, mas com essas três garantias.

## Arquitetura

```
agent.py              → loop principal: recebe objetivo, chama o modelo (Claude),
                         decide se cada ação pode ser executada, pede confirmação
                         humana quando necessário, chama a tool real
permissions.py        → camada de autorização: teto por ação, teto diário,
                         allowlist de ações permitidas (fail-safe: nega por padrão)
audit.py              → trilha de auditoria em SQLite: toda decisão é logada
                         (aprovada, negada, confirmada manualmente, executada, falha)
tools/stripe_tools.py → check_balance, list_pending_bills, pay_bill — wrappers
                         do Stripe sandbox, com modo dry_run automático quando
                         não há chave configurada
dashboard.py          → dashboard web para monitorar pagamentos, segurança,
                         política de autorização e trilha de auditoria
```

## Dashboard

O projeto agora inclui um dashboard web inspirado no layout e nos padrões
visuais do exemplo de dashboard do [shadcn/ui](https://ui.shadcn.com/examples/dashboard).
Ele lê diretamente a trilha SQLite usada pelo agente, então decisões e
execuções aparecem no mesmo painel sem duplicar o sistema de auditoria.

```bash
pip install -r requirements.txt
streamlit run dashboard.py
```

O dashboard possui:

- **Overview** — pagamentos executados, valor movimentado, limite restante e negações.
- **Payment activity** — visualização da atividade de pagamentos.
- **Security posture** — teto de auto-aprovação, limite diário, allowlist e fail-safe.
- **Audit Trail** — tabela filtrável de todas as decisões registradas.
- **Policy** — visão da política de autorização e ferramentas permitidas.

## Fluxo de segurança

1. O modelo decide **qual** ferramenta chamar e com quais argumentos (ex:
   pagar a conta X até R$ 200,00).
2. Antes de executar, `permissions.evaluate_action` decide se a ação roda
   sozinha ou exige confirmação humana (valor acima do teto de auto-aprovação,
   ou que ultrapasse o limite diário).
3. **Se exigir confirmação, o agente para de verdade** — pergunta ao usuário
   via terminal (`ask_human_confirmation`) e só executa com um "sim" explícito.
   Ele não insiste, não tenta valores menores para escapar do controle, e não
   decide sozinho.
4. Toda decisão é registrada na auditoria — inclusive a diferença entre
   "aprovado pela política" e "aprovado manualmente pelo usuário".
5. Pagamentos usam `idempotency_key` para evitar execução duplicada em caso
   de retry por falha de rede.

## Como rodar

```bash
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sua_chave_anthropic
export STRIPE_API_KEY=sua_chave_de_teste_stripe   # opcional

python agent.py
```

Sem `STRIPE_API_KEY`, o projeto roda em **modo dry_run**: todas as chamadas
ao Stripe retornam dados simulados, permitindo testar toda a lógica de
permissões e auditoria sem precisar de conta configurada.

## Testando a camada de segurança isoladamente

Não precisa da chave da Anthropic pra testar a parte mais importante do
projeto — permissões, confirmação humana e auditoria funcionam sozinhas:

```bash
python3 -c "
from permissions import PermissionPolicy
from agent import execute_tool

policy = PermissionPolicy()
result, spent = execute_tool(
    'pay_bill',
    {'bill_id': 'bill_001', 'amount_cents': 20000, 'payee': 'Fornecedor X'},
    policy, 0
)
print(result)
"
```

Isso vai pausar e pedir confirmação no terminal, porque R\$ 200,00 está acima
do teto de auto-aprovação padrão (R$ 100,00).

## Próximos passos (roadmap)

- [ ] Testes automatizados (pytest) cobrindo casos adversariais de permissão.
- [ ] Simulação de prompt injection via descrição de cobrança maliciosa.
- [x] Dashboard web para visualizar a trilha de auditoria.
- [ ] Integração com Pix via sandbox de Open Finance.

## Stack

- Python 3.11+
- [Anthropic API](https://docs.claude.com) (tool use)
- [Stripe](https://stripe.com/docs) (modo sandbox)
- SQLite (auditoria)
- Streamlit + Pandas (dashboard)
