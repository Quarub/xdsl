"""
An interactive command-line tool to explore compilation pipeline construction.

Execute `xdsl-gui` in your terminal to run it.

Run `textual run xdsl.interactive.app:InputApp --dev` to run in development mode. Please
be sure to install `textual-dev` to run this command.
"""

from io import StringIO

from rich.style import Style
from textual import events, on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.widgets import Button, Footer, Label, ListItem, ListView, TextArea
from textual.widgets.text_area import TextAreaTheme

from xdsl.dialects.builtin import ModuleOp
from xdsl.ir import MLContext
from xdsl.parser import Parser
from xdsl.passes import ModulePass, PipelinePass
from xdsl.printer import Printer
from xdsl.tools.command_line_tool import get_all_dialects, get_all_passes

from ._pasteboard import pyclip_copy

ALL_PASSES = tuple(sorted((p.name, p) for p in get_all_passes()))
"""Contains the list of xDSL passes."""


class OutputTextArea(TextArea):
    """Used to prevent users from being able to alter the Output TextArea."""

    async def _on_key(self, event: events.Key) -> None:
        event.prevent_default()


class InputApp(App[None]):
    """
    Interactive application for constructing compiler pipelines.
    """

    CSS_PATH = "app.tcss"

    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
        ("q", "quit_app", "Quit"),
    ]

    # defines a theme for the Input/Output TextArea's
    _DEFAULT_THEME = TextAreaTheme(
        name="my_theme_design",
        base_style=Style(bgcolor="white"),
        syntax_styles={
            "string": Style(color="red"),
            "comment": Style(color="magenta"),
        },
    )

    current_module = reactive[ModuleOp | Exception | None](None)
    """
    Reactive variable used to save the current state of the modified Input TextArea
    (i.e. is the Output TextArea).
    """
    pass_pipeline = reactive(tuple[type[ModulePass], ...])
    """Reactive variable that saves the list of selected passes."""

    input_text_area: TextArea
    """Input TextArea."""
    output_text_area: OutputTextArea
    """Output TextArea."""
    selected_query_label: Label
    """Display selected passes."""
    passes_list_view: ListView
    """ListView displaying the passes available to apply."""

    def __init__(self):
        self.input_text_area = TextArea(id="input")
        self.output_text_area = OutputTextArea(id="output")
        self.passes_list_view = ListView(id="passes_list_view")
        self.selected_query_label = Label("", id="selected_passes_label")

        super().__init__()

    def compose(self) -> ComposeResult:
        """
        Creates the required widgets, events, etc.
        """

        with Horizontal(id="top_container"):
            yield self.passes_list_view
            with Horizontal(id="button_and_selected_horziontal"):
                with Vertical(id="buttons"):
                    yield Button("Copy Query", id="copy_query_button")
                    yield Button("Clear Passes", id="clear_passes_button")
                with ScrollableContainer(id="selected_passes"):
                    yield self.selected_query_label
        with Horizontal(id="bottom_container"):
            with Vertical(id="input_container"):
                yield self.input_text_area
                yield Button("Clear Input", id="clear_input_button")
            with Vertical(id="output_container"):
                yield self.output_text_area
                yield Button("Copy Output", id="copy_output_button")
        yield Footer()

    @on(ListView.Selected)
    def update_pass_pipeline(self, event: ListView.Selected) -> None:
        """
        When a new selection is made, the reactive variable storing the list of selected
        passes is updated.
        """
        selected_pass = event.item.name
        for name, value in ALL_PASSES:
            if name == selected_pass:
                self.pass_pipeline = tuple((*self.pass_pipeline, value))
                return

    def watch_pass_pipeline(self) -> None:
        """
        When the reactive variable pass_pipeline changes, this function
        is called and updates the label to show the respective generated query in the Label.
        """
        new_passes = "\n" + (", " + "\n").join(p.name for p in self.pass_pipeline)
        new_label = f"xdsl-opt -p {new_passes}"
        self.selected_query_label.update(new_label)
        self.update_current_module()

    @on(TextArea.Changed, "#input")
    def update_current_module(self) -> None:
        """
        Function to parse the input and to apply the list of selected passes to it.
        """
        input_text = self.input_text_area.text
        if (input_text) == "":
            self.current_module = None
            return
        try:
            ctx = MLContext(True)
            for dialect in get_all_dialects():
                ctx.load_dialect(dialect)
            parser = Parser(ctx, input_text)
            module = parser.parse_module()
            pipeline = PipelinePass([p() for p in self.pass_pipeline])
            pipeline.apply(ctx, module)
            self.current_module = module
        except Exception as e:
            self.current_module = e

    def watch_current_module(self):
        """
        Function to update the Output TextArea.
        """
        match self.current_module:
            case None:
                output_text = "No input"
            case Exception() as e:
                output_stream = StringIO()
                Printer(output_stream).print(e)
                output_text = output_stream.getvalue()
            case ModuleOp():
                output_stream = StringIO()
                Printer(output_stream).print(self.current_module)
                output_text = output_stream.getvalue()

        self.output_text_area.load_text(output_text)

    def on_mount(self) -> None:
        """Configure widgets in this application before it is first shown."""

        # register's the theme for the Input/Output TextArea's
        self.input_text_area.register_theme(InputApp._DEFAULT_THEME)
        self.output_text_area.register_theme(InputApp._DEFAULT_THEME)
        self.input_text_area.theme = "my_theme_design"
        self.output_text_area.theme = "my_theme_design"

        self.query_one("#input_container").border_title = "Input xDSL IR"
        self.query_one("#output_container").border_title = "Output xDSL IR"
        self.query_one(
            "#passes_list_view"
        ).border_title = "Choose a pass or multiple passes to be applied."
        self.query_one("#selected_passes").border_title = "Selected passes/query"

        for n, _ in ALL_PASSES:
            self.passes_list_view.append(ListItem(Label(n), name=n))

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.dark = not self.dark

    def action_quit_app(self) -> None:
        """An action to quit the app."""
        self.exit()

    @on(Button.Pressed, "#clear_input_button")
    def clear_input(self, event: Button.Pressed) -> None:
        """Input TextArea is cleared when "Clear Input" button is pressed."""
        self.input_text_area.clear()

    @on(Button.Pressed, "#copy_output_button")
    def copy_output(self, event: Button.Pressed) -> None:
        """Output TextArea is copied when "Copy Output" button is pressed."""
        pyclip_copy(self.output_text_area.text)

    @on(Button.Pressed, "#copy_query_button")
    def copy_query(self, event: Button.Pressed) -> None:
        """Selected passes/query Label is copied when "Copy Query" button is pressed."""
        selected_passes = "\n" + (", " + "\n").join(p.name for p in self.pass_pipeline)
        query = f"xdsl-opt -p {selected_passes}"
        pyclip_copy(query)

    @on(Button.Pressed, "#clear_passes_button")
    def clear_passes(self, event: Button.Pressed) -> None:
        """Selected passes cleared when "Clear Passes" button is pressed."""
        self.pass_pipeline = ()


def main():
    return InputApp().run()


if __name__ == "__main__":
    main()