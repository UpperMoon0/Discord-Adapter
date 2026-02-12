"""
Session Service
Manages user sessions with Lily bot - session lifecycle and state only.
Conversation history is stored in Lily-Core's MemoryService.
"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime
import uuid

logger = logging.getLogger("lily-discord-adapter")


@dataclass
class SessionConfig:
    """Configuration for session behavior"""
    max_sessions: int = 1000  # Maximum total sessions


class UserSession:
    """Represents a user's active session with Lily - state only, no history"""
    
    def __init__(self, 
                 user_id: str, 
                 username: str, 
                 channel,
                 config: SessionConfig = None):
        """
        Initialize a user session.
        """
        self.user_id = user_id
        self.username = username
        self.channel = channel
        self.config = config or SessionConfig()
        
        # Session lifecycle
        self.created_at = datetime.now()
        self.active = True
        
        # Session ID for tracking
        self.session_id = str(uuid.uuid4())[:8]
        
        logger.info(f"Session created: {self.session_id} for user {username} ({user_id})")
    
    def is_active(self) -> bool:
        """Check if session is active"""
        return self.active
    
    def end_session(self):
        """End the session"""
        self.active = False
        logger.info(f"Session ended: {self.session_id} for user {self.username}")
    
    def start_session(self):
        """Start/renew the session"""
        self.active = True


class SessionService:
    """Service for managing user sessions (State synced with Core)"""
    
    # Wake word configuration
    WAKE_PHRASE = "hey lily"
    GOODBYE_PHRASE = "goodbye lily"
    
    def __init__(self, config: SessionConfig = None):
        """
        Initialize session service.
        """
        self.config = config or SessionConfig()
        self._sessions: Dict[str, UserSession] = {}
        
        # Statistics
        self._total_sessions = 0
    
    def get_session(self, user_id: str) -> Optional[UserSession]:
        """Get session for a user"""
        return self._sessions.get(user_id)
    
    def create_session(self, user_id: str, username: str, channel) -> UserSession:
        """Create a new session for a user"""
        session = UserSession(
            user_id=user_id,
            username=username,
            channel=channel,
            config=self.config
        )
        self._sessions[user_id] = session
        self._total_sessions += 1
        return session
    
    def end_session(self, user_id: str) -> bool:
        """End a user's session (Called when Goodbye said or Core expires it)"""
        if user_id in self._sessions:
            self._sessions[user_id].end_session()
            del self._sessions[user_id] # Clean up
            logger.info(f"Ended and removed session for user {user_id}")
            return True
        return False
    
    def is_session_active(self, user_id: str) -> bool:
        """Check if user has an active session"""
        session = self.get_session(user_id)
        if session is None:
            return False
        return session.is_active()
    
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
