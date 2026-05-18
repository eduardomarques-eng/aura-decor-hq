#!/usr/bin/env python
"""Ponto de entrada — Equipe Aura Decor."""

import sys
from meu_primeiro_time.crew import MeuPrimeiroTime


def run():
    """Executa o crew para gerar uma proposta de design."""
    # Personalize aqui o nome do cliente e detalhes do briefing
    inputs = {
        "cliente": "Família Silva",
    }
    result = MeuPrimeiroTime().crew().kickoff(inputs=inputs)
    print("\n\n========== PROPOSTA GERADA ==========")
    print(result)


if __name__ == "__main__":
    run()
