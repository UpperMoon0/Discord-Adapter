"""
User Session Model
Tracks user sessions with Lily bot
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import discord


@dataclass
class UserSession:
    """Represents a user's active session with Lily"""
    user_id: str
    username: str
    channel: discord.TextChannel
    started_at: datetime = field(default_factory=datetime.now)
    active: bool = True
    
    def is_active(self) -> bool:
        """Check if session is active"""
        return self.active
    
    def end_session(self):
        """End the session"""
        self.active = False
    
    def start_session(self):
        """Start/renew the session"""
        self.active = True
        self.started_at = datetime.now()
