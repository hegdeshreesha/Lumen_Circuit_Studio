"""
Lumen Circuit Studio — Undo/Redo Command System

Implements the Command pattern for all schematic editing operations.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


class Command(ABC):
    """Base class for undoable commands."""
    @abstractmethod
    def execute(self): ...
    @abstractmethod
    def undo(self): ...
    def description(self) -> str:
        return self.__class__.__name__


class CommandStack:
    """Manages undo/redo history."""

    def __init__(self, max_depth: int = 200):
        self._undo_stack: list[Command] = []
        self._redo_stack: list[Command] = []
        self._max = max_depth

    def execute(self, cmd: Command):
        cmd.execute()
        self._undo_stack.append(cmd)
        if len(self._undo_stack) > self._max:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        cmd = self._undo_stack.pop()
        cmd.undo()
        self._redo_stack.append(cmd)
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        cmd = self._redo_stack.pop()
        cmd.execute()
        self._undo_stack.append(cmd)
        return True

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def clear(self):
        self._undo_stack.clear()
        self._redo_stack.clear()


# ── Concrete Commands ─────────────────────────────────────────

class AddItemCommand(Command):
    def __init__(self, scene, item, item_list):
        self.scene = scene
        self.item = item
        self.item_list = item_list

    def execute(self):
        self.scene.addItem(self.item)
        if self.item not in self.item_list:
            self.item_list.append(self.item)

    def undo(self):
        self.scene.removeItem(self.item)
        if self.item in self.item_list:
            self.item_list.remove(self.item)


class DeleteItemsCommand(Command):
    def __init__(self, scene, items, lists_map):
        """lists_map: dict mapping item -> the list it belongs to"""
        self.scene = scene
        self.items = list(items)
        self.lists_map = lists_map

    def execute(self):
        for item in self.items:
            self.scene.removeItem(item)
            lst = self.lists_map.get(item)
            if lst is not None and item in lst:
                lst.remove(item)

    def undo(self):
        for item in self.items:
            self.scene.addItem(item)
            lst = self.lists_map.get(item)
            if lst is not None and item not in lst:
                lst.append(item)


class MoveItemsCommand(Command):
    def __init__(self, items, dx, dy):
        self.items = list(items)
        self.dx = dx
        self.dy = dy

    def execute(self):
        for item in self.items:
            item.moveBy(self.dx, self.dy)

    def undo(self):
        for item in self.items:
            item.moveBy(-self.dx, -self.dy)


class SetItemPositionsCommand(Command):
    """Set absolute item positions for drag moves that already occurred."""

    def __init__(self, old_positions: dict, new_positions: dict):
        self.old_positions = dict(old_positions)
        self.new_positions = dict(new_positions)
        self.items = list(self.new_positions.keys())

    def execute(self):
        for item, pos in self.new_positions.items():
            item.setPos(pos)

    def undo(self):
        for item, pos in self.old_positions.items():
            item.setPos(pos)

    def description(self) -> str:
        return f"Move {len(self.items)} item(s)"


class CompoundCommand(Command):
    """Groups multiple commands as one undo step."""
    def __init__(self, commands: list[Command]):
        self.commands = commands

    def execute(self):
        for cmd in self.commands:
            cmd.execute()

    def undo(self):
        for cmd in reversed(self.commands):
            cmd.undo()


class RotateCommand(Command):
    """Rotate instances by a specified angle."""

    def __init__(self, items, angle: float):
        self.items = list(items)
        self.angle = angle

    def execute(self):
        for item in self.items:
            item.setRotation(item.rotation() + self.angle)

    def undo(self):
        for item in self.items:
            item.setRotation(item.rotation() - self.angle)

    def description(self) -> str:
        return f"Rotate {len(self.items)} item(s) {self.angle}°"


class MirrorCommand(Command):
    """Mirror instances horizontally or vertically."""

    def __init__(self, items, axis: str):
        """
        Args:
            items: List of items to mirror
            axis: 'x' for horizontal mirror, 'y' for vertical mirror
        """
        self.items = list(items)
        self.axis = axis
        self._transforms = {}  # Store original transforms for undo

    def execute(self):
        for item in self.items:
            self._transforms[id(item)] = item.transform()
            if self.axis == 'x':
                # Horizontal mirror: scale(-1, 1)
                t = item.transform()
                item.setTransform(t * __import__('PyQt6.QtGui', fromlist=['QTransform']).QTransform(-1, 0, 0, 1, 0, 0))
            else:
                # Vertical mirror: scale(1, -1)
                t = item.transform()
                item.setTransform(t * __import__('PyQt6.QtGui', fromlist=['QTransform']).QTransform(1, 0, 0, -1, 0, 0))

    def undo(self):
        for item in self.items:
            orig = self._transforms.get(id(item))
            if orig:
                item.setTransform(orig)

    def description(self) -> str:
        return f"Mirror {len(self.items)} item(s) {'horizontally' if self.axis == 'x' else 'vertically'}"


class LabelCommand(Command):
    """Add or remove a net label."""

    def __init__(self, scene, label, label_list, add: bool = True):
        self.scene = scene
        self.label = label
        self.label_list = label_list
        self.add = add

    def execute(self):
        if self.add:
            self.scene.addItem(self.label)
            if self.label not in self.label_list:
                self.label_list.append(self.label)
        else:
            self.scene.removeItem(self.label)
            if self.label in self.label_list:
                self.label_list.remove(self.label)

    def undo(self):
        if self.add:
            self.scene.removeItem(self.label)
            if self.label in self.label_list:
                self.label_list.remove(self.label)
        else:
            self.scene.addItem(self.label)
            if self.label not in self.label_list:
                self.label_list.append(self.label)

    def description(self) -> str:
        action = "Add" if self.add else "Remove"
        return f"{action} label '{self.label.toPlainText()}'"


class PropertyChangeCommand(Command):
    """Change a property value on an instance."""

    def __init__(self, instance, property_name: str, old_value, new_value):
        self.instance = instance
        self.property_name = property_name
        self.old_value = old_value
        self.new_value = new_value

    def execute(self):
        if hasattr(self.instance, 'parameters'):
            self.instance.parameters[self.property_name] = self.new_value
        if hasattr(self.instance, 'refresh_graphics'):
            self.instance.refresh_graphics()

    def undo(self):
        if hasattr(self.instance, 'parameters'):
            self.instance.parameters[self.property_name] = self.old_value
        if hasattr(self.instance, 'refresh_graphics'):
            self.instance.refresh_graphics()

    def description(self) -> str:
        return f"Change {self.instance.instance_name}.{self.property_name} from {self.old_value} to {self.new_value}"


class WireModifyCommand(Command):
    """Modify wire geometry (split, merge, or move endpoints)."""

    def __init__(self, scene, old_wire_data: dict, new_wire_data: dict, wire_list: list):
        self.scene = scene
        self.old_wire_data = old_wire_data  # {"x1":, "y1":, "x2":, "y2":}
        self.new_wire_data = new_wire_data
        self.wire_list = wire_list
        self._wire_item = None

    def execute(self):
        # Create new wire item from new data
        from lumen.gui.schematic_editor import WireItem
        w = self.new_wire_data
        self._wire_item = WireItem(w["x1"], w["y1"], w["x2"], w["y2"])
        if "net" in w:
            self._wire_item.net_name = w["net"]

        # Add to scene and list
        self.scene.addItem(self._wire_item)
        self.wire_list.append(self._wire_item)

    def undo(self):
        # Remove the new wire
        if self._wire_item:
            self.scene.removeItem(self._wire_item)
            if self._wire_item in self.wire_list:
                self.wire_list.remove(self._wire_item)

    def description(self) -> str:
        return "Modify wire"
