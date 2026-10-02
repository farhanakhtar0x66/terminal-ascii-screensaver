# Planned improvements

- [x] Task-duration mode (`--run`): animate while a build, kernel compilation, or agent task
  runs; restore the terminal automatically when it finishes, retaining logs and
  exit status and supporting cancellation.

- [x] Automatic bash/zsh sessions: animate after ten seconds of unattended work,
  keep interactive input and normal output, and write no task logs.
- [x] OpenCode event integration: pause for questions/permissions and stop at idle.
- [ ] Equivalent event integrations for other full-screen agents.

- [ ] Add larger, readable artwork options for high-density displays such as
  the 13-inch MacBook Air. Favor larger FIGlet fonts and adjustable artwork
  size without changing the user's terminal font or losing letter details.
- [ ] Investigate theme-aware animated gradients (including light themes and
  Catppuccin variants). Currently `--theme` uses the terminal foreground color;
  normal mode deliberately uses effect-specific gradients.
