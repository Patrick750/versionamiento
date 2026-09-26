# Prompt para Agente de Código — Automatización de Versionado

Copia y pega el siguiente prompt completo a tu agente de código (Claude Code, Cursor, GitHub Copilot, Antigravity, etc.):

---

Necesito que implementes en este repositorio un sistema de versionado automático basado en GitHub Actions, con las siguientes reglas exactas:

## 1. Convención de commits

Todos los commits que deban actualizar la versión deben seguir el formato:

```text
tipo(modulo): <palabra_clave> [X.Y.Z] descripcion del cambio
```

Donde `<palabra_clave>` es una de estas tres opciones, y determina explícitamente qué segmento de la versión se incrementa:

- `high [X.Y.Z]` → sube el **major** (ej. `feat(M01): high [1.0.0] cambio de arquitectura de auth`)
- `low [X.Y.Z]` → sube el **minor** (ej. `feat(M01): low [0.1.0] agregar validacion de formulario de login`)
- `parch [X.Y.Z]` → sube el **patch** (ej. `fix(M01): parch [0.0.1] corregir typo en mensaje de error`; también acepta `patch`)

> **Importante:** El número entre corchetes `[X.Y.Z]` **no es la versión final del proyecto** y el bot no lo usa para calcular nada — solo la palabra clave (`high` / `low` / `parch`) importa para decidir qué segmento subir. El número entre corchetes es puramente ilustrativo y documental dentro del propio commit para dar contexto a los revisores.

## 2. Archivo de versión

- Crea un archivo `VERSION` en la raíz del repo, con formato semver de 3 segmentos: `MAJOR.MINOR.PATCH` (ej. `3.12.4` o `0.0.0`).
- Si el archivo no existe cuando corra el workflow, inicialízalo con `0.0.0` como valor de partida.
- El script debe validar que el contenido del archivo cumpla estrictamente con la estructura numérica `X.Y.Z`. Si está corrupto, debe fallar con error descriptivo.

## 3. Disparador (trigger)

- El workflow debe dispararse **únicamente** con eventos `push` a la rama `main` (o `master`).
- No debe dispararse con push a ninguna rama secundaria (`feature/*`, `fix/*`).
- Debe ignorarse a sí mismo: si el commit que disparó el evento fue generado por el propio bot (mensaje que contenga `chore(version-bump)`), el job no debe correr, para evitar loops infinitos.

## 4. Lógica de procesamiento (esto es lo más importante)

Cuando se hace merge de un Pull Request a `main` usando **merge commit (`--no-ff`) o rebase merge** (nunca squash), GitHub conserva todos los commits individuales de la rama dentro del historial de `main`. El workflow debe aprovechar esto así:

1. Usar `github.event.before` y `github.event.after` del evento push para determinar el rango exacto de commits nuevos que entraron con ese push.
2. Obtener esos commits en **orden cronológico** (del más antiguo al más nuevo) con `git rev-list --reverse before..after` (o `git log --reverse`).
3. Recorrer cada commit uno por uno, en ese orden.
4. Por cada commit, buscar la palabra clave `high`, `low` o `parch` (y `patch`) seguida de `[X.Y.Z]` en su mensaje, usando una expresión regular robusta (`\b(high|low|parch|patch)(?=\s*\[[0-9]+\.[0-9]+\.[0-9]+\])`).
5. Si el commit no tiene ninguna de esas palabras clave, se omite (no genera ningún bump ni error).
6. Si el commit sí tiene una palabra clave, aplicar sobre la versión actual del archivo `VERSION`:
   - `high` → sube el **major** (ej. `3.13.0` → `4.0.0`, reseteando minor y patch a `0`).
   - `low` → sube el **minor** (ej. `3.12.4` → `3.13.0`, reseteando patch a `0`).
   - `parch` → sube el **patch** (ej. `3.13.0` → `3.13.1`, sin tocar major ni minor).
   - Escribir la nueva versión en el archivo `VERSION`.
   - Crear un **commit propio** con el mensaje: `chore(version-bump): <NUEVA_VERSION> (origen: <sha corto> - <mensaje original del commit>)`.
   - Crear un **tag anotado de git** con el nombre `v<NUEVA_VERSION>`, cuyo mensaje incluya el sha corto del commit original que lo disparó.
7. Después de procesar todos los commits del rango, hacer **un solo push** al final con todos los commits de versión generados, y otro push de todos los tags creados (`git push origin --tags`).

Es decir: si un merge trae 13 commits y 8 de ellos tienen tag de versión, el resultado debe ser 8 commits de versión nuevos en `main`, cada uno con su tag correspondiente, en el orden cronológico correcto.

## 5. Validaciones y manejo de errores

- Si el archivo `VERSION` tiene un formato inválido (no es `X.Y.Z` numérico), el job debe fallar con un mensaje de error claro (`::error::`).
- Manejar el caso donde `before` es un hash de todo ceros (primer push a una rama nueva o repositorio nuevo) sin que el script falle, leyendo los commits hacia `after`.
- No debe romper si dentro del rango de commits hay alguno sin tag (simplemente se omite).
- El paso de checkout debe incluir `fetch-depth: 0` para tener disponible todo el historial y referencias de tags.
- Configurar permisos de escritura: `permissions: contents: write`.

## 6. Entregables esperados

- Un archivo `.github/workflows/version-on-merge.yml` con el workflow completo.
- Un archivo `VERSION` en la raíz (si no existe ya) inicializado en `0.0.0`.
- Actualizar el `README.md` del repo explicando:
  - El formato de commit requerido.
  - Que los merges a `main` deben hacerse con "Create a merge commit" o rebase, nunca squash.
  - La tabla de palabras clave y su impacto semántico.

## 7. Verificación en Pull Request (Linter de commits)

- Un check adicional en el PR (workflow `.github/workflows/pr-lint.yml`, disparado en `pull_request`) que valide que todos los commits de la rama que intenten versionar cumplan con el formato `tipo(modulo): <high|low|parch> [X.Y.Z] descripcion`, y falle el check si alguno tiene sintaxis defectuosa — para evitar mergear con un commit mal escrito.

---

Cuando termines, muéstrame el workflow final y explícame brevemente cualquier decisión de implementación que hayas tomado.