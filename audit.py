"""
audit.py
---------
Trilha de auditoria do agente: toda decisão (aprovada, negada ou executada)
é registrada aqui. Isso é o que um time de compliance de fintech vai querer
ver: quem pediu, o que o agente decidiu, quando, e por quê.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "audit_log.db"


def _get_connection():
    DB_PATH.parent.mkdir(exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    """Cria a tabela de auditoria se ainda não existir."""
    conn = _get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            action TEXT NOT NULL,
            amount_cents INTEGER,
            currency TEXT,
            status TEXT NOT NULL,          -- 'approved', 'denied', 'executed', 'failed'
            reason TEXT,
            raw_payload TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def log_event(action: str, status: str, amount_cents: int = None,
              currency: str = None, reason: str = "", raw_payload: str = ""):
    """Registra um evento na trilha de auditoria.

    Args:
        action: nome da ação (ex: 'create_payment_intent')
        status: 'approved' | 'denied' | 'executed' | 'failed'
        amount_cents: valor envolvido, em centavos
        currency: moeda (ex: 'brl', 'usd')
        reason: explicação legível da decisão
        raw_payload: payload bruto da chamada, para debug/auditoria
    """
    conn = _get_connection()
    conn.execute(
        """
        INSERT INTO audit_log (timestamp, action, amount_cents, currency, status, reason, raw_payload)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            action,
            amount_cents,
            currency,
            status,
            reason,
            raw_payload,
        ),
    )
    conn.commit()
    conn.close()


def get_recent_events(limit: int = 20):
    """Retorna os eventos mais recentes, para exibir num dashboard/CLI."""
    conn = _get_connection()
    cur = conn.execute(
        "SELECT timestamp, action, amount_cents, currency, status, reason FROM audit_log "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


if __name__ == "__main__":
    init_db()
    print(f"Banco de auditoria pronto em: {DB_PATH}")
