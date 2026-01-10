# recruitment.py
import discord
import random
import json
import os
from character import Character
from cards import get_card
from battle import BattleView
from story import update_quest_progress
from data_manager import get_user_data

DATA_FILE = "user_data.json"

# --- 퀘스트용 몬스터 정의 ---
class QuestMonster:
    """BattleView와 호환되는 퀘스트 전용 몬스터 클래스"""
    def __init__(self, name, hp, cards, attack=0, defense=0):
        self.name = name
        self.max_hp = hp
        self.current_hp = hp
        self.max_mental = hp
        self.current_mental = hp
        self.attack = attack 
        self.defense = defense
        self.equipped_cards = cards
        self.money_range = (0, 0)
        self.pt_range = (0, 0)
        self.reward = None
        self.reward_count = 0

    def decide_action(self):
        """랜덤으로 카드 하나 선택"""
        card_name = random.choice(self.equipped_cards)
        return get_card(card_name)
    

# --- 영입 캐릭터 데이터 레지스트리 ---
RECRUIT_REGISTRY = {
    "Yeongsan": {
        "name": "영산", 
        "description": "일한산으로 여정을 떠나는 작은 마법생물",
        "emoji": "🐀",
        "quests": [
            {
                "title": "🐀 첫 번째 발자취",
                "story": "그는 양담산이라는 작은 산에서 지내던 바라사촌이었답니다. 깨끗한 것을 좋아하는 마법생물이지요.",
                "req_items": {"신화의 발자취": 1, "낡은 모래시계": 30},
                "req_money": 3000
            },
            {
                "title": "🐀 두 번째 발자취",
                "story": "어느 날, 그는 함께 살던 무리를 잃고 헤메다가, 어떤 교단의 사제라는 노인을 만나 사람의 모습을 하는 마법을 배웠어요.",
                "req_items": {"신화의 발자취": 1, "빈 앨범": 100},
                "req_money": 4000
            },
            {
                "title": "🐀 세 번째 발자취",
                "story": "늙은 사제와 함께 살던 바라사촌은 결국 그의 최후를 지켜보고, '영산'이라는 이름을 받게 됩니다.",
                "req_items": {"신화의 발자취": 1, "하급 마력석": 3, "반짝가루": 2},
                "req_money": 3000
            }
        ],
        "char_data": {
            "name": "영산",
            "hp": 270,
            "attack": 25,
            "defense": 40,
            "max_mental": 160,
            "card_slots": 5,
            "equipped_cards": ["전부매입", "금융치료"],
            "is_recruited": True
        }
    },
    "Earthreg": {
        "name": "어즈렉",
        "description": "신에게 가장 먼저 조아린 이",
        "emoji": "🛡️",
        "quests": [
            {
                "type": "item",
                "title": "🛡️ 첫 번째 발자취",
                "story": "'신이 빚은 거인이자 심복은 인간의 곁에 내려가, 그들을 돕고는 하였습니다.'",
                "req_items": {"신화의 발자취": 1, "설국 열매": 20, "무지개 열매": 20},
                "req_money": 0
            },
            {
                "type": "battle",
                "title": "🛡️ 두 번째 발자취",
                "story": "'두려워하는 인간들을 위해 봉인한 육체. 원래의 힘에는 한참 못 미칠 약한 몸입니다.'",
                "req_items": {"신화의 발자취": 1},
                "req_money": 0,
                "monster_data": {
                    "name": "열화된 심복",
                    "hp": 150,
                    "cards": ["섬세한 방어", "강한참격", "숨고르기", "집중반격"]
                }
            },
            {
                "type": "battle",
                "title": "🛡️ 세 번째 발자취",
                "story": "'그럼에도 어떤 상황에서도 대비하기 위해서, 그는 다시금 새로운 곳으로 발을 내딛습니다.'",
                "req_items": {"신화의 발자취": 1},
                "req_money": 0,
                "monster_data": {
                    "name": "봉인된 심복",
                    "hp": 170,
                    "cards": ["회전베기", "숨고르기", "섬세한 방어", "방어와 수복"]
                }
            }
        ],
        "char_data": {
            "name": "어즈렉",
            "hp": 280,
            "attack": 20,
            "defense": 50,
            "max_mental": 200,
            "card_slots": 5,
            "equipped_cards": ["방어와 수복", "방어와 침착"],
            "is_recruited": True
        }
    },
    "Luude10": {
        "name": "루우데 10%",
        "description": "균형을 지키는 수호자",
        "emoji": "☘️",
        "quests": [
            {
                "type": "item",
                "title": "☘️ 첫 번째 발자취",
                "story": "비록 자그마한 아이의 모습일지라도,",
                "req_items": {"신화의 발자취": 1, "흐린 꿈": 30, "맑은 생각": 5},
                "req_money": 25000
            },
            {
                "type": "item",
                "title": "☘️ 두 번째 발자취",
                "story": "태어날 때부터 정해진 의무를 저버린 적 없으니,",
                "req_items": {"신화의 발자취": 1, "친절함 한 스푼": 5, "태양 선글라스": 2},
                "req_money": 4000
            },
            {
                "type": "item",
                "title": "☘️ 세 번째 발자취",
                "story": "그를 '닿을 수 없는 꿈' 이라 불렀고",
                "req_items": {"신화의 발자취": 1, "신전의 등불": 4, "추억사진첩": 20},
                "req_money": 21000
            },
            {
                "type": "battle",
                "title": "☘️ 네 번째 발자취",
                "story": "'가장 친절한 악몽'이라 부른다.",
                "req_items": {"신화의 발자취": 1},
                "req_money": 0,
                "monster_data": {
                    "name": "닿을 수 없는 꿈",
                    "hp": 200,
                    "attack": 20,
                    "defense": 35,
                    "cards": ["사우전드웨이브", "잠금", "자각몽", "꿈꾸기"]
                }
            }
        ],
        "char_data": {
            "name": "루우데 10%",
            "hp": 250,
            "attack": 30,
            "defense": 34,
            "max_mental": 210,
            "card_slots": 5,
            "equipped_cards": ["사우전드웨이브", "잠금"],
            "is_recruited": True
        }
    },
    # [신규] 센쇼
    "Sensho": {
        "name": "센쇼",
        "description": "천년을 잠들었던 별",
        "emoji": "🌟",
        "quests": [
            {
                "type": "item",
                "title": "🌟 첫 번째 발자취",
                "story": "\"천년의 잠에서 깨어나 신의 명을 받고 내려왔습니다.\"",
                "req_items": {"신화의 발자취": 1, "별모양 별": 20, "천년얼음": 10},
                "req_money": 0
            },
            {
                "type": "item",
                "title": "🌟 두 번째 발자취",
                "story": "\"많은 생명체들에게 사랑을 전해주어야 합니다.\"",
                "req_items": {"신화의 발자취": 1, "사랑나무 가지": 10, "따스한 목도리": 5},
                "req_money": 0
            },
            {
                "type": "item",
                "title": "🌟 세 번째 발자취",
                "story": "\"그대의 모험에 신의 빛이 따르기를.\"",
                "req_items": {"신화의 발자취": 1, "반짝가루": 1, "빛구슬": 20, "맑은 생각": 10},
                "req_money": 0
            }
        ],
        "char_data": {
            "name": "센쇼",
            "hp": 180,
            "attack": 28,
            "defense": 30,
            "max_mental": 210,
            "card_slots": 5,
            "equipped_cards": ["파멸의 소원", "치유의 소원", "별의 은총"],
            "is_recruited": True
        }
    },
    # [신규] 샤일라
    "Shayla": {
        "name": "샤일라",
        "description": "은하새의 선조",
        "emoji": "🐦",
        "quests": [
            {
                "type": "item",
                "title": "🐦 첫 번째 발자취",
                "story": "\"일한산에 사는 보랏빛 작은 은하새입니다.\"",
                "req_items": {"신화의 발자취": 1, "별모양 별": 5, "눈꽃팬던트": 3},
                "req_money": 5000
            },
            {
                "type": "item",
                "title": "🐦 두 번째 발자취",
                "story": "\"생각보다 돈을 밝히기도 하지요.\"",
                "req_items": {"신화의 발자취": 1},
                "req_money": 150000
            },
            {
                "type": "item",
                "title": "🐦 세 번째 발자취",
                "story": "\"그래도, 나쁜 새는 아니랍니다!\"",
                "req_items": {"신화의 발자취": 1, "맑은 생각": 3},
                "req_money": 0
            }
        ],
        "char_data": {
            "name": "샤일라",
            "hp": 200,
            "attack": 34,
            "defense": 27,
            "max_mental": 170,
            "card_slots": 5,
            "equipped_cards": ["쪼아대기", "밀키워킹"],
            "is_recruited": True
        }
    },
    # [신규] 로버드
    "Roverd": {
        "name": "로버드",
        "description": "두려운 연구자",
        "emoji": "❄️",
        "quests": [
            {
                "title": "❄️첫 번째 발자취",
                "story": "두려움을 느끼게하는 눈폭풍 너머",
                "type": "item",
                "req_items": {"신화의 발자취": 1,"눈꽃팬던트": 1, "천년얼음": 20},
                "req_money": 0
            },
            {
                "title": "❄️두 번째 발자취",
                "story": "눈이 덮힌 낡은 연구소를 발견합니다.",
                "type": "item",
                "req_items": {"신화의 발자취": 1,"작은 테라리움": 5},
                "req_money": 0
            },
            {
                "title": "❄️세 번째 발자취",
                "story": "추웠던 시간이 지나가고 따뜻한 시선이 보입니다.",
                "type": "item",
                "req_items": {"신화의 발자취": 1,"눈사람": 10, "따스한 목도리": 20},
                "req_money": 0
            }
        ],
        "char_data": {
            "name": "로버드",
            "hp": 170, "max_hp": 170, "current_hp": 170,
            "mental": 250, "max_mental": 250, "current_mental": 250,
            "attack": 30, "defense": 15,
            "card_slots": 5,
            "equipped_cards": ["얼어붙는시선", "날개쉬기"],
            "is_recruited": True
        }
    },

    # [신규] 셰리안
    "Sherian": {
        "name": "셰리안",
        "description": "희망, 하늘, 그리고 아스테로이드.",
        "emoji": "🌠",
        "quests": [
            {
                "title": "🌠첫 번째 발자취",
                "story": "아스테로이드 방정식",
                "type": "item",
                "req_items": {"신화의 발자취": 1,"깃털나무 잎사귀": 10},
                "req_money": 1000
            },
            {
                "title": "🌠두 번째 발자취",
                "story": "엡실론-델타 논법",
                "type": "item",
                "req_items": {"신화의 발자취": 1,"설국 열매": 10},
                "req_money": 1000
            },
            {
                "title": "🌠세 번째 발자취",
                "story": "페아노 공리계",
                "type": "item",
                "req_items": {"신화의 발자취": 1,"장식용 열쇠": 1},
                "req_money": 0
            }
        ],
        "char_data": {
            "name": "셰리안",
            "hp": 170, "max_hp": 170, "current_hp": 170,
            "mental": 100, "max_mental": 100, "current_mental": 100,
            "attack": 45, "defense": 20,
            "card_slots": 5,
            "equipped_cards": ["데이브레이크", "퀀티제이션"],
            "is_recruited": True
        }
    },
    # [신규] 루트렌 뉴마
    "Lutren": {
        "name": "루트렌 뉴마",
        "description": "전장의 흉성",
        "emoji": "☄️",
        "quests": [
            {
                "title": "☄️ 첫 번째 발자취",
                "story": "\"그 눈동자 속 비춰지는 얼굴은 언제나.\"",
                "type": "item",
                "req_items": {"신화의 발자취": 1, "하급 마력석": 20},
                "req_money": 0
            },
            {
                "title": "☄️ 두 번째 발자취",
                "story": "\"정의도, 선악도 없다면, 그 끝에 남는 것은.\"",
                "type": "item",
                "req_items": {"신화의 발자취": 1, "추억사진첩": 2, "장식용 열쇠": 1},
                "req_money": 0
            },
            {
                "title": "☄️ 세 번째 발자취",
                "story": "\"마침내, 오랜 숨이 트이다.\"",
                "type": "item",
                "req_items": {"신화의 발자취": 1, "시간의 모래": 5, "빛구슬": 20, "맑은 생각": 5},
                "req_money": 0
            }
        ],
        "char_data": {
            "name": "루트렌 뉴마",
            "hp": 132, "max_hp": 132, "current_hp": 132,
            "mental": 380, "max_mental": 380, "current_mental": 380,
            "attack": 40, "defense": 17,
            "card_slots": 5,
            "equipped_cards": ["변수제거", "관측과 분석"],
            "is_recruited": True
        }
    },
    # [신규] 미카엘
    "Michael": {
        "name": "미카엘",
        "description": "QUIS UT DEUS?",
        "emoji": "✝️",
        "quests": [
            {
                "title": "✝️ 첫 번째 발자취",
                "story": "\"보라, 주님의 모상을 닮은 이가 이 거룩한 곳에 이르렀나니,\"",
                "type": "item",
                "req_items": {"신화의 발자취": 1, "깃털나무 잎사귀": 9, "추억사진첩": 2, "장식용 열쇠": 9},
                "req_money": 0
            },
            {
                "title": "✝️ 두 번째 발자취",
                "story": "\"별빛이신 주님, 저희의 기도를 들어주소서.\"",
                "type": "item",
                "req_items": {"신화의 발자취": 1, "구름 한 줌": 2, "기억 종이": 3},
                "req_money": 0
            }
        ],
        "char_data": {
            "name": "미카엘",
            "hp": 150, "max_hp": 150, "current_hp": 150,
            "mental": 100, "max_mental": 100, "current_mental": 100,
            "attack": 40, "defense": 30,
            "card_slots": 5,
            "equipped_cards": ["이스카리옷 유다의 입맞춤", "성 미카엘, 용을 죽이다."],
            "is_recruited": True
        }
    }
}

class RecruitProcessView(discord.ui.View):
    """선택한 캐릭터의 영입 퀘스트를 진행하는 뷰"""
    def __init__(self, author, user_data, save_func, char_key, back_callback):
        super().__init__(timeout=180)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.char_key = char_key
        self.back_callback = back_callback 
        
        self.recruit_info = RECRUIT_REGISTRY[char_key]
        self.progress = self.user_data.setdefault("recruit_progress", {}).get(char_key, 0)

    

    @discord.ui.button(label="발자취 따라가기 (퀘스트 진행)", style=discord.ButtonStyle.success)
    async def proceed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        
        quests = self.recruit_info["quests"]
        if self.progress >= len(quests):
            return await interaction.response.send_message("이미 영입이 완료된 캐릭터야!", ephemeral=True)

        current_quest = quests[self.progress]
        inv = self.user_data.get("inventory", {})
        money = self.user_data.get("money", 0)

        # 1. 요구사항 체크
        req_money = current_quest.get("req_money", 0)
        if money < req_money:
            return await interaction.response.send_message(f"❌ 돈이 부족해! ({req_money}원 필요)", ephemeral=True)
        
        missing_items = []
        for item, count in current_quest.get("req_items", {}).items():
            if inv.get(item, 0) < count:
                missing_items.append(f"{item}({inv.get(item,0)}/{count})")
        
        if missing_items:
            return await interaction.response.send_message(f"❌ 재료가 부족해! ({', '.join(missing_items)})", ephemeral=True)

        # 2. 퀘스트 진행
        quest_type = current_quest.get("type", "item")

        if quest_type == "battle":
            # 비용 선차감
            self.user_data["money"] -= req_money
            for item, count in current_quest["req_items"].items():
                inv[item] -= count
            await self.save_func(self.author.id, self.user_data)

            # 전투 준비
            m_data = current_quest["monster_data"]
            monster = QuestMonster(m_data["name"], m_data["hp"], m_data["cards"], m_data.get("attack", 0), m_data.get("defense", 0))
            
            char_idx = self.user_data.get("investigator_index", 0)
            if not self.user_data.get("characters"):
                 return await interaction.response.send_message("전투 가능한 캐릭터가 없습니다.", ephemeral=True)
            
            if char_idx >= len(self.user_data["characters"]): char_idx = 0
            player = Character.from_dict(self.user_data["characters"][char_idx])

            async def on_victory(i, results=None):
                self.user_data = await get_user_data(self.author.id, self.author.display_name)
                self.progress += 1
                self.user_data["recruit_progress"][self.char_key] = self.progress
                await self.save_func(self.author.id, self.user_data)
                await self.show_quest_result(i)

            view = BattleView(
                self.author, player, [monster], 
                self.user_data, self.save_func, 
                char_index=char_idx,
                victory_callback=on_victory
            )
            
            await interaction.response.edit_message(content="⚔️ **영입 시험 시작!**", embed=None, view=view)

        else:
            self.user_data["money"] -= req_money
            for item, count in current_quest["req_items"].items():
                inv[item] -= count
            
            self.progress += 1
            self.user_data["recruit_progress"][self.char_key] = self.progress
            await self.save_func(self.author.id, self.user_data)
            
            await self.show_quest_result(interaction)

    async def show_quest_result(self, interaction):
        
        quests = self.recruit_info["quests"]
        completed_quest = quests[self.progress - 1]
        
        desc = completed_quest['story']
        if completed_quest.get("type") == "battle":
            desc += f"\n\n⚔️ **[{completed_quest['monster_data']['name']}]** 던전에 성공했습니다!"

        embed = discord.Embed(
            title=f"📜 {completed_quest['title']} 완료!", 
            description=desc, 
            color=discord.Color.gold()
        )
        
        # 영입 완료 처리
        if self.progress >= len(quests):
            c_data = self.recruit_info["char_data"]
            new_char = Character(
                name=c_data["name"],
                hp=c_data["hp"],
                max_hp=c_data["hp"],
                mental=c_data.get("max_mental", 90),
                max_mental=c_data.get("max_mental", 90),
                attack=c_data["attack"],
                defense=c_data["defense"],
                card_slots=c_data["card_slots"],
                is_recruited=True
            )
            new_char.equipped_cards = c_data["equipped_cards"]
            
            if "characters" not in self.user_data:
                self.user_data["characters"] = []
            self.user_data["characters"].append(new_char.to_dict())
            await self.save_func(self.author.id, self.user_data)
            
            # [신규] 메인 스토리 진행도 업데이트
            await update_quest_progress(interaction.user.id, self.user_data, self.save_func, "recruit", 1, self.char_key)
            
            embed.add_field(name="🎉 영입 성공!", value=f"**[{c_data['name']}]**이(가) 파티에 합류했어!", inline=False)
            
            if interaction.response.is_done():
                await interaction.channel.send(embed=embed, view=None)
            else:
                await interaction.response.edit_message(embed=embed, view=None)
        else:
            # 다음 퀘스트 안내
            next_q = quests[self.progress]
            req_str = ", ".join([f"{k} x{v}" for k, v in next_q.get("req_items", {}).items()])
            embed.add_field(name="다음 단계", value=f"**{next_q['title']}**\n{req_str}\n💰 {next_q.get('req_money', 0)}원", inline=False)
            embed.set_footer(text=f"진행도: {self.progress}/{len(quests)}")
            
            new_view = RecruitProcessView(self.author, self.user_data, self.save_func, self.char_key, self.back_callback)
            
            if interaction.response.is_done():
                await interaction.channel.send(embed=embed, view=new_view)
            else:
                await interaction.response.edit_message(embed=embed, view=new_view)

    @discord.ui.button(label="목록으로", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RecruitSelectView(self.author, self.user_data, self.save_func, self.back_callback)
        await interaction.response.edit_message(embed=None, content="영입 대상을 선택해줘.", view=view)

class RecruitSelectView(discord.ui.View):
    """영입 가능한 캐릭터 목록 뷰"""
    def __init__(self, author, user_data, save_func, back_callback):
        super().__init__(timeout=180)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.back_callback = back_callback
        self.page = 0
        self.PER_PAGE = 4
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        owned_names = [c["name"] for c in self.user_data.get("characters", [])]
        recruit_progress = self.user_data.get("recruit_progress", {})

        all_keys = list(RECRUIT_REGISTRY.keys())
        total_pages = (len(all_keys) - 1) // self.PER_PAGE + 1
        
        start = self.page * self.PER_PAGE
        for key in all_keys[start:start+self.PER_PAGE]:
            info = RECRUIT_REGISTRY[key]
            progress = recruit_progress.get(key, 0) 
            total_steps = len(info["quests"])
            is_owned = info["name"] in owned_names

            if is_owned:
                label = f"{info['name']} (영입 완료)"
                style = discord.ButtonStyle.secondary
                disabled = True
            else:
                label = f"{info['emoji']} {info['name']} ({progress}/{total_steps})"
                style = discord.ButtonStyle.primary
                disabled = False

            btn = discord.ui.Button(label=label, style=style, disabled=disabled)
            btn.callback = self.make_callback(key)
            self.add_item(btn)

        if total_pages > 1:
            prev_btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=3, disabled=(self.page == 0))
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
            
            next_btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=3, disabled=(self.page >= total_pages - 1))
            next_btn.callback = self.next_page
            self.add_item(next_btn)

        back_btn = discord.ui.Button(label="정비 메뉴로", style=discord.ButtonStyle.gray, row=3)
        back_btn.callback = self.go_back
        self.add_item(back_btn)

    async def prev_page(self, interaction: discord.Interaction):
        self.page -= 1
        self.update_buttons()
        await interaction.response.edit_message(view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.page += 1
        self.update_buttons()
        await interaction.response.edit_message(view=self)

    def make_callback(self, char_key):
        async def callback(interaction: discord.Interaction):
            if interaction.user != self.author: return
            self.user_data = await get_user_data(self.author.id, self.author.display_name)
            
            info = RECRUIT_REGISTRY[char_key]
            progress = self.user_data.get("recruit_progress", {}).get(char_key, 0)
            quests = info["quests"]
            
            if progress < len(quests):
                q = quests[progress]
                req_str = ", ".join([f"{k} x{v}" for k, v in q.get("req_items", {}).items()])
                
                desc = f"**{info['description']}**\n\n📜 **현재 퀘스트: {q['title']}**\n{q['story']}"
                
                if q.get("type") == "battle":
                    desc += f"\n\n⚠️ **[전투 퀘스트]** {q['monster_data']['name']} 처치 필요!"
                
                desc += f"\n\n**필요 재료:**\n{req_str}\n💰 {q.get('req_money', 0)}원"
            else:
                desc = "모든 퀘스트를 완료했습니다."

            embed = discord.Embed(title=f"🕵️ 영입 퀘스트: {info['name']}", description=desc, color=discord.Color.blue())
            view = RecruitProcessView(self.author, self.user_data, self.save_func, char_key, self.back_callback)
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        return callback

    async def go_back(self, interaction: discord.Interaction):
        if self.back_callback:
            await self.back_callback(interaction)
        else:
            await interaction.response.edit_message(content="메인 메뉴로 돌아갈 수 없어.", view=None)