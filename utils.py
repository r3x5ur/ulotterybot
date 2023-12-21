from typing import TypedDict, Union, Optional
from urllib.parse import urlparse, parse_qs
from dblite import aioDbLite

__all__ = [
    'LotteryType',
    'make_lottery',
    'ParticipantType',
    'make_participant',
    'get_db_connect',
    'remove_lottery_by_id',
    'load_lottery',
    'load_lottery_by_id',
    'set_lottery',
    'add_lottery',
    'add_participant',
    'load_participants',
    'int2number',
    'lottery_status2message',
    'lottery_winner2message',
    'lottery2message',
    'get_query_string',
    'prize2message',
    'url2dict'
]


class LotteryType(TypedDict):
    id: int
    chat_id: int
    message_id: int
    # 抽奖标题
    title: str
    # 抽奖状态 0 已暂停 1 抽奖中 2 已结束
    status: int
    # 开奖人数 大于 0 将启用自动开奖
    drawn_people: int
    # 参与口令
    password: str
    # 奖品是否相同，为 true 时 prize 将发送给每个人，为 false 则以\n分割并发送每个人
    same_prize: bool
    # 奖品内容 多个以\n分割
    prize: str


LotteryType.TABLE_NAME = 'lotteries'


def make_lottery(raw: Union[list, tuple]) -> LotteryType:
    _id, chat_id, message_id, title, status, drawn_people, password, same_prize, prize = raw
    return LotteryType(
        id=_id,
        chat_id=chat_id,
        message_id=message_id,
        title=title,
        status=status,
        drawn_people=drawn_people,
        password=password,
        same_prize=bool(same_prize),
        prize=prize if same_prize else str(prize).split('\n')
    )


class ParticipantType(TypedDict):
    id: int
    user_id: int
    user_name: str
    # 关联抽奖
    lottery_id: int


ParticipantType.TABLE_NAME = 'participants'


def make_participant(raw: Union[list, tuple]) -> ParticipantType:
    _id, user_id, user_name, lottery_id, = raw
    return ParticipantType(
        id=_id,
        user_id=user_id,
        user_name=user_name,
        lottery_id=lottery_id,
    )


_title = "❤️‍🔥❤️‍🔥❤️‍🔥❤️‍🔥**{}**❤️‍🔥❤️‍🔥❤️‍🔥❤️‍🔥"
_footer = "❤️‍🔥❤️‍🔥❤️‍🔥❤️‍🔥❤️‍🔥❤️‍🔥❤️‍🔥❤️‍🔥❤️‍🔥❤️‍🔥"
numbers = ['0️⃣', '1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
lottery_status = ['已暂停', '抽奖中', '已结束']


async def get_db_connect(app_name: str):
    aiodb = await aioDbLite(f'db/{app_name}.db')
    await aiodb.create(
        LotteryType.TABLE_NAME,
        id='INTEGER PRIMARY KEY AUTOINCREMENT',
        chat_id='int',
        message_id='int',
        title='TEXT NOT NULL',
        status='int(1)',  # 抽奖状态 0 已暂停 1 抽奖中 2 已结束
        drawn_people='int',  # 开奖人数 为 null 或者 0 时 不自动开奖
        password='varchar(1024)',  # 参与抽奖口令
        same_prize='int(1)',  # 1 相同的奖品  0 每个人都不一样
        prize='TEXT',  # 奖品
    )
    await aiodb.create(
        ParticipantType.TABLE_NAME,
        id='INTEGER PRIMARY KEY AUTOINCREMENT',
        user_id='int',
        user_name='varchar(1024)',
        lottery_id='int',  # 本轮抽奖ID
    )
    sql = f'CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_users_lottery ON {ParticipantType.TABLE_NAME} ' \
          f'(user_id, user_name, lottery_id);'
    await aiodb.cursor.execute(sql)
    await aiodb.conn.commit()
    return aiodb


async def load_lottery_by_id(aiodb: aioDbLite, lottery_id: int) -> LotteryType:
    sql = 'SELECT * FROM `lotteries` WHERE id = ?'
    cursor = await aiodb.cursor.execute(sql, (lottery_id,))
    lotteries_raw = await cursor.fetchone()
    return make_lottery(lotteries_raw) if lotteries_raw else None


async def load_lottery(aiodb: aioDbLite, chat_id: int, status: list = None) -> LotteryType:
    status = status or [0, 1]
    status = (status * 2)[0: 2]
    sql = 'SELECT * FROM `lotteries` WHERE chat_id = ? AND (status = ? OR status = ?) ORDER BY id DESC'
    cursor = await aiodb.cursor.execute(sql, (chat_id, *status))
    lotteries_raw = await cursor.fetchone()
    return make_lottery(lotteries_raw) if lotteries_raw else None


async def remove_lottery_by_id(aiodb: aioDbLite, lottery_id: int):
    await aiodb.remove(LotteryType.TABLE_NAME, id=lottery_id)


async def set_lottery(aiodb: aioDbLite, lottery_id: int, **kwargs):
    title = kwargs.get('title')
    status = kwargs.get('status')
    drawn_people = kwargs.get('drawn_people')
    password = kwargs.get('password')
    same_prize = kwargs.get('same_prize')
    prize = kwargs.get('prize')
    message_id = kwargs.get('message_id')
    updater: Optional[LotteryType] = dict()
    if status is not None:
        updater['status'] = status
    if title is not None:
        updater['title'] = title
    if drawn_people is not None:
        updater['drawn_people'] = drawn_people
    if password is not None:
        updater['password'] = password
    if same_prize is not None:
        updater['same_prize'] = same_prize
    if prize is not None:
        updater['prize'] = prize
    if message_id is not None:
        updater['message_id'] = message_id
    if len(updater.values()) == 0:
        return
    # where
    updater['id'] = lottery_id
    await aiodb.update(LotteryType.TABLE_NAME, **updater)


async def add_lottery(aiodb: aioDbLite, chat_id, message_id, title, status=0, drawn_people=0, password='默认口令',
                      same_prize=1,
                      prize=''):
    await aiodb.add(
        LotteryType.TABLE_NAME,
        chat_id=chat_id,
        message_id=message_id,
        title=title,
        status=status,
        drawn_people=drawn_people,
        password=password,
        same_prize=same_prize,
        prize=prize,
    )


async def add_participant(aiodb: aioDbLite, user_id, user_name, **kwargs):
    lottery_id = kwargs.get('lottery_id')
    if lottery_id is None:
        chat_id = kwargs.get('chat_id')
        if chat_id is None:
            return None
        lottery = await load_lottery(aiodb, chat_id, [1])
        if lottery is None:
            return None
        lottery_id = lottery['id']
    await aiodb.add(
        ParticipantType.TABLE_NAME,
        user_id=user_id,
        user_name=user_name,
        lottery_id=lottery_id,
    )
    return lottery_id


async def load_participants(aiodb: aioDbLite, lottery_id: int):
    participant_raw = await aiodb.select(ParticipantType.TABLE_NAME, '*', lottery_id=lottery_id)
    return list(map(make_participant, participant_raw))


def int2number(n: int) -> str:
    return ''.join(map(lambda i: numbers[int(i)], list(str(n))))


def lottery2message(lottery: LotteryType, show_prize=False):
    text = f"""抽奖名称：`{lottery['title']}`
参与口令：`$${lottery['password']}`
开奖人数：`{'手动开奖' if lottery['drawn_people'] == 0 else int2number(lottery['drawn_people'])}`
抽奖状态：`{lottery_status[lottery['status']]}`"""
    if show_prize:
        prize = lottery["prize"]
        prize_text = ('\n' + '\n'.join(prize)) if isinstance(prize, list) else prize
        text += f'\n奖品类型：`{"相同" if lottery["same_prize"] else "各不相同"}`'
        text += f'\n抽奖奖品：```{prize_text}```'
    return text


def prize2message(prize: str) -> str:
    return f"""{_title.format('中奖啦')}
您的奖品：
`{prize}`
{_footer}"""


def lottery_status2message(lottery: LotteryType, participants: list[ParticipantType]):
    participants_text = (' ' * 2).join(map(lambda x: x['user_name'], participants)) or '暂无参与人员'
    return f"""{_title.format('抽奖啦')}
{lottery2message(lottery)}
参与人数：`{int2number(len(participants))}`
参与人员：`{participants_text}`
{_footer}"""


def lottery_winner2message(lottery: LotteryType, participants: list[ParticipantType], winners: list[ParticipantType]):
    winners_mapped = map(lambda x: f'<u>**[{x["user_name"]}](tg://user?id={x["user_id"]})**</u>', winners)
    winner_text = (' ' * 4).join(winners_mapped)
    return f"""{_title.format('开奖啦')}
{lottery2message(lottery)}
参与人数：`{int2number(len(participants))}`
中奖人数：`{int2number(len(winners))}`
中奖名单：
{winner_text}
{_footer}"""


def get_query_string(url: str, param: str) -> str:
    parser = urlparse(url)
    raw = parse_qs(parser.query).get(param)
    return raw[0] if raw and len(raw) else None


def url2dict(url: str) -> Optional[dict[str, str]]:
    if not url or not url.strip():
        return None
    parser = urlparse(url)
    return dict(scheme=parser.scheme, hostname=parser.hostname, port=parser.port)
