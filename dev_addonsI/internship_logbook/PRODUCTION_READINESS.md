# Internship Logbook Production Readiness

This checklist applies to the Odoo 19 Community `internship_logbook` module. It does not replace the project deployment and backup runbooks.

## Supported runtime

- Odoo 19 Community.
- Python 3.10 or a newer Python version supported by the deployed Odoo 19 build.
- PostgreSQL version supported by that Odoo build.
- Required Odoo addons: `base`, `mail`, `auth_signup`, `portal`, and `website`.
- A working `wkhtmltopdf` installation compatible with Odoo is required for PDF reports. Use the Odoo-supported patched-Qt build for the production operating system.
- The custom addons path must include the repository's `dev_addonsI` directory.

Confirm the exact Odoo, Python, PostgreSQL, and `wkhtmltopdf` versions in the deployment record before every release.

## Release gate

Before upgrading production:

1. Confirm the release commit is reviewed and the Git working tree is clean.
2. Confirm every manifest data file is tracked by Git. In particular, `wizard/communication_center_wizard_views.xml` must be included with Phase 5C and later releases.
3. Run the full `internship_logbook` automated test suite on a disposable database.
4. Run a standalone module upgrade on a disposable or restored test database.
5. Run Python, XML, CSV, duplicate XML-ID, UTF-8/BOM, secret, and whitespace validation.
6. Confirm no real credential, environment file, database dump, filestore, or local configuration is included in the release.
7. Record the exact known-good Git commit and matching database/filestore backup set.

## Configuration safety

AI provider secrets must remain server-side. Prefer a protected environment file such as `/etc/odoo/odoo-ai.env`, readable only by the Odoo service account. Never place a real key in Git, XML, the browser, chatter, or diagnostic output.

Production AI configuration should use an actual provider such as `gemini`; never enable the `mock` provider in production. Verify only the presence of `INTERNSHIP_AI_API_KEY`, never its value.

Review the following non-secret settings before release:

- `INTERNSHIP_AI_ENABLED`
- `INTERNSHIP_AI_PROVIDER`
- `INTERNSHIP_AI_MODEL`
- `INTERNSHIP_AI_GEMINI_ENDPOINT`
- `INTERNSHIP_AI_TIMEOUT`
- `INTERNSHIP_AI_MAX_INPUT_CHARS`
- `INTERNSHIP_AI_MAX_OUTPUT_TOKENS`
- `INTERNSHIP_AI_MAX_OUTPUT_CHARS`

## Mail readiness

Workflow mail and manual Communication Center mail use native queued Odoo mail. Phase 5B reminder cron jobs remain activity-only; Phase 5C does not send reminder email automatically.

Before allowing production mail:

1. Validate the configured sender domain, SPF, DKIM, and DMARC outside Odoo.
2. Confirm the Odoo company/user sender address is accepted by the configured outgoing server.
3. Send a non-sensitive test message to an approved test recipient.
4. Verify the message first becomes **Queued**, then **Sent by Odoo**, or inspect the failure state.
5. Confirm no real student data is used for infrastructure testing.
6. Preview every supported Communication Center category with representative test records.
7. Confirm recipient resolution: submitted/pending-review messages go to the assigned supervisor; revision/approval messages go to the owning intern.
8. Confirm preview creates no mail, chatter entry, activity, or workflow transition.
9. Confirm `Send Again` requires explicit confirmation and is not used as a routine retry mechanism.

Do not claim inbox delivery based only on Odoo's **Sent** state.

## Scheduled-action readiness

The module installs these daily scheduled actions as inactive `noupdate="1"` records:

| Scheduled action | Model | Method | Default |
| --- | --- | --- | --- |
| Internship: Pending Review Reminders | `internship.daily.entry` | `_cron_remind_pending_reviews()` | Inactive |
| Internship: Missing Entry Reminders | `internship.program` | `_cron_remind_missing_entries()` | Inactive |
| Internship: Ending Soon Reminders | `internship.program` | `_cron_remind_programs_ending_soon(days=7)` | Inactive |

Before activation:

1. Create or select an active internal user with the existing **Internship / Manager** group. Do not use the root/superuser account.
2. Confirm that user sees only the records allowed by the current ACLs and record rules.
3. Confirm supervisors and intern relationships are correct and recipient users are active.
4. Confirm the cron is daily, its next execution time is intentional, and the server timezone is understood.
5. Run the cron manually once in a controlled window.
6. Inspect Odoo logs for the `found`, `created`, `existing`, `skipped`, `failed`, and `cleaned` summary.
7. Check that only expected activities were created and no email was queued.
8. Activate one cron at a time and observe at least one complete cycle.

## Backup and restore gate

- Create a consistent PostgreSQL dump and matching filestore archive before the module upgrade.
- Verify the backup SHA-256 manifest before deployment and before any restore.
- Ensure an independently stored off-site backup exists.
- Never restore a database without its matching filestore when attachment consistency matters.
- Periodically rehearse restore on an isolated host and validate module registry, attachments, reports, mail templates, activities, and scheduled actions.

## Production smoke test

After a successful upgrade:

1. Confirm Odoo starts and the module registry loads without errors.
2. Confirm an Intern sees only owned records.
3. Confirm a Supervisor sees only assigned supervised programs and entries.
4. Confirm a Manager can open the program overview, analytics, Communication Center, and scheduled actions as intended.
5. Exercise supervised submit, revision, resubmit, and approval using designated test records.
6. Exercise independent draft completion using a designated test record.
7. Render supervised and independent PDF reports.
8. Preview a Communication Center message and confirm zero side effects.
9. Queue one approved test communication and inspect its native mail traceability.
10. Verify cron jobs remain inactive unless activation was separately approved.
11. If AI changed, perform one real-provider smoke test without exposing the prompt, entry content, or credential in logs.

## Rollback guidance

Stop and assess before any destructive action. Identify the exact known-good Git commit and its matching database/filestore backup. Follow the established restore script and deployment runbook rather than improvising commands.

Database and filestore must be restored as a matching pair. Verify SHA-256 data before restore, validate the Odoo registry and module state while production traffic is stopped, then repeat the production smoke test before reopening access.

## Known operational limitations

- Communication Center history deliberately does not grant Supervisor/Manager access to administrative `mail.mail` records. It shows conservative queued traceability; detailed delivery failures remain an administrator operation.
- Duplicate manual-send detection relies on native, module-owned `mail.message` subtypes. Administratively deleting those messages removes the duplicate marker.
- Reminder cron jobs are inactive by default and require an explicitly assigned Internship Manager execution user.
- Cron processing is bounded. Large backlogs may require multiple normal executions; do not increase batch sizes without measuring database and mail-activity load.
- External AI provider availability, quota, retention, pricing, and billing controls remain operational responsibilities outside this module.

