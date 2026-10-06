# FlashScan

FlashScan is a Windows desktop utility for scanning disks and folders and exporting a detailed file list. Built with Python and a vanilla JavaScript frontend using `pywebview`, it lets you filter, select, and review files before generating reports in Markdown, JSON, plain text, or a rich self-contained HTML file.

![FlashScan – file tree view](docs/screenshots/tree_view.png)

---

## Getting Started

### Prerequisites

- Windows 10 or later
- Python 3.11+
- [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/) — required by `pywebview` on Windows. Most up-to-date Windows 10/11 systems already have it installed.

### Installation

1. **Clone the repository:**
```bash
   git clone https://github.com/coding-codess/flashscan.git
   cd flashscan
```

2. **Install dependencies:**
```bash
   pip install -r requirements.txt
```
   This installs one package: `pywebview >= 4.4`.

3. **Run the application:**
```bash
   python main.py
```

---

## Features

- **Fast File System Scanning**: Scans directories with configurable depth, with options to include hidden and system files.
- **Interactive File Tree**: A virtualized, high-performance tree view displays the scanned folder structure, capable of handling very large file lists smoothly.
- **Advanced Filtering & Selection**:
  - Filter files by extension, with pre-defined categories and support for custom extensions.
  - Full-text search for files and folders.
  - Advanced filters for category, file size, and modification date.
  - Bulk actions like select/deselect all, and three-state folder-level management (include all, name only, or skip).
- **Multiple Export Formats**:
  - **HTML**: A self-contained, interactive report with collapsible sections, color-coded file types, and a dark/light theme toggle.

    ![HTML export – dark mode](docs/screenshots/html_export.png)

  - **Markdown**: A clean, readable document with structured headings and lists.
  - **JSON**: Structured data ideal for scripting and programmatic use.
  - **TXT**: A simple plain text file for maximum compatibility.
- **Context Menu**: Right-click any file or folder for quick actions — Open, Show in Explorer, Copy Path, Copy Name, and Properties.
- **Keyboard Shortcuts**: Full keyboard navigation for power users (see [Keyboard Shortcuts](#keyboard-shortcuts)).
- **Persistent Settings**: Remembers your last used paths, theme, sorting, and scan options between sessions.
- **Drive Memory**: Remembers folder notes, folder states (name only / skip), excluded files, and expanded folders for each drive, so rescanning a flash drive restores your selection even if its drive letter changes.

---

## User Interface Workflow

The application guides you through a simple three-step process:

1. **Scan**: Select a folder or disk to scan. Configure scan depth and whether to include hidden or system files. A progress bar shows scan status.
2. **Select Files**: Browse the interactive file tree. Use the extension sidebar, search bar, or advanced filters to narrow down files. Manage folders with three-state selection (full / name only / skip). The status bar shows a running total of selected files and their combined size.
3. **Export**: Choose one or more output formats, specify a save location, and generate the report.

---

## Keyboard Shortcuts

These shortcuts are active in the file tree on Step 2.

| Shortcut | Action |
|---|---|
| `Ctrl+F` | Focus the search bar |
| `Escape` | Clear the search bar |
| `Ctrl+A` | Select all files |
| `Ctrl+D` | Deselect all files |
| `Ctrl+E` | Expand all folders |
| `Ctrl+W` | Collapse all folders |
| `↑` / `↓` | Move focus up / down |
| `←` / `→` | Collapse / expand the focused folder |
| `Space` | Toggle file selection; cycle folder state (full → name only → skip) |
| `Enter` | Toggle file selection; collapse / expand the focused folder |
| `Shift+Click` | Range-select files |
| `Enter` *(path input)* | Start scan |