# Convenciones de desarrollo

## Ramas

- `main`: rama estable. Lo que entra aquí está probado e integrado.
- `doc`: rama paralela donde se redacta la memoria en LaTeX. Se fusiona a `main` periódicamente.
- Ramas de trabajo: una por tarea, nombradas `IT-XX-descripcion-corta` y creadas a partir de `main`.

## Flujo de trabajo

1. Crear la rama de la tarea a partir de `main`.
2. Implementar la tarea junto con sus pruebas.
3. Si la tarea conlleva una decisión de diseño, añadir un ADR en `docs/adr/`.
4. Hacer commit siguiendo la convención de la sección siguiente.
5. Abrir un Pull Request que cierre la incidencia correspondiente (`Closes #NN`).
6. Fusionar a `main` cuando las pruebas pasen.

## Mensajes de commit

Se sigue Conventional Commits, con el formato `tipo(IT-XX): descripción`. El tipo va en inglés, por ser parte del estándar, y la descripción en español y en presente.

- `feat`: funcionalidad nueva
- `fix`: corrección de un fallo
- `docs`: documentación o ADR
- `test`: pruebas
- `refactor`: cambios internos que no alteran el comportamiento
- `chore`: configuración y tareas de mantenimiento

Ejemplo: `feat(IT-03): extrae el listado de grados de la EPSJ`

## Definición de Hecho

Una tarea se considera terminada cuando su código está en `main`, tiene pruebas, incluye el ADR correspondiente si procede y la sección de la memoria asociada está redactada.
