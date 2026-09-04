# SITE ATTEMPTS
(item · attempt · what was tried · why it failed)

- process · 2026-09-04 · items 7 and 10 committed on a piped check (`| tail -1`) that was red only because staging came after the check; verified green unpiped afterwards. Never pipe the gate.
- process · 2026-09-04 · items 12 and 13 first committed red: a heredoc after `./site-check.sh &&` ended the chain, so `git commit` ran unconditionally. Reset --hard to 8e3fd4d and redone with the check immediately before the commit in one chain.
