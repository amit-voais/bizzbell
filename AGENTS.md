# Bizzbell for Codex (and other agents)

This folder is the **Bizzbell** skill: it makes short AI videos and video ads from a brief, through one Hidrogen API
key, with a quality gate at every layer.

**Read `SKILL.md` and follow it.** It is the full process: the permission points, the ordered stages (each with a
guide in `stages/`), and the gate loop. Everything below is a reminder of what must never be skipped.

- Run every command from this folder: `python3 scripts/bb.py <command>`. Start with `python3 scripts/bb.py doctor`.
- Ask the user before anything is paid for, and record their yes with `python3 scripts/bb.py budget set <inr>`.
  Never raise the cap yourself.
- Never ask for, print, echo, grep or copy an API key. If the key is missing, ask the user to run
  `python3 scripts/bb.py key` themselves.
- The optional ChatGPT step needs the user's yes and a browser tool; the user logs in themselves, and you never type
  a password or a code.
- A real person's face needs `CONSENT.md` first. The voice is always synthetic.
- Never publish, upload or send anything.
- Contributors: the tests run offline against a mock server: `python3 -m unittest discover -s tests -v`.
