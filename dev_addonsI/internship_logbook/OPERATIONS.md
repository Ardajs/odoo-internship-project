# Internship Logbook Operations Guide

This guide covers module-level operations for Odoo administrators. Use a maintenance window and the project's deployment, backup, and restore procedures for production changes.

## Scheduled actions

Open **Settings → Technical → Automation → Scheduled Actions** in developer mode and search for `Internship:`.

### Activate safely

For each scheduled action:

1. Leave **Active** disabled while reviewing the record.
2. Set **Run As** to an active internal user with the existing **Internship / Manager** group. Do not select the root/superuser account.
3. Confirm the model and code exactly match the table in `PRODUCTION_READINESS.md`.
4. Keep the interval at once per day unless a reviewed operational requirement says otherwise.
5. Set an intentional next execution time, considering that Odoo stores datetimes in UTC.
6. Use **Run Manually** once during a controlled maintenance window.
7. Verify the summary log and created activities.
8. Enable **Active** only after the manual run is clean.

Activate jobs individually in this order:

1. Pending Review Reminders
2. Missing Entry Reminders
3. Ending Soon Reminders

The jobs create or clean up activities only. They must not queue reminder email or change workflow state.

### Disable safely

Clear **Active** on the scheduled action. Disabling a cron prevents future executions but does not delete existing activities. Review outstanding activities separately; do not bulk-delete unrelated activities.

### Verify execution

Check:

- **Last Execution Date** and **Next Execution Date** on the scheduled action.
- Odoo logs for one summary line per run.
- Expected activity assignee and related internship record.
- Absence of duplicate activities after a second controlled run.
- Absence of reminder `mail.mail` records caused by cron execution.

Expected log counters are `found`, `created`, `existing`, `skipped`, `failed`, and `cleaned`. Per-record warning/error logs contain record identifiers but must not contain entry descriptions, supervisor comments, email bodies, or credentials.

## Outgoing mail

### Verify configuration

In developer mode, inspect **Settings → Technical → Email → Outgoing Mail Servers**. Do not copy passwords or tokens into tickets, screenshots, shell history, or chat.

Confirm:

- The server is enabled and appropriate for the production company/domain.
- Sender filtering matches the Odoo sender address.
- TLS mode and port follow the mail provider's approved configuration.
- A designated non-sensitive test message can be queued and processed.

Do not enable outgoing mail globally as part of a module upgrade. SMTP configuration is an independent, approved operational change.

### Inspect queued and failed mail

Use **Settings → Technical → Email → Emails** with an administrator account.

- **Outgoing** means queued and not yet successfully handed off by Odoo.
- **Sent** means sent by Odoo; it does not prove inbox delivery.
- **Delivery Failed** requires review of the sanitized failure category and mail-server logs.
- **Cancelled** was not sent.

Never paste a full student email body, SMTP response containing sensitive data, or mail-server credential into an incident report.

### Safe retry

Correct the underlying configuration or recipient issue first. Retry only the intended message. In Communication Center, use **Send Again** only after confirming that a resend is appropriate; it intentionally creates another queued message.

## Communication Center

Supervisors and Managers can open **Internship Logbook → Communication** or use the **Communication** button on an assigned Daily Entry or Internship Program.

Operational checks:

1. Select only a communication category compatible with the current record state.
2. Verify the server-resolved recipient and subject.
3. Review the sanitized preview. Preview must not queue mail or change state.
4. Use **Send** once. If prior manual history exists, the wizard requires explicit **Send Again** confirmation.
5. Use the history tab for bounded, category-specific native message traceability.

The UI recipient is read-only. Recipient, template, model, record, workflow, and state are revalidated on the server immediately before queuing.

## Activities

Verify activities from the related Daily Entry or Internship Program chatter/activity panel and from the assignee's activity menu.

Check:

- Review activities belong to the assigned active supervisor.
- Revision activities belong to the owning eligible intern.
- Missing-entry and ending-soon reminders belong to an approved internal assignee.
- Portal-only users are never activity assignees.
- Completed/cancelled programs and entries that left the relevant state have no stale module reminder.
- Unrelated activities remain untouched.

## AI configuration diagnostics

The API key must be available only to the Odoo server process. A safe Linux check reports non-secret variables and only whether the key exists:

```bash
sudo systemctl show odoo --property=Environment --no-pager \
  | tr ' ' '\n' \
  | grep '^INTERNSHIP_AI_' \
  | grep -v '^INTERNSHIP_AI_API_KEY='

sudo -u odoo sh -c 'test -n "$INTERNSHIP_AI_API_KEY" && echo "INTERNSHIP_AI_API_KEY is set" || echo "INTERNSHIP_AI_API_KEY is missing"'
```

Depending on systemd hardening, the second command may not inherit the service environment. Prefer checking the protected EnvironmentFile metadata and service process configuration without printing file contents or the key value.

Do not use `cat`, `grep`, shell tracing, process dumps, or diagnostic logging that prints `/etc/odoo/odoo-ai.env` or the API key.

## Common incidents

### Scheduled action creates nothing

- Confirm it runs as an internal Internship Manager, not root and not a Supervisor-only user.
- Confirm candidate programs/entries satisfy the current workflow state and active-record conditions.
- Confirm recipient users are active, internal where required, and can read the related record.
- Review `skipped` and `failed` counters without exposing private record content.

### Duplicate reminder concern

Run the job a second time in a controlled environment. The second run should report existing activities rather than create duplicates. Check whether an administrator manually changed the activity summary or deleted the native marker.

### Communication preview fails

- Confirm the module upgrade loaded all templates and message subtypes.
- Confirm the record state matches the selected category.
- Confirm the current user can read the record.
- Confirm the intended recipient is active and has an email.
- Inspect the server traceback using record ID and error type only; do not copy the rendered body into logs.

### Mail stays queued

- Check the mail queue processor and outgoing mail server status.
- Confirm sender filtering and the recipient address.
- Review sanitized Odoo/mail-server errors.
- Do not repeatedly press **Send Again** while the original message remains queued.

### AI Assistant is not configured

- Confirm the service received the non-secret `INTERNSHIP_AI_*` values.
- Confirm the API-key variable exists without printing it.
- Confirm production does not use the `mock` provider.
- Restarting Odoo after an approved EnvironmentFile change is an operational deployment action and must follow the production runbook.

### Module upgrade fails on missing XML/data file

- Stop the deployment.
- Confirm the production Git commit matches the reviewed release.
- Confirm every manifest path exists and is tracked in Git.
- Do not create or edit the missing file directly on production.
- Correct the repository release, retest a standalone upgrade, then redeploy through the normal Git workflow.

## Routine checks

At an agreed interval verify:

- Odoo, PostgreSQL, and reverse-proxy health.
- HTTPS and certificate-renewal timer.
- Local and off-site backup timers and the latest verified backup set.
- Disk, RAM, and swap headroom.
- Recent Odoo errors and mail failures.
- Production Git working-tree cleanliness.
- Scheduled-action execution dates and failure counters.
- Activity backlog and stale activities.
- Gemini configuration presence, quota, and cost monitoring.
- Periodic restore rehearsal results.

