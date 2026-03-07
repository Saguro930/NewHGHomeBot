import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  定数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BATTLE_TIMEOUT   = 120          # 2分間操作なしで不戦勝
ACCEPT_TIMEOUT   = 60           # 挑戦状の受付期限（秒）
MAX_TURNS        = 10           # 最大ターン数（超えたら引き分け）
HEAL_COOLDOWN    = 2            # 回復は N ターンに1回

COLOR_CHALLENGE  = 0xF39C12
COLOR_BATTLE     = 0x3498DB
COLOR_WIN        = 0x2ECC71
COLOR_LOSE       = 0xE74C3C
COLOR_DRAW       = 0x95A5A6
COLOR_TIMEOUT    = 0xE67E22


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ステータス計算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def calc_stats(data: dict) -> dict:
    """Firestore のユーザーデータからバトルステータスを算出"""
    xp_lv    = data.get("level",        1)
    work_lv  = data.get("work_level",   1)
    steal_lv = data.get("steal_level",  1)

    hp   = 100 + xp_lv * 15 + work_lv * 5
    atk  = 10  + xp_lv * 2  + steal_lv * 3
    crit = min(5 + steal_lv * 1.5, 50)   # クリティカル率（%）上限50

    return {"hp": hp, "max_hp": hp, "atk": atk, "crit": crit}


def apply_level_cap(attacker: dict, defender: dict):
    """レベル差補正: 攻撃側ATKを最大30%カット"""
    atk_total  = attacker["atk"]
    def_atk    = defender["atk"]
    if atk_total > def_atk * 1.5:
        attacker["atk"] = int(atk_total * 0.7)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  バトル本体 View
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class BattleView(discord.ui.View):
    def __init__(
        self,
        cog: "Battle",
        challenger: discord.Member,
        opponent:   discord.Member,
        bet:        int,
        ch_stats:   dict,
        op_stats:   dict,
    ):
        # timeout=None にして自前でタイマー管理する
        super().__init__(timeout=None)

        self.cog        = cog
        self.bet        = bet
        self.log        = []          # バトルログ（最新3行）
        self.turn       = 1
        self.finished   = False

        # 先攻をランダム決定
        if random.random() < 0.5:
            self.current, self.waiting = challenger, opponent
            self.cur_stats, self.wait_stats = ch_stats, op_stats
        else:
            self.current, self.waiting = opponent, challenger
            self.cur_stats, self.wait_stats = op_stats, ch_stats

        # 回復クールダウン管理
        self.heal_used: dict[int, int] = {
            challenger.id: 0,
            opponent.id:   0,
        }

        # タイムアウト管理
        self._last_action   = datetime.now(timezone.utc)
        self._last_actor_id = self.current.id   # 最後に行動した人
        self._timeout_task  = None

    # ── ターン制御ヘルパー ────────────────────────────────────────
    def _swap_turn(self):
        self.current,   self.waiting   = self.waiting,   self.current
        self.cur_stats, self.wait_stats = self.wait_stats, self.cur_stats
        self.turn += 1

    def _hp_bar(self, stats: dict) -> str:
        ratio  = max(stats["hp"] / stats["max_hp"], 0)
        filled = int(ratio * 10)
        return "█" * filled + "░" * (10 - filled)

    def _add_log(self, line: str):
        self.log.append(line)
        if len(self.log) > 3:
            self.log.pop(0)

    # ── Embed 生成 ────────────────────────────────────────────────
    def build_embed(
        self,
        *,
        color: int      = COLOR_BATTLE,
        title: str      = "⚔️ バトル中",
        footer: str     = "",
        result_text: str | None = None,
    ) -> discord.Embed:
        embed = discord.Embed(title=f"{title}　— ターン {self.turn}", color=color)

        # 先に表示するのはチャレンジャー側を固定したいので
        # current / waiting の順に表示
        embed.add_field(
            name=f"🔴 {self.current.display_name}",
            value=(
                f"`{self._hp_bar(self.cur_stats)}`\n"
                f"HP: **{self.cur_stats['hp']}** / {self.cur_stats['max_hp']}\n"
                f"ATK: {self.cur_stats['atk']}　CRIT: {self.cur_stats['crit']:.0f}%"
            ),
            inline=True,
        )
        embed.add_field(
            name=f"🔵 {self.waiting.display_name}",
            value=(
                f"`{self._hp_bar(self.wait_stats)}`\n"
                f"HP: **{self.wait_stats['hp']}** / {self.wait_stats['max_hp']}\n"
                f"ATK: {self.wait_stats['atk']}　CRIT: {self.wait_stats['crit']:.0f}%"
            ),
            inline=True,
        )

        if self.log:
            embed.add_field(name="📜 直近のログ", value="\n".join(self.log), inline=False)

        if result_text:
            embed.add_field(name="📢 結果", value=result_text, inline=False)

        if not self.finished:
            embed.set_footer(text=f"⏳ {self.current.display_name} の番　— 2分間操作なしで不戦勝")
        elif footer:
            embed.set_footer(text=footer)

        return embed

    # ── ダメージ計算 ──────────────────────────────────────────────
    def _calc_damage(self, attacker: dict, variant: str = "normal") -> tuple[int, bool]:
        base = attacker["atk"]
        if variant == "normal":
            dmg = int(base * random.uniform(0.8, 1.2))
        else:  # special
            dmg = int(base * random.uniform(1.6, 2.0))

        is_crit = random.random() * 100 < attacker["crit"]
        if is_crit:
            dmg = int(dmg * 1.5)
        return dmg, is_crit

    # ── ボタンの有効無効を切り替える ──────────────────────────────
    def _set_buttons(self, enabled: bool):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = not enabled

    # ── 行動前ガード（手番チェック・終了チェック）────────────────
    async def _guard(self, interaction: discord.Interaction) -> bool:
        if self.finished:
            await interaction.response.send_message("このバトルはすでに終了しています。", ephemeral=True)
            return False
        if interaction.user.id != self.current.id:
            await interaction.response.send_message(
                f"今は **{self.current.display_name}** の番です！", ephemeral=True
            )
            return False
        return True

    # ── 行動後の共通後処理 ────────────────────────────────────────
    async def _after_action(self, interaction: discord.Interaction, *, bust_check: bool = True):
        """ダメージ適用後に呼ぶ。HP0チェック・ターン交代・タイムアウトリセット"""
        self._last_action   = datetime.now(timezone.utc)
        self._last_actor_id = self.current.id

        # タイムアウトタスクをリセット
        if self._timeout_task:
            self._timeout_task.cancel()
        self._timeout_task = asyncio.create_task(self._timeout_coroutine(interaction.message))

        # HP0チェック（攻撃系の行動後のみ）
        if bust_check and self.wait_stats["hp"] <= 0:
            self.wait_stats["hp"] = 0
            await self._end_game(interaction, winner=self.current, loser=self.waiting)
            return

        # 最大ターン超過 → 引き分け
        if self.turn > MAX_TURNS:
            await self._end_game(interaction, winner=None, loser=None)
            return

        # 次のターンへ
        self._swap_turn()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    # ── ゲーム終了 ────────────────────────────────────────────────
    async def _end_game(
        self,
        interaction: discord.Interaction | None,
        *,
        winner: discord.Member | None,
        loser:  discord.Member | None,
        reason: str = "battle",
    ):
        if self.finished:
            return
        self.finished = True
        if self._timeout_task:
            self._timeout_task.cancel()
        self._set_buttons(False)

        if winner:
            payout = self.bet * 2
            await self.cog.add_coins(winner.id, payout)
            # 敗者のコインはすでに validate_bet で引かれているので追加処理不要

            if reason == "timeout":
                result_text = (
                    f"⏰ **2分間操作なし！**\n"
                    f"最後に行動した {winner.mention} の **不戦勝** です！\n"
                    f"🏆 **{payout:,} コイン** 獲得！"
                )
                color, title = COLOR_TIMEOUT, "⏰ タイムアウト — 不戦勝"
            else:
                result_text = (
                    f"🏆 **{winner.display_name}** の勝利！\n"
                    f"**{payout:,} コイン** 獲得！\n"
                    f"💔 {loser.display_name} は {self.bet:,} コインを失った。"
                )
                color, title = COLOR_WIN, "⚔️ バトル終了"

            # バトル経験値付与
            await self.cog.add_battle_exp(winner.id, 20)
            await self.cog.add_battle_exp(loser.id,  5)

        else:
            # 引き分け：両者にベット返却
            await self.cog.add_coins(self.current.id, self.bet)
            await self.cog.add_coins(self.waiting.id, self.bet)
            result_text = f"🤝 {MAX_TURNS}ターン経過！引き分け。ベットは両者に返却されました。"
            color, title = COLOR_DRAW, "⚔️ 引き分け"

        embed = self.build_embed(color=color, title=title, result_text=result_text)

        if interaction:
            await interaction.response.edit_message(embed=embed, view=self)
        elif self._last_message:
            await self._last_message.edit(embed=embed, view=self)

    # ── タイムアウトコルーチン ────────────────────────────────────
    async def _timeout_coroutine(self, message: discord.Message):
        """BATTLE_TIMEOUT 秒待って、最後に行動した人の不戦勝にする"""
        await asyncio.sleep(BATTLE_TIMEOUT)
        if self.finished:
            return

        # 最後に行動した人を winner に
        if self._last_actor_id == self.current.id:
            winner, loser = self.current, self.waiting
        else:
            winner, loser = self.waiting, self.current

        self._last_message = message
        await self._end_game(None, winner=winner, loser=loser, reason="timeout")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  行動ボタン
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @discord.ui.button(label="⚔️ 通常攻撃", style=discord.ButtonStyle.primary,   row=0)
    async def btn_attack(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        dmg, crit = self._calc_damage(self.cur_stats, "normal")
        self.wait_stats["hp"] -= dmg
        crit_str = "💥 クリティカル！" if crit else ""
        self._add_log(f"🔴 {self.current.display_name} → 通常攻撃 **{dmg}** ダメージ {crit_str}")
        await self._after_action(interaction)

    @discord.ui.button(label="✨ 必殺技",   style=discord.ButtonStyle.danger,     row=0)
    async def btn_special(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        # 発動率 40%、失敗したら ATK*0.5 の反動
        if random.random() < 0.4:
            dmg, crit = self._calc_damage(self.cur_stats, "special")
            self.wait_stats["hp"] -= dmg
            crit_str = "💥 クリティカル！" if crit else ""
            self._add_log(f"✨ {self.current.display_name} の必殺技！ **{dmg}** ダメージ {crit_str}")
        else:
            recoil = int(self.cur_stats["atk"] * 0.5)
            self.cur_stats["hp"] -= recoil
            self._add_log(f"💨 {self.current.display_name} の必殺技は外れた… 反動 **{recoil}** ダメージ")
        await self._after_action(interaction)

    @discord.ui.button(label="🛡️ 防御",    style=discord.ButtonStyle.secondary,  row=0)
    async def btn_guard(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        self.cur_stats["_guarding"] = True
        self._add_log(f"🛡️ {self.current.display_name} は防御態勢を取った！（次のダメージ 50%カット）")
        # ターン交代だけ（HP チェック不要）
        self._last_action   = datetime.now(timezone.utc)
        self._last_actor_id = self.current.id
        if self._timeout_task:
            self._timeout_task.cancel()
        self._timeout_task = asyncio.create_task(self._timeout_coroutine(interaction.message))

        if self.turn > MAX_TURNS:
            await self._end_game(interaction, winner=None, loser=None)
            return
        self._swap_turn()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="💊 回復",     style=discord.ButtonStyle.success,    row=1)
    async def btn_heal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        last_heal = self.heal_used.get(self.current.id, 0)
        if self.turn - last_heal < HEAL_COOLDOWN:
            await interaction.response.send_message(
                f"💊 回復はあと **{HEAL_COOLDOWN - (self.turn - last_heal)}** ターン後に使えます。",
                ephemeral=True,
            )
            return
        heal = int(self.cur_stats["max_hp"] * 0.15)
        self.cur_stats["hp"] = min(self.cur_stats["hp"] + heal, self.cur_stats["max_hp"])
        self.heal_used[self.current.id] = self.turn
        self._add_log(f"💊 {self.current.display_name} は **{heal}** HP 回復した！")
        # 回復は攻撃ではないので bust_check=False
        await self._after_action(interaction, bust_check=False)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  挑戦状 View（承諾/拒否ボタン）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class ChallengeView(discord.ui.View):
    def __init__(
        self,
        cog:        "Battle",
        challenger: discord.Member,
        opponent:   discord.Member,
        bet:        int,
    ):
        super().__init__(timeout=ACCEPT_TIMEOUT)
        self.cog        = cog
        self.challenger = challenger
        self.opponent   = opponent
        self.bet        = bet
        self.accepted   = False

    @discord.ui.button(label="✅ 受ける！", style=discord.ButtonStyle.success)
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 相手にしか押せない
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("あなたへの挑戦ではありません。", ephemeral=True)
            return

        self.accepted = True
        self.stop()

        # 相手のコインも引き落とし
        can_pay = await self.cog.remove_coins(self.opponent.id, self.bet)
        if not can_pay:
            embed = discord.Embed(
                title="❌ コイン不足",
                description=f"{self.opponent.display_name} のコインが不足しているためバトルを開始できません。",
                color=COLOR_LOSE,
            )
            for item in self.children:
                item.disabled = True
            # challenger にコインを返却
            await self.cog.add_coins(self.challenger.id, self.bet)
            await interaction.response.edit_message(embed=embed, view=self)
            return

        # 両者のステータス取得
        ch_data = await self.cog.get_user_data(self.challenger.id)
        op_data = await self.cog.get_user_data(self.opponent.id)
        ch_stats = calc_stats(ch_data)
        op_stats = calc_stats(op_data)
        apply_level_cap(ch_stats, op_stats)
        apply_level_cap(op_stats, ch_stats)

        view  = BattleView(self.cog, self.challenger, self.opponent, self.bet, ch_stats, op_stats)

        embed = view.build_embed(title="⚔️ バトル開始！")
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=view)

        # タイムアウトタスクをスタート
        view._timeout_task = asyncio.create_task(
            view._timeout_coroutine(await interaction.original_response())
        )

    @discord.ui.button(label="❌ 断る", style=discord.ButtonStyle.danger)
    async def decline_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("あなたへの挑戦ではありません。", ephemeral=True)
            return

        self.stop()
        # challenger にコインを返却
        await self.cog.add_coins(self.challenger.id, self.bet)

        embed = discord.Embed(
            title="❌ 挑戦を断られました",
            description=(
                f"{self.opponent.display_name} は決闘を断りました。\n"
                f"{self.challenger.mention} の **{self.bet:,} コイン** は返却されました。"
            ),
            color=COLOR_LOSE,
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        """60秒以内に応答がなければ自動キャンセル・返金"""
        if self.accepted:
            return
        await self.cog.add_coins(self.challenger.id, self.bet)
        # メッセージを編集する手段がないため、ログだけ残す
        # （message オブジェクトを保持して編集することも可能）


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Battle Cog
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class Battle(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db  = db

    # ── Firestore ヘルパー ────────────────────────────────────────
    def _user_ref(self, user_id: int):
        return self.db.collection("users").document(str(user_id))

    async def get_user_data(self, user_id: int) -> dict:
        doc  = await asyncio.to_thread(self._user_ref(user_id).get)
        data = doc.to_dict() if doc.exists else {}
        data.setdefault("coins",        0)
        data.setdefault("level",        1)
        data.setdefault("work_level",   1)
        data.setdefault("steal_level",  1)
        data.setdefault("battle_exp",   0)
        data.setdefault("battle_level", 1)
        data.setdefault("battle_wins",  0)
        data.setdefault("battle_loses", 0)
        return data

    async def add_coins(self, user_id: int, amount: int) -> int:
        ref   = self._user_ref(user_id)
        doc   = await asyncio.to_thread(ref.get)
        coins = (doc.to_dict().get("coins", 0) if doc.exists else 0) + amount
        await asyncio.to_thread(ref.set, {"coins": coins}, {"merge": True})
        return coins

    async def remove_coins(self, user_id: int, amount: int) -> bool:
        ref   = self._user_ref(user_id)
        doc   = await asyncio.to_thread(ref.get)
        coins = doc.to_dict().get("coins", 0) if doc.exists else 0
        if coins < amount:
            return False
        await asyncio.to_thread(ref.set, {"coins": coins - amount}, {"merge": True})
        return True

    async def add_battle_exp(self, user_id: int, exp: int):
        data = await self.get_user_data(user_id)
        data["battle_exp"] += exp
        # レベルアップ（100 * level ごと）
        while data["battle_exp"] >= data["battle_level"] * 100:
            data["battle_exp"]   -= data["battle_level"] * 100
            data["battle_level"] += 1
        await asyncio.to_thread(
            self._user_ref(user_id).set,
            {
                "battle_exp":   data["battle_exp"],
                "battle_level": data["battle_level"],
            },
            {"merge": True},
        )

    # ── /battle コマンド ──────────────────────────────────────────
    @app_commands.command(name="battle", description="他のユーザーにコインを賭けた決闘を申し込む")
    @app_commands.describe(
        user="挑戦するユーザー",
        amount="賭けるコイン数",
    )
    async def battle(
        self,
        interaction: discord.Interaction,
        user:   discord.Member,
        amount: int,
    ):
        challenger = interaction.user
        opponent   = user

        # バリデーション
        if opponent.id == challenger.id:
            await interaction.response.send_message("❌ 自分自身には挑戦できません。", ephemeral=True)
            return
        if opponent.bot:
            await interaction.response.send_message("❌ Botには挑戦できません。", ephemeral=True)
            return
        if amount <= 0:
            await interaction.response.send_message("❌ 1以上のコインを指定してください。", ephemeral=True)
            return

        # 挑戦者のコインを先に引き落とし
        can_pay = await self.remove_coins(challenger.id, amount)
        if not can_pay:
            await interaction.response.send_message("❌ コインが不足しています。", ephemeral=True)
            return

        # 挑戦状 Embed を送信（相手にメンション）
        embed = discord.Embed(
            title="⚔️ 決闘の申し込み！",
            description=(
                f"{opponent.mention}\n\n"
                f"**{challenger.display_name}** からの挑戦状です！\n"
                f"賭けコイン: **{amount:,} コイン**\n\n"
                f"⏳ **{ACCEPT_TIMEOUT}秒以内** に承諾しないと自動キャンセルになります。"
            ),
            color=COLOR_CHALLENGE,
        )
        embed.set_thumbnail(url=challenger.display_avatar.url)

        view = ChallengeView(
            cog=self,
            challenger=challenger,
            opponent=opponent,
            bet=amount,
        )

        await interaction.response.send_message(
            content=opponent.mention,   # メンションで通知
            embed=embed,
            view=view,
        )

        # タイムアウト後にメッセージを編集してキャンセル表示
        msg = await interaction.original_response()
        await asyncio.sleep(ACCEPT_TIMEOUT)
        if not view.accepted:
            embed_timeout = discord.Embed(
                title="⏰ 挑戦状の期限切れ",
                description=(
                    f"{opponent.display_name} が応答しなかったため、決闘はキャンセルされました。\n"
                    f"{challenger.mention} の **{amount:,} コイン** は返却されました。"
                ),
                color=COLOR_TIMEOUT,
            )
            for item in view.children:
                item.disabled = True
            try:
                await msg.edit(embed=embed_timeout, view=view)
            except discord.NotFound:
                pass


async def setup(bot, db):
    await bot.add_cog(Battle(bot, db))
