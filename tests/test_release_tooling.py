import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

import hp_scanner

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    # scripts import each other (install_wheel -> shell_path), as they do when run directly
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    # Register before executing: on Python <=3.11, @dataclass looks the module up in sys.modules.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bump_version = _load("bump_version")
verify_wheel = _load("verify_wheel")


def test_version_file_is_semver_and_matches_package():
    version = (ROOT / "VERSION").read_text().strip()
    assert bump_version.parse(version)
    assert hp_scanner.__version__ == version


@pytest.mark.parametrize(
    ("version", "part", "expected"),
    [
        ("0.0.1", "patch", "0.0.2"),
        ("0.0.9", "patch", "0.0.10"),
        ("0.0.99", "patch", "0.0.100"),
        ("0.3.7", "minor", "0.4.0"),
        ("1.2.3", "major", "2.0.0"),
        ("1.2.3\n", "none", "1.2.3"),
    ],
)
def test_bump(version, part, expected):
    assert bump_version.bump(version, part) == expected


@pytest.mark.parametrize("bad", ["0.0.01", "01.0.0", "1.0", "1.0.0-rc1", "v1.0.0", ""])
def test_parse_rejects_non_semver(bad):
    with pytest.raises(ValueError, match="semantic version"):
        bump_version.parse(bad)


def test_bump_unknown_part():
    with pytest.raises(ValueError, match="Unknown part"):
        bump_version.bump("1.0.0", "build")


def test_bump_main_writes_file(tmp_path, capsys):
    f = tmp_path / "VERSION"
    f.write_text("0.0.1\n")
    assert bump_version.main(["patch", "--file", str(f)]) == 0
    assert f.read_text() == "0.0.2\n"
    assert capsys.readouterr().out.strip() == "0.0.2"


def test_bump_main_dry_run_and_errors(tmp_path, capsys):
    f = tmp_path / "VERSION"
    f.write_text("0.0.1\n")
    assert bump_version.main(["minor", "--file", str(f), "--dry-run"]) == 0
    assert f.read_text() == "0.0.1\n"
    f.write_text("0.0.01\n")
    assert bump_version.main(["patch", "--file", str(f)]) == 1
    assert bump_version.main(["patch", "--file", str(tmp_path / "missing")]) == 1
    assert "error:" in capsys.readouterr().err


def _wheel(tmp_path, version="0.0.1", requires=("pillow>=10.0", "requests>=2.31")):
    lines = ["Metadata-Version: 2.4", "Name: hp-scanner", f"Version: {version}"]
    lines += [f"Requires-Dist: {r}" for r in requires]
    lines.append("Requires-Dist: pytest>=8.0; extra == 'dev'")
    path = tmp_path / f"hp_scanner-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"hp_scanner-{version}.dist-info/METADATA", "\n".join(lines) + "\n")
    return path


@pytest.fixture
def project(tmp_path):
    (tmp_path / "VERSION").write_text("0.0.1\n")
    reqs = "# runtime\nPillow >= 10.0\n\n-c constraints.txt\nrequests>=2.31  # http\n"
    (tmp_path / "requirements.txt").write_text(reqs)
    return tmp_path


def test_verify_wheel_ok(project):
    problems = verify_wheel.verify(
        _wheel(project), project / "VERSION", project / "requirements.txt"
    )
    assert problems == []


def test_verify_wheel_reports_version_and_missing_requirements(project):
    wheel = _wheel(project, version="0.0.2", requires=("requests>=2.31",))
    problems = verify_wheel.verify(wheel, project / "VERSION", project / "requirements.txt")
    assert "wheel version 0.0.2 != VERSION 0.0.1" in problems
    assert any("pillow>=10.0" in p for p in problems)


def test_extras_only_requirement_does_not_count(project):
    (project / "requirements.txt").write_text("pytest>=8.0\n")
    problems = verify_wheel.verify(
        _wheel(project), project / "VERSION", project / "requirements.txt"
    )
    assert problems == ["requirement 'pytest>=8.0' missing from wheel Requires-Dist"]


def test_verify_wheel_main(project, capsys):
    args = ["--version-file", str(project / "VERSION"), "--requirements"]
    args.append(str(project / "requirements.txt"))
    assert verify_wheel.main([str(_wheel(project)), *args]) == 0
    assert "OK" in capsys.readouterr().out
    bad = project / "bad.whl"
    bad.write_bytes(b"not a zip")
    assert verify_wheel.main([str(bad), *args]) == 1
    empty = project / "empty.whl"
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("x.txt", "")
    assert verify_wheel.main([str(empty), *args]) == 1
    assert verify_wheel.main([str(_wheel(project, version="9.9.9")), *args]) == 1


install_wheel = _load("install_wheel")


def _user_target(externally_managed):
    return install_wheel.Target(
        "user",
        Path("/py/bin/python3"),
        Path("/u/bin"),
        user=True,
        externally_managed=externally_managed,
    )


def test_user_target_flags():
    assert _user_target(False).pip_flags == ["--user"]
    assert _user_target(True).pip_flags == ["--user", "--break-system-packages"]
    venv = install_wheel.Target("venv", Path("/v/bin/python"), Path("/v/bin"))
    assert venv.pip_flags == []


def test_choose_target_prefers_explicit_venv(tmp_path):
    target = install_wheel.choose_target(tmp_path / "env", env={"VIRTUAL_ENV": "/other"})
    assert target.python == (tmp_path / "env" / "bin" / "python").resolve()
    assert not target.user


def test_choose_target_uses_active_venv():
    target = install_wheel.choose_target(None, env={"VIRTUAL_ENV": "/act"})
    assert target.python == Path("/act/bin/python")
    assert target.description == "active venv /act"


@pytest.fixture
def running_in_venv(tmp_path, monkeypatch):
    """Pretend this interpreter lives in a venv at tmp_path/env (CI runners may not use one)."""
    venv = tmp_path / "env"
    monkeypatch.setattr(install_wheel.sys, "prefix", str(venv))
    monkeypatch.setattr(install_wheel.sys, "base_prefix", "/base")
    monkeypatch.setattr(install_wheel.sys, "executable", str(venv / "bin" / "python3"))
    monkeypatch.setattr(install_wheel.sys, "_base_executable", "/base/bin/python3", raising=False)
    return venv


def test_choose_target_inside_other_venv_interpreter_uses_it(running_in_venv, tmp_path):
    target = install_wheel.choose_target(None, env={}, dev_venv=tmp_path / "elsewhere")
    assert not target.user and target.python == running_in_venv / "bin" / "python"


def test_dev_venv_interpreter_falls_back_to_user_site_of_base_python(running_in_venv):
    # Running from the project's own dev venv must not install into it.
    target = install_wheel.choose_target(None, env={}, dev_venv=running_in_venv)
    assert target.user
    assert target.python == Path("/base/bin/python3")
    assert "ignoring the active dev .venv" in target.description


def test_activated_dev_venv_is_ignored_but_explicit_dev_venv_is_honoured():
    env = {"VIRTUAL_ENV": str(install_wheel.DEV_VENV)}
    assert install_wheel.choose_target(None, env=env).user
    explicit = install_wheel.choose_target(install_wheel.DEV_VENV, env=env)
    assert (
        not explicit.user and explicit.python == install_wheel.DEV_VENV.resolve() / "bin" / "python"
    )


def test_choose_target_user_site(monkeypatch):
    monkeypatch.setattr(install_wheel.sys, "prefix", install_wheel.sys.base_prefix)
    monkeypatch.setattr(install_wheel, "_is_externally_managed", lambda: True)
    target = install_wheel.choose_target(None, env={})
    assert target.user and target.pip_flags == ["--user", "--break-system-packages"]


def test_install_and_uninstall_commands():
    first, second = install_wheel.install_commands(_user_target(True), Path("d/x.whl"))
    assert first == [
        "/py/bin/python3",
        "-m",
        "pip",
        "install",
        "--no-warn-script-location",
        "--user",
        "--break-system-packages",
        "--force-reinstall",
        "--no-deps",
        "d/x.whl",
    ]
    assert second[-1] == "d/x.whl" and "--force-reinstall" not in second
    assert install_wheel.uninstall_command(_user_target(False))[3:] == [
        "uninstall",
        "-y",
        "hp-scanner",
    ]
    assert install_wheel.uninstall_command(_user_target(True))[-3:] == [
        "-y",
        "--break-system-packages",
        "hp-scanner",
    ]


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.delenv("ZDOTDIR", raising=False)
    return home


def _home_target(home):
    scripts = home / "Library" / "Python" / "3.15" / "bin"
    return install_wheel.Target("user", Path("/py"), scripts, user=True)


def test_report_path_prints_instructions_by_default(fake_home):
    msg = install_wheel.report_path(_home_target(fake_home), False, path="/usr/bin")
    assert "not on your PATH" in msg
    assert "make install UPDATE_PATH=1" in msg
    assert """echo 'export PATH="$HOME/Library/Python/3.15/bin:$PATH"' >> $HOME/.zshrc""" in msg
    assert "exec zsh" in msg
    assert not (fake_home / ".zshrc").exists()


def test_report_path_silent_when_already_on_path(fake_home):
    target = _home_target(fake_home)
    assert install_wheel.report_path(target, False, path=f"/usr/bin:{target.scripts}") is None


def test_report_path_update_writes_rc_once(fake_home):
    target = _home_target(fake_home)
    first = install_wheel.report_path(target, True, path="/usr/bin")
    assert "added" in first and "exec zsh" in first
    assert install_wheel.report_path(target, True, path="/usr/bin").endswith(
        "already adds " + str(target.scripts)
    )
    assert (fake_home / ".zshrc").read_text().count("hp-scanner PATH >>>") == 1


def test_report_path_unknown_shell_falls_back_to_instructions(fake_home, monkeypatch, capsys):
    monkeypatch.setenv("SHELL", "/bin/tcsh")
    msg = install_wheel.report_path(_home_target(fake_home), True, path="/usr/bin")
    assert "in your shell's startup file" in msg
    assert "can't detect" in capsys.readouterr().err


def test_report_path_venv(fake_home):
    venv = install_wheel.Target("venv", Path("/v/bin/python"), Path("/v/bin"))
    assert install_wheel.report_path(venv, False) is None
    assert "only applies to user installs" in install_wheel.report_path(venv, True)


def test_report_uninstall_path(fake_home):
    target = _home_target(fake_home)
    assert install_wheel.report_uninstall_path(target, False) is None
    install_wheel.report_path(target, True, path="")
    assert "still adds" in install_wheel.report_uninstall_path(target, False)
    assert "removed" in install_wheel.report_uninstall_path(target, True)
    assert "hp-scanner" not in (fake_home / ".zshrc").read_text()


def test_main_runs_pip_and_creates_venv(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(install_wheel.subprocess, "run", lambda cmd, check: calls.append(cmd))
    wheel = tmp_path / "hp_scanner-0.0.1-py3-none-any.whl"
    wheel.write_bytes(b"x")
    assert install_wheel.main(["--venv", str(tmp_path / "env"), str(wheel)]) == 0
    assert calls[0][1:3] == ["-m", "venv"]
    assert len(calls) == 3 and calls[1][-1] == str(wheel)
    assert "Installed:" in capsys.readouterr().out


def test_main_uninstall_and_errors(tmp_path, monkeypatch, capsys):
    def fail(cmd, check):
        raise install_wheel.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(install_wheel.subprocess, "run", fail)
    assert install_wheel.main(["--uninstall"]) == 1
    assert "error:" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        install_wheel.main([str(tmp_path / "missing.whl")])


def test_check_python():
    assert install_wheel.check_python((3, 10)) is None
    assert install_wheel.check_python((3, 15, 2)) is None
    msg = install_wheel.check_python((3, 9))
    assert "needs Python >= 3.10" in msg and "PYTHON=python3.13" in msg


def test_main_refuses_old_python(monkeypatch, capsys):
    monkeypatch.setattr(install_wheel, "check_python", lambda: "too old")
    assert install_wheel.main(["--uninstall"]) == 1
    assert "too old" in capsys.readouterr().err


release_notes = _load("release_notes")
REPO = "VirtuallyScott/HP_Scanner_App"


def test_release_notes_pin_this_version():
    notes = release_notes.build_notes("0.0.1", REPO)
    url = f"https://github.com/{REPO}/releases/download/v0.0.1/hp_scanner-0.0.1-py3-none-any.whl"
    assert f"python3 -m pip install --user {url}" in notes
    assert f"--break-system-packages {url}" in notes
    assert f"gh release download v0.0.1 -R {REPO} -p '*.whl'" in notes
    assert notes.startswith("## Install")


@pytest.mark.parametrize("rc", ["~/.zshrc", "~/.bash_profile", "~/.bashrc"])
def test_release_notes_show_echo_path_command(rc):
    notes = release_notes.build_notes("0.0.1", REPO)
    line = f'echo "export PATH=\\"$(python3 -m site --user-base)/bin:\\$PATH\\"" >> {rc}'
    assert line in notes
    assert "fish_add_path (python3 -m site --user-base)/bin" in notes


def test_release_notes_wheel_name_matches_build_output():
    # Must match what `python -m build` produces, or the download URL 404s.
    version = (ROOT / "VERSION").read_text().strip()
    assert release_notes.wheel_name(version) == f"hp_scanner-{version}-py3-none-any.whl"


def test_release_notes_append_changelog(tmp_path, capsys):
    log = tmp_path / "changelog.md"
    log.write_text("## What's Changed\n* feat: hpscan\n")
    assert release_notes.main(["0.0.2", "--repo", REPO, "--changelog", str(log)]) == 0
    out = capsys.readouterr().out
    assert out.index("## Install") < out.index("## What's Changed")
    assert "/v0.0.2/hp_scanner-0.0.2-py3-none-any.whl" in out


@pytest.mark.parametrize(
    ("version", "repo"), [("v0.0.1", REPO), ("0.1", REPO), ("0.0.1", "noslash"), ("0.0.1", "a/b c")]
)
def test_release_notes_reject_bad_input(version, repo, capsys):
    assert release_notes.main([version, "--repo", repo]) == 1
    assert "error:" in capsys.readouterr().err
