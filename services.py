import json
from asyncio import BaseTransport
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, Tuple

from constants import (
    AVAILABLE_MESSAGES_COUNT,
    BAN_LIFETIME,
    COUNT_COMPLAINT_FOR_BAN,
    TIME_OF_LIFE_DELIVERED_MESSAGES,
    DestinationTypes, GENERAL_CHANNEL,
)


class ServerCommands(Enum):
    CHOOSE_NAME = "choose_name"
    NAME_ACCEPTED = "name_accepted"
    NAME_REJECTED = "name_rejected"

    GET_STATISTIC = "get_statistic"
    SET_STATISTIC = "set_statistic"

    MESSAGE_FROM_SRV = "message_from_srv"
    MESSAGE_FROM_CLIENT = "message_from_client"
    MESSAGE_APPROVE = "message_approve"

    CHANGE_CHAT = "change_chat"
    BAN_USER = "ban_user"

    def to_bytes(self) -> bytes:
        return self.value.encode()


@dataclass
class Message:
    uuid: str
    dt: datetime
    creator: str
    destination_type: int
    destination_name: str
    message: str
    received_users: List

    def serialize(self) -> str:
        msg = {
            "uuid": self.uuid,
            "creator": self.creator,
            "destination_type": self.destination_type,
            "destination_name": self.destination_name,
            "message": self.message,
        }

        return json.dumps(msg)

    def check_target(self, destination_type: int, destination_name: str, user_name: str) -> bool:
        if destination_type == DestinationTypes.CHANNEL:
            if self.destination_type == DestinationTypes.CHANNEL and self.destination_name == destination_name:
                return True
        elif destination_type == DestinationTypes.PRIVATE:
            if self.destination_type == DestinationTypes.PRIVATE and self.destination_name == user_name:
                return True

        return False


class MessagePool:
    __pool: List[Message] = []

    def add(self, msg: Message):
        self.__pool.append(msg)

    @property
    def count(self) -> int:
        return len(self.__pool)

    def serialize(self) -> bytes:
        return json.dumps([item.message for item in self.__pool], ensure_ascii=False).encode()

    def get_message_by_uuid(self, uuid: str) -> Optional[Message]:
        msgs = filter(lambda msg: msg.uuid == uuid, self.__pool)
        try:
            item = next(msgs)
        except StopIteration:
            item = None
        return item

    def get_messages(self,
                     destination_type: int = DestinationTypes.CHANNEL,
                     destination_name: str = GENERAL_CHANNEL,
                     not_received_user: Optional[str] = None,
                     creator: Optional[str] = None,
                     not_from_creator: Optional[str] = None,
                     ) -> List[Message]:

        """Отдает все сообщения по выбранным параметрам"""

        now = datetime.now()
        msgs = filter(lambda msg: msg.dt < now, self.__pool)

        if creator:
            msgs = filter(lambda msg: msg.creator == creator, msgs)

        if destination_type:
            msgs = filter(lambda msg: msg.destination_type == destination_type, msgs)

        if destination_name:
            msgs = filter(lambda msg: msg.destination_name == destination_name, msgs)

        if not_received_user:
            msgs = filter(lambda msg: not_received_user not in msg.received_users, msgs)

        if not_from_creator:
            msgs = filter(lambda msg: not_from_creator != msg.creator, msgs)

        return list(msgs)

    def delete_delivered_messages(self) -> int:
        now = datetime.now()
        msgs = filter(lambda msg:
                      msg.dt + timedelta(minutes=TIME_OF_LIFE_DELIVERED_MESSAGES) < now
                      and len(msg.received_users) > 0,
                      self.__pool)

        msgs_lst = list(msgs)
        msgs_cnt = len(msgs_lst)

        for msg in msgs_lst:
            self.__pool.remove(msg)
            del msg

        return msgs_cnt


@dataclass
class Connection:
    """Этот класс хранит в себе данные по каждому соединению"""
    current_connection_type = DestinationTypes.CHANNEL
    current_connection_name = GENERAL_CHANNEL
    transport: BaseTransport
    user_name: Optional[str]
    BAN_LIFETIME: Optional[datetime] = None
    banned_users: List[Optional[str]] = None
    messages_count = 0

    def increment_sent_messages_count(self):
        self.messages_count += 1

    def can_send_message(self, is_general_channel: bool) -> Tuple[bool, Optional[str]]:
        now = datetime.now()
        answer: Tuple[bool, Optional[str]] = (True, None)
        if self.BAN_LIFETIME and now < self.BAN_LIFETIME:
            answer = (False, f"You has been banned until {self.BAN_LIFETIME.ctime()}")
        elif is_general_channel and self.messages_count >= AVAILABLE_MESSAGES_COUNT:
            answer = (False, "Max messages limit reached")

        return answer

    def ban_user(self, user_name: str) -> bool:
        banned: bool = False
        if not self.banned_users:
            self.banned_users = list()
        self.banned_users.append(user_name)

        now = datetime.now()
        if len(self.banned_users) >= COUNT_COMPLAINT_FOR_BAN:
            self.banned_users = []
            self.BAN_LIFETIME = now + timedelta(minutes=BAN_LIFETIME)
            banned = True

        return banned


class ConnectionPool:
    __pool: List[Connection] = []

    def send_message(self, msg_item: Message) -> None:
        sender = self.get_by_user_name(msg_item.creator)
        message = f"{ServerCommands.MESSAGE_FROM_SRV.value} {msg_item.serialize()}\n".encode()

        for conn in self.__pool:
            if conn != sender and msg_item.check_target(
                    conn.current_connection_type,
                    conn.current_connection_name,
                    conn.user_name,
            ):
                conn.transport.write(message)

    def add(self, con: Connection) -> None:
        self.__pool.append(con)

    def get_all_user_names(self) -> List[str]:
        return [item.user_name for item in self.__pool]

    def get_by_user_name(self, user_name: str) -> Optional[Connection]:
        item_gen = filter(lambda x: x.user_name == user_name, self.__pool)
        try:
            item = next(item_gen)
        except StopIteration:
            item = None
        return item

    def get_all_channel_names(self) -> List:
        return list(
            {
                item.current_connection_name for item in self.__pool
                if item.current_connection_type == DestinationTypes.CHANNEL
            })

    def get_all_transports(self) -> List[BaseTransport]:
        return [item.transport for item in self.__pool]

    def get_all_transports_with_name(self) -> List[BaseTransport]:
        return [item.transport for item in self.__pool if item.user_name]

    def get_by_transport(self, transport: BaseTransport) -> Optional[Connection]:
        item_gen = filter(lambda x: x.transport == transport, self.__pool)
        try:
            item = next(item_gen)
        except StopIteration:
            item = None
        return item

    def delete_by_transport(self, transport: BaseTransport) -> None:
        item: Connection = self.get_by_transport(transport)
        self.__pool.remove(item)

    def clear_messages(self):
        for conn in self.__pool:
            conn.messages_count = 0

    @property
    def pool_len(self) -> int:
        return len(self.__pool)
