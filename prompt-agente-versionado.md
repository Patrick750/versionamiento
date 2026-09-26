# Prompt para agente de código — Automatización de versionado

Copia y pega el siguiente prompt completo a tu agente de código (Claude Code, Cursor, etc.):

---

Necesito que implementes en este repositorio un sistema de versionado automático basado en GitHub Actions, con las siguientes reglas exactas:

## 1. Convención de commits

Todos los commits deben seguir el formato:

```
tipo(modulo): <palabra_clave> [X.Y.Z] descripcion del cambio
```

Donde `<palabra_clave>` es una de estas tres, y determina explícitamente qué segmento de versión se sube:

- `[X.Y.Z]` → sube el **major**. Ej: `feat(M01): high [1.0.0] cambio de arquitectura de auth`
- `[X.Y.Z]` → sube el **minor**. Ej: `feat(M01): low [0.1.0] agregar validacion de formulario de login`
- `[X.Y.Z]` → sube el **patch**. Ej: `fix(M01): parch [0.0.1] corregir typo en mensaje de error`

Importante: el número entre corchetes `[X.Y.Z]` **no es la versión final del proyecto** y el bot no lo usa para calcular nada — solo la palabra clave (`high`/`low`/`parch`) importa para decidir qué segmento subir. El número entre corchetes es puramente ilustrativo/documental dentro del propio commit.

## 2. Archivo de versión

- Crea un archivo `VERSION` en la raíz del repo, con formato semver de 3 segmentos: `MAJOR.MINOR.PATCH` (ej. `3.12.4`).
- Si el archivo no existe cuando corra el workflow, créalo con `0.0.0` como valor inicial.

## 3. Disparador (trigger)

- El workflow debe dispararse **únicamente** con `push` a la rama `main`.
- No debe dispararse con push a ninguna otra rama.
- Debe ignorarse a sí mismo: si el commit que disparó el evento fue generado por el propio bot (mensaje que contenga `chore(version-bump)`), el job no debe correr, para evitar loops infinitos.

## 4. Lógica de procesamiento (esto es lo más importante)

Cuando se hace merge de un Pull Request a `main` usando **merge commit (`--no-ff`) o rebase merge** (nunca squash), GitHub conserva todos los commits individuales de la rama dentro del historial de `main`. El workflow debe aprovechar esto así:

1. Usar `github.event.before` y `github.event.after` del evento push para determinar el rango exacto de commits nuevos que entraron con ese push.
2. Obtener esos commits en **orden cronológico** (del más antiguo al más nuevo) con `git log --reverse before..after`.
3. Recorrer cada commit uno por uno, en ese orden.
4. Por cada commit, buscar la palabra clave `high`, `low` o `parch` seguida de `[X.Y.Z]` en su mensaje, usando una expresión regular.
5. Si el commit no tiene ninguna de esas palabras clave, se omite (no genera ningún bump).
6. Si el commit sí tiene una palabra clave, aplicar sobre la versión actual del archivo `VERSION`:
   - `high` → sube el **major** (ej. `3.13.0` → `4.0.0`, reseteando minor y patch a `0`).
   - `low` → sube el **minor** (ej. `3.12.4` → `3.13.0`, reseteando patch a `0`).
   - `parch` → sube el **patch** (ej. `3.13.0` → `3.13.1`, sin tocar major ni minor).
   - Escribir la nueva versión en el archivo `VERSION`.
   - Crear un **commit propio** con el mensaje: `chore(version-bump): <NUEVA_VERSION> (origen: <sha corto> - <mensaje original del commit>)`.
   - Crear un **tag anotado de git** con el nombre `v<NUEVA_VERSION>`, cuyo mensaje incluya el sha corto del commit original que lo disparó.
7. Después de procesar todos los commits del rango, hacer **un solo push** al final con todos los commits de versión generados, y otro push de todos los tags creados (`git push origin --tags`).

Es decir: si un merge trae 13 commits y 8 de ellos tienen tag de versión, el resultado debe ser 8 commits de versión nuevos en `main`, cada uno con su tag correspondiente, en el orden correcto.

## 5. Validaciones y manejo de errores

- Si el archivo `VERSION` tiene un formato inválido (no es `X.Y.Z` numérico), el job debe fallar con un mensaje de error claro.
- Manejar el caso donde `before` es un hash de todo ceros (primer push a una rama nueva) sin que el script falle.
- No debe romper si dentro del rango de commits hay alguno sin tag (simplemente se omite, como se indicó).

## 6. Entregables esperados

- Un archivo `.github/workflows/version-on-merge.yml` con el workflow completo.
- Un archivo `VERSION` en la raíz (si no existe ya) inicializado en `0.0.0`.
- Actualiza el `README.md` del repo agregando una sección corta que explique:
  - El formato de commit requerido.
  - Que los merges a `main` deben hacerse con "Create a merge commit" o rebase, nunca squash.

## 7. Opcional (solo si tienes tiempo / pregúntame antes)

- Un check adicional en el PR (workflow separado, disparado en `pull_request`) que valide que todos los commits de la rama cumplen el formato `tipo(modulo): <high|low|parch> [X.Y.Z] descripcion`, y falle el check si alguno no cumple — para evitar mergear con un commit mal escrito.

---

Cuando termines, muéstrame el workflow final y explícame brevemente cualquier decisión de implementación que hayas tenido que tomar por tu cuenta.