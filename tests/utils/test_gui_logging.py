"""Simple test script for GUI components."""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import scrolledtext

from utils.gui_logging_handler import GUILoggingHandler
from utils.logger_utils import LoggerUtils


def run_gui_logging_demo() -> None:
    """Run a manual GUI demo for GUILoggingHandler.

    This script is not intended for automated test runs.
    """
    # Setup logger
    logger = LoggerUtils.get_logger(__name__)

    # Create root window
    root = tk.Tk()
    root.title("GUI Logging Test")
    root.geometry("600x400")

    # Create text widget
    text_widget = scrolledtext.ScrolledText(
        root, state="disabled", wrap=tk.WORD, font=("Courier", 10), bg="#1E1E1E", fg="#00FF00"
    )
    text_widget.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    # Create and add logging handler
    gui_handler = GUILoggingHandler(text_widget, max_lines=30)
    gui_handler.setFormatter(logging.Formatter("%(levelname)-8s: %(message)s"))
    logging.getLogger().addHandler(gui_handler)
    logging.getLogger().setLevel(logging.DEBUG)

    # Test logging
    logger.debug("This is a DEBUG message")
    logger.info("This is an INFO message")
    logger.warning("This is a WARNING message")
    logger.error("This is an ERROR message")
    logger.critical("This is a CRITICAL message")

    # Close button
    close_btn = tk.Button(root, text="Close", command=root.quit, bg="#FF6B6B", fg="white")
    close_btn.pack(pady=5)

    root.mainloop()
    print("Test completed successfully!")


if __name__ == "__main__":
    run_gui_logging_demo()
