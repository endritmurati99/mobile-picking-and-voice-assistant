"""One rule for credential-secret files, enforced identically on both halves.

The check exists twice on purpose -- once on the host, as an early preflight
(`infrastructure/scripts/provision-n8n-credentials.sh`), and once in the
container, immediately before the read, on the very descriptor that is read
(`n8n/scripts/provision-credentials.mjs`). They inspect DIFFERENT files: the
same names live in two namespaces. That duplication is fine; what is not
fine is two different *predicates*, which is what they used to be:

* the host demanded the mode be literally ``600`` or ``400``;
* the container demanded only ``mode & 0o077 == 0``.

So ``0700`` passed one and failed the other. An operator satisfying the
container tripped the host, with an error message naming a rule the other
half does not enforce, and no single source of truth existed.

THE RULE, stated once and enforced by both halves:

    A credential secret file must be a regular file, must have no group or
    other permission bits (``mode & 0o077 == 0``), and must be owned by the
    account that reads it.

The mask is the right predicate, not the two literals: the property being
protected is "no account other than the owner can read this". ``0600``,
``0400`` and ``0700`` are indistinguishable from an attacker's position --
the group/other bits are the entire question. Enumerating two literals
rejects ``0700``/``0500`` while buying no protection at all, and it is the
weaker of the two implementations that enumerated them. The container half
is also the one the R3 re-review judged STRONGER than the plan required
(open with ``O_NOFOLLOW|O_NONBLOCK`` then ``fstat`` the descriptor), so the
preflight moves to the boundary's predicate, never the other way round.

These tests run BOTH real implementations over the same matrix and require
their verdicts to agree -- a source-text assertion alone would not have
caught the disagreement, because each file was internally consistent.
"""
from __future__ import annotations

import getpass
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOST_SCRIPT = ROOT / "infrastructure" / "scripts" / "provision-n8n-credentials.sh"
CONTAINER_SCRIPT = ROOT / "n8n" / "scripts" / "provision-credentials.mjs"

# The exact words both halves must use, so an operator reading either error
# message learns the same rule.
MODE_RULE_PHRASE = "no group or other permission bits"
OWNER_RULE_PHRASE = "owned by the account that reads it"

REQUIRED_SECRET_NAMES = (
    "pwr_n8n_native_header",
    "pwr_backend_to_n8n_active_hmac",
    "pwr_n8n_to_backend_active_hmac",
)

# Modes spanning both sides of the rule. The first four are owner-exclusive
# (accept); the rest leak a bit to group or other (reject). 0o700 and 0o500
# are the two the old host literal-list wrongly refused.
MODE_MATRIX = (
    (0o600, True),
    (0o400, True),
    (0o700, True),
    (0o500, True),
    (0o640, False),
    (0o604, False),
    (0o660, False),
    (0o601, False),
)

FAKE_DOCKER = """#!/usr/bin/env bash
# Stands in for `docker compose ... exec`. The secret check runs long before
# this, so anything reaching here means the preflight ACCEPTED the files.
echo '{}'
"""


def _host_verdict(tmp_path: Path, mode: int) -> tuple[bool, str]:
    """Run the real host preflight over a synthetic secret dir at `mode`."""
    secret_dir = tmp_path / f"secrets-{mode:o}"
    secret_dir.mkdir()
    for name in REQUIRED_SECRET_NAMES:
        secret_file = secret_dir / name
        secret_file.write_text("test-only-placeholder\n", encoding="utf-8")
        secret_file.chmod(mode)

    bin_dir = tmp_path / f"bin-{mode:o}"
    bin_dir.mkdir()
    docker_stub = bin_dir / "docker"
    docker_stub.write_text(FAKE_DOCKER, encoding="utf-8")
    docker_stub.chmod(docker_stub.stat().st_mode | stat.S_IEXEC)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["PWR_SECRET_DIR"] = str(secret_dir)
    env["PWR_SECRET_OWNER"] = getpass.getuser()
    env["COMPOSE_FILE"] = str(tmp_path / "unused-compose.yml")

    result = subprocess.run(
        ["bash", str(HOST_SCRIPT), "verify"],
        env=env, cwd=str(ROOT), capture_output=True, text=True, timeout=60,
    )
    return result.returncode == 0, result.stderr


def _container_verdict(tmp_path: Path, mode: int) -> tuple[bool, str]:
    """Run the real container-side read over a file at `mode`.

    Goes through readSecretFile, not only the pure predicate, so the verdict
    is the one the boundary actually produces at read time.
    """
    secret_dir = tmp_path / f"container-{mode:o}"
    secret_dir.mkdir()
    secret_file = secret_dir / "secret"
    secret_file.write_text("test-only-placeholder\n", encoding="utf-8")
    secret_file.chmod(mode)

    probe = (
        "const {readSecretFile} = await import(process.env.PWR_MODULE);\n"
        "try {\n"
        "  await readSecretFile(process.env.PWR_SECRET_PATH);\n"
        "  console.log(JSON.stringify({accepted: true, message: ''}));\n"
        "} catch (error) {\n"
        "  console.log(JSON.stringify({accepted: false, message: error.message}));\n"
        "}\n"
    )
    env = dict(os.environ)
    env["PWR_MODULE"] = CONTAINER_SCRIPT.as_uri()
    env["PWR_SECRET_PATH"] = str(secret_file)
    result = subprocess.run(
        ["node", "--input-type=module", "-e", probe],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    verdict = json.loads(result.stdout.strip().splitlines()[-1])
    return verdict["accepted"], verdict["message"]


@pytest.mark.parametrize(("mode", "expected_accept"), MODE_MATRIX)
def test_both_halves_return_the_same_verdict_for_the_same_mode(
    tmp_path, mode, expected_accept
):
    """The disagreement itself: same file mode, two answers.

    0o700 used to be accepted in the container and refused on the host, so
    an operator could satisfy exactly one of them at a time.
    """
    host_accepted, host_stderr = _host_verdict(tmp_path, mode)
    container_accepted, container_message = _container_verdict(tmp_path, mode)

    assert host_accepted == container_accepted, (
        f"mode {mode:04o}: host accepted={host_accepted} "
        f"({host_stderr.strip()!r}) but container accepted={container_accepted} "
        f"({container_message!r}) -- the two halves must enforce ONE predicate"
    )
    assert host_accepted is expected_accept, (
        f"mode {mode:04o}: expected accept={expected_accept} under "
        f"'mode & 0o077 == 0'; got {host_accepted} ({host_stderr.strip()!r})"
    )


def test_both_halves_name_the_same_mode_rule_when_they_refuse():
    """A shared predicate with two different explanations is still two rules.

    The host used to say "expected 600 or 400" -- a rule neither half
    actually enforces any more -- while the container said "group- or
    world-accessible".
    """
    host_source = HOST_SCRIPT.read_text(encoding="utf-8")
    container_source = CONTAINER_SCRIPT.read_text(encoding="utf-8")
    assert MODE_RULE_PHRASE in host_source
    assert MODE_RULE_PHRASE in container_source
    assert OWNER_RULE_PHRASE in host_source
    assert OWNER_RULE_PHRASE in container_source
    assert "expected 600 or 400" not in host_source, (
        "the literal-mode rule is gone from the predicate; it must not "
        "survive in the message an operator reads"
    )


def test_refusal_messages_actually_carry_the_shared_wording(tmp_path):
    """Not just present in the source -- emitted on the failing path."""
    _, host_stderr = _host_verdict(tmp_path, 0o640)
    _, container_message = _container_verdict(tmp_path, 0o640)
    assert MODE_RULE_PHRASE in host_stderr, host_stderr
    assert MODE_RULE_PHRASE in container_message, container_message
