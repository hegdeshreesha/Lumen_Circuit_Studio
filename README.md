# Lumen Circuit Studio 🌌
**A Modern, Open-Source Mixed-Signal EDA Suite.**

Lumen Circuit Studio is a high-performance schematic capture and design environment built for the modern analog engineer. Inspired by the industry-standard Cadence Virtuoso workflow, Lumen provides a professional "Obsidian" obsidian-based design experience with a focus on speed, aesthetics, and open-source integration.

---

## ✨ Features (v0.2 Milestone)
- **Obsidian Canvas:** A pure-black, high-contrast design environment optimized for long hours of layout and schematic design.
- **Virtuoso-Inspired Workflow:** Standard hotkeys (i for Instance, w for Wire, q for Properties) to ensure zero learning curve for industry professionals.
- **Intelligent Connectivity Engine:** Recursive net traversal and automatic junction (solder dot) placement.
- **Manhattan Routing:** Clean, orthogonal 90-degree wiring with real-time "ghost" pathing.
- **Dynamic PDK Management:** Built-in support for property editing and serialization of components like SKY130 FETs and resistors.
- **JSON Persistence:** Designs are saved in a clean, human-readable JSON format, making them natively compatible with Git and AI-driven analysis.

## 🛠 Tech Stack
- **Frontend:** Python 3.11+ with PySide6 (Qt6)
- **Graphics Engine:** QGraphicsScene with hardware-accelerated 2D rendering.
- **Database:** Hierarchical JSON-based circuit description.
- **Simulation (In-Progress):** Integration with the high-speed GSPICE C++ engine and OSDI (Verilog-A) loaders.

## 🚀 Getting Started
1. Ensure you have Python installed.
2. Install dependencies: `pip install pyside6`
3. Launch the studio: Run `LumenStudio.bat` or `python main.py`

---

## 🗺 Roadmap to v1.0
- [x] v0.1: Core UI & Library Manager
- [x] v0.2: Schematic Capture & Connectivity Engine
- [ ] v0.3: Netlisting & GSPICE Integration
- [ ] v0.4: KLayout IPC Link for Bidirectional Cross-Probing
- [ ] v1.0: Full SKY130/IHP_Open PDK support with LVS/DRC verification.

---
**Designed by Engineers, for Engineers.**
*Lumen Circuit Studio is currently in active development. Version 0.2.*
