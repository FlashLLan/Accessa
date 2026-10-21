"""Value-level secret masking.

Finds hard-coded secret VALUES and replaces only the value with [REDACTED]; the
surrounding code (variable name, quotes, the rest of the line) stays, so the text
still reads normally. Used on everything sent to the AI review and on the Git
context's diff_text / changed_files_summary.

Detected:
- private key blocks (-----BEGIN ... PRIVATE KEY----- ... END), body masked
- AWS access key ids (AKIA..., ASIA...)
- GitHub tokens (ghp_, gho_, ghu_, ghs_, ghr_, github_pat_)
- OpenAI-style keys (sk-...), Stripe keys (sk_live_/sk_test_/rk_live_/rk_test_)
- Slack tokens (xoxb-, xoxp-, xoxa-, xoxo-, xoxs-, xoxr-)
- JWTs (eyJ....eyJ....signature)
- a name containing password / passwd / secret / token / api_key / access_key /
  private_key assigned a quoted literal (password = "...", "token": "...",
  connect(password='...'), DB_PASSWORD: str = "...")
- the same names assigned an unquoted literal in .env style (DB_PASSWORD=value)
  or in a URL query string (?token=value),
  and, in config files (.env, .yml, .ini, .toml, ...), `password: value`

Never masked: references such as os.environ["API_KEY"], os.getenv("TOKEN"),
process.env.API_TOKEN, settings.SECRET_KEY, ${DB_PASSWORD}, {{ secret }},
empty strings, and values containing spaces (labels like "Enter your password").
"""
import re

REDACTED = "[REDACTED]"

# --- token-shaped secrets (masked wherever they appear) ----------------------------------

_PRIVATE_KEY = re.compile(
    r"(-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----)"
    r"([\s\S]*?)"
    r"(-----END (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----|\Z)"
)

_TOKEN_PATTERNS = [
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),                        # AWS access key id
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b"),                    # GitHub classic tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,255}\b"),                  # GitHub fine-grained
    re.compile(r"(?<![\w-])sk-(?:proj-|svcacct-|admin-)?(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{20,}"),  # OpenAI style
    re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}\b"),            # Stripe
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),                      # Slack
    re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"),  # JWT
]

# --- name = literal --------------------------------------------------------------------------

# The name must END in one of the secret words, so token_type, password_hint or
# TOKEN_URL are not matched, while DB_PASSWORD, client_secret, apiKey, auth-token are.
_SECRET_NAME = (
    r"[A-Za-z0-9_.-]*?"
    r"(?:password|passwd|secret|secret[_-]?key|token|api[_-]?key|access[_-]?key|private[_-]?key)"
)

# name, optional closing quote (JSON/dict keys), optional type annotation, then = : := =>
_QUOTED_ASSIGNMENT = re.compile(
    r"""(?ix)
    (?<![A-Za-z0-9_])
    (?P<prefix>
        ["']?""" + _SECRET_NAME + r"""["']?\]?        # also config["password"] = "..."
        (?:\s*:\s*[A-Za-z_][\w\[\], |.]*?(?=\s*=))?   # type annotation: password: str = "..."
        \s*(?::=|=>|=|:)\s*
    )
    (?P<quote>["'`])
    (?P<value>[^"'`\n]*?)
    (?P=quote)
    """
)

# .env / shell style anywhere: DB_PASSWORD=value (upper-case name, no spaces around =).
_ENV_ASSIGNMENT = re.compile(
    r"""(?mx)
    (?P<prefix>^[+\- ]?[ \t]*(?:export[ \t]+)?
        [A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|SECRET_KEY|TOKEN|API_KEY|APIKEY|ACCESS_KEY|PRIVATE_KEY)
        =)
    (?P<value>[^\s"'`$#][^\s#]*)
    """
)

# URL query strings: ?token=value, &api_key=value.
_QUERY_ASSIGNMENT = re.compile(
    r"(?i)(?P<prefix>[?&]" + _SECRET_NAME + r"=)(?P<value>[^&\s#\"'`]+)"
)

# Config files only: password: value / password = value (unquoted).
_CONFIG_ASSIGNMENT = re.compile(
    r"""(?imx)
    (?P<prefix>^[+\- ]?[ \t]*(?:-[ \t]+)?(?:export[ \t]+)?""" + _SECRET_NAME + r"""[ \t]*[:=][ \t]*)
    (?P<value>[^\s"'`$#{<\[!|>&*][^\s#]*)
    """
)

CONFIG_SUFFIXES = (
    ".env", ".yml", ".yaml", ".ini", ".cfg", ".conf", ".toml", ".properties", ".tfvars",
)

_NOT_A_SECRET_VALUE = re.compile(
    r"""(?ix)^(?:
        \$\{?[\w.:-]+\}?              # $VAR, ${VAR}
      | \{\{.*\}\}                    # {{ template }}
      | %\(?\w+\)?s?                  # %(name)s
      | <[^>]*>                        # <your-token>
      | null | none | nil | true | false | ~
    )$"""
)


def _is_config_file(path: str | None) -> bool:
    if not path:
        return False
    name = path.rsplit("/", 1)[-1].lower()
    return name.startswith(".env") or name.endswith(CONFIG_SUFFIXES)


def _is_literal_secret(value: str) -> bool:
    return (
        bool(value)
        and REDACTED not in value
        and not any(c.isspace() for c in value)
        and not _NOT_A_SECRET_VALUE.match(value)
    )


def mask_secrets(text: str | None, path: str | None = None) -> tuple[str | None, int]:
    """Return (masked text, number of secrets masked). `path` (optional) is the file
    the text comes from; config files also get unquoted `name: value` matching."""
    masked, values = mask_secret_values(text, path)
    return masked, len(values)


def mask_secret_values(text: str | None, path: str | None = None) -> tuple[str | None, list[str]]:
    """Like mask_secrets, but returns the masked values themselves (in memory only;
    callers use them to count distinct secrets and must never store them)."""
    if not text:
        return text, []
    values: list[str] = []

    def private_key(match: re.Match) -> str:
        values.append(match[2].strip())
        return f"{match[1]}\n{REDACTED}\n{match[3]}" if match[3] else f"{match[1]}\n{REDACTED}"

    text = _PRIVATE_KEY.sub(private_key, text)

    def token(match: re.Match) -> str:
        values.append(match[0])
        return REDACTED

    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub(token, text)

    def assignment(match: re.Match) -> str:
        value = match["value"]
        if not _is_literal_secret(value):
            return match[0]
        values.append(value)
        quote = match.groupdict().get("quote") or ""
        return f"{match['prefix']}{quote}{REDACTED}{quote}"

    text = _QUOTED_ASSIGNMENT.sub(assignment, text)
    text = _ENV_ASSIGNMENT.sub(assignment, text)
    text = _QUERY_ASSIGNMENT.sub(assignment, text)
    if _is_config_file(path):
        text = _CONFIG_ASSIGNMENT.sub(assignment, text)
    return text, values
