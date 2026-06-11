# Decisions

## `.omni/` is local-only

Decision: the entire `.omni/` directory is ignored by git and should not be
committed, including `.omni/project_id`.

Rationale: OmniMemory uses this file as the durable local project identity after
`omni init`. On first creation, `omni init` bootstraps the value from the git
remote origin hash when a `git remote origin` URL is available; otherwise it
creates a random `proj_` id. After the file exists, the file wins over git
remote origin so moving the repo path or changing the remote later does not
silently change `project_id`.
