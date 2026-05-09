import sys
import os
from lumen.core.database import LibraryDatabase
from lumen.core.pdk import PDKRegistry, generate_symbol_data

def main():
    db = LibraryDatabase('C:/Users/hegde/LumenWorkspace')
    r = PDKRegistry()
    for pdk in r.get_all_pdks():
        if not db.get_library(pdk.name):
            db.create_library(pdk.name, description=pdk.description)
            print(f"Created library {pdk.name}")
        for dev in pdk.devices:
            if dev.name not in db.get_cells(pdk.name):
                db.create_cell(pdk.name, dev.name)
            sym = generate_symbol_data(dev, pdk.name)
            sym['library'] = pdk.name
            db.save_view(pdk.name, dev.name, 'symbol', sym)
            print(f"  Generated symbol for {dev.name}")
    print("Done generating symbols!")

if __name__ == '__main__':
    main()
