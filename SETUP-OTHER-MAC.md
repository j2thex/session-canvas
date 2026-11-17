# Put Session Canvas on another Mac (yours or a friend's)

You need: Claude Code already installed on that Mac. Nothing else (no Homebrew). It uses Apple's own Python
(`/usr/bin/python3`). If that Mac has never had Apple's Command Line Tools, the installer stops and tells you the
one command to run first (`xcode-select --install`).

## 1. Download
Open https://github.com/j2thex/session-canvas/releases/latest and click the zip under **Assets**
(`session-canvas-<version>-<date>.zip`). It lands in **Downloads**.

## 2. Unzip and install
1. Double-click the zip in Downloads. You get a folder like `session-canvas-1.2.2`.
2. Open **Terminal** (Cmd+Space, type "Terminal", Enter) and paste these two lines (use the folder name you got):
   ```sh
   cd ~/Downloads/session-canvas-1.2.2
   ./install.sh
   ```
   If it says "permission denied", run `zsh install.sh` instead.
3. It asks two yes/no questions: add the `session-canvas` command (say **yes**), and start it at login
   (your choice; **no** is fine). Then your browser opens the board.

## 3. First-run wizard (3 questions, then done)
- **Folder**: your main project folder (new sessions start there). Pick one from the list or type a path.
- **Terminal**: which app opens sessions: Terminal, iTerm or Ghostty.
- **Quick start**: optional commands you often type first (skip if unsure).
You can change all of this later: press **?** on the board → Settings. "Advanced settings" there (status reports,
reminder) are optional; leave them alone unless you know you want them.

## 4. The macOS permission box
The first time you click **Resume** (open a session) with Terminal or iTerm, macOS shows a box like
"… wants access to control Terminal" (the name before it may be python3, osascript or Terminal). It means: may Session Canvas open a Terminal window for you?
Click **OK** once. If you clicked "Don't Allow" by mistake: System Settings → Privacy & Security →
Automation → turn Terminal on. Ghostty never asks.

## 5. Daily use
Open a **new** Terminal window, then: `session-canvas` (open the board), `session-canvas stop`, `session-canvas status`.
The board is at http://127.0.0.1:7788/ while it runs.

## 6. Stay up to date
Run `session-canvas update`, or click the small **Update to v…** note at the bottom of the board when it
appears (the board looks once a day). Your board, notes and settings are kept. Every Mac that does this runs the
same version.

## 7. Uninstall
Run `session-canvas uninstall`. It removes the app and the command, and asks before deleting your board
data (notes, positions). Your Claude Code sessions are never touched.
