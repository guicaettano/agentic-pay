"""
permissions.py
---------------
O coração do "trust layer" do agente: define o que ele pode decidir sozinho
e o que precisa de confirmação humana explícita.

"""

from dataclasses import dataclass


@dataclass
class PermissionPolicy:
    """Política de autorização do agente.

    auto_approve_limit_cents: qualquer ação até esse valor é executada
        sem intervenção humana.
    daily_limit_cents: soma máxima que o agente pode movimentar em um
        único dia, mesmo que cada ação individual esteja dentro do limite.
    allowed_actions: lista de nomes de ações que o agente tem permissão
        de executar. Qualquer ação fora dessa lista é negada por padrão
        (fail-safe: nega o que não foi explicitamente permitido).
    """

    auto_approve_limit_cents: int = 10_000       # R$ 100,00 por padrão
    daily_limit_cents: int = 50_000               # R$ 500,00 por dia
    allowed_actions: tuple = (
        "check_balance",
        "list_pending_bills",
        "pay_bill",
    )


class PermissionDenied(Exception):
    """Levantado quando uma ação não pode ser autorizada automaticamente."""
    pass


def evaluate_action(action: str, amount_cents: int, spent_today_cents: int,
                     policy: PermissionPolicy) -> dict:
    """Avalia se uma ação pode ser aprovada automaticamente.

    Retorna um dict com a decisão. Nunca lança exceção para o fluxo normal —
    isso permite ao agente lidar com a negação de forma controlada, em vez
    de quebrar a execução.
    """

    if action not in policy.allowed_actions:
        return {
            "approved": False,
            "requires_confirmation": False,
            "reason": f"Ação '{action}' não está na lista de ações permitidas.",
        }

    # Ações que não movimentam dinheiro (ex: listar transações) são
    # sempre aprovadas, desde que estejam na allowlist.
    if amount_cents is None:
        return {"approved": True, "requires_confirmation": False, "reason": "Ação sem valor monetário."}

    if amount_cents > policy.auto_approve_limit_cents:
        return {
            "approved": False,
            "requires_confirmation": True,
            "reason": (
                f"Valor de {amount_cents / 100:.2f} excede o limite de "
                f"auto-aprovação ({policy.auto_approve_limit_cents / 100:.2f}). "
                "Confirmação humana necessária."
            ),
        }

    if spent_today_cents + amount_cents > policy.daily_limit_cents:
        return {
            "approved": False,
            "requires_confirmation": True,
            "reason": (
                f"Executar essa ação ultrapassaria o limite diário "
                f"({policy.daily_limit_cents / 100:.2f}). Confirmação humana necessária."
            ),
        }

    return {"approved": True, "requires_confirmation": False, "reason": "Dentro da política de auto-aprovação."}
