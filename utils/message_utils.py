"""
Message Utilities
Helper functions for message formatting and splitting
"""

import logging

logger = logging.getLogger("lily-discord-adapter")

MAX_MESSAGE_LENGTH = 2000  # Discord's message limit


def split_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list:
    """
    Split a long message into multiple chunks that fit within Discord's limit.
    
    Args:
        text: The text to split
        max_length: Maximum length of each chunk (default: 2000 for Discord)
    
    Returns:
        List of message chunks
    """
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    remaining = text
    
    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break
        
        # Try to split at a newline for cleaner breaks
        split_pos = remaining.rfind('\n', 0, max_length)
        if split_pos == -1:
            # No newline found, split at max_length
            split_pos = max_length
        
        chunk = remaining[:split_pos]
        chunks.append(chunk)
        remaining = remaining[split_pos:].lstrip('\n')
    
    return chunks


async def send_message(channel, text: str, prefix: str = "**Lily:**"):
    """
    Send a long message to a Discord channel, splitting if necessary.
    
    Args:
        channel: Discord channel to send to
        text: The message text
        prefix: Prefix to add to each chunk
    
    Returns:
        True if all chunks sent successfully, False otherwise
    """
    chunks = split_message(text)
    
    for i, chunk in enumerate(chunks):
        try:
            if prefix:
                # Add prefix to first chunk, continuation to others
                if i == 0:
                    message = f"{prefix} {chunk}"
                else:
                    message = f"...{chunk}"
            else:
                message = chunk
            
            await channel.send(message)
        except Exception as e:
            logger.error(f"Error sending message chunk {i}: {e}")
            return False
    
    return True
