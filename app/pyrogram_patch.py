import pyrogram.utils
import logging

# Monkey Patch for Pyrogram < 1.4(?) to support 64-bit Channel IDs
# The original get_peer_type rejects IDs < -1002147483647
# We extend the range.

original_get_peer_type = pyrogram.utils.get_peer_type

def patched_get_peer_type(peer_id: int) -> str:
    try:
        return original_get_peer_type(peer_id)
    except ValueError:
        # Check if it looks like a valid 64-bit channel ID
        # Channel IDs start with -100
        # -1009999999999 is valid
        # Our failing ID: -1003632255961
        # It is negative.
        if peer_id < -1000000000000: 
            return "channel"
        raise

print("[PATCH] Applying Pyrogram get_peer_type monkey patch for 64-bit IDs.")
pyrogram.utils.get_peer_type = patched_get_peer_type
