from asyncio import BaseTransport
from datetime import datetime

import pytest

from constants import DestinationTypes, GENERAL_CHANNEL
from services import AVAILABLE_MESSAGES_COUNT, Connection, Message


@pytest.fixture
def message_to_general_channel() -> Message:
    msg = Message(
        uuid="123",
        dt=datetime(year=2023, month=1, day=1, hour=0, minute=0, second=1),
        creator="Fletcher",
        destination_type=DestinationTypes.CHANNEL,
        destination_name=GENERAL_CHANNEL,
        message="text1",
        received_users=[],
    )
    return msg


@pytest.fixture
def message_to_private_michael() -> Message:
    msg = Message(
        uuid="998877665544332211",
        dt=datetime(year=2023, month=6, day=29, hour=0, minute=0, second=41),
        creator="Michael Pearson",
        destination_type=DestinationTypes.PRIVATE,
        destination_name="Fletcher",
        message="Random text",
        received_users=[],
    )
    return msg


@pytest.fixture
def message_to_private_fletcher() -> Message:
    msg = Message(
        uuid="112233445566778899",
        dt=datetime(year=2023, month=6, day=29, hour=0, minute=0, second=43),
        creator="Fletcher",
        destination_type=DestinationTypes.PRIVATE,
        destination_name="Michael Pearson",
        message="Not random text",
        received_users=[],
    )
    return msg


@pytest.fixture
def connection_fixture() -> Connection:
    conn = Connection(
        transport=BaseTransport(),
        user_name="Michael Pearson",
    )
    return conn


def test_text_to_general_true(message_to_general_channel):
    res = message_to_general_channel.check_target(
        destination_type=DestinationTypes.CHANNEL,
        destination_name=GENERAL_CHANNEL,
        user_name="Michael Pearson",
    )
    assert res is True


def test_text_to_general_false(message_to_general_channel):
    res = message_to_general_channel.check_target(
        destination_type=DestinationTypes.CHANNEL,
        destination_name="not_general",
        user_name="Michael Pearson",
    )
    assert res is False


def test_text_to_private_true(message_to_private_fletcher):
    res = message_to_private_fletcher.check_target(
        destination_type=DestinationTypes.PRIVATE,
        destination_name="Michael Pearson",
        user_name="Michael Pearson",
    )
    assert res is True


def test_text_to_private_false(message_to_private_michael):
    res = message_to_private_michael.check_target(
        destination_type=DestinationTypes.PRIVATE,
        destination_name="Michael Pearson",
        user_name="Michael Pearson",
    )
    assert res is False


def test_make_conn_banned(connection_fixture):
    connection_fixture.ban_user("Michael Pearson")
    connection_fixture.ban_user("Random name")
    banned = connection_fixture.ban_user("Phuc")
    assert banned is True


def test_make_conn_not_banned(connection_fixture):
    connection_fixture.ban_user("Random name")
    banned = connection_fixture.ban_user("Who")
    assert banned is False


def test_conn_can_send_message(connection_fixture):
    can_send, _ = connection_fixture.can_send_message(is_general_channel=True)
    assert can_send is True


def test_conn_can_not_send_message(connection_fixture):
    connection_fixture.messages_count = AVAILABLE_MESSAGES_COUNT
    can_send, _ = connection_fixture.can_send_message(is_general_channel=True)
    assert can_send is False
