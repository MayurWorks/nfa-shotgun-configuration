# Slate configuration

The slate already exists (`nfaSlate` gizmo via the ShotGridReview Deadline plugin).
Only configuration is needed:

- Set `company_name` in the slate/review-submission settings to `SlateX`
  (in `env/includes/settings/tk-multi-deadlinereviewsubmission.yml`, or wherever
  your fork keeps the slate settings).
- Pick the slate template (`OS_Slate.nk` / `ZD_Slate.nk`) per project there.
- Slate fields (project, sequence, shot, version, artist, task, notes) come from
  the publish context; artists only type notes.
