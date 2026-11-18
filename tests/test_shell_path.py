import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("shell_path", ROOT / "scripts" / "shell_path.py")
shell_path = importlib.util.module_from_spec(_spec)
sys.modules["shell_path"] = shell_path
_spec.loader.exec_module(shell_path)

HOME = Path("/Users/me")
BIN = HOME / "Library/Python/3.15/bin"


@pytest.mark.parametrize(
    ("shell", "platform", "rc", "line"),
    [
        ("zsh", "darwin", HOME / ".zshrc", 'export PATH="$HOME/Library/Python/3.15/bin:$PATH"'),
        (
            "bash",
            "darwin",
            HOME / ".bash_profile",
            'export PATH="$HOME/Library/Python/3.15/bin:$PATH"',
        ),
        ("bash", "linux", HOME / ".bashrc", 'export PATH="$HOME/Library/Python/3.15/bin:$PATH"'),
        (
            "fish",
            "darwin",
            HOME / ".config/fish/conf.d/hp-scanner.fish",
            'fish_add_path --path "$HOME/Library/Python/3.15/bin"',
        ),
    ],
)
def test_shell_config(shell, platform, rc, line):
    config = shell_path.shell_config(BIN, shell, HOME, env={}, platform=platform)
    assert (config.rc_file, config.line) == (rc, line)


def test_zsh_honours_zdotdir_and_unknown_shell():
    config = shell_path.shell_config(BIN, "zsh", HOME, env={"ZDOTDIR": "/z"})
    assert config.rc_file == Path("/z/.zshrc")
    assert shell_path.shell_config(BIN, "tcsh", HOME, env={}) is None


def test_path_outside_home_is_absolute():
    config = shell_path.shell_config(Path("/opt/bin"), "zsh", HOME, env={})
    assert config.line == 'export PATH="/opt/bin:$PATH"'


def test_detect_shell():
    assert shell_path.detect_shell({"SHELL": "/opt/homebrew/bin/fish"}) == "fish"
    assert shell_path.detect_shell({}) == ""


def _config(tmp_path, directory="/a/bin"):
    return shell_path.shell_config(Path(directory), "zsh", tmp_path, env={})


@pytest.mark.parametrize("original", ["", "alias ll='ls -l'\n", "x=1\n\n# end\n"])
def test_add_then_remove_restores_file(tmp_path, original):
    config = _config(tmp_path)
    if original:
        config.rc_file.write_text(original)
    assert shell_path.add_block(config) == "added"
    text = config.rc_file.read_text()
    assert text.startswith(original) and text.endswith(shell_path.END + "\n")
    assert shell_path.has_block(config)
    assert shell_path.remove_block(config) is True
    assert config.rc_file.read_text() == original
    assert shell_path.remove_block(config) is False


def test_add_is_idempotent_and_updates_changed_dir(tmp_path):
    config = _config(tmp_path)
    config.rc_file.write_text("before\n")
    assert shell_path.add_block(config) == "added"
    assert shell_path.add_block(config) == "unchanged"
    config.rc_file.write_text(config.rc_file.read_text() + "after\n")
    newer = _config(tmp_path, "/b/bin")
    assert shell_path.add_block(newer) == "updated"
    text = newer.rc_file.read_text()
    assert text.count(shell_path.BEGIN) == 1 and "/b/bin" in text and "/a/bin" not in text
    assert text.startswith("before\n") and text.endswith("after\n")


def test_update_block_at_top_of_file_adds_no_blank_line(tmp_path):
    config = _config(tmp_path)
    shell_path.add_block(config)
    shell_path.add_block(_config(tmp_path, "/b/bin"))
    assert config.rc_file.read_text().startswith(shell_path.BEGIN)


def test_add_follows_symlinked_rc(tmp_path):
    real = tmp_path / "dotfiles" / "zshrc"
    real.parent.mkdir()
    real.write_text("# mine\n")
    (tmp_path / ".zshrc").symlink_to(real)
    shell_path.add_block(_config(tmp_path))
    assert (tmp_path / ".zshrc").is_symlink()
    assert shell_path.BEGIN in real.read_text()


def test_fish_creates_conf_d(tmp_path):
    config = shell_path.shell_config(Path("/a/bin"), "fish", tmp_path, env={})
    assert shell_path.add_block(config) == "added"
    assert config.rc_file.read_text() == (
        f'{shell_path.BEGIN}\nfish_add_path --path "/a/bin"\n{shell_path.END}\n'
    )


def test_on_path():
    assert shell_path.on_path(Path("/a/bin"), "/usr/bin:/a/bin")
    assert not shell_path.on_path(Path("/a/bin"), "/usr/bin:/a/bin2")


def test_instructions_unknown_shell():
    text = shell_path.instructions(BIN, None, HOME, "hpscan")
    assert "Until then, run it as: $HOME/Library/Python/3.15/bin/hpscan" in text
    assert "UPDATE_PATH=1" in text
