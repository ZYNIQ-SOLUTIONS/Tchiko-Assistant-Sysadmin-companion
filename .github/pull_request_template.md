## Summary

<!-- Briefly describe what this PR changes and why. -->

## Type of Change

- [ ] Bug fix (`fix:`)
- [ ] New feature (`feat:`)
- [ ] Refactoring / performance (`refactor:` / `perf:`)
- [ ] Documentation (`docs:`)
- [ ] Tests / CI (`test:` / `ci:`)

## Related Issues

<!-- Link related issues, e.g. Closes #123 -->

## Checklist

- [ ] `python3 -m unittest discover -s tests -v` passes locally
- [ ] `python3 main.py --self-test` passes locally (and regenerated SVGs are included if `svg_ghost_renderer.py` changed)
- [ ] New functions/methods include Python 3.10+ type annotations and docstrings
- [ ] Any new host-level tool in `LinuxSystemToolkit` enforces RBAC via `self.config.can_execute_capability(...)` and creates `.bak` backups before mutating files
- [ ] Documentation (`README.md`, `docs/ARCHITECTURE.md`, `CHANGELOG.md`) updated if behavior or public APIs changed
