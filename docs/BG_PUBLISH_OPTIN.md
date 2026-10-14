# Background publish (opt-in, NOT enabled)

Publishing in a background process keeps Nuke usable while a large publish runs.
It is **not enabled** in this config because the `tk-multi-publish2` version
currently pinned does not support it safely.

## Before enabling
1. Upgrade `tk-multi-publish2` to a release that ships background publishing
   (check the release notes / `info.yml` for the `background_processing` setting).
2. Test on ONE machine, one shot, with a Nuke script publish AND a write-node publish.
3. Confirm plugins are background-safe: Deadline-submitting and ShotGrid-writing
   plugins should run in the foreground (`Publish to Shotgun` stays foreground).

## Config (once the app supports it)
In `env/includes/settings/tk-multi-publish2.yml`, per plugin that is safe:

```yaml
- name: Publish Files to Shotgun
  hook: "{self}/publish_file.py:{config}/tk-multi-publish2/..."
  settings: {}
  # background_processing: true   # <- only on apps that support it
```

Roll back by removing the setting. Nothing else in this branch depends on it.
