from pathlib import Path

import pytest

from sshuptime.config import load_settings, validate_server_files


def test_discovery_relative_paths_and_overrides(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = config_dir / "sshuptime.yaml"
    config.write_text(
        "ssh:\n  port: 9000\n  host_key: keys/host\n  authorized_keys: keys/clients\ndashboard:\n  theme: nord\n  interval: 0.5\n"
    )
    monkeypatch.chdir(tmp_path)
    settings = load_settings(str(config), port=9022, host_key="override-key")
    assert settings.ssh.port == 9022
    assert settings.dashboard.theme == "nord"
    assert settings.dashboard.interval == 0.5
    assert settings.ssh.host_key == str(tmp_path / "override-key")
    assert settings.ssh.authorized_keys == str(config_dir / "keys/clients")
    monkeypatch.chdir(config_dir)
    assert load_settings().ssh.port == 9000
    assert load_settings(discover=False).ssh.port == 8022


@pytest.mark.parametrize(
    "yaml_text",
    [
        "ssh: [bad]",
        "dashboard: {interval: true}",
        "ssh: {port: false}",
        "ssh: {port: 70000}",
        "dashboard: {interval: .nan}",
        "dashboard: {interval: 0}",
        "dashboard: {theme: missing}",
        "ssh: {username: ''}",
        "ssh: {host_key: 123}",
        "ssh: {typo: 1}",
        "unknown: value",
        "[]",
        "ssh: [",
        "!!python/object:builtins.object {}",
    ],
)
def test_invalid_configuration_is_rejected(tmp_path, yaml_text):
    config = tmp_path / "invalid.yaml"
    config.write_text(yaml_text)
    with pytest.raises(ValueError):
        load_settings(str(config))


def test_explicit_missing_file_and_required_keys(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_settings(str(tmp_path / "missing.yaml"))
    with pytest.raises(ValueError, match="ssh.host_key"):
        validate_server_files(load_settings(discover=False))
    with pytest.raises(ValueError, match="does not exist"):
        validate_server_files(
            load_settings(discover=False, host_key=str(tmp_path / "missing"))
        )


def test_cli_uses_config_and_override(tmp_path, monkeypatch):
    import sshuptime
    from sshuptime import ssh

    config = tmp_path / "dashboard.yaml"
    (tmp_path / "host").touch()
    (tmp_path / "clients").touch()
    config.write_text(
        "ssh:\n  host_key: host\n  authorized_keys: clients\n  port: 9022\ndashboard:\n  theme: nord\n  interval: 0.5\n"
    )
    received = {}

    async def fake_server(*args, **kwargs):
        received.update(args=args, kwargs=kwargs)

    monkeypatch.setattr(ssh, "serve", fake_server)
    monkeypatch.setattr(
        "sys.argv", ["sshuptime", "serve", "--config", str(config), "--port", "8023"]
    )
    sshuptime.main()
    assert received["args"] == (
        "127.0.0.1",
        8023,
        str(tmp_path / "host"),
        str(tmp_path / "clients"),
        "monitor",
    )
    assert received["kwargs"] == {
        "theme": "nord",
        "interval": 0.5,
        "mode": "live",
        "podman_socket": None,
        "kubeconfig": None,
        "kube_context": None,
        "source_settings": load_settings(str(config), port=8023).sources,
    }


def test_sample_is_valid():
    config = Path(__file__).parent.parent / "sshuptime.example.yaml"
    settings = load_settings(str(config))
    assert settings.ssh.port == 8022
    assert settings.ssh.host_key == str(config.parent / "ssh_host_ed25519_key")


def test_pydantic_sources_and_default_theme(tmp_path, monkeypatch):
    from pydantic_settings import BaseSettings

    from sshuptime.config import Settings

    monkeypatch.chdir(tmp_path)
    assert isinstance(Settings(), BaseSettings)
    assert Settings().dashboard.theme == "sshuptime"
    (tmp_path / "sshuptime.yaml").write_text(
        "dashboard: {theme: nord, interval: 3}\nssh: {port: 9000}\n"
    )
    assert Settings().dashboard.theme == "nord"
    (tmp_path / ".env").write_text(
        "SSHUPTIME_DASHBOARD__THEME=dracula\nSSHUPTIME_SSH__PORT=9022\n"
    )
    assert load_settings().dashboard.theme == "dracula"
    assert load_settings().ssh.port == 9022
    assert load_settings().dashboard.interval == 3
    monkeypatch.setenv("SSHUPTIME_DASHBOARD__THEME", "gruvbox")
    assert load_settings().dashboard.theme == "gruvbox"
    assert load_settings(theme="nord").dashboard.theme == "nord"
    assert load_settings(discover=False).dashboard.theme == "gruvbox"
    assert load_settings(discover=False).ssh.port == 8022
