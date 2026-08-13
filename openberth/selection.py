from __future__ import annotations


class SelectionModel:
    def __init__(self) -> None:
        self.selected: set[int] = set()
        self.anchor_index: int | None = None

    def single_click(self, item_id: int, index: int) -> set[int]:
        self.selected = {item_id}
        self.anchor_index = index
        return self.selected.copy()

    def ctrl_click(self, item_id: int, index: int) -> set[int]:
        if item_id in self.selected:
            self.selected.remove(item_id)
        else:
            self.selected.add(item_id)
            self.anchor_index = index
        return self.selected.copy()

    def shift_click(self, ids_in_order: list[int], index: int) -> set[int]:
        if self.anchor_index is None:
            item_id = ids_in_order[index]
            return self.single_click(item_id, index)
        start = min(self.anchor_index, index)
        end = max(self.anchor_index, index)
        self.selected = set(ids_in_order[start : end + 1])
        return self.selected.copy()

