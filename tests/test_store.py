from __future__ import annotations

import tempfile
import unittest

from openberth.models import DiscoveredTarget
from openberth.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db")
        self.store = Store(self.tmp.name)
        self.store.init()

    def tearDown(self) -> None:
        self.store.conn.close()
        self.tmp.close()

    def test_purge_all_clears_targets_berths_and_tombstones(self) -> None:
        self.store.upsert_discovered_targets(
            [DiscoveredTarget("forex", 1, 0, "forex:1"), DiscoveredTarget("forex", 2, 0, "forex:2")]
        )
        bid = self.store.create_berth("Trading")
        rows = self.store.list_targets()
        self.store.set_target_berth(rows[0].id, bid)
        self.store.set_preview(rows[0].id, "some output")
        self.store.close_tv(rows[1].id)
        # a dead tombstone, the thing that otherwise accumulates forever
        self.store.upsert_discovered_targets([])
        self.assertTrue(self.store.list_targets())

        self.store.purge_all()

        self.assertEqual(self.store.list_targets(include_hidden=True), [])
        self.assertEqual(self.store.list_berths(), [])
        self.assertIsNone(self.store.restore_last_closed_tv())

    def test_purge_all_keeps_settings(self) -> None:
        self.store.set_setting("ui.theme", "dark")
        self.store.purge_all()
        self.assertEqual(self.store.get_setting("ui.theme"), "dark")

    def test_upsert_discovery_and_status_transitions(self) -> None:
        first = [
            DiscoveredTarget("forex", 1, 0, "forex:1"),
            DiscoveredTarget("forex", 2, 0, "forex:2"),
        ]
        self.store.upsert_discovered_targets(first)
        rows = self.store.list_targets()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r.status for r in rows}, {"alive"})

        second = [DiscoveredTarget("forex", 1, 0, "forex:1")]
        self.store.upsert_discovered_targets(second)
        rows = self.store.list_targets()
        statuses = {(r.tmux_window, r.status) for r in rows}
        self.assertIn((1, "alive"), statuses)
        self.assertIn((2, "dead"), statuses)

    def test_display_name_not_overwritten(self) -> None:
        self.store.upsert_discovered_targets([DiscoveredTarget("fx", 1, 0, "fx:1")])
        row = self.store.list_targets()[0]
        self.store.rename_target(row.id, "Trader")
        self.store.upsert_discovered_targets([DiscoveredTarget("fx", 1, 0, "fx:1")])
        updated = self.store.list_targets()[0]
        self.assertEqual(updated.display_name, "Trader")

    def test_search_and_health(self) -> None:
        berth_id = self.store.create_berth("Forex", "green")
        self.store.upsert_discovered_targets([DiscoveredTarget("fx", 1, 0, "fx:1")])
        row = self.store.list_targets()[0]
        self.store.rename_target(row.id, "Trader")
        self.store.set_target_berth(row.id, berth_id)

        results = self.store.search_targets("trad")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["display_name"], "Trader")

        health = self.store.berth_health()
        self.assertEqual(health[berth_id], (1, 1))
        self.store.set_berth_color(berth_id, "orange")
        row = self.store.conn.execute("SELECT color FROM berths WHERE id = ?", (berth_id,)).fetchone()
        self.assertEqual(row["color"], "orange")

    def test_settings(self) -> None:
        self.store.set_setting("window.size", "1200x800")
        self.assertEqual(self.store.get_setting("window.size"), "1200x800")

    def test_close_and_restore_tv(self) -> None:
        self.store.upsert_discovered_targets([DiscoveredTarget("fx", 1, 0, "fx:1")])
        row = self.store.list_targets()[0]
        self.assertFalse(row.hidden)
        self.store.close_tv(row.id)
        visible = self.store.list_targets(include_hidden=False)
        self.assertEqual(len(visible), 0)
        restored_id = self.store.restore_last_closed_tv()
        self.assertEqual(restored_id, row.id)
        visible = self.store.list_targets(include_hidden=False)
        self.assertEqual(len(visible), 1)

    def test_activity_map(self) -> None:
        self.store.upsert_discovered_targets([DiscoveredTarget("fx", 1, 0, "fx:1")])
        row = self.store.list_targets()[0]
        self.assertEqual(self.store.target_activity_map(row.id, width=8), "########")
        self.store.upsert_discovered_targets([])
        self.assertEqual(self.store.target_activity_map(row.id, width=8), "........")

    def test_activity_map_uses_preview_text(self) -> None:
        self.store.upsert_discovered_targets([DiscoveredTarget("fx", 1, 0, "fx:1")])
        row = self.store.list_targets()[0]
        self.store.set_preview(row.id, "ab  cd\n  ef")
        self.assertEqual(self.store.target_activity_map(row.id, width=6, height=2), "##..##\n....##")

    def test_restore_last_closed_tv_restores_most_recent(self) -> None:
        self.store.upsert_discovered_targets(
            [DiscoveredTarget("fx", 1, 0, "fx:1"), DiscoveredTarget("fx", 2, 0, "fx:2")]
        )
        rows = self.store.list_targets()
        self.store.close_tv(rows[0].id)
        self.store.close_tv(rows[1].id)
        restored_id = self.store.restore_last_closed_tv()
        self.assertEqual(restored_id, rows[1].id)
        visible_ids = {row.id for row in self.store.list_targets(include_hidden=False)}
        self.assertIn(rows[1].id, visible_ids)
        self.assertNotIn(rows[0].id, visible_ids)

    def test_get_and_delete_berth(self) -> None:
        berth_id = self.store.create_berth("Forex", "#22c55e")
        row = self.store.get_berth(berth_id)
        assert row is not None
        self.assertEqual(row["name"], "Forex")
        self.assertEqual(row["color"], "#22c55e")

        self.store.upsert_discovered_targets([DiscoveredTarget("fx", 1, 0, "fx:1")])
        target = self.store.list_targets()[0]
        self.store.set_target_berth(target.id, berth_id)
        self.store.delete_berth(berth_id)
        self.assertIsNone(self.store.get_berth(berth_id))
        self.assertIsNone(self.store.list_targets()[0].berth_id)

    def test_set_berth_sort_orders_reorders_list(self) -> None:
        a = self.store.create_berth("Alpha", "#22c55e")
        b = self.store.create_berth("Bravo", "#3b82f6")
        c = self.store.create_berth("Charlie", "#ef4444")
        self.assertEqual([r["id"] for r in self.store.list_berths()], [a, b, c])

        self.store.set_berth_sort_orders([c, a, b])
        self.assertEqual([r["id"] for r in self.store.list_berths()], [c, a, b])

    def test_preview_cache(self) -> None:
        self.store.upsert_discovered_targets([DiscoveredTarget("fx", 1, 0, "fx:1")])
        row = self.store.list_targets()[0]
        self.store.set_preview(row.id, "line1\nline2")
        text, updated = self.store.get_preview(row.id)
        self.assertEqual(text, "line1\nline2")
        self.assertIsNotNone(updated)


if __name__ == "__main__":
    unittest.main()
