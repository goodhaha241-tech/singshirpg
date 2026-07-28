import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import guild
import boss_training


class DummyCard:
    name = "테스트 기술"
    description = "테스트 주사위"
    is_aoe = False

    def use_card(self, *args, **kwargs):
        return [{"type": "attack", "value": 1, "effect": None}]


class DummyBoss:
    name = "테스트 보스"
    max_hp = 10_000
    current_hp = 10_000
    attack = 25
    defense = 25

    def decide_action(self):
        return DummyCard()


class DummyCharacter:
    name = "테스트 공격자"
    max_hp = 1_000
    current_hp = 1_000
    max_mental = 100
    current_mental = 100
    attack = 10
    defense = 10
    equipped_cards = ["기본공격"]
    equipped_artifact = None
    equipped_engraved_artifact = None

    def to_dict(self):
        return {
            "name": self.name,
            "hp": self.max_hp,
            "current_hp": self.current_hp,
            "max_mental": self.max_mental,
            "current_mental": self.current_mental,
            "attack": self.attack,
            "defense": self.defense,
        }


def make_lobby(*, controlled):
    user = SimpleNamespace(id=1, display_name="공격자")
    return SimpleNamespace(
        participants={
            1: {
                "user": user,
                "char": DummyCharacter(),
                "char_idx": 0,
                "data": {},
                "revived": False,
            }
        },
        user_boss_record={"boss_id": "boss"} if controlled else None,
        battle_id="battle" if controlled else None,
        boss_control_user_id=99 if controlled else None,
        boss_control_user=SimpleNamespace(id=99, display_name="보스 주인"),
        guild_info={"guild_id": 1},
        host=user,
    )


def make_dungeon_lobby(*, controlled=False):
    lobby = make_lobby(controlled=controlled)
    factors = [
        {"kind": "stat", "stat": "hp", "stars": 1},
        {"kind": "stat", "stat": "attack", "stars": 1},
        {"kind": "stat", "stat": "defense", "stars": 1},
    ]
    monsters = []
    for index, factor in enumerate(factors):
        monsters.append({
            "slot": index,
            "name": f"수문장 {index + 1}",
            "role": ("attack", "defense", "control")[index],
            "role_label": ("공격형", "방어형", "제어형")[index],
            "target_score": 1_000,
            "hp": 100,
            "mental": 100,
            "attack": 5,
            "defense": 5,
            "skills": [{
                "name": f"수문장 기술 {index + 1}",
                "dice": [{"type": "attack", "min": 5, "max": 9}],
                "effects": [],
                "cooldown": 2,
                "is_aoe": False,
            }],
            "factors": [factor],
        })
    elite = {
        "slot": 3,
        "name": "혼합체",
        "role": "elite",
        "role_label": "혼합 엘리트",
        "target_score": 2_400,
        "hp": 200,
        "mental": 200,
        "attack": 8,
        "defense": 8,
        "skills": monsters[0]["skills"],
        "factors": [],
    }
    lobby.user_boss_record = {
        "boss_id": "boss",
        "boss_name": "최종 보스",
        "owner_id": "99",
        "grade": "S",
        "boss_data": {
            "name": "최종 보스",
            "hp": 1_000,
            "mental": 500,
            "attack": 20,
            "defense": 20,
            "build": {"skills": monsters[0]["skills"], "ai_style": "balanced"},
            "dungeon": {
                "version": boss_training.DUNGEON_VERSION,
                "locked": True,
                "monsters": monsters,
                "elite": elite,
            },
        },
    }
    return lobby


class RaidFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_dungeon_floor_clear_grants_factor_and_recovers_party(self):
        lobby = make_dungeon_lobby()
        view = guild.RaidBattleView(
            lobby,
            boss_training.DungeonRaidMonster(
                lobby.user_boss_record["boss_data"]["dungeon"]["monsters"][0]
            ),
        )
        view._refresh_public_windows = AsyncMock()
        view._refresh_command_panels = AsyncMock()
        char = view.participants[1]["char"]
        char.current_hp = 500
        char.current_mental = 50
        char.runtime_cooldowns = {
            "guild_attack_bonus": 3,
            "gem_state": {"ripple_last_turn": 8},
            "fierce_attack": 8,
        }
        view.participants[1]["revived"] = True
        interaction = SimpleNamespace(channel=SimpleNamespace())

        advanced = await view._advance_dungeon_floor(interaction)

        self.assertTrue(advanced)
        self.assertEqual(view.floor_index, 1)
        self.assertEqual(char.max_hp, 1_150)
        self.assertEqual(char.attack, 10)
        self.assertGreater(char.current_hp, 500)
        self.assertTrue(view.inherited_factor_labels)
        self.assertEqual(view.turn, 1)
        self.assertEqual(char.runtime_cooldowns, {"guild_attack_bonus": 3})
        self.assertFalse(view.participants[1]["revived"])

    async def test_middle_dungeon_floors_do_not_use_hundred_turn_limit(self):
        lobby = make_dungeon_lobby()
        view = guild.RaidBattleView(
            lobby,
            boss_training.DungeonRaidMonster(
                lobby.user_boss_record["boss_data"]["dungeon"]["monsters"][0]
            ),
        )
        view.turn = guild.RAID_TURN_LIMIT
        view.selected_cards = {1: "기본공격"}
        view.end_raid = AsyncMock()
        view._refresh_public_windows = AsyncMock()
        view._refresh_command_panels = AsyncMock()
        interaction = SimpleNamespace(channel=SimpleNamespace())

        with (
            patch("guild.advance_guild_world_turn", new=AsyncMock(return_value={})),
            patch("guild.get_card", return_value=DummyCard()),
            patch("guild.process_gem_turn_start", return_value=""),
            patch(
                "guild.battle_engine.apply_stat_scaling",
                side_effect=lambda results, actor: results,
            ),
            patch(
                "guild.battle_engine.process_turn_start_artifacts",
                return_value=("", False),
            ),
            patch(
                "guild.battle_engine.process_clash_loop",
                return_value=("", 0, 0),
            ),
        ):
            await view.resolve_turn(interaction)

        view.end_raid.assert_not_awaited()
        self.assertEqual(view.turn, guild.RAID_TURN_LIMIT + 1)

    async def test_four_clears_reach_owner_controlled_final_boss(self):
        lobby = make_dungeon_lobby(controlled=True)
        view = guild.RaidBattleView(
            lobby,
            boss_training.DungeonRaidMonster(
                lobby.user_boss_record["boss_data"]["dungeon"]["monsters"][0]
            ),
        )
        view._refresh_public_windows = AsyncMock()
        view._refresh_command_panels = AsyncMock()
        interaction = SimpleNamespace(channel=SimpleNamespace())
        try:
            for expected_floor in range(1, 5):
                advanced = await view._advance_dungeon_floor(interaction)
                self.assertTrue(advanced)
                self.assertEqual(view.floor_index, expected_floor)
            self.assertTrue(view._on_final_floor())
            self.assertTrue(view._owner_controls_current_floor())
            self.assertIsInstance(view.boss, boss_training.UserBossMonster)
            self.assertIsNone(view.boss_intent)
            self.assertEqual(len(view.floor_results), 4)
        finally:
            if view.boss_choice_task:
                view.boss_choice_task.cancel()

    async def test_skill_and_passive_factors_become_temporary_combat_bonuses(self):
        lobby = make_dungeon_lobby()
        view = guild.RaidBattleView(
            lobby,
            boss_training.DungeonRaidMonster(
                lobby.user_boss_record["boss_data"]["dungeon"]["monsters"][0]
            ),
        )
        participant = view.participants[1]
        view._apply_dungeon_factor({
            "kind": "skill",
            "stars": 2,
            "skill": {
                "name": "계승의 일격",
                "dice": [{"type": "attack", "min": 8, "max": 14}],
                "effects": [],
                "cooldown": 2,
                "is_aoe": False,
            },
        })
        view._apply_dungeon_factor({
            "kind": "passive_discount",
            "passive": "low_hp_attack",
            "stars": 2,
        })
        self.assertIn("계승의 일격", participant["dungeon_skill_cards"])
        self.assertEqual(participant["dungeon_passives"]["low_hp_attack"], 0.75)
        self.assertIn("계승의 일격", view._new_command_view(1).cards)

        view._remove_dungeon_factors(participant)
        self.assertEqual(participant["dungeon_skill_cards"], {})
        self.assertEqual(participant["dungeon_passives"], {})

    async def test_raid_status_embed_shows_effects_immunity_and_resistance(self):
        view = guild.RaidBattleView(make_lobby(controlled=False), DummyBoss())
        view.boss.status_effects = {"bleed": 2, "paralysis": 1, "stun": 0}
        view.boss.status_immunity = "stun"
        view.boss.status_resistances = {"bleed": 50}
        participant = view.participants[1]["char"]
        participant.status_effects = {"bleed": 0, "paralysis": 0, "stun": 1}

        embed = view.get_status_embed()
        boss_field = embed.fields[0].value
        player_field = next(
            field.value for field in embed.fields
            if field.name.startswith("👤")
        )
        intent_field = next(
            field.value for field in embed.fields
            if field.name == "⚠️ 보스 의도"
        )
        self.assertIn("🩸 출혈 **2**", boss_field)
        self.assertIn("⚡ 마비 **1**", boss_field)
        self.assertIn("🛡️ 면역: 기절", boss_field)
        self.assertIn("🔰 저항: 출혈 50%", boss_field)
        self.assertIn("💫 기절 **1**", player_field)
        self.assertEqual(view.boss_target_ids, [1])
        self.assertIn("🎯 대상: **공격자**", intent_field)
        self.assertIn("테스트 주사위", intent_field)

    async def test_downed_character_revives_after_ten_turns_if_ally_survives(self):
        lobby = make_lobby(controlled=False)
        ally = DummyCharacter()
        lobby.participants[2] = {
            "user": SimpleNamespace(id=2, display_name="생존자"),
            "char": ally,
            "char_idx": 0,
            "data": {},
            "revived": False,
            "raid_revive_turn": None,
        }
        view = guild.RaidBattleView(lobby, DummyBoss())
        downed = view.participants[1]["char"]
        downed.current_hp = 0
        downed.current_mental = 0
        downed.status_effects = {"bleed": 3, "paralysis": 2, "stun": 1}
        view.participants[1]["raid_revive_turn"] = 11
        view.turn = 10
        self.assertEqual(view._revive_due_characters(), [])
        view.turn = 11
        logs = view._revive_due_characters()
        self.assertEqual(downed.current_hp, 200)
        self.assertEqual(downed.current_mental, 20)
        self.assertEqual(downed.status_effects, {"bleed": 0, "paralysis": 0, "stun": 0})
        self.assertIsNone(view.participants[1]["raid_revive_turn"])
        self.assertTrue(any("전선 복귀" in line for line in logs))

    async def test_no_revive_when_every_attacker_is_downed(self):
        view = guild.RaidBattleView(make_lobby(controlled=False), DummyBoss())
        participant = view.participants[1]
        participant["char"].current_hp = 0
        participant["raid_revive_turn"] = 1
        self.assertEqual(view._revive_due_characters(), [])
        self.assertEqual(participant["char"].current_hp, 0)

    async def test_user_boss_attacker_reward_ledger_and_daily_hope(self):
        view = guild.RaidBattleView(make_lobby(controlled=False), DummyBoss())
        view.user_boss_record = {
            "boss_id": "boss",
            "owner_id": "99",
            "grade": "SS",
        }
        view.battle_id = "battle-reward"
        participant = view.participants[1]
        latest = {
            "money": 0,
            "pt": 0,
            "characters": [{}],
            "life_data": {},
            "inventory": {},
        }

        async def mutate(_uid, callback, _name):
            callback(latest)
            return latest

        with patch("guild.mutate_user_data", side_effect=mutate):
            first = await view._save_participant_result(1, participant, win=True)
            second = await view._save_participant_result(1, participant, win=True)
        self.assertTrue(first["reward_granted"])
        self.assertFalse(second["reward_granted"])
        self.assertEqual((latest["money"], latest["pt"]), (13_750, 2_750))
        self.assertEqual(latest["inventory"]["순수한 희망"], 2)

    async def test_self_boss_attacker_gets_seventy_percent_without_hope(self):
        view = guild.RaidBattleView(make_lobby(controlled=False), DummyBoss())
        view.user_boss_record = {
            "boss_id": "boss",
            "owner_id": "1",
            "grade": "UF",
        }
        view.battle_id = "battle-self"
        participant = view.participants[1]
        latest = {
            "money": 0,
            "pt": 0,
            "characters": [{}],
            "life_data": {},
            "inventory": {},
        }

        async def mutate(_uid, callback, _name):
            callback(latest)
            return latest

        with patch("guild.mutate_user_data", side_effect=mutate):
            result = await view._save_participant_result(1, participant, win=True)
        self.assertEqual(
            result["reward"],
            {"money": 17_500, "pt": 3_500, "contribution": 350},
        )
        self.assertNotIn("순수한 희망", latest["inventory"])

    async def test_attacker_commands_wait_for_controlled_boss(self):
        view = guild.RaidBattleView(make_lobby(controlled=True), DummyBoss())
        try:
            self.assertIsNone(view.boss_intent)
            self.assertFalse(view.attackers_can_choose())
            self.assertTrue(view.btn_pick.disabled)

            status_names = [field.name for field in view.get_status_embed().fields]
            self.assertNotIn("📜 전투 로그", status_names)
            view.logs.append("분리된 로그")
            self.assertIn("분리된 로그", view.get_log_embed().description)

            view.boss_intent = DummyCard()
            view._sync_command_gate()
            self.assertTrue(view.attackers_can_choose())
            self.assertFalse(view.btn_pick.disabled)
        finally:
            if view.boss_choice_task:
                view.boss_choice_task.cancel()

    async def test_stale_command_panel_cannot_choose_before_boss(self):
        view = guild.RaidBattleView(make_lobby(controlled=True), DummyBoss())
        interaction = SimpleNamespace(
            response=SimpleNamespace(send_message=AsyncMock())
        )
        try:
            callback = view._make_raid_card_callback(1, view.turn)
            await callback(interaction, "기본공격")
            self.assertNotIn(1, view.selected_cards)
            interaction.response.send_message.assert_awaited_once()
            self.assertIn(
                "보스가 먼저 선택",
                interaction.response.send_message.await_args.args[0],
            )
        finally:
            if view.boss_choice_task:
                view.boss_choice_task.cancel()

    async def test_turn_one_hundred_ends_with_boss_victory(self):
        view = guild.RaidBattleView(make_lobby(controlled=False), DummyBoss())
        view.turn = guild.RAID_TURN_LIMIT
        view.selected_cards = {1: "기본공격"}
        view.end_raid = AsyncMock()
        view._refresh_public_windows = AsyncMock()
        interaction = SimpleNamespace(channel=SimpleNamespace())

        with (
            patch("guild.advance_guild_world_turn", new=AsyncMock(return_value={})),
            patch("guild.get_card", return_value=DummyCard()),
            patch("guild.process_gem_turn_start", return_value=""),
            patch(
                "guild.battle_engine.apply_stat_scaling",
                side_effect=lambda results, actor: results,
            ),
            patch(
                "guild.battle_engine.process_turn_start_artifacts",
                return_value=("", False),
            ),
            patch(
                "guild.battle_engine.process_clash_loop",
                return_value=("", 0, 0),
            ),
        ):
            await view.resolve_turn(interaction)

        view.end_raid.assert_awaited_once()
        args, kwargs = view.end_raid.await_args
        self.assertFalse(args[1])
        self.assertIn("100턴", kwargs["reason"])
        self.assertTrue(any("보스 자동 승리" in line for line in view.logs))

    async def test_all_attackers_downed_ends_raid_immediately(self):
        view = guild.RaidBattleView(make_lobby(controlled=False), DummyBoss())
        view.selected_cards = {1: "기본공격"}
        view.logs = ["이전 턴 로그"]
        view.end_raid = AsyncMock()
        interaction = SimpleNamespace(channel=SimpleNamespace())

        def knock_out(character, *_args, **_kwargs):
            character.current_hp = 0
            return "", 0, 0

        with (
            patch("guild.advance_guild_world_turn", new=AsyncMock(return_value={})),
            patch("guild.get_card", return_value=DummyCard()),
            patch("guild.process_gem_turn_start", return_value=""),
            patch(
                "guild.battle_engine.apply_stat_scaling",
                side_effect=lambda results, actor: results,
            ),
            patch(
                "guild.battle_engine.process_turn_start_artifacts",
                return_value=("", False),
            ),
            patch(
                "guild.battle_engine.process_clash_loop",
                side_effect=knock_out,
            ),
        ):
            await view.resolve_turn(interaction)

        view.end_raid.assert_awaited_once()
        args, kwargs = view.end_raid.await_args
        self.assertFalse(args[1])
        self.assertIn("모든 공격자", kwargs["reason"])
        self.assertNotIn("이전 턴 로그", view.get_log_embed().description)


if __name__ == "__main__":
    unittest.main()
