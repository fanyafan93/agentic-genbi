from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


def load_project_env(env_file: str | None = None) -> bool:
    path = _resolve_env_path(env_file)
    if not path or not path.exists():
        return False
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError("python-dotenv is required to load env files.") from exc
    return bool(load_dotenv(path, override=False, encoding="utf-8"))


def _resolve_env_path(env_file: str | None = None) -> Path | None:
    explicit = env_file or os.getenv("GENBI_ENV_FILE")
    if explicit:
        return Path(explicit).expanduser().resolve()
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
        Path(__file__).resolve().parents[2] / "backend" / ".env",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


@dataclass(frozen=True)
class EnvCheck:
    name: str
    ok: bool
    message: str
    detail: str | None = None


def check_runtime_env(env_file: str | None = None) -> dict[str, Any]:
    env_path = _resolve_env_path(env_file)
    loaded = load_project_env(env_file)
    checks = [
        _check_llm(),
        _check_mysql(),
        _check_resource_library(),
        _check_frontend_api_base(),
        _check_cost_config(),
    ]
    return {
        "env_file": str(env_path) if env_path else None,
        "env_loaded": loaded,
        "ready": all(check.ok for check in checks if check.name in {"llm", "mysql", "resource_library"}),
        "checks": [asdict(check) for check in checks],
    }


def _check_llm() -> EnvCheck:
    runtime = os.getenv("GENBI_EXPLORATION_RUNTIME", "local").lower()
    provider = os.getenv("GENBI_LLM_PROVIDER", "openai").strip().lower() or "openai"
    api_key = _llm_api_key(provider)
    model = os.getenv("GENBI_EXPLORATION_MODEL", "gpt-4.1-mini" if provider == "openai" else "").strip()
    base_url = _llm_base_url(provider)
    if runtime not in {"openai", "llm"}:
        return EnvCheck("llm", True, "LLM Runner 未启用，当前使用本地探索事件服务。", f"GENBI_EXPLORATION_RUNTIME={runtime}; provider={provider}")
    if provider not in {"openai", "minimax"}:
        return EnvCheck("llm", False, "LLM provider 暂不支持。", f"provider={provider}; supported=openai,minimax")
    if not api_key:
        return EnvCheck("llm", False, f"已启用 LLM Runner，但缺少 {_llm_api_key_name(provider)}。", f"provider={provider}")
    if not model:
        return EnvCheck("llm", False, "已启用 LLM Runner，但缺少 GENBI_EXPLORATION_MODEL。", f"provider={provider}")
    if provider == "minimax" and not base_url:
        return EnvCheck("llm", False, "已启用 MiniMax provider，但缺少 MINIMAX_BASE_URL 或 GENBI_LLM_BASE_URL。", f"model={model}; key={_mask_secret(api_key)}")
    detail = f"provider={provider}; model={model}; key={_mask_secret(api_key)}"
    if base_url:
        detail += f"; base_url={base_url}"
    return EnvCheck("llm", True, "LLM Runner 配置存在。", detail)


def _check_mysql() -> EnvCheck:
    database_url = _parse_mysql_database_url(os.getenv("DATABASE_URL", ""))
    values = {
        "GENBI_DB_HOST": os.getenv("GENBI_DB_HOST") or database_url.get("host"),
        "GENBI_DB_USER": os.getenv("GENBI_DB_USER") or database_url.get("user"),
        "GENBI_DB_PASSWORD": os.getenv("GENBI_DB_PASSWORD") or database_url.get("password"),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        return EnvCheck("mysql", False, "MySQL 只读连接信息不完整。", "missing=" + ",".join(missing))
    host = values["GENBI_DB_HOST"] or ""
    port = os.getenv("GENBI_DB_PORT") or database_url.get("port") or "3306"
    database = os.getenv("GENBI_DB_DATABASE") or database_url.get("database") or ""
    enabled = os.getenv("GENBI_BUSINESS_QUERY_ENABLED", "true").lower()
    return EnvCheck("mysql", True, "MySQL 只读连接配置存在。", f"host={host}; port={port}; database={database or '-'}; business_query={enabled}")


def _check_resource_library() -> EnvCheck:
    root = Path(os.getenv("GENBI_RESOURCE_LIBRARY_ROOT", "资源库"))
    if root.exists() and root.is_dir():
        return EnvCheck("resource_library", True, "资源库目录存在。", str(root.resolve()))
    return EnvCheck("resource_library", False, "资源库目录不存在。", str(root))


def _check_frontend_api_base() -> EnvCheck:
    value = os.getenv("NEXT_PUBLIC_GENBI_API_BASE_URL")
    if value:
        return EnvCheck("frontend_api_base", True, "前端探索 API 地址已配置。", value)
    return EnvCheck("frontend_api_base", False, "缺少 NEXT_PUBLIC_GENBI_API_BASE_URL，知识探索前端不会使用本地模拟降级。")


def _check_cost_config() -> EnvCheck:
    input_rate = os.getenv("GENBI_MODEL_INPUT_USD_PER_1M")
    output_rate = os.getenv("GENBI_MODEL_OUTPUT_USD_PER_1M")
    if input_rate and output_rate:
        return EnvCheck("cost_config", True, "模型成本估算配置存在。", f"input={input_rate}; output={output_rate}")
    return EnvCheck("cost_config", False, "缺少模型成本估算价格；Run trace 会保留 token，但成本为空。")


def _mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def _llm_api_key(provider: str) -> str:
    generic = os.getenv("GENBI_LLM_API_KEY", "")
    if generic:
        return generic
    if provider == "minimax":
        return os.getenv("MINIMAX_API_KEY", "")
    return os.getenv("OPENAI_API_KEY", "")


def _llm_api_key_name(provider: str) -> str:
    if provider == "minimax":
        return "MINIMAX_API_KEY 或 GENBI_LLM_API_KEY"
    return "OPENAI_API_KEY 或 GENBI_LLM_API_KEY"


def _llm_base_url(provider: str) -> str:
    generic = os.getenv("GENBI_LLM_BASE_URL", "")
    if generic:
        return generic
    if provider == "minimax":
        return os.getenv("MINIMAX_BASE_URL", "")
    return os.getenv("OPENAI_BASE_URL", "")


def _parse_mysql_database_url(value: str) -> dict[str, str]:
    if not value.strip():
        return {}
    parsed = urlparse(value)
    if parsed.scheme not in {"mysql", "mysql+pymysql", "mysql+mysqlconnector"}:
        return {}
    return {
        key: current
        for key, current in {
            "host": parsed.hostname or "",
            "port": str(parsed.port) if parsed.port else "",
            "user": unquote(parsed.username or ""),
            "password": unquote(parsed.password or ""),
            "database": parsed.path.lstrip("/"),
        }.items()
        if current
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load and check Agentic GenBI runtime environment.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor", help="Check OpenAI, MySQL, resource library, frontend and cost env readiness.")
    doctor.add_argument("--env-file", default=None, help="Optional env file path. Defaults to GENBI_ENV_FILE or project .env.")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    doctor.add_argument("--no-fail", action="store_true", help="Always exit 0 after printing the report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "doctor":
        payload = check_runtime_env(args.env_file)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"env_file: {payload['env_file'] or '-'}")
            print(f"env_loaded: {payload['env_loaded']}")
            print(f"ready: {payload['ready']}")
            for check in payload["checks"]:
                mark = "OK" if check["ok"] else "MISSING"
                line = f"- {mark} {check['name']}: {check['message']}"
                if check.get("detail"):
                    line += f" ({check['detail']})"
                print(line)
        return 0 if args.no_fail or payload["ready"] else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
