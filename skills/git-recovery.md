---
name: git-recovery
description: Recover from detached HEAD, merge conflicts, accidental resets, and repository bloat.
triggers: git, detached head, merge conflict, reflog, rebase, stash
---
# Git Recovery Runbook

1. Start with `<git path="." />` to inspect branch state, remotes, and recent commits.
2. Never run `git reset --hard` or `git clean -fd` without creating a safety branch (`git branch backup-before-fix`) first.
3. For lost commits after a reset/rebase, inspect `git reflog -n 20` and cherry-pick or reset to the target SHA.
4. For large accidental files in history, identify them before rewriting history.
