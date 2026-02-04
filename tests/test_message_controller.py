import pytest
from unittest.mock import MagicMock, AsyncMock
from controllers.message_controller import MessageController
from services.session_service import SessionService
from services.lily_core_service import LilyCoreService

@pytest.mark.asyncio
async def test_handle_chat_message():
    # Setup mocks
    bot = MagicMock()
    session_service = MagicMock(spec=SessionService)
    lily_core_service = MagicMock(spec=LilyCoreService)
    
    # Setup async methods
    lily_core_service.send_chat_message = AsyncMock()
    
    # Initialize controller
    controller = MessageController(bot, session_service, lily_core_service)
    
    # Mock user session
    session_service.is_session_active.return_value = True
    session_service.is_wake_phrase.return_value = False
    session_service.is_goodbye_phrase.return_value = False
    
    # Mock message
    message = MagicMock()
    message.author.id = "123"
    message.author.name = "TestUser"
    message.content = "Hello Lily"
    message.channel = MagicMock()
    message.attachments = []
    
    # Execute
    await controller.handle_user_message(message)
    
    # Verify
    lily_core_service.send_chat_message.assert_called_once_with(
        "123", "TestUser", "Hello Lily", []
    )

@pytest.mark.asyncio
async def test_wake_phrase():
    # Setup mocks
    bot = MagicMock()
    session_service = MagicMock(spec=SessionService)
    lily_core_service = MagicMock(spec=LilyCoreService)
    
    lily_core_service.send_chat_message = AsyncMock()
    
    controller = MessageController(bot, session_service, lily_core_service)
    
    # Mock session service
    session_service.is_wake_phrase.return_value = True
    session_service.extract_message_after_wake.return_value = "Hello"
    session_service.get_session_start_prompt.return_value = "Session Start"
    
    message = MagicMock()
    message.author.id = "123"
    message.author.name = "TestUser"
    message.content = "Hey Lily Hello"
    message.channel = MagicMock()
    
    await controller.handle_user_message(message)
    
    # Verify session created
    session_service.create_session.assert_called_once()
    
    # Verify message sent (prompt + content)
    expected_prompt = "Session Start\n\nUser's message: Hello"
    lily_core_service.send_chat_message.assert_called_once_with(
        "123", "TestUser", expected_prompt
    )

@pytest.mark.asyncio
async def test_goodbye_phrase():
    # Setup mocks
    bot = MagicMock()
    session_service = MagicMock(spec=SessionService)
    lily_core_service = MagicMock(spec=LilyCoreService)
    
    lily_core_service.send_chat_message = AsyncMock()
    
    controller = MessageController(bot, session_service, lily_core_service)
    
    # Mock session service
    session_service.is_wake_phrase.return_value = False
    session_service.is_goodbye_phrase.return_value = True
    session_service.is_session_active.return_value = True
    session_service.get_session_end_prompt.return_value = "Goodbye Prompt"
    
    message = MagicMock()
    message.author.id = "123"
    message.author.name = "TestUser"
    message.content = "Bye Lily"
    message.channel = MagicMock()
    
    await controller.handle_user_message(message)
    
    # Verify session ended
    session_service.end_session.assert_called_once_with("123")
    
    # Verify message sent
    lily_core_service.send_chat_message.assert_called_once_with(
        "123", "TestUser", "Goodbye Prompt"
    )
