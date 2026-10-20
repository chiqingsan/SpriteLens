from __future__ import annotations

import unittest
from types import SimpleNamespace

from spritelens.services.account_selection_service import (
    AccountNotFound,
    AccountSelectionService,
    AccountSwitchBusy,
)


class _Store:
    def __init__(self, profiles, *, failure: Exception | None = None, events: list[str] | None = None):
        self.profiles = profiles
        self.failure = failure
        self.events = events if events is not None else []

    def list_account_profiles(self):
        self.events.append("profiles")
        return tuple(self.profiles)

    def load(self, uid):
        self.events.append(f"load:{uid}")
        if self.failure:
            raise self.failure
        return (f"data-{uid}",)

    def load_backpack(self, uid):
        self.events.append(f"backpack:{uid}")
        if self.failure:
            raise self.failure
        return f"backpack-{uid}"

    def load_hatch_slots(self, uid):
        self.events.append(f"slots:{uid}")
        if self.failure:
            raise self.failure
        return {uid}


class _PetRepository:
    def __init__(self, store, events):
        self.store = store
        self.events = events
        self.selected = 101
        self.applied = []

    def cached_account_profiles(self):
        return self.store.list_account_profiles()

    def consistent_snapshot(self):
        return SimpleNamespace(uid=self.selected)

    @property
    def identity(self):
        return None

    def select_historical_account(self, uid, profile, pets, backpack):
        self.events.append("apply:pets")
        self.selected = uid
        self.applied.append((uid, profile, pets, backpack))


class _Repo:
    def __init__(self, events, name):
        self.events = events
        self.name = name
        self.applied = []

    def select_historical_account(self, *args):
        self.events.append("apply:" + self.name)
        self.applied.append(args)


class AccountSelectionServiceTest(unittest.TestCase):
    def make_service(self, *, running=False, failure=None):
        events = []
        profiles = ((101, "甲", 40, "https://example/甲"), (202, "乙", 55, ""))
        pet_store = _Store(profiles, events=events)
        egg_store = _Store(profiles, failure=failure, events=events)
        home_store = _Store(profiles, events=events)
        pets = _PetRepository(pet_store, events)
        eggs = _Repo(events, "eggs")
        home = _Repo(events, "home")
        flowers = _Repo(events, "flowers")
        service = AccountSelectionService(
            pet_store=pet_store,
            egg_store=egg_store,
            home_store=home_store,
            pet_repository=pets,
            egg_box=eggs,
            home_repo=home,
            flower_repo=flowers,
            capture_running=lambda: running,
        )
        return service, pets, eggs, home, flowers, events

    def test_reads_every_domain_before_applying_any_snapshot(self):
        service, pets, eggs, home, flowers, events = self.make_service()

        service.select(202)

        first_apply = next(index for index, value in enumerate(events) if value.startswith("apply:"))
        self.assertTrue(all(not value.startswith("apply:") for value in events[:first_apply]))
        self.assertEqual(pets.selected, 202)
        self.assertEqual([item[0] for item in eggs.applied], [202])
        self.assertEqual([item[0] for item in home.applied], [202])
        self.assertEqual([item[0] for item in flowers.applied], [202])

    def test_read_failure_keeps_current_account_and_does_not_apply(self):
        service, pets, eggs, home, flowers, events = self.make_service(failure=OSError("read failed"))

        with self.assertRaises(OSError):
            service.select(202)

        self.assertEqual(pets.selected, 101)
        self.assertFalse(eggs.applied or home.applied or flowers.applied)

    def test_running_capture_blocks_switch(self):
        service, pets, eggs, home, flowers, events = self.make_service(running=True)

        with self.assertRaises(AccountSwitchBusy):
            service.select(202)

        self.assertEqual(pets.selected, 101)

    def test_unknown_account_is_rejected(self):
        service, pets, eggs, home, flowers, events = self.make_service()

        with self.assertRaises(AccountNotFound):
            service.select(404)

        self.assertEqual(pets.selected, 101)


if __name__ == "__main__":
    unittest.main()
