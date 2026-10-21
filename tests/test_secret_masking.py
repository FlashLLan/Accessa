"""Value-level secret masking: only the secret value becomes [REDACTED]."""
import pytest

from backend.services.secret_masking import mask_secret_values, mask_secrets

AWS = "AKIA" + "IOSFODNN7EXAMPLE"
AWS_TEMP = "ASIA" + "Y34FZKBOKMUTVV7A"
GHP = "ghp_" + "A1b2" * 9
GHS = "ghs_" + "Z9y8" * 9
GH_PAT = "github_pat_11ABCDEFG0" + "x" * 30
OPENAI = "sk-proj-" + "Ab3" * 10
OPENAI_PLAIN = "sk-" + "9Zq" * 12
STRIPE = "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc"
SLACK = "xoxb-" + "123456789012-1234567890123-abcdefABCDEF"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"


# --- token-shaped secrets: masked wherever they appear ------------------------------------------

@pytest.mark.parametrize("secret", [AWS, AWS_TEMP, GHP, GHS, GH_PAT, OPENAI, OPENAI_PLAIN, STRIPE, SLACK, JWT],
                         ids=["aws", "aws-temp", "github-classic", "github-app", "github-pat", "openai-proj",
                              "openai", "stripe", "slack", "jwt"])
@pytest.mark.parametrize("template", ["{s}", "key: {s} (prod)", "headers = {{'X': '{s}'}}", "+    token {s}\n"])
def test_token_shaped_secrets_are_masked(secret, template):
    masked, count = mask_secrets(template.format(s=secret))
    assert secret not in masked
    assert masked == template.format(s="[REDACTED]")
    assert count == 1


@pytest.mark.parametrize("header", ["RSA PRIVATE KEY", "PRIVATE KEY", "OPENSSH PRIVATE KEY", "EC PRIVATE KEY",
                                    "ENCRYPTED PRIVATE KEY"])
def test_private_key_block_body_is_masked(header):
    text = f"before\n-----BEGIN {header}-----\nMIIEowIBAAKCAQEA\n+abcDEF==\n-----END {header}-----\nafter"
    masked, count = mask_secrets(text)
    assert masked == f"before\n-----BEGIN {header}-----\n[REDACTED]\n-----END {header}-----\nafter"
    assert count == 1


def test_private_key_block_cut_off_is_masked_to_the_end():
    masked, count = mask_secrets("-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nAAAA")
    assert masked == "-----BEGIN RSA PRIVATE KEY-----\n[REDACTED]"
    assert count == 1


def test_public_key_and_certificate_are_not_masked():
    text = "-----BEGIN PUBLIC KEY-----\nMFkw\n-----END PUBLIC KEY-----\n-----BEGIN CERTIFICATE-----\nMIIB\n"
    assert mask_secrets(text) == (text, 0)


# --- name = literal string -------------------------------------------------------------------------

@pytest.mark.parametrize("before, after", [
    ('password = "hunter2"', 'password = "[REDACTED]"'),
    ("DB_PASSWORD = 'S3cr3t!'", "DB_PASSWORD = '[REDACTED]'"),
    ('+    db_password: str = "S3cr3t!"', '+    db_password: str = "[REDACTED]"'),
    ('client_secret="abc123"', 'client_secret="[REDACTED]"'),
    ('SECRET_KEY = "django-insecure-xyz"', 'SECRET_KEY = "[REDACTED]"'),
    ('{"api_key": "abc123xyz", "name": "demo"}', '{"api_key": "[REDACTED]", "name": "demo"}'),
    ("const apiKey = 'k-123';", "const apiKey = '[REDACTED]';"),
    ("const authToken = `t0k3n`;", "const authToken = `[REDACTED]`;"),
    ('connect(host="db", password="p@ss")', 'connect(host="db", password="[REDACTED]")'),
    ('config["password"] = "x9"', 'config["password"] = "[REDACTED]"'),
    ('access_key := "AK1"', 'access_key := "[REDACTED]"'),
    ("'private_key' => 'pk-1'", "'private_key' => '[REDACTED]'"),
    ('token: "abc"', 'token: "[REDACTED]"'),
])
def test_secret_names_assigned_a_quoted_literal_are_masked(before, after):
    assert mask_secrets(before) == (after, 1)


@pytest.mark.parametrize("before, after", [
    ("API_TOKEN=abcdef123", "API_TOKEN=[REDACTED]"),
    ("export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG", "export AWS_SECRET_ACCESS_KEY=[REDACTED]"),
    ("+DB_PASSWORD=hunter2", "+DB_PASSWORD=[REDACTED]"),
    ("https://api.example.com/x?api_key=abc123&page=2", "https://api.example.com/x?api_key=[REDACTED]&page=2"),
    ("GET /hook?token=s3cr3t", "GET /hook?token=[REDACTED]"),
])
def test_env_style_and_query_string_literals_are_masked(before, after):
    assert mask_secrets(before) == (after, 1)


@pytest.mark.parametrize("path", ["config/app.yml", "deploy.yaml", ".env", ".env.production", "settings.ini",
                                  "pyproject.toml"])
def test_unquoted_values_are_masked_in_config_files(path):
    assert mask_secrets("password: hunter2\n  - token: abc", path) == (
        "password: [REDACTED]\n  - token: [REDACTED]", 2)


def test_unquoted_values_in_code_files_are_left_alone():
    # In code, `password = user_password` assigns a variable, not a literal.
    assert mask_secrets("password = user_password", "app.py") == ("password = user_password", 0)
    assert mask_secrets("password: hunter2", "app.py") == ("password: hunter2", 0)


# --- references and non-secrets stay unchanged --------------------------------------------------------

@pytest.mark.parametrize("text, path", [
    ('password = os.environ["DB_PASSWORD"]', None),
    ("api_key = os.environ.get('API_KEY')", None),
    ('api_key = os.getenv("API_KEY", "")', None),
    ("SECRET_KEY = settings.SECRET_KEY", None),
    ("const token = process.env.API_TOKEN;", None),
    ("const apiKey = import.meta.env.VITE_API_KEY;", None),
    ("token = get_token()", None),
    ('password: ${DB_PASSWORD}', "docker-compose.yml"),
    ('token: "${GITHUB_TOKEN}"', None),
    ("DB_PASSWORD=${DB_PASSWORD}", None),
    ("secret: {{ .Values.secret }}", "values.yaml"),
    ("password = %(DB_PASS)s", "alembic.ini"),
    ("password: <your-password>", "a.yml"),
    ('password = ""', None),
    ('token_type = "bearer"', None),
    ('password_hint = "Enter your password"', None),
    ('TOKEN_URL = "https://example.com/oauth/token"', None),
    ('<input type="password" name="password" autoComplete="current-password" />', None),
    ('if password == "x":', None),
    ("PWD=/usr/src/app", None),
    ('class="sk-spinner-fading-circle-large"', None),
    ("risk-assessment-for-production-rollout", None),
    ("const password = 'Enter a password';", None),
])
def test_references_and_non_secrets_are_unchanged(text, path):
    assert mask_secrets(text, path) == (text, 0)


def test_only_the_value_is_replaced_and_the_line_is_kept():
    line = '    client = Client(url="https://api.example.com", api_key="abc123", timeout=10)'
    assert mask_secrets(line)[0] == '    client = Client(url="https://api.example.com", api_key="[REDACTED]", timeout=10)'


def test_several_secrets_are_counted_and_values_returned():
    text = f'password = "one"\nAWS={AWS}\ntoken = "{GHP}"'
    masked, values = mask_secret_values(text)
    assert "one" not in masked and AWS not in masked and GHP not in masked
    assert sorted(values) == sorted(["one", AWS, GHP])


def test_already_masked_text_is_not_counted_again():
    once, n1 = mask_secrets('password = "hunter2"')
    assert mask_secrets(once) == (once, 0)
    assert n1 == 1


@pytest.mark.parametrize("value", [None, ""])
def test_empty_input(value):
    assert mask_secrets(value) == (value, 0)
