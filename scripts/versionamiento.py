#!/usr/bin/env python3
"""
scripts/versionamiento.py

Sistema de versionamiento automático basado en commits.
Implementa las especificaciones descritas en implementacion/v2.md:
- check: valida la sincronización de VERSION, README.md y frontend_project.
- lint: valida el formato y coherencia de commits en PRs sin modificar archivos.
- bump: procesa commits entrantes, actualiza versiones, CHANGELOG.md,
        genera commits con trailer Version-Origin y tags anotados, y publica
        atéticamente con git push --atomic.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple

try:
    from zoneinfo import ZoneInfo
    BOGOTA_TZ = ZoneInfo("America/Bogota")
except Exception:
    BOGOTA_TZ = datetime.timezone(datetime.timedelta(hours=-5))

VALID_COMMIT_REGEX = re.compile(
    r"^[a-zA-Z0-9_-]+(?:\([a-zA-Z0-9_.-]+\))?:\s*(high|low|parch|patch)\s*\[([0-9]+\.[0-9]+\.[0-9]+)\]\s*(.+)$",
    re.IGNORECASE,
)
SUSPICIOUS_REGEX = re.compile(
    r"\b(high|low|parch|patch)\b|\[[0-9]+(?:\.[0-9]+)*\]",
    re.IGNORECASE,
)
SEMVER_REGEX = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
VERSION_ORIGIN_REGEX = re.compile(r"Version-Origin:\s*([0-9a-fA-F]{40})", re.IGNORECASE)


def run_git(args: List[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Ejecuta un comando git y retorna el resultado."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        err_msg = result.stderr.strip() or result.stdout.strip() or f"Error ejecutando git {' '.join(args)}"
        raise RuntimeError(err_msg)
    return result


def parse_commit_message(subject: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Analiza la primera línea del mensaje de commit.
    Retorna (keyword_normalizado, bracket_version, descripcion, error_mensaje).
    Si el commit es ordinario sin intención de versionado, retorna (None, None, None, None).
    """
    subject = subject.strip()
    if not subject:
        return None, None, None, None

    # Omitir commits automáticos y merges
    if "chore(version-bump)" in subject or subject.startswith("Merge pull request ") or subject.startswith("Merge branch "):
        return None, None, None, None

    match = VALID_COMMIT_REGEX.match(subject)
    if match:
        raw_keyword = match.group(1).lower()
        bracket_ver = match.group(2)
        description = match.group(3).strip()

        if not description:
            return None, None, None, "El commit no incluye una descripción del cambio."

        # Validación estricta de coherencia semántica
        if raw_keyword == "high" and bracket_ver != "1.0.0":
            return None, None, None, (
                f"Inconsistencia semántica: Usaste 'high' (Major) pero colocaste '[{bracket_ver}]'. "
                "La convención exige 'high [1.0.0]'."
            )
        if raw_keyword == "low" and bracket_ver != "0.1.0":
            return None, None, None, (
                f"Inconsistencia semántica: Usaste 'low' (Minor) pero colocaste '[{bracket_ver}]'. "
                "La convención exige 'low [0.1.0]'."
            )
        if raw_keyword in ("parch", "patch") and bracket_ver != "0.0.1":
            return None, None, None, (
                f"Inconsistencia semántica: Usaste '{raw_keyword}' (Patch) pero colocaste '[{bracket_ver}]'. "
                f"La convención exige '{raw_keyword} [0.0.1]'."
            )

        return raw_keyword, bracket_ver, description, None

    # Si no cumple el formato estricto pero tiene indicios de querer versionar
    if SUSPICIOUS_REGEX.search(subject):
        return None, None, None, (
            "El commit intenta declarar versión pero tiene sintaxis defectuosa. "
            "Formato esperado: tipo(modulo): <high|low|parch> [X.Y.Z] descripcion"
        )

    # Commit estándar ordinario sin declaración de versión
    return None, None, None, None


def calculate_new_version(current_ver: str, keyword: str) -> str:
    """Calcula la siguiente versión SemVer a partir del keyword."""
    if not SEMVER_REGEX.match(current_ver):
        raise ValueError(f"Versión actual inválida: '{current_ver}'. Se esperaba MAJOR.MINOR.PATCH.")

    major, minor, patch = map(int, current_ver.split("."))
    kw = keyword.lower()
    if kw == "high":
        major += 1
        minor = 0
        patch = 0
    elif kw == "low":
        minor += 1
        patch = 0
    elif kw in ("parch", "patch"):
        patch += 1
    else:
        raise ValueError(f"Palabra clave desconocida: '{keyword}'")

    return f"{major}.{minor}.{patch}"


def get_repo_root(cwd: Optional[Path] = None) -> Path:
    """Obtiene la raíz del repositorio Git."""
    res = run_git(["rev-parse", "--show-toplevel"], cwd=cwd)
    return Path(res.stdout.strip())


def read_version_file(repo_root: Path) -> str:
    """Lee y sanea el contenido del archivo VERSION."""
    version_file = repo_root / "VERSION"
    if not version_file.exists():
        return "0.0.0"
    content = version_file.read_text(encoding="utf-8").strip()
    if not SEMVER_REGEX.match(content):
        raise ValueError(f"Formato inválido en VERSION: '{content}'. Debe ser MAJOR.MINOR.PATCH.")
    return content


def write_version_file(repo_root: Path, version: str) -> None:
    """Escribe la nueva versión en el archivo VERSION."""
    version_file = repo_root / "VERSION"
    version_file.write_text(f"{version}\n", encoding="utf-8")


def sync_readme(repo_root: Path, new_version: str) -> bool:
    """Actualiza la línea 'Versión: **X.Y.Z**' en README.md."""
    readme_file = repo_root / "README.md"
    if not readme_file.exists():
        return False

    content = readme_file.read_text(encoding="utf-8")
    readme_pattern = re.compile(r"Versión:\s*\*\*[0-9]+\.[0-9]+\.[0-9]+\*\*", re.IGNORECASE)

    if readme_pattern.search(content):
        new_content = readme_pattern.sub(f"Versión: **{new_version}**", content)
    else:
        # Si aún no existe la línea, insertarla después del título principal H1
        h1_match = re.search(r"^(#\s+.*)$", content, flags=re.MULTILINE)
        if h1_match:
            new_content = re.sub(
                r"^(#\s+.*)$",
                rf"\1\n\nVersión: **{new_version}**",
                content,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            new_content = f"Versión: **{new_version}**\n\n" + content

    readme_file.write_text(new_content, encoding="utf-8")
    return True


def sync_frontend_files(repo_root: Path, new_version: str) -> List[Path]:
    """Actualiza version en package.json y package-lock.json si existen."""
    updated = []
    pkg_file = repo_root / "frontend_project" / "package.json"
    if pkg_file.exists():
        try:
            data = json.loads(pkg_file.read_text(encoding="utf-8"))
            data["version"] = new_version
            pkg_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            updated.append(pkg_file)
        except Exception as e:
            print(f"Advertencia: no se pudo actualizar {pkg_file}: {e}", file=sys.stderr)

    lock_file = repo_root / "frontend_project" / "package-lock.json"
    if lock_file.exists():
        try:
            data = json.loads(lock_file.read_text(encoding="utf-8"))
            data["version"] = new_version
            if "packages" in data and isinstance(data["packages"], dict) and "" in data["packages"]:
                data["packages"][""]["version"] = new_version
            lock_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            updated.append(lock_file)
        except Exception as e:
            print(f"Advertencia: no se pudo actualizar {lock_file}: {e}", file=sys.stderr)

    return updated


def append_changelog_entry(
    repo_root: Path,
    new_version: str,
    subject: str,
    author_name: str,
    full_sha: str,
    actor: Optional[str] = None,
) -> None:
    """Escribe una entrada al inicio de CHANGELOG.md preservando el historial."""
    changelog_file = repo_root / "CHANGELOG.md"
    existing_content = changelog_file.read_text(encoding="utf-8") if changelog_file.exists() else ""

    date_str = datetime.datetime.now(BOGOTA_TZ).strftime("%Y-%m-%d")

    actor_val = (actor or os.environ.get("VERSION_ACTOR", "")).strip()
    if actor_val:
        actor_display = f"@{actor_val.lstrip('@')}"
    else:
        actor_display = "No disponible (ejecución local)"

    entry = (
        f"### {new_version} — {date_str} — {subject}\n\n"
        f"- Autor del commit: {author_name}.\n"
        f"- Usuario de GitHub que inició el versionamiento: {actor_display}.\n"
        f"- Commit de origen: `{full_sha}`. Versión calculada automáticamente desde VERSION.\n"
    )

    if existing_content.strip():
        new_content = f"{entry}\n{existing_content.lstrip()}"
    else:
        new_content = f"{entry}\n"

    changelog_file.write_text(new_content, encoding="utf-8")


def get_processed_origins(cwd: Path) -> Set[str]:
    """Obtiene el conjunto de SHAs que ya originaron un commit de versionado."""
    origins = set()
    res = run_git(["log", "--grep=Version-Origin:", "--format=%(trailers:key=Version-Origin,valueonly)"], cwd=cwd, check=False)
    if res.returncode == 0:
        for line in res.stdout.splitlines():
            sha = line.strip()
            if re.match(r"^[0-9a-fA-F]{40}$", sha):
                origins.add(sha.lower())

    if not origins:
        # Fallback analizando mensajes de log completos
        res2 = run_git(["log", "-n", "300", "--format=%B%x00"], cwd=cwd, check=False)
        if res2.returncode == 0:
            for msg in res2.stdout.split("\x00"):
                for m in VERSION_ORIGIN_REGEX.finditer(msg):
                    origins.add(m.group(1).lower())
    return origins


def check_clean_checkout(cwd: Path) -> None:
    """Verifica que no existan modificaciones sin guardar en archivos bajo control de versiones."""
    res_head = run_git(["rev-parse", "--verify", "HEAD"], cwd=cwd, check=False)
    if res_head.returncode == 0:
        diff_res = run_git(["diff-index", "--quiet", "HEAD", "--"], cwd=cwd, check=False)
        if diff_res.returncode != 0:
            raise RuntimeError("El checkout debe estar limpio: existen cambios locales no guardados.")


# -----------------------------------------------------------------------------
# COMANDOS PRINCIPALES: check, lint, bump
# -----------------------------------------------------------------------------


def cmd_check(args: argparse.Namespace) -> int:
    """Comprueba que VERSION, README y los archivos de frontend coincidan."""
    repo_root = get_repo_root(args.cwd)
    errors = []

    try:
        current_version = read_version_file(repo_root)
    except Exception as e:
        print(f"❌ Error al leer VERSION: {e}", file=sys.stderr)
        return 1

    print(f"ℹ️  Versión base en VERSION: {current_version}")

    # Verificar README.md
    readme_file = repo_root / "README.md"
    if readme_file.exists():
        content = readme_file.read_text(encoding="utf-8")
        match = re.search(r"Versión:\s*\*\*([0-9]+\.[0-9]+\.[0-9]+)\*\*", content, re.IGNORECASE)
        if match:
            readme_ver = match.group(1)
            if readme_ver != current_version:
                errors.append(f"README.md declara versión '{readme_ver}' pero VERSION tiene '{current_version}'.")
            else:
                print(f"✅ README.md sincronizado ({readme_ver})")
        else:
            errors.append("README.md no contiene la línea esperada 'Versión: **X.Y.Z**'.")
    else:
        print("ℹ️  README.md no encontrado en la raíz.")

    # Verificar frontend_project/package.json
    pkg_file = repo_root / "frontend_project" / "package.json"
    if pkg_file.exists():
        try:
            data = json.loads(pkg_file.read_text(encoding="utf-8"))
            pkg_ver = data.get("version")
            if pkg_ver != current_version:
                errors.append(f"frontend_project/package.json tiene versión '{pkg_ver}' pero VERSION tiene '{current_version}'.")
            else:
                print(f"✅ frontend_project/package.json sincronizado ({pkg_ver})")
        except Exception as e:
            errors.append(f"Error al analizar frontend_project/package.json: {e}")

    # Verificar frontend_project/package-lock.json
    lock_file = repo_root / "frontend_project" / "package-lock.json"
    if lock_file.exists():
        try:
            data = json.loads(lock_file.read_text(encoding="utf-8"))
            lock_top_ver = data.get("version")
            lock_root_ver = data.get("packages", {}).get("", {}).get("version")
            if lock_top_ver != current_version:
                errors.append(f"frontend_project/package-lock.json nivel superior tiene '{lock_top_ver}' vs '{current_version}'.")
            if lock_root_ver != current_version:
                errors.append(f"frontend_project/package-lock.json paquete raíz tiene '{lock_root_ver}' vs '{current_version}'.")
            if lock_top_ver == current_version and lock_root_ver == current_version:
                print(f"✅ frontend_project/package-lock.json sincronizado ({lock_top_ver})")
        except Exception as e:
            errors.append(f"Error al analizar frontend_project/package-lock.json: {e}")

    if errors:
        print("\n❌ Se encontraron inconsistencias en la sincronización de versiones:")
        for err in errors:
            print(f"   - {err}")
        return 1

    print(f"\n✅ Todas las versiones están sincronizadas ({current_version}).")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    """Valida los commits de un rango (PR) sin generar versiones."""
    repo_root = get_repo_root(args.cwd)
    before = args.before.strip()
    after = args.after.strip()

    print("=============================================")
    print("Linting Commits in Pull Request")
    print(f"Base SHA : {before}")
    print(f"Head SHA : {after}")
    print("=============================================")

    # Encontrar merge base para permitir divergencias con historia común
    mb_res = run_git(["merge-base", before, after], cwd=repo_root, check=False)
    if mb_res.returncode != 0:
        print(f"::error::Base ({before}) y Head ({after}) no comparten historia común.", file=sys.stderr)
        return 1
    merge_base = mb_res.stdout.strip()

    rev_list_res = run_git(["rev-list", "--reverse", f"{merge_base}..{after}"], cwd=repo_root, check=False)
    if rev_list_res.returncode != 0:
        print(f"::error::Error obteniendo commits entre {merge_base} y {after}", file=sys.stderr)
        return 1

    commits = [c.strip() for c in rev_list_res.stdout.splitlines() if c.strip()]
    if not commits:
        print("No commits found to lint.")
        return 0

    errors = 0
    total = 0
    versioned = 0

    for sha in commits:
        total += 1
        subj_res = run_git(["log", "-1", "--format=%s", sha], cwd=repo_root)
        subject = subj_res.stdout.strip()
        short_sha = sha[:7]

        # Verificar si es commit de versionado del bot o merge
        if "chore(version-bump)" in subject or subject.startswith("Merge pull request ") or subject.startswith("Merge branch "):
            print(f"ℹ️  [SKIP MERGE/BOT]  {short_sha} - {subject}")
            continue

        kw, bracket_ver, desc, err_msg = parse_commit_message(subject)

        if err_msg:
            errors += 1
            if "Inconsistencia semántica" in err_msg:
                print(f"❌ [CONTRADICTION ERROR] {short_sha} - {subject}")
                print(f"   -> {err_msg}")
                print("   💡 Cómo corregir:")
                print("      git commit --amend -m \"tipo: <palabra_clave_correcta> [X.Y.Z_correcto] descripcion\"")
                print("      git push --force-with-lease")
                print(f"::error file=git,title=Commit Inconsistency::{short_sha}: {err_msg}")
            else:
                print(f"❌ [MALFORMED VERSION TAG] {short_sha} - {subject}")
                print(f"   Error: {err_msg}")
                print("   Formato esperado: tipo(modulo): <high|low|parch> [X.Y.Z] descripcion")
                print(f"::error file=git,title=Malformed Commit Syntax::{short_sha}: {err_msg}")
        elif kw:
            versioned += 1
            print(f"✅ [VALID & COHERENT] {short_sha} - {subject}")
        else:
            print(f"ℹ️  [STANDARD COMMIT]    {short_sha} - {subject}")

    print("\n=============================================")
    print(f"Summary: {total} total commit(s) evaluated.")
    print(f"  - Version-tagged commits: {versioned}")
    print(f"  - Syntax / Coherence errors: {errors}")
    print("=============================================")

    if errors > 0:
        print(f"::error::El Pull Request contiene {errors} commit(s) con errores o contradicciones de versión. Corrige los commits antes de fusionar.", file=sys.stderr)
        return 1

    print("All PR commits passed validation successfully.")
    return 0


def cmd_bump(args: argparse.Namespace) -> int:
    """Procesa commits entrantes y genera los incrementos correspondientes."""
    repo_root = get_repo_root(args.cwd)
    before = args.before.strip() if args.before else ""
    after = args.after.strip() if args.after else "HEAD"

    print("=============================================")
    print("Automated Versioning Execution (bump)")
    print(f"Before SHA : {before}")
    print(f"After SHA  : {after}")
    print("=============================================")

    # 1. Comprobar checkout limpio
    check_clean_checkout(repo_root)

    # 2. Manejo de tag inicial opcional (--initial-version)
    created_tags: List[str] = []
    current_version = read_version_file(repo_root)

    if args.initial_version:
        init_ver = args.initial_version.strip()
        init_tag = f"v{init_ver}"
        tag_check = run_git(["rev-parse", "-q", "--verify", f"refs/tags/{init_tag}"], cwd=repo_root, check=False)
        if tag_check.returncode != 0:
            if current_version != init_ver:
                raise RuntimeError(
                    f"El tag inicial {init_tag} no existe y VERSION ya avanzó ({current_version}). "
                    f"Deteniendo el proceso para evitar registrar un snapshot incorrecto como {init_ver}."
                )
            # Crear tag anotado inicial sobre HEAD actual antes de incrementos
            run_git(["tag", "-a", init_tag, "-m", f"Initial release {init_tag}"], cwd=repo_root)
            created_tags.append(init_tag)
            print(f"🏷️  Creado tag inicial anotado {init_tag}")
        else:
            print(f"ℹ️  Tag inicial {init_tag} ya existe. Se conserva.")

    # 3. Determinar rango de commits
    if not before or re.match(r"^0+$", before):
        print(f"Primer push o referencia inicial detectada. Leyendo commits hasta {after}...")
        rev_cmd = ["rev-list", "--reverse", after]
    else:
        # Verificar que before sea ancestro de after
        ancestor_res = run_git(["merge-base", "--is-ancestor", before, after], cwd=repo_root, check=False)
        if ancestor_res.returncode != 0:
            raise RuntimeError(f"before no es ancestro de after ({before} no es ancestro de {after}).")
        rev_cmd = ["rev-list", "--reverse", f"{before}..{after}"]

    rev_res = run_git(rev_cmd, cwd=repo_root)
    commits = [c.strip() for c in rev_res.stdout.splitlines() if c.strip()]

    if not commits:
        print("No commits found in the range. Exiting.")
        final_sha = run_git(["rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
        if args.output_sha_file:
            Path(args.output_sha_file).write_text(f"{final_sha}\n", encoding="utf-8")
        return 0

    processed_origins = get_processed_origins(repo_root)
    print(f"ℹ️  Commits de origen ya procesados anteriormente: {len(processed_origins)}")

    # 4. Fase de validación previa de TODO el lote antes de modificar archivos
    planned_bumps = []
    for sha in commits:
        subj_res = run_git(["log", "-1", "--format=%s", sha], cwd=repo_root)
        subject = subj_res.stdout.strip()
        short_sha = sha[:7]

        if "chore(version-bump)" in subject or subject.startswith("Merge pull request ") or subject.startswith("Merge branch "):
            continue

        if sha.lower() in processed_origins:
            print(f"  [SKIP] Commit {short_sha} ya fue procesado en una ejecución anterior.")
            continue

        kw, bracket_ver, desc, err_msg = parse_commit_message(subject)
        if err_msg:
            raise RuntimeError(f"Error de validación en commit {short_sha} ('{subject}'): {err_msg}")

        if kw:
            author_res = run_git(["log", "-1", "--format=%an", sha], cwd=repo_root)
            author_name = author_res.stdout.strip() or "Autor Desconocido"
            planned_bumps.append({
                "sha": sha,
                "short_sha": short_sha,
                "subject": subject,
                "keyword": kw,
                "author": author_name,
            })

    print(f"\nCommits a procesar con incremento: {len(planned_bumps)}")

    # 5. Aplicar incrementos cronológicamente
    bump_count = 0
    for item in planned_bumps:
        new_version = calculate_new_version(current_version, item["keyword"])
        print(f"\n--- Incrementando {current_version} -> {new_version} por commit {item['short_sha']} ---")

        # Actualizar VERSION
        write_version_file(repo_root, new_version)

        # Sincronizar README.md
        sync_readme(repo_root, new_version)

        # Sincronizar frontend
        sync_frontend_files(repo_root, new_version)

        # Escribir entrada en CHANGELOG.md
        append_changelog_entry(
            repo_root=repo_root,
            new_version=new_version,
            subject=item["subject"],
            author_name=item["author"],
            full_sha=item["sha"],
            actor=args.actor,
        )

        # Preparar archivos para commit
        files_to_add = ["VERSION", "CHANGELOG.md"]
        if (repo_root / "README.md").exists():
            files_to_add.append("README.md")
        if (repo_root / "frontend_project" / "package.json").exists():
            files_to_add.append("frontend_project/package.json")
        if (repo_root / "frontend_project" / "package-lock.json").exists():
            files_to_add.append("frontend_project/package-lock.json")

        run_git(["add"] + files_to_add, cwd=repo_root)

        commit_title = f"chore(version-bump): {new_version} (origen: {item['short_sha']} - {item['subject']})"
        commit_body = f"Version-Origin: {item['sha']}"
        run_git(["commit", "-m", commit_title, "-m", commit_body], cwd=repo_root)

        tag_name = f"v{new_version}"
        tag_msg = f"Release {tag_name} (origen: {item['short_sha']} - {item['subject']})"

        # Comprobar si tag existe
        tag_check = run_git(["rev-parse", "-q", "--verify", f"refs/tags/{tag_name}"], cwd=repo_root, check=False)
        if tag_check.returncode == 0:
            raise RuntimeError(f"Colisión de tag detectada: {tag_name} ya existe. Deteniendo el lote.")

        run_git(["tag", "-a", tag_name, "-m", tag_msg], cwd=repo_root)
        created_tags.append(tag_name)
        print(f"  [TAG] Creado tag anotado {tag_name}")

        current_version = new_version
        bump_count += 1

    final_sha = run_git(["rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
    print("\n=============================================")
    print(f"Resumen: {bump_count} versión(es) calculada(s).")
    print(f"SHA final: {final_sha}")
    print("=============================================")

    if args.output_sha_file:
        out_path = Path(args.output_sha_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(f"{final_sha}\n", encoding="utf-8")
        print(f"SHA final guardado en {out_path}")

    # 6. Publicación atómica si se especificó --push
    if args.push:
        if bump_count > 0 or created_tags:
            # Obtener nombre de rama remota
            branch = args.branch
            if not branch:
                branch = os.environ.get("GITHUB_REF_NAME")
            if not branch:
                branch_res = run_git(["branch", "--show-current"], cwd=repo_root)
                branch = branch_res.stdout.strip() or "main"

            print(f"Publicando commits y tags de forma atómica a origin/{branch}...")
            push_args = ["push", "--atomic", "origin", f"HEAD:{branch}"]
            for t in created_tags:
                push_args.append(f"refs/tags/{t}")

            run_git(push_args, cwd=repo_root)
            print("✅ Publicación atómica completada exitosamente.")
        else:
            print("No se generaron incrementos ni tags nuevos. Nada que publicar.")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Automatización de versionamiento por commits.")
    parser.add_argument("--cwd", type=Path, default=None, help="Directorio raíz de ejecución")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcomando check
    parser_check = subparsers.add_parser("check", help="Verifica sincronización de archivos de versión")
    parser_check.set_defaults(func=cmd_check)

    # Subcomando lint
    parser_lint = subparsers.add_parser("lint", help="Valida sintaxis y coherencia de commits en PR")
    parser_lint.add_argument("--before", required=True, help="SHA base o commit anterior")
    parser_lint.add_argument("--after", required=True, help="SHA head o commit posterior")
    parser_lint.set_defaults(func=cmd_lint)

    # Subcomando bump
    parser_bump = subparsers.add_parser("bump", help="Genera incrementos de versión a partir de commits")
    parser_bump.add_argument("--before", default="", help="SHA anterior")
    parser_bump.add_argument("--after", default="HEAD", help="SHA posterior")
    parser_bump.add_argument("--push", action="store_true", help="Publica commits y tags a origin de forma atómica")
    parser_bump.add_argument("--initial-version", default="", help="Versión inicial a etiquetar si no existe")
    parser_bump.add_argument("--actor", default="", help="Usuario de GitHub que inició el versionamiento")
    parser_bump.add_argument("--branch", default="", help="Nombre de la rama de destino para el push")
    parser_bump.add_argument("--output-sha-file", default="", help="Ruta de archivo donde escribir el SHA final")
    parser_bump.set_defaults(func=cmd_bump)

    args = parser.parse_args()
    try:
        sys.exit(args.func(args))
    except Exception as exc:
        print(f"❌ Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
