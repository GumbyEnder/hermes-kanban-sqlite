"""
TUI (Terminal UI) Rendering Module — Interactive Kanban display in terminal.

Uses Textual for rich terminal rendering with:
- Column-based kanban layout
- Card hover/selection for editing
- Basic drag-and-drop via mouse events
- Real-time updates (polling backend)
"""
import textual.app
from textual import work, on
from textual.containers import Container, Horizontal
from textual.widgets import Static, Input, Button
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.message import Message

from ..kanban import (
    list_cards,
    get_card,
    update_card,
    archive_card,
    add_comment,
)

class KanbanCard(Static):
    """A single kanban card in the TUI."""

    def __init__(self, title: str, column_name: str = "To Do", tags: list = None, **kwargs):
        super().__init__(id=title[:50] if len(title) > 50 else title, **kwargs)
        self.title = title
        self.column = column_name
        self.tags = tags or []

    def compose(self) -> Container:
        with Horizontal(id="card-title"):
            yield Static(f\"🎴 [{len(str(self.id))}] {self.title}\", classes="title")
            if self.tags:
                tag_text = ", ".join(t["name"] for t in self.tags)
                yield Static(tag_text, id="card-tags", classes="tags")

        with Horizontal(id="card-column"):
            yield Static(self.column, id="column-label", classes="column-badge")
            if self.tags:
                tag_badge = Static(", ".join(t["name"] for t in self.tags), id="tag-badges", classes="tags")
                yield tag_badge

    def on_key(self, event: textual.app.KeyEvents.Key):
        """Handle key events (e.g., 'd' to delete card)."""
        if event.key == "d":
            self.query_one(".delete-button", Button).press()


class KanbanColumn(Static):
    """A kanban column containing cards."""

    def __init__(self, name: str, description: str = ""):
        super().__init__(id=f"column-{name.replace(' ', '-').lower()}")
        self.name = name
        self.description = description

    def compose(self) -> Container:
        # Header showing column name and card count
        yield Static(f\"📂 {self.name} ({len(self.query(KanbanCard))})\", id="column-header")

        with Horizontal(id="cards-container"):
            # Cards are rendered here via on_mount

    def on_mount(self) -> None:
        """Render all cards in this column."""
        for card_data in self.data.get("cards", []):
            yield KanbanCard(
                title=card_data["title"],
                column_name=self.name,
                tags=card_data.get("tags", [])
            )

    def on_key(self, event: textual.app.KeyEvents.Key):
        """Handle key events (e.g., 'Enter' to select card for editing)."""
        if event.key == "enter":
            # Highlight the selected card and prompt for actions
            self.query_one(".selected-card", Static).focus()


class KanbanBoard(Static):
    """Main kanban board container."""

    def __init__(self, db_path: str = None):
        super().__init__()  # type: ignore[call-arg]
        self.db_path = db_path or str(__import__("pathlib").Path.home() / ".hermes/kanban.db")
        self.selected_card_id = None
        self.columns_data = {}

    def on_mount(self) -> None:
        """Initialize the board by loading cards from database."""
        try:
            from ..database import SQLiteDatabase
            with SQLiteDatabase(self.db_path) as db:
                # Load all columns first
                columns = [c for c in db.get_columns()]
                self.columns_data = {c["name"]: c for c in columns}

                # Then load cards per column
                active_columns = list(columns)  # Exclude "Blocked", "Done"
                for col_name in active_columns:
                    cards = list_cards(
                        str(self.db_path),
                        column_name=col_name,
                        status="active"
                    )
                    self.columns_data[col_name]["cards"] = cards
        except Exception as e:
            self.add_error(f\"Failed to load kanban board: {e}\")

    def on_key(self, event: textual.app.KeyEvents.Key):
        """Handle global key events."""
        if not self.has_focus:
            return

        # 'Escape' — clear selection
        if event.key == "escape":
            self.selected_card_id = None
            for col in self.query(KanbanColumn):
                card = col.query_one(".selected-card", Static)
                if card is not None:
                    card.styles.background = ""

        # 'Enter' — select a card
        elif event.key == "enter":
            selected_card = self.query_one(".selected-card", Static) or KanbanCard(
                title="No card selected",
                column_name=self.focus_column  # type: ignore[attr-defined]
            )
            if selected_card and selected_card.title != "No card selected":
                self.selected_card_id = len(str(selected_card.id))  # Simple ID extraction
                self.prompt_card_action()

        # 'd' — delete/archive selected card
        elif event.key == "d":
            self.archive_selected_card()

    def prompt_card_action(self) -> None:
        """Prompt for actions on the selected card."""
        # TODO: Implement card editing modal
        click.echo(f\"  Selected Card: {self.selected_card_id}\")
        print("TODO: Implement card editing modal here.")

    def archive_selected_card(self) -> None:
        """Archive the selected card."""
        if not self.selected_card_id:
            click.echo("No card selected to archive.")
            return

        try:
            from ..database import SQLiteDatabase
            with SQLiteDatabase(self.db_path) as db:
                archived = archive_card(str(self.db_path), self.selected_card_id)
                if archived:
                    # Refresh the board display
                    self.on_mount()
                    click.echo(f\"✅ Card {self.selected_card_id} archived.\")
        except Exception as e:
            click.echo(f\"❌ Error archiving card: {e}\")
