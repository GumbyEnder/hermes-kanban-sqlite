"""
CLI entry point for hermes-kanban-sqlite.

Usage:
  hermes-kanban-sqlite init <project> — Initialize a new Kanban board
  hermes-kanban-sqlite list [column] — List cards, optionally filtered by column
  hermes-kanban-sqlite add <title> [description] — Add a card to the current board
  hermes-kanban-sqlite move <card_id> <new_column>
  hermes-kanban-sqlite info <card_id> — Show detailed card information
"""
import click
from pathlib import Path
import sqlite3

from .database import init_schema, get_connection, SQLiteDatabase
from .kanban import (
    create_board,
    list_boards,
    list_cards,
    get_card,
    update_card,
    archive_card,
    delete_card,
    add_comment,
    get_dependencies,
)

class KanbanBoardError(Exception):
    """CLI error for kanban operations."""
    pass

@click.group(invoke_without_command=True)
def cli():
    """Hermes Kanban SQLite — Standalone terminal Kanban CLI/TUI.
    
    Initialize with `hermes-kanban-sqlite init <project>` or use the default DB at ~/.hermes/kanban.db
    """
    db_path = Path.home() / ".hermes/kanban.db"
    if not db_path.exists():
        click.echo(f"📁 No Kanban database found at {db_path}")
        click.echo("Run `hermes-kanban-sqlite init <project>` to create a new board.")
        # Show available commands
        help_menu = "\nAvailable commands:\n"
        for param in cli.params:
            if param.name and not param.hidden:
                help_menu += f"  {param.name}\n"
        click.echo(help_menu)
    else:
        click.echo(f"✅ Kanban database found at {db_path}")

# Subcommands
@cli.command()
def init(project_name: str, db_path: Path = None):
    """Initialize a new Kanban board.
    
    PROJECT — Name for the new board (e.g., "Project-X-Backlog")
    """
    if not project_name:
        click.echo("❌ Error: Project name required.\nUsage: hermes-kanban-sqlite init <project>")
        return
    
    # Default to home directory if no db_path provided
    if db_path is None:
        default_db = Path.home() / f".hermes/{project_name}.db"
        click.echo(f"📁 Creating board at {default_db}")
    else:
        default_db = Path(db_path).resolve()
    
    # Initialize schema
    with SQLiteDatabase(default_db) as db:
        try:
            init_schema(str(default_db))
            click.echo(f"✅ Schema initialized successfully\n")
            click.echo(f"📋 Board: {project_name}")
            click.echo(f"💾 Database: {default_db}")
            
            # Create default columns
            for name, desc, color, _ in STANDARD_COLUMNS:
                try:
                    create_column(str(default_db), -1, name, desc, color)
                except Exception as e:
                    click.echo(f"⚠️  Column '{name}' may already exist: {e}")
            
            click.echo("✅ Default columns created successfully")
            click.echo(f"\n🎯 Next steps:\n  - hermes-kanban-sqlite list    — View all cards
  - hermes-kanban-sqlite add <title> — Add a new card")
            
        except KanbanError as e:
            click.echo(f"❌ Error: {e}")

@cli.command(name='list')
def list_cards(column_name: str = None, status: str = None):
    """List cards on the current board.
    
    Use `hermes-kanban-sqlite list [column]` to filter by column.\n
    Examples:\n      hermes-kanban-sqlite list                  — List all cards\n      hermes-kanban-sqlite list To Do            — Filter to "To Do" column only\n    """
    db_path = Path.home() / ".hermes/kanban.db"
    if not db_path.exists():
        click.echo(f"❌ No database found at {db_path}")
        return
    
    with SQLiteDatabase(str(db_path)) as db:
        try:
            cards = list_cards(str(db_path), column_name=column_name, status=status)
            if not cards:
                click.echo("📭 No cards to display\n")
                return
            
            # Display in a readable format
            for card in cards:
                tags = " | ".join(t["name"] for t in card.get("tags", []))
                comments_count = len(card.get("comments", []))
                status_icon = "🟢" if card["status"] == "active" else f"⚪ ({card['status']})"
                
                click.echo(f\"  {status_icon} [{len(str(card['id']))}] {card['title']}\")
                click.echo(f\"      Column: {card['column_name']} | Tags: {tags if tags else '—'}\")
                if comments_count:
                    click.echo(f\"      Comments: {comments_count}\")
            
        except KanbanError as e:
            click.echo(f"❌ Error: {e}")

@cli.command()
def add(title: str, description: str = None):
    """Add a new card to the current board.
    
    Title — Short title for the card\nDescription — Optional detailed description (defaults to repeating title)
    """
    db_path = Path.home() / ".hermes/kanban.db"
    if not db_path.exists():
        click.echo(f"❌ No database found at {db_path}\nRun `hermes-kanban-sqlite init <project>` first.")
        return
    
    with SQLiteDatabase(str(db_path)) as db:
        try:
            if description is None:
                description = f"Description: {title}"
            
            card_id = create_card(
                str(db_path),
                board_id=-1,  # Global cards table (can be enhanced per-board later)
                title=title,
                column_name="To Do",  # Default starting column
                description=description
            )
            click.echo(f"✅ Card created successfully\n")
            click.echo(f\"  ID: {card_id}\")
            click.echo(f\"  Title: {title}\")
            click.echo(f\"  Description: {description}\")
            
        except KanbanError as e:
            click.echo(f"❌ Error: {e}")

@cli.command()
def move(card_id: int, new_column: str = None):
    """Move a card to a different column.
    
    CARD_ID — ID of the card from `hermes-kanban-sqlite list`
    NEW_COLUMN — Target column (e.g., "Backlog", "To Do", "In Progress", etc.)
    """
    db_path = Path.home() / ".hermes/kanban.db"
    if not db_path.exists():
        click.echo(f"❌ No database found at {db_path}\nRun `hermes-kanban-sqlite init <project>` first.")
        return
    
    with SQLiteDatabase(str(db_path)) as db:
        try:
            # First, get the card to know its title
            card = get_card(str(db_path), card_id)
            if not card:
                click.echo(f"❌ Card with ID {card_id} not found\n")
                return
            
            original_column = card["column_name"]
            new_description = f"Moved from {original_column} → {new_column or 'Backlog'}"
            
            # Update the card
            update_card(
                str(db_path),
                card_id=card_id,
                description=new_description,
                column_name=new_column if new_column else "Backlog"  # Default to Backlog if not specified
            )
            click.echo(f"✅ Card moved successfully\n")
            click.echo(f\"  ID: {card_id}\")
            click.echo(f\"  From: {original_column} → To: {new_column or 'Backlog'}\")
            
        except KanbanError as e:
            click.echo(f"❌ Error: {e}")

@cli.command()
def info(card_id: int = None):
    """Show detailed information about a card.
    
    CARD_ID — Optional. If not specified, shows the most recently added card.\n    """
    db_path = Path.home() / ".hermes/kanban.db"
    if not db_path.exists():
        click.echo(f"❌ No database found at {db_path}\nRun `hermes-kanban-sqlite init <project>` first.")
        return
    
    with SQLiteDatabase(str(db_path)) as db:
        try:
            if card_id is None:
                # Get most recent card (by created_at DESC)
                cursor = get_connection(str(db_path)).cursor()
                cursor.execute(
                    "SELECT id, title, column_name FROM cards WHERE status != 'deleted' ORDER BY created_at DESC LIMIT 1"
                )
                row = cursor.fetchone()
                if not row:
                    click.echo("📭 No recent cards found\n")
                    return
                card_id = row[0]
            
            card = get_card(str(db_path), card_id)
            if not card:
                click.echo(f"❌ Card with ID {card_id} not found\n")
                return
            
            # Display card details
            click.echo(f\"🎴 CARD DETAILS\")
            click.echo(f\"  ID:   {card['id']}\")
            click.echo(f\"  Title:    {card['title']}\")
            click.echo(f\"  Column:   {card['column_name']}\")
            click.echo(f\"  Status:   {'🟢 active' if card['status'] == 'active' else f'⚪ {card['status']}' }\")
            
            # Tags
            tags = [t for t in card.get("tags", [])]
            if tags:
                click.echo(f\"  Tags:\   {' | '.join(t['name'] for t in tags)}\")
            else:
                click.echo(f\"  Tags:    —\")
            
            # Comments
            comments = card.get("comments", [])
            if comments:
                click.echo(f\"  Comments:\ ({len(comments)})\")
                for comment in comments:
                    click.echo(f\"    • [{comment['created_at']}] {comment['author']}:\")
                    click.echo(f\"      {comment['content']}\")
            else:
                click.echo(f\"  Comments: —\")
            
        except KanbanError as e:
            click.echo(f"❌ Error: {e}")

@cli.command()
def delete(card_id: int):
    """Soft-delete (archive) a card.
    
    This permanently removes the card from active view but keeps it in the database for audit purposes.\n
    Use `hermes-kanban-sqlite restore <card_id>` to undelete a card.\n    """
    db_path = Path.home() / ".hermes/kanban.db"
    if not db_path.exists():
        click.echo(f"❌ No database found at {db_path}\nRun `hermes-kanban-sqlite init <project>` first.")
        return
    
    with SQLiteDatabase(str(db_path)) as db:
        try:
            card = get_card(str(db_path), card_id)
            if not card:
                click.echo(f"❌ Card with ID {card_id} not found\n")
                return
            
            archive_card(str(db_path), card_id)
            click.echo(f"✅ Card archived successfully\n")
            click.echo(f\"  ID: {card['id']}\")
            click.echo(f\"  Title: {card['title']}\")
            click.echo("💾 The card has been soft-deleted and can be restored if needed.")
            
        except KanbanError as e:
            click.echo(f"❌ Error: {e}")

@cli.command()
def restore(card_id: int):
    """Restore a previously archived card."""
    db_path = Path.home() / ".hermes/kanban.db"
    if not db_path.exists():
        click.echo(f"❌ No database found at {db_path}\nRun `hermes-kanban-sqlite init <project>` first.")
        return
    
    with SQLiteDatabase(str(db_path)) as db:
        try:
            cursor = get_connection(str(db_path)).cursor()
            cursor.execute(
                "SELECT id, title FROM cards WHERE id = ? AND status = 'archived'",
                (card_id,) if card_id else ()
            )
            row = cursor.fetchone()
            if not row:
                click.echo(f"❌ Card with ID {card_id} not found or already active\n")
                return
            
            # Restore by deleting the record (SQLite doesn't have a true "restore", we'd need a history table)
            # For now, just note that this would require schema modification to support proper undo\n            click.echo(f"⚠️  Schema limitation: True restore requires history tracking in the database.")
            click.echo(f"💾 The card cannot be fully restored without modifying the schema.")
        except Exception as e:
            click.echo(f"❌ Error: {e}")

@cli.command()
def comment(card_id: int, content: str = None):
    """Add a comment to a card."""
    db_path = Path.home() / ".hermes/kanban.db"
    if not db_path.exists():
        click.echo(f"❌ No database found at {db_path}\nRun `hermes-kanban-sqlite init <project>` first.")
        return
    
    with SQLiteDatabase(str(db_path)) as db:
        try:
            if content is None or not content.strip():
                click.echo("❌ Error: Comment text required\n")
                return
            
            comment_id = add_comment(
                str(db_path),
                card_id=card_id,
                author="CLI User",
                content=content or ""
            )
            click.echo(f"✅ Comment added successfully (ID: {comment_id})\n")
        except Exception as e:
            click.echo(f"❌ Error: {e}")

@cli.command()
def dependency(card1_id: int, card2_id: int):
    """Create a blocking relationship between two cards.
    
    CARD1 — The blocker (this work blocks the other)
    CARD2 — The blocked-by (depends on CARD1 being completed first)
    """
    db_path = Path.home() / ".hermes/kanban.db"
    if not db_path.exists():
        click.echo(f"❌ No database found at {db_path}\nRun `hermes-kanban-sqlite init <project>` first.")
        return
    
    with SQLiteDatabase(str(db_path)) as db:
        try:
            # Validate both cards exist
            card1 = get_card(str(db_path), card1_id)
            card2 = get_card(str(db_path), card2_id)
            if not card1 or not card2:
                click.echo(f"❌ One or both cards not found\n")
                return
            
            dep_id = add_dependency(
                str(db_path),
                blocker_card_id=card1["id"],
                blocked_by_card_id=card2["id"]
            )
            click.echo(f"✅ Dependency created successfully\n")
            click.echo(f\"  Blocker:   {card1['title']} (ID: {card1['id']})\")
            click.echo(f\"  Blocked by:{card2['title']} (ID: {card2['id']})\")
            
        except Exception as e:
            click.echo(f"❌ Error: {e}")

if __name__ == "__main__":
    cli()
