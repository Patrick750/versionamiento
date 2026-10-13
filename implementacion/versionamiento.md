# Guía Técnica de Versionamiento Automático

Documento técnico de referencia local para la automatización de versionamiento.

## Resumen del Sistema

El sistema implementa el cálculo automático de versiones semánticas a partir de las declaraciones de los desarrolladores en los mensajes de commit:

- `high [1.0.0]`: Incremento Major (`X.0.0`)
- `low [0.1.0]`: Incremento Minor (`X.Y.0`)
- `parch [0.0.1]` / `patch [0.0.1]`: Incremento Patch (`X.Y.Z`)

## Componentes y Archivos Clave

- **`VERSION`**: Archivo con la versión actual (SemVer estricto).
- **`scripts/versionamiento.py`**: Motor de ejecución en Python.
  - `check`: Verifica coherencia entre `VERSION`, `README.md` y `frontend_project`.
  - `lint`: Analiza commits de Pull Requests sin modificar archivos.
  - `bump`: Aplica incrementos, actualiza archivos, genera commits con trailer `Version-Origin`, tags anotados y publica con `git push --atomic`.
- **`.github/workflows/pr-lint.yml`**: Verificación previa en PRs (tests unitarios + check + lint).
- **`.github/workflows/version-on-merge.yml`**: Ejecución en push a `main` o `master`, publicando tags y emitiendo el artifact `versioned-reference`.
- **`.github/workflows/deploy.yml`**: Despliegue encadenado por `workflow_run` que consume el SHA emitido en `versioned-reference`.
- **`tests/test_versionamiento.py`**: Pruebas unitarias e integración en repositorios aislados.

Para más detalles, consulta:
- [Instructivo detallado (v2.md)](v2.md)
- [Documentación histórica de diseño](../documentacion-versionado.md)
- [README principal](../README.md)
