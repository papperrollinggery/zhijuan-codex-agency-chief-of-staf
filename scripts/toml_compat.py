"""Small TOML loading compatibility layer for release helper scripts."""

from __future__ import annotations

import ast
import re

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - depends on interpreter
    try:
        import tomli as _toml  # type: ignore[no-redef]
    except ModuleNotFoundError:  # pragma: no cover - depends on environment
        _toml = None


if _toml is not None:
    TOMLDecodeError = getattr(_toml, "TOMLDecodeError", ValueError)

    def loads(text: str) -> dict:
        return _toml.loads(text)

else:

    class TOMLDecodeError(ValueError):
        """Raised when the minimal fallback parser cannot read a TOML file."""

    _KEY = re.compile(r"^[A-Za-z0-9_-]+$")

    def _parse_string(value: str) -> str:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            raise TOMLDecodeError(str(exc)) from exc
        if not isinstance(parsed, str):
            raise TOMLDecodeError("expected string value")
        return parsed

    def loads(text: str) -> dict:
        """Parse the flat string TOML shape used by Codex agent files.

        This fallback is intentionally small. It supports top-level keys with
        single-line quoted strings and triple-quoted multi-line strings, which
        covers the bundled `assets/codex_agents/*.toml` files.
        """

        data: dict[str, str] = {}
        lines = iter(enumerate(text.splitlines(), start=1))
        for line_no, raw in lines:
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("["):
                raise TOMLDecodeError(f"tables are unsupported at line {line_no}")
            if "=" not in stripped:
                raise TOMLDecodeError(f"expected key/value at line {line_no}")

            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not _KEY.match(key):
                raise TOMLDecodeError(f"unsupported key at line {line_no}: {key!r}")

            if value.startswith(('"""', "'''")):
                quote = value[:3]
                remainder = value[3:]
                parts: list[str] = []
                if quote in remainder:
                    data[key] = remainder.split(quote, 1)[0]
                    continue
                if remainder:
                    parts.append(remainder)
                for end_no, follow in lines:
                    if quote in follow:
                        parts.append(follow.split(quote, 1)[0])
                        data[key] = "\n".join(parts)
                        break
                    parts.append(follow)
                else:
                    raise TOMLDecodeError(
                        f"unterminated multi-line string for {key!r}"
                    )
                continue

            if value.startswith(('"', "'")):
                data[key] = _parse_string(value)
                continue

            data[key] = value

        return data
