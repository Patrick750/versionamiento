# Documentación — Automatización de versionado por commits

## 1. Objetivo

Eliminar la actualización manual de versión del proyecto. Los desarrolladores solo deben escribir una "bandera" de versión dentro de su mensaje de commit; un bot de GitHub Actions se encarga de interpretar esa bandera, calcular la versión real del proyecto, dejar constancia en un commit propio y crear el tag de Git correspondiente.

## 2. Formato de commit requerido

```
tipo(modulo): <palabra_clave> [X.Y.Z] descripcion del cambio
```

Ejemplos reales:
```
feat(M01): high [1.0.0] cambio de arquitectura de auth
feat(M01): low [0.1.0] agregar validacion de formulario de login
fix(M01): parch [0.0.1] corregir typo en mensaje de error
```

- **tipo**: clase de cambio (`feat`, `fix`, `refactor`, etc.), igual que en Conventional Commits.
- **modulo**: parte del sistema afectada.
- **palabra_clave**: `high`, `low` o `parch` — indica explícitamente qué segmento de versión se debe subir.
- **[X.Y.Z]**: acompaña a la palabra clave, pero es solo documental/ilustrativo dentro del commit — el bot no calcula nada a partir de este número.
- **descripcion**: el detalle normal del commit.

## 3. Qué significa cada palabra clave

A diferencia del esquema anterior (que inferí la, del dígito del tag), ahora la palabra clave lo dice de forma explícita, sin ambigüedad:

| Palabra clave | Significado | Efecto en la versión del proyecto |
|---|---|---|
| `high [X.Y.Z]` | Cambio grande / breaking change | Sube el **major**. Ej: `3.13.0` → `4.0.0` |
| `low [X.Y.Z]` | Cambio normal (feature, mejora) | Sube el **minor**. Ej: `3.12.4` → `3.13.0` |
| `parch [X.Y.Z]` | Corrección pequeña / bugfix menor | Sube el **patch**. Ej: `3.13.0` → `3.13.1` |

Este esquema agrega un tercer nivel (patch) que el esquema anterior no distinguía por separado.

## 4. Cómo se extrae la palabra clave del mensaje de commit

Se usa esta expresión regular sobre el mensaje del commit:

```bash
KEYWORD=$(echo "$MSG" | grep -oP '\b(high|low|parch)(?=\s*\[[0-9]+\.[0-9]+\.[0-9]+\])' || true)
```

Explicación pieza por pieza:
- `\b` — asegura que se detecte la palabra completa (evita coincidencias parciales dentro de otra palabra).
- `(high|low|parch)` — captura cualquiera de las tres palabras clave válidas.
- `(?=\s*\[[0-9]+\.[0-9]+\.[0-9]+\])` — verifica (sin incluirlo en el resultado) que justo después venga un espacio opcional y un patrón `[X.Y.Z]`, para confirmar que la palabra realmente está acompañando a un tag de versión y no es una coincidencia casual en la descripción del commit.
- `|| true` — evita que el script falle si el commit no trae ninguna palabra clave; en ese caso simplemente se omite ese commit.

## 5. Archivo de versión

- Vive en la raíz del repo como `VERSION`.
- Formato: `MAJOR.MINOR.PATCH` (3 segmentos, ej. `3.12.4`).
- Si no existe cuando corre el workflow por primera vez, se crea automáticamente en `0.0.0`.

## 6. Cuándo se dispara la automatización

- **Solo** con `push` a la rama `main`. Los commits en ramas de feature no disparan nada — el sistema únicamente reacciona cuando el trabajo llega a `main`, típicamente por la fusión de un Pull Request.
- El job se auto-excluye si el commit que lo disparó fue generado por el propio bot (para no entrar en loop infinito consigo mismo).

## 7. Por qué importa cómo se fusiona el Pull Request

GitHub ofrece tres formas de fusionar un PR:

- **Create a merge commit** (`--no-ff`): conserva todos los commits originales de la rama dentro del historial de `main`, más un commit de merge adicional. ✅ Compatible con esta automatización.
- **Rebase and merge**: también conserva todos los commits individuales, reescritos sobre `main`. ✅ Compatible.
- **Squash and merge**: colapsa todos los commits de la rama en **uno solo**. ❌ Incompatible — si se usa esta opción, el bot solo vería un commit y no podría procesar los 13 commits individuales con sus 13 tags.

**Regla para el equipo:** nunca usar "Squash and merge" en este repositorio si se quiere aprovechar el versionado automático por commit.

## 8. Flujo completo, paso a paso

1. El desarrollador crea su rama de feature desde `main`.
2. Hace sus commits normales, seleccionando su tag de versión `[X.Y.Z]` en los que correspondan.
3. Abre el Pull Request hacia `main`. El equipo revisa, se pueden agregar más commits.
4. Al aprobar, se fusiona eligiendo **"Create a merge commit"** (nunca squash).
5. GitHub genera un evento `push` sobre `main`, con las referencias `before` (estado anterior) y `after` (estado nuevo, el merge commit).
6. El workflow calcula el rango exacto de commits nuevos con `git log --reverse before..after`, obteniendo los commits en el orden real en que se programaron.
7. Recorre cada commit del rango:
   - Si no tiene tag `[X.Y.Z]`, lo omite (incluye el propio commit de merge que genera GitHub, que normalmente no trae corchetes).
   - Si tiene tag, calcula el nuevo número de versión según la regla de major/minor, actualiza el archivo `VERSION`, crea un commit de versión (`chore(version-bump): ...`) y un tag anotado (`vX.Y.Z`) apuntando a ese commit.
8. Al terminar de recorrer todos los commits, hace un único `push` de todos los commits de versión generados, y un `push --tags` para subir todos los tags creados.

**Resultado esperado con 13 commits en el merge:** si, por ejemplo, 8 traen tag `[0.x.x]` y 5 traen `[1.x.x]`, el historial de `main` termina con hasta 13 commits de versión nuevos (uno por cada commit taggeado), cada uno con su tag correspondiente, aplicados en el orden correcto — no un solo salto acumulado al final.

## 9. Casos borde contemplados

- **Primer push a una rama nueva** (`before` es un hash de puros ceros): se maneja tomando todos los commits desde el inicio del historial hasta `after`, en vez de intentar un rango inválido.
- **Commit sin tag**: se omite sin generar ningún bump ni error.
- **Formato de `VERSION` inválido**: el job debe fallar explícitamente con un mensaje claro, en vez de continuar con datos corruptos.
- **El propio commit de merge de GitHub** (mensaje tipo `Merge pull request #12 from...`): normalmente no trae corchetes, así que se omite igual que cualquier commit sin tag.

## 10. Pendiente / mejoras futuras a considerar

- Un check en el propio Pull Request que valide, antes de fusionar, que todos los commits de la rama cumplen el formato esperado — para evitar descubrir un commit mal escrito después de fusionar.
- Generación automática de GitHub Releases con notas de cambio, usando los tags creados como base (similar a lo que hace un workflow de release tradicional, pero disparado por estos mismos tags).
- Decidir si en algún momento se prefiere colapsar los bumps en un solo commit final por merge, en vez de uno por cada commit taggeado (actualmente se optó por mantener el commit por commit para trazabilidad completa).