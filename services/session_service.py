"""
Session Service
Manages user sessions with Lily bot
"""

import logging
from typing import Dict, Optional
from models.user_session import UserSession

logger = logging.getLogger("lily-discord-adapter")


class SessionService:
    """Service for managing user sessions"""
    
    # Wake word configuration
    WAKE_PHRASE = "hey lily"
    GOODBYE_PHRASE = "goodbye lily"
    
    def __init__(self):
        self._sessions: Dict[str, UserSession] = {}
    
    def get_session(self, user_id: str) -> Optional[UserSession]:
        """Get session for a user"""
        return self._sessions.get(user_id)
    
    def create_session(self, user_id: str, username: str, channel) -> UserSession:
        """Create a new session for a user"""
        session = UserSession(
            user_id=user_id,
            username=username,
            channel=channel
        )
        self._sessions[user_id] = session
        logger.info(f"Created session for user {username} ({user_id})")
        return session
    
    def end_session(self, user_id: str) -> bool:
        """End a user's session"""
        if user_id in self._sessions:
            self._sessions[user_id].end_session()
            logger.info(f"Ended session for user {user_id}")
            return True
        return False
    
    def is_session_active(self, user_id: str) -> bool:
        """Check if user has an active session"""
        session = self.get_session(user_id)
        return session is not None and session.is_active()
    
    def is_wake_phrase(self, content: str) -> bool:
        """Check if content starts with wake phrase"""
        return content.lower().startswith(self.WAKE_PHRASE)
    
    def is_goodbye_phrase(self, content: str) -> bool:
        """Check if content equals goodbye phrase"""
        return content.lower() == self.GOODBYE_PHRASE
    
    def extract_message_after_wake(self, content: str) -> str:
        """Extract message content after the wake phrase"""
        words = content.split(' ', 1)
        if len(words) > 1:
            return words[1].strip()
        return ""
