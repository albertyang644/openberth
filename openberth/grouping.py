from __future__ import annotations

from openberth.store import Store


def link_targets_to_new_berth(
    store: Store,
    berth_name: str,
    target_ids: list[int],
    color: str | None = None,
) -> int:
    berth_id = store.create_berth(berth_name, color)
    for target_id in target_ids:
        store.set_target_berth(target_id, berth_id)
    return berth_id


def unlink_targets(store: Store, target_ids: list[int]) -> None:
    for target_id in target_ids:
        store.set_target_berth(target_id, None)


def move_targets_to_berth(store: Store, berth_id: int, target_ids: list[int]) -> None:
    for target_id in target_ids:
        store.set_target_berth(target_id, berth_id)


def reorder_within_berth(store: Store, ordered_target_ids: list[int]) -> None:
    store.set_sort_orders(ordered_target_ids)

