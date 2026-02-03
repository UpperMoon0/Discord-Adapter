"""
Session Service
Manages user sessions with Lily bot including conversation history and session lifecycle
"""

import asyncio
import logging
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import uuid

logger = logging.getLogger("lily-discord-adapter")


@dataclass
class ConversationMessage:
    """Represents a single message in the conversation history"""
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    message_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "message_id": self.message_id
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ConversationMessage':
        """Create from dictionary"""
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            message_id=data.get("message_id", str(uuid.uuid4())[:8])
        )


@dataclass
class SessionConfig:
    """Configuration for session behavior"""
    max_history_messages: int = 20  # Max messages in conversation history (sliding window)
    session_timeout_minutes: int = 30  # Inactive session timeout
    max_sessions: int = 1000  # Maximum total sessions
    cleanup_interval_seconds: int = 60  # How often to run cleanup


class UserSession:
    """Represents a user's active session with Lily"""
    
    def __init__(self, 
                 user_id: str, 
                 username: str, 
                 channel,
                 config: SessionConfig = None):
        """
        Initialize a user session.
        
        Args:
            user_id: Discord user ID
            username: Discord username
            channel: Discord channel for responses
            config: Session configuration
        """
        self.user_id = user_id
        self.username = username
        self.channel = channel
        self.config = config or SessionConfig()
        
        # Conversation history with sliding window
        self.history: deque = deque(maxlen=self.config.max_history_messages)
        
        # Session lifecycle
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        self.active = True
        
        # Session ID for tracking
        self.session_id = str(uuid.uuid4())[:8]
        
        logger.info(f"Session created: {self.session_id} for user {username} ({user_id})")
    
    def add_message(self, role: str, content: str):
        """Add a message to conversation history"""
        msg = ConversationMessage(role=role, content=content)
        self.history.append(msg)
        self.last_activity = datetime.now()
        logger.debug(f"Added message to session {self.session_id}: {role}: {content[:50]}...")
    
    def get_history(self, limit: int = None) -> List[dict]:
        """Get conversation history"""
        messages = list(self.history)
        if limit:
            messages = messages[-limit:]
        return [msg.to_dict() for msg in messages]
    
    def get_history_text(self, limit: int = None) -> str:
        """Get conversation history as formatted text"""
        messages = self.get_history(limit)
        if not messages:
            return ""
        
        formatted = []
        for msg in messages:
            role = "User" if msg["role"] == "user" else "Lily"
            formatted.append(f"{role}: {msg['content']}")
        return "\n".join(formatted)
    
    def is_active(self) -> bool:
        """Check if session is active"""
        return self.active
    
    def is_expired(self) -> bool:
        """Check if session has expired due to inactivity"""
        if not self.active:
            return True
        timeout = timedelta(minutes=self.config.session_timeout_minutes)
        return datetime.now() - self.last_activity > timeout
    
    def end_session(self):
        """End the session"""
        self.active = False
        logger.info(f"Session ended: {self.session_id} for user {self.username}")
    
    def start_session(self):
        """Start/renew the session"""
        self.active = True
        self.last_activity = datetime.now()
    
    @property
    def age(self) -> timedelta:
        """Get session age"""
        return datetime.now() - self.created_at
    
    @property
    def idle_time(self) -> timedelta:
        """Get idle time"""
        return datetime.now() - self.last_activity
    
    @property
    def message_count(self) -> int:
        """Get number of messages in history"""
        return len(self.history)


class SessionService:
    """Service for managing user sessions with history and timeout"""
    
    # Wake word configuration
    WAKE_PHRASE = "hey lily"
    GOODBYE_PHRASE = "goodbye lily"
    
    def __init__(self, config: SessionConfig = None):
        """
        Initialize session service.
        
        Args:
            config: Session configuration
        """
        self.config = config or SessionConfig()
        self._sessions: Dict[str, UserSession] = {}
        self._cleanup_task = None
        self._running = False
        
        # Statistics
        self._total_sessions = 0
        self._expired_sessions = 0
        
        # Session lifecycle prompts (Discord-specific)
        self._session_start_prompt = (
            "The user {username} just said 'Hey Lily' to wake you up. "
            "Respond with a friendly greeting. Keep it brief and conversational. "
            "No markdown formatting."
        )
        
        self._session_end_prompt = (
            "The user {username} said 'Goodbye Lily'. "
            "Respond with a friendly farewell. Keep it brief and conversational. "
            "No markdown formatting."
        )
        
        self._session_no_active_prompt = (
            "The user said 'Goodbye Lily' but there was no active conversation. "
            "Respond with a gentle message indicating we weren't chatting. "
            "Keep it brief and friendly. No markdown formatting."
        )
    
    async def start(self):
        """Start the session cleanup task"""
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Session service started")
    
    async def stop(self):
        """Stop the session cleanup task"""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("Session service stopped")
    
    async def _cleanup_loop(self):
        """Periodic cleanup of expired sessions"""
        while self._running:
            try:
                await asyncio.sleep(self.config.cleanup_interval_seconds)
                self._cleanup_expired_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
    
    def _cleanup_expired_sessions(self):
        """Remove expired sessions"""
        expired_users = []
        for user_id, session in self._sessions.items():
            if session.is_expired():
                expired_users.append(user_id)
                self._expired_sessions += 1
                logger.info(f"Session expired: {session.session_id} for user {session.username}")
        
        for user_id in expired_users:
            del self._sessions[user_id]
        
        if expired_users:
            logger.info(f"Cleaned up {len(expired_users)} expired sessions")
    
    def get_session(self, user_id: str) -> Optional[UserSession]:
        """Get session for a user"""
        return self._sessions.get(user_id)
    
    def create_session(self, user_id: str, username: str, channel) -> UserSession:
        """Create a new session for a user"""
        # Check if we've hit max sessions
        if len(self._sessions) >= self.config.max_sessions:
            # Remove oldest expired session
            oldest_user = None
            oldest_time = datetime.now()
            for user_id, session in self._sessions.items():
                if session.created_at < oldest_time:
                    oldest_time = session.created_at
                    oldest_user = user_id
            if oldest_user:
                del self._sessions[oldest_user]
                logger.warning(f"Removed oldest session due to max sessions limit")
        
        session = UserSession(
            user_id=user_id,
            username=username,
            channel=channel,
            config=self.config
        )
        self._sessions[user_id] = session
        self._total_sessions += 1
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
        if session is None:
            return False
        if session.is_expired():
            self.end_session(user_id)
            return False
        return session.is_active()
    
    def add_to_history(self, user_id: str, role: str, content: str) -> bool:
        """Add message to user's conversation history"""
        session = self.get_session(user_id)
        if session and session.is_active():
            session.add_message(role, content)
            return True
        return False
    
    def get_history(self, user_id: str, limit: int = None) -> List[dict]:
        """Get user's conversation history"""
        session = self.get_session(user_id)
        if session:
            return session.get_history(limit)
        return []
    
    def get_history_text(self, user_id: str, limit: int = None) -> str:
        """Get user's conversation history as formatted text"""
        session = self.get_session(user_id)
        if session:
            return session.get_history_text(limit)
        return ""
    
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
    
    def get_session_start_prompt(self, username: str) -> str:
        """
        Get the prompt for session start (wake-up).
        
        This is Discord-specific logic that should not be in Lily-Core.
        Lily-Core should only receive the actual message to process.
        
        Args:
            username: The Discord username
            
        Returns:
            The prompt to send to Lily-Core for session start
        """
        return self._session_start_prompt.format(username=username)
    
    def get_session_end_prompt(self, username: str) -> str:
        """
        Get the prompt for session end (goodbye).
        
        Args:
            username: The Discord username
            
        Returns:
            The prompt to send to Lily-Core for session end
        """
        return self._session_end_prompt.format(username=username)
    
    def get_session_no_active_prompt(self) -> str:
        """
        Get the prompt when user says goodbye but no active session.
        
        Returns:
            The prompt to send to Lily-Core for no active session
        """
        return self._session_no_active_prompt
    
    @property
    def stats(self) -> dict:
        """Get session service statistics"""
        active_count = sum(1 for s in self._sessions.values() if s.is_active())
        return {
            "total_sessions": self._total_sessions,
            "active_sessions": active_count,
            "expired_sessions": self._expired_sessions,
            "total_stored": len(self._sessions)
        }
