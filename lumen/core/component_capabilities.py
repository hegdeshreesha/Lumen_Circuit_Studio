"""Component backend capability matrix."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    model: str
    ngspice: bool = True
    gspice: bool = True
    xyce: bool = True
    notes: str = ""


_UNSUPPORTED_GSPICE = {
    # File/import backed components
    "SPICE_NETLIST", "SUB_FILE", "VHDL_FILE", "VERILOG_FILE",
    # Advanced digital/stateful blocks need mixed-signal runtime support.
    "DFF", "RSFF", "JKFF", "TFF_SR", "JKFF_SR", "DFF_SR", "DLATCH",
    "MUX2TO1", "MUX4TO1", "MUX8TO1", "DEMUX2TO4", "DEMUX3TO8", "DEMUX4TO16",
    "PRIO_ENC", "GREY2BIN", "BIN2GREY", "ANDOR4X2", "ANDOR4X3", "ANDOR4X4",
    "PAT2", "PAT3", "PAT4", "COMP1", "COMP2", "COMP4", "HADD1", "FADD1", "FADD2",
}

_UNSUPPORTED_XYCE = {
    "VHDL_FILE", "VERILOG_FILE",
}


def is_supported(spice_model: str, simulator: str) -> tuple[bool, str]:
    model = (spice_model or "").upper()
    sim = (simulator or "GSPICE").upper()
    if sim == "GSPICE" and model in _UNSUPPORTED_GSPICE:
        return False, f"{model} is not supported by current GSPICE backend."
    if sim == "XYCE" and model in _UNSUPPORTED_XYCE:
        return False, f"{model} is not supported by current Xyce backend."
    return True, ""
