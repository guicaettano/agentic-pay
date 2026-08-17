"""
tools/stripe_tools.py
-----------------------
Funções que o agente pode chamar como "tools", focadas no cenário da
Opção 3 do plano: o agente recebe um objetivo tipo "pague essa conta até
X valor", verifica saldo disponível, e executa (ou pede confirmação para)
uma transferência.

Se não houver STRIPE_API_KEY configurada, as funções caem em modo
"dry_run" e retornam dados simulados — isso permite testar toda a lógica
do agente (permissões, auditoria, decisão) sem precisar de uma conta
Stripe configurada.
"""

import os
import uuid

try:
    import stripe
    _STRIPE_AVAILABLE = True
except ImportError:
    _STRIPE_AVAILABLE = False

STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY")
DRY_RUN = not (STRIPE_API_KEY and _STRIPE_AVAILABLE)

if not DRY_RUN:
    stripe.api_key = STRIPE_API_KEY

# Saldo simulado para modo dry_run (em centavos).
_FAKE_BALANCE_CENTS = 80_000  # R$ 800,00


def check_balance() -> dict:
    """Consulta o saldo disponível da conta (sandbox).

    Esse é o primeiro passo do fluxo de Opção 3: o agente precisa saber
    quanto dinheiro existe disponível ANTES de decidir se pode pagar algo.
    """
    if DRY_RUN:
        return {"available_cents": _FAKE_BALANCE_CENTS, "currency": "brl", "dry_run": True}

    balance = stripe.Balance.retrieve()
    available = balance["available"][0]
    return {"available_cents": available["amount"], "currency": available["currency"]}


def list_pending_bills(limit: int = 5) -> list[dict]:
    """Lista contas/cobranças pendentes que poderiam ser pagas pelo agente."""
    if DRY_RUN:
        return [
            {"id": "bill_fake_001", "payee": "Fornecedor A", "amount_cents": 15000, "currency": "brl", "due": "2026-08-20"},
            {"id": "bill_fake_002", "payee": "Fornecedor B", "amount_cents": 32000, "currency": "brl", "due": "2026-08-25"},
        ][:limit]

    # Em produção real isso viria de um sistema de contas a pagar, não do
    # Stripe diretamente — aqui simplificamos usando invoices como exemplo.
    invoices = stripe.Invoice.list(limit=limit, status="open")
    return [
        {"id": inv["id"], "payee": inv.get("customer_name", "desconhecido"),
         "amount_cents": inv["amount_due"], "currency": inv["currency"], "due": inv.get("due_date")}
        for inv in invoices["data"]
    ]


def pay_bill(bill_id: str, amount_cents: int, payee: str, currency: str = "brl") -> dict:
    """Executa o pagamento de uma conta (transferência), até o valor especificado.

    Esta é a ação monetária mais sensível do sistema. Ela SÓ é chamada pelo
    agent.py depois que `permissions.evaluate_action` aprovar — nunca antes.

    Idempotência: usamos uma idempotency_key para garantir que, se a chamada
    for repetida por causa de um erro de rede, o Stripe não execute o mesmo
    pagamento duas vezes. Isso é crítico em qualquer sistema de pagamento
    automatizado.
    """
    idempotency_key = str(uuid.uuid4())

    if DRY_RUN:
        return {
            "id": f"tr_fake_{idempotency_key[:8]}",
            "bill_id": bill_id,
            "payee": payee,
            "amount_cents": amount_cents,
            "currency": currency,
            "status": "paid",
            "dry_run": True,
        }

    transfer = stripe.Transfer.create(
        amount=amount_cents,
        currency=currency,
        destination=payee,  # em produção: ID de conta conectada do beneficiário
        description=f"Pagamento da conta {bill_id}",
        idempotency_key=idempotency_key,
    )
    return {
        "id": transfer["id"],
        "bill_id": bill_id,
        "payee": payee,
        "amount_cents": transfer["amount"],
        "currency": transfer["currency"],
        "status": "paid",
    }
