"""
Unit test for SimulatorBridge SSH remote execution & SimENV Machine setup options.
"""
import os
import pytest
from lumen.core.simulator import SimulatorBridge


def test_simulator_bridge_local_command():
    bridge = SimulatorBridge(
        simulator="GSPICE",
        exe_path="gspice",
        sim_env="local",
        save_mode="none",
        adaptive_maxstep=True,
    )
    cmd = bridge._build_command("input.sp", "waveforms.raw", threads=4)
    assert "--save" in cmd
    assert "none" in cmd
    assert "--adaptive-maxstep" in cmd
    assert "--threads" in cmd
    assert "4" in cmd
    assert "-o" in cmd
    assert "waveforms.raw" in cmd
    assert "input.sp" in cmd
    assert "--sim-env" not in cmd


def test_simulator_bridge_ssh_command_with_local_binary():
    gspice_bin = r"C:\EDA\GSPICE\build\Release\gspice.exe"
    bridge = SimulatorBridge(
        simulator="GSPICE",
        exe_path=gspice_bin,
        sim_env="remote",
        ssh_host="192.168.1.100",
        ssh_user="remoteuser",
        ssh_key="/path/to/key.pem",
        remote_gspice="/usr/bin/gspice",
        save_mode="selected",
        adaptive_maxstep=True,
    )
    cmd = bridge._build_command("input.sp", "waveforms.raw", threads=8)
    assert "--sim-env" not in cmd
    assert "gspice_ssh.py" in cmd[1]
    assert "--host" in cmd
    assert "192.168.1.100" in cmd
    assert "--user" in cmd
    assert "remoteuser" in cmd
    assert "--key" in cmd
    assert "/path/to/key.pem" in cmd
    assert "--remote-gspice" in cmd
    assert "/usr/bin/gspice" in cmd
    assert "--deploy-binary" in cmd
    assert "--local-binary" in cmd
    assert gspice_bin in cmd
    assert "--save" in cmd
    assert "selected" in cmd
    assert "--adaptive-maxstep" in cmd
    assert "--threads" in cmd
    assert "8" in cmd


def test_simulator_bridge_ssh_fallback_without_local_binary():
    bridge = SimulatorBridge(
        simulator="GSPICE",
        exe_path="non_existent_gspice_binary_xyz",
        sim_env="remote",
        ssh_host="192.168.1.100",
        ssh_user="remoteuser",
        ssh_key="/path/to/key.pem",
        remote_gspice="/usr/bin/gspice",
        save_mode="all",
        adaptive_maxstep=False,
    )
    cmd = bridge._build_command("input.sp", "waveforms.raw", threads=8)
    assert "gspice_ssh.py" in cmd[1]
    assert "--host" in cmd
    assert "192.168.1.100" in cmd
    assert "--user" in cmd
    assert "remoteuser" in cmd
    assert "--key" in cmd
    assert "/path/to/key.pem" in cmd
    assert "--remote-gspice" in cmd
    assert "/usr/bin/gspice" in cmd
    assert "--save" in cmd
    assert "all" in cmd
    assert "--adaptive-maxstep" not in cmd
    assert "--threads" in cmd
    assert "8" in cmd


def test_simulator_bridge_ssh_availability():
    bridge = SimulatorBridge(
        simulator="GSPICE",
        exe_path="non_existent_gspice_binary_xyz",
        sim_env="remote",
        ssh_host="10.0.0.1",
        ssh_user="admin",
    )
    assert bridge.is_available() is True
