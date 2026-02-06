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
    # Mock send as async
    message.channel.send = AsyncMock()
    message.attachments = []
    
    # Execute
    await controller.handle_user_message(message)
    
    # Verify
    # Set default return value for the async mock
    lily_core_service.send_chat_message.return_value = "Response"
    
    # Re-setup mocks to ensure return value is set before call
    lily_core_service.send_chat_message = AsyncMock(return_value="Response")
    controller.lily_core_service = lily_core_service
    
    # Execute again with proper mock setup
    await controller.handle_user_message(message)

    lily_core_service.send_chat_message.assert_called_with(
        "123", "TestUser", "Hello Lily", []
    )
    # The controller awaits the channel.send coroutine when a response is returned
    # Since mocked methods return None or awaitable, check if channel.send was called
    message.channel.send.assert_called()


@pytest.mark.asyncio
async def test_wake_phrase():
    # Setup mocks
    bot = MagicMock()
    session_service = MagicMock(spec=SessionService)
    lily_core_service = MagicMock(spec=LilyCoreService)
    
    # Make send_chat_message return a non-empty string so channel.send is called
    lily_core_service.send_chat_message.return_value = "Hello there!"
    lily_core_service.send_chat_message = AsyncMock(return_value="Hello there!")
    
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
    
    # Important: Configure the AsyncMock for channel.send
    message.channel.send = AsyncMock()
    
    await controller.handle_user_message(message)
    
    # Verify session created
    session_service.create_session.assert_called_once()
    
    # Verify message sent (prompt + content)
    expected_prompt = "Session Start\n\nUser's message: Hello"
    lily_core_service.send_chat_message.assert_called_once_with(
        "123", "TestUser", expected_prompt
    )
    
    # Verify channel.send was called with the response
    message.channel.send.assert_called_once_with("Hello there!")


@pytest.mark.asyncio
async def test_goodbye_phrase():
    # Setup mocks
    bot = MagicMock()
    session_service = MagicMock(spec=SessionService)
    lily_core_service = MagicMock(spec=LilyCoreService)
    
    lily_core_service.send_chat_message = AsyncMock(return_value="Goodbye!")
    
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
    
    # Important: Configure the AsyncMock for channel.send
    message.channel.send = AsyncMock()
    
    await controller.handle_user_message(message)
    
    # Verify session ended
    session_service.end_session.assert_called_once_with("123")
    
    # Verify message sent
    lily_core_service.send_chat_message.assert_called_once_with(
        "123", "TestUser", "Goodbye Prompt"
    )
    
    # Verify channel.send was called
    message.channel.send.assert_called_once_with("Goodbye!")
