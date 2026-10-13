# README Maintenance

`README.md` is the canonical public landing page. `README.zh-CN.md` is the maintained Simplified Chinese translation.

The locale registry, section contract, freshness state, and terminology metadata live in this directory. Translation freshness is explicit: changing English semantics invalidates the translation stamp until the translation is reviewed and marked current.

```bash
python scripts/readme_i18n.py status
python scripts/readme_i18n.py sync-navigation
python scripts/readme_i18n.py mark-current en zh-CN
python scripts/check_readme_i18n.py --all-current
```

README pages must describe current release behavior only. Development history, private projects, machine paths, run IDs, unpublished results, and historical validation counts do not belong on the public landing surface.
