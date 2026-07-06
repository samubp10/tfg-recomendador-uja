"""Validación básica rápida del dataset extraído.

Verifica que el archivo exportado por el spider cumple las métricas
mínimas esperadas de asignaturas extraídas y campos obligatorios.
Validación básica rápida del dataset extraído.

Verifica que el archivo exportado por el spider cumple las métricas
mínimas esperadas de asignaturas extraídas y campos obligatorios.
"""

import json
from pathlib import Path

ruta = Path(__file__).parent.parent / "data" / "grados.json"
d = [a for a in json.load(open(ruta, encoding='utf-8')) if a['tipo']=='asignatura']
assert len(d) == 361, len(d)
assert all('ofertada' in a for a in d), "falta campo ofertada"
assert not [a for a in d if '(' in a['nombre']], "nombres aún sucios"
assert not [a for a in d if any('/' in m for m in a['menciones'])], "menciones con / sin separar"
assert sum(1 for a in d if not a['ofertada']) == 9, "no ofertadas != 9"
print("Dataset OK:", len(d), "asignaturas,",
      sum(1 for a in d if not a['ofertada']), "no ofertadas,",
      sum(1 for a in d if not a['ects']), "sin ECTS (esperado 1)")
