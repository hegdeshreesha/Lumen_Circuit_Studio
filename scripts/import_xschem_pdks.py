import os
import sys
from pathlib import Path
from lumen.core.database import LibraryDatabase
from lumen.core.xschem_parser import XschemParser

def import_pdk_symbols(db: LibraryDatabase, lib_name: str, sym_dir: str):
    if not os.path.exists(sym_dir):
        print(f"Error: Directory {sym_dir} does not exist.")
        return

    # Create library if it doesn't exist
    if not db.get_library(lib_name):
        db.create_library(lib_name, description=f"Imported from {sym_dir}")
        print(f"Created library {lib_name}")

    count = 0
    for root, _, files in os.walk(sym_dir):
        for file in files:
            if file.endswith('.sym'):
                filepath = os.path.join(root, file)
                sym_data = XschemParser.parse_sym_file(filepath)
                if not sym_data:
                    continue
                    
                cell_name = sym_data["name"]
                # Save to DB natively
                if cell_name not in db.get_cells(lib_name):
                    db.create_cell(lib_name, cell_name)
                
                sym_data["library"] = lib_name
                db.save_view(lib_name, cell_name, "symbol", sym_data)
                count += 1
                
    print(f"Imported {count} symbols into {lib_name}")

def main():
    db = LibraryDatabase('C:/Users/hegde/LumenWorkspace')
    
    # sky130
    import_pdk_symbols(db, "sky130", "C:/EDA/xschem_sky130/sky130_fd_pr")
    import_pdk_symbols(db, "sky130", "C:/EDA/xschem_sky130/sky130_stdcells")
    
    # ihp_sg13g2
    import_pdk_symbols(db, "ihp_sg13g2", "C:/EDA/ihp_pdk/ihp-sg13g2/libs.tech/xschem")
    
    # gf180mcu
    import_pdk_symbols(db, "gf180mcu", "C:/EDA/xschem_gf180mcu/gf180mcu_fd_pr")

if __name__ == '__main__':
    main()
