"""
agent.py
---------
Agente de pagamentos: recebe um objetivo em linguagem
natural do tipo "pague essa conta até X valor", verifica saldo, decide se
pode executar sozinho ou se precisa de confirmação humana, e só então
executa a transferência — dentro de um teto pré-aprovado.

Fluxo de segurança (o que mais importa aqui):
  1. O modelo decide QUAL ferramenta chamar e com quais argumentos.
  2. Antes de executar, `permissions.evaluate_action` decide se a ação
     pode rodar sozinha ou precisa de confirmação humana.
  3. Se precisar de confirmação, o agente PARA e pergunta de verdade ao
     usuário (não decide sozinho, não insiste, não tenta valores menores
     pra escapar do controle).
  4. Toda decisão (aprovada, negada, confirmada, executada, falha) é
     registrada na trilha de auditoria.
  5. O resultado real da execução (não a intenção do modelo) é o que
     volta pro modelo continuar o raciocínio.

Rodar:
    cp .env.example .env
    # edite o .env com sua chave da OpenAI (OPENAI_API_KEY) e, opcionalmente,
    # a chave restrita do Stripe (STRIPE_API_KEY)
    python agent.py
"""

import json
import os

from dotenv import load_dotenv

load_dotenv()  # precisa rodar ANTES de importar tools.stripe_tools, que lê
                # STRIPE_API_KEY do ambiente assim que é importado.

from audit import init_db, log_event
from permissions import PermissionPolicy, evaluate_action
from tools import stripe_tools

MODEL = "gpt-4o"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_balance",
            "description": "Consulta o saldo disponível da conta antes de autorizar qualquer pagamento.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_pending_bills",
            "description": "Lista contas/cobranças pendentes que podem ser pagas.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "Quantidade de contas a listar."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pay_bill",
            "description": (
                "Executa o pagamento de uma conta específica, até um valor determinado. "
                "Ação monetária sensível — passa pela camada de permissões e pode exigir "
                "confirmação humana antes de ser executada."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bill_id": {"type": "string", "description": "ID da conta a pagar."},
                    "amount_cents": {"type": "integer", "description": "Valor a pagar, em centavos."},
                    "payee": {"type": "string", "description": "Nome ou ID do beneficiário."},
                    "currency": {"type": "string", "description": "Moeda, ex: 'brl'."},
                },
                "required": ["bill_id", "amount_cents", "payee"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "check_balance": stripe_tools.check_balance,
    "list_pending_bills": stripe_tools.list_pending_bills,
    "pay_bill": stripe_tools.pay_bill,
}

SYSTEM_PROMPT = """Você é um agente financeiro que paga contas em nome de uma empresa,
usando o Stripe em modo sandbox.

Regras importantes:
- Antes de pagar qualquer conta, verifique o saldo disponível.
- Você NUNCA deve tentar contornar limites de valor, dividir um pagamento em partes
  menores, ou repetir uma ação negada fingindo que é outra coisa, para escapar
  da necessidade de confirmação humana.
- Se uma ação exigir confirmação humana, explique isso claramente ao usuário e
  aguarde a decisão — não insista.
- Seja direto e objetivo nas explicações, sem inventar dados que não vieram das
  ferramentas.
"""


def ask_human_confirmation(action: str, tool_input: dict, reason: str) -> bool:
    """Pausa a execução e pede confirmação humana real via terminal.

    Em uma versão com interface (web/CLI mais rica), isso viraria uma
    notificação/aprovação assíncrona. Aqui, para o escopo do projeto,
    fica como input() direto — mas o ponto importante é que a decisão
    NUNCA é tomada pelo próprio agente.
    """
    print("\n--- CONFIRMAÇÃO HUMANA NECESSÁRIA ---")
    print(f"Ação: {action}")
    print(f"Detalhes: {json.dumps(tool_input, ensure_ascii=False)}")
    print(f"Motivo: {reason}")
    resposta = input("Autorizar essa ação? (s/n): ").strip().lower()
    return resposta == "s"


def execute_tool(name: str, tool_input: dict, policy: PermissionPolicy, spent_today_cents: int) -> tuple[dict, int]:
    """Executa uma tool respeitando a política de permissões.

    Retorna (resultado, novo_spent_today_cents).
    """
    amount_cents = tool_input.get("amount_cents") if name == "pay_bill" else None

    decision = evaluate_action(
        action=name,
        amount_cents=amount_cents,
        spent_today_cents=spent_today_cents,
        policy=policy,
    )

    if not decision["approved"]:
        if decision["requires_confirmation"]:
            confirmado = ask_human_confirmation(name, tool_input, decision["reason"])
            if not confirmado:
                log_event(
                    action=name, status="denied", amount_cents=amount_cents,
                    currency=tool_input.get("currency"),
                    reason=f"Negado pelo usuário. Motivo original: {decision['reason']}",
                    raw_payload=json.dumps(tool_input),
                )
                return {"error": "denied_by_user", "reason": decision["reason"]}, spent_today_cents

            log_event(
                action=name, status="approved", amount_cents=amount_cents,
                currency=tool_input.get("currency"),
                reason="Aprovado manualmente pelo usuário após exigência de confirmação.",
                raw_payload=json.dumps(tool_input),
            )
        else:
            log_event(
                action=name, status="denied", amount_cents=amount_cents,
                currency=tool_input.get("currency"), reason=decision["reason"],
                raw_payload=json.dumps(tool_input),
            )
            return {"error": "permission_denied", "reason": decision["reason"]}, spent_today_cents
    else:
        log_event(
            action=name, status="approved", amount_cents=amount_cents,
            currency=tool_input.get("currency"), reason=decision["reason"],
            raw_payload=json.dumps(tool_input),
        )

    try:
        func = TOOL_FUNCTIONS[name]
        result = func(**tool_input)
        log_event(
            action=name, status="executed", amount_cents=amount_cents,
            currency=tool_input.get("currency"), reason="Execução concluída com sucesso.",
            raw_payload=json.dumps(result, default=str),
        )
        new_spent = spent_today_cents + (amount_cents or 0)
        return result, new_spent

    except Exception as exc:  # nunca deixar uma falha de API quebrar o agente silenciosamente
        log_event(
            action=name, status="failed", amount_cents=amount_cents,
            currency=tool_input.get("currency"), reason=str(exc),
            raw_payload=json.dumps(tool_input),
        )
        return {"error": "execution_failed", "reason": str(exc)}, spent_today_cents


def run_agent(user_goal: str, policy: PermissionPolicy = None, max_turns: int = 6):
    """Roda o loop do agente até ele terminar ou atingir max_turns.

    O import da SDK da OpenAI fica aqui dentro (e não no topo do arquivo)
    de propósito: assim `execute_tool`, `permissions` e `audit` podem ser
    testados isoladamente sem precisar da SDK instalada — útil em CI ou
    para testar só a camada de segurança.
    """
    from openai import OpenAI

    init_db()
    policy = policy or PermissionPolicy()
    client = OpenAI()  # usa OPENAI_API_KEY do ambiente

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_goal},
    ]
    spent_today_cents = 0

    for _ in range(max_turns):
        response = client.chat.completions.create(
            model=MODEL,
            tools=TOOLS,
            messages=messages,
        )
        message = response.choices[0].message

        # A mensagem do assistente precisa ser adicionada ao histórico
        # exatamente como veio, incluindo os tool_calls, ou a próxima
        # chamada perde o contexto de qual tool_call_id corresponde a quê.
        messages.append(message.model_dump(exclude_unset=True))

        if not message.tool_calls:
            return message.content or ""

        for tool_call in message.tool_calls:
            name = tool_call.function.name
            tool_input = json.loads(tool_call.function.arguments)

            result, spent_today_cents = execute_tool(
                name, tool_input, policy, spent_today_cents
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, default=str),
                }
            )

    return "Número máximo de turnos atingido sem resposta final."


if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY"):
        print("Defina a variável de ambiente OPENAI_API_KEY antes de rodar.")
        raise SystemExit(1)

    objetivo = (
        "Verifique o saldo disponível, liste as contas pendentes, e pague a conta "
        "'bill_fake_001' até o limite de R$ 200,00 se houver saldo suficiente."
    )
    resposta = run_agent(objetivo)
    print("\n=== Resposta final do agente ===")
    print(resposta)
