# Clean database deployment

This plan replaces the restore-and-upgrade rehearsal only for a separately approved clean cutover. The operator confirmed that the existing PostgreSQL database contains test/demo data. No production database was queried. A clean schema starts with no organizations, accounts, vacancies, assessments, applications, matching evidence, or delivery history. Confirm which demo accounts and fixtures must be recreated before approving the cutover.

## Configuration and preservation

The repository Compose file wires the backend to PostgreSQL 16 via the internal db service and DATABASE_URL. PostgreSQL data and uploaded CVs use separate named volumes. JWT, callback authentication, CORS, Ollama, and other runtime settings come from deployment configuration. n8n workflows and credential references are managed independently.

Use a new Compose project with distinct database and CV volumes, a private database network, and separate loopback staging ports. Preserve the old project, volumes, CV files, backup, image identifiers, and secret configuration. Do not copy the existing database volume into the new project. The normal backend image starts Uvicorn, so run Alembic explicitly before opening traffic.

Before requesting approval, verify that no required organization membership, vacancy, assessment, attachment, or delivery record must follow the cutover. Retain any necessary non-database configuration through its existing secret store and document how the authorized initial recruiter will be provisioned. Discarding old test records from the live view does not require deleting their database.

## Approved deployment order

1. Review a dedicated Compose manifest with distinct ports, project-scoped volume names, pinned images, and a private database. Check the effective config with a redacted comparison. Set CV_AUTOMATION_ENABLED and N8N_AUTO_DISPATCH_ENABLED to false. Keep the new n8n workflow inactive and unpublished.
2. With approval, use the reviewed manifest and secured environment file. From the repository root set PowerShell variables `$project`, `$manifest`, and `$environmentFile` to the approved new project and file paths. Confirm the project has never mounted the old volumes.
3. Start and wait for only the new database.

       docker compose -p $project --env-file $environmentFile -f $manifest up -d --wait db

4. Initialize the empty database. Abort on any nonzero exit and inspect the disposable or new instance only.

       docker compose -p $project --env-file $environmentFile -f $manifest run --rm --no-deps backend python -m alembic -c backend/alembic.ini upgrade 0008_recruiter_summaries
       docker compose -p $project --env-file $environmentFile -f $manifest run --rm --no-deps backend python -m alembic -c backend/alembic.ini current

5. Start the approved new application stack on its staging ports. Verify revision 0008_recruiter_summaries, health, login, tenant isolation, CV storage permissions, and dispatch flags. Provision only approved operator accounts and data. Do not copy the synthetic smoke fixture into the live database.
6. After separate traffic approval, point ingress to the new backend and frontend. Keep delivery off. Workflow publication and dispatch require separate explicit approval.

## Rollback

Before traffic changes, stop the new project and retain its volumes for diagnosis. After a traffic switch, disable any newly enabled dispatch first, then route ingress back to the preserved prior frontend/backend and their original database and CV storage. Verify health and dispatch flags before reopening access. Preserve both databases and reconcile any records written after the switch before retrying. Do not use Alembic downgrade as rollback because the delivery migration intentionally preserves evidence. No volume removal is required.

       docker compose -p $project --env-file $environmentFile -f $manifest stop

The rollback command targets the new project after traffic is off it. Never use down -v on either project.
