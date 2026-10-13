#!/usr/bin/env python3
"""
tests/test_versionamiento.py

Pruebas unitarias y de integración para la automatización de versionamiento.
Verifica:
- Análisis sintáctico y coherencia de mensajes de commit.
- Cálculo de versiones SemVer.
- Comandos check, lint y bump con repositorios Git temporales y remotos locales.
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

# Agregar scripts al path para importar
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import versionamiento


def init_git_repo(path: Path) -> None:
    """Inicializa un repositorio Git local con configuración de usuario."""
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Runner"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True, capture_output=True)


class TestCommitParsingAndCoherence(unittest.TestCase):
    """Pruebas de análisis y coherencia de formato de commits."""

    def test_valid_commits(self):
        valid_cases = [
            ("feat(cors): parch [0.0.1] autorizar el dominio del frontend", "parch", "0.0.1"),
            ("feat: patch [0.0.1] alias patch aceptado", "patch", "0.0.1"),
            ("feat(catalogo): low [0.1.0] agregar filtros de búsqueda", "low", "0.1.0"),
            ("feat(auth): high [1.0.0] cambiar el contrato de autenticación", "high", "1.0.0"),
            ("FIX: PARCH [0.0.1] prueba mayúsculas", "parch", "0.0.1"),
            ("chore(deps): low [0.1.0] actualizar dependencias", "low", "0.1.0"),
        ]
        for msg, expected_kw, expected_bracket in valid_cases:
            with self.subTest(msg=msg):
                kw, bracket, desc, err = versionamiento.parse_commit_message(msg)
                self.assertIsNone(err)
                self.assertEqual(kw, expected_kw)
                self.assertEqual(bracket, expected_bracket)
                self.assertTrue(len(desc) > 0)

    def test_incoherent_increments(self):
        incoherent_cases = [
            ("fix(cors): parch [5.0.9] autorizar frontend", "parch"),
            ("feat(api): low [1.0.0] agregar filtros", "low"),
            ("feat: high [0.1.0] contrato roto pero incremento menor", "high"),
            ("fix: patch [0.1.0] inconsistente", "patch"),
        ]
        for msg, kw in incoherent_cases:
            with self.subTest(msg=msg):
                _, _, _, err = versionamiento.parse_commit_message(msg)
                self.assertIsNotNone(err)
                self.assertIn("Inconsistencia semántica", err)

    def test_malformed_syntax(self):
        malformed_cases = [
            "fix: patch [0.0.1]",  # Sin descripción
            "feat: high 1.0.0 romper contrato",  # Sin corchetes
            "fix: parch [0.0.1] ",  # Descripción vacía tras strip
        ]
        for msg in malformed_cases:
            with self.subTest(msg=msg):
                _, _, _, err = versionamiento.parse_commit_message(msg)
                self.assertIsNotNone(err)

    def test_suspicious_keywords_in_ordinary_commits(self):
        # Commits que usan palabras reservadas sin formato completo
        suspicious = [
            "docs: aplicar un parch urgente",
            "chore: actualizar high level doc",
            "refactor: low memory footprint",
        ]
        for msg in suspicious:
            with self.subTest(msg=msg):
                _, _, _, err = versionamiento.parse_commit_message(msg)
                self.assertIsNotNone(err)
                self.assertIn("intenta declarar versión pero tiene sintaxis defectuosa", err)

    def test_standard_commits_ignored(self):
        standard = [
            "docs: mejorar el instructivo",
            "chore: limpiar archivos temporales",
            "Merge pull request #5 from feature/branch",
            "chore(version-bump): 5.1.0 (origen: 1234567 - feat: low [0.1.0] algo)",
        ]
        for msg in standard:
            with self.subTest(msg=msg):
                kw, bracket, desc, err = versionamiento.parse_commit_message(msg)
                self.assertIsNone(kw)
                self.assertIsNone(bracket)
                self.assertIsNone(desc)
                self.assertIsNone(err)


class TestSemVerCalculation(unittest.TestCase):
    """Pruebas de cálculo de versión semántica."""

    def test_calculation(self):
        self.assertEqual(versionamiento.calculate_new_version("5.2.3", "high"), "6.0.0")
        self.assertEqual(versionamiento.calculate_new_version("5.2.3", "low"), "5.3.0")
        self.assertEqual(versionamiento.calculate_new_version("5.2.3", "parch"), "5.2.4")
        self.assertEqual(versionamiento.calculate_new_version("5.2.3", "patch"), "5.2.4")

        # Desde 0.0.0
        self.assertEqual(versionamiento.calculate_new_version("0.0.0", "low"), "0.1.0")
        self.assertEqual(versionamiento.calculate_new_version("0.0.0", "high"), "1.0.0")
        self.assertEqual(versionamiento.calculate_new_version("0.0.0", "parch"), "0.0.1")

    def test_invalid_input(self):
        with self.assertRaises(ValueError):
            versionamiento.calculate_new_version("invalid", "low")
        with self.assertRaises(ValueError):
            versionamiento.calculate_new_version("1.2.3", "unknown")


class TestCheckCommand(unittest.TestCase):
    """Pruebas para el comando check."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo = Path(self.test_dir)
        init_git_repo(self.repo)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_check_synchronized_success(self):
        (self.repo / "VERSION").write_text("5.0.0\n")
        (self.repo / "README.md").write_text("# Proyecto\n\nVersión: **5.0.0**\n")
        fe_dir = self.repo / "frontend_project"
        fe_dir.mkdir(parents=True)
        (fe_dir / "package.json").write_text(json.dumps({"name": "app", "version": "5.0.0"}))
        (fe_dir / "package-lock.json").write_text(json.dumps({
            "name": "app",
            "version": "5.0.0",
            "packages": {"": {"name": "app", "version": "5.0.0"}},
        }))

        args = argparse.Namespace(cwd=self.repo)
        code = versionamiento.cmd_check(args)
        self.assertEqual(code, 0)

    def test_check_mismatched_readme_fails(self):
        (self.repo / "VERSION").write_text("5.0.0\n")
        (self.repo / "README.md").write_text("# Proyecto\n\nVersión: **4.9.9**\n")

        args = argparse.Namespace(cwd=self.repo)
        code = versionamiento.cmd_check(args)
        self.assertEqual(code, 1)

    def test_check_mismatched_frontend_fails(self):
        (self.repo / "VERSION").write_text("5.0.0\n")
        (self.repo / "README.md").write_text("# Proyecto\n\nVersión: **5.0.0**\n")
        fe_dir = self.repo / "frontend_project"
        fe_dir.mkdir(parents=True)
        (fe_dir / "package.json").write_text(json.dumps({"name": "app", "version": "5.1.0"}))

        args = argparse.Namespace(cwd=self.repo)
        code = versionamiento.cmd_check(args)
        self.assertEqual(code, 1)


class TestLintCommand(unittest.TestCase):
    """Pruebas para el comando lint con commits en Git."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo = Path(self.test_dir)
        init_git_repo(self.repo)

        # Commit base inicial
        (self.repo / "init.txt").write_text("inicio")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "chore: commit inicial"], cwd=self.repo, check=True)
        self.base_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True, check=True
        ).stdout.strip()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_lint_valid_commits(self):
        # Crear rama y agregar commits válidos
        subprocess.run(["git", "checkout", "-b", "feature/valida"], cwd=self.repo, check=True)
        (self.repo / "f1.txt").write_text("1")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "feat(api): low [0.1.0] agregar endpoint"], cwd=self.repo, check=True)

        (self.repo / "f2.txt").write_text("2")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "fix: parch [0.0.1] solucionar bug"], cwd=self.repo, check=True)

        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True, check=True
        ).stdout.strip()

        args = argparse.Namespace(cwd=self.repo, before=self.base_sha, after=head_sha)
        code = versionamiento.cmd_lint(args)
        self.assertEqual(code, 0)

    def test_lint_incoherent_commit_fails(self):
        subprocess.run(["git", "checkout", "-b", "feature/incoherente"], cwd=self.repo, check=True)
        (self.repo / "f1.txt").write_text("1")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "feat(api): low [1.0.0] incoherencia total"], cwd=self.repo, check=True)

        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True, check=True
        ).stdout.strip()

        args = argparse.Namespace(cwd=self.repo, before=self.base_sha, after=head_sha)
        code = versionamiento.cmd_lint(args)
        self.assertEqual(code, 1)

    def test_lint_allows_divergent_history_with_common_ancestor(self):
        # Crear rama de feature
        subprocess.run(["git", "checkout", "-b", "feature/divergente"], cwd=self.repo, check=True)
        (self.repo / "feat.txt").write_text("feat")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "feat: low [0.1.0] cambio en rama"], cwd=self.repo, check=True)
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True, check=True
        ).stdout.strip()

        # Avanzar main independientemente
        subprocess.run(["git", "checkout", "main"], cwd=self.repo, check=True)
        (self.repo / "main_advance.txt").write_text("main advance")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "docs: avance en main"], cwd=self.repo, check=True)
        new_main_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True, check=True
        ).stdout.strip()

        # El validador de PR debe aceptar la divergencia si comparten historia
        args = argparse.Namespace(cwd=self.repo, before=new_main_sha, after=head_sha)
        code = versionamiento.cmd_lint(args)
        self.assertEqual(code, 0)


class TestBumpCommand(unittest.TestCase):
    """Pruebas completas para el comando bump."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo = Path(self.test_dir) / "local"
        self.remote = Path(self.test_dir) / "remote.git"
        self.repo.mkdir(parents=True)

        # Crear remote bare
        subprocess.run(["git", "init", "--bare", "-b", "main", str(self.remote)], check=True, capture_output=True)

        # Inicializar repositorio local
        init_git_repo(self.repo)
        subprocess.run(["git", "remote", "add", "origin", str(self.remote)], cwd=self.repo, check=True)

        # Archivos iniciales
        (self.repo / "VERSION").write_text("5.0.0\n")
        (self.repo / "README.md").write_text("# Proyecto\n\nVersión: **5.0.0**\n")
        fe_dir = self.repo / "frontend_project"
        fe_dir.mkdir(parents=True)
        (fe_dir / "package.json").write_text(json.dumps({"name": "app", "version": "5.0.0"}))
        (fe_dir / "package-lock.json").write_text(json.dumps({
            "name": "app",
            "version": "5.0.0",
            "packages": {"": {"name": "app", "version": "5.0.0"}},
        }))

        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "chore: setup inicial"], cwd=self.repo, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=self.repo, check=True)

        self.initial_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True, check=True
        ).stdout.strip()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_bump_single_commit(self):
        # Crear un commit con low [0.1.0]
        (self.repo / "nuevo.txt").write_text("nuevo")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "feat(catalogo): low [0.1.0] agregar filtros de busqueda"],
            cwd=self.repo,
            check=True,
        )
        incoming_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True, check=True
        ).stdout.strip()

        sha_file = self.repo / "final_sha.txt"
        args = argparse.Namespace(
            cwd=self.repo,
            before=self.initial_sha,
            after=incoming_sha,
            push=True,
            initial_version="5.0.0",
            actor="Patrick750",
            branch="main",
            output_sha_file=str(sha_file),
        )
        code = versionamiento.cmd_bump(args)
        self.assertEqual(code, 0)

        # Verificar VERSION actualizada
        self.assertEqual((self.repo / "VERSION").read_text().strip(), "5.1.0")

        # Verificar README actualizado
        self.assertIn("Versión: **5.1.0**", (self.repo / "README.md").read_text())

        # Verificar frontend sincronizado
        pkg_data = json.loads((self.repo / "frontend_project" / "package.json").read_text())
        self.assertEqual(pkg_data["version"], "5.1.0")
        lock_data = json.loads((self.repo / "frontend_project" / "package-lock.json").read_text())
        self.assertEqual(lock_data["version"], "5.1.0")
        self.assertEqual(lock_data["packages"][""]["version"], "5.1.0")

        # Verificar CHANGELOG.md
        changelog = (self.repo / "CHANGELOG.md").read_text()
        self.assertIn("### 5.1.0 — ", changelog)
        self.assertIn("Usuario de GitHub que inició el versionamiento: @Patrick750", changelog)
        self.assertIn(f"Commit de origen: `{incoming_sha}`", changelog)

        # Verificar commit y tag de versionado
        tag_check = subprocess.run(
            ["git", "rev-parse", "v5.1.0"], cwd=self.repo, capture_output=True, text=True, check=True
        )
        self.assertTrue(len(tag_check.stdout.strip()) > 0)

        # Verificar trailer Version-Origin en el commit de bump
        log_bump = subprocess.run(
            ["git", "log", "-1", "--format=%B", "HEAD"], cwd=self.repo, capture_output=True, text=True, check=True
        ).stdout
        self.assertIn(f"Version-Origin: {incoming_sha}", log_bump)

        # Verificar que el remote recibió el tag y commit (por push --atomic)
        remote_tags = subprocess.run(
            ["git", "ls-remote", "--tags", "origin"], cwd=self.repo, capture_output=True, text=True, check=True
        ).stdout
        self.assertIn("refs/tags/v5.1.0", remote_tags)
        self.assertIn("refs/tags/v5.0.0", remote_tags)  # Tag inicial registrado

    def test_bump_sequential_commits(self):
        # Realizar 2 commits en secuencia: parch [0.0.1] y high [1.0.0]
        (self.repo / "f1.txt").write_text("1")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "fix: parch [0.0.1] correccion simple"], cwd=self.repo, check=True)
        sha_1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True, check=True).stdout.strip()

        (self.repo / "f2.txt").write_text("2")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "feat: high [1.0.0] breaking change grande"], cwd=self.repo, check=True)
        sha_2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True, check=True).stdout.strip()

        args = argparse.Namespace(
            cwd=self.repo,
            before=self.initial_sha,
            after=sha_2,
            push=False,
            initial_version="",
            actor="",
            branch="main",
            output_sha_file="",
        )
        code = versionamiento.cmd_bump(args)
        self.assertEqual(code, 0)

        # Primera versión calculada debió ser 5.0.1, y la segunda 6.0.0
        self.assertEqual((self.repo / "VERSION").read_text().strip(), "6.0.0")

        # Deben existir tags v5.0.1 y v6.0.0
        subprocess.run(["git", "rev-parse", "v5.0.1"], cwd=self.repo, check=True)
        subprocess.run(["git", "rev-parse", "v6.0.0"], cwd=self.repo, check=True)

        changelog = (self.repo / "CHANGELOG.md").read_text()
        self.assertIn("### 6.0.0 — ", changelog)
        self.assertIn("### 5.0.1 — ", changelog)
        self.assertIn("No disponible (ejecución local)", changelog)

    def test_bump_idempotency_skips_processed_origin(self):
        (self.repo / "f.txt").write_text("mod")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "fix: parch [0.0.1] arreglo"], cwd=self.repo, check=True)
        incoming_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True, check=True).stdout.strip()

        args = argparse.Namespace(
            cwd=self.repo,
            before=self.initial_sha,
            after=incoming_sha,
            push=False,
            initial_version="",
            actor="",
            branch="main",
            output_sha_file="",
        )
        self.assertEqual(versionamiento.cmd_bump(args), 0)
        self.assertEqual((self.repo / "VERSION").read_text().strip(), "5.0.1")

        # Repetir la ejecución sobre el mismo rango
        self.assertEqual(versionamiento.cmd_bump(args), 0)
        # La versión no debe cambiar a 5.0.2 porque el origen ya fue procesado
        self.assertEqual((self.repo / "VERSION").read_text().strip(), "5.0.1")

    def test_bump_fails_if_unclean_checkout(self):
        # Crear cambio sin guardar en archivo trackeado
        (self.repo / "VERSION").write_text("modificado")
        args = argparse.Namespace(
            cwd=self.repo,
            before=self.initial_sha,
            after="HEAD",
            push=False,
            initial_version="",
            actor="",
            branch="main",
            output_sha_file="",
        )
        with self.assertRaises(RuntimeError) as ctx:
            versionamiento.cmd_bump(args)
        self.assertIn("El checkout debe estar limpio", str(ctx.exception))

    def test_bump_fails_if_initial_version_tag_missing_and_version_advanced(self):
        # Cambiar VERSION a 5.1.0 pero initial_version esperado es 5.0.0 y no existe tag v5.0.0
        (self.repo / "VERSION").write_text("5.1.0\n")
        subprocess.run(["git", "add", "VERSION"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "chore: version avanzada"], cwd=self.repo, check=True)

        args = argparse.Namespace(
            cwd=self.repo,
            before=self.initial_sha,
            after="HEAD",
            push=False,
            initial_version="5.0.0",
            actor="",
            branch="main",
            output_sha_file="",
        )
        with self.assertRaises(RuntimeError) as ctx:
            versionamiento.cmd_bump(args)
        self.assertIn("El tag inicial v5.0.0 no existe y VERSION ya avanzó", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
