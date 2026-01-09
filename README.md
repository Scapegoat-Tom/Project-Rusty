List of dependencies for your Python environment:

```txt
discord.py>=2.3.0
pytz>=2023.3
```

## **Python Version Requirement**
- Python 3.8 or higher

Here's a complete list of features:

## **Admin Commands**
- `/setup` - Initial bot configuration with autocomplete for categories and channels
- `/repair` - Repairs missing channels/categories from config
- `/reset` - Removes server configuration to start fresh

## **Event Creation Commands**
- `/destiny2-raid` - Create Destiny 2 raid events (6 players, autocomplete raid list)
- `/destiny2-dungeon` - Create Destiny 2 dungeon events (3 players, autocomplete dungeon list)
- `/other-game` - Create custom game events (autocomplete from templates)
- `/create-other` - Create custom game templates with name, mode, and player limit

## **Event Features**
- **Joinable Event Messages** with interactive buttons:
  - Join (main participant)
  - Join as Alternate
  - Leave
  - Edit Event (creator/admin only)
  - Cancel Event (creator/admin only)
- **Automatic Channel Creation**:
  - Text channel created on event creation
  - Voice channel created 15 minutes before event
  - Proper naming: `raid-name-12345` for Destiny 2, `game-name-12345` for others
- **Discord Scheduled Events** - Auto-created with proper naming conventions
- **Player Management**:
  - Automatic promotion from alternate to participant when someone leaves
  - Unlimited player support (0 = unlimited)
  - Real-time participant list updates

## **Notification System**
- **DM Reminders** (participants only, not alternates):
  - 15-minute reminder with orange embed
  - 5-minute reminder with orange embed
  - Shows event name, relative timestamp, voice channel status
- **Cancellation Notifications**:
  - Required cancellation reason (visible to all)
  - Orange embed with event details, scheduled time, and reason
  - Only sent on manual cancellation (not automatic cleanup)
- **Promotion Notifications** - DM when promoted from alternate to participant

## **Time & Timezone Features**
- **Multi-timezone Support**: GMT, AST, EST, CST, PST
- **Automatic Time Conversion** - Users see times in their local timezone via Discord timestamps
- **Flexible Time Input** - Supports 12-hour (AM/PM) and 24-hour formats

## **Automatic Cleanup**
- **1-hour post-event cleanup** when voice channel is empty:
  - Deletes text channel
  - Deletes voice channel
  - Deletes event message
  - Deletes Discord scheduled event
  - Removes event from database
- **Silent external deletion handling** - No participant spam when events/messages deleted manually

## **Event Logging** (Admin-only channel)
- Event creation logs (who, when, event ID)
- Event edit logs
- Event cancellation logs (with reason)
- External deletion logs (message/Discord event deleted)

## **Channel Management**
- **Auto-delete** non-command messages in event channel
- **Admin-only** event-log channel
- **Category-based** organization
- **Duplicate prevention** for custom game templates (case-insensitive)

## **Persistence & Reliability**
- **JSON-based storage** (per-server configs and events)
- **View persistence** - Buttons work after bot restart
- **Server-specific** configs and custom games
- **Event data includes**: ID, title, description, game, mode, datetime, timezone, player limit, creator, participants, alternates, channel IDs

## **Naming Conventions**
- **Destiny 2 channels**: `vault-of-glass-12345`
- **Other game channels**: `valorant-12345`
- **Discord events**: `Destiny 2 - Raid: Vault of Glass` or `Valorant - Competitive`
- **Event IDs**: `Destiny2-Raid-12345` or `Valorant-Competitive-12345`

## **Color Scheme**
- Event embeds: Blue (#5865F2)
- Reminders: Orange (#F08328)
- Cancellations: Orange (#F08328)
- Success logs: Green
- Error/Cancel logs: Red

Ready for stress testing! 🚀
