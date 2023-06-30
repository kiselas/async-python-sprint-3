import asyncio
import json
import uuid
from datetime import datetime

from constants import BLOCK_INTERVAL, LINE_BREAK, START_MESSAGES_COUNT, DestinationTypes, GENERAL_CHANNEL
from logger import logger
from services import (
    Connection,
    ConnectionPool,
    Message,
    MessagePool,
    ServerCommands,
)

QUEUE = asyncio.Queue()

MSG_POOL = MessagePool()
CONNECTION_POOL = ConnectionPool()


class ChatServerProtocol(asyncio.Protocol):
    # Определяем статический метод для создания строки со статистикой
    @staticmethod
    def make_statistic_str() -> str:
        usr_names_lst = CONNECTION_POOL.get_all_user_names()
        channels_names_lst = CONNECTION_POOL.get_all_channel_names()

        srv_stat = {"users": usr_names_lst, "channels": channels_names_lst}

        srv_stat_str = json.dumps(srv_stat, ensure_ascii=False)
        message = f"{ServerCommands.SET_STATISTIC.value} {srv_stat_str}"

        return message

    # Отправка статистики всем клиентам, кроме исключаемого
    def send_srv_stat(self, except_trs=None):
        message = self.make_statistic_str()
        for transport in CONNECTION_POOL.get_all_transports():
            if not except_trs or transport != except_trs:
                transport.write(message.encode())

    def connection_made(self, transport):
        # Отправка сообщения для выбора имени клиента
        transport.write(ServerCommands.CHOOSE_NAME.to_bytes())
        self.transport = transport
        conn = Connection(transport=transport, user_name=None)
        CONNECTION_POOL.add(conn)

    def data_received(self, data):  # noqa C901
        conn = CONNECTION_POOL.get_by_transport(self.transport)
        text = data.decode().strip()

        if not conn.user_name:
            # Если не установлено имя клиента
            if text in CONNECTION_POOL.get_all_user_names():
                self.transport.write(ServerCommands.NAME_REJECTED.to_bytes() + LINE_BREAK)
                return

            conn.user_name = text
            self.transport.write(ServerCommands.NAME_ACCEPTED.to_bytes() + b" " + data + LINE_BREAK)

            # При первом подключении отправляем все сообщения клиенту
            if MSG_POOL.count:
                msgs = MSG_POOL.get_messages()

                msg_to_client = msgs
                msgs_len = len(msgs)
                if msgs_len > START_MESSAGES_COUNT:
                    # Отправляем клиенту только последние `START_MESSAGES_COUNT` сообщений
                    msg_to_client = msgs[msgs_len - START_MESSAGES_COUNT:]
                    lost_messages = msgs[:msgs_len - START_MESSAGES_COUNT]
                    for msg in lost_messages:
                        msg.received_users.append(conn.user_name)

                for msg in msg_to_client:
                    QUEUE.put_nowait((msg, self.transport))
            return

        operator, *args = data.decode().strip().split(" ", 1)

        if operator == ServerCommands.GET_STATISTIC.value:
            # Запрос статистики
            message = self.make_statistic_str().encode()
            self.transport.write(message)
            return

        elif operator == ServerCommands.MESSAGE_APPROVE.value:
            # Подтверждение получения сообщения клиентом
            msg = json.loads(args[0])
            message = MSG_POOL.get_message_by_uuid(msg["uuid"])
            if message:
                message.received_users.append(msg["user"])
            return

        elif operator == ServerCommands.CHANGE_CHAT.value:
            # Смена активного чата
            chat_type, chat_name = args[0].strip().split(" ", 1)
            conn = CONNECTION_POOL.get_by_transport(self.transport)
            if conn:
                conn.current_connection_type = chat_type
                conn.current_connection_name = chat_name
                self.transport.write(data)

                if chat_type == DestinationTypes.CHANNEL:
                    msgs = MSG_POOL.get_messages(
                        destination_type=DestinationTypes.CHANNEL,
                        destination_name=chat_name,
                        not_received_user=conn.user_name,
                        not_from_creator=conn.user_name,
                    )
                elif chat_type == DestinationTypes.CHANNEL:
                    msgs = MSG_POOL.get_messages(
                        destination_type=DestinationTypes.PRIVATE,
                        destination_name=conn.user_name,
                        not_received_user=conn.user_name,
                        creator=chat_name,
                        not_from_creator=conn.user_name,
                    )
                else:
                    logger.warning("Invalid chat type")
                    return

                for msg in msgs:
                    QUEUE.put_nowait((msg, self.transport))

        elif operator == ServerCommands.BAN_USER.value:
            # Блокировка пользователя
            who_send_ban = conn.user_name
            banned_user = args[0]
            ban_conn = CONNECTION_POOL.get_by_user_name(banned_user)
            if ban_conn:
                if ban_conn.ban_user(who_send_ban):
                    ban_msg = f"You has been baned until `{ban_conn.BAN_LIFETIME.ctime()}` "
                    ban_msg += "and you can\'t send messages"
                    ban_conn.transport.write(ban_msg.encode())
            else:
                logger.error(f"Can\'t find connection for user {banned_user}")

        elif operator == ServerCommands.MESSAGE_FROM_CLIENT.value:
            # Отправка сообщения от клиента
            sending_to_general_channel = False
            if conn.current_connection_type == DestinationTypes.CHANNEL and \
                    conn.current_connection_name == GENERAL_CHANNEL:
                sending_to_general_channel = True

            can_send, error_text = conn.can_send_message(sending_to_general_channel)
            if not can_send:
                self.transport.write(error_text.encode())
                return

            if sending_to_general_channel:
                conn.increment_sent_messages_count()

            try:
                msg_text = args[0]
            except IndexError:
                logger.info("Can\'t read the message text")
                return

            msg = Message(uuid=str(uuid.uuid4()), dt=datetime.now(), creator=conn.user_name,
                          destination_type=conn.current_connection_type,
                          destination_name=conn.current_connection_name,
                          message=msg_text, received_users=[],
                          )

            MSG_POOL.add(msg)

            CONNECTION_POOL.send_message(msg)
            return

    def connection_lost(self, exc):
        # Обработка потери соединения
        CONNECTION_POOL.delete_by_transport(self.transport)


class Server:
    def __init__(self, host, port):
        self.host = host
        self.port = port

    @staticmethod
    async def send_messages_from_queue():

        while True:
            msg_item, transport = await QUEUE.get()
            await asyncio.sleep(0.001)
            message = f"{ServerCommands.MESSAGE_FROM_SRV.value} {msg_item.serialize()}\n".encode()
            transport.write(message)

    @staticmethod
    async def clear_interval_limits():
        """
        Очищаем счётчик сообщений общего канала
        """

        while True:
            await asyncio.sleep(BLOCK_INTERVAL * 60)
            CONNECTION_POOL.clear_messages()
            logger.info("Cleared the history of messages sent at the general channel")

    @staticmethod
    async def delete_delivered_messages():
        while True:
            del_msgs_count = MSG_POOL.delete_delivered_messages()
            if del_msgs_count:
                logger.info(f"Has been deleted delivered messages ({del_msgs_count})")
            await asyncio.sleep(0.001)

    def listen(self):

        loop = asyncio.get_event_loop()

        srv = loop.create_server(lambda: ChatServerProtocol(), self.host, self.port)

        loop.create_task(self.send_messages_from_queue())
        loop.create_task(self.clear_interval_limits())
        loop.create_task(self.delete_delivered_messages())
        loop.run_until_complete(srv)

        loop.run_forever()
        logger.info("Server successfully started")


if __name__ == "__main__":
    server_host = input("Enter server host. Leave it blank for the default value (127.0.0.1): ") or "127.0.0.1"
    server_port = input("Enter server port. Leave it blank for the default value (8000): ") or 8000
    server_port = int(server_port)

    server = Server(host=server_host, port=server_port)

    print(f"Start server at {server_host}:{server_port}")

    server.listen()
