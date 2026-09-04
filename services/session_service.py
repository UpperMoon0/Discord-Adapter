"""Bounded Discord-to-Lily session state.

The caller supplies a security-scoped session key. MessageController uses
(guild, channel, user), preventing a conversation opened in one Discord context
from being silently reused in another.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger("lily-discord-adapter")


@dataclass(frozen=True)
class SessionConfig:
    max_sessions: int = 1000


class SessionLimitExceeded(RuntimeError):
    """Raised when creating another active session would exceed the hard cap."""


class UserSession:
    def __init__(
        self,
        user_id: str,
        username: str,
        channel,
        config: SessionConfig | None = None,
    ):
        self.user_id = user_id
        self.username = username
        self.channel = channel
        self.config = config or SessionConfig()
        self.created_at = datetime.now()
        self.active = True
        self.session_id = str(uuid.uuid4())[:8]
        logger.info("Session created: %s for scoped user %s", self.session_id, user_id)

    def is_active(self) -> bool:
        return self.active

    def end_session(self):
        self.active = False
        logger.info("Session ended: %s for scoped user %s", self.session_id, self.user_id)

    def start_session(self):
        self.active = True


class SessionService:
    """Manage bounded session lifecycle only; Lily-Core owns conversation memory."""

    WAKE_PHRASE = "hey lily"
    GOODBYE_PHRASE = "goodbye lily"

    def __init__(self, config: SessionConfig | None = None):
        self.config = config or SessionConfig()
        if self.config.max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        self._sessions: Dict[str, UserSession] = {}
        self._total_sessions = 0

    def get_session(self, user_id: str) -> Optional[UserSession]:
        return self._sessions.get(user_id)

    def create_session(self, user_id: str, username: str, channel) -> UserSession:
        previous = self._sessions.get(user_id)
        if previous is None and len(self._sessions) >= self.config.max_sessions:
            raise SessionLimitExceeded(
                f"maximum active Discord sessions reached ({self.config.max_sessions})"
            )
        if previous is not None:
            previous.end_session()

        session = UserSession(
            user_id=user_id,
            username=username,
            channel=channel,
            config=self.config,
        )
        self._sessions[user_id] = session
        self._total_sessions += 1
        return session

    def end_session(self, user_id: str) -> bool:
        session = self._sessions.pop(user_id, None)
        if session is None:
            return False
        session.end_session()
        return True

    def is_session_active(self, user_id: str) -> bool:
        session = self.get_session(user_id)
        return bool(session and session.is_active())

    def is_wake_phrase(self, content: str) -> bool:
        return content.lower().startswith(self.WAKE_PHRASE)

    def is_goodbye_phrase(self, content: str) -> bool:
        return content.lower() == self.GOODBYE_PHRASE

    def extract_message_after_wake(self, content: str) -> str:
        # Remove the complete two-word wake phrase, not just the first word.
        return content[len(self.WAKE_PHRASE):].strip()
