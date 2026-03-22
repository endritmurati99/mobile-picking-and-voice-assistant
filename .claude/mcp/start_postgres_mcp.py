import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


def load_env_file(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def build_dsn(project_dir: Path) -> str:
    env_path = project_dir / "Mobile Picking und Voice Assistant" / ".env"
    values = load_env_file(env_path)

    user = values.get("POSTGRES_USER", "odoo")
    password = values.get("POSTGRES_PASSWORD")
    host_port = values.get("POSTGRES_HOST_PORT", "5433")
    database = values.get("CLAUDE_MCP_POSTGRES_DB") or values.get("ODOO_DB", "picking")

    if not password:
        raise RuntimeError("POSTGRES_PASSWORD fehlt in Mobile Picking und Voice Assistant/.env")

    return f"postgresql://{quote(user)}:{quote(password)}@127.0.0.1:{host_port}/{quote(database)}"


def main() -> int:
    project_dir = Path(__file__).resolve().parents[2]

    if "--print-dsn" in sys.argv:
        print(build_dsn(project_dir))
        return 0

    dsn = build_dsn(project_dir)
    completed = subprocess.run(["cmd", "/c", "npx", "-y", "@modelcontextprotocol/server-postgres", dsn])
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
