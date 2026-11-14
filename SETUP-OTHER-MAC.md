# Put Session Canvas on your other Mac

You need: the zip (`session-canvas-1.0.1-<date>.zip`), and Claude Code already installed on the other Mac.
Nothing else (no Homebrew). It uses Apple's own Python (`/usr/bin/python3`). If that Mac has never had Apple's
Command Line Tools, the installer stops and tells you the one command to run first (`xcode-select --install`).

## 1. Copy the zip over (AirDrop)
1. On this Mac, open Finder, go to the `dist` folder, right-click the zip → **Share** → **AirDrop**.
2. Pick the other Mac. On the other Mac, click **Accept**. The zip lands in **Downloads**.

## 2. Unzip and install
1. On the other Mac, double-click the zip in Downloads. You get a folder `session-canvas-1.0.1`.
2. Open **Terminal** (Cmd+Space, type "Terminal", Enter) and paste these two lines:
   ```sh
   cd ~/Downloads/session-canvas-1.0.1
   ./install.sh
   ```
   If it says "permission denied", run `zsh install.sh` instead.
3. It asks two yes/no questions: add the `session-canvas` command (say **yes**), and start it at login
   (your choice; **no** is fine). Then your browser opens the board.

## 3. First-run wizard (3 questions, then done)
- **Folder**: your main project folder (new sessions start there). Pick one from the list or type a path.
- **Terminal**: which app opens sessions: Terminal, iTerm or Ghostty.
- **Quick start**: optional commands you often type first (skip if unsure).
You can change all of this later: press **?** on the board → Settings.

## 4. The macOS permission box
The first time you click **Resume** (open a session) with Terminal or iTerm, macOS shows a box like
"… wants access to control Terminal" (the name before it may be python3, osascript or Terminal). It means: may Session Canvas open a Terminal window for you?
Click **OK** once. If you clicked "Don't Allow" by mistake: System Settings → Privacy & Security →
Automation → turn Terminal on. Ghostty never asks.

## 5. Daily use
Open a **new** Terminal window, then: `session-canvas` (open the board), `session-canvas stop`, `session-canvas status`.
The board is at http://127.0.0.1:7788/ while it runs.

## 6. Uninstall
Run `session-canvas uninstall`. It removes the app and the command, and asks before deleting your board
data (notes, positions). Your Claude Code sessions are never touched.
