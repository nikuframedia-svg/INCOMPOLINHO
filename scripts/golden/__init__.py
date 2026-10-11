"""Golden master of the INCOMPOLINHO planner (plan Passo 1b).

``flows.py`` runs one flow in its own process against one code tree,
``capture.py`` runs every flow (or the fast subset) and writes one canonical
JSON per flow, ``compare.py`` compares two captures. Inputs and outputs hold
client data and live outside git, under ``~/incompolinho-private/golden``.
"""
