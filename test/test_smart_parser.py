from __future__ import annotations

import argparse

import pytest

from tuochat.cli.utils.cli_suggestions import SmartParser


@pytest.fixture()
def parser() -> argparse.ArgumentParser:
    p = SmartParser(prog="mycli")
    sub = p.add_subparsers(dest="cmd", required=True)
    # a small set with some near-misses
    for name in ["init", "install", "inspect", "index"]:
        sp = sub.add_parser(name)
        sp.set_defaults(cmd=name)
    return p


def test_valid_subcommand_parses(parser):
    args = parser.parse_args(["install"])
    assert args.cmd == "install"


def test_invalid_subcommand_suggests_close_match(parser, capsys):
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["instll"])  # missing 'a'
    assert exc.value.code == 2

    # Argparse writes usage + our error to stderr
    err = capsys.readouterr().err
    # sanity: usage header is printed
    assert "usage:" in err
    # our enhanced message or Python 3.15+ argparse native suggestion shows the candidate
    assert "Did you mean:" in err or "maybe you meant" in err
    assert "install" in err


def test_invalid_subcommand_without_close_match(parser, capsys):
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["zzzzzz"])
    assert exc.value.code == 2

    err = capsys.readouterr().err
    assert "usage:" in err
    # No good suggestions for nonsense input — don't show hint text
    assert "Did you mean:" not in err


def test_error_message_includes_original_arg(parser, capsys):
    bad = "insatll"  # another near-miss
    with pytest.raises(SystemExit):
        parser.parse_args([bad])
    err = capsys.readouterr().err
    # The original token should appear in the argparse error message
    assert bad in err
