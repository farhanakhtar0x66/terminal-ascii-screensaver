# Terminal ASCII Screensaver

An Omarchy-inspired animated ASCII screensaver for **Linux and macOS**. It centers
editable artwork in your terminal, runs random text effects, and exits on any key.
It uses Omarchy's `ttfx` engine when available and otherwise the original Python
TerminalTextEffects engine, installed automatically with this project.

## Install

You need Python 3.9+ and [pipx](https://pipx.pypa.io/stable/installation/).

On macOS with Homebrew:

```sh
brew install pipx
pipx ensurepath
```

On Debian/Ubuntu:

```sh
sudo apt install pipx
pipx ensurepath
```

On Arch Linux:

```sh
sudo pacman -S python-pipx
pipx ensurepath
```

Open a new terminal after `ensurepath`, then install:

```sh
pipx install git+https://github.com/farhanakhtar0x66/terminal-ascii-screensaver.git
screensaver
```

This installs dependencies in an isolated environment; no separate engine setup
is needed. Windows users can run it inside **WSL** using the Linux instructions.
Native Windows is not supported.

## Customize your artwork

The first run creates a placeholder logo. Enter your own text with:

```sh
screensaver --new-art
screensaver
```

The prompt generates a slanted ASCII logo and saves it for subsequent runs.
You can edit that art by hand, or replace it with your own multiline drawing:

```sh
screensaver --art-path
```

Installed artwork lives in
`~/.config/terminal-ascii-screensaver/ascii.txt`, or under `$XDG_CONFIG_HOME` when
set. Choose any other file with `screensaver /path/to/ascii.txt`.

## Automatic triggering (bash and zsh)

Start an automatic terminal session once, then use your commands normally:

```sh
screensaver --auto --shell zsh
# or: screensaver --auto --shell bash
brew upgrade
```

When a command is running and you haven't typed or moved the mouse inside the
terminal for **10 seconds**, the animation appears. Input dismisses it; task
completion restores the terminal automatically. Output generated while covered
is held briefly in memory and displayed normally on return, exactly once.
**Automatic mode writes no task logs.** Commands retain their interactive stdin.
The shell's prompt itself never starts an animation.

Enable this for future terminal sessions:

```sh
screensaver --install-shell zsh
screensaver --install-shell bash
```

The installer adds a marked startup block to `.zshrc` or `.bashrc` (on macOS,
`.bash_profile` for bash), preserves existing settings and makes a backup if
the file already exists. Open a new terminal afterwards. To uninstall the
integration, remove the marked block before uninstalling the application.

Use `--idle-after 30` to change the delay when starting an automatic session.
Known confirmation/password prompts suspend the animation. Text-based prompt
detection cannot recognize every possible custom CLI prompt; pressing a key
always dismisses the animation, and input is still available to the command.
Mouse reporting during a task can require holding Shift for native text selection.

### OpenCode

```sh
screensaver --install-opencode
```

Quit and restart OpenCode **inside an automatic session**. The optional local
plugin sends only activity states over a private local socket: working, waiting
for a question/permission, and idle. It writes no conversation content or logs.
An animation stops when a question or permission appears or the agent finishes
its turn—even if the agent application stays open. Full-screen text UI content
is tracked in memory and redrawn when the overlay is dismissed.

Other full-screen agents are not automatically inferred to be working. They need
an equivalent activity integration; otherwise their screen remains visible.
This is not global OS activity monitoring and doesn't attach to terminals that
were already open outside an automatic session.

## Themes and effects

Your terminal's background, transparency, font, and configured palette are left
untouched. By default effects use their own animated color gradients, as in
Omarchy. To use your terminal's foreground color instead:

```sh
screensaver --theme
```

`NO_COLOR` is also honored. Preview individual effects:

```sh
screensaver --effect beams
screensaver --effect fireworks
screensaver --effect matrix
screensaver --effect vhstape
```

Effect palettes are not automatically derived from Catppuccin or another terminal
theme. For consistently theme-matching text, use `screensaver --theme`.

## tmux

Inside tmux, the screensaver hides the current session's status bar while it runs
and restores the previous setting on exit, including multi-row status bars and
inherited settings. This affects all clients attached to that session. It runs
inside the current pane; it does not hide other panes or pane borders.

To keep the status bar visible:

```sh
screensaver --keep-tmux-status
```

Larger artwork for high-density screens and animated theme palettes are tracked
in [TODO.md](TODO.md).

Use `screensaver --engine tte` to force the bundled Python engine or
`screensaver --engine ttfx` to force Omarchy's installed Rust engine. Engine
versions can differ in effect availability and rendering details.

## Sizing and controls

- Reads actual terminal rows/columns rather than trusting stale environment values.
- Centers the artwork and fits oversized art in character cells.
- Rebuilds the animation when the terminal is resized.
- Uses a 120 FPS target and plays every effect once per randomly shuffled cycle.
  After the full catalog has played, it reshuffles for the next cycle. The last
  effect of a cycle won't immediately repeat at the start of the next one.
  Resizing restarts the current effect without consuming another cycle entry.
- Any key or Ctrl-C exits and restores the terminal's original input settings.

ASCII is a grid of characters, not a scalable image: shrinking large custom art
can lose detail. The terminal itself controls pixel resolution, font size, and
glyph sharpness. This is a manually launched terminal animation, not an OS lock
screen or automatic idle service.

## Run during a task

```sh
screensaver --run npm run build
screensaver --theme --run make -j8
screensaver --run sh -c 'make && make modules'
```

This older explicit mode is separate from automatic mode and **does save logs**.
Use `--auto` for automatic triggering without logs. Put `--run` last. Arguments after it belong to the command, and shell expressions
require an explicit `sh -c`. This mode is for **non-interactive** commands: stdin
is closed, and combined stdout/stderr are saved to a persistent log under
`~/.local/state/terminal-ascii-screensaver/logs` (or `$XDG_STATE_HOME`).

When the task finishes, the animation stops, output is replayed, and the command's
exit status is returned. Press any ordinary key to dismiss the animation and
follow the log while the task continues. Ctrl-C cancels the task and its worker
process group. The log path is printed on exit. Use this for agent builds only
when the agent supports non-interactive execution.

## Run from source

```sh
git clone https://github.com/farhanakhtar0x66/terminal-ascii-screensaver.git
cd terminal-ascii-screensaver
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/python screensaver
```

The source launcher uses `ascii.txt` beside the script; the installed `screensaver`
command uses the user config directory. Pass an explicit file to share artwork.

## Upgrade / uninstall

```sh
pipx upgrade terminal-ascii-screensaver
pipx uninstall terminal-ascii-screensaver
```

Uninstalling keeps your artwork in your config directory.

## TODO

- [x] **Task-duration screensaver:** `--run` shows animations while a build runs,
  then restores the terminal, replays logs, and returns the command's exit status.
- [x] Automatic bash/zsh sessions: trigger after unattended activity and preserve
  normal task output without disk logs.
- [x] OpenCode busy/idle/question/permission integration.
- [ ] Activity integrations for additional interactive agents.
- [ ] Larger, readable artwork for high-density displays such as the MacBook Air.
- [ ] Theme-aware animated color gradients, including Catppuccin and light themes.

Unchecked items are planned features.

## Credits and license

MIT licensed. Inspired by [Omarchy](https://github.com/omacom/omarchy).
Animations are provided by [ttfx](https://github.com/omacom/ttfx) and
[TerminalTextEffects](https://github.com/ChrisBuilds/terminaltexteffects).
Text artwork generation uses [pyfiglet](https://github.com/pwaller/pyfiglet).
Dependencies are installed separately; see `THIRD_PARTY_LICENSES.md` for details.
