import asyncio
import os
import random
import sqlite3

from dblite import aioDbLite
from dotenv import load_dotenv
from pyrogram import Client, idle, filters
from pyrogram.enums import ChatMemberStatus, ChatType, MessageEntityType
from pyrogram.errors import MessageNotModified, ChatAdminRequired
from pyrogram.handlers import MessageHandler
from pyrogram.handlers.handler import Handler
from pyrogram.types import BotCommand, Message, ChatMember, Chat

from utils import *

load_dotenv()
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID')
BOT_PROXY = os.getenv('BOT_PROXY')
APP_NAME = 'lotteries'


async def _delete_temp_message(msg: Message, delay: int = 30):
    await asyncio.sleep(delay)
    await msg.delete()


def member_is_admin(member: ChatMember) -> bool:
    return member.status == ChatMemberStatus.OWNER or member.status == member.status.ADMINISTRATOR


def chat_isin_group(chat: Chat):
    return chat.type == ChatType.GROUP or chat.type == ChatType.SUPERGROUP


async def get_group_chat_id(client: Client, message: Message, limit: int = 100) -> int:
    chat = message.chat
    messages = await client.get_messages(chat.id, range(message.id, message.id - limit, -1))
    for entities in map(lambda x: x.entities,
                        filter(lambda item: item.entities and item.from_user and item.from_user.is_self, messages)):
        for entity in entities:
            if entity.type == MessageEntityType.TEXT_LINK:
                chat_id = get_query_string(entity.url, 'chat_id')
                if chat_id:
                    return int(chat_id)


manage_doc = """`/manage start` 开启抽奖
`/manage pause` 暂停抽奖
`/manage cancel` 取消抽奖
`/manage draw` 手动开奖"""
config_doc = f"""/create 创建一个抽奖(需要在群里发送)
/info   查看当前抽奖信息
{manage_doc}
`/set title 抽奖名称` 设置抽奖名称
`/set drawn_people 20` 设置开奖人数，为0时动手开奖
`/set winner_people 10` 设置中奖人数，数字或者百分比
`/set password 参与口令` 设置参与口令
`/set same_prize true` 设置奖品是否相同
`/set prize 奖品`     设置奖品，多个则`shift+回车`输入多行
/help   显示此帮助信息"""


class LotteryBot(object):
    aiodb: aioDbLite = None
    app: Client = None
    participant_handlers: dict[str, tuple[Handler, int]] = dict()

    async def init_server(self):
        self.aiodb = await get_db_connect(APP_NAME)
        await self.app.start()
        print('[+] Service started successfully')
        await self.app.set_bot_commands([
            BotCommand('create', '创建抽奖'),
            BotCommand('help', '帮助信息'),
            BotCommand('info', '抽奖信息'),
            BotCommand('prize', '获取中奖奖品'),
        ])
        await idle()
        await self.app.stop()
        await self.aiodb.close()

    def start_server(self):
        self.app = Client(
            APP_NAME,
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            in_memory=True,
            proxy=url2dict(BOT_PROXY)
        )
        self.app.add_handler(MessageHandler(self.send_helper_message, filters.command(['start', 'help'])))
        self.app.add_handler(MessageHandler(self.create_lottery_handler, filters.command(['create'])))
        self.app.add_handler(MessageHandler(self.set_lottery_handler, filters.command(['set'])))
        self.app.add_handler(MessageHandler(self.read_lottery_handler, filters.command(['info'])))
        self.app.add_handler(MessageHandler(self.manage_lottery_handler, filters.command(['manage'])))
        self.app.add_handler(MessageHandler(self.get_prize_handler, filters.command(['prize'])))
        self.app.run(self.init_server())

    async def send_helper_message(self, client: Client, message: Message):
        chat = message.chat
        if chat.type != ChatType.PRIVATE:
            return
        helper_text = f'''欢迎使用**抽奖小助手**
{int2number(1)} 先添加此机器人到群聊并设置为管理员
{int2number(2)} 你可以使用以下命令:
{config_doc}
'''
        await client.send_message(chat.id, text=helper_text)
        return self

    async def create_lottery_handler(self, client: Client, message: Message):
        chat = message.chat
        if not chat_isin_group(chat):
            await message.reply('请在群里发送此命令')
            return self
        chat_id = chat.id
        old_lottery = await load_lottery(self.aiodb, chat_id)
        if old_lottery:
            _temp_message = await client.send_message(chat_id, '**存在未结束的抽奖**',
                                                      reply_to_message_id=old_lottery['message_id'])
            asyncio.create_task(_delete_temp_message(_temp_message, 5))
            return self
        user_id = message.from_user.id
        _bot = await client.get_me()
        username = message.from_user.username
        if not username:
            await message.reply('请先设置用户名')
            return self
        member = await client.get_chat_member(chat_id=chat_id, user_id=user_id)
        if not member_is_admin(member):
            return self
        bot_member = await client.get_chat_member(chat_id=chat_id, user_id=_bot.id)
        if not member_is_admin(bot_member):
            await message.reply('请先将我设置成管理员')
            return self
        title = message.command[1] if len(message.command) > 1 else '请设置抽奖名称'
        text = f'创建抽奖成功，请查看[私聊](https://t.me/{_bot.username})信息设置抽奖内容'
        send_message = await client.send_message(chat_id, text)
        asyncio.create_task(_delete_temp_message(message, 5))
        await add_lottery(self.aiodb, chat_id, send_message.id, title)
        lottery = await load_lottery(self.aiodb, chat_id)
        if not lottery:
            await send_message.edit_text('创建抽奖失败，请检查服务')
            return self
        try:
            invite_link = await chat.export_invite_link()
        except ChatAdminRequired:
            invite_link = 'tg://empty'
        text = f"""**开始设置[{chat.title}]({invite_link}?chat_id={chat_id})的抽奖**
{int2number(1)} 你可以使用以下命令:
{config_doc}
{int2number(2)} 当前抽奖信息：
{lottery2message(lottery, True)}
"""
        await client.send_message(chat_id=username, text=text)
        return self

    async def _get_current_lottery(self, client: Client, message: Message):
        chat = message.chat
        if chat.type != ChatType.PRIVATE:
            return None, None
        chat_id = await get_group_chat_id(client, message)
        if chat_id is None:
            await message.reply('服务异常，请联系管理员')
            return None, None
        lottery = await load_lottery(self.aiodb, chat_id)
        if lottery is None:
            await message.reply('请先创建抽奖')
            return None, None
        return chat_id, lottery

    async def set_lottery_handler(self, client: Client, message: Message):
        chat_id, lottery = await self._get_current_lottery(client, message)
        if lottery is None:
            return self
        if lottery['status'] != 0:
            await message.reply('请先暂停抽奖')
            return self
        _, prop, *args = message.command
        if len(args) == 0:
            await message.reply(f'**参数错误**\n你可以使用以下命令:\n{config_doc}')
            return self

        def winner_people_converter(_str: str):
            _str = _str.strip()
            _default = '50%'
            if _str.isdigit():
                return _str
            if _str.endswith('%'):
                __s = _str.split('%')[0]
                if __s.isdigit():
                    return _str
            return _default

        converter = {
            'title': lambda l: ' '.join(l),
            'drawn_people': lambda l: int(l[0]),
            'winner_people': lambda l: winner_people_converter(l[0]),
            'password': lambda l: ' '.join(l),
            'same_prize': lambda l: l[0] == 'true',
            'prize': lambda l: '\n'.join(l),
        }
        fn = converter.get(prop)
        if fn is None:
            await message.reply(f'**参数错误**\n你可以使用以下命令:\n{config_doc}')
            return self
        await set_lottery(self.aiodb, lottery['id'], **{prop: fn(args)})
        lottery = await load_lottery(self.aiodb, chat_id)
        text = f"""**设置成功**
{int2number(1)} 你可以使用以下命令:
{config_doc}
{int2number(2)} 当前抽奖信息：
{lottery2message(lottery, True)}
"""
        await message.reply(text)
        return self

    async def read_lottery_handler(self, client: Client, message: Message):
        _, lottery = await self._get_current_lottery(client, message)
        if lottery is None:
            return self
        await message.reply(f'**当前抽奖信息**\n{lottery2message(lottery, True)}')
        return self

    async def manage_lottery_handler(self, client: Client, message: Message):
        chat_id, lottery = await self._get_current_lottery(client, message)
        if lottery is None:
            return self
        _, cmd = (message.command + ['empty'])[0: 2]
        manage_cmd = {
            'start': lambda *args: self.start_lottery(*args),
            'pause': lambda *args: self.pause_lottery(*args),
            'cancel': lambda *args: self.cancel_lottery(*args),
            'draw': lambda *args: self.draw_lottery(*args),
        }
        fn = manage_cmd.get(cmd)
        handler_key = f'{chat_id}_{message.from_user.id}'
        handler = self.participant_handlers.get(handler_key)
        if cmd == 'start' and handler is None:
            self.participant_handlers[handler_key] = self.app.add_handler(MessageHandler(
                self.add_participant_handler,
                filters.chat(lottery['chat_id']) & filters.regex(rf'\$\${lottery["password"]}')
            ))
        elif cmd in ['pause', 'cancel', 'draw'] and handler:
            self.app.remove_handler(*handler)
            del self.participant_handlers[handler_key]
        chat_message = await client.get_messages(chat_id, lottery['message_id'])
        if chat_message.empty:
            chat_message.chat and (await chat_message.delete())
            chat_message = await client.send_message(chat_id, "/empty")
            await set_lottery(self.aiodb, lottery['id'], message_id=chat_message.id)
        if fn is None:
            await message.reply(f'**无效的命令**\n你可以使用以下命令:\n{config_doc}')
            return self
        try:
            lottery = await fn(lottery, chat_message)
        except MessageNotModified:
            pass
        if lottery is None:
            return self
        await message.reply(f'**当前可使用的命令**\n{manage_doc}\n**当前抽奖信息**\n{lottery2message(lottery, True)}')
        return self

    async def start_lottery(self, lottery: LotteryType, message: Message):
        lottery_id = lottery['id']
        await set_lottery(self.aiodb, lottery_id, status=1)
        lottery = await load_lottery_by_id(self.aiodb, lottery_id)
        participants = await load_participants(self.aiodb, lottery_id)
        await message.edit_text(lottery_status2message(lottery, participants))
        pined = await message.pin()
        pined and (await pined.delete())
        return lottery

    async def draw_lottery(self, lottery: LotteryType, message: Message):
        if lottery['status'] == 2:
            if message.text == '/empty':
                await message.delete()
            return lottery
        lottery_id = lottery['id']
        await set_lottery(self.aiodb, lottery_id, status=2)
        lottery = await load_lottery_by_id(self.aiodb, lottery_id)
        participants = await load_participants(self.aiodb, lottery_id)
        winner_people = lottery['winner_people']
        if winner_people.isdigit():
            sample_count = int(winner_people)
        elif winner_people.endswith('%'):
            sample_count = len(participants) * int(winner_people.split('%')[0]) / 100
        else:
            sample_count = len(participants) / 2
        winners = random.sample(participants, k=int(sample_count))
        prize = [lottery['prize']] * len(winners) if lottery['same_prize'] else lottery['prize']
        _empty = '无奖品，请联系抽奖发布者'
        for winner in winners:
            await set_winner_prize(self.aiodb, winner['id'], prize.pop() if len(prize) else _empty)
        _bot = await self.app.get_me()
        await message.edit_text(lottery_winner2message(lottery, participants, winners, _bot))
        asyncio.create_task(_delete_temp_message(message, 600))
        return lottery

    async def pause_lottery(self, lottery: LotteryType, message: Message):
        same = lottery['status'] == 0
        lottery_id = lottery['id']
        await set_lottery(self.aiodb, lottery_id, status=0)
        lottery = await load_lottery_by_id(self.aiodb, lottery_id)
        participants = await load_participants(self.aiodb, lottery_id)
        await message.edit(lottery_status2message(lottery, participants))
        if same:
            return lottery
        _temp_message = await message.reply('**抽奖已暂停，消息将在30秒后删除**')
        asyncio.create_task(_delete_temp_message(_temp_message))
        return lottery

    async def cancel_lottery(self, lottery: LotteryType, message: Message):
        if lottery['status'] == 2:
            if message.text == '/empty':
                await message.delete()
            return
        lottery_id = lottery['id']
        lottery['status'] = 2
        await message.edit(lottery_status2message(lottery, []))
        await message.unpin()
        await remove_lottery_by_id(self.aiodb, lottery_id)
        _temp_message = await message.reply('**抽奖已取消，消息将在30秒后删除**')
        asyncio.create_task(_delete_temp_message(_temp_message))
        asyncio.create_task(_delete_temp_message(message))

    async def add_participant_handler(self, client: Client, message: Message):
        user = message.from_user
        chat = message.chat
        user_id = user.id
        username = user.username
        _temp_message = None
        if not username:
            username = ' '.join(filter(lambda x: x and x.strip(), [user.first_name, user.last_name]))
        if not username:
            username = 'U%x' % user_id
        try:
            if not username:
                _temp_message = await message.reply(f'需要设置用户名才能参与抽奖')
                return self
            lottery_id = await add_participant(self.aiodb, user_id=user_id, user_name=username, chat_id=chat.id)
            if lottery_id is None:
                _temp_message = await message.reply(f'服务异常，请联系管理员')
                return self
            _temp_message = await message.reply(f'@{username} 参与抽奖成功')
            lottery = await load_lottery_by_id(self.aiodb, lottery_id)
            participants = await load_participants(self.aiodb, lottery_id)
            chat_message = await client.get_messages(lottery['chat_id'], lottery['message_id'])
            text = lottery_status2message(lottery, participants)
            if chat_message.empty:
                chat_message.chat and (await chat_message.delete())
                chat_message = await client.send_message(lottery['chat_id'], text)
                await set_lottery(self.aiodb, lottery['id'], message_id=chat_message.id)
            else:
                await chat_message.edit(text)
            # 自动开奖
            if 0 < lottery['drawn_people'] <= len(participants):
                await self.draw_lottery(lottery, chat_message)
        except sqlite3.IntegrityError:
            pass
        finally:
            _temp_message and asyncio.create_task(_delete_temp_message(_temp_message, 5))
            asyncio.create_task(_delete_temp_message(message, 5))
        return self

    async def get_prize_handler(self, client: Client, message: Message):
        chat = message.chat
        if chat.type != ChatType.PRIVATE:
            return self
        user_id = message.from_user.id
        winner = await get_winner_by_user(self.aiodb, user_id)
        if winner is None:
            await message.reply('没有中奖信息')
        lottery = await load_lottery_by_id(self.aiodb, winner['lottery_id'])
        if lottery is None:
            await message.reply('没有抽奖信息')
        await message.reply(prize2message(lottery['title'], winner['prize']))
        return self


if __name__ == '__main__':
    bot = LotteryBot()
    try:
        print('[*] Starting service...')
        bot.start_server()
    except KeyboardInterrupt:
        loop = asyncio.get_event_loop()
        loop.call_later(0, lambda _: print('[+] Service stopped'), None)
        loop.run_until_complete(bot.aiodb.close())
