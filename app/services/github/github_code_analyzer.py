from pathlib import PurePosixPath
from typing import Any, Dict, List, Set


class GitHubCodeAnalyzer:
    SOURCE_EXTENSIONS: Set[str] = {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".java",
        ".c",
        ".cpp",
        ".cc",
        ".h",
        ".hpp",
        ".cs",
        ".go",
        ".rs",
        ".php",
        ".rb",
        ".swift",
        ".kt",
        ".kts",
        ".scala",
        ".html",
        ".css",
        ".scss",
        ".sql",
    }

    IGNORED_DIRECTORIES: Set[str] = {
        ".git",
        ".agents",
        ".claude",
        ".cursor",
        ".copilot",
        ".idea",
        ".vscode",
        "node_modules",
        "dist",
        "build",
        ".next",
        ".venv",
        "venv",
        "__pycache__",
        "coverage",
        "vendor",
        "target",
    }

    IGNORED_EXTENSIONS: Set[str] = {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".svg",
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".exe",
        ".dll",
        ".so",
        ".woff",
        ".woff2",
        ".ttf",
        ".mp3",
        ".mp4",
        ".avi",
        ".agents",
        ".claude",
        ".cursor",
        ".copilot",
    }

    DEPENDENCY_FILES: Set[str] = {
        "requirements.txt",
        "pyproject.toml",
        "pipfile",
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "pom.xml",
        "build.gradle",
        "cargo.toml",
        "go.mod",
        "composer.json",
    }

    def analyze_tree(self, tree: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_files = 0
        source_files = 0
        important_files: List[str] = []
        dependency_files: List[str] = []
        source_paths: List[str] = []
        has_readme = False
        has_tests = False
        has_docker = False
        has_ci = False
        has_license = False
        detected_frameworks: Set[str] = set()

        for item in tree:
            if item.get("type") != "blob":
                continue

            path = item.get("path", "")
            if not path:
                continue
            if self._is_ignored(path):
                continue

            total_files += 1
            normalized = path.lower()
            file_name = PurePosixPath(path).name
            file_name_lower = file_name.lower()
            extension = PurePosixPath(path).suffix.lower()

            if extension in self.SOURCE_EXTENSIONS:
                source_files += 1
                source_paths.append(path)

            if file_name_lower.startswith("readme"):
                has_readme = True
                important_files.append(path)

            if "test" in file_name_lower or "/tests/" in f"/{normalized}/" or "/test/" in f"/{normalized}/" or "/__tests__/" in f"/{normalized}/":
                has_tests = True

            if file_name_lower == "dockerfile" or file_name_lower == "docker-compose.yml" or file_name_lower == "docker-compose.yaml":
                has_docker = True
                important_files.append(path)

            if normalized.startswith(".github/workflows/"):
                has_ci = True
                important_files.append(path)

            if file_name_lower.startswith("license"):
                has_license = True
                important_files.append(path)

            if file_name_lower in self.DEPENDENCY_FILES:
                dependency_files.append(path)
                important_files.append(path)

            self._detect_frameworks_from_path(path, detected_frameworks)

        return {
            "total_files": total_files,
            "source_files": source_files,
            "has_readme": has_readme,
            "has_tests": has_tests,
            "has_docker": has_docker,
            "has_ci": has_ci,
            "has_license": has_license,
            "detected_frameworks": sorted(detected_frameworks),
            "dependency_files": dependency_files,
            "important_files": important_files[:50],
            "source_paths": source_paths,
        }

    def select_source_files(self, source_paths: List[str], max_files: int = 20) -> List[str]:
        priority_keywords = (
            "main",
            "app",
            "server",
            "api",
            "route",
            "service",
            "model",
            "repository",
            "controller",
            "auth",
            "config",
            "schema",
            "test",
        )

        scored = []
        for path in source_paths:
            lowered = path.lower()
            score = 0
            for keyword in priority_keywords:
                if keyword in lowered:
                    score += 1
            depth = len(PurePosixPath(path).parts)
            scored.append((score, -depth, path))

        scored.sort(reverse=True)
        return [item[2] for item in scored[:max_files]]

    def detect_technologies_from_dependencies(self, dependency_contents: Dict[str, str]) -> List[str]:
        detected: Set[str] = set()

        for file_name, content in dependency_contents.items():
            lower_name = file_name.lower()
            lower_content = content.lower()

            if lower_name.endswith("package.json"):
                signals = {
                    '"react"': "React",
                    '"next"': "Next.js",
                    '"express"': "Express",
                    '"@nestjs/': "NestJS",
                    '"vue"': "Vue",
                    '"@angular/': "Angular",
                    '"tailwindcss"': "Tailwind CSS",
                    '"prisma"': "Prisma",
                    '"@prisma/client"': "Prisma",
                    '"mongoose"': "MongoDB / Mongoose",
                    '"mongodb"': "MongoDB",
                    '"jsonwebtoken"': "JWT",
                    '"redux"': "Redux",
                    '"@reduxjs/': "Redux Toolkit",
                    '"vite"': "Vite",
                    '"axios"': "Axios",
                    '"socket.io"': "Socket.IO",
                    '"jest"': "Jest",
                    '"vitest"': "Vitest",
                    '"cypress"': "Cypress",
                    '"playwright"': "Playwright",
                }
                for signal, technology in signals.items():
                    if signal in lower_content:
                        detected.add(technology)

            if lower_name.endswith("requirements.txt") or lower_name.endswith("pyproject.toml") or lower_name.endswith("pipfile"):
                signals = {
                    "fastapi": "FastAPI",
                    "django": "Django",
                    "flask": "Flask",
                    "pymongo": "MongoDB / PyMongo",
                    "motor": "MongoDB / Motor",
                    "sqlalchemy": "SQLAlchemy",
                    "pydantic": "Pydantic",
                    "tensorflow": "TensorFlow",
                    "torch": "PyTorch",
                    "pandas": "Pandas",
                    "numpy": "NumPy",
                    "scikit-learn": "Scikit-learn",
                    "sklearn": "Scikit-learn",
                    "langchain": "LangChain",
                    "llama-index": "LlamaIndex",
                    "pytest": "Pytest",
                    "uvicorn": "Uvicorn",
                }
                for signal, technology in signals.items():
                    if signal in lower_content:
                        detected.add(technology)

            if lower_name.endswith("pom.xml") or lower_name.endswith("build.gradle"):
                if "spring" in lower_content:
                    detected.add("Spring")
                if "hibernate" in lower_content:
                    detected.add("Hibernate")
                if "junit" in lower_content:
                    detected.add("JUnit")

            if lower_name.endswith("go.mod"):
                if "gin-gonic" in lower_content:
                    detected.add("Gin")
                if "gorm" in lower_content:
                    detected.add("GORM")

            if lower_name.endswith("cargo.toml"):
                if "actix" in lower_content:
                    detected.add("Actix")
                if "rocket" in lower_content:
                    detected.add("Rocket")

        return sorted(detected)

    def _is_ignored(self, path: str) -> bool:
        normalized = path.replace("\\", "/").lower()
        parts = [part.lower() for part in PurePosixPath(normalized).parts]

        if any(ignored.lower() in parts for ignored in self.IGNORED_DIRECTORIES):
            return True

        extension = PurePosixPath(normalized).suffix.lower()
        if extension in self.IGNORED_EXTENSIONS:
            return True

        if normalized.endswith(".min.js"):
            return True

        if normalized.endswith(".min.css"):
            return True

        return False

    def _detect_frameworks_from_path(self, path: str, detected_frameworks: Set[str]) -> None:
        normalized = path.lower()
        framework_signals = {
            "next.config": "Next.js",
            "vite.config": "Vite",
            "angular.json": "Angular",
            "manage.py": "Django",
            "settings.py": "Django",
            "dockerfile": "Docker",
            "tailwind.config": "Tailwind CSS",
        }

        for signal, framework in framework_signals.items():
            if signal in normalized:
                detected_frameworks.add(framework)
