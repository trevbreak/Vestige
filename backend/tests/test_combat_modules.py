"""
Unit tests for Phase 6 — D&D 5e Rules Engine & Combat.

Covers:
  - ActionEconomyTracker
  - ConditionTracker
  - SpellSlotTracker
  - ConcentrationTracker
  - DeathSaveState + CombatState
  - CombatDetector
  - CombatManager
  - AvailableActionsBuilder (smoke)
"""

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# ActionEconomyTracker
# ═══════════════════════════════════════════════════════════════════════════════

class TestActionEconomyTracker:
    def _make(self, speed=30):
        from app.rules.action_economy import ActionEconomyTracker
        return ActionEconomyTracker(avatar_id=1, speed=speed)

    def test_initial_budget_full(self):
        t = self._make()
        b = t.get_budget()
        assert b.action is True
        assert b.bonus_action is True
        assert b.reaction is True
        assert b.movement_remaining == 30
        assert b.movement_total == 30

    def test_use_action_success(self):
        t = self._make()
        assert t.use_action() is True
        assert t.get_budget().action is False

    def test_use_action_twice_fails(self):
        t = self._make()
        t.use_action()
        assert t.use_action() is False

    def test_use_bonus_action(self):
        t = self._make()
        assert t.use_bonus_action() is True
        assert t.use_bonus_action() is False

    def test_use_reaction(self):
        t = self._make()
        assert t.use_reaction() is True
        assert t.use_reaction() is False

    def test_move_partial(self):
        t = self._make(speed=30)
        moved = t.move(15)
        assert moved == 15
        assert t.get_budget().movement_remaining == 15

    def test_move_capped_at_remaining(self):
        t = self._make(speed=30)
        moved = t.move(50)
        assert moved == 30
        assert t.get_budget().movement_remaining == 0

    def test_start_turn_resets(self):
        t = self._make()
        t.use_action()
        t.use_bonus_action()
        t.move(30)
        t.start_turn()
        b = t.get_budget()
        assert b.action is True
        assert b.bonus_action is True
        assert b.movement_remaining == 30

    def test_can_act_property(self):
        t = self._make()
        assert t.can_act is True
        t.use_action()
        assert t.can_act is False

    def test_set_speed(self):
        t = self._make(speed=30)
        t.set_speed(60)
        t.start_turn()
        assert t.get_budget().movement_total == 60
        assert t.get_budget().movement_remaining == 60

    def test_budget_to_dict(self):
        from app.rules.action_economy import ActionEconomyTracker
        t = ActionEconomyTracker(avatar_id=2, speed=25)
        d = t.get_budget().to_dict()
        assert d["action"] is True
        assert d["movement_total"] == 25


# ═══════════════════════════════════════════════════════════════════════════════
# ConditionTracker
# ═══════════════════════════════════════════════════════════════════════════════

class TestConditionTracker:
    def _make(self):
        from app.rules.conditions import ConditionTracker
        return ConditionTracker(avatar_id=1)

    def test_add_and_has(self):
        from app.rules.conditions import Condition
        t = self._make()
        t.add(Condition.POISONED)
        assert t.has(Condition.POISONED) is True

    def test_remove(self):
        from app.rules.conditions import Condition
        t = self._make()
        t.add(Condition.BLINDED)
        assert t.remove(Condition.BLINDED) is True
        assert t.has(Condition.BLINDED) is False

    def test_remove_absent_returns_false(self):
        from app.rules.conditions import Condition
        t = self._make()
        assert t.remove(Condition.CHARMED) is False

    def test_is_incapacitated_by_stunned(self):
        from app.rules.conditions import Condition
        t = self._make()
        t.add(Condition.STUNNED)
        assert t.is_incapacitated is True

    def test_is_incapacitated_false_for_poisoned(self):
        from app.rules.conditions import Condition
        t = self._make()
        t.add(Condition.POISONED)
        assert t.is_incapacitated is False

    def test_tick_removes_expired(self):
        from app.rules.conditions import Condition
        t = self._make()
        t.add(Condition.FRIGHTENED, duration_rounds=2)
        expired = t.tick()   # round 1 → 1 remaining
        assert Condition.FRIGHTENED not in expired
        assert t.has(Condition.FRIGHTENED)
        expired = t.tick()   # round 2 → expires
        assert Condition.FRIGHTENED in expired
        assert not t.has(Condition.FRIGHTENED)

    def test_indefinite_condition_never_expires(self):
        from app.rules.conditions import Condition
        t = self._make()
        t.add(Condition.GRAPPLED, duration_rounds=-1)
        for _ in range(10):
            t.tick()
        assert t.has(Condition.GRAPPLED)

    def test_active_conditions_list(self):
        from app.rules.conditions import Condition
        t = self._make()
        t.add(Condition.PRONE)
        t.add(Condition.BLINDED)
        names = t.active_conditions
        assert "prone" in names
        assert "blinded" in names

    def test_exhaustion(self):
        t = self._make()
        level = t.add_exhaustion(2)
        assert level == 2
        assert t.exhaustion_level == 2
        level = t.remove_exhaustion(1)
        assert level == 1

    def test_exhaustion_level_6_sets_unconscious(self):
        from app.rules.conditions import Condition
        t = self._make()
        t.add_exhaustion(6)
        assert t.has(Condition.UNCONSCIOUS)

    def test_can_move_false_when_grappled(self):
        from app.rules.conditions import Condition
        t = self._make()
        t.add(Condition.GRAPPLED)
        assert t.can_move is False

    def test_clear_all(self):
        from app.rules.conditions import Condition
        t = self._make()
        t.add(Condition.POISONED)
        t.add_exhaustion(3)
        t.clear_all()
        assert t.active_conditions == []
        assert t.exhaustion_level == 0


# ═══════════════════════════════════════════════════════════════════════════════
# SpellSlotTracker
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpellSlotTracker:
    def _make_wizard5(self):
        from app.rules.spell_slots import SpellSlotTracker
        return SpellSlotTracker.from_class_level("wizard", 5)

    def test_from_class_level_wizard5_has_slots(self):
        t = self._make_wizard5()
        assert t.remaining(1) == 4
        assert t.remaining(2) == 3
        assert t.remaining(3) == 2

    def test_use_slot(self):
        t = self._make_wizard5()
        assert t.use(3) is True
        assert t.remaining(3) == 1

    def test_use_slot_exhausted(self):
        t = self._make_wizard5()
        t.use(3); t.use(3)   # 2 max at level 3
        assert t.use(3) is False

    def test_long_rest_restores(self):
        t = self._make_wizard5()
        t.use(1); t.use(1)
        t.long_rest()
        assert t.remaining(1) == 4

    def test_short_rest_no_recovery_for_wizard(self):
        t = self._make_wizard5()
        t.use(1)
        t.short_rest()
        assert t.remaining(1) == 3

    def test_short_rest_warlock_recovery(self):
        from app.rules.spell_slots import SpellSlotTracker
        t = SpellSlotTracker.from_dict({"3": {"max": 2, "used": 2}})
        t.short_rest(warlock_slots=2)
        assert t.remaining(3) == 2

    def test_from_dict_full_format(self):
        from app.rules.spell_slots import SpellSlotTracker
        t = SpellSlotTracker.from_dict({"1": {"max": 4, "used": 1}, "2": {"max": 3, "used": 0}})
        assert t.remaining(1) == 3
        assert t.remaining(2) == 3

    def test_from_dict_legacy_format(self):
        from app.rules.spell_slots import SpellSlotTracker
        t = SpellSlotTracker.from_dict({"1": 4, "2": 3})
        assert t.remaining(1) == 4

    def test_from_dict_empty(self):
        from app.rules.spell_slots import SpellSlotTracker
        t = SpellSlotTracker.from_dict(None)
        assert t.has_any() is False

    def test_has_any(self):
        t = self._make_wizard5()
        assert t.has_any(minimum_level=3) is True
        t.use(3); t.use(3)
        assert t.has_any(minimum_level=3) is False

    def test_summary_string(self):
        t = self._make_wizard5()
        s = t.summary_string()
        assert "L1:" in s
        assert "4/4" in s

    def test_to_dict_round_trip(self):
        from app.rules.spell_slots import SpellSlotTracker
        t = self._make_wizard5()
        t.use(1)
        d = t.to_dict()
        t2 = SpellSlotTracker.from_dict(d)
        assert t2.remaining(1) == 3

    def test_half_caster_paladin_level1_no_slots(self):
        from app.rules.spell_slots import SpellSlotTracker
        t = SpellSlotTracker.from_class_level("paladin", 1)
        assert t.has_any() is False

    def test_half_caster_paladin_level5(self):
        from app.rules.spell_slots import SpellSlotTracker
        t = SpellSlotTracker.from_class_level("paladin", 5)
        assert t.remaining(1) == 4
        assert t.remaining(2) == 2

    def test_use_lowest_available(self):
        t = self._make_wizard5()
        lvl = t.use_lowest_available(minimum_level=1)
        assert lvl == 1


# ═══════════════════════════════════════════════════════════════════════════════
# ConcentrationTracker
# ═══════════════════════════════════════════════════════════════════════════════

class TestConcentrationTracker:
    def _make(self):
        from app.rules.concentration import ConcentrationTracker
        return ConcentrationTracker(avatar_id=1)

    def test_initially_not_concentrating(self):
        t = self._make()
        assert t.is_concentrating is False
        assert t.current_spell is None

    def test_start_concentration(self):
        t = self._make()
        prior = t.start("Bless")
        assert prior is None
        assert t.is_concentrating is True
        assert t.current_spell == "Bless"

    def test_start_displaces_prior(self):
        t = self._make()
        t.start("Bless")
        prior = t.start("Hex")
        assert prior == "Bless"
        assert t.current_spell == "Hex"

    def test_end_concentration(self):
        t = self._make()
        t.start("Bless")
        ended = t.end()
        assert ended == "Bless"
        assert t.is_concentrating is False

    def test_end_when_not_concentrating(self):
        t = self._make()
        assert t.end() is None

    def test_force_break(self):
        t = self._make()
        t.start("Fog Cloud")
        broken = t.force_break()
        assert broken == "Fog Cloud"
        assert not t.is_concentrating

    def test_tick_expires_spell(self):
        t = self._make()
        t.start("Bless", duration_rounds=2)
        expired = t.tick()   # round 1 → 1 remaining
        assert expired is False
        expired = t.tick()   # round 2 → expires
        assert expired is True
        assert not t.is_concentrating

    def test_tick_indefinite_never_expires(self):
        t = self._make()
        t.start("Hunter's Mark", duration_rounds=-1)
        for _ in range(20):
            t.tick()
        assert t.is_concentrating

    def test_check_concentration_sets_dc(self):
        t = self._make()
        t.start("Bless")
        t.check_concentration(damage_taken=20)
        assert t.get_concentration_dc() == 10   # max(10, 20//2) = 10

    def test_check_concentration_high_damage(self):
        t = self._make()
        t.start("Bless")
        t.check_concentration(damage_taken=30)
        assert t.get_concentration_dc() == 15   # max(10, 30//2) = 15

    def test_break_on_incapacitation(self):
        t = self._make()
        t.start("Sanctuary")
        broke = t.break_on_incapacitation()
        assert broke is True
        assert not t.is_concentrating

    def test_to_dict_concentrating(self):
        t = self._make()
        t.start("Bless", duration_rounds=5)
        d = t.to_dict()
        assert d["concentrating"] is True
        assert d["spell"] == "Bless"

    def test_to_dict_not_concentrating(self):
        t = self._make()
        d = t.to_dict()
        assert d["concentrating"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# DeathSaveState
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeathSaveState:
    def _make(self):
        from app.rules.combat import DeathSaveState
        return DeathSaveState(avatar_id=1)

    def test_three_successes_stable(self):
        ds = self._make()
        ds.save_success()
        ds.save_success()
        result = ds.save_success()
        assert result == "stable"
        assert ds.is_stable is True

    def test_three_failures_dead(self):
        ds = self._make()
        ds.save_failure()
        ds.save_failure()
        result = ds.save_failure()
        assert result == "dead"
        assert ds.is_dead is True

    def test_critical_hit_two_failures(self):
        ds = self._make()
        result = ds.critical_hit()
        assert ds.failures == 2

    def test_critical_hit_can_kill(self):
        ds = self._make()
        ds.save_failure()  # 1 failure
        result = ds.critical_hit()  # 2 more = 3 total
        assert result == "dead"

    def test_heal_resets_state(self):
        ds = self._make()
        ds.save_failure()
        ds.save_success()
        ds.heal()
        assert ds.successes == 0
        assert ds.failures == 0
        assert ds.is_stable is False

    def test_stable_blocks_further_saves(self):
        ds = self._make()
        ds.save_success(); ds.save_success(); ds.save_success()
        result = ds.save_failure()   # already stable — no change
        assert result == "stable"


# ═══════════════════════════════════════════════════════════════════════════════
# CombatState
# ═══════════════════════════════════════════════════════════════════════════════

class TestCombatState:
    def _make_combatants(self):
        from app.rules.combat import CombatantEntry
        return [
            CombatantEntry(avatar_id=1, name="Aldric", initiative=18, hp_current=40, hp_max=40),
            CombatantEntry(avatar_id=2, name="Kaela",  initiative=12, hp_current=30, hp_max=30),
            CombatantEntry(avatar_id=0, name="Goblin", initiative=8,  hp_current=10, hp_max=10, is_enemy=True),
        ]

    def _state(self):
        from app.rules.combat import CombatState
        s = CombatState(session_id=1)
        s.start(self._make_combatants())
        return s

    def test_start_sets_active_phase(self):
        from app.rules.combat import CombatPhase
        s = self._state()
        assert s.phase == CombatPhase.ACTIVE
        assert s.round == 1

    def test_initiative_order_sorted_descending(self):
        s = self._state()
        names = [c.name for c in s.initiative_order]
        assert names == ["Aldric", "Kaela", "Goblin"]

    def test_current_combatant_is_first(self):
        s = self._state()
        assert s.current_combatant.name == "Aldric"

    def test_next_turn_advances(self):
        s = self._state()
        nxt = s.next_turn()
        assert nxt.name == "Kaela"

    def test_round_increments_after_full_cycle(self):
        s = self._state()
        s.next_turn()  # Kaela
        s.next_turn()  # Goblin
        s.next_turn()  # Aldric (round 2)
        assert s.round == 2

    def test_deal_damage_reduces_hp(self):
        s = self._state()
        result = s.deal_damage(1, 10)
        assert result["hp_current"] == 30
        assert result["outcome"] == "damaged"

    def test_deal_damage_drops_to_zero(self):
        from app.rules.conditions import Condition
        s = self._state()
        result = s.deal_damage(1, 15)   # 15 < hp_max(40), so "down" not instant-death
        assert result["hp_current"] == 25
        result2 = s.deal_damage(1, 25)  # brings to 0, damage(25) < max(40) → "down"
        assert result2["hp_current"] == 0
        assert result2["outcome"] == "down"
        aldric = s.get_combatant(1)
        assert aldric.conditions.has(Condition.UNCONSCIOUS)

    def test_heal_restores_hp(self):
        s = self._state()
        s.deal_damage(2, 20)
        result = s.heal(2, 10)
        assert result["hp_current"] == 20

    def test_heal_from_zero_removes_unconscious(self):
        from app.rules.conditions import Condition
        s = self._state()
        s.deal_damage(2, 30)
        s.heal(2, 5)
        kaela = s.get_combatant(2)
        assert not kaela.conditions.has(Condition.UNCONSCIOUS)
        assert kaela.hp_current == 5

    def test_record_death_save_success(self):
        s = self._state()
        s.deal_damage(1, 20)   # partial damage first
        s.deal_damage(1, 20)   # bring to 0, outcome "down" (20 < max 40)
        s.record_death_save(1, True)
        saves = s.get_death_saves(1)
        assert saves.successes == 1

    def test_record_death_save_three_success_stable(self):
        s = self._state()
        s.deal_damage(1, 20)
        s.deal_damage(1, 20)   # "down"
        for _ in range(3):
            result = s.record_death_save(1, True)
        assert result == "stable"

    def test_record_death_save_three_failure_dead(self):
        s = self._state()
        s.deal_damage(1, 20)
        s.deal_damage(1, 20)   # "down"
        for _ in range(3):
            result = s.record_death_save(1, False)
        assert result == "dead"

    def test_set_initiative(self):
        s = self._state()
        s.set_initiative(2, 20)
        order = s.initiative_order
        assert order[0].name == "Kaela"   # now highest

    def test_end_clears_state(self):
        from app.rules.combat import CombatPhase
        s = self._state()
        s.end()
        assert s.phase == CombatPhase.ENDED
        assert s.initiative_order == []

    def test_to_dict_structure(self):
        s = self._state()
        d = s.to_dict()
        assert d["phase"] == "active"
        assert d["round"] == 1
        assert len(d["initiative_order"]) == 3
        assert d["current_turn"] == "Aldric"


# ═══════════════════════════════════════════════════════════════════════════════
# CombatDetector
# ═══════════════════════════════════════════════════════════════════════════════

class TestCombatDetector:
    def _det(self):
        from app.rules.combat_detector import CombatDetector
        return CombatDetector()

    def _signal(self, text):
        return self._det().detect(text).signal

    def test_start_combat_roll_initiative(self):
        from app.rules.combat_detector import CombatSignal
        assert self._signal("Everyone roll for initiative!") == CombatSignal.START_COMBAT

    def test_start_combat_roll_initiative_variant(self):
        from app.rules.combat_detector import CombatSignal
        assert self._signal("Roll initiative, combat begins!") == CombatSignal.START_COMBAT

    def test_end_combat(self):
        from app.rules.combat_detector import CombatSignal
        assert self._signal("Combat is over, you've defeated them.") == CombatSignal.END_COMBAT

    def test_end_combat_enemies_defeated(self):
        from app.rules.combat_detector import CombatSignal
        assert self._signal("The enemies are dead.") == CombatSignal.END_COMBAT

    def test_damage_detected(self):
        from app.rules.combat_detector import CombatSignal
        r = self._det().detect("Aldric takes 14 fire damage.")
        assert r.signal == CombatSignal.DAMAGE
        assert r.damage_amount == 14

    def test_death_save(self):
        from app.rules.combat_detector import CombatSignal
        assert self._signal("Roll a death saving throw.") == CombatSignal.DEATH_SAVE

    def test_next_round(self):
        from app.rules.combat_detector import CombatSignal
        assert self._signal("Next round, top of the order.") == CombatSignal.NEXT_ROUND

    def test_turn_prompt_your_turn(self):
        from app.rules.combat_detector import CombatSignal
        r = self._det().detect("Aldric, it's your turn.")
        assert r.signal == CombatSignal.TURN_PROMPT
        assert r.addressed_name == "Aldric"

    def test_turn_prompt_what_do_you_do(self):
        from app.rules.combat_detector import CombatSignal
        r = self._det().detect("Kaela, what do you do?")
        assert r.signal == CombatSignal.TURN_PROMPT
        assert r.addressed_name == "Kaela"

    def test_none_signal_on_empty(self):
        from app.rules.combat_detector import CombatSignal
        assert self._signal("") == CombatSignal.NONE

    def test_none_signal_on_narrative(self):
        from app.rules.combat_detector import CombatSignal
        assert self._signal("The tavern is warm and welcoming.") == CombatSignal.NONE

    def test_end_overrides_start_in_same_phrase(self):
        from app.rules.combat_detector import CombatSignal
        # End patterns checked first — "over" takes priority
        result = self._signal("Combat is over, roll initiative for the next encounter.")
        assert result == CombatSignal.END_COMBAT

    def test_is_dm_speech(self):
        d = self._det()
        assert d.is_dm_speech("DM") is True
        assert d.is_dm_speech("dm") is True
        assert d.is_dm_speech("Dungeon Master") is True
        assert d.is_dm_speech("Aldric") is False


# ═══════════════════════════════════════════════════════════════════════════════
# CombatManager
# ═══════════════════════════════════════════════════════════════════════════════

class TestCombatManager:
    def _manager(self):
        from app.services.combat_manager import CombatManager
        return CombatManager()

    def _combatants(self):
        return [
            {"avatar_id": 1, "name": "Aldric", "initiative": 18, "hp_current": 40, "hp_max": 40},
            {"avatar_id": 2, "name": "Kaela",  "initiative": 12, "hp_current": 30, "hp_max": 30},
            {"avatar_id": 0, "name": "Goblin", "initiative": 8,  "hp_current": 10, "hp_max": 10, "is_enemy": True},
        ]

    def test_start_combat(self):
        m = self._manager()
        state = m.start_combat(1, self._combatants())
        assert m.is_in_combat(1) is True
        assert state.round == 1

    def test_end_combat(self):
        m = self._manager()
        m.start_combat(1, self._combatants())
        m.end_combat(1)
        assert m.is_in_combat(1) is False

    def test_next_turn(self):
        m = self._manager()
        m.start_combat(1, self._combatants())
        nxt = m.next_turn(1)
        assert nxt.name == "Kaela"

    def test_deal_damage(self):
        m = self._manager()
        m.start_combat(1, self._combatants())
        result = m.deal_damage(1, 1, 10)
        assert result["hp_current"] == 30

    def test_heal(self):
        m = self._manager()
        m.start_combat(1, self._combatants())
        m.deal_damage(1, 2, 20)
        result = m.heal(1, 2, 5)
        assert result["hp_current"] == 15

    def test_add_condition(self):
        m = self._manager()
        m.start_combat(1, self._combatants())
        ok = m.add_condition(1, 1, "poisoned")
        assert ok is True

    def test_add_invalid_condition(self):
        m = self._manager()
        m.start_combat(1, self._combatants())
        ok = m.add_condition(1, 1, "turned_to_cheese")
        assert ok is False

    def test_remove_condition(self):
        m = self._manager()
        m.start_combat(1, self._combatants())
        m.add_condition(1, 1, "poisoned")
        ok = m.remove_condition(1, 1, "poisoned")
        assert ok is True

    def test_record_death_save(self):
        m = self._manager()
        m.start_combat(1, self._combatants())
        m.deal_damage(1, 1, 20)   # partial
        m.deal_damage(1, 1, 20)   # to 0 → "down"
        result = m.record_death_save(1, 1, True)
        assert result == "ongoing"

    def test_get_available_actions_text_in_combat(self):
        m = self._manager()
        m.start_combat(1, self._combatants())
        text = m.get_available_actions_text(1, 1, "Aldric")
        assert isinstance(text, str)
        assert len(text) > 0

    def test_get_available_actions_text_not_in_combat(self):
        m = self._manager()
        text = m.get_available_actions_text(99, 1, "Aldric")
        assert text == ""

    def test_process_transcript_start_combat(self):
        from app.rules.combat_detector import CombatSignal
        m = self._manager()
        sig = m.process_transcript(1, "DM", "Roll for initiative!")
        assert sig == CombatSignal.START_COMBAT

    def test_process_transcript_non_dm_ignored(self):
        from app.rules.combat_detector import CombatSignal
        m = self._manager()
        sig = m.process_transcript(1, "Aldric", "Roll for initiative!")
        assert sig == CombatSignal.NONE

    def test_stop_session_removes_state(self):
        m = self._manager()
        m.start_combat(1, self._combatants())
        m.stop_session(1)
        assert m.get_state(1) is None

    def test_get_combat_state_dict_inactive(self):
        m = self._manager()
        d = m.get_combat_state_dict(99)
        assert d["phase"] == "inactive"

    def test_rest_long(self):
        from app.rules.spell_slots import SpellSlotTracker
        m = self._manager()
        combatants = self._combatants()
        combatants[0]["spell_slots"] = {"1": {"max": 4, "used": 4}}
        m.start_combat(1, combatants)
        m.rest(1, 1, "long")
        state = m.get_state(1)
        aldric = state.get_combatant(1)
        assert aldric.spell_slots.remaining(1) == 4
