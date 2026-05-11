# Symbol Placement Issue - Analysis & Fix

## Issue Description
Users reported being unable to place symbols in the schematic editor.

## Root Cause Analysis

### Critical Bug Found!
**The symbols were being created but immediately deleted by the mode switching logic.**

### Investigation Steps
1. **Database Check** ✓ - Symbol library system works correctly
   - Primitives library loads with 10 components
   - Symbol data loads correctly from database

2. **Symbol Rendering** ✓ - Graphics rendering works correctly
   - InstanceItem creates child graphics items properly
   - Symbols have correct bounding boxes and are visible

3. **THE BUG** ✗ - Found in `start_instance_placement()`:
   ```python
   # Old buggy code:
   ghost = InstanceItem(sym_data, '?', 0, 0)
   self.scene.addItem(ghost)          # Line 843: Add ghost to scene
   self._placement_ghost = ghost      # Line 844: Store reference
   self.set_mode('place')             # Line 845: PROBLEM!
   ```
   
   **What happened:**
   - Line 843-844: Ghost created and added to scene ✓
   - Line 845: `set_mode('place')` called
   - Inside `set_mode()`: calls `_cancel_current_action()` 
   - Inside `_cancel_current_action()`: **REMOVES the ghost we just added!** (lines 506-509)
   
   The ghost was being created and immediately deleted by the cancel logic!

## Fixes Applied

### Fix 1: Critical Bug - Mode Setting Order
Fixed the race condition where the ghost was being removed immediately after creation:

**File:** `lumen/gui/schematic_editor.py` (lines 828-852)

**Change:** Set mode variables directly BEFORE creating ghost:
```python
def start_instance_placement(self):
    """Open the instance browser, then enter placement mode."""
    dialog = InstanceBrowserDialog(self.db, parent=self)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        sym_data = dialog.get_symbol_data()
        if sym_data:
            # Set mode FIRST, before creating ghost
            # (set_mode calls _cancel_current_action which would remove the ghost)
            self._mode = 'place'
            self.canvas.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.canvas.setCursor(Qt.CursorShape.CrossCursor)
            self.mode_changed.emit('place')
            
            # Now create and add the ghost
            self._placement_sym_data = sym_data
            ghost = InstanceItem(sym_data, '?', 0, 0)
            ghost.setOpacity(0.5)
            self.scene.addItem(ghost)
            self._placement_ghost = ghost
```

### Fix 2: UX Enhancement - Double-Click Support
Added double-click functionality to Instance Browser Dialog (lines 938, 1017-1020):

```python
# In _setup_ui():
self.cell_list.itemDoubleClicked.connect(self._on_cell_double_clicked)

# New method:
def _on_cell_double_clicked(self, item):
    """Accept the dialog when a cell is double-clicked."""
    if self.selected_library and self.selected_cell:
        self.accept()
```

## How to Use Symbol Placement

### Method 1: Keyboard Shortcut (Fastest)
1. Press **'I'** key
2. Select a library (e.g., "primitives")
3. **Double-click** a cell (e.g., "res" for resistor)
4. Move mouse to desired location
5. Click to place component
6. Press **ESC** to exit placement mode

### Method 2: Menu/Toolbar
1. Click "Instance" button or menu item
2. Select library and cell
3. Click "OK" button OR double-click the cell
4. Place component on canvas

## Additional Features
- **'R'** - Rotate symbol 90° during placement
- **'X'** - Mirror horizontally
- **'Y'** - Mirror vertically
- **ESC** - Cancel placement mode
- **Right-click** - Cancel current action

## Testing Performed
- ✓ Database loads symbols correctly
- ✓ Symbol rendering works (InstanceItem creates graphics properly)
- ✓ Instance browser populates correctly
- ✓ Symbol data retrieval works
- ✓ Ghost creation fixed (no longer deleted immediately)
- ✓ Double-click now accepts dialog
- ✓ Symbols now visible and placeable on canvas

## Status
**FIXED** - Symbol placement now works correctly! The critical bug where ghosts were immediately deleted has been resolved, and UX improved with double-click support.
