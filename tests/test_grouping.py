from __future__ import annotations

import tempfile
import unittest

from openberth.grouping import (
    link_targets_to_new_berth,
    move_targets_to_berth,
    unlink_targets,
)
from openberth.models import DiscoveredTarget
from openberth.store import Store


class GroupingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db")
        self.store = Store(self.tmp.name)
        self.store.init()
        self.store.upsert_discovered_targets(
            [DiscoveredTarget("fx", 1, 0, "fx:1"), DiscoveredTarget("fx", 2, 0, "fx:2")]
        )

    def tearDown(self) -> None:
        self.store.conn.close()
        self.tmp.close()

    def test_link_unlink_move(self) -> None:
        ids = [t.id for t in self.store.list_targets()]
        berth_id = link_targets_to_new_berth(self.store, "Forex", ids, "green")
        for t in self.store.list_targets():
            self.assertEqual(t.berth_id, berth_id)

        unlink_targets(self.store, [ids[0]])
        states = {t.id: t.berth_id for t in self.store.list_targets()}
        self.assertIsNone(states[ids[0]])
        self.assertEqual(states[ids[1]], berth_id)

        research = self.store.create_berth("Research", "blue")
        move_targets_to_berth(self.store, research, [ids[0]])
        states = {t.id: t.berth_id for t in self.store.list_targets()}
        self.assertEqual(states[ids[0]], research)


if __name__ == "__main__":
    unittest.main()

